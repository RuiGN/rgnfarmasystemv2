from django.contrib import admin
from django.db import transaction
from base.admin_mixins import GxpRetentionModelAdmin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin
from production.models import MaterialConsumption, ProductionOrder


class MaterialConsumptionInline(admin.TabularInline):
    def has_change_permission(self, request, obj=None):
        if obj and obj.status in {
            ProductionOrder.Status.CANCELLED,
            ProductionOrder.Status.COMPLETED,
            ProductionOrder.Status.CLOSED,
        }:
            return False
        return super().has_change_permission(request, obj)

    def has_add_permission(self, request, obj=None):
        return self.has_change_permission(request, obj) and super().has_add_permission(request, obj)

    model = MaterialConsumption
    extra = 0
    autocomplete_fields = ('component', 'material', 'unit')
    fields = (
        'component',
        'material',
        'planned_quantity',
        'actual_quantity',
        'loss_quantity',
        'returned_quantity',
        'unit',
        'quality_status',
        'expiry_date',
    )


@admin.register(ProductionOrder)
class ProductionOrderAdmin(AutomaticGeneratedFieldsAdminMixin, GxpRetentionModelAdmin):
    list_display = ('order_number', 'batch_number', 'product', 'status', 'planned_quantity', 'unit')
    list_filter = ('status', 'product__item_type')
    search_fields = ('order_number', 'batch_number', 'product__code', 'product__description')
    autocomplete_fields = (
        'product',
        'formula',
        'route',
        'unit',
    )
    readonly_fields = (
        'status',
        'approved_by',
        'released_by',
        'started_by',
        'completed_by',
        'cancelled_by',
        'cancel_reason',
        'created_at',
        'updated_at',
        'approved_at',
        'released_at',
        'actual_start',
        'actual_end',
        'cancelled_at',
    )
    inlines = (MaterialConsumptionInline,)

    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.method == 'POST' and object_id:
            ProductionOrder.objects.select_for_update().filter(pk=object_id).first()
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(MaterialConsumption)
class MaterialConsumptionAdmin(GxpRetentionModelAdmin):
    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.order.status in {
            ProductionOrder.Status.CANCELLED,
            ProductionOrder.Status.COMPLETED,
            ProductionOrder.Status.CLOSED,
        }:
            return False
        return super().has_change_permission(request, obj)

    @transaction.atomic
    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if request.method == 'POST':
            order_id = request.POST.get('order')
            if object_id:
                order_id = (
                    MaterialConsumption.objects.filter(pk=object_id)
                    .values_list('order_id', flat=True)
                    .first()
                )
            if order_id and str(order_id).isdigit():
                ProductionOrder.objects.select_for_update().filter(pk=order_id).first()
                if object_id:
                    MaterialConsumption.objects.select_for_update().filter(pk=object_id).first()
        return super().changeform_view(request, object_id, form_url, extra_context)

    list_display = (
        'order',
        'material',
        'planned_quantity',
        'actual_quantity',
        'unit',
        'quality_status',
        'expiry_date',
    )
    list_filter = ('quality_status', 'material__item_type')
    search_fields = (
        'order__order_number',
        'order__batch_number',
        'material__code',
        'material__description',
        'lot_number',
    )
    autocomplete_fields = ('order', 'component', 'material', 'unit')
    readonly_fields = ('created_at', 'updated_at')
