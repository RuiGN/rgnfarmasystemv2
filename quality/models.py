from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import IdentifierSpec, sequence_code
from inventory.models import StockQualityStatus
from masters.models import Product, UnitOfMeasure


DECIMAL_SCALE = Decimal('0.0001')
ZERO_DECIMAL = Decimal('0.0000')


def _decimal(value):
    try:
        amount = Decimal(str(value or ZERO_DECIMAL))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError('Informe um número válido.') from exc
    return amount.quantize(DECIMAL_SCALE, rounding=ROUND_HALF_UP)


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


def _validate_limit_pair(errors, lower_field, upper_field, lower_value, upper_value):
    if lower_value is not None and upper_value is not None and lower_value > upper_value:
        errors[upper_field] = (
            f'O limite superior de {upper_field} não pode ser menor que {lower_field}.'
        )


class AnalyticalSpecification(SingleInstanceModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovada'
        OBSOLETE = 'obsolete', 'Obsoleta'

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='analytical_specifications',
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='analytical_specifications',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    version = models.CharField('versão', max_length=40)
    method_code = models.CharField('código do método', max_length=80)
    method_name = models.CharField('método', max_length=160)
    parameter_name = models.CharField('parâmetro', max_length=160)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='analytical_specifications',
        null=True,
        blank=True,
        verbose_name='unidade',
    )
    lower_limit = models.DecimalField(
        'limite inferior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    upper_limit = models.DecimalField(
        'limite superior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    alert_lower_limit = models.DecimalField(
        'alerta inferior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    alert_upper_limit = models.DecimalField(
        'alerta superior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    action_lower_limit = models.DecimalField(
        'ação inferior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    action_upper_limit = models.DecimalField(
        'ação superior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    trend_lower_limit = models.DecimalField(
        'tendência inferior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    trend_upper_limit = models.DecimalField(
        'tendência superior', max_digits=14, decimal_places=4, null=True, blank=True
    )
    acceptance_criteria = models.TextField('critério de aceitação', blank=True)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    effective_from = models.DateField('vigência inicial')
    effective_to = models.DateField('vigência final', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_analytical_specifications',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code', 'parameter_name', 'version']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'product',
                    'stock_lot',
                    'version',
                    'method_code',
                    'parameter_name',
                ],
                name='unique_qc_spec_product_lot_version',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'status']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['method_code']),
            models.Index(fields=['effective_from', 'effective_to']),
        ]
        verbose_name = 'especificação analítica'
        verbose_name_plural = 'especificações analíticas'

    def _require_status(self, allowed_statuses):
        if self.status not in allowed_statuses:
            allowed_labels = ', '.join(allowed_statuses)
            raise ValidationError(
                {'status': f'Transição inválida. Status esperado: {allowed_labels}.'}
            )

    def approve(self, user=None):
        self._require_status({self.Status.DRAFT, self.Status.APPROVED})
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def obsolete(self):
        self._require_status({self.Status.APPROVED})
        self.status = self.Status.OBSOLETE
        self.save(update_fields=['status', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        for field in ('product', 'stock_lot', 'unit'):
            pass
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto da especificação.'
        if self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = 'A vigência final não pode ser anterior à inicial.'
        if not self.acceptance_criteria and self.lower_limit is None and self.upper_limit is None:
            errors['acceptance_criteria'] = 'Informe limites numéricos ou critério de aceitação.'
        _validate_limit_pair(
            errors, 'lower_limit', 'upper_limit', self.lower_limit, self.upper_limit
        )
        _validate_limit_pair(
            errors,
            'alert_lower_limit',
            'alert_upper_limit',
            self.alert_lower_limit,
            self.alert_upper_limit,
        )
        _validate_limit_pair(
            errors,
            'action_lower_limit',
            'action_upper_limit',
            self.action_lower_limit,
            self.action_upper_limit,
        )
        _validate_limit_pair(
            errors,
            'trend_lower_limit',
            'trend_upper_limit',
            self.trend_lower_limit,
            self.trend_upper_limit,
        )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.product.code} - {self.parameter_name} ({self.version})'


class QualitySample(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('sample_number', 'AMO'),)

    class SampleType(models.TextChoices):
        RECEIPT = 'receipt', 'Recebimento'
        PRODUCTION = 'production', 'Produção'
        STABILITY = 'stability', 'Estabilidade'
        VALIDATION = 'validation', 'Validação'
        COMPLAINT = 'complaint', 'Reclamação'
        INVESTIGATION = 'investigation', 'Investigação'
        ENVIRONMENTAL = 'environmental', 'Monitoramento ambiental'

    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Solicitada'
        COLLECTED = 'collected', 'Coletada'
        RECEIVED = 'received', 'Recebida'
        IN_ANALYSIS = 'in_analysis', 'Em análise'
        REVIEWED = 'reviewed', 'Revisada'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Reprovada'
        CANCELLED = 'cancelled', 'Cancelada'

    sample_number = models.CharField('amostra', max_length=80, blank=True)
    sample_type = models.CharField('tipo', max_length=32, choices=SampleType.choices)
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='quality_samples', verbose_name='produto'
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    specification = models.ForeignKey(
        AnalyticalSpecification,
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='especificação',
    )
    source_purchase_receipt = models.ForeignKey(
        'procurement.PurchaseReceipt',
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='recebimento de compra',
    )
    source_production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    customer_complaint = models.ForeignKey(
        'crm.CustomerComplaint',
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='reclamação de cliente',
    )
    quantity = models.DecimalField(
        'quantidade', max_digits=14, decimal_places=4, default=Decimal('1.0000')
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='unidade',
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.REQUESTED
    )
    collection_point = models.CharField('ponto de coleta', max_length=180, blank=True)
    collection_site = models.ForeignKey(
        'masters.Site',
        on_delete=models.PROTECT,
        related_name='quality_samples',
        null=True,
        blank=True,
        verbose_name='unidade/planta de coleta',
    )
    collected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='collected_quality_samples',
        null=True,
        blank=True,
        verbose_name='coletada por',
    )
    collected_at = models.DateTimeField('coletada em', null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='received_quality_samples',
        null=True,
        blank=True,
        verbose_name='recebida por',
    )
    received_at = models.DateTimeField('recebida em', null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_quality_samples',
        null=True,
        blank=True,
        verbose_name='iniciada por',
    )
    started_at = models.DateTimeField('iniciada em', null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reviewed_quality_samples',
        null=True,
        blank=True,
        verbose_name='revisada por',
    )
    reviewed_at = models.DateTimeField('revisada em', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_quality_samples',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rejected_quality_samples',
        null=True,
        blank=True,
        verbose_name='reprovada por',
    )
    rejected_at = models.DateTimeField('reprovada em', null=True, blank=True)
    rejection_reason = models.TextField('motivo da reprovação', blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['sample_number'], name='unique_quality_sample_number'),
        ]
        indexes = [
            models.Index(fields=['sample_type', 'status']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['sample_number']),
        ]
        verbose_name = 'amostra de qualidade'
        verbose_name_plural = 'amostras de qualidade'

    def save(self, *args, **kwargs):
        if not self.sample_number:
            self.sample_number = _sequence_code(QualitySample, 'sample_number', 'AMO')
        super().save(*args, **kwargs)

    def collect(self, user=None):
        self._require_status({self.Status.REQUESTED})
        self.status = self.Status.COLLECTED
        self.collected_by = user
        self.collected_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'collected_by', 'collected_at', 'updated_at'])

    def receive(self, user=None):
        self._require_status({self.Status.COLLECTED})
        self.status = self.Status.RECEIVED
        self.received_by = user
        self.received_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'received_by', 'received_at', 'updated_at'])

    def start_analysis(self, user=None):
        self._require_status({self.Status.RECEIVED})
        self.status = self.Status.IN_ANALYSIS
        self.started_by = user
        self.started_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'started_by', 'started_at', 'updated_at'])

    def review(self, user=None):
        self._require_status({self.Status.IN_ANALYSIS})
        self.status = self.Status.REVIEWED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])

    def approve(self, user=None):
        self._require_status({self.Status.REVIEWED})
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        if self.stock_lot_id:
            self.stock_lot.quality_status = StockQualityStatus.APPROVED
            self.stock_lot.save(update_fields=['quality_status', 'updated_at'])

    def reject(self, reason, user=None):
        if not reason:
            raise ValidationError({'rejection_reason': 'Informe o motivo da reprovação.'})
        if self.status in {self.Status.APPROVED, self.Status.CANCELLED}:
            raise ValidationError(
                {'status': 'Amostras aprovadas ou canceladas não podem ser reprovadas.'}
            )
        self.status = self.Status.REJECTED
        self.rejection_reason = reason
        self.rejected_by = user
        self.rejected_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=['status', 'rejection_reason', 'rejected_by', 'rejected_at', 'updated_at']
        )
        if self.stock_lot_id:
            self.stock_lot.quality_status = StockQualityStatus.REJECTED
            self.stock_lot.save(update_fields=['quality_status', 'updated_at'])

    def cancel(self, reason):
        if not reason:
            raise ValidationError({'rejection_reason': 'Informe a justificativa do cancelamento.'})
        self._require_status(
            {
                self.Status.REQUESTED,
                self.Status.COLLECTED,
                self.Status.RECEIVED,
                self.Status.IN_ANALYSIS,
                self.Status.REVIEWED,
            }
        )
        self.status = self.Status.CANCELLED
        self.rejection_reason = reason
        self.save(update_fields=['status', 'rejection_reason', 'updated_at'])

    def create_analysis(self, method_reference=''):
        return QualityAnalysis.objects.create(
            sample=self,
            specification=self.specification,
            method_reference=method_reference
            or (self.specification.method_code if self.specification else ''),
        )

    def _require_status(self, allowed_statuses):
        if self.status not in allowed_statuses:
            allowed_labels = ', '.join(allowed_statuses)
            raise ValidationError(
                {'status': f'Transição inválida. Status esperado: {allowed_labels}.'}
            )

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'product',
            'stock_lot',
            'specification',
            'source_purchase_receipt',
            'source_production_order',
            'customer_complaint',
            'unit',
        ):
            pass
        for field in (
            'collected_by',
            'received_by',
            'started_by',
            'reviewed_by',
            'approved_by',
            'rejected_by',
        ):
            pass
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto da amostra.'
        if self.specification and self.product and self.specification.product_id != self.product_id:
            errors['specification'] = 'A especificação deve pertencer ao produto da amostra.'
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.sample_number


class QualityAnalysis(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('analysis_number', 'ANA'),)

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        IN_PROGRESS = 'in_progress', 'Em execução'
        COMPLETED = 'completed', 'Concluída'
        REVIEWED = 'reviewed', 'Revisada'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Rejeitada'

    analysis_number = models.CharField('análise', max_length=80, blank=True)
    sample = models.ForeignKey(
        QualitySample, on_delete=models.CASCADE, related_name='analyses', verbose_name='amostra'
    )
    specification = models.ForeignKey(
        AnalyticalSpecification,
        on_delete=models.PROTECT,
        related_name='analyses',
        null=True,
        blank=True,
        verbose_name='especificação',
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    method_reference = models.CharField('método executado', max_length=120, blank=True)
    reagent_lot = models.CharField('lote do reagente', max_length=80, blank=True)
    standard_lot = models.CharField('lote do padrão', max_length=80, blank=True)
    analyst = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quality_analyses_as_analyst',
        null=True,
        blank=True,
        verbose_name='analista',
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quality_analyses_as_reviewer',
        null=True,
        blank=True,
        verbose_name='revisor',
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='quality_analyses_as_approver',
        null=True,
        blank=True,
        verbose_name='aprovador',
    )
    started_at = models.DateTimeField('iniciada em', null=True, blank=True)
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)
    reviewed_at = models.DateTimeField('revisada em', null=True, blank=True)
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    rejected_reason = models.TextField('motivo da rejeição', blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['analysis_number'], name='unique_quality_analysis_number'
            ),
        ]
        indexes = [
            models.Index(fields=['sample', 'status']),
            models.Index(fields=['specification']),
            models.Index(fields=['analysis_number']),
        ]
        verbose_name = 'análise de qualidade'
        verbose_name_plural = 'análises de qualidade'

    def save(self, *args, **kwargs):
        if not self.analysis_number:
            self.analysis_number = _sequence_code(QualityAnalysis, 'analysis_number', 'ANA')
        super().save(*args, **kwargs)

    def start(self, user=None):
        self._require_status({self.Status.PENDING})
        self.status = self.Status.IN_PROGRESS
        self.analyst = user
        self.started_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'analyst', 'started_at', 'updated_at'])

    def complete(self):
        self._require_status({self.Status.IN_PROGRESS})
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])

    def _require_not_analyst(self, user, field):
        if user is not None and self.analyst_id and self.analyst_id == user.pk:
            raise ValidationError(
                {
                    field: 'Segregação de funções: o analista não pode revisar ou aprovar a própria análise.'
                }
            )

    def review(self, user=None):
        self._require_status({self.Status.COMPLETED})
        self._require_not_analyst(user, 'reviewer')
        self.status = self.Status.REVIEWED
        self.reviewer = user
        self.reviewed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'reviewer', 'reviewed_at', 'updated_at'])

    def approve(self, user=None):
        self._require_status({self.Status.REVIEWED})
        self._require_not_analyst(user, 'approver')
        self.status = self.Status.APPROVED
        self.approver = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approver', 'approved_at', 'updated_at'])

    def reject(self, reason, user=None):
        if not reason:
            raise ValidationError({'rejected_reason': 'Informe o motivo da rejeição.'})
        if self.status == self.Status.APPROVED:
            raise ValidationError({'status': 'Análises aprovadas não podem ser rejeitadas.'})
        self.status = self.Status.REJECTED
        self.approver = user
        self.rejected_reason = reason
        self.full_clean()
        self.save(update_fields=['status', 'approver', 'rejected_reason', 'updated_at'])

    def _require_status(self, allowed_statuses):
        if self.status not in allowed_statuses:
            allowed_labels = ', '.join(allowed_statuses)
            raise ValidationError(
                {'status': f'Transição inválida. Status esperado: {allowed_labels}.'}
            )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('analyst', 'reviewer', 'approver'):
            pass
        if (
            self.specification
            and self.sample
            and self.specification.product_id != self.sample.product_id
        ):
            errors['specification'] = 'A especificação deve pertencer ao produto da amostra.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.analysis_number


class QualityResult(SingleInstanceModel):
    class ResultType(models.TextChoices):
        QUANTITATIVE = 'quantitative', 'Quantitativo'
        QUALITATIVE = 'qualitative', 'Qualitativo'

    class ResultStatus(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        COMPLIANT = 'compliant', 'Conforme'
        ALERT_LIMIT = 'alert_limit', 'Limite de alerta'
        ACTION_LIMIT = 'action_limit', 'Limite de ação'
        OUT_OF_TREND = 'out_of_trend', 'OOT'
        OUT_OF_SPECIFICATION = 'out_of_specification', 'OOS'

    analysis = models.ForeignKey(
        QualityAnalysis, on_delete=models.CASCADE, related_name='results', verbose_name='análise'
    )
    specification = models.ForeignKey(
        AnalyticalSpecification,
        on_delete=models.PROTECT,
        related_name='results',
        null=True,
        blank=True,
        verbose_name='especificação',
    )
    parameter_name = models.CharField('parâmetro', max_length=160)
    result_type = models.CharField('tipo', max_length=24, choices=ResultType.choices)
    numeric_result = models.DecimalField(
        'resultado numérico', max_digits=14, decimal_places=4, null=True, blank=True
    )
    text_result = models.CharField('resultado textual', max_length=255, blank=True)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='quality_results',
        null=True,
        blank=True,
        verbose_name='unidade',
    )
    result_status = models.CharField(
        'status do resultado',
        max_length=32,
        choices=ResultStatus.choices,
        default=ResultStatus.PENDING,
    )
    attachment_reference = models.CharField('anexo', max_length=255, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorded_quality_results',
        null=True,
        blank=True,
        verbose_name='registrado por',
    )
    recorded_at = models.DateTimeField('registrado em', default=timezone.now)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['analysis__analysis_number', 'parameter_name']
        indexes = [
            models.Index(fields=['analysis']),
            models.Index(fields=['specification']),
            models.Index(fields=['result_status']),
            models.Index(fields=['parameter_name']),
        ]
        verbose_name = 'resultado analítico'
        verbose_name_plural = 'resultados analíticos'

    @property
    def is_blocking(self):
        return self.result_status in {
            self.ResultStatus.OUT_OF_SPECIFICATION,
            self.ResultStatus.ACTION_LIMIT,
        }

    def evaluate(self, save=True):
        if self.result_type == self.ResultType.QUALITATIVE:
            normalized = self.text_result.strip().lower()
            self.result_status = (
                self.ResultStatus.COMPLIANT
                if normalized in {'aprovado', 'conforme', 'pass', 'passed'}
                else self.ResultStatus.OUT_OF_SPECIFICATION
            )
        else:
            if self.numeric_result is None:
                raise ValidationError(
                    {'numeric_result': 'Resultado quantitativo exige valor numérico.'}
                )
            spec = self.specification
            if spec is None:
                self.result_status = self.ResultStatus.COMPLIANT
            elif self._outside(self.numeric_result, spec.lower_limit, spec.upper_limit):
                self.result_status = self.ResultStatus.OUT_OF_SPECIFICATION
            elif self._outside(
                self.numeric_result, spec.action_lower_limit, spec.action_upper_limit
            ):
                self.result_status = self.ResultStatus.ACTION_LIMIT
            elif self._outside(self.numeric_result, spec.trend_lower_limit, spec.trend_upper_limit):
                self.result_status = self.ResultStatus.OUT_OF_TREND
            elif self._outside(self.numeric_result, spec.alert_lower_limit, spec.alert_upper_limit):
                self.result_status = self.ResultStatus.ALERT_LIMIT
            else:
                self.result_status = self.ResultStatus.COMPLIANT
        self.full_clean()
        if save:
            self.save(update_fields=['result_status', 'updated_at'])
        return self.result_status

    def _outside(self, value, lower, upper):
        if lower is not None and value < lower:
            return True
        if upper is not None and value > upper:
            return True
        return False

    def clean(self):
        super().clean()
        errors = {}
        for field in ('analysis', 'specification', 'unit'):
            pass
        if (
            self.specification
            and self.analysis
            and self.specification.product_id != self.analysis.sample.product_id
        ):
            errors['specification'] = 'A especificação deve pertencer ao produto da amostra.'
        if self.result_type == self.ResultType.QUANTITATIVE and self.numeric_result is None:
            errors['numeric_result'] = 'Resultado quantitativo exige valor numérico.'
        if self.result_type == self.ResultType.QUALITATIVE and not self.text_result:
            errors['text_result'] = 'Resultado qualitativo exige valor textual.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.analysis} - {self.parameter_name}'


class LaboratoryInvestigation(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('investigation_number', 'INV'),)

    class InvestigationType(models.TextChoices):
        LABORATORY = 'laboratory', 'Investigação laboratorial'
        REPEAT = 'repeat', 'Repetição justificada'
        RETEST = 'retest', 'Reteste'
        RESAMPLING = 'resampling', 'Reamostragem'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        CONCLUDED = 'concluded', 'Concluída'
        CANCELLED = 'cancelled', 'Cancelada'

    investigation_number = models.CharField('investigação', max_length=80, blank=True)
    sample = models.ForeignKey(
        QualitySample,
        on_delete=models.PROTECT,
        related_name='investigations',
        verbose_name='amostra',
    )
    analysis = models.ForeignKey(
        QualityAnalysis,
        on_delete=models.PROTECT,
        related_name='investigations',
        null=True,
        blank=True,
        verbose_name='análise',
    )
    result = models.ForeignKey(
        QualityResult,
        on_delete=models.PROTECT,
        related_name='investigations',
        null=True,
        blank=True,
        verbose_name='resultado',
    )
    investigation_type = models.CharField('tipo', max_length=24, choices=InvestigationType.choices)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    justification = models.TextField('justificativa')
    root_cause = models.TextField('causa raiz', blank=True)
    conclusion = models.TextField('conclusão', blank=True)
    repeat_justification = models.TextField('justificativa de repetição', blank=True)
    retest_justification = models.TextField('justificativa de reteste', blank=True)
    resampling_justification = models.TextField('justificativa de reamostragem', blank=True)
    repeat_approved = models.BooleanField('repetição aprovada', default=False)
    retest_approved = models.BooleanField('reteste aprovado', default=False)
    resampling_approved = models.BooleanField('reamostragem aprovada', default=False)
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='opened_laboratory_investigations',
        null=True,
        blank=True,
        verbose_name='aberta por',
    )
    opened_at = models.DateTimeField('aberta em', default=timezone.now)
    started_at = models.DateTimeField('iniciada em', null=True, blank=True)
    concluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='concluded_laboratory_investigations',
        null=True,
        blank=True,
        verbose_name='concluída por',
    )
    concluded_at = models.DateTimeField('concluída em', null=True, blank=True)

    class Meta:
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(
                fields=['investigation_number'],
                name='unique_lab_investigation_number',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'investigation_type']),
            models.Index(fields=['sample']),
            models.Index(fields=['result']),
            models.Index(fields=['investigation_number']),
        ]
        verbose_name = 'investigação laboratorial'
        verbose_name_plural = 'investigações laboratoriais'

    def save(self, *args, **kwargs):
        if not self.investigation_number:
            self.investigation_number = _sequence_code(
                LaboratoryInvestigation, 'investigation_number', 'INV'
            )
        super().save(*args, **kwargs)

    def start(self):
        if self.status != self.Status.OPEN:
            raise ValidationError({'status': 'Somente investigações abertas podem ser iniciadas.'})
        self.status = self.Status.IN_PROGRESS
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'updated_at'])

    def approve_repeat(self, justification, user=None):
        if not justification:
            raise ValidationError({'repeat_justification': 'Informe a justificativa da repetição.'})
        self.repeat_approved = True
        self.repeat_justification = justification
        self.opened_by = self.opened_by or user
        self.save(
            update_fields=['repeat_approved', 'repeat_justification', 'opened_by', 'updated_at']
        )

    def approve_retest(self, justification, user=None):
        if not justification:
            raise ValidationError({'retest_justification': 'Informe a justificativa do reteste.'})
        self.retest_approved = True
        self.retest_justification = justification
        self.opened_by = self.opened_by or user
        self.save(
            update_fields=['retest_approved', 'retest_justification', 'opened_by', 'updated_at']
        )

    def approve_resampling(self, justification, user=None):
        if not justification:
            raise ValidationError(
                {'resampling_justification': 'Informe a justificativa da reamostragem.'}
            )
        self.resampling_approved = True
        self.resampling_justification = justification
        self.opened_by = self.opened_by or user
        self.save(
            update_fields=[
                'resampling_approved',
                'resampling_justification',
                'opened_by',
                'updated_at',
            ]
        )

    def conclude(self, root_cause, conclusion, user=None):
        if not root_cause:
            raise ValidationError({'root_cause': 'Informe a causa raiz.'})
        if not conclusion:
            raise ValidationError({'conclusion': 'Informe a conclusão.'})
        if self.status not in {self.Status.OPEN, self.Status.IN_PROGRESS}:
            raise ValidationError(
                {'status': 'Somente investigações abertas ou em andamento podem ser concluídas.'}
            )
        self.status = self.Status.CONCLUDED
        self.root_cause = root_cause
        self.conclusion = conclusion
        self.concluded_by = user
        self.concluded_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'root_cause',
                'conclusion',
                'concluded_by',
                'concluded_at',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('sample', 'analysis', 'result'):
            pass
        if self.analysis and self.analysis.sample_id != self.sample_id:
            errors['analysis'] = 'A análise deve pertencer à amostra informada.'
        if self.result and self.analysis and self.result.analysis_id != self.analysis_id:
            errors['result'] = 'O resultado deve pertencer à análise informada.'
        if self.status == self.Status.CONCLUDED and (not self.root_cause or not self.conclusion):
            errors['conclusion'] = 'Investigações concluídas exigem causa raiz e conclusão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.investigation_number


class QualityDocument(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('document_number', 'LAU'),)

    class DocumentType(models.TextChoices):
        CERTIFICATE_OF_ANALYSIS = 'certificate_of_analysis', 'Certificado de análise'
        ANALYTICAL_REPORT = 'analytical_report', 'Laudo analítico'
        RELEASE_LABEL = 'release_label', 'Etiqueta de liberação'
        RELEASE_REPORT = 'release_report', 'Relatório de liberação'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        ISSUED = 'issued', 'Emitido'
        CANCELLED = 'cancelled', 'Cancelado'

    document_number = models.CharField('documento', max_length=80, blank=True)
    document_type = models.CharField('tipo', max_length=40, choices=DocumentType.choices)
    sample = models.ForeignKey(
        QualitySample,
        on_delete=models.PROTECT,
        related_name='quality_documents',
        verbose_name='amostra',
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='quality_documents', verbose_name='produto'
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='quality_documents',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    summary = models.TextField('resumo', blank=True)
    conclusion = models.TextField('conclusão')
    attachment_reference = models.CharField('arquivo emitido', max_length=255, blank=True)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='issued_quality_documents',
        null=True,
        blank=True,
        verbose_name='emitido por',
    )
    issued_at = models.DateTimeField('emitido em', null=True, blank=True)
    valid_until = models.DateField('válido até', null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['document_number'], name='unique_quality_document_number'
            ),
        ]
        indexes = [
            models.Index(fields=['document_type', 'status']),
            models.Index(fields=['sample']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['document_number']),
        ]
        verbose_name = 'documento de qualidade'
        verbose_name_plural = 'documentos de qualidade'

    def save(self, *args, **kwargs):
        if not self.document_number:
            self.document_number = _sequence_code(QualityDocument, 'document_number', 'LAU')
        super().save(*args, **kwargs)

    def issue(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente documentos em rascunho podem ser emitidos.'})
        if self.sample.status != QualitySample.Status.APPROVED:
            raise ValidationError({'sample': 'A emissão exige amostra aprovada.'})
        self.status = self.Status.ISSUED
        self.issued_by = user
        self.issued_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'issued_by', 'issued_at', 'updated_at'])

    def cancel(self, reason):
        if not reason:
            raise ValidationError({'summary': 'Informe a justificativa do cancelamento.'})
        self.status = self.Status.CANCELLED
        self.summary = reason
        self.save(update_fields=['status', 'summary', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        for field in ('sample', 'product', 'stock_lot'):
            pass
        if self.sample and self.product and self.sample.product_id != self.product_id:
            errors['product'] = 'O produto deve ser o mesmo da amostra.'
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto do documento.'
        if (
            self.valid_until
            and self.issued_at
            and self.valid_until < timezone.localdate(self.issued_at)
        ):
            errors['valid_until'] = 'A validade não pode ser anterior à emissão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.document_number
