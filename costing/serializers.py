from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from costing.models import (
    CostElement,
    CostReportSnapshot,
    CostSimulation,
    MonthlyCostClosing,
    ProductionCostCapture,
    StandardCost,
)


class SingleInstanceCostingSerializerMixin(ModelSerializerContractMixin):
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


class CostElementSerializer(SingleInstanceCostingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CostElement
        fields = (
            'id',
            'code',
            'name',
            'category',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class StandardCostSerializer(SingleInstanceCostingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = StandardCost
        fields = (
            'id',
            'product',
            'version',
            'status',
            'effective_from',
            'effective_to',
            'standard_quantity',
            'unit',
            'material_cost',
            'loss_cost',
            'labor_cost',
            'machine_cost',
            'third_party_cost',
            'analysis_cost',
            'overhead_cost',
            'indirect_cost',
            'tax_cost',
            'total_standard_cost',
            'approved_by',
            'approved_at',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'total_standard_cost',
            'approved_by',
            'approved_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CostSimulationSerializer(SingleInstanceCostingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = CostSimulation
        fields = (
            'id',
            'product',
            'formula',
            'name',
            'batch_size',
            'expected_yield_percent',
            'material_cost',
            'loss_percent',
            'labor_hours',
            'labor_rate',
            'machine_hours',
            'machine_rate',
            'third_party_cost',
            'analysis_cost',
            'overhead_rate_percent',
            'indirect_cost',
            'tax_rate_percent',
            'capacity_factor_percent',
            'simulated_total_cost',
            'simulated_unit_cost',
            'assumptions',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'simulated_total_cost',
            'simulated_unit_cost',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'formula'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ProductionCostCaptureSerializer(
    SingleInstanceCostingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ProductionCostCapture
        fields = (
            'id',
            'production_order',
            'period_start',
            'period_end',
            'planned_cost',
            'actual_material_cost',
            'actual_loss_cost',
            'actual_labor_cost',
            'actual_machine_cost',
            'actual_third_party_cost',
            'actual_analysis_cost',
            'actual_overhead_cost',
            'actual_indirect_cost',
            'non_quality_cost',
            'rework_cost',
            'total_actual_cost',
            'variance_amount',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'total_actual_cost',
            'variance_amount',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('production_order',):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MonthlyCostClosingSerializer(
    SingleInstanceCostingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = MonthlyCostClosing
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


class CostReportSnapshotSerializer(
    SingleInstanceCostingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = CostReportSnapshot
        fields = (
            'id',
            'report_type',
            'product',
            'stock_lot',
            'production_order',
            'period_start',
            'period_end',
            'revenue_amount',
            'cost_amount',
            'margin_amount',
            'margin_percent',
            'non_quality_cost',
            'deviation_impact',
            'rework_impact',
            'generated_at',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'margin_amount',
            'margin_percent',
            'generated_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'stock_lot', 'production_order'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
