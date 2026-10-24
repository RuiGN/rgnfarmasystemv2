from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from planning.models import (
    CapacityLoad,
    CapacityResource,
    InventoryPosition,
    MPSLine,
    MRPRun,
    MRPSuggestion,
    MasterProductionSchedule,
    PlanningPolicy,
)


class SingleInstancePlanningSerializerMixin(ModelSerializerContractMixin):
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


class PlanningPolicySerializer(SingleInstancePlanningSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = PlanningPolicy
        fields = (
            'id',
            'product',
            'preferred_source',
            'safety_stock_quantity',
            'minimum_order_quantity',
            'order_multiple',
            'lead_time_days',
            'is_active',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MasterProductionScheduleSerializer(
    SingleInstancePlanningSerializerMixin, serializers.ModelSerializer
):
    lines_count = serializers.SerializerMethodField()

    class Meta:
        model = MasterProductionSchedule
        fields = (
            'id',
            'code',
            'name',
            'period_start',
            'period_end',
            'status',
            'notes',
            'lines_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'lines_count', 'created_at', 'updated_at')

    def get_lines_count(self, obj) -> int:
        annotated = getattr(obj, 'annotated_lines_count', None)
        return annotated if annotated is not None else obj.lines.count()

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MPSLineSerializer(SingleInstancePlanningSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = MPSLine
        fields = (
            'id',
            'schedule',
            'product',
            'due_date',
            'demand_quantity',
            'unit',
            'source',
            'customer_reference',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('schedule', 'product', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class InventoryPositionSerializer(
    SingleInstancePlanningSerializerMixin, serializers.ModelSerializer
):
    available_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    projected_available_quantity = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )

    class Meta:
        model = InventoryPosition
        fields = (
            'id',
            'product',
            'unit',
            'on_hand_quantity',
            'quarantine_quantity',
            'reserved_quantity',
            'incoming_purchase_quantity',
            'incoming_production_quantity',
            'expiry_date',
            'captured_at',
            'available_quantity',
            'projected_available_quantity',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'available_quantity',
            'projected_available_quantity',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MRPRunSerializer(SingleInstancePlanningSerializerMixin, serializers.ModelSerializer):
    suggestions_count = serializers.SerializerMethodField()

    class Meta:
        model = MRPRun
        fields = (
            'id',
            'schedule',
            'status',
            'run_at',
            'scenario_name',
            'demand_variation_percent',
            'lead_time_variation_days',
            'capacity_variation_percent',
            'restriction_notes',
            'notes',
            'suggestions_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'run_at',
            'suggestions_count',
            'created_at',
            'updated_at',
        )

    def get_suggestions_count(self, obj) -> int:
        annotated = getattr(obj, 'annotated_suggestions_count', None)
        return annotated if annotated is not None else obj.suggestions.count()

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MRPSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = MRPSuggestion
        fields = (
            'id',
            'run',
            'product',
            'suggestion_type',
            'due_date',
            'required_quantity',
            'available_quantity',
            'net_requirement',
            'suggested_quantity',
            'lead_time_days',
            'release_date',
            'alert_level',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = fields


class CapacityResourceSerializer(
    SingleInstancePlanningSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = CapacityResource
        fields = (
            'id',
            'code',
            'name',
            'resource_type',
            'work_center',
            'daily_capacity_minutes',
            'is_active',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CapacityLoadSerializer(SingleInstancePlanningSerializerMixin, serializers.ModelSerializer):
    is_overloaded = serializers.BooleanField(read_only=True)
    overload_minutes = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = CapacityLoad
        fields = (
            'id',
            'run',
            'resource',
            'period_date',
            'shift',
            'required_minutes',
            'available_minutes',
            'is_overloaded',
            'overload_minutes',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'is_overloaded',
            'overload_minutes',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('run', 'resource'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
