from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin, instance_for_clean
from base.aggregate_writes import WriterSerializerMixin

from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula, RouteStep


class SingleInstanceFormulationSerializerMixin(ModelSerializerContractMixin):
    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def _instance_for_clean(self, attrs):
        return instance_for_clean(self.Meta.model, self.instance, attrs)


class MasterFormulaSerializer(
    WriterSerializerMixin, SingleInstanceFormulationSerializerMixin, serializers.ModelSerializer
):
    is_released = serializers.BooleanField(read_only=True)

    class Meta:
        model = MasterFormula
        fields = (
            'id',
            'product',
            'code',
            'version',
            'status',
            'batch_size',
            'batch_unit',
            'expected_yield_percent',
            'effective_from',
            'effective_to',
            'copied_from',
            'approved_by',
            'approved_at',
            'notes',
            'is_released',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'approved_by',
            'approved_at',
            'is_released',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'batch_unit', 'copied_from'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class FormulaComponentSerializer(
    WriterSerializerMixin, SingleInstanceFormulationSerializerMixin, serializers.ModelSerializer
):
    planned_quantity_with_loss = serializers.DecimalField(
        max_digits=14, decimal_places=4, read_only=True
    )

    class Meta:
        model = FormulaComponent
        fields = (
            'id',
            'formula',
            'line_number',
            'material',
            'role',
            'quantity',
            'unit',
            'expected_loss_percent',
            'conversion_factor',
            'is_active',
            'planned_quantity_with_loss',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'planned_quantity_with_loss',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('formula', 'material', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ManufacturingRouteSerializer(
    SingleInstanceFormulationSerializerMixin, serializers.ModelSerializer
):
    is_released = serializers.BooleanField(read_only=True)

    class Meta:
        model = ManufacturingRoute
        fields = (
            'id',
            'product',
            'formula',
            'code',
            'version',
            'status',
            'effective_from',
            'effective_to',
            'notes',
            'is_released',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'is_released', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('product', 'formula'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class RouteStepSerializer(SingleInstanceFormulationSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = RouteStep
        fields = (
            'id',
            'route',
            'sequence',
            'operation',
            'work_center',
            'resource',
            'setup_time_minutes',
            'standard_time_minutes',
            'critical_parameters',
            'instructions',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
