from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import IdentifierSpec, sequence_code
from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula
from masters.models import Product, UnitOfMeasure


def _persisted_values(instance):
    if instance.pk is None or instance._state.adding:
        return None

    field_names = [
        field.attname
        for field in instance._meta.concrete_fields
        if not field.primary_key and field.name not in {'created_at', 'updated_at'}
    ]
    return type(instance).objects.filter(pk=instance.pk).values(*field_names).first()


def _has_persisted_changes(instance, persisted):
    return any(getattr(instance, field_name) != value for field_name, value in persisted.items())


class ProductionOrder(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (
        IdentifierSpec('order_number', 'OP'),
        IdentifierSpec('batch_number', 'LOT'),
    )

    class Priority(models.TextChoices):
        LOW = 'low', 'Baixa'
        NORMAL = 'normal', 'Normal'
        HIGH = 'high', 'Alta'
        URGENT = 'urgent', 'Urgente'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovada'
        RELEASED = 'released', 'Liberada'
        IN_PROGRESS = 'in_progress', 'Em execução'
        PAUSED = 'paused', 'Pausada'
        COMPLETED = 'completed', 'Concluída'
        CANCELLED = 'cancelled', 'Cancelada'
        CLOSED = 'closed', 'Encerrada'

    CANCELLABLE_STATUSES = (
        Status.DRAFT,
        Status.APPROVED,
        Status.RELEASED,
        Status.IN_PROGRESS,
        Status.PAUSED,
    )

    order_number = models.CharField('ordem', max_length=80, blank=True)
    batch_number = models.CharField('lote', max_length=80, blank=True)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='production_orders',
        verbose_name='produto',
    )
    formula = models.ForeignKey(
        MasterFormula,
        on_delete=models.PROTECT,
        related_name='production_orders',
        verbose_name='fórmula',
    )
    route = models.ForeignKey(
        ManufacturingRoute,
        on_delete=models.PROTECT,
        related_name='production_orders',
        verbose_name='roteiro',
    )
    planned_quantity = models.DecimalField('quantidade planejada', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='production_orders',
        verbose_name='unidade',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    priority = models.CharField(
        'prioridade', max_length=16, choices=Priority.choices, default=Priority.NORMAL
    )
    scheduled_start = models.DateField('início previsto', null=True, blank=True)
    scheduled_end = models.DateField('fim previsto', null=True, blank=True)
    actual_start = models.DateTimeField('início real', null=True, blank=True)
    actual_end = models.DateTimeField('fim real', null=True, blank=True)
    production_line = models.CharField('linha', max_length=120, blank=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='responsible_production_orders',
        null=True,
        blank=True,
        verbose_name='responsável',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_production_orders',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='released_production_orders',
        null=True,
        blank=True,
        verbose_name='liberada por',
    )
    released_at = models.DateTimeField('liberada em', null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_production_orders',
        null=True,
        blank=True,
        verbose_name='iniciada por',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_production_orders',
        null=True,
        blank=True,
        verbose_name='concluída por',
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='cancelled_production_orders',
        null=True,
        blank=True,
        verbose_name='cancelada por',
    )
    cancelled_at = models.DateTimeField('cancelada em', null=True, blank=True)
    cancel_reason = models.TextField('justificativa de cancelamento', blank=True)
    actual_yield_quantity = models.DecimalField(
        'rendimento real',
        max_digits=14,
        decimal_places=4,
        null=True,
        blank=True,
    )
    real_loss_quantity = models.DecimalField(
        'perda real',
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
    )
    rework_quantity = models.DecimalField(
        'retrabalho',
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        permissions = [
            ('view_production_maps', 'Pode consultar mapas da ordem de produção'),
        ]
        constraints = [
            models.UniqueConstraint(fields=['order_number'], name='unique_production_order_number'),
            models.UniqueConstraint(fields=['batch_number'], name='unique_production_batch_number'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['order_number']),
            models.Index(fields=['batch_number']),
        ]
        verbose_name = 'ordem de produção'
        verbose_name_plural = 'ordens de produção'

    @transaction.atomic
    def save(self, *args, **kwargs):
        cancellation = kwargs.pop('_cancellation', False)
        persisted = (
            type(self).objects.select_for_update().filter(pk=self.pk).first() if self.pk else None
        )
        if not cancellation and (
            (
                self.status == self.Status.CANCELLED
                and (persisted is None or persisted.status != self.Status.CANCELLED)
            )
            or (
                persisted is not None
                and persisted.status == self.Status.CANCELLED
                and any(
                    getattr(self, name) != getattr(persisted, name)
                    for name in ('status', 'cancelled_by_id', 'cancelled_at', 'cancel_reason')
                )
            )
        ):
            raise ValidationError({'status': 'Use cancel para cancelar e liberar reservas.'})
        if not self.order_number:
            self.order_number = self.generate_order_number()
        if not self.batch_number:
            self.batch_number = self.generate_batch_number()
        super().save(*args, **kwargs)

    def generate_order_number(self):
        return sequence_code(ProductionOrder, 'order_number', 'OP')

    def generate_batch_number(self):
        return sequence_code(ProductionOrder, 'batch_number', 'LOT')

    def clean(self):
        super().clean()
        errors = {}

        if self.planned_quantity <= 0:
            errors['planned_quantity'] = 'A quantidade planejada deve ser maior que zero.'
        if (
            self.scheduled_start
            and self.scheduled_end
            and self.scheduled_end < self.scheduled_start
        ):
            errors['scheduled_end'] = (
                'A data fim prevista não pode ser anterior ao início previsto.'
            )
        if self.formula and self.formula.product_id != self.product_id:
            errors['formula'] = 'A fórmula deve pertencer ao produto da ordem.'
        if self.route and self.route.product_id != self.product_id:
            errors['route'] = 'O roteiro deve pertencer ao produto da ordem.'
        if (
            self.route
            and self.formula
            and self.route.formula_id
            and self.route.formula_id != self.formula_id
        ):
            errors['route'] = 'O roteiro deve estar vinculado à fórmula da ordem.'
        if self.status in {
            self.Status.RELEASED,
            self.Status.IN_PROGRESS,
            self.Status.PAUSED,
            self.Status.COMPLETED,
            self.Status.CLOSED,
        }:
            errors.update(self._release_errors())
        if self.actual_yield_quantity is not None and self.actual_yield_quantity < 0:
            errors['actual_yield_quantity'] = 'O rendimento real não pode ser negativo.'
        if self.real_loss_quantity < 0:
            errors['real_loss_quantity'] = 'A perda real não pode ser negativa.'
        if self.rework_quantity < 0:
            errors['rework_quantity'] = 'O retrabalho não pode ser negativo.'
        if errors:
            raise ValidationError(errors)

    def _release_errors(self):
        errors = {}
        if not self.product.is_operationally_available:
            errors['product'] = 'A liberação exige produto aprovado e operacionalmente disponível.'
        if not self.formula.is_released:
            errors['formula'] = 'A liberação exige fórmula aprovada e vigente.'
        if not self.route.is_released:
            errors['route'] = 'A liberação exige roteiro aprovado e vigente.'
        return errors

        return None

    def _require_status(self, allowed_statuses):
        if self.status not in allowed_statuses:
            allowed_labels = ', '.join(allowed_statuses)
            raise ValidationError(
                {'status': f'Transição inválida. Status esperado: {allowed_labels}.'}
            )

    @staticmethod
    def _require_lifecycle_actor(user):
        if (
            user is None
            or not getattr(user, 'is_authenticated', False)
            or getattr(user, 'pk', None) is None
        ):
            raise ValidationError(
                {'user': 'Informe um ator autenticado e persistido para a transição.'}
            )
        return user

    def _locked_lifecycle_order(self):
        if self.pk is None:
            raise ValidationError(
                {'status': 'A ordem deve estar persistida antes de mudar de estado.'}
            )
        return (
            type(self)
            .objects.select_for_update()
            .select_related('product', 'formula', 'route', 'unit')
            .get(pk=self.pk)
        )

    def _sync_lifecycle_state(self, locked_order):
        self.__dict__.update(locked_order.__dict__)

    def _record_lifecycle_audit(
        self,
        *,
        action,
        message,
        previous_status,
        user,
        safe_context=None,
    ):
        from governance.models import GovernanceAuditLog

        context = {
            'from_status': previous_status,
            'to_status': self.status,
        }
        context.update(safe_context or {})
        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module='production',
            action=action,
            target_model='ProductionOrder',
            target_record_id=str(self.pk),
            user=user,
            message=message,
            safe_context=context,
        )

    @transaction.atomic
    def approve(self, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.DRAFT})
        order.status = order.Status.APPROVED
        order.approved_by = user
        order.approved_at = timezone.now()
        order.full_clean()
        order.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        order._record_lifecycle_audit(
            action='production.order.approved',
            message='Ordem de produção aprovada.',
            previous_status=previous_status,
            user=user,
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def release(self, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.APPROVED})
        errors = order._release_errors()
        if errors:
            raise ValidationError(errors)
        order.status = order.Status.RELEASED
        order.released_by = user
        order.released_at = timezone.now()
        order.full_clean()
        order.save(update_fields=['status', 'released_by', 'released_at', 'updated_at'])
        order._record_lifecycle_audit(
            action='production.order.released',
            message='Ordem de produção liberada.',
            previous_status=previous_status,
            user=user,
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def start(self, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.RELEASED})
        order.status = order.Status.IN_PROGRESS
        order.started_by = user
        if order.actual_start is None:
            order.actual_start = timezone.now()
        order.full_clean()
        order.save(update_fields=['status', 'started_by', 'actual_start', 'updated_at'])
        order._record_lifecycle_audit(
            action='production.order.started',
            message='Execução da ordem de produção iniciada.',
            previous_status=previous_status,
            user=user,
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def pause(self, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.IN_PROGRESS})
        order.status = order.Status.PAUSED
        order.save(update_fields=['status', 'updated_at'])
        order._record_lifecycle_audit(
            action='production.order.paused',
            message='Execução da ordem de produção pausada.',
            previous_status=previous_status,
            user=user,
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def resume(self, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.PAUSED})
        order.status = order.Status.IN_PROGRESS
        order.save(update_fields=['status', 'updated_at'])
        order._record_lifecycle_audit(
            action='production.order.resumed',
            message='Execução da ordem de produção retomada.',
            previous_status=previous_status,
            user=user,
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def complete(self, actual_yield_quantity, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        previous_status = order.status
        order._require_status({order.Status.IN_PROGRESS})
        try:
            actual_yield_quantity = Decimal(str(actual_yield_quantity))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise ValidationError({'actual_yield_quantity': 'Informe um número válido.'}) from exc
        order.status = order.Status.COMPLETED
        order.actual_yield_quantity = actual_yield_quantity
        order.completed_by = user
        order.actual_end = timezone.now()
        order.full_clean()
        order.save(
            update_fields=[
                'status',
                'actual_yield_quantity',
                'completed_by',
                'actual_end',
                'updated_at',
            ]
        )
        order._record_lifecycle_audit(
            action='production.order.completed',
            message='Ordem de produção concluída.',
            previous_status=previous_status,
            user=user,
            safe_context={'actual_yield_quantity': str(actual_yield_quantity)},
        )
        self._sync_lifecycle_state(order)

    @transaction.atomic
    def cancel(self, reason, user):
        user = self._require_lifecycle_actor(user)
        order = self._locked_lifecycle_order()
        if order.status == order.Status.CANCELLED:
            if order.cancelled_by_id != user.pk:
                raise ValidationError({'status': 'A ordem já foi cancelada por outro ator.'})
            self._sync_lifecycle_state(order)
            return
        order._require_status(order.CANCELLABLE_STATUSES)
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe a justificativa do cancelamento.'})
        from production.services import ProductionOrderOperations

        movements = ProductionOrderOperations(order, user)._release_reservations_for_cancellation()
        previous_status = order.status
        order.status = order.Status.CANCELLED
        order.cancel_reason = reason
        order.cancelled_by = user
        order.cancelled_at = timezone.now()
        order.save(
            update_fields=['status', 'cancel_reason', 'cancelled_by', 'cancelled_at', 'updated_at'],
            _cancellation=True,
        )
        order._record_lifecycle_audit(
            action='production.order.cancelled',
            message='Ordem de produção cancelada.',
            previous_status=previous_status,
            user=user,
            safe_context={
                'reason_recorded': True,
                **({'release_movement_ids': [m.pk for m in movements]} if movements else {}),
            },
        )
        self._sync_lifecycle_state(order)

    def __str__(self):
        return f'{self.order_number} - {self.product.code}'


class MaterialConsumption(SingleInstanceModel):
    @classmethod
    def from_db(cls, db, field_names, values):
        instance = super().from_db(db, field_names, values)
        instance._loaded_values = dict(zip(field_names, values))
        return instance

    @transaction.atomic
    def save(self, *args, **kwargs):
        # Never acquire an allocation lock before its parent order.
        persisted_order_id = (
            type(self).objects.filter(pk=self.pk).values_list('order_id', flat=True).first()
            if self.pk
            else None
        )
        if persisted_order_id is not None and persisted_order_id != self.order_id:
            raise ValidationError({'order': 'A ordem de uma alocação é imutável.'})
        order = ProductionOrder.objects.select_for_update().get(pk=self.order_id)
        if order.status in {order.Status.CANCELLED, order.Status.COMPLETED, order.Status.CLOSED}:
            raise ValidationError({'order': 'A ordem terminal não permite alterar alocações.'})
        self.order = order
        if persisted_order_id is None:
            result = super().save(*args, **kwargs)
        else:
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            requested = kwargs.get('update_fields')
            loaded = getattr(self, '_loaded_values', {})
            fields = [
                field
                for field in self._meta.concrete_fields
                if not field.primary_key and field.name not in {'created_at', 'updated_at'}
            ]
            if requested is not None:
                changed = [
                    field
                    for field in fields
                    if field.name in requested or field.attname in requested
                ]
            else:
                changed = [
                    field
                    for field in fields
                    if getattr(self, field.attname)
                    != loaded.get(field.attname, getattr(locked, field.attname))
                ]
            for field in changed:
                setattr(locked, field.attname, getattr(self, field.attname))
            locked.order = order
            locked.full_clean()
            result = super(MaterialConsumption, locked).save(
                *args,
                **{**kwargs, 'update_fields': [field.name for field in changed] + ['updated_at']},
            )
            self.__dict__.update(locked.__dict__)
        self._loaded_values = {
            field.attname: getattr(self, field.attname) for field in self._meta.concrete_fields
        }
        return result

    class QualityStatus(models.TextChoices):
        QUARANTINE = 'quarantine', 'Quarentena'
        APPROVED = 'approved', 'Aprovado'
        REJECTED = 'rejected', 'Reprovado'
        BLOCKED = 'blocked', 'Bloqueado'
        RESERVED = 'reserved', 'Reservado'
        IN_ANALYSIS = 'in_analysis', 'Em análise'
        RETURNED = 'returned', 'Devolvido'
        SEGREGATED = 'segregated', 'Segregado'
        EXPIRED = 'expired', 'Vencido'

    order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.CASCADE,
        related_name='material_consumptions',
        verbose_name='ordem',
    )
    component = models.ForeignKey(
        FormulaComponent,
        on_delete=models.PROTECT,
        related_name='material_consumptions',
        null=True,
        blank=True,
        verbose_name='componente',
    )
    material = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='material_consumptions',
        verbose_name='material',
    )
    planned_quantity = models.DecimalField('quantidade planejada', max_digits=14, decimal_places=4)
    actual_quantity = models.DecimalField(
        'quantidade real', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    loss_quantity = models.DecimalField(
        'perda', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    returned_quantity = models.DecimalField(
        'devolução', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='production_material_allocations',
        null=True,
        blank=True,
        verbose_name='lote de estoque',
    )
    warehouse = models.ForeignKey(
        'masters.Warehouse',
        on_delete=models.PROTECT,
        related_name='production_material_allocations',
        null=True,
        blank=True,
        verbose_name='almoxarifado',
    )
    location = models.ForeignKey(
        'masters.StorageLocation',
        on_delete=models.PROTECT,
        related_name='production_material_allocations',
        null=True,
        blank=True,
        verbose_name='localização',
    )
    reserved_quantity = models.DecimalField(
        'quantidade reservada', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    issued_quantity = models.DecimalField(
        'quantidade baixada', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    reservation_movement = models.OneToOneField(
        'inventory.StockMovement',
        on_delete=models.PROTECT,
        related_name='reserved_material_consumption',
        null=True,
        blank=True,
        verbose_name='movimento de reserva',
    )
    issue_movement = models.OneToOneField(
        'inventory.StockMovement',
        on_delete=models.PROTECT,
        related_name='issued_material_consumption',
        null=True,
        blank=True,
        verbose_name='movimento de baixa',
    )
    loss_movement = models.OneToOneField(
        'inventory.StockMovement',
        on_delete=models.PROTECT,
        related_name='lost_material_consumption',
        null=True,
        blank=True,
        verbose_name='movimento de perda',
    )
    return_movement = models.OneToOneField(
        'inventory.StockMovement',
        on_delete=models.PROTECT,
        related_name='returned_material_consumption',
        null=True,
        blank=True,
        verbose_name='movimento de devolução de reserva',
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='material_consumptions',
        verbose_name='unidade',
    )
    lot_number = models.CharField('lote do material', max_length=80, blank=True)
    quality_status = models.CharField(
        'status de qualidade',
        max_length=24,
        choices=QualityStatus.choices,
        default=QualityStatus.QUARANTINE,
    )
    expiry_date = models.DateField('validade', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['order', 'material__code']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    planned_quantity__gte=0,
                    actual_quantity__gte=0,
                    loss_quantity__gte=0,
                    returned_quantity__gte=0,
                    reserved_quantity__gte=0,
                    issued_quantity__gte=0,
                ),
                name='production_material_quantities_nonnegative',
            ),
        ]
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['material']),
            models.Index(fields=['quality_status']),
            models.Index(fields=['lot_number']),
        ]
        verbose_name = 'consumo de material'
        verbose_name_plural = 'consumos de material'

    @property
    def variance_quantity(self):
        return self.actual_quantity - self.planned_quantity

    def _validate_stock_movement(
        self,
        errors,
        field_name,
        expected_type,
        address_prefix,
        quantity_field,
    ):
        movement = getattr(self, field_name)
        if movement is None:
            return

        invalid_reasons = []
        if movement.movement_type != expected_type:
            invalid_reasons.append('tipo')
        if movement.product_id != self.material_id:
            invalid_reasons.append('material')
        if movement.unit_id != self.unit_id:
            invalid_reasons.append('unidade')
        if movement.quantity != getattr(self, quantity_field):
            invalid_reasons.append('quantidade')
        if not self.stock_lot_id or movement.lot_id != self.stock_lot_id:
            invalid_reasons.append('lote')
        if (
            not self.warehouse_id
            or getattr(movement, f'{address_prefix}_warehouse_id') != self.warehouse_id
        ):
            invalid_reasons.append('almoxarifado')
        if (
            not self.location_id
            or getattr(movement, f'{address_prefix}_location_id') != self.location_id
        ):
            invalid_reasons.append('localização')
        if movement.source_production_order_id != self.order_id:
            invalid_reasons.append('ordem de produção')
        if self.pk is None or movement.source_material_consumption_id != self.pk:
            invalid_reasons.append('consumo de material')

        if invalid_reasons:
            errors[field_name] = (
                'O movimento de estoque não corresponde ao consumo em: '
                f'{", ".join(invalid_reasons)}.'
            )

    def clean(self):
        super().clean()
        from inventory.models import StockMovement

        errors = {}
        order_status = (
            ProductionOrder.objects.filter(pk=self.order_id)
            .values_list('status', flat=True)
            .first()
        )
        if order_status in {
            ProductionOrder.Status.CANCELLED,
            ProductionOrder.Status.COMPLETED,
            ProductionOrder.Status.CLOSED,
        }:
            persisted = _persisted_values(self)
            if persisted is None or _has_persisted_changes(self, persisted):
                errors['order'] = 'A ordem terminal não permite alterar alocações.'
        if self.component and self.component.formula_id != self.order.formula_id:
            errors['component'] = 'O componente deve pertencer à fórmula da ordem.'
        if self.component and self.component.material_id != self.material_id:
            errors['material'] = 'O material deve corresponder ao componente da fórmula.'
        if self.planned_quantity is not None and self.planned_quantity < 0:
            errors['planned_quantity'] = 'A quantidade planejada não pode ser negativa.'
        if self.actual_quantity is not None and self.actual_quantity < 0:
            errors['actual_quantity'] = 'A quantidade real não pode ser negativa.'
        if self.loss_quantity is not None and self.loss_quantity < 0:
            errors['loss_quantity'] = 'A perda não pode ser negativa.'
        if self.returned_quantity is not None and self.returned_quantity < 0:
            errors['returned_quantity'] = 'A devolução não pode ser negativa.'
        if self.reserved_quantity is not None and self.reserved_quantity < 0:
            errors['reserved_quantity'] = 'A quantidade reservada não pode ser negativa.'
        if self.issued_quantity is not None and self.issued_quantity < 0:
            errors['issued_quantity'] = 'A quantidade baixada não pode ser negativa.'
        if self.stock_lot and self.stock_lot.product_id != self.material_id:
            errors['stock_lot'] = 'O lote de estoque deve pertencer ao material informado.'
        if self.stock_lot and self.lot_number and self.stock_lot.lot_number != self.lot_number:
            errors['lot_number'] = 'O lote informado deve corresponder ao lote de estoque.'
        if bool(self.warehouse_id) != bool(self.location_id):
            errors['location'] = 'Informe almoxarifado e localização em conjunto.'
        if self.location_id and self.location.warehouse_id != self.warehouse_id:
            errors['location'] = 'A localização deve pertencer ao almoxarifado.'
        if (
            self.actual_quantity is not None
            and self.actual_quantity > 0
            and self.quality_status != self.QualityStatus.APPROVED
        ):
            errors['quality_status'] = 'Consumo real exige material com status aprovado.'
        if self.expiry_date and self.expiry_date < timezone.localdate():
            errors['expiry_date'] = 'Não é permitido consumir material vencido.'
        if not self.material.is_operationally_available:
            errors['material'] = (
                'Não é permitido consumir material bloqueado, obsoleto ou não aprovado.'
            )
        self._validate_stock_movement(
            errors,
            'reservation_movement',
            StockMovement.MovementType.RESERVATION,
            'from',
            'reserved_quantity',
        )
        self._validate_stock_movement(
            errors,
            'issue_movement',
            StockMovement.MovementType.ISSUE,
            'from',
            'issued_quantity',
        )
        self._validate_stock_movement(
            errors,
            'loss_movement',
            StockMovement.MovementType.LOSS,
            'from',
            'loss_quantity',
        )
        self._validate_stock_movement(
            errors,
            'return_movement',
            StockMovement.MovementType.RELEASE_RESERVATION,
            'from',
            'returned_quantity',
        )
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.order.order_number} - {self.material.code}'


class ProductionOutput(SingleInstanceModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        RECEIVED = 'received', 'Recebido em quarentena'

    PENDING_MUTABLE_ORDER_STATUSES = frozenset(
        {
            ProductionOrder.Status.DRAFT,
            ProductionOrder.Status.APPROVED,
            ProductionOrder.Status.RELEASED,
            ProductionOrder.Status.IN_PROGRESS,
            ProductionOrder.Status.PAUSED,
        }
    )

    order = models.ForeignKey(
        ProductionOrder, on_delete=models.CASCADE, related_name='outputs', verbose_name='ordem'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='production_outputs', verbose_name='produto'
    )
    lot_number = models.CharField('lote', max_length=80)
    sublot_number = models.CharField('sublote', max_length=80, blank=True)
    planned_quantity = models.DecimalField('quantidade planejada', max_digits=14, decimal_places=4)
    produced_quantity = models.DecimalField(
        'quantidade produzida', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    unit = models.ForeignKey(
        UnitOfMeasure, on_delete=models.PROTECT, related_name='production_outputs'
    )
    warehouse = models.ForeignKey(
        'masters.Warehouse', on_delete=models.PROTECT, null=True, blank=True
    )
    location = models.ForeignKey(
        'masters.StorageLocation', on_delete=models.PROTECT, null=True, blank=True
    )
    manufacturing_date = models.DateField('fabricação', null=True, blank=True)
    expiry_date = models.DateField('validade', null=True, blank=True)
    status = models.CharField(
        'status', max_length=16, choices=Status.choices, default=Status.PENDING
    )
    stock_lot = models.OneToOneField(
        'inventory.StockLot', on_delete=models.PROTECT, null=True, blank=True
    )
    stock_movement = models.OneToOneField(
        'inventory.StockMovement', on_delete=models.PROTECT, null=True, blank=True
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['order', 'lot_number', 'sublot_number']
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'lot_number', 'sublot_number'],
                name='unique_production_output_lot',
            ),
            models.CheckConstraint(
                condition=models.Q(
                    planned_quantity__gte=0,
                    produced_quantity__gte=0,
                ),
                name='production_output_quantities_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=('pending', 'received')),
                name='production_output_status_valid',
            ),
        ]
        permissions = [('receive_productionoutput', 'Pode receber produto acabado')]

    def clean(self):
        super().clean()
        from inventory.models import StockMovement, StockQualityStatus

        errors = {}
        persisted = _persisted_values(self)
        if persisted:
            if persisted['order_id'] != self.order_id:
                errors['order'] = 'A ordem de um resultado existente não pode ser alterada.'
            if persisted['status'] == self.Status.RECEIVED and _has_persisted_changes(
                self, persisted
            ):
                errors['status'] = (
                    'Resultados recebidos são imutáveis; preserve a evidência de recebimento.'
                )
        if (
            self.order_id
            and self.status == self.Status.PENDING
            and self.order.status not in self.PENDING_MUTABLE_ORDER_STATUSES
            and (persisted is None or _has_persisted_changes(self, persisted))
        ):
            errors['order'] = 'A ordem não permite criar ou alterar resultados pendentes.'
        if self.order_id and self.product_id != self.order.product_id:
            errors['product'] = 'O produto acabado deve ser o produto da ordem.'
        if self.planned_quantity is not None and self.planned_quantity < 0:
            errors['planned_quantity'] = 'A quantidade planejada não pode ser negativa.'
        if self.produced_quantity is not None and self.produced_quantity < 0:
            errors['produced_quantity'] = 'A quantidade produzida não pode ser negativa.'
        if (
            self.expiry_date
            and self.manufacturing_date
            and self.expiry_date < self.manufacturing_date
        ):
            errors['expiry_date'] = 'A validade não pode ser anterior à fabricação.'
        if bool(self.warehouse_id) != bool(self.location_id):
            errors['location'] = 'Informe almoxarifado e localização em conjunto.'
        if self.location_id and self.location.warehouse_id != self.warehouse_id:
            errors['location'] = 'A localização deve pertencer ao almoxarifado.'

        receipt_evidence = {
            'stock_lot': self.stock_lot_id,
            'stock_movement': self.stock_movement_id,
            'received_by': self.received_by_id,
            'received_at': self.received_at,
        }
        if self.status == self.Status.RECEIVED:
            for field_name, value in receipt_evidence.items():
                if not value:
                    errors[field_name] = 'O recebimento exige evidência completa.'
        elif self.status == self.Status.PENDING:
            for field_name, value in receipt_evidence.items():
                if value:
                    errors[field_name] = (
                        'Resultados pendentes não podem guardar evidência de recebimento.'
                    )

        if self.stock_lot_id and (
            self.stock_lot.product_id != self.product_id
            or self.stock_lot.lot_number != self.lot_number
            or self.stock_lot.sublot_number != self.sublot_number
            or self.stock_lot.source_production_order_id != self.order_id
            or self.stock_lot.quality_status != StockQualityStatus.QUARANTINE
        ):
            errors['stock_lot'] = (
                'O lote de estoque deve corresponder ao produto, lote, sublote, ordem e '
                'permanecer em quarentena.'
            )

        if self.stock_movement_id:
            movement = self.stock_movement
            invalid_movement = (
                movement.movement_type != StockMovement.MovementType.PRODUCTION_RECEIPT
                or movement.product_id != self.product_id
                or movement.unit_id != self.unit_id
                or movement.quantity != self.produced_quantity
                or movement.quality_status != StockQualityStatus.QUARANTINE
                or not self.stock_lot_id
                or movement.lot_id != self.stock_lot_id
                or not self.warehouse_id
                or movement.to_warehouse_id != self.warehouse_id
                or not self.location_id
                or movement.to_location_id != self.location_id
                or movement.source_production_order_id != self.order_id
            )
            if invalid_movement:
                errors['stock_movement'] = (
                    'O recebimento deve corresponder ao produto, unidade, quantidade, lote, '
                    'destino, ordem e permanecer em quarentena.'
                )
        if errors:
            raise ValidationError(errors)


class ProductionOperationExecution(SingleInstanceModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        IN_PROGRESS = 'in_progress', 'Em execução'
        COMPLETED = 'completed', 'Concluído'
        SKIPPED = 'skipped', 'Não executado'

    order = models.ForeignKey(
        ProductionOrder, on_delete=models.CASCADE, related_name='operation_executions'
    )
    route_step = models.ForeignKey(
        'formulations.RouteStep', on_delete=models.PROTECT, null=True, blank=True
    )
    sequence = models.PositiveIntegerField('sequência')
    operation = models.CharField('operação', max_length=160)
    work_center = models.CharField('centro de trabalho', max_length=120, blank=True)
    planned_minutes = models.DecimalField(
        'minutos planejados', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    actual_minutes = models.DecimalField(
        'minutos reais', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    machine_hourly_cost = models.DecimalField(
        'custo de máquina por hora',
        max_digits=14,
        decimal_places=4,
        default=Decimal('0.0000'),
    )
    status = models.CharField(
        'status', max_length=20, choices=Status.choices, default=Status.PENDING
    )
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['order', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['order', 'sequence'], name='unique_production_operation_sequence'
            ),
            models.CheckConstraint(
                condition=models.Q(
                    planned_minutes__gte=0,
                    actual_minutes__gte=0,
                    machine_hourly_cost__gte=0,
                ),
                name='production_operation_values_nonnegative',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(started_at__isnull=True)
                    | models.Q(ended_at__isnull=True)
                    | models.Q(ended_at__gte=models.F('started_at'))
                ),
                name='production_operation_times_ordered',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        status='pending',
                        started_at__isnull=True,
                        ended_at__isnull=True,
                        actual_minutes=0,
                    )
                    | models.Q(
                        status='in_progress',
                        started_at__isnull=False,
                        ended_at__isnull=True,
                        actual_minutes=0,
                        recorded_by__isnull=False,
                    )
                    | models.Q(
                        status='completed',
                        started_at__isnull=False,
                        ended_at__isnull=False,
                        recorded_by__isnull=False,
                    )
                    | models.Q(
                        status='skipped',
                        started_at__isnull=True,
                        ended_at__isnull=True,
                        actual_minutes=0,
                        recorded_by__isnull=False,
                    )
                ),
                name='production_operation_status_evidence',
            ),
            models.CheckConstraint(
                condition=~models.Q(status='skipped') | models.Q(notes__regex=r'\S'),
                name='production_operation_skipped_reason',
            ),
        ]

    @classmethod
    def validate_status_transition(
        cls,
        previous_status,
        requested_status,
        *,
        has_persisted_changes=True,
    ):
        """Enforce the auditable lifecycle shared by UI and API writes."""
        if previous_status is None:
            if requested_status not in {
                cls.Status.PENDING,
                cls.Status.IN_PROGRESS,
                cls.Status.COMPLETED,
            }:
                raise ValidationError(
                    {
                        'status': (
                            'Crie a operação pendente antes de registrar que ela não foi executada.'
                        )
                    }
                )
            return

        if previous_status in {cls.Status.COMPLETED, cls.Status.SKIPPED}:
            if has_persisted_changes:
                raise ValidationError(
                    {'status': 'Operações concluídas ou não executadas são imutáveis.'}
                )
            return

        allowed_transitions = {
            cls.Status.PENDING: {
                cls.Status.PENDING,
                cls.Status.IN_PROGRESS,
                cls.Status.COMPLETED,
                cls.Status.SKIPPED,
            },
            cls.Status.IN_PROGRESS: {
                cls.Status.IN_PROGRESS,
                cls.Status.COMPLETED,
            },
        }
        if requested_status not in allowed_transitions[previous_status]:
            raise ValidationError({'status': 'A regressão de estado da operação não é permitida.'})

    def clean(self):
        super().clean()
        errors = {}
        persisted = _persisted_values(self)
        if persisted:
            if persisted['order_id'] != self.order_id:
                errors['order'] = 'A ordem de uma execução existente não pode ser alterada.'
        try:
            self.validate_status_transition(
                persisted['status'] if persisted else None,
                self.status,
                has_persisted_changes=(
                    _has_persisted_changes(self, persisted) if persisted else True
                ),
            )
        except ValidationError as error:
            errors.update(error.message_dict)
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            errors['ended_at'] = 'O fim não pode ser anterior ao início.'

        if self.status == self.Status.PENDING:
            if self.started_at:
                errors['started_at'] = 'Operações pendentes não podem ter início registrado.'
            if self.ended_at:
                errors['ended_at'] = 'Operações pendentes não podem ter fim registrado.'
            if self.actual_minutes != Decimal('0.00'):
                errors['actual_minutes'] = 'Operações pendentes devem ter duração real zero.'
        elif self.status == self.Status.IN_PROGRESS:
            if not self.started_at:
                errors['started_at'] = 'Operações em execução exigem o início registrado.'
            if self.ended_at:
                errors['ended_at'] = 'Operações em execução não podem ter fim registrado.'
            if self.actual_minutes != Decimal('0.00'):
                errors['actual_minutes'] = 'Operações em execução devem ter duração real zero.'
            if not self.recorded_by_id:
                errors['recorded_by'] = 'Operações em execução exigem o ator do apontamento.'
        elif self.status == self.Status.COMPLETED:
            if not self.started_at:
                errors['started_at'] = 'Operações concluídas exigem o início registrado.'
            if not self.ended_at:
                errors['ended_at'] = 'Operações concluídas exigem o fim registrado.'
            if not self.recorded_by_id:
                errors['recorded_by'] = 'Operações concluídas exigem o ator do apontamento.'
        elif self.status == self.Status.SKIPPED:
            if self.started_at:
                errors['started_at'] = 'Operações não executadas não podem ter início registrado.'
            if self.ended_at:
                errors['ended_at'] = 'Operações não executadas não podem ter fim registrado.'
            if self.actual_minutes != Decimal('0.00'):
                errors['actual_minutes'] = 'Operações não executadas devem ter duração real zero.'
            if not self.recorded_by_id:
                errors['recorded_by'] = 'Operações não executadas exigem o ator do apontamento.'
            if not self.notes.strip():
                errors['notes'] = 'Informe a justificativa para não executar a operação.'

        if (
            self.status == self.Status.COMPLETED
            and self.started_at
            and self.ended_at
            and self.ended_at >= self.started_at
        ):
            self.actual_minutes = (
                Decimal(str((self.ended_at - self.started_at).total_seconds())) / Decimal('60')
            ).quantize(Decimal('0.01'))
        if self.planned_minutes is not None and self.planned_minutes < 0:
            errors['planned_minutes'] = 'O tempo planejado não pode ser negativo.'
        if self.actual_minutes is not None and self.actual_minutes < 0:
            errors['actual_minutes'] = 'O tempo real não pode ser negativo.'
        if self.machine_hourly_cost is not None and self.machine_hourly_cost < 0:
            errors['machine_hourly_cost'] = 'O custo-hora da máquina não pode ser negativo.'
        if self.route_step_id:
            if self.route_step.route_id != self.order.route_id:
                errors['route_step'] = 'A etapa deve pertencer ao roteiro da ordem.'
            if self.sequence != self.route_step.sequence:
                errors['sequence'] = 'A sequência deve corresponder à etapa do roteiro.'
            if self.operation != self.route_step.operation:
                errors['operation'] = 'A operação deve corresponder à etapa do roteiro.'
        if errors:
            raise ValidationError(errors)


class ProductionLaborEntry(SingleInstanceModel):
    MUTABLE_ORDER_STATUSES = frozenset(
        {
            ProductionOrder.Status.RELEASED,
            ProductionOrder.Status.IN_PROGRESS,
            ProductionOrder.Status.PAUSED,
        }
    )

    order = models.ForeignKey(
        ProductionOrder, on_delete=models.CASCADE, related_name='labor_entries'
    )
    operation_execution = models.ForeignKey(
        ProductionOperationExecution,
        on_delete=models.PROTECT,
        related_name='labor_entries',
        null=True,
        blank=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='production_labor_entries'
    )
    role = models.CharField('função', max_length=120)
    started_at = models.DateTimeField('início')
    ended_at = models.DateTimeField('fim')
    duration_minutes = models.DecimalField(
        'duração em minutos', max_digits=10, decimal_places=2, default=Decimal('0.00')
    )
    hourly_cost = models.DecimalField(
        'custo por hora', max_digits=14, decimal_places=4, default=Decimal('0.0000')
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['order', 'started_at']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(
                    duration_minutes__gte=0,
                    hourly_cost__gte=0,
                ),
                name='production_labor_values_nonnegative',
            ),
            models.CheckConstraint(
                condition=models.Q(ended_at__gte=models.F('started_at')),
                name='production_labor_times_ordered',
            ),
        ]
        indexes = [
            models.Index(
                fields=['order', 'started_at'],
                name='prod_labor_order_start_idx',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        persisted = _persisted_values(self)
        if persisted and persisted['order_id'] != self.order_id:
            errors['order'] = 'A ordem de um apontamento existente não pode ser alterada.'
        if (
            self.order_id
            and self.order.status not in self.MUTABLE_ORDER_STATUSES
            and (persisted is None or _has_persisted_changes(self, persisted))
        ):
            errors['order'] = 'A ordem não permite criar ou alterar apontamentos de mão de obra.'
        if self.ended_at and self.started_at and self.ended_at < self.started_at:
            errors['ended_at'] = 'O fim não pode ser anterior ao início.'
        if self.started_at and self.ended_at and self.ended_at >= self.started_at:
            self.duration_minutes = (
                Decimal(str((self.ended_at - self.started_at).total_seconds())) / Decimal('60')
            ).quantize(Decimal('0.01'))
        if self.hourly_cost is not None and self.hourly_cost < 0:
            errors['hourly_cost'] = 'O custo-hora não pode ser negativo.'
        if self.operation_execution_id and self.operation_execution.order_id != self.order_id:
            errors['operation_execution'] = 'O processo deve pertencer à mesma ordem.'
        if errors:
            raise ValidationError(errors)
