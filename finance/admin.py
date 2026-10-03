from typing import TYPE_CHECKING, TypeAlias

from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError
from django.db import router, transaction
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin
from finance.models import (
    CashFlowEntry,
    ChartOfAccount,
    FinancialAccount,
    FinancialCategory,
    FinancialPeriodClosing,
    FinancialSettlement,
    FinancialTitle,
)


if TYPE_CHECKING:
    _FinanceAdminBase: TypeAlias = admin.ModelAdmin
else:
    _FinanceAdminBase = object


class FinanceDomainErrorAdminMixin(_FinanceAdminBase):
    """Roll back rejected saves before rendering errors on the bound admin form."""

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)
        error = getattr(request, '_finance_domain_error', None)
        if error is None:
            return form_class

        domain_error = error

        class RejectedFinanceFormMixin(forms.ModelForm):
            def clean(self):
                data = super().clean()
                errors = (
                    domain_error.message_dict
                    if hasattr(domain_error, 'message_dict')
                    else {'__all__': domain_error.messages}
                )
                for field, messages in errors.items():
                    self.add_error(field if field in self.fields else None, messages)
                return data

        # Keep the generated admin form ahead of ModelForm in the runtime MRO.
        return type('RejectedFinanceForm', (RejectedFinanceFormMixin, form_class), {})

    def _changeform_view(self, request, object_id, form_url, extra_context):
        try:
            with transaction.atomic(using=router.db_for_write(self.model)):
                return super()._changeform_view(request, object_id, form_url, extra_context)
        except ValidationError as error:
            # Django's admin saves only after is_valid(). Rebuild the same bound
            # form with errors so neither save_model nor save_related runs again.
            request._finance_domain_error = error
            return super()._changeform_view(request, object_id, form_url, extra_context)


class FinanceDomainForm(forms.ModelForm):
    def _update_errors(self, errors):
        if hasattr(errors, 'error_dict'):
            mapped = {}
            for field, messages in errors.error_dict.items():
                target = field if field in self.fields else '__all__'
                mapped.setdefault(target, []).extend(messages)
            errors = ValidationError(mapped)
        super()._update_errors(errors)


class FinancialTitleForm(FinanceDomainForm):
    class Meta:
        model = FinancialTitle
        fields = '__all__'

    def clean(self):
        data = super().clean()
        if data.get('original_amount') is not None:
            self.instance.open_amount = data['original_amount'] - self.instance.paid_amount
        return data


class FinancialSettlementForm(FinanceDomainForm):
    class Meta:
        model = FinancialSettlement
        fields = '__all__'

    def clean(self):
        data = super().clean()
        if self.instance._state.adding:
            title = data.get('title')
            if title is not None and title.status not in {
                FinancialTitle.Status.APPROVED,
                FinancialTitle.Status.PARTIALLY_SETTLED,
            }:
                self.add_error('title', 'A baixa exige título aprovado.')
            amount_fields = ('amount', 'interest_amount', 'penalty_amount', 'discount_amount')
            if all(data.get(field) is not None for field in amount_fields):
                self.instance.net_amount = (
                    data['amount']
                    + data['interest_amount']
                    + data['penalty_amount']
                    - data['discount_amount']
                )
        return data


@admin.register(ChartOfAccount)
class ChartOfAccountAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'account_type', 'parent', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('code', 'name')
    autocomplete_fields = ('parent',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FinancialCategory)
class FinancialCategoryAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'name', 'category_type', 'chart_account', 'is_active')
    list_filter = ('category_type', 'is_active')
    search_fields = ('code', 'name', 'chart_account__code', 'chart_account__name')
    autocomplete_fields = ('chart_account',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FinancialAccount)
class FinancialAccountAdmin(
    FinanceDomainErrorAdminMixin, AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin
):
    list_display = ('code', 'name', 'account_type', 'bank_name', 'current_balance', 'is_active')
    list_filter = ('account_type', 'is_active')
    search_fields = ('code', 'name', 'bank_name', 'agency_number', 'account_number')
    autocomplete_fields = ()
    readonly_fields = ('current_balance', 'created_at', 'updated_at')


@admin.register(FinancialTitle)
class FinancialTitleAdmin(
    FinanceDomainErrorAdminMixin, AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin
):
    form = FinancialTitleForm

    def save_model(self, request, obj, form, change):
        if change and form is not None:
            obj.save(update_fields=set(form.changed_data) | {'updated_at'})
        else:
            obj.save()

    list_display = (
        'title_number',
        'title_type',
        'source_type',
        'partner',
        'due_date',
        'original_amount',
        'open_amount',
        'status',
    )
    list_filter = ('title_type', 'source_type', 'status', 'due_date')
    search_fields = (
        'title_number',
        'partner__legal_name',
        'fiscal_document_number',
        'contract_reference',
        'sale_reference',
    )
    autocomplete_fields = (
        'partner',
        'category',
        'financial_account',
        'purchase_order',
        'approved_by',
    )
    readonly_fields = (
        'status',
        'open_amount',
        'paid_amount',
        'approved_by',
        'approved_at',
        'created_at',
        'updated_at',
    )


@admin.register(FinancialSettlement)
class FinancialSettlementAdmin(FinanceDomainErrorAdminMixin, admin.ModelAdmin):
    form = FinancialSettlementForm
    list_display = (
        'title',
        'financial_account',
        'settlement_date',
        'method',
        'amount',
        'net_amount',
        'status',
    )

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return tuple(
                field.name
                for field in self.model._meta.concrete_fields
                if not field.primary_key and field.name != 'notes'
            )
        return (*self.readonly_fields, 'status', 'reversal_reason')

    def has_delete_permission(self, request, obj=None):
        return False

    list_filter = ('method', 'status', 'settlement_date')
    search_fields = ('title__title_number', 'reference', 'notes')
    autocomplete_fields = ('title', 'financial_account', 'reconciled_by', 'reversed_by')
    readonly_fields = (
        'net_amount',
        'reconciled_by',
        'reconciled_at',
        'reversed_by',
        'reversed_at',
        'created_at',
        'updated_at',
    )


@admin.register(CashFlowEntry)
class CashFlowEntryAdmin(admin.ModelAdmin):
    list_display = (
        'cash_date',
        'flow_type',
        'direction',
        'title',
        'financial_account',
        'amount',
        'status',
    )
    list_filter = ('flow_type', 'direction', 'status', 'cash_date')
    search_fields = ('title__title_number', 'description')
    autocomplete_fields = ('title', 'settlement', 'financial_account')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(FinancialPeriodClosing)
class FinancialPeriodClosingAdmin(admin.ModelAdmin):
    list_display = ('period_year', 'period_month', 'status', 'closed_by', 'closed_at')
    list_filter = ('status', 'period_year', 'period_month')
    search_fields = ('validation_notes',)
    autocomplete_fields = ('closed_by',)
    readonly_fields = ('closed_by', 'closed_at', 'created_at', 'updated_at')
