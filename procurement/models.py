from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone

from base.models import SingleInstanceModel
from base.normalized_locations import validate_normalized_location
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner, Product, UnitOfMeasure
from planning.models import MRPSuggestion


QUANTITY_SCALE = Decimal('0.0001')
MONEY_SCALE = Decimal('0.0001')
ZERO_QUANTITY = Decimal('0.0000')
ZERO_MONEY = Decimal('0.0000')


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class PurchaseRequisition(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('requisition_number', 'REQ'),)

    class Source(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        MRP = 'mrp', 'MRP'
        STOCK_MINIMUM = 'stock_minimum', 'Estoque mínimo'
        LABORATORY = 'laboratory', 'Laboratório'
        ADMINISTRATIVE = 'administrative', 'Administrativa'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        SUBMITTED = 'submitted', 'Submetida'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Rejeitada'
        CANCELLED = 'cancelled', 'Cancelada'
        CONVERTED = 'converted', 'Convertida'

    requisition_number = models.CharField('requisição', max_length=80, blank=True)
    source = models.CharField(
        'origem', max_length=24, choices=Source.choices, default=Source.MANUAL
    )
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.DRAFT)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchase_requisitions',
        null=True,
        blank=True,
        verbose_name='solicitante',
    )
    justification = models.TextField('justificativa')
    submitted_at = models.DateTimeField('submetida em', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_purchase_requisitions',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rejected_purchase_requisitions',
        null=True,
        blank=True,
        verbose_name='rejeitada por',
    )
    rejected_at = models.DateTimeField('rejeitada em', null=True, blank=True)
    rejection_reason = models.TextField('motivo da rejeição', blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['requisition_number'],
                name='unique_purchase_requisition_number',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['source']),
            models.Index(fields=['requisition_number']),
        ]
        verbose_name = 'requisição de compra'
        verbose_name_plural = 'requisições de compra'

    def save(self, *args, **kwargs):
        if not self.requisition_number:
            self.requisition_number = _sequence_code(
                PurchaseRequisition, 'requisition_number', 'REQ'
            )
        super().save(*args, **kwargs)

    @classmethod
    def create_from_mrp_suggestion(
        cls, suggestion, requested_by=None, justification='Gerada pelo MRP'
    ):
        with transaction.atomic():
            requisition = cls.objects.create(
                source=cls.Source.MRP,
                requested_by=requested_by,
                justification=justification,
            )
            PurchaseRequisitionItem.objects.create(
                requisition=requisition,
                product=suggestion.product,
                quantity=suggestion.suggested_quantity,
                unit=suggestion.product.unit,
                needed_by=suggestion.due_date,
                mrp_suggestion=suggestion,
            )
            return requisition

    def _require_status(self, allowed_statuses):
        if self.status not in allowed_statuses:
            allowed_labels = ', '.join(allowed_statuses)
            raise ValidationError(
                {'status': f'Transição inválida. Status esperado: {allowed_labels}.'}
            )

    def submit(self):
        self._require_status({self.Status.DRAFT})
        if self.pk and not self.items.exists():
            raise ValidationError({'items': 'A requisição precisa de ao menos um item.'})
        self.status = self.Status.SUBMITTED
        self.submitted_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'submitted_at', 'updated_at'])

    def approve(self, user=None):
        self._require_status({self.Status.SUBMITTED})
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def reject(self, reason, user=None):
        self._require_status({self.Status.SUBMITTED})
        if not reason:
            raise ValidationError({'rejection_reason': 'Informe o motivo da rejeição.'})
        self.status = self.Status.REJECTED
        self.rejection_reason = reason
        self.rejected_by = user
        self.rejected_at = timezone.now()
        self.save(
            update_fields=['status', 'rejection_reason', 'rejected_by', 'rejected_at', 'updated_at']
        )

    def cancel(self):
        if self.status in {self.Status.APPROVED, self.Status.CONVERTED}:
            raise ValidationError(
                {'status': 'Requisições aprovadas ou convertidas não podem ser canceladas.'}
            )
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status', 'updated_at'])

    def mark_converted(self):
        self.status = self.Status.CONVERTED
        self.save(update_fields=['status', 'updated_at'])

    def __str__(self):
        return self.requisition_number


class PurchaseRequisitionItem(SingleInstanceModel):
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.CASCADE,
        related_name='items',
        verbose_name='requisição',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='purchase_requisition_items',
        verbose_name='item',
    )
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='purchase_requisition_items',
        verbose_name='unidade',
    )
    needed_by = models.DateField('necessário em', null=True, blank=True)
    mrp_suggestion = models.ForeignKey(
        MRPSuggestion,
        on_delete=models.PROTECT,
        related_name='purchase_requisition_items',
        null=True,
        blank=True,
        verbose_name='sugestão MRP',
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['requisition__requisition_number', 'product__code']
        indexes = [
            models.Index(fields=['requisition']),
            models.Index(fields=['product']),
            models.Index(fields=['needed_by']),
        ]
        verbose_name = 'item da requisição'
        verbose_name_plural = 'itens da requisição'

    def clean(self):
        super().clean()
        errors = {}
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.product and not self.product.is_operationally_available:
            errors['product'] = 'O item precisa estar aprovado e operacionalmente disponível.'
        if self.mrp_suggestion and self.mrp_suggestion.product_id != self.product_id:
            errors['mrp_suggestion'] = 'A sugestão MRP deve ser do mesmo produto do item.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.requisition} - {self.product}'


class QuotationRequest(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('rfq_number', 'COT'),)

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        SENT = 'sent', 'Enviada'
        QUOTED = 'quoted', 'Cotada'
        APPROVED = 'approved', 'Aprovada'
        CANCELLED = 'cancelled', 'Cancelada'

    rfq_number = models.CharField('cotação', max_length=80, blank=True)
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.PROTECT,
        related_name='quotation_requests',
        verbose_name='requisição',
    )
    status = models.CharField('status', max_length=20, choices=Status.choices, default=Status.DRAFT)
    due_date = models.DateField('prazo de resposta', null=True, blank=True)
    terms = models.TextField('condições gerais', blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_quotation_requests',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['rfq_number'], name='unique_rfq_number'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['requisition']),
            models.Index(fields=['rfq_number']),
        ]
        verbose_name = 'cotação'
        verbose_name_plural = 'cotações'

    def save(self, *args, **kwargs):
        if not self.rfq_number:
            self.rfq_number = _sequence_code(QuotationRequest, 'rfq_number', 'COT')
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if False:
            raise ValidationError(
                {'requisition': 'A requisição relacionada é incompatível com o registro.'}
            )

    def send(self):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Apenas cotações em rascunho podem ser enviadas.'})
        self.status = self.Status.SENT
        self.save(update_fields=['status', 'updated_at'])

    def approve(self, user=None):
        if self.status not in {self.Status.SENT, self.Status.QUOTED}:
            raise ValidationError(
                {'status': 'A cotação precisa estar enviada ou cotada para aprovação.'}
            )
        if not self.best_quotation():
            raise ValidationError(
                {'quotations': 'Não há cotação válida de fornecedor qualificado.'}
            )
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def best_quotation(self):
        today = timezone.localdate()
        candidates = [
            quotation
            for quotation in self.quotations.select_related('supplier')
            if quotation.is_supplier_valid
            and (quotation.valid_until is None or quotation.valid_until >= today)
        ]
        if not candidates:
            return None
        return sorted(
            candidates,
            key=lambda quotation: (
                quotation.total_amount,
                quotation.lead_time_days,
                -quotation.supplier_performance_score,
                quotation.id,
            ),
        )[0]

    def __str__(self):
        return self.rfq_number


class SupplierQuotation(SingleInstanceModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        SUBMITTED = 'submitted', 'Recebida'
        SELECTED = 'selected', 'Selecionada'
        REJECTED = 'rejected', 'Rejeitada'

    rfq = models.ForeignKey(
        QuotationRequest,
        on_delete=models.CASCADE,
        related_name='quotations',
        verbose_name='cotação',
    )
    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='supplier_quotations',
        verbose_name='fornecedor',
    )
    status = models.CharField(
        'status', max_length=20, choices=Status.choices, default=Status.SUBMITTED
    )
    quoted_quantity = models.DecimalField('quantidade cotada', max_digits=14, decimal_places=4)
    unit_price = models.DecimalField('preço unitário', max_digits=14, decimal_places=4)
    tax_amount = models.DecimalField(
        'impostos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    freight_amount = models.DecimalField(
        'frete', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    currency = models.CharField('moeda', max_length=3, default='BRL')
    currency_ref = models.ForeignKey(
        'auxiliary.Currency',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='moeda normalizada',
    )
    lead_time_days = models.PositiveIntegerField('prazo em dias', default=0)
    payment_terms = models.CharField('condição de pagamento', max_length=160, blank=True)
    payment_term_ref = models.ForeignKey(
        'auxiliary.CommercialTerm',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='condição de pagamento normalizada',
    )
    delivery_terms = models.CharField('condição de entrega', max_length=160, blank=True)
    delivery_term_ref = models.ForeignKey(
        'auxiliary.CommercialTerm',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='condição de entrega normalizada',
    )
    supplier_performance_score = models.DecimalField(
        'desempenho do fornecedor', max_digits=5, decimal_places=2, default=Decimal('0.00')
    )
    valid_until = models.DateField('validade da proposta', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['rfq__rfq_number', 'unit_price', 'lead_time_days']
        constraints = [
            models.UniqueConstraint(fields=['rfq', 'supplier'], name='unique_rfq_supplier_quote'),
        ]
        indexes = [
            models.Index(fields=['rfq']),
            models.Index(fields=['supplier']),
            models.Index(fields=['status']),
            models.Index(fields=['valid_until']),
        ]
        verbose_name = 'proposta de fornecedor'
        verbose_name_plural = 'propostas de fornecedores'

    @property
    def total_amount(self):
        return (
            (self.quoted_quantity * self.unit_price) + self.tax_amount + self.freight_amount
        ).quantize(MONEY_SCALE)

    @property
    def is_supplier_valid(self):
        return (
            self.supplier.partner_type
            in {
                BusinessPartner.PartnerType.SUPPLIER,
                BusinessPartner.PartnerType.MANUFACTURER,
                BusinessPartner.PartnerType.DISTRIBUTOR,
            }
            and self.supplier.is_operationally_available
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.quoted_quantity <= 0:
            errors['quoted_quantity'] = 'A quantidade cotada deve ser maior que zero.'
        if self.unit_price <= 0:
            errors['unit_price'] = 'O preço unitário deve ser maior que zero.'
        for field_name in ('tax_amount', 'freight_amount', 'supplier_performance_score'):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O valor não pode ser negativo.'
        if self.valid_until and self.valid_until < timezone.localdate():
            errors['valid_until'] = 'A proposta não pode estar vencida.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.rfq} - {self.supplier}'


class SupplierQualificationEvent(SingleInstanceModel):
    class EventType(models.TextChoices):
        DOCUMENT = 'document', 'Documento'
        AUDIT = 'audit', 'Auditoria'
        OCCURRENCE = 'occurrence', 'Ocorrência'
        RESTRICTION = 'restriction', 'Restrição'

    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='qualification_events',
        verbose_name='fornecedor',
    )
    event_type = models.CharField('tipo', max_length=24, choices=EventType.choices)
    event_date = models.DateField('data do evento')
    valid_until = models.DateField('válido até', null=True, blank=True)
    severity = models.CharField('criticidade', max_length=40, blank=True)
    severity_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    blocks_purchases = models.BooleanField('bloqueia compras', default=False)
    description = models.TextField('descrição')
    resolved_at = models.DateTimeField('resolvido em', null=True, blank=True)
    site = models.ForeignKey(
        'masters.Site',
        on_delete=models.PROTECT,
        related_name='supplier_qualification_events',
        null=True,
        blank=True,
        verbose_name='unidade/local',
    )
    event_zipcode = models.CharField('CEP do local', max_length=20, blank=True)
    event_street = models.CharField('logradouro do local', max_length=200, blank=True)
    event_street_number = models.CharField('número', max_length=20, blank=True)
    event_complement = models.CharField('complemento', max_length=100, blank=True)
    event_neighborhood = models.CharField('bairro do local', max_length=120, blank=True)
    event_country_ref = models.ForeignKey(
        'auxiliary.Country',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name='país',
    )
    event_state_ref = models.ForeignKey(
        'auxiliary.StateProvince',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='UF',
    )
    event_city_ref = models.ForeignKey(
        'auxiliary.City',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='Cidade',
    )

    class Meta:
        ordering = ['-event_date', '-created_at']
        indexes = [
            models.Index(fields=['supplier', 'event_type']),
            models.Index(fields=['blocks_purchases']),
            models.Index(fields=['valid_until']),
        ]
        verbose_name = 'evento de qualificação de fornecedor'
        verbose_name_plural = 'eventos de qualificação de fornecedores'

    @property
    def is_active_block(self):
        if not self.blocks_purchases or self.resolved_at:
            return False
        return self.valid_until is None or self.valid_until >= timezone.localdate()

    @classmethod
    def supplier_has_active_block(cls, supplier):
        return (
            cls.objects.filter(
                supplier=supplier,
                blocks_purchases=True,
                resolved_at__isnull=True,
            )
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))
            .exists()
        )

    def clean(self):
        super().clean()
        validate_normalized_location(
            self,
            city_ref_field='event_city_ref',
            state_ref_field='event_state_ref',
        )
        if False:
            raise ValidationError(
                {'supplier': 'O fornecedor relacionado é incompatível com o registro.'}
            )

    def __str__(self):
        return f'{self.supplier} - {self.get_event_type_display()}'


class PurchaseOrder(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('order_number', 'PC'),)

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovado'
        SENT = 'sent', 'Enviado'
        PARTIALLY_RECEIVED = 'partially_received', 'Parcialmente recebido'
        RECEIVED = 'received', 'Recebido'
        CANCELLED = 'cancelled', 'Cancelado'
        CLOSED = 'closed', 'Encerrado'

    order_number = models.CharField('pedido', max_length=80, blank=True)
    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        verbose_name='fornecedor',
    )
    requisition = models.ForeignKey(
        PurchaseRequisition,
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        null=True,
        blank=True,
        verbose_name='requisição',
    )
    source_quotation = models.ForeignKey(
        SupplierQuotation,
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        null=True,
        blank=True,
        verbose_name='proposta origem',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    issue_date = models.DateField('emissão', default=timezone.localdate)
    expected_delivery_date = models.DateField('entrega prevista', null=True, blank=True)
    payment_terms = models.CharField('condição de pagamento', max_length=160, blank=True)
    payment_term_ref = models.ForeignKey(
        'auxiliary.CommercialTerm',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='condição de pagamento normalizada',
    )
    delivery_terms = models.CharField('condição de entrega', max_length=160, blank=True)
    delivery_term_ref = models.ForeignKey(
        'auxiliary.CommercialTerm',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='condição de entrega normalizada',
    )
    currency = models.CharField('moeda', max_length=3, default='BRL')
    currency_ref = models.ForeignKey(
        'auxiliary.Currency',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='moeda normalizada',
    )
    freight_amount = models.DecimalField(
        'frete', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    total_amount = models.DecimalField(
        'valor total', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    delivery_site = models.ForeignKey(
        'masters.Site',
        on_delete=models.PROTECT,
        related_name='purchase_orders',
        null=True,
        blank=True,
        verbose_name='unidade de entrega',
    )
    delivery_zipcode = models.CharField('CEP de entrega', max_length=20, blank=True)
    delivery_street = models.CharField('logradouro de entrega', max_length=200, blank=True)
    delivery_street_number = models.CharField('número', max_length=20, blank=True)
    delivery_complement = models.CharField('complemento', max_length=100, blank=True)
    delivery_neighborhood = models.CharField('bairro de entrega', max_length=120, blank=True)
    delivery_country_ref = models.ForeignKey(
        'auxiliary.Country',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name='país',
    )
    delivery_state_ref = models.ForeignKey(
        'auxiliary.StateProvince',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='UF',
    )
    delivery_city_ref = models.ForeignKey(
        'auxiliary.City',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='Cidade',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_purchase_orders',
        null=True,
        blank=True,
        verbose_name='aprovado por',
    )
    approved_at = models.DateTimeField('aprovado em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['order_number'], name='unique_purchase_order_number'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['supplier', 'status']),
            models.Index(fields=['order_number']),
            models.Index(fields=['expected_delivery_date']),
        ]
        verbose_name = 'pedido de compra'
        verbose_name_plural = 'pedidos de compra'

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = _sequence_code(PurchaseOrder, 'order_number', 'PC')
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        validate_normalized_location(
            self,
            city_ref_field='delivery_city_ref',
            state_ref_field='delivery_state_ref',
        )
        errors = {}
        if (
            self.expected_delivery_date
            and self.issue_date
            and self.expected_delivery_date < self.issue_date
        ):
            errors['expected_delivery_date'] = 'A entrega prevista não pode ser anterior à emissão.'
        if self.freight_amount < 0:
            errors['freight_amount'] = 'O frete não pode ser negativo.'
        if (
            self.pk
            and self._requires_qualified_supplier()
            and not self._supplier_is_available_for_controlled_items()
        ):
            errors['supplier'] = (
                'Fornecedor não qualificado, vencido, bloqueado ou restrito para item que exige fornecedor aprovado.'
            )
        if errors:
            raise ValidationError(errors)

        return None

    def _requires_qualified_supplier(self):
        return self.items.filter(product__requires_approved_supplier=True).exists()

    def _supplier_is_available_for_controlled_items(self):
        return (
            self.supplier.is_operationally_available
            and not SupplierQualificationEvent.supplier_has_active_block(self.supplier)
        )

    def recalculate_total(self):
        items_total = sum((item.line_total for item in self.items.all()), ZERO_MONEY)
        self.total_amount = (items_total + self.freight_amount).quantize(MONEY_SCALE)
        self.save(update_fields=['total_amount', 'updated_at'])
        return self.total_amount

    def approve(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Apenas pedidos em rascunho podem ser aprovados.'})
        if self.pk and not self.items.exists():
            raise ValidationError({'items': 'O pedido precisa de ao menos um item.'})
        self.recalculate_total()
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])

    def send(self):
        if self.status != self.Status.APPROVED:
            raise ValidationError({'status': 'Apenas pedidos aprovados podem ser enviados.'})
        self.status = self.Status.SENT
        self.save(update_fields=['status', 'updated_at'])

    def cancel(self):
        if self.status in {self.Status.RECEIVED, self.Status.CLOSED}:
            raise ValidationError(
                {'status': 'Pedidos recebidos ou encerrados não podem ser cancelados.'}
            )
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status', 'updated_at'])

    def __str__(self):
        return self.order_number


class PurchaseOrderItem(SingleInstanceModel):
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.CASCADE, related_name='items', verbose_name='pedido'
    )
    requisition_item = models.ForeignKey(
        PurchaseRequisitionItem,
        on_delete=models.PROTECT,
        related_name='purchase_order_items',
        null=True,
        blank=True,
        verbose_name='item da requisição',
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='purchase_order_items', verbose_name='item'
    )
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='purchase_order_items',
        verbose_name='unidade',
    )
    unit_price = models.DecimalField('preço unitário', max_digits=14, decimal_places=4)
    tax_amount = models.DecimalField(
        'impostos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    expected_delivery_date = models.DateField('entrega prevista', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['order__order_number', 'product__code']
        indexes = [
            models.Index(fields=['order']),
            models.Index(fields=['product']),
            models.Index(fields=['expected_delivery_date']),
        ]
        verbose_name = 'item do pedido de compra'
        verbose_name_plural = 'itens do pedido de compra'

    @property
    def line_subtotal(self):
        return (self.quantity * self.unit_price).quantize(MONEY_SCALE)

    @property
    def line_total(self):
        return (self.line_subtotal + self.tax_amount).quantize(MONEY_SCALE)

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Same row lock as receipt posting; no receipt/balance/sequence locks here.
            type(self).objects.select_for_update(no_key=True).get(pk=self.pk)
            update_fields = kwargs.get('update_fields')
            if update_fields is None or 'quantity' in update_fields:
                self._validate_posted_quantity()
        super().save(*args, **kwargs)

    def _validate_posted_quantity(self):
        if self.pk is None:
            return
        from django.db.models import Sum
        from inventory.models import StockMovement

        accepted_posted = (
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RECEIPT,
                source_purchase_receipt_item__order_item_id=self.pk,
            ).aggregate(quantity=Sum('quantity'))['quantity']
            or ZERO_QUANTITY
        )
        if self.quantity < accepted_posted:
            raise ValidationError(
                {
                    'quantity': 'A quantidade do pedido não pode ser inferior à quantidade aceita já lançada.'
                }
            )

    def clean(self):
        super().clean()
        self._validate_posted_quantity()
        errors = {}
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.unit_price <= 0:
            errors['unit_price'] = 'O preço unitário deve ser maior que zero.'
        if self.tax_amount < 0:
            errors['tax_amount'] = 'O imposto não pode ser negativo.'
        if self.requisition_item and self.requisition_item.product_id != self.product_id:
            errors['requisition_item'] = 'O item da requisição deve ser do mesmo produto.'
        if (
            self.product
            and self.order
            and self.product.requires_approved_supplier
            and not self.order._supplier_is_available_for_controlled_items()
        ):
            errors['product'] = 'Item exige fornecedor aprovado, vigente e sem restrição ativa.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.order} - {self.product}'


class PurchaseReceipt(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('receipt_number', 'REC'),)

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        RECEIVED = 'received', 'Recebido'
        QUALITY_RELEASED = 'quality_released', 'Qualidade liberada'
        STOCK_POSTED = 'stock_posted', 'Estoque lançado'
        CANCELLED = 'cancelled', 'Cancelado'

    class QualityStatus(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        QUARANTINE = 'quarantine', 'Quarentena'
        APPROVED = 'approved', 'Aprovado'
        REJECTED = 'rejected', 'Rejeitado'

    class StockEntryStatus(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        POSTED = 'posted', 'Lançado'

    receipt_number = models.CharField('recebimento', max_length=80, blank=True)
    order = models.ForeignKey(
        PurchaseOrder, on_delete=models.PROTECT, related_name='receipts', verbose_name='pedido'
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    fiscal_document_number = models.CharField('documento fiscal', max_length=80, blank=True)
    nfe_access_key = models.CharField('chave de acesso NF-e', max_length=44, blank=True)
    nfe_xml_sha256 = models.CharField('hash do XML NF-e', max_length=64, blank=True)
    nfe_xml_file = models.OneToOneField(
        'files.ProtectedFile',
        on_delete=models.PROTECT,
        related_name='purchase_receipt_nfe',
        null=True,
        blank=True,
        verbose_name='XML NF-e protegido',
    )
    fiscal_received_at = models.DateTimeField('recebimento fiscal em', null=True, blank=True)
    physical_received_at = models.DateTimeField('recebimento físico em', null=True, blank=True)
    quality_status = models.CharField(
        'status de qualidade',
        max_length=24,
        choices=QualityStatus.choices,
        default=QualityStatus.PENDING,
    )
    stock_entry_status = models.CharField(
        'entrada em estoque',
        max_length=24,
        choices=StockEntryStatus.choices,
        default=StockEntryStatus.PENDING,
    )
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='purchase_receipts',
        null=True,
        blank=True,
        verbose_name='recebido por',
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['receipt_number'], name='unique_purchase_receipt_number'
            ),
            models.UniqueConstraint(
                fields=['nfe_access_key'],
                condition=~Q(nfe_access_key=''),
                name='unique_purchase_receipt_nfe_access_key',
            ),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['order']),
            models.Index(fields=['quality_status']),
            models.Index(fields=['receipt_number']),
        ]
        verbose_name = 'recebimento de compra'
        verbose_name_plural = 'recebimentos de compra'

    @transaction.atomic
    def save(self, *args, **kwargs):
        stock_posting = kwargs.pop('_stock_posting', False)
        persisted = None
        if self.pk:
            persisted = type(self).objects.select_for_update().get(pk=self.pk)
        if (
            not stock_posting
            and (
                self.status == self.Status.STOCK_POSTED
                or self.stock_entry_status == self.StockEntryStatus.POSTED
            )
            and (persisted is None or persisted.stock_entry_status != self.StockEntryStatus.POSTED)
        ):
            raise ValidationError(
                {'stock_entry_status': 'Use post_stock para lançar estoque real.'}
            )
        if persisted is not None:
            if persisted.stock_entry_status == self.StockEntryStatus.POSTED:
                fields = (
                    'order_id',
                    'status',
                    'quality_status',
                    'stock_entry_status',
                    'fiscal_document_number',
                )
                if any(getattr(self, field) != getattr(persisted, field) for field in fields):
                    raise ValidationError(
                        {'receipt': 'Recebimento lançado é imutável; use compensação de domínio.'}
                    )
        if not self.receipt_number:
            self.receipt_number = _sequence_code(PurchaseReceipt, 'receipt_number', 'REC')
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        if False:
            raise ValidationError({'order': 'O pedido relacionado é incompatível com o registro.'})

    def mark_received(self, user=None):
        self.status = self.Status.RECEIVED
        self.received_by = user
        if self.physical_received_at is None:
            self.physical_received_at = timezone.now()
        self.save(update_fields=['status', 'received_by', 'physical_received_at', 'updated_at'])

    def release_quality(self, quality_status, *, user):
        from base.modules import OperationalModule
        from governance.models import GovernanceAuditLog

        if quality_status not in {self.QualityStatus.APPROVED, self.QualityStatus.REJECTED}:
            raise ValidationError({'quality_status': 'Informe aprovado ou rejeitado.'})
        with transaction.atomic():
            persisted = type(self).objects.select_for_update().get(pk=self.pk)
            if persisted.status == self.Status.CANCELLED:
                raise ValidationError({'status': 'Recebimento cancelado não pode ser liberado.'})
            if persisted.stock_entry_status == self.StockEntryStatus.POSTED:
                raise ValidationError(
                    {'stock_entry_status': 'Recebimento com estoque lançado não pode ser liberado.'}
                )
            if persisted.status != self.Status.RECEIVED:
                raise ValidationError(
                    {'status': 'Somente recebimentos recebidos aguardam liberação pela qualidade.'}
                )
            self.status = persisted.status
            self.quality_status = persisted.quality_status
            self.stock_entry_status = persisted.stock_entry_status
            previous_status = persisted.status
            previous_quality_status = persisted.quality_status
            self.status = self.Status.QUALITY_RELEASED
            self.quality_status = quality_status
            self.save(update_fields=['status', 'quality_status', 'updated_at'])
            GovernanceAuditLog.record(
                log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
                severity=GovernanceAuditLog.Severity.INFO,
                module=OperationalModule.PROCUREMENT,
                action='receipt_quality_released',
                target_model='PurchaseReceipt',
                target_record_id=str(self.pk),
                user=user,
                message='Recebimento liberado pela qualidade.',
                safe_context={
                    'from_status': previous_status,
                    'to_status': self.status,
                    'from_quality_status': previous_quality_status,
                    'to_quality_status': quality_status,
                },
            )

    def _validate_stock_entry_status(self, quality_status):
        from inventory.models import StockQualityStatus

        if self.status == self.Status.CANCELLED:
            raise ValidationError({'status': 'Recebimento cancelado não pode ser lançado.'})
        if (
            quality_status == StockQualityStatus.APPROVED
            and self.quality_status != self.QualityStatus.APPROVED
        ):
            raise ValidationError(
                {'quality_status': 'A entrada em estoque exige qualidade aprovada.'}
            )

    def _validate_first_stock_entry(self, items, quality_status):
        """Validate first entry using receipt/items/order items already locked by the caller."""
        from django.db.models import Sum
        from inventory.models import StockMovement, StockQualityStatus

        self._validate_stock_entry_status(quality_status)
        for order_item in {item.order_item_id: item.order_item for item in items}.values():
            accepted_here = sum(
                (item.accepted_quantity for item in items if item.order_item_id == order_item.pk),
                ZERO_QUANTITY,
            )
            accepted_posted = (
                StockMovement.objects.filter(
                    movement_type=StockMovement.MovementType.RECEIPT,
                    source_purchase_receipt_item__order_item_id=order_item.pk,
                )
                .exclude(source_purchase_receipt_item_id__in=[item.pk for item in items])
                .aggregate(quantity=Sum('quantity'))['quantity']
                or ZERO_QUANTITY
            )
            if accepted_posted + accepted_here > order_item.quantity:
                raise ValidationError(
                    {
                        'accepted_quantity': 'A quantidade aceita acumulada não pode superar a quantidade do pedido.'
                    }
                )
        for item in items:
            item.full_clean()
            if item.receipt_id != self.pk or item.order_item.order_id != self.order_id:
                raise ValidationError(
                    {'order_item': 'O item deve pertencer ao pedido do recebimento.'}
                )
            if item.unit_id != item.order_item.unit_id or item.unit_id != item.product.unit_id:
                raise ValidationError({'unit': 'Unidade incompatível; conversão não configurada.'})
            if item.accepted_quantity + item.rejected_quantity != item.received_quantity:
                raise ValidationError({'quantity': 'Reconcilie as quantidades aceita e rejeitada.'})
            if item.accepted_quantity == ZERO_QUANTITY:
                continue
            if not item.lot_number.strip():
                raise ValidationError({'lot_number': 'Informe o lote recebido.'})
            if (
                quality_status == StockQualityStatus.APPROVED
                and item.expiry_date
                and item.expiry_date < timezone.localdate()
            ):
                raise ValidationError(
                    {'expiry_date': 'Lote vencido não pode entrar como aprovado.'}
                )

    @transaction.atomic
    def post_stock(self, warehouse=None, location=None, user=None):
        from inventory.models import StockMovement, StockQualityStatus

        receipt = type(self).objects.select_for_update().get(pk=self.pk)
        receipt._validate_stock_entry_status(StockQualityStatus.APPROVED)
        items = list(receipt.items.select_for_update().order_by('product_id', 'lot_number', 'pk'))
        if not items:
            raise ValidationError({'items': 'O recebimento precisa de ao menos um item.'})
        if not any(item.accepted_quantity > ZERO_QUANTITY for item in items):
            raise ValidationError(
                {'accepted_quantity': 'O lançamento exige quantidade aceita positiva.'}
            )
        if (
            receipt.status == self.Status.STOCK_POSTED
            or receipt.stock_entry_status == self.StockEntryStatus.POSTED
        ):
            if (
                receipt.status != self.Status.STOCK_POSTED
                or receipt.stock_entry_status != self.StockEntryStatus.POSTED
                or any(
                    item.stock_movements.filter(
                        movement_type=StockMovement.MovementType.RECEIPT
                    ).count()
                    != (1 if item.accepted_quantity > ZERO_QUANTITY else 0)
                    for item in items
                )
            ):
                raise ValidationError(
                    {
                        'stock_entry_status': 'Lançamento histórico inconsistente exige reconciliação auditada.'
                    }
                )
        order_items = list(
            PurchaseOrderItem.objects.select_for_update(no_key=True)
            .filter(pk__in={item.order_item_id for item in items})
            .order_by('pk')
        )
        order_items_by_id = {item.pk: item for item in order_items}
        for item in items:
            item.receipt = receipt
            item.order_item = order_items_by_id[item.order_item_id]
        warehouse, location = StockMovement._lock_purchase_address(warehouse, location)
        if receipt.stock_entry_status == self.StockEntryStatus.POSTED:
            # Confirm the historical entry, not first-posting limits against an
            # order quantity legitimately reduced to the accepted amount later.
            for item in items:
                if item.accepted_quantity > ZERO_QUANTITY:
                    StockMovement.receive_purchase_receipt_item(
                        item,
                        warehouse,
                        location,
                        quality_status=StockQualityStatus.APPROVED,
                        user=user,
                    )
            self.__dict__.update(receipt.__dict__)
            return
        receipt._validate_first_stock_entry(items, StockQualityStatus.APPROVED)
        # Validate the entire receipt before prelocking lots and balances. No sequence
        # lock may be held while this batch is still acquiring a new balance lock.
        accepted_items = [item for item in items if item.accepted_quantity > ZERO_QUANTITY]
        pending_items = [
            item
            for item in accepted_items
            if not item.stock_movements.filter(
                movement_type=StockMovement.MovementType.RECEIPT
            ).exists()
        ]
        lots = [
            StockMovement._purchase_receipt_lot(item, StockQualityStatus.APPROVED)
            for item in pending_items
        ]
        StockMovement._lock_receiving_balances(
            (item.product, lot, warehouse, location, StockQualityStatus.APPROVED, item.unit)
            for item, lot in zip(pending_items, lots)
        )
        for item in accepted_items:
            StockMovement.receive_purchase_receipt_item(
                item, warehouse, location, quality_status=StockQualityStatus.APPROVED, user=user
            )
        receipt.status = self.Status.STOCK_POSTED
        receipt.stock_entry_status = self.StockEntryStatus.POSTED
        receipt.save(
            update_fields=['status', 'stock_entry_status', 'updated_at'], _stock_posting=True
        )
        self.__dict__.update(receipt.__dict__)

    def __str__(self):
        return self.receipt_number


class PurchaseReceiptItem(SingleInstanceModel):
    @transaction.atomic
    def save(self, *args, **kwargs):
        receipt_ids = {self.receipt_id}
        if self.pk:
            previous_receipt_id = (
                type(self).objects.filter(pk=self.pk).values_list('receipt_id', flat=True).first()
            )
            receipt_ids.add(previous_receipt_id)
        receipts = (
            PurchaseReceipt.objects.select_for_update().filter(pk__in=receipt_ids).order_by('pk')
        )
        if any(
            receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.POSTED
            for receipt in receipts
        ):
            raise ValidationError({'receipt': 'Itens de recebimento lançado são imutáveis.'})
        if self.pk and self.stock_movements.exists():
            raise ValidationError({'receipt': 'Item com movimento de estoque é imutável.'})
        return super().save(*args, **kwargs)

    receipt = models.ForeignKey(
        PurchaseReceipt, on_delete=models.CASCADE, related_name='items', verbose_name='recebimento'
    )
    order_item = models.ForeignKey(
        PurchaseOrderItem,
        on_delete=models.PROTECT,
        related_name='receipt_items',
        verbose_name='item do pedido',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='purchase_receipt_items',
        verbose_name='item',
    )
    received_quantity = models.DecimalField('quantidade recebida', max_digits=14, decimal_places=4)
    accepted_quantity = models.DecimalField(
        'quantidade aceita', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    rejected_quantity = models.DecimalField(
        'quantidade rejeitada', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='purchase_receipt_items',
        verbose_name='unidade',
    )
    lot_number = models.CharField('lote', max_length=80, blank=True)
    manufacturing_date = models.DateField('fabricação', null=True, blank=True)
    expiry_date = models.DateField('validade', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['receipt__receipt_number', 'product__code']
        indexes = [
            models.Index(fields=['receipt']),
            models.Index(fields=['product']),
            models.Index(fields=['lot_number']),
            models.Index(fields=['manufacturing_date']),
            models.Index(fields=['expiry_date']),
        ]
        verbose_name = 'item do recebimento'
        verbose_name_plural = 'itens do recebimento'

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('received_quantity', 'accepted_quantity', 'rejected_quantity'):
            value = getattr(self, field_name)
            if value is not None and value < 0:
                errors[field_name] = 'A quantidade não pode ser negativa.'
        if self.received_quantity is not None and self.received_quantity <= 0:
            errors['received_quantity'] = 'A quantidade recebida deve ser maior que zero.'
        if (
            self.received_quantity is not None
            and self.accepted_quantity is not None
            and self.rejected_quantity is not None
            and self.accepted_quantity + self.rejected_quantity > self.received_quantity
        ):
            errors['accepted_quantity'] = (
                'A soma das quantidades aceita e rejeitada não pode superar a recebida.'
            )
        if self.order_item_id and self.product_id and self.order_item.product_id != self.product_id:
            errors['product'] = 'O produto recebido deve ser o mesmo item do pedido.'
        if (
            self.order_item_id
            and self.received_quantity is not None
            and self.received_quantity > self.order_item.quantity
        ):
            errors['received_quantity'] = (
                'A quantidade recebida não pode superar a quantidade do pedido.'
            )
        if (
            self.manufacturing_date
            and self.expiry_date
            and self.manufacturing_date > self.expiry_date
        ):
            errors['manufacturing_date'] = 'A fabricação não pode ser posterior à data de validade.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.receipt} - {self.product}'
