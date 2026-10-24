from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from fiscal.models import (
    FiscalAuditTrail,
    FiscalBookEntry,
    FiscalCompany,
    FiscalDocument,
    FiscalDocumentItem,
    FiscalEmailDelivery,
    FiscalEmissionEvent,
    FiscalMunicipality,
    FiscalNCM,
    FiscalObligation,
    FiscalOperationCode,
    FiscalTax,
    FiscalUnit,
    TaxAssessmentPeriod,
    TaxRule,
    TaxSituation,
)


class SingleInstanceFiscalSerializerMixin(ModelSerializerContractMixin):
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
        instance._state.db = self.instance._state.db
        return instance

    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error


class FiscalCompanySerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalCompany
        fields = (
            'id',
            'legal_name',
            'document',
            'state_registration',
            'municipal_registration',
            'tax_regime',
            'zipcode',
            'street',
            'street_number',
            'complement',
            'neighborhood',
            'state_ref',
            'city_ref',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalMunicipalitySerializer(
    SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = FiscalMunicipality
        fields = (
            'id',
            'ibge_code',
            'name',
            'state_ref',
            'city_ref',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        instance = self._instance_for_clean(attrs)
        self._run_model_clean(instance)
        if not attrs.get('name') and instance.name:
            attrs['name'] = instance.name
        return attrs


class FiscalUnitSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalUnit
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class FiscalNCMSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalNCM
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class FiscalOperationCodeSerializer(
    SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = FiscalOperationCode
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class TaxSituationSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = TaxSituation
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class TaxRuleSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = TaxRule
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('company', 'product', 'partner', 'ncm', 'cfop', 'tax_situation'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalDocumentSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalDocument
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'emission_status',
            'access_key',
            'authorization_protocol',
            'authorization_at',
            'cancel_protocol',
            'cancelled_at',
            'rejection_code',
            'rejection_reason',
            'total_products',
            'total_taxes',
            'retained_taxes',
            'total_amount',
            'reviewed_by',
            'reviewed_at',
            'approved_by',
            'approved_at',
            'posted_by',
            'posted_at',
            'financial_title',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('company', 'partner', 'purchase_order', 'purchase_receipt'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalDocumentItemSerializer(
    SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer
):
    line_subtotal = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = FiscalDocumentItem
        fields = (
            'id',
            'document',
            'line_number',
            'product',
            'fiscal_unit',
            'ncm',
            'cfop',
            'tax_situation',
            'quantity',
            'unit_price',
            'discount_amount',
            'freight_amount',
            'insurance_amount',
            'other_amount',
            'line_subtotal',
            'line_total',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'line_subtotal',
            'line_total',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('document', 'product', 'fiscal_unit', 'ncm', 'cfop', 'tax_situation'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalTaxSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalTax
        fields = '__all__'
        read_only_fields = ('id', 'tax_amount', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('document', 'item', 'tax_rule'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class TaxAssessmentPeriodSerializer(
    SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = TaxAssessmentPeriod
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'debit_amount',
            'credit_amount',
            'retained_amount',
            'balance_amount',
            'calculated_at',
            'closed_by',
            'closed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalBookEntrySerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalBookEntry
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalObligationSerializer(SingleInstanceFiscalSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = FiscalObligation
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'submitted_by',
            'submitted_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FiscalAuditTrailSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalAuditTrail
        fields = '__all__'
        read_only_fields = tuple(field.name for field in FiscalAuditTrail._meta.fields)


class FiscalEmissionEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalEmissionEvent
        fields = '__all__'
        read_only_fields = tuple(field.name for field in FiscalEmissionEvent._meta.fields)


class FiscalEmailDeliverySerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalEmailDelivery
        fields = '__all__'
        read_only_fields = tuple(field.name for field in FiscalEmailDelivery._meta.fields)
