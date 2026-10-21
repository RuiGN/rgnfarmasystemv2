from django.contrib import admin
from formulations.admin_writers import FormulaWriterAdminMixin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin
from masters.models import (
    BusinessPartner,
    MasterCategory,
    Product,
    Site,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
)


@admin.register(UnitOfMeasure)
class UnitOfMeasureAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'symbol', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'symbol')


@admin.register(MasterCategory)
class MasterCategoryAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'parent', 'is_active')
    list_filter = ('kind', 'is_active')
    search_fields = ('code', 'name')
    autocomplete_fields = ('parent',)


@admin.register(Product)
class ProductAdmin(FormulaWriterAdminMixin, AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'description', 'item_type', 'status', 'unit')
    list_filter = ('item_type', 'status', 'requires_quality_release', 'requires_approved_supplier')
    search_fields = ('code', 'description', 'fiscal_ncm')
    autocomplete_fields = (
        'unit',
        'category',
        'product_line',
        'cosmetic_form',
        'application_area',
    )


@admin.register(BusinessPartner)
class BusinessPartnerAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'code',
        'legal_name',
        'partner_type',
        'city_ref',
        'state_ref',
        'qualification_status',
        'qualification_valid_until',
        'is_blocked',
    )
    list_filter = (
        'partner_type',
        'qualification_status',
        'state_ref',
        'is_active',
        'is_blocked',
    )
    search_fields = (
        'code',
        'legal_name',
        'trade_name',
        'document',
        'city_ref__name',
        'state_ref__name',
        'state_ref__name',
    )
    autocomplete_fields = ('city_ref', 'state_ref')


@admin.register(Site)
class SiteAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'site_type', 'city_ref', 'state_ref', 'is_active')
    list_filter = ('site_type', 'state_ref', 'is_active')
    search_fields = ('code', 'name', 'city_ref__name', 'state_ref__name')
    autocomplete_fields = ('city_ref', 'state_ref')


@admin.register(Warehouse)
class WarehouseAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'warehouse_type', 'site', 'is_active')
    list_filter = ('warehouse_type', 'is_active')
    search_fields = ('code', 'name', 'site__name')
    autocomplete_fields = ('site',)


@admin.register(StorageLocation)
class StorageLocationAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'warehouse', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('code', 'name', 'warehouse__name')
    autocomplete_fields = ('warehouse',)
