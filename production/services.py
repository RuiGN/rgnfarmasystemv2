from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


MONEY_SCALE = Decimal('0.0001')
QUANTITY_SCALE = Decimal('0.0001')
ZERO = Decimal('0.0000')


def _money(value):
    return Decimal(value).quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


def _ordered_balance_keys(keys):
    return sorted(set(keys))


def _lock_stock_balances(keys):
    from inventory.models import StockBalance

    ordered_keys = _ordered_balance_keys(keys)
    if not ordered_keys:
        return {}

    lookup = Q()
    for product_id, lot_id, warehouse_id, location_id, quality_status in ordered_keys:
        lookup |= Q(
            product_id=product_id,
            lot_id=lot_id,
            warehouse_id=warehouse_id,
            location_id=location_id,
            quality_status=quality_status,
        )

    balances = list(
        StockBalance.objects.select_for_update(of=('self',))
        .select_related('lot')
        .filter(lookup)
        .order_by('pk')
    )
    return {
        (
            balance.product_id,
            balance.lot_id,
            balance.warehouse_id,
            balance.location_id,
            balance.quality_status,
        ): balance
        for balance in balances
    }


def _balance_key(item, quality_status):
    return (
        item.material_id,
        item.stock_lot_id,
        item.warehouse_id,
        item.location_id,
        quality_status,
    )


class ProductionOrderOperations:
    def __init__(self, order, user):
        self.order = order
        self.user = user

    def _locked_order(self):
        from production.models import ProductionOrder

        return (
            ProductionOrder.objects.select_for_update()
            .select_related('product', 'formula', 'route', 'unit')
            .get(pk=self.order.pk)
        )

    @transaction.atomic
    def reserve_materials(self):
        from inventory.models import StockMovement, StockQualityStatus

        order = self._locked_order()
        if order.status not in {order.Status.APPROVED, order.Status.RELEASED}:
            raise ValidationError({'status': 'A ordem deve estar aprovada ou liberada.'})

        items = list(
            order.material_consumptions.select_for_update(of=('self',))
            .select_related(
                'material',
                'stock_lot',
                'warehouse',
                'location',
                'unit',
                'reservation_movement',
            )
            .order_by('pk')
        )
        reservations_by_balance = defaultdict(lambda: ZERO)
        balances = {}
        movements = []
        pending_items = []

        for item in items:
            if item.reservation_movement_id:
                self._validate_movement_direction(item.reservation_movement)
            item.full_clean()
            if item.reservation_movement_id:
                if item.reserved_quantity != item.planned_quantity:
                    raise ValidationError(
                        {
                            'materials': (
                                f'A reserva vinculada de {item.material} deve corresponder '
                                'à quantidade planejada.'
                            )
                        }
                    )
                movements.append(item.reservation_movement)
                continue
            if item.reserved_quantity != ZERO:
                raise ValidationError(
                    {
                        'materials': (
                            f'A quantidade reservada de {item.material} exige movimento vinculado.'
                        )
                    }
                )
            if not all((item.stock_lot_id, item.warehouse_id, item.location_id)):
                raise ValidationError({'materials': f'Alocação incompleta para {item.material}.'})
            if item.planned_quantity <= ZERO:
                raise ValidationError(
                    {'materials': f'Informe quantidade planejada positiva para {item.material}.'}
                )
            pending_items.append(item)

        locked_balances = _lock_stock_balances(
            _balance_key(item, StockQualityStatus.APPROVED) for item in pending_items
        )
        for item in pending_items:
            key = _balance_key(item, StockQualityStatus.APPROVED)
            balance = locked_balances.get(key)
            if balance is None:
                raise ValidationError(
                    {'quantity': ('Saldo aprovado não encontrado para o endereço e lote alocados.')}
                )
            if balance.unit_id != item.unit_id:
                raise ValidationError(
                    {'unit': 'A unidade da alocação deve corresponder à unidade do saldo.'}
                )
            balances[balance.pk] = balance
            reservations_by_balance[balance.pk] += item.planned_quantity

        for balance_id, quantity in reservations_by_balance.items():
            balance = balances[balance_id]
            StockMovement._validate_issue(balance, quantity)

        changed = False
        for item in items:
            if item.reservation_movement_id:
                continue
            movement = StockMovement.reserve_stock(
                product=item.material,
                lot=item.stock_lot,
                warehouse=item.warehouse,
                location=item.location,
                quantity=item.planned_quantity,
                unit=item.unit,
                reason=f'Reserva para {order.order_number}',
                quality_status=StockQualityStatus.APPROVED,
            )
            movement.source_production_order = order
            movement.source_material_consumption = item
            movement.created_by = self.user
            self._validate_movement_direction(movement)
            movement.full_clean()
            movement.save()

            item.reserved_quantity = movement.quantity
            item.reservation_movement = movement
            item.full_clean()
            item.save()
            movements.append(movement)
            changed = True

        if changed:
            self._audit(
                order,
                'production.materials.reserved',
                {'movement_ids': [movement.pk for movement in movements]},
            )
        return movements

    @transaction.atomic
    def _release_reservations_for_cancellation(self):
        from inventory.models import StockMovement, StockQualityStatus

        order = self._locked_order()
        order._require_status(order.CANCELLABLE_STATUSES)
        items = list(
            order.material_consumptions.select_for_update(of=('self',))
            .select_related(
                'reservation_movement', 'issue_movement', 'loss_movement', 'return_movement'
            )
            .order_by('pk')
        )
        balances = _lock_stock_balances(
            _balance_key(item, StockQualityStatus.APPROVED)
            for item in items
            if item.reservation_movement_id
        )
        movements = []
        for item in items:
            if not item.reservation_movement_id:
                if item.reserved_quantity != ZERO:
                    raise ValidationError({'materials': 'Reserva sem movimento vinculado.'})
                continue
            errors = {}
            for field, kind, quantity_field in (
                (
                    'reservation_movement',
                    StockMovement.MovementType.RESERVATION,
                    'reserved_quantity',
                ),
                ('issue_movement', StockMovement.MovementType.ISSUE, 'issued_quantity'),
                ('loss_movement', StockMovement.MovementType.LOSS, 'loss_quantity'),
                (
                    'return_movement',
                    StockMovement.MovementType.RELEASE_RESERVATION,
                    'returned_quantity',
                ),
            ):
                item._validate_stock_movement(errors, field, kind, 'from', quantity_field)
            if errors:
                raise ValidationError(errors)
            released = sum(
                (
                    movement.quantity
                    for movement in (item.issue_movement, item.loss_movement, item.return_movement)
                    if movement is not None
                ),
                ZERO,
            )
            outstanding = item.reserved_quantity - released
            if outstanding < ZERO:
                raise ValidationError({'materials': 'Movimentos excedem a reserva original.'})
            if outstanding == ZERO:
                continue
            if item.return_movement_id:
                raise ValidationError(
                    {'materials': 'Liberação parcial inconsistente exige reconciliação.'}
                )
            balance = balances.get(_balance_key(item, StockQualityStatus.APPROVED))
            if balance is None or balance.unit_id != item.unit_id:
                raise ValidationError(
                    {'materials': 'Saldo da reserva ausente ou unidade incompatível.'}
                )
            item.returned_quantity = outstanding
            movement = StockMovement.release_reserved_stock(consumption=item, user=self.user)
            movement.related_movement = item.reservation_movement
            movement.reason = f'Liberação por cancelamento de {order.order_number}'
            movement.save(update_fields=['related_movement', 'reason', 'updated_at'])
            item.return_movement = movement
            item.save(update_fields=['returned_quantity', 'return_movement', 'updated_at'])
            movements.append(movement)
        return movements

    @transaction.atomic
    def issue_materials(self):
        from inventory.models import StockMovement, StockQualityStatus

        order = self._locked_order()
        if order.status != order.Status.IN_PROGRESS:
            raise ValidationError({'status': 'A ordem deve estar em execução.'})

        items = list(
            order.material_consumptions.select_for_update(of=('self',))
            .select_related(
                'material',
                'stock_lot',
                'warehouse',
                'location',
                'unit',
                'reservation_movement',
                'issue_movement',
                'loss_movement',
                'return_movement',
            )
            .order_by('pk')
        )
        demand_by_balance = defaultdict(lambda: ZERO)
        balances = {}
        movements = []
        pending_by_item = {}

        for item in items:
            for linked_movement in (
                item.reservation_movement,
                item.issue_movement,
                item.loss_movement,
                item.return_movement,
            ):
                if linked_movement is not None:
                    self._validate_movement_direction(linked_movement)
            item.full_clean()
            if item.planned_quantity > ZERO and not item.reservation_movement_id:
                raise ValidationError(
                    {'materials': f'Reserve {item.material} antes de efetuar a baixa.'}
                )
            reconciled = (
                item.actual_quantity + item.loss_quantity + item.returned_quantity
            ).quantize(QUANTITY_SCALE)
            if reconciled != item.reserved_quantity:
                raise ValidationError(
                    {
                        'materials': (
                            f'O consumo, a perda e a devolução de {item.material} '
                            'devem reconciliar a quantidade reservada.'
                        )
                    }
                )
            if item.issue_movement_id:
                if item.actual_quantity <= ZERO:
                    raise ValidationError(
                        {'materials': f'A baixa vinculada de {item.material} deve ser positiva.'}
                    )
                if item.issued_quantity != item.actual_quantity:
                    raise ValidationError(
                        {
                            'materials': (
                                f'A quantidade baixada de {item.material} deve corresponder '
                                'ao consumo real.'
                            )
                        }
                    )
            elif item.issued_quantity != ZERO:
                raise ValidationError(
                    {
                        'materials': (
                            f'A quantidade baixada de {item.material} exige movimento vinculado.'
                        )
                    }
                )

            pending_quantity = ZERO
            if item.actual_quantity > ZERO and not item.issue_movement_id:
                pending_quantity += item.actual_quantity
            if item.loss_quantity > ZERO and not item.loss_movement_id:
                pending_quantity += item.loss_quantity
            if item.returned_quantity > ZERO and not item.return_movement_id:
                pending_quantity += item.returned_quantity
            if pending_quantity:
                pending_by_item[item.pk] = pending_quantity

        locked_balances = _lock_stock_balances(
            _balance_key(item, StockQualityStatus.APPROVED)
            for item in items
            if item.pk in pending_by_item
        )
        for item in items:
            item_pending_quantity = pending_by_item.get(item.pk)
            if item_pending_quantity is None:
                continue
            key = _balance_key(item, StockQualityStatus.APPROVED)
            balance = locked_balances.get(key)
            if balance is None:
                raise ValidationError(
                    {'quantity': 'Saldo aprovado não encontrado para a baixa de produção.'}
                )
            if balance.unit_id != item.unit_id:
                raise ValidationError(
                    {'unit': 'A unidade do consumo deve corresponder à unidade do saldo.'}
                )
            balances[balance.pk] = balance
            demand_by_balance[balance.pk] += item_pending_quantity

        for balance_id, quantity in demand_by_balance.items():
            balance = balances[balance_id]
            if balance.reserved_quantity < quantity:
                raise ValidationError(
                    {'reserved_quantity': 'A reserva não cobre a reconciliação informada.'}
                )
            StockMovement._validate_issue(
                balance,
                quantity,
                allow_reserved_consumption=True,
            )

        changed = False
        for item in items:
            item_changed = False
            if item.actual_quantity > ZERO and not item.issue_movement_id:
                item.issue_movement = StockMovement.issue_reserved_stock(
                    consumption=item,
                    user=self.user,
                )
                self._validate_movement_direction(item.issue_movement)
                item.issue_movement.full_clean()
                item.issued_quantity = item.issue_movement.quantity
                changed = True
                item_changed = True
            if item.loss_quantity > ZERO and not item.loss_movement_id:
                item.loss_movement = StockMovement.record_reserved_loss(
                    consumption=item,
                    user=self.user,
                )
                self._validate_movement_direction(item.loss_movement)
                item.loss_movement.full_clean()
                changed = True
                item_changed = True
            if item.returned_quantity > ZERO and not item.return_movement_id:
                item.return_movement = StockMovement.release_reserved_stock(
                    consumption=item,
                    user=self.user,
                )
                self._validate_movement_direction(item.return_movement)
                item.return_movement.full_clean()
                changed = True
                item_changed = True
            if item_changed:
                item.full_clean()
                item.save()
            movements.extend(
                movement
                for movement in (
                    item.issue_movement,
                    item.loss_movement,
                    item.return_movement,
                )
                if movement is not None
            )

        if changed:
            self._audit(
                order,
                'production.materials.issued',
                {'movement_ids': [movement.pk for movement in movements]},
            )
        return movements

    @transaction.atomic
    def receive_outputs(self):
        from inventory.models import (
            StockLotGenealogy,
            StockMovement,
            StockQualityStatus,
        )

        order = self._locked_order()
        if order.status != order.Status.COMPLETED:
            raise ValidationError({'status': 'A ordem deve estar concluída.'})

        consumptions = list(
            order.material_consumptions.select_for_update(of=('self',))
            .select_related(
                'material',
                'stock_lot',
                'warehouse',
                'location',
                'unit',
                'reservation_movement',
                'issue_movement',
                'loss_movement',
                'return_movement',
            )
            .order_by('pk')
        )
        genealogy_inputs = {}
        for item in consumptions:
            for linked_movement in (
                item.reservation_movement,
                item.issue_movement,
                item.loss_movement,
                item.return_movement,
            ):
                if linked_movement is not None:
                    self._validate_movement_direction(linked_movement)
            item.full_clean()
            if item.actual_quantity > ZERO and not item.issue_movement_id:
                raise ValidationError(
                    {'materials': (f'O consumo real de {item.material} exige movimento de baixa.')}
                )
            if not item.issue_movement_id:
                continue
            if item.issued_quantity != item.actual_quantity:
                raise ValidationError(
                    {
                        'materials': (
                            f'A baixa de {item.material} deve corresponder ao consumo real.'
                        )
                    }
                )
            current = genealogy_inputs.get(item.stock_lot_id)
            if current is None:
                genealogy_inputs[item.stock_lot_id] = {
                    'quantity': item.actual_quantity,
                    'unit': item.unit,
                }
            elif current['unit'].pk != item.unit_id:
                raise ValidationError(
                    {
                        'genealogy': (
                            'Consumos do mesmo lote usam unidades incompatíveis e não há '
                            'conversão configurada.'
                        )
                    }
                )
            else:
                current['quantity'] = (current['quantity'] + item.actual_quantity).quantize(
                    QUANTITY_SCALE
                )

        outputs = list(
            order.outputs.select_for_update(of=('self',))
            .select_related(
                'product',
                'unit',
                'warehouse',
                'location',
                'stock_lot',
                'stock_movement',
                'received_by',
            )
            .order_by('pk')
        )
        for output in outputs:
            if output.status not in {
                output.Status.PENDING,
                output.Status.RECEIVED,
            }:
                raise ValidationError({'status': 'Status de resultado inválido.'})
            if output.product_id != order.product_id:
                raise ValidationError(
                    {'product': 'O produto do resultado deve corresponder à ordem.'}
                )
            if output.unit_id != order.unit_id:
                raise ValidationError(
                    {'unit': 'A unidade do resultado deve corresponder à unidade da ordem.'}
                )
            if output.stock_movement_id:
                self._validate_movement_direction(
                    output.stock_movement,
                    incoming=True,
                )
            output.full_clean()

        if outputs:
            if not genealogy_inputs:
                raise ValidationError(
                    {
                        'materials': (
                            'O recebimento exige ao menos um lote de componente efetivamente '
                            'baixado para registrar a genealogia.'
                        )
                    }
                )
            expected_component_ids = set(
                order.formula.components.filter(is_active=True).values_list('pk', flat=True)
            )
            issued_component_ids = {
                item.component_id
                for item in consumptions
                if (
                    item.issue_movement_id
                    and item.actual_quantity > ZERO
                    and item.component_id in expected_component_ids
                )
            }
            if expected_component_ids != issued_component_ids:
                raise ValidationError(
                    {
                        'materials': (
                            'Os componentes efetivamente baixados devem corresponder aos '
                            'componentes ativos da fórmula da ordem.'
                        )
                    }
                )

        pending_outputs = sorted(
            (output for output in outputs if output.status == output.Status.PENDING),
            key=lambda output: (output.product_id, output.lot_number, output.sublot_number),
        )
        lots = [StockMovement._production_output_lot(output) for output in pending_outputs]
        StockMovement._lock_receiving_balances(
            (
                output.product,
                lot,
                output.warehouse,
                output.location,
                StockQualityStatus.QUARANTINE,
                output.unit,
            )
            for output, lot in zip(pending_outputs, lots)
        )
        changed = False
        for output in outputs:
            if output.status == output.Status.PENDING:
                movement = StockMovement.receive_production_output(
                    output=output,
                    user=self.user,
                )
                self._validate_movement_direction(movement, incoming=True)
                movement.full_clean()
                output.stock_lot = movement.lot
                output.stock_movement = movement
                output.status = output.Status.RECEIVED
                output.received_by = self.user
                output.received_at = timezone.now()
                output.full_clean()
                output.save()
                changed = True

            for input_lot_id, genealogy_data in genealogy_inputs.items():
                lookup = {
                    'input_lot_id': input_lot_id,
                    'output_lot': output.stock_lot,
                    'production_order': order,
                    'relation_type': (StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION),
                }
                genealogy = StockLotGenealogy.objects.select_for_update().filter(**lookup).first()
                if genealogy is None:
                    genealogy = StockLotGenealogy(
                        **lookup,
                        quantity=genealogy_data['quantity'],
                        unit=genealogy_data['unit'],
                        document_reference=order.order_number,
                    )
                    genealogy.full_clean()
                    genealogy.save()
                    changed = True
                elif (
                    genealogy.quantity != genealogy_data['quantity']
                    or genealogy.unit_id != genealogy_data['unit'].pk
                ):
                    raise ValidationError(
                        {
                            'genealogy': (
                                'A genealogia existente não corresponde ao consumo '
                                'reconciliado da ordem.'
                            )
                        }
                    )

            if output.stock_lot.quality_status != StockQualityStatus.QUARANTINE:
                raise ValidationError(
                    {'stock_lot': 'O produto acabado deve permanecer em quarentena.'}
                )

        if changed:
            self._audit(
                order,
                'production.outputs.received',
                {'output_ids': [output.pk for output in outputs]},
            )
        return outputs

    @transaction.atomic
    def calculate_cost(self, *, period_start, period_end):
        from costing.models import MonthlyCostClosing, ProductionCostCapture, StandardCost

        order = self._locked_order()
        if order.status not in {order.Status.COMPLETED, order.Status.CLOSED}:
            raise ValidationError(
                {'status': 'A ordem deve estar concluída ou encerrada para calcular custos.'}
            )
        if period_start is None or period_end is None or period_end < period_start:
            raise ValidationError(
                {'period_end': 'O fim do período não pode ser anterior ao início.'}
            )
        if (period_start.year, period_start.month) != (period_end.year, period_end.month):
            raise ValidationError(
                {'period_end': 'A captura de custo deve permanecer no mesmo mês contábil.'}
            )

        MonthlyCostClosing.objects.get_or_create(
            period_year=period_start.year,
            period_month=period_start.month,
        )
        closing = MonthlyCostClosing.objects.select_for_update().get(
            period_year=period_start.year,
            period_month=period_start.month,
        )
        if closing.status == MonthlyCostClosing.Status.CLOSED:
            raise ValidationError({'period_start': 'O período de custos está fechado.'})

        planned_cost = ZERO
        material_cost = ZERO
        loss_cost = ZERO
        items = list(
            order.material_consumptions.select_for_update(of=('self',))
            .select_related('material', 'unit')
            .order_by('pk')
        )
        standard_by_product_unit = {}
        standard_candidates = (
            StandardCost.objects.filter(
                product_id__in={item.material_id for item in items},
                unit_id__in={item.unit_id for item in items},
                status=StandardCost.Status.APPROVED,
                approved_at__isnull=False,
                effective_from__lte=period_end,
            )
            .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=period_end))
            .order_by(
                'product_id',
                'unit_id',
                '-effective_from',
                '-approved_at',
                '-created_at',
                '-pk',
            )
        )
        for standard in standard_candidates:
            standard_by_product_unit.setdefault(
                (standard.product_id, standard.unit_id),
                standard,
            )

        for item in items:
            item.full_clean()
            standard = standard_by_product_unit.get((item.material_id, item.unit_id))
            if standard is None or standard.standard_quantity <= ZERO:
                raise ValidationError(
                    {
                        'standard_cost': (
                            f'Custo padrão aprovado, vigente e compatível ausente para '
                            f'{item.material}.'
                        )
                    }
                )
            unit_cost = standard.total_standard_cost / standard.standard_quantity
            planned_cost += item.planned_quantity * unit_cost
            material_cost += item.actual_quantity * unit_cost
            loss_cost += item.loss_quantity * unit_cost

        labor_cost = ZERO
        for entry in order.labor_entries.select_for_update().all():
            entry.full_clean()
            labor_cost += (entry.duration_minutes / Decimal('60')) * entry.hourly_cost

        machine_cost = ZERO
        for operation in order.operation_executions.select_for_update().all():
            operation.full_clean()
            machine_cost += (
                operation.actual_minutes / Decimal('60')
            ) * operation.machine_hourly_cost

        capture = (
            ProductionCostCapture.objects.select_for_update()
            .filter(
                production_order=order,
                period_start=period_start,
                period_end=period_end,
            )
            .first()
        )
        created = capture is None
        if capture is None:
            capture = ProductionCostCapture(
                production_order=order,
                period_start=period_start,
                period_end=period_end,
            )

        calculated_values = {
            'planned_cost': _money(planned_cost),
            'actual_material_cost': _money(material_cost),
            'actual_loss_cost': _money(loss_cost),
            'actual_labor_cost': _money(labor_cost),
            'actual_machine_cost': _money(machine_cost),
        }
        previous_values = {
            field_name: getattr(capture, field_name)
            for field_name in (
                *calculated_values,
                'total_actual_cost',
                'variance_amount',
            )
        }
        for field_name, value in calculated_values.items():
            setattr(capture, field_name, value)
        capture.calculate_actuals(save=False)
        capture.full_clean()
        changed = created or any(
            previous_values[field_name] != getattr(capture, field_name)
            for field_name in previous_values
        )
        if changed:
            capture.save()
            self._audit(
                order,
                'production.cost.calculated',
                {'capture_id': capture.pk},
            )
        return capture

    @staticmethod
    def _validate_movement_direction(movement, *, incoming=False):
        if incoming:
            required_ids = (
                movement.to_warehouse_id,
                movement.to_location_id,
            )
            forbidden_ids = (
                movement.from_warehouse_id,
                movement.from_location_id,
            )
        else:
            required_ids = (
                movement.from_warehouse_id,
                movement.from_location_id,
            )
            forbidden_ids = (
                movement.to_warehouse_id,
                movement.to_location_id,
            )
        if not all(required_ids) or any(forbidden_ids):
            direction = 'entrada' if incoming else 'saída'
            raise ValidationError(
                {
                    'movement': (
                        f'O movimento deve ser unidirecional de {direction}, com apenas '
                        'o endereço correspondente preenchido.'
                    )
                }
            )

    def _audit(self, order, action, safe_context):
        from governance.models import GovernanceAuditLog

        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module='production',
            action=action,
            target_model='ProductionOrder',
            target_record_id=order.pk,
            user=self.user,
            message=f'Ação operacional executada na ordem {order.order_number}.',
            safe_context=safe_context,
        )
