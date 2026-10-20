from collections.abc import Mapping

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)


class SingleInstanceProductionSerializerMixin(ModelSerializerContractMixin):
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
            details = (
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            )
            raise serializers.ValidationError(details) from error

    def _validate_immutable_order(self, attrs):
        requested_order = attrs.get('order')
        if (
            self.instance is not None
            and requested_order is not None
            and requested_order.pk != self.instance.order_id
        ):
            raise serializers.ValidationError(
                {'order': 'A ordem de um recurso existente não pode ser alterada.'}
            )

    def create(self, validated_data):
        instance = self.Meta.model(**validated_data)
        self._run_model_clean(instance)
        instance.save()
        return instance

    def update(self, instance, validated_data):
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        self._run_model_clean(instance)
        instance.save()
        return instance


class ProductionOrderSerializer(
    SingleInstanceProductionSerializerMixin, serializers.ModelSerializer
):
    def to_internal_value(self, data):
        if not isinstance(data, Mapping):
            return super().to_internal_value(data)
        controlled = {'status', 'cancelled_by', 'cancelled_at'}.intersection(data)
        if controlled:
            raise serializers.ValidationError(
                {field: 'Campo controlado pelo fluxo de domínio.' for field in sorted(controlled)}
            )
        return super().to_internal_value(data)

    @transaction.atomic
    def update(self, instance, validated_data):
        # Validation may have run before a lifecycle transition committed.
        # Reapply only the submitted fields to the current row under its lock.
        current = ProductionOrder.objects.select_for_update().get(pk=instance.pk)
        for field_name, value in validated_data.items():
            setattr(current, field_name, value)
        try:
            self._run_model_clean(current)
            current.save(update_fields=[*validated_data, 'updated_at'])
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            ) from error
        return current

    class Meta:
        model = ProductionOrder
        fields = (
            'id',
            'order_number',
            'batch_number',
            'product',
            'formula',
            'route',
            'planned_quantity',
            'unit',
            'status',
            'scheduled_start',
            'scheduled_end',
            'actual_start',
            'actual_end',
            'production_line',
            'approved_by',
            'approved_at',
            'released_by',
            'released_at',
            'started_by',
            'completed_by',
            'cancelled_by',
            'cancelled_at',
            'cancel_reason',
            'actual_yield_quantity',
            'real_loss_quantity',
            'rework_quantity',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'order_number',
            'batch_number',
            'status',
            'actual_start',
            'actual_end',
            'approved_by',
            'approved_at',
            'released_by',
            'released_at',
            'started_by',
            'completed_by',
            'cancelled_by',
            'cancelled_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'formula', 'route', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class MaterialConsumptionSerializer(
    SingleInstanceProductionSerializerMixin, serializers.ModelSerializer
):
    variance_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    def update(self, instance, validated_data):
        for field_name, value in validated_data.items():
            setattr(instance, field_name, value)
        try:
            instance.save(update_fields=[*validated_data, 'updated_at'])
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            ) from error
        return instance

    class Meta:
        model = MaterialConsumption
        fields = (
            'id',
            'order',
            'component',
            'material',
            'planned_quantity',
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'unit',
            'lot_number',
            'quality_status',
            'expiry_date',
            'variance_quantity',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'variance_quantity', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('order', 'component', 'material', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ProductionOutputSerializer(
    SingleInstanceProductionSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ProductionOutput
        fields = (
            'id',
            'order',
            'product',
            'lot_number',
            'sublot_number',
            'planned_quantity',
            'produced_quantity',
            'unit',
            'warehouse',
            'location',
            'manufacturing_date',
            'expiry_date',
            'status',
            'stock_lot',
            'stock_movement',
            'received_by',
            'received_at',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'stock_lot',
            'stock_movement',
            'received_by',
            'received_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._validate_immutable_order(attrs)
        if self.instance and self.instance.status == ProductionOutput.Status.RECEIVED:
            raise serializers.ValidationError(
                {'status': 'Resultados recebidos são imutáveis; use a evidência de recebimento.'}
            )
        order = attrs.get('order', getattr(self.instance, 'order', None))
        if order and order.status not in ProductionOutput.PENDING_MUTABLE_ORDER_STATUSES:
            raise serializers.ValidationError(
                {'order': 'A ordem não permite criar ou alterar resultados pendentes.'}
            )
        return attrs


class ProductionOperationExecutionSerializer(
    SingleInstanceProductionSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ProductionOperationExecution
        fields = (
            'id',
            'order',
            'route_step',
            'sequence',
            'operation',
            'work_center',
            'planned_minutes',
            'actual_minutes',
            'machine_hourly_cost',
            'status',
            'started_at',
            'ended_at',
            'recorded_by',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'actual_minutes',
            'recorded_by',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._validate_immutable_order(attrs)
        status_value = attrs.get(
            'status',
            getattr(self.instance, 'status', ProductionOperationExecution.Status.PENDING),
        )
        try:
            ProductionOperationExecution.validate_status_transition(
                self.instance.status if self.instance else None,
                status_value,
            )
        except DjangoValidationError as error:
            details = (
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            )
            raise serializers.ValidationError(details) from error
        return attrs


class ProductionLaborEntrySerializer(
    SingleInstanceProductionSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ProductionLaborEntry
        fields = (
            'id',
            'order',
            'operation_execution',
            'user',
            'role',
            'started_at',
            'ended_at',
            'duration_minutes',
            'hourly_cost',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'duration_minutes', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._validate_immutable_order(attrs)
        order = attrs.get('order', getattr(self.instance, 'order', None))
        if order and order.status not in ProductionLaborEntry.MUTABLE_ORDER_STATUSES:
            raise serializers.ValidationError(
                {'order': 'A ordem não permite criar ou alterar apontamentos de mão de obra.'}
            )
        return attrs


class ProductionCostActionSerializer(serializers.Serializer):
    period_start = serializers.DateField()
    period_end = serializers.DateField()

    def validate(self, attrs):
        if attrs['period_end'] < attrs['period_start']:
            raise serializers.ValidationError(
                {'period_end': 'O fim do período não pode ser anterior ao início.'}
            )
        if (attrs['period_start'].year, attrs['period_start'].month) != (
            attrs['period_end'].year,
            attrs['period_end'].month,
        ):
            raise serializers.ValidationError(
                {'period_end': 'A captura de custo deve permanecer no mesmo mês contábil.'}
            )
        return attrs
