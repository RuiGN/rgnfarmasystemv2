from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from recalls.models import (
    MarketComplaint,
    ProductReturn,
    RecallCampaign,
    RecallCommunication,
    RecallEffectivenessReport,
    RecallImpactedCustomer,
)


class SingleInstanceRecallsSerializerMixin(ModelSerializerContractMixin):
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


class MarketComplaintSerializer(SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = MarketComplaint
        fields = '__all__'
        read_only_fields = (
            'id',
            'complaint_number',
            'reported_by',
            'status',
            'triaged_by',
            'triaged_at',
            'investigation_started_by',
            'investigation_started_at',
            'investigation_summary',
            'regulatory_communication_reference',
            'regulatory_communicated_by',
            'regulatory_communicated_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ProductReturnSerializer(SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ProductReturn
        fields = '__all__'
        read_only_fields = (
            'id',
            'return_number',
            'status',
            'received_quantity',
            'disposition',
            'inspection_notes',
            'requested_by',
            'authorized_by',
            'authorized_at',
            'received_by',
            'received_at',
            'inspected_by',
            'inspected_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RecallCampaignSerializer(SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RecallCampaign
        fields = '__all__'
        read_only_fields = (
            'id',
            'campaign_number',
            'status',
            'approved_by',
            'approved_at',
            'started_by',
            'started_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RecallImpactedCustomerSerializer(
    SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RecallImpactedCustomer
        fields = '__all__'
        read_only_fields = (
            'id',
            'quantity_returned',
            'response_status',
            'response_notes',
            'response_received_at',
            'returned_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RecallCommunicationSerializer(
    SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RecallCommunication
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'sent_by',
            'sent_at',
            'acknowledged_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RecallEffectivenessReportSerializer(
    SingleInstanceRecallsSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = RecallEffectivenessReport
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'content_reference',
            'impacted_customers',
            'customers_contacted',
            'responses_received',
            'total_distributed',
            'total_recalled',
            'total_returned',
            'effectiveness_rate',
            'generated_by',
            'generated_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
