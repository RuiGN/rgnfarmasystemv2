from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from integrations.models import (
    ApiCallLog,
    ApiClientApplication,
    IntegrationConnector,
    IntegrationEvent,
    LabelPrinterSettings,
)


class SingleInstanceIntegrationSerializerMixin(ModelSerializerContractMixin):
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
            if hasattr(error, 'message_dict'):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error


class LabelPrinterSettingsSerializer(
    SingleInstanceIntegrationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = LabelPrinterSettings
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class IntegrationConnectorSerializer(
    SingleInstanceIntegrationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = IntegrationConnector
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'is_active',
            'last_tested_at',
            'last_error',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        from rest_framework.exceptions import PermissionDenied

        instance = self.instance or IntegrationConnector(**attrs)
        try:
            instance.validate_fiscal_management(
                getattr(self.context.get('request'), 'user', None), attrs
            )
        except DjangoValidationError as error:
            raise PermissionDenied(error.message_dict) from error
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ApiClientApplicationSerializer(
    SingleInstanceIntegrationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ApiClientApplication
        fields = '__all__'
        read_only_fields = (
            'id',
            'secret_hash',
            'created_by',
            'last_used_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ApiCallLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ApiCallLog
        fields = '__all__'
        read_only_fields = (
            'id',
            'request_id',
            'api_version',
            'method',
            'path',
            'endpoint_name',
            'status_code',
            'outcome',
            'user',
            'client_application',
            'remote_addr',
            'user_agent',
            'duration_ms',
            'safe_context',
            'error_message',
            'created_at',
            'updated_at',
        )


class IntegrationEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = IntegrationEvent
        fields = '__all__'
        read_only_fields = (
            'id',
            'connector',
            'api_client_application',
            'event_type',
            'actor',
            'occurred_at',
            'message',
            'safe_context',
            'created_at',
            'updated_at',
        )
