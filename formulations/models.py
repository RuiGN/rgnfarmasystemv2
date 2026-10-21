from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from masters.models import Product, UnitOfMeasure


class ReleasedVersionMixin:
    effective_from: Any
    effective_to: Any
    status: Any
    Status: Any

    def is_effective_on(self, date=None):
        reference_date = date or timezone.localdate()
        if self.effective_from and self.effective_from > reference_date:
            return False
        if self.effective_to and self.effective_to < reference_date:
            return False
        return True

    @property
    def is_released(self):
        return self.status == self.Status.APPROVED and self.is_effective_on()


class MasterFormula(AutoCodeMixin, ReleasedVersionMixin, SingleInstanceModel):
    CODE_PREFIX = 'MF'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        IN_REVIEW = 'in_review', 'Em revisão'
        APPROVED = 'approved', 'Aprovada'
        OBSOLETE = 'obsolete', 'Obsoleta'

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='formulas',
        verbose_name='produto',
    )
    code = models.CharField('código', max_length=80, blank=True)
    version = models.PositiveIntegerField('versão')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    batch_size = models.DecimalField('tamanho do lote', max_digits=14, decimal_places=4)
    batch_unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='formula_batches',
        verbose_name='unidade do lote',
    )
    expected_yield_percent = models.DecimalField(
        'rendimento esperado %',
        max_digits=7,
        decimal_places=4,
        default=Decimal('100.0000'),
    )
    effective_from = models.DateField('vigente a partir de', null=True, blank=True)
    effective_to = models.DateField('vigente até', null=True, blank=True)
    copied_from = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='copies',
        null=True,
        blank=True,
        verbose_name='copiada de',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_formulas',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'version'],
                name='unique_formula_product_version',
            ),
            models.UniqueConstraint(fields=['code', 'version'], name='unique_formula_code_version'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['code', 'version']),
        ]
        verbose_name = 'fórmula mestra'
        verbose_name_plural = 'fórmulas mestras'

    def clean(self):
        super().clean()
        errors = {}

        if self.batch_size is not None and self.batch_size <= 0:
            errors['batch_size'] = 'O tamanho do lote deve ser maior que zero.'
        if self.expected_yield_percent is not None and (
            self.expected_yield_percent <= 0 or self.expected_yield_percent > 100
        ):
            errors['expected_yield_percent'] = 'O rendimento esperado deve estar entre 0 e 100.'
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = (
                'A data final de vigência não pode ser anterior à data inicial.'
            )
        if self.status == self.Status.APPROVED:
            if (
                not (self.product_id or self._state.fields_cache.get('product'))
                or not self.product.is_operationally_available
            ):
                errors['product'] = (
                    'A fórmula aprovada exige produto aprovado e operacionalmente disponível.'
                )
            if not self.effective_from:
                errors['effective_from'] = 'A fórmula aprovada exige data inicial de vigência.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.code} v{self.version} - {self.product.code}'


class FormulaComponent(SingleInstanceModel):
    class Role(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        EXCIPIENT = 'excipient', 'Excipiente'
        PACKAGING = 'packaging', 'Embalagem'
        PROCESS_AID = 'process_aid', 'Auxiliar de processo'

    formula = models.ForeignKey(
        MasterFormula,
        on_delete=models.CASCADE,
        related_name='components',
        verbose_name='fórmula',
    )
    line_number = models.PositiveIntegerField('linha')
    material = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='formula_components',
        verbose_name='material',
    )
    role = models.CharField('função', max_length=24, choices=Role.choices, default=Role.EXCIPIENT)
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='formula_components',
        verbose_name='unidade',
    )
    expected_loss_percent = models.DecimalField(
        'perda prevista %',
        max_digits=7,
        decimal_places=4,
        default=Decimal('0.0000'),
    )
    conversion_factor = models.DecimalField(
        'fator de conversão',
        max_digits=14,
        decimal_places=6,
        default=Decimal('1.000000'),
    )
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['formula', 'line_number']
        constraints = [
            models.UniqueConstraint(
                fields=['formula', 'line_number'], name='unique_formula_component_line'
            ),
        ]
        indexes = [
            models.Index(fields=['material']),
            models.Index(fields=['formula', 'line_number']),
        ]
        verbose_name = 'componente da fórmula'
        verbose_name_plural = 'componentes da fórmula'

    @property
    def planned_quantity_with_loss(self):
        factor = Decimal('1.0000') + (self.expected_loss_percent / Decimal('100.0000'))
        return (self.quantity * factor).quantize(Decimal('0.0001'))

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity is not None and self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.expected_loss_percent is not None and self.expected_loss_percent < 0:
            errors['expected_loss_percent'] = 'A perda prevista não pode ser negativa.'
        if self.conversion_factor is not None and self.conversion_factor <= 0:
            errors['conversion_factor'] = 'O fator de conversão deve ser maior que zero.'
        if (
            (self.formula_id or self._state.fields_cache.get('formula'))
            and self.formula.status == MasterFormula.Status.APPROVED
            and (not self.material_id or not self.material.is_operationally_available)
        ):
            errors['material'] = (
                'Fórmula aprovada exige material aprovado e operacionalmente disponível.'
            )
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.formula.code} #{self.line_number} - {self.material.code}'


class ManufacturingRoute(AutoCodeMixin, ReleasedVersionMixin, SingleInstanceModel):
    CODE_PREFIX = 'RT'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        IN_REVIEW = 'in_review', 'Em revisão'
        APPROVED = 'approved', 'Aprovado'
        OBSOLETE = 'obsolete', 'Obsoleto'

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='routes',
        verbose_name='produto',
    )
    formula = models.ForeignKey(
        MasterFormula,
        on_delete=models.PROTECT,
        related_name='routes',
        null=True,
        blank=True,
        verbose_name='fórmula',
    )
    code = models.CharField('código', max_length=80, blank=True)
    version = models.PositiveIntegerField('versão')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateField('vigente a partir de', null=True, blank=True)
    effective_to = models.DateField('vigente até', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'version'], name='unique_route_product_version'
            ),
            models.UniqueConstraint(fields=['code', 'version'], name='unique_route_code_version'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['product', 'status']),
            models.Index(fields=['code', 'version']),
        ]
        verbose_name = 'roteiro de fabricação'
        verbose_name_plural = 'roteiros de fabricação'

    @property
    def is_released(self):
        if not super().is_released:
            return False
        if self.formula and not self.formula.is_released:
            return False
        return True

    def clean(self):
        super().clean()
        errors = {}
        if self.formula and self.formula.product_id != self.product_id:
            errors['formula'] = 'A fórmula deve pertencer ao mesmo produto do roteiro.'
        if self.effective_from and self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = (
                'A data final de vigência não pode ser anterior à data inicial.'
            )
        if self.status == self.Status.APPROVED:
            if not self.product.is_operationally_available:
                errors['product'] = (
                    'O roteiro aprovado exige produto aprovado e operacionalmente disponível.'
                )
            if not self.effective_from:
                errors['effective_from'] = 'O roteiro aprovado exige data inicial de vigência.'
            if self.formula and not self.formula.is_released:
                errors['formula'] = 'O roteiro aprovado exige fórmula aprovada e vigente.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.code} v{self.version} - {self.product.code}'


class RouteStep(SingleInstanceModel):
    route = models.ForeignKey(
        ManufacturingRoute,
        on_delete=models.CASCADE,
        related_name='steps',
        verbose_name='roteiro',
    )
    sequence = models.PositiveIntegerField('sequência')
    operation = models.CharField('operação', max_length=160)
    work_center = models.CharField('centro de trabalho', max_length=160)
    resource = models.CharField('recurso', max_length=160, blank=True)
    setup_time_minutes = models.DecimalField(
        'tempo de setup em minutos',
        max_digits=10,
        decimal_places=2,
        default=Decimal('0.00'),
    )
    standard_time_minutes = models.DecimalField(
        'tempo padrão em minutos', max_digits=10, decimal_places=2
    )
    critical_parameters = models.TextField('parâmetros críticos', blank=True)
    instructions = models.TextField('instruções', blank=True)

    class Meta:
        ordering = ['route', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['route', 'sequence'], name='unique_route_step_sequence'
            ),
        ]
        indexes = [
            models.Index(fields=['route']),
            models.Index(fields=['route', 'sequence']),
        ]
        verbose_name = 'etapa do roteiro'
        verbose_name_plural = 'etapas do roteiro'

    def clean(self):
        super().clean()
        errors = {}
        if False:
            errors['route'] = 'O roteiro relacionado é incompatível com o registro.'
        if self.setup_time_minutes < 0:
            errors['setup_time_minutes'] = 'O tempo de setup não pode ser negativo.'
        if self.standard_time_minutes <= 0:
            errors['standard_time_minutes'] = 'O tempo padrão deve ser maior que zero.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.route.code} - {self.sequence} {self.operation}'
