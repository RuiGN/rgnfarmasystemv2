from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin
from masters.models import StorageLocation, Warehouse

from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    QuotationRequest,
    SupplierQualificationEvent,
    SupplierQuotation,
)


class SingleInstanceProcurementSerializerMixin(ModelSerializerContractMixin):
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


class PurchaseRequisitionSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseRequisition
        fields = (
            'id',
            'requisition_number',
            'source',
            'status',
            'requested_by',
            'justification',
            'submitted_at',
            'approved_by',
            'approved_at',
            'rejected_by',
            'rejected_at',
            'rejection_reason',
            'notes',
            'items_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'submitted_at',
            'approved_by',
            'approved_at',
            'rejected_by',
            'rejected_at',
            'items_count',
            'created_at',
            'updated_at',
        )

    def get_items_count(self, obj) -> int:
        annotated = getattr(obj, 'annotated_items_count', None)
        return annotated if annotated is not None else obj.items.count()


class PurchaseRequisitionItemSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = PurchaseRequisitionItem
        fields = (
            'id',
            'requisition',
            'product',
            'quantity',
            'unit',
            'needed_by',
            'mrp_suggestion',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('requisition', 'product', 'unit', 'mrp_suggestion'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class QuotationRequestSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    best_quotation = serializers.SerializerMethodField()

    class Meta:
        model = QuotationRequest
        fields = (
            'id',
            'rfq_number',
            'requisition',
            'status',
            'due_date',
            'terms',
            'approved_by',
            'approved_at',
            'notes',
            'best_quotation',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'approved_by',
            'approved_at',
            'best_quotation',
            'created_at',
            'updated_at',
        )

    def get_best_quotation(self, obj) -> int | None:
        best = obj.best_quotation()
        return best.id if best else None

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SupplierQuotationSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    total_amount = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    is_supplier_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = SupplierQuotation
        fields = (
            'id',
            'rfq',
            'supplier',
            'status',
            'quoted_quantity',
            'unit_price',
            'tax_amount',
            'freight_amount',
            'currency',
            'lead_time_days',
            'payment_terms',
            'delivery_terms',
            'supplier_performance_score',
            'valid_until',
            'total_amount',
            'is_supplier_valid',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'total_amount',
            'is_supplier_valid',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('rfq', 'supplier'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SupplierQualificationEventSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    is_active_block = serializers.BooleanField(read_only=True)

    class Meta:
        model = SupplierQualificationEvent
        fields = (
            'id',
            'supplier',
            'event_type',
            'event_date',
            'valid_until',
            'severity',
            'blocks_purchases',
            'site',
            'event_zipcode',
            'event_street',
            'event_street_number',
            'event_complement',
            'event_neighborhood',
            'event_state_ref',
            'event_city_ref',
            'description',
            'resolved_at',
            'is_active_block',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'is_active_block', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class PurchaseOrderSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            'id',
            'order_number',
            'supplier',
            'requisition',
            'source_quotation',
            'status',
            'issue_date',
            'expected_delivery_date',
            'payment_terms',
            'delivery_terms',
            'delivery_site',
            'delivery_zipcode',
            'delivery_street',
            'delivery_street_number',
            'delivery_complement',
            'delivery_neighborhood',
            'delivery_state_ref',
            'delivery_city_ref',
            'currency',
            'freight_amount',
            'total_amount',
            'approved_by',
            'approved_at',
            'notes',
            'items_count',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'total_amount',
            'approved_by',
            'approved_at',
            'items_count',
            'created_at',
            'updated_at',
        )

    def get_items_count(self, obj) -> int:
        annotated = getattr(obj, 'annotated_items_count', None)
        return annotated if annotated is not None else obj.items.count()

    def validate(self, attrs):
        for field_name in ('supplier', 'requisition', 'source_quotation'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class PurchaseOrderItemSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    def update(self, instance, validated_data):
        try:
            return super().update(instance, validated_data)
        except DjangoValidationError as error:
            raise serializers.ValidationError(
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            ) from error

    line_subtotal = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)
    line_total = serializers.DecimalField(max_digits=14, decimal_places=4, read_only=True)

    class Meta:
        model = PurchaseOrderItem
        fields = (
            'id',
            'order',
            'requisition_item',
            'product',
            'quantity',
            'unit',
            'unit_price',
            'tax_amount',
            'expected_delivery_date',
            'line_subtotal',
            'line_total',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'line_subtotal',
            'line_total',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('order', 'requisition_item', 'product', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class PurchaseReceiptItemSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = PurchaseReceiptItem
        fields = (
            'id',
            'receipt',
            'order_item',
            'product',
            'received_quantity',
            'accepted_quantity',
            'rejected_quantity',
            'unit',
            'lot_number',
            'manufacturing_date',
            'expiry_date',
            'notes',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('receipt', 'order_item', 'product', 'unit'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class PurchaseReceiptStockPostingSerializer(serializers.Serializer):
    warehouse = serializers.PrimaryKeyRelatedField(queryset=Warehouse.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=StorageLocation.objects.all())


class PurchaseReceiptSerializer(
    SingleInstanceProcurementSerializerMixin, serializers.ModelSerializer
):
    items_count = serializers.SerializerMethodField()
    items = PurchaseReceiptItemSerializer(many=True, read_only=True)

    class Meta:
        model = PurchaseReceipt
        fields = (
            'id',
            'receipt_number',
            'order',
            'status',
            'fiscal_document_number',
            'nfe_access_key',
            'nfe_xml_sha256',
            'nfe_xml_file',
            'fiscal_received_at',
            'physical_received_at',
            'quality_status',
            'stock_entry_status',
            'received_by',
            'notes',
            'items_count',
            'items',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'nfe_access_key',
            'nfe_xml_sha256',
            'nfe_xml_file',
            'stock_entry_status',
            'received_by',
            'items_count',
            'items',
            'created_at',
            'updated_at',
        )

    def get_items_count(self, obj) -> int:
        annotated = getattr(obj, 'annotated_items_count', None)
        return annotated if annotated is not None else obj.items.count()

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
