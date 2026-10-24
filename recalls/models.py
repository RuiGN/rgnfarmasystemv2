from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.modules import OperationalModule
from base.normalized_locations import validate_normalized_location
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner


def _record_recall_audit(action, message, instance, user=None, **context):
    from governance.models import GovernanceAuditLog

    return GovernanceAuditLog.record(
        log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
        severity=GovernanceAuditLog.Severity.INFO,
        module=OperationalModule.RECALLS,
        action=action,
        message=message,
        target_model=type(instance).__name__,
        target_record_id=str(instance.pk),
        user=user,
        safe_context=context,
    )


QUANTITY_SCALE = Decimal('0.0001')
PERCENT_SCALE = Decimal('0.01')
ZERO_QUANTITY = Decimal('0.0000')
ZERO_PERCENT = Decimal('0.00')


def _quantity(value):
    try:
        amount = Decimal(str(value or ZERO_QUANTITY))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError('Informe uma quantidade válida.') from exc
    return amount.quantize(QUANTITY_SCALE, rounding=ROUND_HALF_UP)


def _percent(value):
    try:
        amount = Decimal(str(value or ZERO_PERCENT))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError('Informe um percentual válido.') from exc
    return amount.quantize(PERCENT_SCALE, rounding=ROUND_HALF_UP)


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


def _validate_customer(errors, field, customer):
    if customer and customer.partner_type != BusinessPartner.PartnerType.CUSTOMER:
        errors[field] = 'O cliente deve usar parceiro de negócio do tipo cliente.'


class MarketComplaint(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('complaint_number', 'MKTQ'),)

    class ComplaintType(models.TextChoices):
        COMPLAINT = 'complaint', 'Reclamação'
        TECHNICAL_COMPLAINT = 'technical_complaint', 'Queixa técnica'
        RETURN = 'return', 'Devolução'
        RECALL_REQUEST = 'recall_request', 'Solicitação de recolhimento'

    class Source(models.TextChoices):
        CUSTOMER = 'customer', 'Cliente'
        DISTRIBUTOR = 'distributor', 'Distribuidor'
        AUTHORITY = 'authority', 'Autoridade sanitária'
        INTERNAL = 'internal', 'Interna'
        OTHER = 'other', 'Outra'

    class Criticality(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        TRIAGE = 'triage', 'Triagem'
        INVESTIGATION = 'investigation', 'Investigação'
        PENDING_REGULATORY_COMMUNICATION = (
            'pending_regulatory_communication',
            'Comunicação regulatória pendente',
        )
        CLOSED = 'closed', 'Encerrada'
        CANCELLED = 'cancelled', 'Cancelada'

    complaint_number = models.CharField('reclamação pós-mercado', max_length=80, blank=True)
    complaint_type = models.CharField('tipo', max_length=32, choices=ComplaintType.choices)
    source = models.CharField('fonte', max_length=32, choices=Source.choices)
    customer = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        verbose_name='cliente',
    )
    product = models.ForeignKey(
        'masters.Product',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    sales_order = models.ForeignKey(
        'crm.SalesOrder',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='pedido',
    )
    fiscal_document = models.ForeignKey(
        'fiscal.FiscalDocument',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='nota fiscal',
    )
    customer_complaint = models.ForeignKey(
        'crm.CustomerComplaint',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='reclamação CRM',
    )
    quality_sample = models.ForeignKey(
        'quality.QualitySample',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='amostra',
    )
    deviation_event = models.ForeignKey(
        'deviations.QualityEvent',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='desvio',
    )
    capa = models.ForeignKey(
        'capa.CapaRecord',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='CAPA',
    )
    document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='market_complaints',
        null=True,
        blank=True,
        verbose_name='documento',
    )
    criticality = models.CharField('criticidade', max_length=24, choices=Criticality.choices)
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    description = models.TextField('descrição')
    received_at = models.DateTimeField('recebida em')
    regulatory_communication_required = models.BooleanField(
        'exige comunicação regulatória', default=False
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='responsible_market_complaints',
        verbose_name='responsável',
    )
    country_ref = models.ForeignKey(
        'auxiliary.Country',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name='país',
    )
    state_ref = models.ForeignKey(
        'auxiliary.StateProvince',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='UF',
    )
    city_ref = models.ForeignKey(
        'auxiliary.City',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='Cidade',
    )
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reported_market_complaints',
        null=True,
        blank=True,
        verbose_name='relatada por',
    )
    status = models.CharField('status', max_length=40, choices=Status.choices, default=Status.DRAFT)
    triaged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='triaged_market_complaints',
        null=True,
        blank=True,
        verbose_name='triada por',
    )
    triaged_at = models.DateTimeField('triada em', null=True, blank=True)
    investigation_started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_market_complaint_investigations',
        null=True,
        blank=True,
        verbose_name='investigação iniciada por',
    )
    investigation_started_at = models.DateTimeField(
        'investigação iniciada em', null=True, blank=True
    )
    investigation_summary = models.TextField('resumo da investigação', blank=True)
    regulatory_communication_reference = models.CharField(
        'referência regulatória', max_length=160, blank=True
    )
    regulatory_communicated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='communicated_market_complaints',
        null=True,
        blank=True,
        verbose_name='comunicada por',
    )
    regulatory_communicated_at = models.DateTimeField('comunicada em', null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_market_complaints',
        null=True,
        blank=True,
        verbose_name='encerrada por',
    )
    closed_at = models.DateTimeField('encerrada em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-received_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['complaint_number'], name='unique_market_complaint_number'
            ),
        ]
        indexes = [
            models.Index(fields=['complaint_type', 'status']),
            models.Index(fields=['source']),
            models.Index(fields=['customer']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['criticality']),
            models.Index(fields=['received_at']),
            models.Index(fields=['responsible']),
            models.Index(fields=['complaint_number']),
        ]
        verbose_name = 'reclamação pós-mercado'
        verbose_name_plural = 'reclamações pós-mercado'

    def save(self, *args, **kwargs):
        if not self.complaint_number:
            self.complaint_number = _sequence_code(MarketComplaint, 'complaint_number', 'MKTQ')
        super().save(*args, **kwargs)

    def start_triage(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {'status': 'Somente reclamações em rascunho podem iniciar triagem.'}
            )
        self.status = self.Status.TRIAGE
        self.triaged_by = user or self.triaged_by
        self.triaged_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'triaged_by', 'triaged_at', 'updated_at'])

    def start_investigation(self, user=None):
        if self.status != self.Status.TRIAGE:
            raise ValidationError({'status': 'Investigação exige reclamação em triagem.'})
        self.status = self.Status.INVESTIGATION
        self.investigation_started_by = user or self.investigation_started_by
        self.investigation_started_at = timezone.now()
        self.investigation_summary = (
            self.investigation_summary
            or 'Investigação iniciada para triagem técnica, criticidade e impacto.'
        )
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'investigation_started_by',
                'investigation_started_at',
                'investigation_summary',
                'updated_at',
            ]
        )

    def record_regulatory_communication(self, reference, user=None):
        if not reference:
            raise ValidationError(
                {
                    'regulatory_communication_reference': 'Informe a referência da comunicação regulatória.'
                }
            )
        if self.status not in {
            self.Status.INVESTIGATION,
            self.Status.PENDING_REGULATORY_COMMUNICATION,
        }:
            raise ValidationError(
                {'status': 'Comunicação regulatória exige investigação em andamento.'}
            )
        self.regulatory_communication_reference = reference
        self.regulatory_communicated_by = user
        self.regulatory_communicated_at = timezone.now()
        self.status = self.Status.INVESTIGATION
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'regulatory_communication_reference',
                'regulatory_communicated_by',
                'regulatory_communicated_at',
                'updated_at',
            ]
        )

    def close(self, summary, user=None):
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if self.status in {self.Status.DRAFT, self.Status.TRIAGE}:
            raise ValidationError(
                {'investigation_summary': 'Encerramento exige investigação documentada.'}
            )
        if self.status not in {
            self.Status.INVESTIGATION,
            self.Status.PENDING_REGULATORY_COMMUNICATION,
        }:
            raise ValidationError({'status': 'Encerramento exige investigação em andamento.'})
        if not self.investigation_summary:
            raise ValidationError(
                {'investigation_summary': 'Encerramento exige investigação documentada.'}
            )
        if self.regulatory_communication_required and not self.regulatory_communication_reference:
            # A tentativa de encerramento sem comunicação regulatória é um evento de
            # negócio: o status pendente deve persistir mesmo com a recusa.
            if self.status != self.Status.PENDING_REGULATORY_COMMUNICATION:
                previous_status = self.status
                with transaction.atomic():
                    self.status = self.Status.PENDING_REGULATORY_COMMUNICATION
                    self.save(update_fields=['status', 'updated_at'])
                    _record_recall_audit(
                        'recalls.complaint.pending_regulatory_communication',
                        'Encerramento bloqueado: comunicação regulatória pendente.',
                        self,
                        user,
                        from_status=previous_status,
                    )
            raise ValidationError(
                {
                    'regulatory_communication_reference': 'Encerramento exige comunicação regulatória registrada.'
                }
            )
        previous_status = self.status
        self.status = self.Status.CLOSED
        self.closure_summary = summary
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(
                update_fields=['status', 'closure_summary', 'closed_by', 'closed_at', 'updated_at']
            )
            _record_recall_audit(
                'recalls.complaint.closed',
                'Reclamação pós-mercado encerrada.',
                self,
                user,
                from_status=previous_status,
            )

    def cancel(self, reason, user=None):
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe o motivo do cancelamento.'})
        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.status in {
                self.Status.CLOSED,
                self.Status.CANCELLED,
                self.Status.PENDING_REGULATORY_COMMUNICATION,
            }:
                raise ValidationError(
                    {
                        'status': 'Reclamação encerrada, cancelada ou com comunicação regulatória pendente não pode ser cancelada.'
                    }
                )
            previous_status = locked.status
            self.status = self.Status.CANCELLED
            self.cancel_reason = reason
            self.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            _record_recall_audit(
                'recalls.complaint.cancelled',
                'Reclamação pós-mercado cancelada.',
                self,
                user,
                from_status=previous_status,
            )

    def clean(self):
        super().clean()
        validate_normalized_location(self)
        errors = {}
        _validate_customer(errors, 'customer', self.customer)
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if self.sales_order and self.sales_order.customer_id != self.customer_id:
            errors['sales_order'] = 'O pedido deve pertencer ao cliente informado.'
        if self.fiscal_document and self.fiscal_document.partner_id != self.customer_id:
            errors['fiscal_document'] = 'A nota fiscal deve pertencer ao cliente informado.'
        if self.customer_complaint and self.customer_complaint.customer_id != self.customer_id:
            errors['customer_complaint'] = 'A reclamação CRM deve pertencer ao cliente informado.'
        if self.quality_sample and self.quality_sample.product_id != self.product_id:
            errors['quality_sample'] = 'A amostra deve pertencer ao produto informado.'
        if self.status == self.Status.CLOSED and (
            not self.closure_summary or not self.closed_by_id or not self.closed_at
        ):
            errors['closure_summary'] = 'Reclamação encerrada exige resumo, responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.complaint_number


class ProductReturn(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('return_number', 'RET'),)

    class ReturnType(models.TextChoices):
        CUSTOMER_RETURN = 'customer_return', 'Devolução de cliente'
        RECALL_RETURN = 'recall_return', 'Retorno de recall'
        SAMPLE_RETURN = 'sample_return', 'Retorno de amostra'
        DESTRUCTION_REQUEST = 'destruction_request', 'Solicitação de destruição'

    class Status(models.TextChoices):
        REQUESTED = 'requested', 'Solicitada'
        AUTHORIZED = 'authorized', 'Autorizada'
        RECEIVED = 'received', 'Recebida'
        INSPECTED = 'inspected', 'Inspecionada'
        CLOSED = 'closed', 'Encerrada'
        CANCELLED = 'cancelled', 'Cancelada'

    class Disposition(models.TextChoices):
        QUARANTINE = 'quarantine', 'Quarentena'
        REPROCESS = 'reprocess', 'Reprocessar'
        DESTROY = 'destroy', 'Destruir'
        RETURN_TO_STOCK = 'return_to_stock', 'Retornar ao estoque'
        INVESTIGATE = 'investigate', 'Investigar'

    return_number = models.CharField('devolução', max_length=80, blank=True)
    complaint = models.ForeignKey(
        MarketComplaint,
        on_delete=models.PROTECT,
        related_name='returns',
        null=True,
        blank=True,
        verbose_name='reclamação',
    )
    return_type = models.CharField('tipo', max_length=32, choices=ReturnType.choices)
    customer = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='product_returns',
        verbose_name='cliente',
    )
    product = models.ForeignKey(
        'masters.Product',
        on_delete=models.PROTECT,
        related_name='product_returns',
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='product_returns',
        verbose_name='lote',
    )
    sales_order = models.ForeignKey(
        'crm.SalesOrder',
        on_delete=models.PROTECT,
        related_name='product_returns',
        null=True,
        blank=True,
        verbose_name='pedido',
    )
    fiscal_document = models.ForeignKey(
        'fiscal.FiscalDocument',
        on_delete=models.PROTECT,
        related_name='product_returns',
        null=True,
        blank=True,
        verbose_name='nota fiscal',
    )
    quantity = models.DecimalField('quantidade solicitada', max_digits=14, decimal_places=4)
    received_quantity = models.DecimalField(
        'quantidade recebida', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    unit = models.ForeignKey(
        'masters.UnitOfMeasure',
        on_delete=models.PROTECT,
        related_name='product_returns',
        verbose_name='unidade',
    )
    reason = models.TextField('motivo')
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.REQUESTED
    )
    disposition = models.CharField(
        'destinação', max_length=24, choices=Disposition.choices, blank=True
    )
    inspection_notes = models.TextField('notas de inspeção', blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_product_returns',
        null=True,
        blank=True,
        verbose_name='solicitada por',
    )
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='authorized_product_returns',
        null=True,
        blank=True,
        verbose_name='autorizada por',
    )
    authorized_at = models.DateTimeField('autorizada em', null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='received_product_returns',
        null=True,
        blank=True,
        verbose_name='recebida por',
    )
    received_at = models.DateTimeField('recebida em', null=True, blank=True)
    inspected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='inspected_product_returns',
        null=True,
        blank=True,
        verbose_name='inspecionada por',
    )
    inspected_at = models.DateTimeField('inspecionada em', null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_product_returns',
        null=True,
        blank=True,
        verbose_name='encerrada por',
    )
    closed_at = models.DateTimeField('encerrada em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['return_number'], name='unique_product_return_number'),
        ]
        indexes = [
            models.Index(fields=['return_type', 'status']),
            models.Index(fields=['complaint']),
            models.Index(fields=['customer']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['return_number']),
        ]
        verbose_name = 'devolução pós-mercado'
        verbose_name_plural = 'devoluções pós-mercado'

    def save(self, *args, **kwargs):
        if not self.return_number:
            self.return_number = _sequence_code(ProductReturn, 'return_number', 'RET')
        super().save(*args, **kwargs)

    def authorize(self, user=None):
        if self.status != self.Status.REQUESTED:
            raise ValidationError(
                {'status': 'Somente devoluções solicitadas podem ser autorizadas.'}
            )
        self.status = self.Status.AUTHORIZED
        self.authorized_by = user
        self.authorized_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'authorized_by', 'authorized_at', 'updated_at'])

    def receive(self, quantity, user=None):
        if self.status != self.Status.AUTHORIZED:
            raise ValidationError({'status': 'Recebimento exige devolução autorizada.'})
        received_quantity = _quantity(quantity)
        if received_quantity <= 0:
            raise ValidationError(
                {'received_quantity': 'A quantidade recebida deve ser maior que zero.'}
            )
        if received_quantity > self.quantity:
            raise ValidationError(
                {'received_quantity': 'A quantidade recebida não pode exceder a solicitada.'}
            )
        self.received_quantity = received_quantity
        self.status = self.Status.RECEIVED
        self.received_by = user
        self.received_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'received_quantity',
                'received_by',
                'received_at',
                'updated_at',
            ]
        )

    def inspect(self, disposition, notes, user=None):
        if self.status != self.Status.RECEIVED:
            raise ValidationError({'status': 'Inspeção exige devolução recebida.'})
        if not disposition:
            raise ValidationError({'disposition': 'Informe a destinação da devolução.'})
        self.disposition = disposition
        self.inspection_notes = notes
        self.status = self.Status.INSPECTED
        self.inspected_by = user
        self.inspected_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'disposition',
                'inspection_notes',
                'inspected_by',
                'inspected_at',
                'updated_at',
            ]
        )

    def close(self, summary, user=None):
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if self.status != self.Status.INSPECTED:
            raise ValidationError({'status': 'Encerramento exige devolução inspecionada.'})
        previous_status = self.status
        self.status = self.Status.CLOSED
        self.closure_summary = summary
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(
                update_fields=['status', 'closure_summary', 'closed_by', 'closed_at', 'updated_at']
            )
            _record_recall_audit(
                'recalls.return.closed',
                'Devolução encerrada.',
                self,
                user,
                from_status=previous_status,
            )

    def cancel(self, reason, user=None):
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe o motivo do cancelamento.'})
        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            if locked.status in {self.Status.CLOSED, self.Status.CANCELLED}:
                raise ValidationError(
                    {'status': 'Devolução encerrada ou cancelada não pode ser cancelada.'}
                )
            previous_status = locked.status
            self.status = self.Status.CANCELLED
            self.cancel_reason = reason
            self.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            _record_recall_audit(
                'recalls.return.cancelled',
                'Devolução cancelada.',
                self,
                user,
                from_status=previous_status,
            )

    def clean(self):
        super().clean()
        errors = {}
        _validate_customer(errors, 'customer', self.customer)
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if self.sales_order and self.sales_order.customer_id != self.customer_id:
            errors['sales_order'] = 'O pedido deve pertencer ao cliente informado.'
        if self.fiscal_document and self.fiscal_document.partner_id != self.customer_id:
            errors['fiscal_document'] = 'A nota fiscal deve pertencer ao cliente informado.'
        if self.complaint and self.complaint.customer_id != self.customer_id:
            errors['complaint'] = 'A reclamação deve pertencer ao cliente informado.'
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.received_quantity < 0:
            errors['received_quantity'] = 'A quantidade recebida não pode ser negativa.'
        if self.received_quantity > self.quantity:
            errors['received_quantity'] = 'A quantidade recebida não pode exceder a solicitada.'
        if self.status == self.Status.CLOSED and (
            not self.closure_summary or not self.closed_by_id or not self.closed_at
        ):
            errors['closure_summary'] = 'Devolução encerrada exige resumo, responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.return_number


class RecallCampaign(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('campaign_number', 'RECALL'),)

    class CampaignType(models.TextChoices):
        RECALL = 'recall', 'Recall'
        VOLUNTARY_RECALL = 'voluntary_recall', 'Recolhimento voluntário'
        FIELD_CORRECTION = 'field_correction', 'Correção em campo'
        STOCK_WITHDRAWAL = 'stock_withdrawal', 'Retirada de estoque'

    class Trigger(models.TextChoices):
        TECHNICAL_COMPLAINT = 'technical_complaint', 'Queixa técnica'
        DEVIATION = 'deviation', 'Desvio'
        AUTHORITY = 'authority', 'Autoridade sanitária'
        INTERNAL = 'internal', 'Interna'

    class Criticality(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovada'
        IN_EXECUTION = 'in_execution', 'Em execução'
        MONITORING = 'monitoring', 'Monitoramento'
        CLOSED = 'closed', 'Encerrada'
        CANCELLED = 'cancelled', 'Cancelada'

    campaign_number = models.CharField('campanha', max_length=80, blank=True)
    campaign_type = models.CharField('tipo', max_length=32, choices=CampaignType.choices)
    trigger = models.CharField('gatilho', max_length=32, choices=Trigger.choices)
    product = models.ForeignKey(
        'masters.Product',
        on_delete=models.PROTECT,
        related_name='recall_campaigns',
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='recall_campaigns',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    complaint = models.ForeignKey(
        MarketComplaint,
        on_delete=models.PROTECT,
        related_name='recall_campaigns',
        null=True,
        blank=True,
        verbose_name='reclamação',
    )
    deviation_event = models.ForeignKey(
        'deviations.QualityEvent',
        on_delete=models.PROTECT,
        related_name='recall_campaigns',
        null=True,
        blank=True,
        verbose_name='desvio',
    )
    capa = models.ForeignKey(
        'capa.CapaRecord',
        on_delete=models.PROTECT,
        related_name='recall_campaigns',
        null=True,
        blank=True,
        verbose_name='CAPA',
    )
    criticality = models.CharField('criticidade', max_length=24, choices=Criticality.choices)
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    reason = models.TextField('motivo')
    decision_date = models.DateField('data da decisão')
    target_completion_date = models.DateField('prazo alvo')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='responsible_recall_campaigns',
        verbose_name='responsável',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_recall_campaigns',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_recall_campaigns',
        null=True,
        blank=True,
        verbose_name='iniciada por',
    )
    started_at = models.DateTimeField('iniciada em', null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_recall_campaigns',
        null=True,
        blank=True,
        verbose_name='encerrada por',
    )
    closed_at = models.DateTimeField('encerrada em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-decision_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign_number'], name='unique_recall_campaign_number'
            ),
        ]
        indexes = [
            models.Index(fields=['campaign_type', 'status']),
            models.Index(fields=['trigger']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['criticality']),
            models.Index(fields=['target_completion_date']),
            models.Index(fields=['campaign_number']),
        ]
        verbose_name = 'campanha de recall/recolhimento'
        verbose_name_plural = 'campanhas de recall/recolhimento'

    def save(self, *args, **kwargs):
        if not self.campaign_number:
            self.campaign_number = _sequence_code(RecallCampaign, 'campaign_number', 'RECALL')
        super().save(*args, **kwargs)

    def approve(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente campanhas em rascunho podem ser aprovadas.'})
        if user is None:
            raise ValidationError({'approved_by': 'Aprovação exige usuário identificado.'})
        if self.responsible_id and self.responsible_id == user.pk:
            raise ValidationError(
                {
                    'approved_by': 'O responsável pela campanha não pode aprová-la (segregação de funções).'
                }
            )
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
            _record_recall_audit(
                'recalls.campaign.approved',
                'Campanha de recall aprovada.',
                self,
                user,
                to_status=self.status,
            )

    def start(self, user=None):
        if self.status != self.Status.APPROVED:
            raise ValidationError({'status': 'Execução exige campanha aprovada.'})
        if not self.impacted_customers.exists():
            raise ValidationError(
                {'impacted_customers': 'Execução exige ao menos um cliente impactado.'}
            )
        self.status = self.Status.IN_EXECUTION
        self.started_by = user
        self.started_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'started_by', 'started_at', 'updated_at'])

    def close(self, summary, user=None):
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if self.status not in {self.Status.IN_EXECUTION, self.Status.MONITORING}:
            raise ValidationError(
                {'status': 'Encerramento exige campanha em execução ou monitoramento.'}
            )
        if not self.communications.filter(status=RecallCommunication.Status.SENT).exists():
            raise ValidationError({'communications': 'Encerramento exige comunicação enviada.'})
        open_customers = self.impacted_customers.exclude(
            response_status__in=[
                RecallImpactedCustomer.ResponseStatus.RETURNED,
                RecallImpactedCustomer.ResponseStatus.NOT_APPLICABLE,
                RecallImpactedCustomer.ResponseStatus.CLOSED,
                RecallImpactedCustomer.ResponseStatus.LOST,
            ]
        )
        if open_customers.exists():
            raise ValidationError(
                {
                    'impacted_customers': 'Encerramento exige respostas e retorno dos clientes impactados.'
                }
            )
        if not self.reports.filter(status=RecallEffectivenessReport.Status.GENERATED).exists():
            raise ValidationError(
                {'reports': 'Encerramento exige relatório de efetividade/rastreabilidade gerado.'}
            )
        previous_status = self.status
        self.status = self.Status.CLOSED
        self.closure_summary = summary
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(
                update_fields=['status', 'closure_summary', 'closed_by', 'closed_at', 'updated_at']
            )
            _record_recall_audit(
                'recalls.campaign.closed',
                'Campanha de recall encerrada.',
                self,
                user,
                from_status=previous_status,
            )

    def cancel(self, reason, user=None):
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe o motivo do cancelamento.'})
        if self.status in {
            self.Status.IN_EXECUTION,
            self.Status.MONITORING,
            self.Status.CLOSED,
            self.Status.CANCELLED,
        }:
            raise ValidationError(
                {
                    'status': 'Campanha em execução, monitoramento ou finalizada não pode ser cancelada.'
                }
            )
        previous_status = self.status
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        with transaction.atomic():
            self.save(update_fields=['status', 'cancel_reason', 'updated_at'])
            _record_recall_audit(
                'recalls.campaign.cancelled',
                'Campanha de recall cancelada.',
                self,
                user,
                from_status=previous_status,
            )

    def clean(self):
        super().clean()
        errors = {}
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if self.complaint and self.complaint.product_id != self.product_id:
            errors['complaint'] = 'A reclamação deve pertencer ao produto da campanha.'
        if (
            self.target_completion_date
            and self.decision_date
            and self.target_completion_date < self.decision_date
        ):
            errors['target_completion_date'] = 'O prazo alvo não pode ser anterior à decisão.'
        if self.status == self.Status.CLOSED and (
            not self.closure_summary or not self.closed_by_id or not self.closed_at
        ):
            errors['closure_summary'] = 'Campanha encerrada exige resumo, responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.campaign_number


class RecallImpactedCustomer(SingleInstanceModel):
    class ResponseStatus(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        CONTACTED = 'contacted', 'Contatado'
        ACKNOWLEDGED = 'acknowledged', 'Reconhecido'
        RETURNED = 'returned', 'Retornado'
        NOT_APPLICABLE = 'not_applicable', 'Não aplicável'
        LOST = 'lost', 'Não recuperável'
        CLOSED = 'closed', 'Encerrado'

    campaign = models.ForeignKey(
        RecallCampaign,
        on_delete=models.CASCADE,
        related_name='impacted_customers',
        verbose_name='campanha',
    )
    customer = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='recall_impacts',
        verbose_name='cliente',
    )
    sales_order = models.ForeignKey(
        'crm.SalesOrder',
        on_delete=models.PROTECT,
        related_name='recall_impacts',
        null=True,
        blank=True,
        verbose_name='pedido',
    )
    fiscal_document = models.ForeignKey(
        'fiscal.FiscalDocument',
        on_delete=models.PROTECT,
        related_name='recall_impacts',
        null=True,
        blank=True,
        verbose_name='nota fiscal',
    )
    quantity_distributed = models.DecimalField(
        'quantidade distribuída', max_digits=14, decimal_places=4
    )
    quantity_recalled = models.DecimalField(
        'quantidade a recolher', max_digits=14, decimal_places=4
    )
    quantity_returned = models.DecimalField(
        'quantidade retornada', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    response_status = models.CharField(
        'status da resposta',
        max_length=24,
        choices=ResponseStatus.choices,
        default=ResponseStatus.PENDING,
    )
    contact_name = models.CharField('contato', max_length=120, blank=True)
    contact_email = models.EmailField('email', blank=True)
    response_notes = models.TextField('observações da resposta', blank=True)
    response_received_at = models.DateTimeField('resposta recebida em', null=True, blank=True)
    returned_at = models.DateTimeField('retornado em', null=True, blank=True)

    class Meta:
        ordering = ['campaign__campaign_number', 'customer__legal_name']
        constraints = [
            models.UniqueConstraint(
                fields=['campaign', 'customer', 'sales_order', 'fiscal_document'],
                name='unique_recall_customer_distribution',
            ),
        ]
        indexes = [
            models.Index(fields=['campaign', 'response_status']),
            models.Index(fields=['customer']),
            models.Index(fields=['sales_order']),
            models.Index(fields=['fiscal_document']),
        ]
        verbose_name = 'cliente impactado por recall'
        verbose_name_plural = 'clientes impactados por recall'

    def record_response(self, status, notes=''):
        if status not in self.ResponseStatus.values:
            raise ValidationError({'response_status': 'Status de resposta inválido.'})
        if status == self.ResponseStatus.PENDING:
            raise ValidationError({'response_status': 'Resposta não pode voltar para pendente.'})
        self.response_status = status
        self.response_notes = notes
        self.response_received_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'response_status',
                'response_notes',
                'response_received_at',
                'updated_at',
            ]
        )

    def record_return(self, quantity, notes=''):
        returned_quantity = _quantity(quantity)
        if returned_quantity <= 0:
            raise ValidationError(
                {'quantity_returned': 'A quantidade retornada deve ser maior que zero.'}
            )
        if returned_quantity > self.quantity_recalled:
            raise ValidationError(
                {'quantity_returned': 'A quantidade retornada não pode exceder a recolhida.'}
            )
        self.quantity_returned = returned_quantity
        self.response_status = self.ResponseStatus.RETURNED
        self.response_notes = notes or self.response_notes
        self.returned_at = timezone.now()
        self.response_received_at = self.response_received_at or timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'quantity_returned',
                'response_status',
                'response_notes',
                'returned_at',
                'response_received_at',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        _validate_customer(errors, 'customer', self.customer)
        if self.sales_order and self.sales_order.customer_id != self.customer_id:
            errors['sales_order'] = 'O pedido deve pertencer ao cliente informado.'
        if self.fiscal_document and self.fiscal_document.partner_id != self.customer_id:
            errors['fiscal_document'] = 'A nota fiscal deve pertencer ao cliente informado.'
        if self.quantity_distributed <= 0:
            errors['quantity_distributed'] = 'A quantidade distribuída deve ser maior que zero.'
        if self.quantity_recalled <= 0:
            errors['quantity_recalled'] = 'A quantidade a recolher deve ser maior que zero.'
        if self.quantity_recalled > self.quantity_distributed:
            errors['quantity_recalled'] = 'A quantidade a recolher não pode exceder a distribuída.'
        if self.quantity_returned < 0:
            errors['quantity_returned'] = 'A quantidade retornada não pode ser negativa.'
        if self.quantity_returned > self.quantity_recalled:
            errors['quantity_returned'] = 'A quantidade retornada não pode exceder a recolhida.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.campaign} - {self.customer}'


class RecallCommunication(SingleInstanceModel):
    class Channel(models.TextChoices):
        EMAIL = 'email', 'Email'
        PHONE = 'phone', 'Telefone'
        LETTER = 'letter', 'Carta'
        PORTAL = 'portal', 'Portal'
        AUTHORITY = 'authority', 'Autoridade sanitária'
        OTHER = 'other', 'Outro'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        SENT = 'sent', 'Enviada'
        ACKNOWLEDGED = 'acknowledged', 'Reconhecida'

    campaign = models.ForeignKey(
        RecallCampaign,
        on_delete=models.CASCADE,
        related_name='communications',
        verbose_name='campanha',
    )
    impacted_customer = models.ForeignKey(
        RecallImpactedCustomer,
        on_delete=models.CASCADE,
        related_name='communications',
        null=True,
        blank=True,
        verbose_name='cliente impactado',
    )
    channel = models.CharField('canal', max_length=24, choices=Channel.choices)
    subject = models.CharField('assunto', max_length=180)
    message = models.TextField('mensagem')
    response_due_date = models.DateField('prazo de resposta', null=True, blank=True)
    acknowledgement_required = models.BooleanField('exige reconhecimento', default=True)
    content_hash = models.CharField('hash do conteúdo', max_length=128)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sent_recall_communications',
        null=True,
        blank=True,
        verbose_name='enviada por',
    )
    sent_at = models.DateTimeField('enviada em', null=True, blank=True)
    acknowledged_at = models.DateTimeField('reconhecida em', null=True, blank=True)

    class Meta:
        ordering = ['campaign__campaign_number', '-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['impacted_customer']),
            models.Index(fields=['channel']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'comunicação de recall'
        verbose_name_plural = 'comunicações de recall'

    def send(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {'status': 'Somente comunicações em rascunho podem ser enviadas.'}
            )
        self.status = self.Status.SENT
        self.sent_by = user
        self.sent_at = timezone.now()
        self.full_clean()
        customer = self.impacted_customer
        with transaction.atomic():
            if customer:
                customer.response_status = RecallImpactedCustomer.ResponseStatus.CONTACTED
                customer.save(update_fields=['response_status', 'updated_at'])
            self.save(update_fields=['status', 'sent_by', 'sent_at', 'updated_at'])
            _record_recall_audit(
                'recalls.communication.sent',
                'Comunicação de recall enviada.',
                self,
                user,
                campaign_id=self.campaign_id,
            )

    def acknowledge(self):
        if self.status != self.Status.SENT:
            raise ValidationError({'status': 'Reconhecimento exige comunicação enviada.'})
        self.status = self.Status.ACKNOWLEDGED
        self.acknowledged_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'acknowledged_at', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        if self.impacted_customer and self.impacted_customer.campaign_id != self.campaign_id:
            errors['impacted_customer'] = 'O cliente impactado deve pertencer à campanha informada.'
        if not self.content_hash:
            errors['content_hash'] = 'Comunicação exige hash de integridade.'
        if self.status == self.Status.SENT and (not self.sent_by_id or not self.sent_at):
            errors['sent_by'] = 'Comunicação enviada exige usuário e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.campaign} - {self.subject}'


class RecallEffectivenessReport(SingleInstanceModel):
    class ReportType(models.TextChoices):
        EFFECTIVENESS = 'effectiveness', 'Efetividade'
        TRACEABILITY = 'traceability', 'Rastreabilidade'
        DISTRIBUTION = 'distribution', 'Distribuição'
        REGULATORY = 'regulatory', 'Regulatório'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        GENERATED = 'generated', 'Gerado'

    campaign = models.ForeignKey(
        RecallCampaign, on_delete=models.CASCADE, related_name='reports', verbose_name='campanha'
    )
    report_type = models.CharField('tipo', max_length=24, choices=ReportType.choices)
    title = models.CharField('título', max_length=180)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    content_reference = models.CharField('conteúdo gerado', max_length=255, blank=True)
    impacted_customers = models.PositiveIntegerField('clientes impactados', default=0)
    customers_contacted = models.PositiveIntegerField('clientes contatados', default=0)
    responses_received = models.PositiveIntegerField('respostas recebidas', default=0)
    total_distributed = models.DecimalField(
        'total distribuído', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    total_recalled = models.DecimalField(
        'total a recolher', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    total_returned = models.DecimalField(
        'total retornado', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    effectiveness_rate = models.DecimalField(
        'efetividade (%)', max_digits=7, decimal_places=2, default=ZERO_PERCENT
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='generated_recall_reports',
        null=True,
        blank=True,
        verbose_name='gerado por',
    )
    generated_at = models.DateTimeField('gerado em', null=True, blank=True)

    class Meta:
        ordering = ['campaign__campaign_number', '-created_at']
        indexes = [
            models.Index(fields=['campaign', 'status']),
            models.Index(fields=['report_type']),
            models.Index(fields=['generated_at']),
        ]
        verbose_name = 'relatório de recall'
        verbose_name_plural = 'relatórios de recall'

    def generate(self, user=None, content_reference=''):
        if not content_reference:
            raise ValidationError(
                {'content_reference': 'Informe a referência do relatório gerado.'}
            )
        impacted = list(self.campaign.impacted_customers.all())
        self.impacted_customers = len(impacted)
        self.customers_contacted = sum(
            1
            for item in impacted
            if item.response_status != RecallImpactedCustomer.ResponseStatus.PENDING
        )
        self.responses_received = sum(
            1
            for item in impacted
            if item.response_received_at is not None or item.returned_at is not None
        )
        self.total_distributed = _quantity(
            sum((item.quantity_distributed for item in impacted), ZERO_QUANTITY)
        )
        self.total_recalled = _quantity(
            sum((item.quantity_recalled for item in impacted), ZERO_QUANTITY)
        )
        self.total_returned = _quantity(
            sum((item.quantity_returned for item in impacted), ZERO_QUANTITY)
        )
        self.effectiveness_rate = (
            ZERO_PERCENT
            if self.total_recalled == 0
            else _percent((self.total_returned / self.total_recalled) * Decimal('100'))
        )
        self.content_reference = content_reference
        self.generated_by = user
        self.generated_at = timezone.now()
        self.status = self.Status.GENERATED
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'content_reference',
                'impacted_customers',
                'customers_contacted',
                'responses_received',
                'total_distributed',
                'total_recalled',
                'total_returned',
                'effectiveness_rate',
                'generated_by',
                'generated_at',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.GENERATED and (
            not self.content_reference or not self.generated_by_id or not self.generated_at
        ):
            errors['content_reference'] = 'Relatório gerado exige referência, usuário e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


# Create your models here.
