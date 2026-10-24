from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_CEILING

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Min, Sum
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from masters.models import Product, UnitOfMeasure


QUANTITY_SCALE = Decimal('0.0001')
MINUTES_SCALE = Decimal('0.01')
ZERO_QUANTITY = Decimal('0.0000')


def _quantize_quantity(value):
    try:
        return Decimal(str(value)).quantize(QUANTITY_SCALE)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError('Informe uma quantidade válida.') from exc


class PlanningPolicy(SingleInstanceModel):
    class Source(models.TextChoices):
        BUY = 'buy', 'Compra'
        PRODUCE = 'produce', 'Produção'
        TRANSFER = 'transfer', 'Transferência'
        OUTSOURCE = 'outsource', 'Terceirização'

    product = models.OneToOneField(
        Product,
        on_delete=models.PROTECT,
        related_name='planning_policy',
        verbose_name='produto',
    )
    preferred_source = models.CharField(
        'origem preferencial',
        max_length=20,
        choices=Source.choices,
        default=Source.PRODUCE,
    )
    safety_stock_quantity = models.DecimalField(
        'estoque de segurança',
        max_digits=14,
        decimal_places=4,
        default=ZERO_QUANTITY,
    )
    minimum_order_quantity = models.DecimalField(
        'lote mínimo',
        max_digits=14,
        decimal_places=4,
        default=ZERO_QUANTITY,
    )
    order_multiple = models.DecimalField(
        'múltiplo de lote',
        max_digits=14,
        decimal_places=4,
        default=ZERO_QUANTITY,
    )
    lead_time_days = models.PositiveIntegerField('lead time em dias', default=0)
    is_active = models.BooleanField('ativo', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code']
        constraints = [
            models.UniqueConstraint(fields=['product'], name='unique_planning_policy_product'),
        ]
        indexes = [
            models.Index(fields=['preferred_source', 'is_active']),
            models.Index(fields=['product']),
        ]
        verbose_name = 'política de planejamento'
        verbose_name_plural = 'políticas de planejamento'

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('safety_stock_quantity', 'minimum_order_quantity', 'order_multiple'):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'A quantidade não pode ser negativa.'
        if errors:
            raise ValidationError(errors)

        return None

    def round_requirement(self, quantity):
        suggested = _quantize_quantity(quantity)
        if suggested <= 0:
            return ZERO_QUANTITY
        if self.minimum_order_quantity > 0:
            suggested = max(suggested, self.minimum_order_quantity)
        if self.order_multiple > 0:
            multiplier = (suggested / self.order_multiple).to_integral_value(rounding=ROUND_CEILING)
            suggested = multiplier * self.order_multiple
        return suggested.quantize(QUANTITY_SCALE)

    def __str__(self):
        return f'{self.product} - {self.get_preferred_source_display()}'


class MasterProductionSchedule(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'MPS'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovado'
        CANCELLED = 'cancelled', 'Cancelado'

    code = models.CharField('código', max_length=80, blank=True)
    name = models.CharField('nome', max_length=160)
    period_start = models.DateField('início do período')
    period_end = models.DateField('fim do período')
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.DRAFT)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-period_start', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_mps_code'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['period_start', 'period_end']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'plano mestre de produção'
        verbose_name_plural = 'planos mestres de produção'

    def clean(self):
        super().clean()
        if self.period_start and self.period_end and self.period_end < self.period_start:
            raise ValidationError(
                {'period_end': 'O fim do período não pode ser anterior ao início.'}
            )

    def __str__(self):
        return f'{self.code} - {self.name}'


class MPSLine(SingleInstanceModel):
    class Source(models.TextChoices):
        FORECAST = 'forecast', 'Previsão'
        SALES_ORDER = 'sales_order', 'Pedido em carteira'
        CONTRACT = 'contract', 'Contrato'
        CAMPAIGN = 'campaign', 'Campanha'
        SAFETY_STOCK = 'safety_stock', 'Estoque de segurança'
        MANUAL = 'manual', 'Manual'

    schedule = models.ForeignKey(
        MasterProductionSchedule,
        on_delete=models.CASCADE,
        related_name='lines',
        verbose_name='plano mestre',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='mps_lines',
        verbose_name='produto',
    )
    due_date = models.DateField('data de necessidade')
    demand_quantity = models.DecimalField('quantidade demandada', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='mps_lines',
        verbose_name='unidade',
    )
    source = models.CharField('origem da demanda', max_length=24, choices=Source.choices)
    customer_reference = models.CharField('referência comercial', max_length=120, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['due_date', 'product__code']
        indexes = [
            models.Index(fields=['schedule', 'due_date']),
            models.Index(fields=['product', 'due_date']),
            models.Index(fields=['source']),
        ]
        verbose_name = 'linha do MPS'
        verbose_name_plural = 'linhas do MPS'

    def clean(self):
        super().clean()
        errors = {}
        if self.demand_quantity <= 0:
            errors['demand_quantity'] = 'A quantidade demandada deve ser maior que zero.'
        if self.product and not self.product.is_operationally_available:
            errors['product'] = 'O produto precisa estar aprovado e operacionalmente disponível.'
        if self.schedule and self.due_date:
            if not self.schedule.period_start <= self.due_date <= self.schedule.period_end:
                errors['due_date'] = 'A data de necessidade deve estar dentro do período do MPS.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.schedule} - {self.product} - {self.demand_quantity}'


class InventoryPosition(SingleInstanceModel):
    product = models.OneToOneField(
        Product,
        on_delete=models.PROTECT,
        related_name='inventory_position',
        verbose_name='produto',
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='inventory_positions',
        verbose_name='unidade',
    )
    on_hand_quantity = models.DecimalField(
        'saldo físico', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    quarantine_quantity = models.DecimalField(
        'quarentena', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    reserved_quantity = models.DecimalField(
        'reservado', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    incoming_purchase_quantity = models.DecimalField(
        'compras em aberto',
        max_digits=14,
        decimal_places=4,
        default=ZERO_QUANTITY,
    )
    incoming_production_quantity = models.DecimalField(
        'ordens em aberto',
        max_digits=14,
        decimal_places=4,
        default=ZERO_QUANTITY,
    )
    expiry_date = models.DateField('validade mais próxima', null=True, blank=True)
    captured_at = models.DateTimeField('capturado em', default=timezone.now)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code']
        constraints = [
            models.UniqueConstraint(fields=['product'], name='unique_inventory_position_product'),
        ]
        indexes = [
            models.Index(fields=['product']),
            models.Index(fields=['expiry_date']),
        ]
        verbose_name = 'posição de estoque para MRP'
        verbose_name_plural = 'posições de estoque para MRP'

    @property
    def available_quantity(self):
        return (self.on_hand_quantity - self.quarantine_quantity - self.reserved_quantity).quantize(
            QUANTITY_SCALE
        )

    @property
    def projected_available_quantity(self):
        return (
            self.available_quantity
            + self.incoming_purchase_quantity
            + self.incoming_production_quantity
        ).quantize(QUANTITY_SCALE)

    def clean(self):
        super().clean()
        errors = {}
        for field_name in (
            'on_hand_quantity',
            'quarantine_quantity',
            'reserved_quantity',
            'incoming_purchase_quantity',
            'incoming_production_quantity',
        ):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'A quantidade não pode ser negativa.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.product} - disponível {self.projected_available_quantity}'


class MRPRun(SingleInstanceModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        CALCULATED = 'calculated', 'Calculado'
        CANCELLED = 'cancelled', 'Cancelado'

    schedule = models.ForeignKey(
        MasterProductionSchedule,
        on_delete=models.PROTECT,
        related_name='mrp_runs',
        verbose_name='plano mestre',
    )
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.DRAFT)
    run_at = models.DateTimeField('calculado em', null=True, blank=True)
    scenario_name = models.CharField('cenário de simulação', max_length=120, blank=True)
    demand_variation_percent = models.DecimalField(
        'variação de demanda (%)',
        max_digits=7,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    lead_time_variation_days = models.IntegerField('variação de lead time em dias', default=0)
    capacity_variation_percent = models.DecimalField(
        'variação de capacidade (%)',
        max_digits=7,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    restriction_notes = models.TextField('restrições simuladas', blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['schedule', 'created_at']),
        ]
        verbose_name = 'execução de MRP'
        verbose_name_plural = 'execuções de MRP'

    def clean(self):
        super().clean()
        errors = {}
        if self.demand_variation_percent <= Decimal('-100.00'):
            errors['demand_variation_percent'] = 'A variação de demanda deve ser maior que -100%.'
        if self.capacity_variation_percent <= Decimal('-100.00'):
            errors['capacity_variation_percent'] = (
                'A variação de capacidade deve ser maior que -100%.'
            )
        if errors:
            raise ValidationError(errors)

        return None

    def calculate(self):
        if self.pk is None:
            raise ValidationError({'id': 'Salve a execução de MRP antes de calcular.'})

        with transaction.atomic():
            type(self).objects.select_for_update().get(pk=self.pk)
            if self.suggestions.filter(purchase_requisition_items__isnull=False).exists():
                raise ValidationError(
                    {
                        'id': (
                            'Não é possível recalcular o MRP: já existem requisições de '
                            'compra geradas a partir das sugestões desta execução.'
                        )
                    }
                )
            self.full_clean()
            self.suggestions.all().delete()
            demand_by_product = self._collect_demand()
            suggestions = []
            if demand_by_product:
                suggestions = self._create_suggestions(demand_by_product)
            self.status = self.Status.CALCULATED
            self.run_at = timezone.now()
            self.save(update_fields=['status', 'run_at', 'updated_at'])
            return suggestions

    def _collect_demand(self):
        lines = (
            self.schedule.lines.select_related('product')
            .values('product')
            .annotate(required_quantity=Sum('demand_quantity'), due_date=Min('due_date'))
        )
        product_ids = [line['product'] for line in lines]
        products = Product.objects.filter(id__in=product_ids).in_bulk()
        demand_factor = Decimal('1.00') + (self.demand_variation_percent / Decimal('100.00'))
        demand_by_product = {}
        for line in lines:
            product = products[line['product']]
            demand_by_product[product.id] = {
                'product': product,
                'required_quantity': _quantize_quantity(line['required_quantity'] * demand_factor),
                'due_date': line['due_date'],
            }
        return demand_by_product

    def _create_suggestions(self, demand_by_product):
        product_ids = list(demand_by_product.keys())
        policies = {
            policy.product_id: policy
            for policy in PlanningPolicy.objects.filter(product_id__in=product_ids, is_active=True)
        }
        inventory_positions = {
            position.product_id: position
            for position in InventoryPosition.objects.filter(product_id__in=product_ids)
        }
        suggestions = []
        today = timezone.localdate()
        for product_id, demand in demand_by_product.items():
            product = demand['product']
            policy = policies.get(product_id)
            position = inventory_positions.get(product_id)
            required_quantity = demand['required_quantity']
            due_date = demand['due_date']
            safety_stock = policy.safety_stock_quantity if policy else ZERO_QUANTITY
            available_quantity = (
                position.projected_available_quantity if position else ZERO_QUANTITY
            )
            net_requirement = max(
                required_quantity + safety_stock - available_quantity, ZERO_QUANTITY
            ).quantize(QUANTITY_SCALE)
            suggested_quantity = (
                policy.round_requirement(net_requirement)
                if policy
                else _quantize_quantity(net_requirement)
            )
            lead_time_days = max(
                (policy.lead_time_days if policy else 0) + self.lead_time_variation_days, 0
            )
            release_date = due_date - timedelta(days=lead_time_days)
            alert_level, notes = self._classify_alert(
                required_quantity=required_quantity,
                safety_stock=safety_stock,
                available_quantity=available_quantity,
                net_requirement=net_requirement,
                suggested_quantity=suggested_quantity,
                release_date=release_date,
                due_date=due_date,
                position=position,
                today=today,
            )
            suggestions.append(
                MRPSuggestion.objects.create(
                    run=self,
                    product=product,
                    suggestion_type=policy.preferred_source
                    if policy
                    else self._default_source(product),
                    due_date=due_date,
                    required_quantity=required_quantity,
                    available_quantity=available_quantity,
                    net_requirement=net_requirement,
                    suggested_quantity=suggested_quantity,
                    lead_time_days=lead_time_days,
                    release_date=release_date,
                    alert_level=alert_level,
                    notes=' '.join(notes),
                )
            )
        return suggestions

    def _classify_alert(
        self,
        required_quantity,
        safety_stock,
        available_quantity,
        net_requirement,
        suggested_quantity,
        release_date,
        due_date,
        position,
        today,
    ):
        alert_level = MRPSuggestion.AlertLevel.NONE
        notes = []
        if net_requirement > 0:
            alert_level = MRPSuggestion.AlertLevel.SHORTAGE
            notes.append('Necessidade líquida positiva: risco de ruptura.')
        if suggested_quantity > 0 and release_date < today:
            alert_level = MRPSuggestion.AlertLevel.LATE
            notes.append('Data de liberação sugerida anterior à data atual: atraso previsto.')
        expires_before_demand = (
            position and position.expiry_date and position.expiry_date <= due_date
        )
        if expires_before_demand:
            notes.append('Saldo com validade anterior ou igual à data de necessidade.')
            if net_requirement == 0:
                alert_level = MRPSuggestion.AlertLevel.EXPIRING
        if (
            alert_level == MRPSuggestion.AlertLevel.NONE
            and available_quantity > required_quantity + safety_stock
        ):
            alert_level = MRPSuggestion.AlertLevel.EXCESS
            notes.append('Saldo projetado acima da demanda e do estoque de segurança.')
        return alert_level, notes

    def _default_source(self, product):
        if product.item_type in {
            Product.ItemType.FINISHED_PRODUCT,
            Product.ItemType.SEMIFINISHED,
            Product.ItemType.INTERMEDIATE,
        }:
            return PlanningPolicy.Source.PRODUCE
        if product.item_type == Product.ItemType.SERVICE:
            return PlanningPolicy.Source.OUTSOURCE
        return PlanningPolicy.Source.BUY

    def __str__(self):
        return f'MRP {self.schedule} - {self.get_status_display()}'


class MRPSuggestion(SingleInstanceModel):
    class SuggestionType(models.TextChoices):
        BUY = PlanningPolicy.Source.BUY, 'Compra'
        PRODUCE = PlanningPolicy.Source.PRODUCE, 'Produção'
        TRANSFER = PlanningPolicy.Source.TRANSFER, 'Transferência'
        OUTSOURCE = PlanningPolicy.Source.OUTSOURCE, 'Terceirização'

    class AlertLevel(models.TextChoices):
        NONE = 'none', 'Sem alerta'
        SHORTAGE = 'shortage', 'Ruptura'
        LATE = 'late', 'Atraso previsto'
        EXCESS = 'excess', 'Excesso'
        EXPIRING = 'expiring', 'Vencimento próximo'
        CAPACITY = 'capacity', 'Capacidade insuficiente'

    run = models.ForeignKey(
        MRPRun, on_delete=models.CASCADE, related_name='suggestions', verbose_name='execução MRP'
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='mrp_suggestions', verbose_name='produto'
    )
    suggestion_type = models.CharField(
        'tipo de sugestão', max_length=20, choices=SuggestionType.choices
    )
    due_date = models.DateField('data de necessidade')
    required_quantity = models.DecimalField('necessidade bruta', max_digits=14, decimal_places=4)
    available_quantity = models.DecimalField(
        'saldo projetado disponível', max_digits=14, decimal_places=4
    )
    net_requirement = models.DecimalField('necessidade líquida', max_digits=14, decimal_places=4)
    suggested_quantity = models.DecimalField('quantidade sugerida', max_digits=14, decimal_places=4)
    lead_time_days = models.PositiveIntegerField('lead time em dias', default=0)
    release_date = models.DateField('data sugerida de liberação')
    alert_level = models.CharField(
        'alerta', max_length=20, choices=AlertLevel.choices, default=AlertLevel.NONE
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['due_date', 'product__code']
        indexes = [
            models.Index(fields=['run']),
            models.Index(fields=['product', 'suggestion_type']),
            models.Index(fields=['alert_level']),
            models.Index(fields=['due_date']),
        ]
        verbose_name = 'sugestão do MRP'
        verbose_name_plural = 'sugestões do MRP'

    def clean(self):
        super().clean()
        errors = {}
        for field_name in (
            'required_quantity',
            'available_quantity',
            'net_requirement',
            'suggested_quantity',
        ):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'A quantidade não pode ser negativa.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.product} - {self.get_suggestion_type_display()} {self.suggested_quantity}'


class CapacityResource(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'CAP'

    class ResourceType(models.TextChoices):
        LINE = 'line', 'Linha'
        WORK_CENTER = 'work_center', 'Centro de trabalho'
        SHIFT = 'shift', 'Turno'

    code = models.CharField('código', max_length=80, blank=True)
    name = models.CharField('nome', max_length=160)
    resource_type = models.CharField('tipo de recurso', max_length=24, choices=ResourceType.choices)
    work_center = models.CharField('centro de trabalho', max_length=120, blank=True)
    daily_capacity_minutes = models.DecimalField(
        'capacidade diária em minutos', max_digits=10, decimal_places=2
    )
    is_active = models.BooleanField('ativo', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_capacity_resource_code'),
        ]
        indexes = [
            models.Index(fields=['resource_type', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'recurso de capacidade'
        verbose_name_plural = 'recursos de capacidade'

    def clean(self):
        super().clean()
        if self.daily_capacity_minutes <= 0:
            raise ValidationError(
                {'daily_capacity_minutes': 'A capacidade diária deve ser maior que zero.'}
            )

    def __str__(self):
        return f'{self.code} - {self.name}'


class CapacityLoad(SingleInstanceModel):
    run = models.ForeignKey(
        MRPRun,
        on_delete=models.CASCADE,
        related_name='capacity_loads',
        null=True,
        blank=True,
        verbose_name='execução MRP',
    )
    resource = models.ForeignKey(
        CapacityResource,
        on_delete=models.PROTECT,
        related_name='capacity_loads',
        verbose_name='recurso',
    )
    period_date = models.DateField('data do período')
    shift = models.CharField('turno', max_length=80, blank=True)
    required_minutes = models.DecimalField('minutos requeridos', max_digits=10, decimal_places=2)
    available_minutes = models.DecimalField('minutos disponíveis', max_digits=10, decimal_places=2)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['period_date', 'resource__code']
        indexes = [
            models.Index(fields=['period_date']),
            models.Index(fields=['resource', 'period_date']),
            models.Index(fields=['run']),
        ]
        verbose_name = 'carga de capacidade'
        verbose_name_plural = 'cargas de capacidade'

    @property
    def is_overloaded(self):
        return self.required_minutes > self.available_minutes

    @property
    def overload_minutes(self):
        overload = max(self.required_minutes - self.available_minutes, Decimal('0.00'))
        return overload.quantize(MINUTES_SCALE)

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('required_minutes', 'available_minutes'):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'Os minutos não podem ser negativos.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.resource} - {self.period_date}'
