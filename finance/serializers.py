from typing import TYPE_CHECKING, Protocol, cast

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

if TYPE_CHECKING:
    from django.db.models import Model

from finance.models import (
    CashFlowEntry,
    ChartOfAccount,
    FinancialAccount,
    FinancialCategory,
    FinancialPeriodClosing,
    FinancialSettlement,
    FinancialTitle,
)


class SingleInstanceFinanceSerializerMixin(ModelSerializerContractMixin):
    def _instance_for_clean(self, attrs):
        model = self.Meta.model
        if self.instance is None:
            return model(**attrs)
        values = {}
        for field in model._meta.concrete_fields:
            if field.primary_key:
                continue
            values[field.name] = attrs.get(field.name, getattr(self.instance, field.name))
        instance = model(**values)
        instance.pk = self.instance.pk
        instance._state.adding = False
        return instance

    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class ChartOfAccountSerializer(SingleInstanceFinanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ChartOfAccount
        fields = (
            'id',
            'code',
            'name',
            'account_type',
            'parent',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FinancialCategorySerializer(
    SingleInstanceFinanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = FinancialCategory
        fields = (
            'id',
            'code',
            'name',
            'category_type',
            'chart_account',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class _ModelSerializerCreate(Protocol):
    def create(self, validated_data: dict[str, object]) -> 'Model': ...


class LockedFinanceSerializerMixin(SingleInstanceFinanceSerializerMixin):
    def create(self, validated_data):
        try:
            return cast(_ModelSerializerCreate, super()).create(validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = self.Meta.model.objects.select_for_update().get(pk=instance.pk)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        try:
            instance.save(update_fields=set(validated_data) | {'updated_at'})
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error
        return instance


class FinancialAccountSerializer(LockedFinanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FinancialAccount
        fields = (
            'id',
            'code',
            'name',
            'account_type',
            'bank_name',
            'agency_number',
            'account_number',
            'opening_balance',
            'current_balance',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'current_balance', 'created_at', 'updated_at')


class FinancialTitleSerializer(LockedFinanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FinancialTitle
        fields = (
            'id',
            'title_number',
            'title_type',
            'source_type',
            'partner',
            'category',
            'financial_account',
            'purchase_order',
            'fiscal_document_number',
            'contract_reference',
            'sale_reference',
            'status',
            'issue_date',
            'due_date',
            'original_amount',
            'open_amount',
            'paid_amount',
            'approved_by',
            'approved_at',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'open_amount',
            'paid_amount',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'partner',
            'category',
            'financial_account',
            'purchase_order',
        ):
            pass
        if self.instance is None and 'open_amount' not in attrs and 'original_amount' in attrs:
            attrs['open_amount'] = attrs['original_amount']
        candidate = self._instance_for_clean(attrs)
        candidate.open_amount = candidate.original_amount - candidate.paid_amount
        self._run_model_clean(candidate)
        return attrs


class FinancialSettlementSerializer(
    SingleInstanceFinanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = FinancialSettlement
        fields = (
            'id',
            'title',
            'financial_account',
            'settlement_date',
            'method',
            'amount',
            'interest_amount',
            'penalty_amount',
            'discount_amount',
            'net_amount',
            'status',
            'reconciled_by',
            'reconciled_at',
            'reversed_by',
            'reversed_at',
            'reversal_reason',
            'reference',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'net_amount',
            'status',
            'reconciled_by',
            'reconciled_at',
            'reversed_by',
            'reversed_at',
            'reversal_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        candidate = self._instance_for_clean(attrs)
        if self.instance is not None:
            try:
                candidate.validate_immutable_fields(self.instance, attrs)
            except DjangoValidationError as error:
                raise serializers.ValidationError(error.message_dict) from error
        self._run_model_clean(candidate)
        return attrs

    def create(self, validated_data):
        title = validated_data['title']
        try:
            return title.register_settlement(
                financial_account=validated_data['financial_account'],
                amount=validated_data['amount'],
                settlement_date=validated_data['settlement_date'],
                method=validated_data['method'],
                interest_amount=validated_data.get('interest_amount', 0),
                penalty_amount=validated_data.get('penalty_amount', 0),
                discount_amount=validated_data.get('discount_amount', 0),
                reference=validated_data.get('reference', ''),
                notes=validated_data.get('notes', ''),
            )
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    @transaction.atomic
    def update(self, instance, validated_data):
        instance = FinancialSettlement.objects.select_for_update().get(pk=instance.pk)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        try:
            instance.save(update_fields=set(validated_data) | {'updated_at'})
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error
        return instance


class CashFlowEntrySerializer(SingleInstanceFinanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CashFlowEntry
        fields = (
            'id',
            'flow_type',
            'direction',
            'title',
            'settlement',
            'financial_account',
            'cash_date',
            'amount',
            'status',
            'description',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('title', 'settlement', 'financial_account'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FinancialPeriodClosingSerializer(
    SingleInstanceFinanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = FinancialPeriodClosing
        fields = (
            'id',
            'period_year',
            'period_month',
            'status',
            'validation_notes',
            'closed_by',
            'closed_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'closed_by',
            'closed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
