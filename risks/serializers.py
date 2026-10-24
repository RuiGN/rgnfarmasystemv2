from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from risks.models import (
    RiskAlert,
    RiskAssessment,
    RiskControl,
    RiskLink,
    RiskMitigationAction,
    RiskRecord,
    RiskReview,
)


class SingleInstanceRiskSerializerMixin(ModelSerializerContractMixin):
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


class RiskRecordSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskRecord
        fields = '__all__'
        read_only_fields = (
            'id',
            'risk_number',
            'status',
            'identified_by',
            'identified_at',
            'treatment_started_by',
            'treatment_started_at',
            'monitoring_started_by',
            'monitoring_started_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'initial_score',
            'initial_level',
            'residual_score',
            'residual_level',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'owner',
            'identified_by',
            'treatment_started_by',
            'monitoring_started_by',
            'closed_by',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskAssessmentSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskAssessment
        fields = '__all__'
        read_only_fields = (
            'id',
            'score',
            'risk_level',
            'assessed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskControlSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskControl
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskMitigationActionSerializer(
    SingleInstanceRiskSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RiskMitigationAction
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'completion_notes',
            'evidence_reference',
            'content_hash',
            'completed_by',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('responsible', 'completed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskLinkSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskLink
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in (
            'risk',
            'product',
            'document',
            'deviation_event',
            'capa',
            'change_control',
            'audit',
            'supplier',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskReviewSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskReview
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'result',
            'next_review_date',
            'completed_by',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('reviewer', 'completed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RiskAlertSerializer(SingleInstanceRiskSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RiskAlert
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'acknowledged_by',
            'acknowledged_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('risk', 'action'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
