from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from base.normalized_locations import validate_normalized_location


class UnitOfMeasure(SingleInstanceModel):
    code = models.CharField('código', max_length=20)
    name = models.CharField('nome', max_length=120)
    symbol = models.CharField('símbolo', max_length=20)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_unit_code'),
        ]
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'unidade de medida'
        verbose_name_plural = 'unidades de medida'

    def __str__(self):
        return f'{self.code} - {self.name}'


class MasterCategory(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'CAT'

    class Kind(models.TextChoices):
        FAMILY = 'family', 'Família'
        GROUP = 'group', 'Grupo'
        CATEGORY = 'category', 'Categoria'
        PRODUCT_LINE = 'product_line', 'Linha de produto'
        COSMETIC_FORM = 'cosmetic_form', 'Forma cosmética'
        PRESENTATION = 'presentation', 'Apresentação'
        CONCENTRATION = 'concentration', 'Concentração'
        APPLICATION_AREA = 'application_area', 'Área de aplicação'

    code = models.CharField('código', max_length=40, blank=True)
    name = models.CharField('nome', max_length=160)
    kind = models.CharField('tipo', max_length=32, choices=Kind.choices)
    parent = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='children',
        null=True,
        blank=True,
        verbose_name='categoria superior',
    )
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['kind', 'name']
        constraints = [
            models.UniqueConstraint(fields=['kind', 'code'], name='unique_category_kind_code'),
        ]
        indexes = [
            models.Index(fields=['kind', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'categoria mestre'
        verbose_name_plural = 'categorias mestres'

    def clean(self):
        super().clean()
        if False:
            raise ValidationError({'parent': 'A categoria superior é incompatível com o registro.'})

    def __str__(self):
        return f'{self.name} ({self.get_kind_display()})'


class Product(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'PRD'

    class ItemType(models.TextChoices):
        FINISHED_PRODUCT = 'finished_product', 'Produto acabado'
        SEMIFINISHED = 'semifinished', 'Semiacabado'
        INTERMEDIATE = 'intermediate', 'Intermediário'
        RAW_MATERIAL = 'raw_material', 'Matéria-prima'
        EXCIPIENT = 'excipient', 'Excipiente'
        PACKAGING = 'packaging', 'Embalagem'
        REAGENT = 'reagent', 'Reagente'
        STANDARD = 'standard', 'Padrão'
        PROMOTIONAL = 'promotional', 'Material promocional'
        SERVICE = 'service', 'Serviço'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        APPROVED = 'approved', 'Aprovado'
        BLOCKED = 'blocked', 'Bloqueado'
        OBSOLETE = 'obsolete', 'Obsoleto'

    code = models.CharField('código', max_length=64, blank=True)
    description = models.CharField('descrição', max_length=255)
    item_type = models.CharField('tipo de item', max_length=32, choices=ItemType.choices)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='products',
        verbose_name='unidade',
    )
    category = models.ForeignKey(
        MasterCategory,
        on_delete=models.PROTECT,
        related_name='products',
        null=True,
        blank=True,
        verbose_name='categoria',
    )
    product_line = models.ForeignKey(
        MasterCategory,
        on_delete=models.PROTECT,
        related_name='product_line_products',
        null=True,
        blank=True,
        verbose_name='linha de produto',
    )
    cosmetic_form = models.ForeignKey(
        MasterCategory,
        on_delete=models.PROTECT,
        related_name='form_products',
        null=True,
        blank=True,
        verbose_name='forma cosmética',
    )
    application_area = models.ForeignKey(
        MasterCategory,
        on_delete=models.PROTECT,
        related_name='application_area_products',
        null=True,
        blank=True,
        verbose_name='área de aplicação',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    storage_condition = models.CharField('condição de armazenamento', max_length=255, blank=True)
    shelf_life_days = models.PositiveIntegerField('vida útil em dias', null=True, blank=True)
    requires_quality_release = models.BooleanField('exige liberação da qualidade', default=True)
    requires_approved_supplier = models.BooleanField('exige fornecedor aprovado', default=False)
    fiscal_ncm = models.CharField('NCM', max_length=16, blank=True)
    fiscal_cest = models.CharField('CEST', max_length=16, blank=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_product_code'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['item_type']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'produto/material'
        verbose_name_plural = 'produtos/materiais'

    @property
    def is_operationally_available(self):
        if self.status != self.Status.APPROVED:
            return False
        if not self.unit_id or not self.unit.is_active:
            return False
        if self.category and not self.category.is_active:
            return False
        return True

    def clean(self):
        super().clean()
        errors = {}
        self._validate_match(errors, 'unit', self.unit if self.unit_id else None)
        self._validate_category(errors, 'category', self.category, MasterCategory.Kind.CATEGORY)
        self._validate_category(
            errors,
            'product_line',
            self.product_line,
            MasterCategory.Kind.PRODUCT_LINE,
        )
        self._validate_category(
            errors,
            'cosmetic_form',
            self.cosmetic_form,
            MasterCategory.Kind.COSMETIC_FORM,
        )
        self._validate_category(
            errors,
            'application_area',
            self.application_area,
            MasterCategory.Kind.APPLICATION_AREA,
        )
        if errors:
            raise ValidationError(errors)

    def _validate_match(self, errors, field, related):
        return None

    def _validate_category(self, errors, field, category, expected_kind):
        self._validate_match(errors, field, category)
        if category and category.kind != expected_kind:
            errors[field] = f'A categoria deve ser do tipo {expected_kind}.'

    def __str__(self):
        return f'{self.code} - {self.description}'


class BusinessPartner(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'BP'

    class PartnerType(models.TextChoices):
        SUPPLIER = 'supplier', 'Fornecedor'
        MANUFACTURER = 'manufacturer', 'Fabricante'
        DISTRIBUTOR = 'distributor', 'Distribuidor'
        CARRIER = 'carrier', 'Transportadora'
        CUSTOMER = 'customer', 'Cliente'
        PARTNER = 'partner', 'Parceiro'
        OUTSOURCED_LAB = 'outsourced_lab', 'Laboratório terceirizado'
        REGULATORY_AUTHORITY = 'regulatory_authority', 'Autoridade regulatória'

    class QualificationStatus(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        QUALIFIED = 'qualified', 'Qualificado'
        NOT_QUALIFIED = 'not_qualified', 'Não qualificado'
        EXPIRED = 'expired', 'Vencido'
        BLOCKED = 'blocked', 'Bloqueado'

    code = models.CharField('código', max_length=64, blank=True)
    legal_name = models.CharField('razão social/nome', max_length=255)
    trade_name = models.CharField('nome fantasia', max_length=255, blank=True)
    document = models.CharField('documento fiscal/regulatório', max_length=40, blank=True)
    partner_type = models.CharField('tipo', max_length=32, choices=PartnerType.choices)
    qualification_status = models.CharField(
        'status de qualificação',
        max_length=24,
        choices=QualificationStatus.choices,
        default=QualificationStatus.DRAFT,
    )
    qualification_valid_until = models.DateField('qualificação válida até', null=True, blank=True)
    email = models.EmailField('email', blank=True)
    phone = models.CharField('telefone', max_length=40, blank=True)
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
    is_blocked = models.BooleanField('bloqueado', default=False)

    class Meta:
        ordering = ['legal_name']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_partner_code'),
        ]
        indexes = [
            models.Index(fields=['partner_type']),
            models.Index(fields=['qualification_status']),
            models.Index(fields=['code']),
            models.Index(fields=['document']),
        ]
        verbose_name = 'parceiro de negócio'
        verbose_name_plural = 'parceiros de negócio'

    @property
    def is_qualification_valid(self):
        if self.qualification_status != self.QualificationStatus.QUALIFIED:
            return False
        if self.qualification_valid_until and self.qualification_valid_until < timezone.localdate():
            return False
        return True

    @property
    def is_operationally_available(self):
        return self.is_active and not self.is_blocked and self.is_qualification_valid

    def clean(self):
        super().clean()
        validate_normalized_location(self)

    def __str__(self):
        return f'{self.code} - {self.legal_name}'


class Site(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'ST'

    class SiteType(models.TextChoices):
        PLANT = 'plant', 'Planta fabril'
        DISTRIBUTION = 'distribution', 'Distribuição'
        LAB = 'lab', 'Laboratório'
        ADMIN = 'admin', 'Administrativo'

    code = models.CharField('código', max_length=40, blank=True)
    name = models.CharField('nome', max_length=160)
    site_type = models.CharField(
        'tipo', max_length=24, choices=SiteType.choices, default=SiteType.PLANT
    )
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
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_site_code'),
        ]
        indexes = [
            models.Index(fields=['site_type', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'planta/unidade'
        verbose_name_plural = 'plantas/unidades'

    def clean(self):
        super().clean()
        validate_normalized_location(self)

    def __str__(self):
        return f'{self.code} - {self.name}'


class Warehouse(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'WH'

    class WarehouseType(models.TextChoices):
        RAW_MATERIAL = 'raw_material', 'Matéria-prima'
        PACKAGING = 'packaging', 'Embalagem'
        FINISHED_PRODUCT = 'finished_product', 'Produto acabado'
        QUALITY = 'quality', 'Qualidade'
        REJECTED = 'rejected', 'Reprovado'
        GENERAL = 'general', 'Geral'

    site = models.ForeignKey(
        Site, on_delete=models.PROTECT, related_name='warehouses', verbose_name='planta'
    )
    code = models.CharField('código', max_length=40, blank=True)
    name = models.CharField('nome', max_length=160)
    warehouse_type = models.CharField('tipo', max_length=32, choices=WarehouseType.choices)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['site__name', 'name']
        constraints = [
            models.UniqueConstraint(fields=['site', 'code'], name='unique_site_warehouse_code'),
        ]
        indexes = [
            models.Index(fields=['warehouse_type', 'is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'almoxarifado'
        verbose_name_plural = 'almoxarifados'

    def clean(self):
        super().clean()
        if False:
            raise ValidationError({'site': 'A planta relacionada é incompatível com o registro.'})

    def __str__(self):
        return f'{self.code} - {self.name}'


class StorageLocation(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'SL'
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='locations',
        verbose_name='almoxarifado',
    )
    code = models.CharField('código', max_length=40, blank=True)
    name = models.CharField('nome', max_length=160)
    is_active = models.BooleanField('ativo', default=True)

    class Meta:
        ordering = ['warehouse__name', 'code']
        constraints = [
            models.UniqueConstraint(
                fields=['warehouse', 'code'], name='unique_warehouse_location_code'
            ),
        ]
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'localização de estoque'
        verbose_name_plural = 'localizações de estoque'

    def clean(self):
        super().clean()
        if False:
            raise ValidationError(
                {'warehouse': 'O almoxarifado relacionado é incompatível com o registro.'}
            )

    def __str__(self):
        return f'{self.warehouse.code}/{self.code} - {self.name}'
