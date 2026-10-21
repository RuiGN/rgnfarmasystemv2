from django.contrib import admin
from formulations.admin_writers import FormulaWriterAdminMixin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin
from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula, RouteStep


class FormulaComponentInline(admin.TabularInline):
    model = FormulaComponent
    extra = 0
    autocomplete_fields = ('material', 'unit')
    fields = (
        'line_number',
        'material',
        'role',
        'quantity',
        'unit',
        'expected_loss_percent',
        'is_active',
    )


@admin.register(MasterFormula)
class MasterFormulaAdmin(
    FormulaWriterAdminMixin, AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin
):
    list_display = ('code', 'version', 'product', 'status', 'effective_from', 'effective_to')
    list_filter = ('status', 'product__item_type')
    search_fields = ('code', 'product__code', 'product__description')
    autocomplete_fields = ('product', 'batch_unit', 'copied_from', 'approved_by')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (FormulaComponentInline,)


@admin.register(FormulaComponent)
class FormulaComponentAdmin(FormulaWriterAdminMixin, admin.ModelAdmin):
    list_display = ('formula', 'line_number', 'material', 'role', 'quantity', 'unit', 'is_active')
    list_filter = ('role', 'is_active')
    search_fields = ('formula__code', 'material__code', 'material__description')
    autocomplete_fields = ('formula', 'material', 'unit')
    readonly_fields = ('created_at', 'updated_at')


class RouteStepInline(admin.TabularInline):
    model = RouteStep
    extra = 0
    autocomplete_fields = ()
    fields = (
        'sequence',
        'operation',
        'work_center',
        'resource',
        'standard_time_minutes',
    )


@admin.register(ManufacturingRoute)
class ManufacturingRouteAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'code',
        'version',
        'product',
        'formula',
        'status',
        'effective_from',
        'effective_to',
    )
    list_filter = ('status', 'product__item_type')
    search_fields = ('code', 'product__code', 'product__description', 'formula__code')
    autocomplete_fields = ('product', 'formula')
    readonly_fields = ('created_at', 'updated_at')
    inlines = (RouteStepInline,)


@admin.register(RouteStep)
class RouteStepAdmin(admin.ModelAdmin):
    list_display = (
        'route',
        'sequence',
        'operation',
        'work_center',
        'standard_time_minutes',
    )
    list_filter = ('work_center',)
    search_fields = ('route__code', 'operation', 'work_center', 'resource')
    autocomplete_fields = ('route',)
    readonly_fields = ('created_at', 'updated_at')
