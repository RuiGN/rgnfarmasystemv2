from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from base.normalized_locations import validate_normalized_location
from masters.models import BusinessPartner, Product
from procurement.models import PurchaseOrder, PurchaseReceipt


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


class TaxKindChoices(models.TextChoices):
    ICMS = 'icms', 'ICMS'
    IPI = 'ipi', 'IPI'
    PIS = 'pis', 'PIS'
    COFINS = 'cofins', 'COFINS'
    ISS = 'iss', 'ISS'
    IRRF = 'irrf', 'IRRF'
    INSS = 'inss', 'INSS'
    CSLL = 'csll', 'CSLL'
    RETENTION = 'retention', 'Retenção'


class FiscalCompany(SingleInstanceModel):
    class TaxRegime(models.TextChoices):
        SIMPLES_NACIONAL = 'simples_nacional', 'Simples Nacional'
        LUCRO_PRESUMIDO = 'lucro_presumido', 'Lucro Presumido'
        LUCRO_REAL = 'lucro_real', 'Lucro Real'
        EXEMPT = 'exempt', 'Isento'

    legal_name = models.CharField('razão social', max_length=255)
    document = models.CharField('CNPJ/CPF', max_length=32)
    state_registration = models.CharField('inscrição estadual', max_length=40, blank=True)
    municipal_registration = models.CharField('inscrição municipal', max_length=40, blank=True)
    tax_regime = models.CharField('regime tributário', max_length=32, choices=TaxRegime.choices)
    zipcode = models.CharField('CEP', max_length=20, blank=True)
    street = models.CharField('logradouro', max_length=200, blank=True)
    street_number = models.CharField('número', max_length=20, blank=True)
    complement = models.CharField('complemento', max_length=100, blank=True)
    neighborhood = models.CharField('bairro', max_length=120, blank=True)
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
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['legal_name']
        constraints = [
            models.UniqueConstraint(fields=['document'], name='unique_fiscal_company_document'),
        ]
        indexes = [
            models.Index(fields=['tax_regime', 'is_active']),
            models.Index(fields=['document']),
            models.Index(fields=['state_ref', 'city_ref']),
        ]
        verbose_name = 'empresa fiscal'
        verbose_name_plural = 'empresas fiscais'

    def clean(self):
        super().clean()
        validate_normalized_location(self, require=True)

    def __str__(self):
        return self.legal_name


class FiscalMunicipality(SingleInstanceModel):
    ibge_code = models.CharField('código IBGE', max_length=16)
    name = models.CharField('município', max_length=120, blank=True)
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
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['state_ref__name', 'name']
        constraints = [
            models.UniqueConstraint(fields=['ibge_code'], name='unique_fiscal_municipality_ibge'),
        ]
        indexes = [
            models.Index(fields=['state_ref', 'is_active']),
            models.Index(fields=['ibge_code']),
        ]
        verbose_name = 'município fiscal'
        verbose_name_plural = 'municípios fiscais'

    def clean(self):
        super().clean()
        validate_normalized_location(self, require=True)
        if self.city_ref and not self.name:
            self.name = self.city_ref.name

    def __str__(self):
        state = self.state_ref.name if self.state_ref else ''
        return f'{self.name}/{state}'.rstrip('/')


class FiscalUnit(AutoCodeMixin, SingleInstanceModel):
    # Código oficial: unidade fiscal legal (UN, KG, CX). Informado pelo usuário, nunca gerado.
    CODE_PREFIX = None

    code = models.CharField('código', max_length=20)
    description = models.CharField('descrição', max_length=120)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_fiscal_unit_code'),
        ]
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'unidade fiscal'
        verbose_name_plural = 'unidades fiscais'

    def __str__(self):
        return f'{self.code} - {self.description}'


class FiscalNCM(AutoCodeMixin, SingleInstanceModel):
    # Código oficial: NCM da NCM/SH (3304.99.90). Informado pelo usuário, nunca gerado.
    CODE_PREFIX = None

    code = models.CharField('NCM', max_length=12)
    description = models.CharField('descrição', max_length=255)
    cest = models.CharField('CEST', max_length=16, blank=True)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_fiscal_ncm_code'),
        ]
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['code']),
            models.Index(fields=['cest']),
        ]
        verbose_name = 'NCM'
        verbose_name_plural = 'NCMs'

    def __str__(self):
        return f'{self.code} - {self.description}'


class FiscalOperationCode(AutoCodeMixin, SingleInstanceModel):
    # Código oficial: CFOP oficial (5101). Informado pelo usuário, nunca gerado.
    CODE_PREFIX = None

    class Direction(models.TextChoices):
        INBOUND = 'inbound', 'Entrada'
        OUTBOUND = 'outbound', 'Saída'
        BOTH = 'both', 'Entrada e saída'

    code = models.CharField('CFOP', max_length=8)
    description = models.CharField('descrição', max_length=255)
    direction = models.CharField('direção', max_length=16, choices=Direction.choices)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_cfop_code'),
        ]
        indexes = [
            models.Index(fields=['direction', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'CFOP'
        verbose_name_plural = 'CFOPs'

    def __str__(self):
        return f'{self.code} - {self.description}'


class TaxSituation(AutoCodeMixin, SingleInstanceModel):
    # Código oficial: CST/CSOSN oficial (060). Informado pelo usuário, nunca gerado.
    CODE_PREFIX = None

    TaxKind = TaxKindChoices

    class RegimeKind(models.TextChoices):
        CST = 'cst', 'CST'
        CSOSN = 'csosn', 'CSOSN'

    code = models.CharField('código', max_length=8)
    tax_kind = models.CharField('tributo', max_length=24, choices=TaxKind.choices)
    regime_kind = models.CharField('regime do código', max_length=16, choices=RegimeKind.choices)
    description = models.CharField('descrição', max_length=255)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['tax_kind', 'regime_kind', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['tax_kind', 'regime_kind', 'code'],
                name='unique_tax_situation',
            ),
        ]
        indexes = [
            models.Index(fields=['tax_kind', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'CST/CSOSN'
        verbose_name_plural = 'CST/CSOSN'

    def __str__(self):
        return f'{self.get_tax_kind_display()} {self.regime_kind.upper()} {self.code}'


class FiscalAuditTrail(SingleInstanceModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='fiscal_audit_events',
        null=True,
        blank=True,
        verbose_name='usuário',
    )
    entity_name = models.CharField('entidade', max_length=120)
    object_id = models.CharField('objeto', max_length=80)
    action = models.CharField('ação', max_length=80)
    details = models.JSONField('detalhes', default=dict, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['entity_name', 'object_id']),
            models.Index(fields=['action']),
            models.Index(fields=['created_at']),
        ]
        verbose_name = 'auditoria fiscal'
        verbose_name_plural = 'auditorias fiscais'

    @classmethod
    def record(cls, actor, entity_name, object_id, action, details=None):
        return cls.objects.create(
            actor=actor,
            entity_name=entity_name,
            object_id=str(object_id),
            action=action,
            details=details or {},
        )

    def clean(self):
        super().clean()
        if False:
            raise ValidationError({'actor': 'O usuário relacionado é incompatível com o registro.'})

    def __str__(self):
        return f'{self.entity_name}:{self.object_id} - {self.action}'


class TaxRule(SingleInstanceModel):
    TaxKind = TaxKindChoices

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovada'
        OBSOLETE = 'obsolete', 'Obsoleta'

    name = models.CharField('nome', max_length=160)
    tax_kind = models.CharField('tributo', max_length=24, choices=TaxKind.choices)
    company = models.ForeignKey(
        FiscalCompany,
        on_delete=models.PROTECT,
        related_name='tax_rules',
        null=True,
        blank=True,
        verbose_name='empresa',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='tax_rules',
        null=True,
        blank=True,
        verbose_name='produto',
    )
    partner = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='tax_rules',
        null=True,
        blank=True,
        verbose_name='parceiro',
    )
    ncm = models.ForeignKey(
        FiscalNCM, on_delete=models.PROTECT, related_name='tax_rules', verbose_name='NCM'
    )
    cfop = models.ForeignKey(
        FiscalOperationCode, on_delete=models.PROTECT, related_name='tax_rules', verbose_name='CFOP'
    )
    tax_situation = models.ForeignKey(
        TaxSituation, on_delete=models.PROTECT, related_name='tax_rules', verbose_name='CST/CSOSN'
    )
    rate_percent = models.DecimalField(
        'alíquota (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    reduction_percent = models.DecimalField(
        'redução (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    retention_percent = models.DecimalField(
        'retenção (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    effective_from = models.DateField('vigência inicial')
    effective_to = models.DateField('vigência final', null=True, blank=True)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_tax_rules',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['tax_kind', 'name']
        indexes = [
            models.Index(fields=['tax_kind', 'status']),
            models.Index(fields=['ncm', 'cfop']),
            models.Index(fields=['effective_from', 'effective_to']),
        ]
        verbose_name = 'regra tributária'
        verbose_name_plural = 'regras tributárias'

    def calculate_tax(self, base_amount):
        reduced_base = _money(base_amount) * (
            Decimal('1.0000') - _percent_factor(self.reduction_percent)
        )
        return _money(reduced_base * _percent_factor(self.rate_percent))

    def approve(self, user=None):
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        FiscalAuditTrail.record(user, 'TaxRule', self.pk, 'approved', {'name': self.name})

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('company', 'product', 'partner', 'ncm', 'cfop', 'tax_situation'):
            pass
        if self.tax_situation and self.tax_situation.tax_kind != self.tax_kind:
            errors['tax_situation'] = 'A situação tributária deve ser do mesmo tributo da regra.'
        if self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = 'A vigência final não pode ser anterior à inicial.'
        for field_name in ('rate_percent', 'reduction_percent', 'retention_percent'):
            value = getattr(self, field_name)
            if value < 0 or value > PERCENT_BASE:
                errors[field_name] = 'O percentual deve estar entre 0 e 100.'
        if errors:
            raise ValidationError(errors)

        return None

        return None

    def __str__(self):
        return f'{self.name} - {self.get_tax_kind_display()}'


class FiscalDocument(SingleInstanceModel):
    class ElectronicModel(models.TextChoices):
        NFE_55 = '55', 'NF-e modelo 55'

    class Environment(models.TextChoices):
        HOMOLOGATION = 'homologation', 'Homologação'
        PRODUCTION = 'production', 'Produção'

    class EmissionStatus(models.TextChoices):
        NOT_SENT = 'not_sent', 'Não enviada'
        VALIDATING = 'validating', 'Validando'
        SENT = 'sent', 'Transmitida'
        AUTHORIZED = 'authorized', 'Autorizada'
        REJECTED = 'rejected', 'Rejeitada'
        CANCELLED = 'cancelled', 'Cancelada'
        ERROR = 'error', 'Erro'

    class DocumentType(models.TextChoices):
        INBOUND = 'inbound', 'Entrada'
        OUTBOUND = 'outbound', 'Saída'

    class OperationType(models.TextChoices):
        PURCHASE = 'purchase', 'Compra'
        SALE = 'sale', 'Venda'
        SERVICE = 'service', 'Serviço'
        RETURN = 'return', 'Devolução'
        TRANSFER = 'transfer', 'Transferência'
        OTHER = 'other', 'Outra'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        UNDER_REVIEW = 'under_review', 'Em conferência'
        REVIEWED = 'reviewed', 'Conferida'
        APPROVED = 'approved', 'Aprovada'
        POSTED = 'posted', 'Lançada'
        CANCELLED = 'cancelled', 'Cancelada'

    company = models.ForeignKey(
        FiscalCompany,
        on_delete=models.PROTECT,
        related_name='fiscal_documents',
        verbose_name='empresa',
    )
    partner = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='fiscal_documents',
        verbose_name='parceiro',
    )
    document_type = models.CharField('tipo', max_length=24, choices=DocumentType.choices)
    operation_type = models.CharField('operação', max_length=24, choices=OperationType.choices)
    number = models.CharField('número', max_length=80)
    series = models.CharField('série', max_length=20)
    issue_date = models.DateField('emissão')
    operation_date = models.DateField('operação')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    electronic_model = models.CharField(
        'modelo eletrônico',
        max_length=4,
        choices=ElectronicModel.choices,
        default=ElectronicModel.NFE_55,
    )
    environment = models.CharField(
        'ambiente fiscal',
        max_length=24,
        choices=Environment.choices,
        default=Environment.HOMOLOGATION,
    )
    emission_status = models.CharField(
        'status de emissão',
        max_length=24,
        choices=EmissionStatus.choices,
        default=EmissionStatus.NOT_SENT,
    )
    access_key = models.CharField('chave de acesso', max_length=64, blank=True)
    authorization_protocol = models.CharField('protocolo de autorização', max_length=80, blank=True)
    authorization_at = models.DateTimeField('autorizada em', null=True, blank=True)
    cancel_protocol = models.CharField('protocolo de cancelamento', max_length=80, blank=True)
    cancelled_at = models.DateTimeField('cancelada em', null=True, blank=True)
    rejection_code = models.CharField('código de rejeição', max_length=24, blank=True)
    rejection_reason = models.TextField('motivo de rejeição', blank=True)
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.PROTECT,
        related_name='fiscal_documents',
        null=True,
        blank=True,
        verbose_name='pedido de compra',
    )
    purchase_receipt = models.ForeignKey(
        PurchaseReceipt,
        on_delete=models.PROTECT,
        related_name='fiscal_documents',
        null=True,
        blank=True,
        verbose_name='recebimento',
    )
    financial_title = models.ForeignKey(
        'finance.FinancialTitle',
        on_delete=models.PROTECT,
        related_name='fiscal_documents',
        null=True,
        blank=True,
        verbose_name='título financeiro',
    )
    total_products = models.DecimalField(
        'total produtos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    total_taxes = models.DecimalField(
        'total impostos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    retained_taxes = models.DecimalField(
        'retenções', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    total_amount = models.DecimalField(
        'total da nota', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='reviewed_fiscal_documents',
        null=True,
        blank=True,
        verbose_name='conferida por',
    )
    reviewed_at = models.DateTimeField('conferida em', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_fiscal_documents',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='posted_fiscal_documents',
        null=True,
        blank=True,
        verbose_name='lançada por',
    )
    posted_at = models.DateTimeField('lançada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-issue_date', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['document_type', 'number', 'series', 'partner'],
                name='unique_fiscal_document_number',
            ),
        ]
        indexes = [
            models.Index(fields=['document_type', 'status']),
            models.Index(fields=['operation_type']),
            models.Index(fields=['emission_status']),
            models.Index(fields=['issue_date']),
            models.Index(fields=['partner']),
            models.Index(fields=['number', 'series']),
            models.Index(fields=['access_key']),
        ]
        permissions = [
            ('issue_fiscaldocument', 'Pode emitir NF-e'),
            ('cancel_fiscaldocument', 'Pode cancelar NF-e'),
            ('send_email_fiscaldocument', 'Pode enviar NF-e por e-mail'),
            ('download_fiscaldocument', 'Pode baixar XML/DANFE fiscal'),
        ]
        verbose_name = 'documento fiscal'
        verbose_name_plural = 'documentos fiscais'

    def recalculate_totals(self, save=True):
        self.total_products = _money(
            sum((item.line_total for item in self.items.all()), ZERO_MONEY)
        )
        taxes = list(self.taxes.all())
        self.total_taxes = _money(sum((tax.tax_amount for tax in taxes), ZERO_MONEY))
        self.retained_taxes = _money(
            sum((tax.tax_amount for tax in taxes if tax.is_retained), ZERO_MONEY)
        )
        self.total_amount = _money(self.total_products + self.total_taxes - self.retained_taxes)
        self.full_clean(validate_unique=False)
        if save:
            self.save(
                update_fields=[
                    'total_products',
                    'total_taxes',
                    'retained_taxes',
                    'total_amount',
                    'updated_at',
                ]
            )
        return self.total_amount

    def submit_for_review(self):
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {'status': 'Somente documentos em rascunho podem ir para conferência.'}
            )
        self.status = self.Status.UNDER_REVIEW
        self.save(update_fields=['status', 'updated_at'])

    def review(self, user=None):
        if self.status != self.Status.UNDER_REVIEW:
            raise ValidationError({'status': 'A conferência exige documento em conferência.'})
        self.status = self.Status.REVIEWED
        self.reviewed_by = user
        self.reviewed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'updated_at'])
        FiscalAuditTrail.record(
            user, 'FiscalDocument', self.pk, 'reviewed', {'number': self.number}
        )

    def approve(self, user=None):
        if self.status != self.Status.REVIEWED:
            raise ValidationError({'status': 'A aprovação exige documento conferido.'})
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
        FiscalAuditTrail.record(
            user, 'FiscalDocument', self.pk, 'approved', {'number': self.number}
        )

    def post_entry(self, user=None):
        if self.status != self.Status.APPROVED:
            raise ValidationError(
                {'status': 'A entrada definitiva exige documento fiscal aprovado.'}
            )
        self.status = self.Status.POSTED
        self.posted_by = user
        self.posted_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'posted_by', 'posted_at', 'updated_at'])
        FiscalAuditTrail.record(user, 'FiscalDocument', self.pk, 'posted', {'number': self.number})

    def create_financial_title(self, category, due_date):
        from finance.models import FinancialTitle

        if False:
            raise ValidationError(
                {'category': 'A categoria financeira é incompatível com o registro.'}
            )
        if self.total_amount <= 0:
            raise ValidationError(
                {'total_amount': 'A nota fiscal precisa ter valor total maior que zero.'}
            )
        title = FinancialTitle.objects.create(
            title_type=(
                FinancialTitle.TitleType.PAYABLE
                if self.document_type == self.DocumentType.INBOUND
                else FinancialTitle.TitleType.RECEIVABLE
            ),
            source_type=FinancialTitle.SourceType.FISCAL_NOTE,
            partner=self.partner,
            category=category,
            fiscal_document_number=self.number,
            issue_date=self.issue_date,
            due_date=due_date,
            original_amount=self.total_amount,
            open_amount=self.total_amount,
        )
        self.financial_title = title
        self.save(update_fields=['financial_title', 'updated_at'])
        return title

    def clean(self):
        super().clean()
        errors = {}
        for field_name in (
            'company',
            'partner',
            'purchase_order',
            'purchase_receipt',
            'financial_title',
            'reviewed_by',
            'approved_by',
            'posted_by',
        ):
            pass
        if (
            self.purchase_receipt
            and self.purchase_order
            and self.purchase_receipt.order_id != self.purchase_order_id
        ):
            errors['purchase_receipt'] = (
                'O recebimento deve pertencer ao pedido de compra informado.'
            )
        if self.operation_date and self.issue_date and self.operation_date < self.issue_date:
            errors['operation_date'] = 'A data de operação não pode ser anterior à emissão.'
        for field_name in ('total_products', 'total_taxes', 'retained_taxes', 'total_amount'):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O valor não pode ser negativo.'
        if self.emission_status == self.EmissionStatus.AUTHORIZED and not self.access_key:
            errors['access_key'] = 'Documento autorizado deve ter chave de acesso.'
        if self.emission_status == self.EmissionStatus.CANCELLED and not self.cancel_protocol:
            errors['cancel_protocol'] = 'Documento cancelado deve ter protocolo de cancelamento.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.number}/{self.series}'


class FiscalEmissionEvent(SingleInstanceModel):
    class EventType(models.TextChoices):
        VALIDATION_FAILED = 'validation_failed', 'Validação falhou'
        SENT = 'sent', 'Transmitida'
        AUTHORIZED = 'authorized', 'Autorizada'
        REJECTED = 'rejected', 'Rejeitada'
        CANCELLED = 'cancelled', 'Cancelada'
        STATUS_CHECKED = 'status_checked', 'Status consultado'
        EMAIL_SCHEDULED = 'email_scheduled', 'E-mail agendado'
        EMAIL_SENT = 'email_sent', 'E-mail enviado'
        EMAIL_FAILED = 'email_failed', 'E-mail falhou'
        ERROR = 'error', 'Erro'

    document = models.ForeignKey(
        FiscalDocument,
        on_delete=models.PROTECT,
        related_name='emission_events',
        verbose_name='documento',
    )
    event_type = models.CharField('tipo de evento', max_length=40, choices=EventType.choices)
    provider = models.CharField('provedor', max_length=80, blank=True)
    status = models.CharField('status externo', max_length=40, blank=True)
    access_key = models.CharField('chave de acesso', max_length=64, blank=True)
    protocol = models.CharField('protocolo', max_length=80, blank=True)
    message = models.TextField('mensagem', blank=True)
    payload = models.JSONField('contexto seguro', default=dict, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='fiscal_emission_events',
        null=True,
        blank=True,
        verbose_name='usuário',
    )
    xml_file = models.ForeignKey(
        'files.ProtectedFile',
        on_delete=models.PROTECT,
        related_name='fiscal_xml_emission_events',
        null=True,
        blank=True,
        verbose_name='XML protegido',
    )
    danfe_file = models.ForeignKey(
        'files.ProtectedFile',
        on_delete=models.PROTECT,
        related_name='fiscal_danfe_emission_events',
        null=True,
        blank=True,
        verbose_name='DANFE protegido',
    )

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document', 'event_type']),
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['access_key']),
        ]
        verbose_name = 'evento de emissão fiscal'
        verbose_name_plural = 'eventos de emissão fiscal'

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('document', 'xml_file', 'danfe_file'):
            pass
        if False:
            errors['actor'] = 'O usuário relacionado é incompatível com o registro.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.document} - {self.get_event_type_display()}'


class FiscalEmailDelivery(SingleInstanceModel):
    class Status(models.TextChoices):
        SCHEDULED = 'scheduled', 'Agendado'
        SENDING = 'sending', 'Enviando'
        SENT = 'sent', 'Enviado'
        FAILED = 'failed', 'Falhou'
        CANCELLED = 'cancelled', 'Cancelado'

    document = models.ForeignKey(
        FiscalDocument,
        on_delete=models.PROTECT,
        related_name='email_deliveries',
        verbose_name='documento',
    )
    recipient_email = models.EmailField('destinatário')
    subject = models.CharField('assunto', max_length=255)
    body = models.TextField('corpo')
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.SCHEDULED
    )
    scheduled_at = models.DateTimeField('agendado para')
    sent_at = models.DateTimeField('enviado em', null=True, blank=True)
    failed_at = models.DateTimeField('falhou em', null=True, blank=True)
    attempts = models.PositiveSmallIntegerField('tentativas', default=0)
    last_error = models.TextField('último erro', blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_fiscal_email_deliveries',
        null=True,
        blank=True,
        verbose_name='solicitado por',
    )
    xml_file = models.ForeignKey(
        'files.ProtectedFile',
        on_delete=models.PROTECT,
        related_name='fiscal_xml_email_deliveries',
        null=True,
        blank=True,
        verbose_name='XML protegido',
    )
    danfe_file = models.ForeignKey(
        'files.ProtectedFile',
        on_delete=models.PROTECT,
        related_name='fiscal_danfe_email_deliveries',
        null=True,
        blank=True,
        verbose_name='DANFE protegido',
    )

    class Meta:
        ordering = ['-scheduled_at', '-created_at']
        indexes = [
            models.Index(fields=['document', 'status']),
            models.Index(fields=['status', 'scheduled_at']),
            models.Index(fields=['recipient_email']),
        ]
        verbose_name = 'envio de NF-e por e-mail'
        verbose_name_plural = 'envios de NF-e por e-mail'

    def mark_sending(self):
        self.status = self.Status.SENDING
        self.attempts += 1
        self.last_error = ''
        self.save(update_fields=['status', 'attempts', 'last_error', 'updated_at'])

    def mark_sent(self):
        self.status = self.Status.SENT
        self.sent_at = timezone.now()
        self.last_error = ''
        self.save(update_fields=['status', 'sent_at', 'last_error', 'updated_at'])

    def mark_failed(self, error_message):
        self.status = self.Status.FAILED
        self.failed_at = timezone.now()
        self.last_error = str(error_message or 'Falha ao enviar e-mail fiscal.')[:4000]
        self.save(update_fields=['status', 'failed_at', 'last_error', 'updated_at'])

    def cancel(self):
        if self.status == self.Status.SENT:
            raise ValidationError({'status': 'Envio já concluído não pode ser cancelado.'})
        self.status = self.Status.CANCELLED
        self.save(update_fields=['status', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('document', 'xml_file', 'danfe_file'):
            pass
        if (
            self.document
            and self.document.emission_status != FiscalDocument.EmissionStatus.AUTHORIZED
        ):
            errors['document'] = 'Somente NF-e autorizada pode ser enviada por e-mail.'
        if not self.recipient_email:
            errors['recipient_email'] = 'Informe o destinatário.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.document} -> {self.recipient_email}'


class FiscalDocumentItem(SingleInstanceModel):
    document = models.ForeignKey(
        FiscalDocument, on_delete=models.CASCADE, related_name='items', verbose_name='documento'
    )
    line_number = models.PositiveIntegerField('linha')
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='fiscal_document_items',
        verbose_name='produto',
    )
    fiscal_unit = models.ForeignKey(
        FiscalUnit,
        on_delete=models.PROTECT,
        related_name='fiscal_document_items',
        verbose_name='unidade fiscal',
    )
    ncm = models.ForeignKey(
        FiscalNCM,
        on_delete=models.PROTECT,
        related_name='fiscal_document_items',
        verbose_name='NCM',
    )
    cfop = models.ForeignKey(
        FiscalOperationCode,
        on_delete=models.PROTECT,
        related_name='fiscal_document_items',
        verbose_name='CFOP',
    )
    tax_situation = models.ForeignKey(
        TaxSituation,
        on_delete=models.PROTECT,
        related_name='fiscal_document_items',
        verbose_name='CST/CSOSN',
    )
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit_price = models.DecimalField('valor unitário', max_digits=14, decimal_places=4)
    discount_amount = models.DecimalField(
        'desconto', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    freight_amount = models.DecimalField(
        'frete', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    insurance_amount = models.DecimalField(
        'seguro', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    other_amount = models.DecimalField(
        'outras despesas', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )

    class Meta:
        ordering = ['document', 'line_number']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'line_number'],
                name='unique_fiscal_document_line',
            ),
        ]
        indexes = [
            models.Index(fields=['document']),
            models.Index(fields=['product']),
            models.Index(fields=['ncm', 'cfop']),
        ]
        verbose_name = 'item de documento fiscal'
        verbose_name_plural = 'itens de documentos fiscais'

    @property
    def line_subtotal(self):
        return _money(self.quantity * self.unit_price)

    @property
    def line_total(self):
        return _money(
            self.line_subtotal
            - self.discount_amount
            + self.freight_amount
            + self.insurance_amount
            + self.other_amount
        )

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('document', 'product', 'fiscal_unit', 'ncm', 'cfop', 'tax_situation'):
            pass
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.unit_price < 0:
            errors['unit_price'] = 'O valor unitário não pode ser negativo.'
        for field_name in ('discount_amount', 'freight_amount', 'insurance_amount', 'other_amount'):
            if getattr(self, field_name) < 0:
                errors[field_name] = 'O valor não pode ser negativo.'
        if (
            self.document
            and self.cfop
            and self.cfop.direction != FiscalOperationCode.Direction.BOTH
        ):
            expected = (
                FiscalOperationCode.Direction.INBOUND
                if self.document.document_type == FiscalDocument.DocumentType.INBOUND
                else FiscalOperationCode.Direction.OUTBOUND
            )
            if self.cfop.direction != expected:
                errors['cfop'] = 'O CFOP deve ser compatível com entrada ou saída do documento.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.document} - {self.line_number}'


class FiscalTax(SingleInstanceModel):
    TaxKind = TaxKindChoices

    document = models.ForeignKey(
        FiscalDocument, on_delete=models.CASCADE, related_name='taxes', verbose_name='documento'
    )
    item = models.ForeignKey(
        FiscalDocumentItem,
        on_delete=models.CASCADE,
        related_name='taxes',
        null=True,
        blank=True,
        verbose_name='item',
    )
    tax_rule = models.ForeignKey(
        TaxRule,
        on_delete=models.PROTECT,
        related_name='fiscal_taxes',
        null=True,
        blank=True,
        verbose_name='regra tributária',
    )
    tax_kind = models.CharField('tributo', max_length=24, choices=TaxKind.choices)
    base_amount = models.DecimalField('base', max_digits=14, decimal_places=4)
    rate_percent = models.DecimalField(
        'alíquota (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    reduction_percent = models.DecimalField(
        'redução (%)', max_digits=9, decimal_places=4, default=ZERO_MONEY
    )
    tax_amount = models.DecimalField('valor', max_digits=14, decimal_places=4, default=ZERO_MONEY)
    is_retained = models.BooleanField('retido', default=False)

    class Meta:
        ordering = ['document', 'tax_kind']
        indexes = [
            models.Index(fields=['document', 'tax_kind']),
            models.Index(fields=['tax_kind', 'is_retained']),
            models.Index(fields=['item']),
        ]
        verbose_name = 'imposto do documento'
        verbose_name_plural = 'impostos dos documentos'

    def calculate(self, save=True):
        reduced_base = self.base_amount * (
            Decimal('1.0000') - _percent_factor(self.reduction_percent)
        )
        self.tax_amount = _money(reduced_base * _percent_factor(self.rate_percent))
        self.full_clean(validate_unique=False)
        if save:
            self.save(update_fields=['tax_amount', 'updated_at'])
        return self.tax_amount

    def save(self, *args, **kwargs):
        reduced_base = self.base_amount * (
            Decimal('1.0000') - _percent_factor(self.reduction_percent)
        )
        self.tax_amount = _money(reduced_base * _percent_factor(self.rate_percent))
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('document', 'item', 'tax_rule'):
            pass
        if self.item and self.item.document_id != self.document_id:
            errors['item'] = 'O item deve pertencer ao documento informado.'
        if self.tax_rule and self.tax_rule.tax_kind != self.tax_kind:
            errors['tax_rule'] = 'A regra tributária deve ser do mesmo tributo.'
        if self.base_amount < 0:
            errors['base_amount'] = 'A base não pode ser negativa.'
        for field_name in ('rate_percent', 'reduction_percent'):
            value = getattr(self, field_name)
            if value < 0 or value > PERCENT_BASE:
                errors[field_name] = 'O percentual deve estar entre 0 e 100.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.document} - {self.get_tax_kind_display()}'


class TaxAssessmentPeriod(SingleInstanceModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        CALCULATED = 'calculated', 'Calculada'
        CLOSED = 'closed', 'Fechada'
        REOPENED = 'reopened', 'Reaberta'

    period_year = models.PositiveSmallIntegerField('ano')
    period_month = models.PositiveSmallIntegerField('mês')
    tax_kind = models.CharField('tributo', max_length=24, choices=TaxKindChoices.choices)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    debit_amount = models.DecimalField(
        'débitos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    credit_amount = models.DecimalField(
        'créditos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    retained_amount = models.DecimalField(
        'retenções', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    balance_amount = models.DecimalField(
        'saldo', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    calculated_at = models.DateTimeField('calculada em', null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_tax_assessments',
        null=True,
        blank=True,
        verbose_name='fechada por',
    )
    closed_at = models.DateTimeField('fechada em', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-period_year', '-period_month', 'tax_kind']
        constraints = [
            models.UniqueConstraint(
                fields=['period_year', 'period_month', 'tax_kind'],
                name='unique_tax_assessment_period',
            ),
        ]
        indexes = [
            models.Index(fields=['period_year', 'period_month']),
            models.Index(fields=['tax_kind', 'status']),
        ]
        verbose_name = 'apuração fiscal'
        verbose_name_plural = 'apurações fiscais'

    def calculate(self):
        taxes = FiscalTax.objects.select_related('document').filter(
            tax_kind=self.tax_kind,
            document__status=FiscalDocument.Status.POSTED,
            document__issue_date__year=self.period_year,
            document__issue_date__month=self.period_month,
        )
        self.debit_amount = _money(
            sum(
                (
                    tax.tax_amount
                    for tax in taxes
                    if tax.document.document_type == FiscalDocument.DocumentType.OUTBOUND
                    and not tax.is_retained
                ),
                ZERO_MONEY,
            )
        )
        self.credit_amount = _money(
            sum(
                (
                    tax.tax_amount
                    for tax in taxes
                    if tax.document.document_type == FiscalDocument.DocumentType.INBOUND
                    and not tax.is_retained
                ),
                ZERO_MONEY,
            )
        )
        self.retained_amount = _money(
            sum((tax.tax_amount for tax in taxes if tax.is_retained), ZERO_MONEY)
        )
        self.balance_amount = _money(self.debit_amount - self.credit_amount - self.retained_amount)
        self.status = self.Status.CALCULATED
        self.calculated_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'debit_amount',
                'credit_amount',
                'retained_amount',
                'balance_amount',
                'status',
                'calculated_at',
                'updated_at',
            ]
        )

    def close(self, user=None):
        if self.status != self.Status.CALCULATED:
            raise ValidationError({'status': 'O fechamento exige apuração calculada.'})
        self.status = self.Status.CLOSED
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'closed_by', 'closed_at', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        if not 1 <= self.period_month <= 12:
            errors['period_month'] = 'O mês deve estar entre 1 e 12.'
        if self.period_year < 2000:
            errors['period_year'] = 'Informe um ano válido.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.period_year:04d}-{self.period_month:02d} {self.tax_kind}'


class FiscalBookEntry(SingleInstanceModel):
    class BookType(models.TextChoices):
        INBOUND = 'inbound', 'Livro de entradas'
        OUTBOUND = 'outbound', 'Livro de saídas'
        SERVICE = 'service', 'Livro de serviços'

    document = models.ForeignKey(
        FiscalDocument,
        on_delete=models.PROTECT,
        related_name='book_entries',
        verbose_name='documento',
    )
    book_type = models.CharField('livro', max_length=24, choices=BookType.choices)
    entry_date = models.DateField('data de escrituração')
    total_amount = models.DecimalField(
        'valor total', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    tax_amount = models.DecimalField(
        'valor impostos', max_digits=14, decimal_places=4, default=ZERO_MONEY
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-entry_date', 'document__number']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'book_type'], name='unique_document_book_entry'
            ),
        ]
        indexes = [
            models.Index(fields=['book_type', 'entry_date']),
            models.Index(fields=['document']),
        ]
        verbose_name = 'livro fiscal'
        verbose_name_plural = 'livros fiscais'

    @classmethod
    def create_from_document(cls, document):
        return cls.objects.create(
            document=document,
            book_type=cls.BookType.INBOUND
            if document.document_type == FiscalDocument.DocumentType.INBOUND
            else cls.BookType.OUTBOUND,
            entry_date=document.operation_date,
            total_amount=document.total_amount,
            tax_amount=document.total_taxes,
        )

    def clean(self):
        super().clean()
        if False:
            raise ValidationError(
                {'document': 'O documento relacionado é incompatível com o registro.'}
            )


class FiscalObligation(SingleInstanceModel):
    class ObligationType(models.TextChoices):
        SPED_FISCAL = 'sped_fiscal', 'SPED Fiscal'
        SPED_CONTRIB = 'sped_contrib', 'SPED Contribuições'
        GIA = 'gia', 'GIA'
        DCTF = 'dctf', 'DCTF'
        MUNICIPAL = 'municipal', 'Obrigação municipal'
        OTHER = 'other', 'Outra'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        SUBMITTED = 'submitted', 'Entregue'
        ACCEPTED = 'accepted', 'Aceita'
        OVERDUE = 'overdue', 'Vencida'
        CANCELLED = 'cancelled', 'Cancelada'

    obligation_type = models.CharField('obrigação', max_length=32, choices=ObligationType.choices)
    period_year = models.PositiveSmallIntegerField('ano')
    period_month = models.PositiveSmallIntegerField('mês')
    due_date = models.DateField('vencimento')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_fiscal_obligations',
        null=True,
        blank=True,
        verbose_name='entregue por',
    )
    submitted_at = models.DateTimeField('entregue em', null=True, blank=True)
    protocol_number = models.CharField('protocolo', max_length=80, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['due_date', 'obligation_type']
        constraints = [
            models.UniqueConstraint(
                fields=['obligation_type', 'period_year', 'period_month'],
                name='unique_fiscal_obligation_period',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'due_date']),
            models.Index(fields=['obligation_type']),
        ]
        verbose_name = 'obrigação fiscal'
        verbose_name_plural = 'obrigações fiscais'

    def submit(self, user=None, protocol_number=''):
        if self.status != self.Status.OPEN:
            raise ValidationError({'status': 'Somente obrigações abertas podem ser entregues.'})
        self.status = self.Status.SUBMITTED
        self.submitted_by = user
        self.submitted_at = timezone.now()
        self.protocol_number = protocol_number
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'submitted_by',
                'submitted_at',
                'protocol_number',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        if not 1 <= self.period_month <= 12:
            errors['period_month'] = 'O mês deve estar entre 1 e 12.'
        if self.period_year < 2000:
            errors['period_year'] = 'Informe um ano válido.'
        if errors:
            raise ValidationError(errors)
