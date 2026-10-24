from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from compliance.models import (
    ComplianceChecklistItem,
    CriticalActionExecution,
    RecordStatusHistory,
    TransversalRequirementPolicy,
)


class SingleInstanceComplianceSerializerMixin:
    def _instance_for_clean(self, attrs):
        model = self.Meta.model  # type: ignore[attr-defined]
        if self.instance is None:  # type: ignore[attr-defined]
            return model(**attrs)
        values = {}
        for field in model._meta.concrete_fields:
            if field.primary_key:
                continue
            values[field.name] = attrs.get(
                field.name,
                getattr(self.instance, field.name),  # type: ignore[attr-defined]
            )
        instance = model(**values)
        instance.pk = self.instance.pk  # type: ignore[attr-defined]
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


class TransversalRequirementPolicySerializer(
    SingleInstanceComplianceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = TransversalRequirementPolicy
        fields = '__all__'
        read_only_fields = ('id', 'owner', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RecordStatusHistorySerializer(
    SingleInstanceComplianceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RecordStatusHistory
        fields = '__all__'
        read_only_fields = ('id', 'occurred_at', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CriticalActionExecutionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CriticalActionExecution
        fields = '__all__'
        read_only_fields = (
            'id',
            'action_code',
            'source_module',
            'target_model',
            'target_record_id',
            'status',
            'actor',
            'requires_transaction',
            'transaction_id',
            'message',
            'safe_context',
            'started_at',
            'completed_at',
            'error_message',
            'created_at',
            'updated_at',
        )


class ComplianceChecklistItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceChecklistItem
        fields = '__all__'
        read_only_fields = (
            'id',
            'source_module',
            'check_type',
            'status',
            'evidence',
            'checked_by',
            'checked_at',
            'created_at',
            'updated_at',
        )


class ModuleEvaluationRequestSerializer(serializers.Serializer):
    module = serializers.ChoiceField(
        choices=TransversalRequirementPolicy._meta.get_field('source_module').choices
    )
