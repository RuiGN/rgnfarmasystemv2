from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from governance.models import (
    DemoScenarioLoad,
    GovernanceAuditLog,
    GovernanceCatalogItem,
    GovernanceParameter,
    InstitutionSettings,
)


class SingleInstanceGovernanceSerializerMixin:
    context: dict[str, Any]
    instance: Any
    Meta: Any

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


class GovernanceParameterSerializer(
    SingleInstanceGovernanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = GovernanceParameter
        fields = '__all__'
        read_only_fields = ('id', 'updated_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class InstitutionSettingsSerializer(
    SingleInstanceGovernanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = InstitutionSettings
        fields = (
            'id',
            'trade_name',
            'legal_name',
            'document',
            'state_registration',
            'municipal_registration',
            'tax_regime',
            'phone',
            'email',
            'website',
            'zipcode',
            'street',
            'street_number',
            'complement',
            'neighborhood',
            'state_ref',
            'city_ref',
            'logo',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class GovernanceCatalogItemSerializer(
    SingleInstanceGovernanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = GovernanceCatalogItem
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class GovernanceAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = GovernanceAuditLog
        fields = '__all__'
        read_only_fields = (
            'id',
            'log_type',
            'severity',
            'module',
            'action',
            'target_model',
            'target_record_id',
            'user',
            'message',
            'safe_context',
            'request_id',
            'occurred_at',
            'created_at',
            'updated_at',
        )


class DemoScenarioLoadSerializer(
    SingleInstanceGovernanceSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DemoScenarioLoad
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'requested_by',
            'started_at',
            'completed_at',
            'records_created',
            'error_message',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
