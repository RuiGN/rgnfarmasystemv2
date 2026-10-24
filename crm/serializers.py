from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from crm.models import (
    Campaign,
    CustomerComplaint,
    CustomerContact,
    CustomerGroup,
    CustomerInteraction,
    CustomerProfile,
    Opportunity,
    SalesChannel,
    SalesContract,
    SalesOrder,
    SalesOrderItem,
    SalesProposal,
    SalesProposalItem,
    SalesRepresentative,
)


class SingleInstanceCrmSerializerMixin(ModelSerializerContractMixin):
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


class CustomerGroupSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomerGroup
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesChannelSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesChannel
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesRepresentativeSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesRepresentative
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('user', 'partner'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CustomerProfileSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomerProfile
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('customer', 'group', 'default_channel', 'representative'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CustomerContactSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomerContact
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CampaignSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class OpportunitySerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Opportunity
        fields = '__all__'
        read_only_fields = ('id', 'won_at', 'lost_at', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('customer', 'contact', 'channel', 'representative', 'campaign'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesProposalSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesProposal
        fields = '__all__'
        read_only_fields = (
            'id',
            'proposal_number',
            'status',
            'total_amount',
            'sent_at',
            'accepted_at',
            'rejected_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('opportunity', 'customer'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesProposalItemSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    line_subtotal = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = SalesProposalItem
        fields = (
            'id',
            'proposal',
            'product',
            'quantity',
            'unit_price',
            'discount_percent',
            'line_subtotal',
            'discount_amount',
            'line_total',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'line_subtotal',
            'discount_amount',
            'line_total',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('proposal', 'product'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesContractSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesContract
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
        for field_name in ('customer', 'opportunity', 'proposal'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesOrderSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = SalesOrder
        fields = '__all__'
        read_only_fields = (
            'id',
            'order_number',
            'status',
            'total_amount',
            'approved_by',
            'approved_at',
            'block_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('customer', 'proposal', 'contract', 'channel', 'representative'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SalesOrderItemSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    line_subtotal = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    discount_amount = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = SalesOrderItem
        fields = (
            'id',
            'order',
            'product',
            'quantity',
            'unit_price',
            'discount_percent',
            'promised_date',
            'line_subtotal',
            'discount_amount',
            'line_total',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'line_subtotal',
            'discount_amount',
            'line_total',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('order', 'product'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CustomerInteractionSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomerInteraction
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('customer', 'contact', 'opportunity', 'created_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CustomerComplaintSerializer(SingleInstanceCrmSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CustomerComplaint
        fields = '__all__'
        read_only_fields = (
            'id',
            'complaint_number',
            'status',
            'closed_at',
            'closed_by',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'customer',
            'contact',
            'product',
            'stock_lot',
            'sales_order',
            'fiscal_document',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
