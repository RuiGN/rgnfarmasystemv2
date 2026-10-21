from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from procurement.nfe_xml_import import NfeImportError, import_nfe_into_purchase_order
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
from procurement.serializers import (
    PurchaseOrderItemSerializer,
    PurchaseOrderSerializer,
    PurchaseReceiptItemSerializer,
    PurchaseReceiptSerializer,
    PurchaseReceiptStockPostingSerializer,
    PurchaseRequisitionItemSerializer,
    PurchaseRequisitionSerializer,
    QuotationRequestSerializer,
    SupplierQualificationEventSerializer,
    SupplierQuotationSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_response_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    if hasattr(error, 'messages'):
        return {'detail': error.messages}
    return {'detail': str(error)}


class SingleInstanceProcurementViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class PurchaseRequisitionViewSet(SingleInstanceProcurementViewSet):
    queryset = PurchaseRequisition.objects.prefetch_related('items')
    serializer_class = PurchaseRequisitionSerializer
    filterset_fields = ('source', 'status')
    search_fields = ('requisition_number', 'justification')

    def _transition_response(self, transition):
        requisition = self.get_object()
        try:
            transition(requisition)
        except DjangoValidationError as error:
            return Response(_validation_response_payload(error), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(requisition).data)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        return self._transition_response(lambda requisition: requisition.submit())

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._transition_response(lambda requisition: requisition.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        reason = request.data.get('rejection_reason', '')
        return self._transition_response(
            lambda requisition: requisition.reject(reason=reason, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._transition_response(lambda requisition: requisition.cancel())


class PurchaseRequisitionItemViewSet(SingleInstanceProcurementViewSet):
    queryset = PurchaseRequisitionItem.objects.select_related(
        'requisition', 'product', 'unit', 'mrp_suggestion'
    )
    serializer_class = PurchaseRequisitionItemSerializer
    filterset_fields = ('requisition', 'product', 'needed_by')
    search_fields = ('requisition__requisition_number', 'product__code', 'product__description')
    ordering = ('needed_by', 'product__code')


class QuotationRequestViewSet(SingleInstanceProcurementViewSet):
    queryset = QuotationRequest.objects.select_related('requisition').prefetch_related('quotations')
    serializer_class = QuotationRequestSerializer
    filterset_fields = ('requisition', 'status', 'due_date')
    search_fields = ('rfq_number', 'requisition__requisition_number', 'terms')

    def _transition_response(self, transition):
        rfq = self.get_object()
        try:
            transition(rfq)
        except DjangoValidationError as error:
            return Response(_validation_response_payload(error), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(rfq).data)

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        return self._transition_response(lambda rfq: rfq.send())

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._transition_response(lambda rfq: rfq.approve(user=request.user))


class SupplierQuotationViewSet(SingleInstanceProcurementViewSet):
    queryset = SupplierQuotation.objects.select_related('rfq', 'supplier')
    serializer_class = SupplierQuotationSerializer
    filterset_fields = ('rfq', 'supplier', 'status', 'valid_until')
    search_fields = (
        'rfq__rfq_number',
        'supplier__code',
        'supplier__legal_name',
        'payment_terms',
        'delivery_terms',
    )
    ordering = ('rfq__rfq_number', 'unit_price', 'lead_time_days')


class SupplierQualificationEventViewSet(SingleInstanceProcurementViewSet):
    queryset = SupplierQualificationEvent.objects.select_related(
        'supplier', 'site', 'event_state_ref', 'event_city_ref'
    )
    serializer_class = SupplierQualificationEventSerializer
    filterset_fields = (
        'supplier',
        'event_type',
        'blocks_purchases',
        'valid_until',
        'site',
        'event_state_ref',
        'event_city_ref',
    )
    search_fields = (
        'supplier__code',
        'supplier__legal_name',
        'description',
        'severity',
        'event_city_ref__name',
        'event_state_ref__name',
    )
    ordering = ('-event_date', '-created_at')


class PurchaseOrderViewSet(SingleInstanceProcurementViewSet):
    queryset = PurchaseOrder.objects.select_related(
        'supplier',
        'requisition',
        'source_quotation',
        'delivery_site',
        'delivery_state_ref',
        'delivery_city_ref',
    ).prefetch_related('items')
    serializer_class = PurchaseOrderSerializer
    filterset_fields = (
        'supplier',
        'requisition',
        'status',
        'expected_delivery_date',
        'delivery_site',
        'delivery_state_ref',
        'delivery_city_ref',
    )
    search_fields = (
        'order_number',
        'supplier__code',
        'supplier__legal_name',
        'notes',
        'delivery_city_ref__name',
        'delivery_state_ref__name',
    )

    def _transition_response(self, transition):
        order = self.get_object()
        try:
            transition(order)
        except DjangoValidationError as error:
            return Response(_validation_response_payload(error), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(order).data)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._transition_response(lambda order: order.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        return self._transition_response(lambda order: order.send())

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._transition_response(lambda order: order.cancel())


class PurchaseOrderItemViewSet(SingleInstanceProcurementViewSet):
    queryset = PurchaseOrderItem.objects.select_related(
        'order', 'requisition_item', 'product', 'unit'
    )
    serializer_class = PurchaseOrderItemSerializer
    filterset_fields = ('order', 'product', 'expected_delivery_date')
    search_fields = ('order__order_number', 'product__code', 'product__description')
    ordering = ('expected_delivery_date', 'product__code')


class PurchaseReceiptViewSet(SingleInstanceProcurementViewSet):
    action_permission_map = {'import_xml': ('procurement.add_purchasereceipt',)}

    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        try:
            serializer.save()
        except DjangoValidationError as error:
            raise ValidationError(_validation_response_payload(error)) from error

    perform_update = perform_create

    queryset = PurchaseReceipt.objects.select_related('order', 'nfe_xml_file').prefetch_related(
        'items__product', 'items__unit'
    )
    serializer_class = PurchaseReceiptSerializer
    filterset_fields = ('order', 'status', 'quality_status', 'stock_entry_status')
    search_fields = ('receipt_number', 'order__order_number', 'fiscal_document_number')

    def _transition_response(self, transition):
        receipt = self.get_object()
        try:
            transition(receipt)
        except DjangoValidationError as error:
            return Response(_validation_response_payload(error), status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(receipt).data)

    @action(detail=True, methods=['post'])
    def mark_received(self, request, pk=None):
        return self._transition_response(lambda receipt: receipt.mark_received(user=request.user))

    @action(detail=True, methods=['post'])
    def release_quality(self, request, pk=None):
        quality_status = request.data.get('quality_status')
        return self._transition_response(
            lambda receipt: receipt.release_quality(quality_status=quality_status)
        )

    @extend_schema(
        request=PurchaseReceiptStockPostingSerializer, responses=PurchaseReceiptSerializer
    )
    @action(detail=True, methods=['post'])
    def post_stock(self, request, pk=None):
        serializer = PurchaseReceiptStockPostingSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self._transition_response(
            lambda receipt: receipt.post_stock(**serializer.validated_data, user=request.user)
        )

    @action(
        detail=False,
        methods=['post'],
        parser_classes=(MultiPartParser, FormParser),
    )
    def import_xml(self, request):
        upload = request.FILES.get('xml')
        order_id = request.data.get('order_id')
        if upload is None or not order_id:
            return Response(
                {'detail': 'Informe o pedido e o arquivo XML NF-e.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        order = get_object_or_404(PurchaseOrder, pk=order_id)
        try:
            receipt = import_nfe_into_purchase_order(
                upload.read(),
                purchase_order=order,
                user=request.user,
                file_name=upload.name,
            )
        except NfeImportError as error:
            return Response(
                _validation_response_payload(error),
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(self.get_serializer(receipt).data, status=status.HTTP_201_CREATED)


class PurchaseReceiptItemViewSet(SingleInstanceProcurementViewSet):
    def perform_create(self, serializer):
        from rest_framework.exceptions import ValidationError

        try:
            serializer.save()
        except DjangoValidationError as error:
            raise ValidationError(_validation_response_payload(error)) from error

    perform_update = perform_create

    queryset = PurchaseReceiptItem.objects.select_related(
        'receipt', 'order_item', 'product', 'unit'
    )
    serializer_class = PurchaseReceiptItemSerializer
    filterset_fields = ('receipt', 'order_item', 'product', 'lot_number', 'expiry_date')
    search_fields = (
        'receipt__receipt_number',
        'product__code',
        'product__description',
        'lot_number',
    )
    ordering = ('receipt__receipt_number', 'product__code')
