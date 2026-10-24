from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from quality.models import (
    AnalyticalSpecification,
    LaboratoryInvestigation,
    QualityAnalysis,
    QualityDocument,
    QualityResult,
    QualitySample,
)


class SingleInstanceQualitySerializerMixin(ModelSerializerContractMixin):
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
            if hasattr(error, 'message_dict'):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error


class AnalyticalSpecificationSerializer(
    SingleInstanceQualitySerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = AnalyticalSpecification
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
        for field_name in ('product', 'stock_lot', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class QualitySampleSerializer(SingleInstanceQualitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = QualitySample
        fields = '__all__'
        read_only_fields = (
            'id',
            'sample_number',
            'status',
            'collected_by',
            'collected_at',
            'received_by',
            'received_at',
            'started_by',
            'started_at',
            'reviewed_by',
            'reviewed_at',
            'approved_by',
            'approved_at',
            'rejected_by',
            'rejected_at',
            'rejection_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'product',
            'stock_lot',
            'specification',
            'source_purchase_receipt',
            'source_production_order',
            'customer_complaint',
            'unit',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class QualityAnalysisSerializer(SingleInstanceQualitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = QualityAnalysis
        fields = '__all__'
        read_only_fields = (
            'id',
            'analysis_number',
            'status',
            'analyst',
            'reviewer',
            'approver',
            'started_at',
            'completed_at',
            'reviewed_at',
            'approved_at',
            'rejected_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('sample', 'specification'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class QualityResultSerializer(SingleInstanceQualitySerializerMixin, serializers.ModelSerializer):
    is_blocking = serializers.BooleanField(read_only=True)

    class Meta:
        model = QualityResult
        fields = '__all__'
        read_only_fields = (
            'id',
            'result_status',
            'is_blocking',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('analysis', 'specification', 'unit', 'recorded_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class LaboratoryInvestigationSerializer(
    SingleInstanceQualitySerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = LaboratoryInvestigation
        fields = '__all__'
        read_only_fields = (
            'id',
            'investigation_number',
            'status',
            'repeat_approved',
            'retest_approved',
            'resampling_approved',
            'opened_by',
            'opened_at',
            'started_at',
            'concluded_by',
            'concluded_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('sample', 'analysis', 'result'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class QualityDocumentSerializer(SingleInstanceQualitySerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = QualityDocument
        fields = '__all__'
        read_only_fields = (
            'id',
            'document_number',
            'status',
            'issued_by',
            'issued_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('sample', 'product', 'stock_lot', 'issued_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
