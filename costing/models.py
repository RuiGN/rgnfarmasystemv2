from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from formulations.models import MasterFormula
from masters.models import Product, UnitOfMeasure
from production.models import ProductionOrder


MONEY_SCALE = Decimal('0.0001')
ZERO_MONEY = Decimal('0.0000')
PERCENT_BASE = Decimal('100.0000')


def _money(value):
    try:
        amount = Decimal(str(value or ZERO_MONEY))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError('Informe um valor monetário válido.') from exc
    return amount.quantize(MONEY_SCALE, rounding=ROUND_HALF_UP)


def _percent_factor(value):
    return Decimal(str(value or ZERO_MONEY)) / PERCENT_BASE


class CostElement(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'CE'

    class Category(models.TextChoices):
        MATERIAL = 'material', 'Material'
        LOSS = 'loss', 'Perda'
        LABOR = 'labor', 'Mão de obra'
        MACHINE = 'machine', 'Hora máquina'
        THIRD_PARTY = 'third_party', 'Terceiros'
        ANALYSIS = 'analysis', 'Análises'
        OVERHEAD = 'overhead', 'Overhead'
        INDIRECT = 'indirect', 'Indireto'
        TAX = 'tax', 'Impostos'
        NON_QUALITY = 'non_quality', 'Não qualidade'

    code = models.CharField('código', max_length=40, blank=True)
    name = models.CharField('nome', max_length=160)
    category = models.CharField('categoria', max_length=32, choices=Category.choices)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['category', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_cost_element_code'),
        ]
        indexes = [
            models.Index(fields=['category', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'elemento de custo'
        verbose_name_plural = 'elementos de custo'

    def __str__(self):
        return f'{self.code} - {self.name}'


class StandardCost(SingleInstanceModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovado'
        OBSOLETE = 'obsolete', 'Obsoleto'

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='standard_costs', verbose_name='produto'
    )
    version = models.CharField('versão', max_length=40)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateField('vigente a partir de')
    effective_to = models.DateField('vigente até', null=True, blank=True)
    standard_quantity = models.DecimalField('quantidade padrão', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='standard_costs',
        verbose_name='unidade',
    )
    material_cost = models.DecimalField(
        'custo material', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    loss_cost = models.DecimalField(
        'custo perdas', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    labor_cost = models.DecimalField(
        'custo mão de obra', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    machine_cost = models.DecimalField(
        'custo máquina', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    third_party_cost = models.DecimalField(
        'custo terceiros', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    analysis_cost = models.DecimalField(
        'custo análises', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    overhead_cost = models.DecimalField(
        'custo overhead', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    indirect_cost = models.DecimalField(
        'custo indireto', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    tax_cost = models.DecimalField(
        'custo impostos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    total_standard_cost = models.DecimalField(
        'custo padrão total', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_standard_costs',
        null=True,
        blank=True,
        verbose_name='aprovado por',
    )
    approved_at = models.DateTimeField('aprovado em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code', '-effective_from', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'version'], name='unique_product_cost_version'
            ),
            models.CheckConstraint(
                condition=~models.Q(status='approved') | models.Q(approved_at__isnull=False),
                name='standard_cost_approved_at_required',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'status']),
            models.Index(fields=['effective_from']),
            models.Index(fields=['version']),
        ]
        verbose_name = 'custo padrão'
        verbose_name_plural = 'custos padrão'

    def recalculate(self, save=True):
        self.total_standard_cost = _money(
            self.material_cost
            + self.loss_cost
            + self.labor_cost
            + self.machine_cost
            + self.third_party_cost
            + self.analysis_cost
            + self.overhead_cost
            + self.indirect_cost
            + self.tax_cost
        )
        self.full_clean(validate_unique=False)
        if save:
            self.save(update_fields=['total_standard_cost', 'updated_at'])
        return self.total_standard_cost

    def _persisted_state(self, *, for_update=False):
        if self.pk is None:
            return None
        queryset = type(self).objects
        if for_update:
            queryset = queryset.select_for_update()
        return (
            queryset.filter(pk=self.pk)
            .values(
                'status',
                'approved_by_id',
                'approved_at',
            )
            .first()
        )

    def _require_transition_origin(self, expected_status, action_label):
        if self.status != expected_status:
            raise ValidationError(
                {'status': (f'O custo padrão deve estar em {expected_status} para {action_label}.')}
            )
        persisted = self._persisted_state(for_update=True)
        if persisted is None:
            raise ValidationError(
                {'status': 'O custo padrão deve ser salvo como rascunho antes da transição.'}
            )
        if persisted['status'] != expected_status:
            raise ValidationError(
                {
                    'status': (
                        f'O custo padrão persistido deve estar em {expected_status} '
                        f'para {action_label}.'
                    )
                }
            )
        return persisted

    @transaction.atomic
    def approve(self, user=None):
        if user is None or not getattr(user, 'pk', None):
            raise ValidationError({'approved_by': 'Aprovação exige usuário identificado.'})
        self._require_transition_origin(self.Status.DRAFT, 'aprovar')
        # Totais calculados somente após a trava da linha.
        self.recalculate(save=False)
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self._domain_transition = (self.Status.DRAFT, self.Status.APPROVED)
        try:
            self.full_clean()
            self.save(
                update_fields=[
                    'status',
                    'total_standard_cost',
                    'approved_by',
                    'approved_at',
                    'updated_at',
                ]
            )
        finally:
            del self._domain_transition

    @transaction.atomic
    def obsolete(self):
        persisted = self._require_transition_origin(self.Status.APPROVED, 'tornar obsoleto')
        self.approved_by_id = persisted['approved_by_id']
        self.approved_at = persisted['approved_at']
        self.status = self.Status.OBSOLETE
        self._domain_transition = (self.Status.APPROVED, self.Status.OBSOLETE)
        try:
            self.full_clean()
            self.save(update_fields=['status', 'updated_at'])
        finally:
            del self._domain_transition

    def clean(self):
        super().clean()
        errors = {}
        persisted = self._persisted_state()
        domain_transition = getattr(self, '_domain_transition', None)
        if persisted is None:
            if self.status != self.Status.DRAFT:
                errors['status'] = 'Custos padrão novos devem ser criados como rascunho.'
            if self.approved_by_id is not None or self.approved_at is not None:
                errors['approved_at'] = 'Rascunhos novos não podem conter evidência de aprovação.'
        else:
            transition = (persisted['status'], self.status)
            if transition[0] != transition[1] and transition != domain_transition:
                errors['status'] = (
                    f'Transição de {transition[0]} para {transition[1]} não permitida diretamente.'
                )
            evidence_changed = (
                self.approved_by_id != persisted['approved_by_id']
                or self.approved_at != persisted['approved_at']
            )
            if evidence_changed and transition != (
                self.Status.DRAFT,
                self.Status.APPROVED,
            ):
                errors['approved_at'] = 'A evidência da aprovação deve ser preservada.'
        if self.standard_quantity <= 0:
            errors['standard_quantity'] = 'A quantidade padrão deve ser maior que zero.'
        if self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = 'A vigência final não pode ser anterior à inicial.'
        if self.status == self.Status.APPROVED and self.approved_at is None:
            errors['approved_at'] = 'A data de aprovação é obrigatória para custos aprovados.'
        for field_name in self._cost_fields():
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O custo não pode ser negativo.'
        if (
            self.status == self.Status.APPROVED
            and self.product
            and not self.product.is_operationally_available
        ):
            errors['product'] = 'A aprovação exige produto aprovado e operacionalmente disponível.'
        if errors:
            raise ValidationError(errors)

    def _cost_fields(self):
        return (
            'material_cost',
            'loss_cost',
            'labor_cost',
            'machine_cost',
            'third_party_cost',
            'analysis_cost',
            'overhead_cost',
            'indirect_cost',
            'tax_cost',
            'total_standard_cost',
        )

        return None

        return None

    def __str__(self):
        return f'{self.product.code} - {self.version}'


class CostSimulation(SingleInstanceModel):
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='cost_simulations', verbose_name='produto'
    )
    formula = models.ForeignKey(
        MasterFormula,
        on_delete=models.PROTECT,
        related_name='cost_simulations',
        null=True,
        blank=True,
        verbose_name='fórmula',
    )
    name = models.CharField('nome', max_length=160)
    batch_size = models.DecimalField('tamanho do lote', max_digits=14, decimal_places=4)
    expected_yield_percent = models.DecimalField(
        'rendimento esperado (%)', max_digits=7, decimal_places=4
    )
    material_cost = models.DecimalField(
        'custo de materiais', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    loss_percent = models.DecimalField(
        'perda (%)', max_digits=7, decimal_places=4, default=ZERO_MONEY
    )
    labor_hours = models.DecimalField(
        'horas de mão de obra', max_digits=10, decimal_places=4, default=ZERO_MONEY
    )
    labor_rate = models.DecimalField(
        'taxa de mão de obra', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    machine_hours = models.DecimalField(
        'horas máquina', max_digits=10, decimal_places=4, default=ZERO_MONEY
    )
    machine_rate = models.DecimalField(
        'taxa máquina', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    third_party_cost = models.DecimalField(
        'custo terceiros', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    analysis_cost = models.DecimalField(
        'custo análises', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    overhead_rate_percent = models.DecimalField(
        'overhead (%)', max_digits=7, decimal_places=4, default=ZERO_MONEY
    )
    indirect_cost = models.DecimalField(
        'custo indireto', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    tax_rate_percent = models.DecimalField(
        'impostos (%)', max_digits=7, decimal_places=4, default=ZERO_MONEY
    )
    capacity_factor_percent = models.DecimalField(
        'fator de capacidade (%)', max_digits=7, decimal_places=4, default=PERCENT_BASE
    )
    simulated_total_cost = models.DecimalField(
        'custo simulado total', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    simulated_unit_cost = models.DecimalField(
        'custo simulado unitário', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    assumptions = models.TextField('premissas', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['product']),
            models.Index(fields=['formula']),
        ]
        verbose_name = 'simulação de custo'
        verbose_name_plural = 'simulações de custo'

    def calculate(self, save=True):
        self.full_clean(validate_unique=False)
        material_with_loss = self.material_cost * (
            Decimal('1.0000') + _percent_factor(self.loss_percent)
        )
        labor = self.labor_hours * self.labor_rate
        machine = self.machine_hours * self.machine_rate
        subtotal = (
            material_with_loss
            + labor
            + machine
            + self.third_party_cost
            + self.analysis_cost
            + self.indirect_cost
        )
        overhead = subtotal * _percent_factor(self.overhead_rate_percent)
        taxable_base = subtotal + overhead
        taxes = taxable_base * _percent_factor(self.tax_rate_percent)
        capacity_factor = _percent_factor(self.capacity_factor_percent)
        total = (taxable_base + taxes) / capacity_factor
        effective_yield = self.batch_size * _percent_factor(self.expected_yield_percent)
        self.simulated_total_cost = _money(total)
        self.simulated_unit_cost = _money(total / effective_yield)
        self.full_clean(validate_unique=False)
        if save:
            self.save(update_fields=['simulated_total_cost', 'simulated_unit_cost', 'updated_at'])
        return self.simulated_total_cost

    def clean(self):
        super().clean()
        errors = {}
        if self.formula and self.product and self.formula.product_id != self.product_id:
            errors['formula'] = 'A fórmula deve pertencer ao produto simulado.'
        if self.batch_size <= 0:
            errors['batch_size'] = 'O tamanho do lote deve ser maior que zero.'
        if self.expected_yield_percent <= 0 or self.expected_yield_percent > PERCENT_BASE:
            errors['expected_yield_percent'] = 'O rendimento esperado deve estar entre 0 e 100%.'
        if self.capacity_factor_percent <= 0:
            errors['capacity_factor_percent'] = 'O fator de capacidade deve ser maior que zero.'
        for field_name in self._numeric_non_negative_fields():
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O valor não pode ser negativo.'
        if errors:
            raise ValidationError(errors)

    def _numeric_non_negative_fields(self):
        return (
            'material_cost',
            'loss_percent',
            'labor_hours',
            'labor_rate',
            'machine_hours',
            'machine_rate',
            'third_party_cost',
            'analysis_cost',
            'overhead_rate_percent',
            'indirect_cost',
            'tax_rate_percent',
            'simulated_total_cost',
            'simulated_unit_cost',
        )

        return None

    def __str__(self):
        return f'{self.name} - {self.product.code}'


class ProductionCostCapture(SingleInstanceModel):
    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.PROTECT,
        related_name='cost_captures',
        verbose_name='ordem de produção',
    )
    period_start = models.DateField('início do período')
    period_end = models.DateField('fim do período')
    planned_cost = models.DecimalField(
        'custo planejado', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_material_cost = models.DecimalField(
        'material real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_loss_cost = models.DecimalField(
        'perda real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_labor_cost = models.DecimalField(
        'mão de obra real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_machine_cost = models.DecimalField(
        'máquina real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_third_party_cost = models.DecimalField(
        'terceiros real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_analysis_cost = models.DecimalField(
        'análises real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_overhead_cost = models.DecimalField(
        'overhead real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    actual_indirect_cost = models.DecimalField(
        'indireto real', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    non_quality_cost = models.DecimalField(
        'custo de não qualidade', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    rework_cost = models.DecimalField(
        'custo de retrabalho', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    total_actual_cost = models.DecimalField(
        'custo real total', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    variance_amount = models.DecimalField(
        'variação', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-period_start', 'production_order__order_number']
        constraints = [
            models.UniqueConstraint(
                fields=['production_order', 'period_start', 'period_end'],
                name='unique_order_cost_period',
            ),
        ]
        indexes = [
            models.Index(fields=['production_order']),
            models.Index(fields=['period_start', 'period_end']),
        ]
        verbose_name = 'captura de custo de produção'
        verbose_name_plural = 'capturas de custo de produção'

    def calculate_actuals(self, save=True):
        self.total_actual_cost = _money(
            self.actual_material_cost
            + self.actual_loss_cost
            + self.actual_labor_cost
            + self.actual_machine_cost
            + self.actual_third_party_cost
            + self.actual_analysis_cost
            + self.actual_overhead_cost
            + self.actual_indirect_cost
            + self.non_quality_cost
            + self.rework_cost
        )
        self.variance_amount = _money(self.total_actual_cost - self.planned_cost)
        self.full_clean(validate_unique=False)
        if save:
            self.save(update_fields=['total_actual_cost', 'variance_amount', 'updated_at'])
        return self.total_actual_cost

    def clean(self):
        super().clean()
        errors = {}
        if self.period_end < self.period_start:
            errors['period_end'] = 'O fim do período não pode ser anterior ao início.'
        elif (self.period_start.year, self.period_start.month) != (
            self.period_end.year,
            self.period_end.month,
        ):
            errors['period_end'] = 'A captura de custo deve permanecer no mesmo mês contábil.'
        for field_name in self._cost_fields():
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O custo não pode ser negativo.'
        if self._period_is_closed():
            errors['period_start'] = 'O período de custos está fechado.'
        if errors:
            raise ValidationError(errors)

    def _period_is_closed(self):
        if not self.period_start:
            return False
        return MonthlyCostClosing.objects.filter(
            period_year=self.period_start.year,
            period_month=self.period_start.month,
            status=MonthlyCostClosing.Status.CLOSED,
        ).exists()

    def _cost_fields(self):
        return (
            'planned_cost',
            'actual_material_cost',
            'actual_loss_cost',
            'actual_labor_cost',
            'actual_machine_cost',
            'actual_third_party_cost',
            'actual_analysis_cost',
            'actual_overhead_cost',
            'actual_indirect_cost',
            'non_quality_cost',
            'rework_cost',
            'total_actual_cost',
        )

        return None

    def __str__(self):
        return f'{self.production_order.order_number} - {self.period_start:%Y-%m}'


class MonthlyCostClosing(SingleInstanceModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        VALIDATED = 'validated', 'Validado'
        CLOSED = 'closed', 'Fechado'
        REOPENED = 'reopened', 'Reaberto'

    period_year = models.PositiveSmallIntegerField('ano')
    period_month = models.PositiveSmallIntegerField('mês')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    validation_notes = models.TextField('observações de validação', blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_cost_periods',
        null=True,
        blank=True,
        verbose_name='fechado por',
    )
    closed_at = models.DateTimeField('fechado em', null=True, blank=True)

    class Meta:
        ordering = ['-period_year', '-period_month']
        constraints = [
            models.UniqueConstraint(
                fields=['period_year', 'period_month'], name='unique_cost_period'
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['period_year', 'period_month']),
        ]
        verbose_name = 'fechamento mensal de custo'
        verbose_name_plural = 'fechamentos mensais de custo'

    def validate_period(self, notes=''):
        if self.status not in {self.Status.OPEN, self.Status.REOPENED}:
            raise ValidationError(
                {'status': 'Somente períodos abertos ou reabertos podem ser validados.'}
            )
        self.status = self.Status.VALIDATED
        self.validation_notes = notes
        self.closed_by = None
        self.closed_at = None
        self.full_clean()
        self.save(
            update_fields=['status', 'validation_notes', 'closed_by', 'closed_at', 'updated_at']
        )

    @transaction.atomic
    def close(self, user=None):
        if self.pk is None:
            raise ValidationError({'status': 'Salve o período antes de fechá-lo.'})
        closing = type(self).objects.select_for_update().get(pk=self.pk)
        if closing.status != self.Status.VALIDATED:
            raise ValidationError({'status': 'O fechamento exige período validado.'})
        closing.status = self.Status.CLOSED
        closing.closed_by = user
        closing.closed_at = timezone.now()
        closing.full_clean()
        closing.save(update_fields=['status', 'closed_by', 'closed_at', 'updated_at'])
        self.status = closing.status
        self.closed_by = closing.closed_by
        self.closed_at = closing.closed_at
        self.updated_at = closing.updated_at

    def reopen(self, reason, user=None):
        if self.status != self.Status.CLOSED:
            raise ValidationError({'status': 'Somente períodos fechados podem ser reabertos.'})
        if not reason:
            raise ValidationError({'validation_notes': 'Informe a justificativa de reabertura.'})
        self.status = self.Status.REOPENED
        self.validation_notes = reason
        self.closed_by = None
        self.closed_at = None
        self.full_clean()
        self.save(
            update_fields=['status', 'validation_notes', 'closed_by', 'closed_at', 'updated_at']
        )

    def clean(self):
        super().clean()
        errors = {}
        if not 1 <= self.period_month <= 12:
            errors['period_month'] = 'O mês deve estar entre 1 e 12.'
        if self.period_year < 2000:
            errors['period_year'] = 'Informe um ano válido.'
        if self.status == self.Status.CLOSED and not self.closed_at:
            errors['closed_at'] = 'O fechamento deve registrar data e hora.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.period_year:04d}-{self.period_month:02d} - {self.get_status_display()}'


class CostReportSnapshot(SingleInstanceModel):
    class ReportType(models.TextChoices):
        MARGIN = 'margin', 'Margem'
        LOT_COST = 'lot_cost', 'Custo por lote'
        PRODUCT_COST = 'product_cost', 'Custo por produto'
        NON_QUALITY = 'non_quality', 'Não qualidade'
        DEVIATION_REWORK = 'deviation_rework', 'Desvios e retrabalho'

    report_type = models.CharField('tipo de relatório', max_length=32, choices=ReportType.choices)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='cost_report_snapshots',
        null=True,
        blank=True,
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='cost_report_snapshots',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    production_order = models.ForeignKey(
        ProductionOrder,
        on_delete=models.PROTECT,
        related_name='cost_report_snapshots',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    period_start = models.DateField('início do período')
    period_end = models.DateField('fim do período')
    revenue_amount = models.DecimalField(
        'receita', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    cost_amount = models.DecimalField('custo', max_digits=14, decimal_places=4, default=ZERO_MONEY)
    margin_amount = models.DecimalField(
        'margem', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    margin_percent = models.DecimalField(
        'margem (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    non_quality_cost = models.DecimalField(
        'custo de não qualidade', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    deviation_impact = models.DecimalField(
        'impacto de desvios', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    rework_impact = models.DecimalField(
        'impacto de retrabalho', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    generated_at = models.DateTimeField('gerado em', default=timezone.now)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-generated_at']
        indexes = [
            models.Index(fields=['report_type']),
            models.Index(fields=['product']),
            models.Index(fields=['period_start', 'period_end']),
        ]
        verbose_name = 'snapshot de relatório de custo'
        verbose_name_plural = 'snapshots de relatórios de custo'

    def calculate_margin(self, save=True):
        self.margin_amount = _money(self.revenue_amount - self.cost_amount)
        if self.revenue_amount:
            self.margin_percent = _money((self.margin_amount / self.revenue_amount) * PERCENT_BASE)
        else:
            self.margin_percent = ZERO_MONEY
        self.full_clean(validate_unique=False)
        if save:
            self.save(update_fields=['margin_amount', 'margin_percent', 'updated_at'])
        return self.margin_amount

    def clean(self):
        super().clean()
        errors = {}
        if self.period_end < self.period_start:
            errors['period_end'] = 'O fim do período não pode ser anterior ao início.'
        for field_name in (
            'revenue_amount',
            'cost_amount',
            'non_quality_cost',
            'deviation_impact',
            'rework_impact',
        ):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O valor não pode ser negativo.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.get_report_type_display()} - {self.period_start:%Y-%m}'
