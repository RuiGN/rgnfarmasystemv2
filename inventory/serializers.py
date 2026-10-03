from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from inventory.models import StockBalance, StockLot, StockLotGenealogy, StockMovement


class SingleInstanceInventorySerializerMixin(ModelSerializerContractMixin):
    controlled_write_fields: tuple[str, ...] = ()
    immutable_update_fields: tuple[str, ...] = ()

    def to_internal_value(self, data):
        immutable_fields = [
            field_name
            for field_name in self.immutable_update_fields
            if self.instance is not None and field_name in data
        ]
        if immutable_fields:
            raise serializers.ValidationError(
                {
                    field_name: 'Campo de identidade imutável após a criação.'
                    for field_name in immutable_fields
                }
            )
        controlled_fields = [
            field_name for field_name in self.controlled_write_fields if field_name in data
        ]
        if controlled_fields:
            raise serializers.ValidationError(
                {
                    field_name: (
                        'Campo controlado pelo fluxo de domínio e indisponível '
                        'para mutação genérica.'
                    )
                    for field_name in controlled_fields
                }
            )
        return serializers.ModelSerializer.to_internal_value(self, data)

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


class StockLotSerializer(SingleInstanceInventorySerializerMixin, serializers.ModelSerializer):
    controlled_write_fields = ('quality_status',)
    is_expired = serializers.BooleanField(read_only=True)
    sublot_number = serializers.CharField(required=False, allow_blank=True, default='')

    class Meta:
        model = StockLot
        fields = (
            'id',
            'product',
            'lot_number',
            'sublot_number',
            'quality_status',
            'supplier',
            'source_purchase_receipt_item',
            'source_production_order',
            'manufacturing_date',
            'expiry_date',
            'is_expired',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'quality_status',
            'is_expired',
            'created_at',
            'updated_at',
        )
        extra_kwargs = {'sublot_number': {'required': False}}

    def validate(self, attrs):
        for field_name in (
            'product',
            'supplier',
            'source_purchase_receipt_item',
            'source_production_order',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class StockBalanceSerializer(SingleInstanceInventorySerializerMixin, serializers.ModelSerializer):
    controlled_write_fields = ('quality_status', 'quantity', 'reserved_quantity')
    immutable_update_fields = StockBalance.IDENTITY_FIELDS
    available_quantity = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    can_issue = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockBalance
        fields = (
            'id',
            'product',
            'lot',
            'warehouse',
            'location',
            'quality_status',
            'quantity',
            'reserved_quantity',
            'available_quantity',
            'can_issue',
            'unit',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'quality_status',
            'quantity',
            'reserved_quantity',
            'available_quantity',
            'can_issue',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('product', 'lot', 'warehouse', 'location', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class StockMovementSerializer(SingleInstanceInventorySerializerMixin, serializers.ModelSerializer):
    def to_internal_value(self, data):
        raise serializers.ValidationError(
            {'detail': 'Ledger somente leitura. Utilize as operações de domínio.'}
        )

    def create(self, validated_data):
        raise serializers.ValidationError('Utilize as operações de domínio.')

    def update(self, instance, validated_data):
        raise serializers.ValidationError('Movimentos contabilizados são imutáveis.')

    class Meta:
        model = StockMovement
        fields = (
            'id',
            'movement_number',
            'movement_type',
            'product',
            'lot',
            'quantity',
            'unit',
            'quality_status',
            'from_warehouse',
            'from_location',
            'to_warehouse',
            'to_location',
            'movement_date',
            'source_purchase_receipt_item',
            'source_production_order',
            'source_material_consumption',
            'related_movement',
            'document_reference',
            'reason',
            'adjustment_reason',
            'created_by',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'movement_number', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in (
            'product',
            'lot',
            'unit',
            'from_warehouse',
            'from_location',
            'to_warehouse',
            'to_location',
            'source_purchase_receipt_item',
            'source_production_order',
            'source_material_consumption',
            'related_movement',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class StockIssueSerializer(SingleInstanceInventorySerializerMixin, serializers.ModelSerializer):
    stock_balance = serializers.PrimaryKeyRelatedField(
        queryset=StockBalance.objects.select_related(
            'product', 'lot', 'warehouse', 'location', 'unit'
        ),
        required=False,
    )
    reference = serializers.CharField(max_length=120, required=False, allow_blank=True)
    notes = serializers.CharField(max_length=4000, required=False, allow_blank=True)

    class Meta:
        model = StockMovement
        fields = (
            'stock_balance',
            'quantity',
            'reference',
            'notes',
            'product',
            'lot',
            'unit',
            'from_warehouse',
            'from_location',
            'reason',
        )
        extra_kwargs = {
            field: {'required': False, 'allow_null': False}
            for field in ('product', 'lot', 'unit', 'from_warehouse', 'from_location', 'reason')
        }

    def validate(self, attrs):
        balance = attrs.pop('stock_balance', None)
        reference = attrs.pop('reference', '')
        notes = attrs.pop('notes', '')
        if balance is not None:
            if balance.quality_status != 'approved':
                raise serializers.ValidationError(
                    {'stock_balance': 'Saída exige o saldo selecionado aprovado.'}
                )
            identity_fields = (
                'product',
                'lot',
                'unit',
                'from_warehouse',
                'from_location',
                'reason',
            )
            if any(field in attrs for field in identity_fields):
                raise serializers.ValidationError(
                    {'stock_balance': 'Informe somente o saldo, sem sobrescrever suas dimensões.'}
                )
            attrs.update(
                product=balance.product,
                lot=balance.lot,
                unit=balance.unit,
                from_warehouse=balance.warehouse,
                from_location=balance.location,
                reason=notes or 'Saída operacional',
            )
        else:
            missing = {
                field: 'Este campo é obrigatório.'
                for field in ('product', 'lot', 'unit', 'from_warehouse', 'from_location', 'reason')
                if not attrs.get(field)
            }
            if missing:
                raise serializers.ValidationError(missing)
        movement = StockMovement(
            **attrs,
            document_reference=reference,
            movement_type=StockMovement.MovementType.ISSUE,
            quality_status='approved',
        )
        self._run_model_clean(movement)
        attrs['document_reference'] = reference
        if balance is not None:
            attrs['stock_balance_id'] = balance.pk
        return attrs


class StockLotGenealogySerializer(
    SingleInstanceInventorySerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = StockLotGenealogy
        fields = (
            'id',
            'input_lot',
            'output_lot',
            'relation_type',
            'quantity',
            'unit',
            'production_order',
            'document_reference',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('input_lot', 'output_lot', 'unit', 'production_order'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
