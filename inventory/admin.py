from django.contrib import admin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin, GxpRetentionModelAdmin
from inventory.models import StockBalance, StockLot, StockLotGenealogy, StockMovement


@admin.register(StockLot)
class StockLotAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'lot_number',
        'sublot_number',
        'quality_status',
        'supplier',
        'expiry_date',
    )
    list_filter = ('quality_status', 'expiry_date', 'product__item_type')
    search_fields = (
        'product__code',
        'product__description',
        'lot_number',
        'sublot_number',
        'supplier__legal_name',
    )
    autocomplete_fields = (
        'product',
        'supplier',
        'source_purchase_receipt_item',
        'source_production_order',
    )
    readonly_fields = ('quality_status', 'is_expired', 'created_at', 'updated_at')

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        return (*fields, 'product') if obj is not None else fields


@admin.register(StockBalance)
class StockBalanceAdmin(GxpRetentionModelAdmin):
    list_display = (
        'product',
        'lot',
        'warehouse',
        'location',
        'quality_status',
        'quantity',
        'reserved_quantity',
        'available_quantity',
        'unit',
    )
    list_filter = ('quality_status', 'warehouse', 'product__item_type')
    search_fields = (
        'product__code',
        'product__description',
        'lot__lot_number',
        'warehouse__name',
        'location__code',
    )
    autocomplete_fields = ('product', 'lot', 'warehouse', 'location', 'unit')
    readonly_fields = (
        'quality_status',
        'quantity',
        'reserved_quantity',
        'available_quantity',
        'can_issue',
        'created_at',
        'updated_at',
    )

    def get_readonly_fields(self, request, obj=None):
        fields = tuple(super().get_readonly_fields(request, obj))
        if obj is not None:
            fields += StockBalance.IDENTITY_FIELDS
        return fields


@admin.register(StockMovement)
class StockMovementAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    list_display = (
        'movement_number',
        'movement_type',
        'product',
        'lot',
        'quantity',
        'unit',
        'quality_status',
        'movement_date',
    )
    list_filter = ('movement_type', 'quality_status', 'movement_date')
    search_fields = (
        'movement_number',
        'product__code',
        'product__description',
        'lot__lot_number',
        'document_reference',
        'reason',
    )
    autocomplete_fields = (
        'product',
        'lot',
        'unit',
        'from_warehouse',
        'from_location',
        'to_warehouse',
        'to_location',
        'source_purchase_receipt_item',
        'source_production_order',
        'source_material_consumption',
        'related_movement',
        'created_by',
    )
    readonly_fields = ('movement_number', 'created_at', 'updated_at')


@admin.register(StockLotGenealogy)
class StockLotGenealogyAdmin(admin.ModelAdmin):
    list_display = (
        'input_lot',
        'output_lot',
        'relation_type',
        'quantity',
        'unit',
        'production_order',
    )
    list_filter = ('relation_type',)
    search_fields = (
        'input_lot__lot_number',
        'output_lot__lot_number',
        'document_reference',
        'notes',
    )
    autocomplete_fields = ('input_lot', 'output_lot', 'unit', 'production_order')
    readonly_fields = ('created_at', 'updated_at')
