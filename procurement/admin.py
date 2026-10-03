from django.contrib import admin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    QuotationRequest,
    SupplierQualificationEvent,
    SupplierQuotation,
)


class PurchaseRequisitionItemInline(admin.TabularInline):
    model = PurchaseRequisitionItem
    extra = 0
    autocomplete_fields = ('product', 'unit', 'mrp_suggestion')
    fields = ('product', 'quantity', 'unit', 'needed_by', 'mrp_suggestion')


@admin.register(PurchaseRequisition)
class PurchaseRequisitionAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('requisition_number', 'source', 'status', 'requested_by', 'approved_at')
    list_filter = ('source', 'status')
    search_fields = ('requisition_number', 'justification')
    autocomplete_fields = ('requested_by', 'approved_by', 'rejected_by')
    readonly_fields = ('submitted_at', 'approved_at', 'rejected_at', 'created_at', 'updated_at')
    inlines = (PurchaseRequisitionItemInline,)


@admin.register(PurchaseRequisitionItem)
class PurchaseRequisitionItemAdmin(admin.ModelAdmin):
    list_display = ('requisition', 'product', 'quantity', 'unit', 'needed_by')
    list_filter = ('needed_by', 'product__item_type')
    search_fields = ('requisition__requisition_number', 'product__code', 'product__description')
    autocomplete_fields = ('requisition', 'product', 'unit', 'mrp_suggestion')
    readonly_fields = ('created_at', 'updated_at')


class SupplierQuotationInline(admin.TabularInline):
    model = SupplierQuotation
    extra = 0
    autocomplete_fields = ('supplier',)
    fields = (
        'supplier',
        'quoted_quantity',
        'unit_price',
        'lead_time_days',
        'valid_until',
        'supplier_performance_score',
    )


@admin.register(QuotationRequest)
class QuotationRequestAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('rfq_number', 'requisition', 'status', 'due_date', 'approved_at')
    list_filter = ('status', 'due_date')
    search_fields = ('rfq_number', 'requisition__requisition_number', 'terms')
    autocomplete_fields = ('requisition', 'approved_by')
    readonly_fields = ('approved_at', 'created_at', 'updated_at')
    inlines = (SupplierQuotationInline,)


@admin.register(SupplierQuotation)
class SupplierQuotationAdmin(admin.ModelAdmin):
    list_display = (
        'rfq',
        'supplier',
        'status',
        'quoted_quantity',
        'unit_price',
        'total_amount',
        'lead_time_days',
        'valid_until',
    )
    list_filter = ('status', 'valid_until')
    search_fields = ('rfq__rfq_number', 'supplier__code', 'supplier__legal_name')
    autocomplete_fields = ('rfq', 'supplier')
    readonly_fields = ('total_amount', 'is_supplier_valid', 'created_at', 'updated_at')


@admin.register(SupplierQualificationEvent)
class SupplierQualificationEventAdmin(admin.ModelAdmin):
    list_display = (
        'supplier',
        'event_type',
        'event_date',
        'valid_until',
        'event_state_ref',
        'event_city_ref',
        'blocks_purchases',
        'is_active_block',
    )
    list_filter = (
        'event_type',
        'blocks_purchases',
        'valid_until',
        'site',
        'event_state_ref',
        'event_city_ref',
    )
    search_fields = (
        'supplier__code',
        'supplier__legal_name',
        'description',
        'severity',
        'event_city_ref__name',
        'event_state_ref__name',
    )
    autocomplete_fields = ('supplier', 'site', 'event_state_ref', 'event_city_ref')
    readonly_fields = ('is_active_block', 'created_at', 'updated_at')


class PurchaseOrderItemInline(admin.TabularInline):
    model = PurchaseOrderItem
    extra = 0
    autocomplete_fields = ('requisition_item', 'product', 'unit')
    fields = ('product', 'quantity', 'unit', 'unit_price', 'tax_amount', 'expected_delivery_date')


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'order_number',
        'supplier',
        'status',
        'issue_date',
        'expected_delivery_date',
        'delivery_state_ref',
        'delivery_city_ref',
        'total_amount',
    )
    list_filter = (
        'status',
        'issue_date',
        'expected_delivery_date',
        'delivery_site',
        'delivery_state_ref',
        'delivery_city_ref',
    )
    search_fields = (
        'order_number',
        'supplier__code',
        'supplier__legal_name',
        'notes',
        'delivery_city_ref__name',
        'delivery_state_ref__name',
    )
    autocomplete_fields = (
        'supplier',
        'requisition',
        'source_quotation',
        'delivery_site',
        'delivery_state_ref',
        'delivery_city_ref',
        'approved_by',
    )
    readonly_fields = ('total_amount', 'approved_at', 'created_at', 'updated_at')
    inlines = (PurchaseOrderItemInline,)


@admin.register(PurchaseOrderItem)
class PurchaseOrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'product',
        'quantity',
        'unit',
        'unit_price',
        'line_total',
        'expected_delivery_date',
    )
    list_filter = ('expected_delivery_date', 'product__item_type')
    search_fields = ('order__order_number', 'product__code', 'product__description')
    autocomplete_fields = ('order', 'requisition_item', 'product', 'unit')
    readonly_fields = ('line_subtotal', 'line_total', 'created_at', 'updated_at')


class PurchaseReceiptItemInline(admin.TabularInline):
    model = PurchaseReceiptItem
    extra = 0
    autocomplete_fields = ('order_item', 'product', 'unit')
    fields = (
        'order_item',
        'product',
        'received_quantity',
        'accepted_quantity',
        'rejected_quantity',
        'unit',
        'lot_number',
        'expiry_date',
    )


@admin.register(PurchaseReceipt)
class PurchaseReceiptAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'receipt_number',
        'order',
        'status',
        'quality_status',
        'stock_entry_status',
        'fiscal_document_number',
    )
    list_filter = ('status', 'quality_status', 'stock_entry_status')
    search_fields = ('receipt_number', 'order__order_number', 'fiscal_document_number')
    autocomplete_fields = ('order',)
    readonly_fields = (
        'created_at',
        'updated_at',
        'status',
        'quality_status',
        'stock_entry_status',
        'received_by',
        'fiscal_received_at',
        'physical_received_at',
    )
    inlines = (PurchaseReceiptItemInline,)


@admin.register(PurchaseReceiptItem)
class PurchaseReceiptItemAdmin(admin.ModelAdmin):
    list_display = (
        'receipt',
        'product',
        'received_quantity',
        'accepted_quantity',
        'rejected_quantity',
        'unit',
        'lot_number',
        'expiry_date',
    )
    list_filter = ('expiry_date', 'product__item_type')
    search_fields = (
        'receipt__receipt_number',
        'product__code',
        'product__description',
        'lot_number',
    )
    autocomplete_fields = ('receipt', 'order_item', 'product', 'unit')
    readonly_fields = ('created_at', 'updated_at')
