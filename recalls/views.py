from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from recalls.models import (
    MarketComplaint,
    ProductReturn,
    RecallCampaign,
    RecallCommunication,
    RecallEffectivenessReport,
    RecallImpactedCustomer,
)
from recalls.serializers import (
    MarketComplaintSerializer,
    ProductReturnSerializer,
    RecallCampaignSerializer,
    RecallCommunicationSerializer,
    RecallEffectivenessReportSerializer,
    RecallImpactedCustomerSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


class SingleInstanceRecallsViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()

    def _domain_action_response(self, callback):
        obj = self.get_object()
        try:
            callback(obj)
        except DjangoValidationError as error:
            return Response(_validation_payload(error), status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


class MarketComplaintViewSet(SingleInstanceRecallsViewSet):
    queryset = MarketComplaint.objects.select_related(
        'customer',
        'product',
        'stock_lot',
        'sales_order',
        'fiscal_document',
        'customer_complaint',
        'quality_sample',
        'deviation_event',
        'capa',
        'document',
        'responsible',
        'reported_by',
        'triaged_by',
        'investigation_started_by',
        'regulatory_communicated_by',
        'closed_by',
        'state_ref',
        'city_ref',
    )
    serializer_class = MarketComplaintSerializer
    filterset_fields = (
        'complaint_type',
        'source',
        'status',
        'customer',
        'product',
        'stock_lot',
        'criticality',
        'responsible',
        'regulatory_communication_required',
        'state_ref',
        'city_ref',
    )
    search_fields = (
        'complaint_number',
        'description',
        'regulatory_communication_reference',
        'customer__legal_name',
        'product__code',
        'stock_lot__lot_number',
        'city_ref__name',
        'state_ref__name',
    )
    ordering = ('-received_at', '-created_at')

    def perform_create(self, serializer):
        serializer.save(reported_by=self.request.user)

    @action(detail=True, methods=['post'])
    def start_triage(self, request, pk=None):
        return self._domain_action_response(
            lambda complaint: complaint.start_triage(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def start_investigation(self, request, pk=None):
        return self._domain_action_response(
            lambda complaint: complaint.start_investigation(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def record_regulatory_communication(self, request, pk=None):
        reference = request.data.get('reference', '')
        return self._domain_action_response(
            lambda complaint: complaint.record_regulatory_communication(
                reference=reference, user=request.user
            )
        )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        summary = request.data.get('summary', '')
        return self._domain_action_response(
            lambda complaint: complaint.close(summary=summary, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('reason', '')
        return self._domain_action_response(
            lambda complaint: complaint.cancel(reason=reason, user=request.user)
        )


class ProductReturnViewSet(SingleInstanceRecallsViewSet):
    queryset = ProductReturn.objects.select_related(
        'complaint',
        'customer',
        'product',
        'stock_lot',
        'sales_order',
        'fiscal_document',
        'unit',
        'requested_by',
        'authorized_by',
        'received_by',
        'inspected_by',
        'closed_by',
    )
    serializer_class = ProductReturnSerializer
    filterset_fields = (
        'complaint',
        'return_type',
        'status',
        'customer',
        'product',
        'stock_lot',
        'disposition',
    )
    search_fields = (
        'return_number',
        'reason',
        'inspection_notes',
        'closure_summary',
        'customer__legal_name',
        'product__code',
        'stock_lot__lot_number',
    )
    ordering = ('-created_at',)

    def perform_create(self, serializer):
        serializer.save(requested_by=self.request.user)

    @action(detail=True, methods=['post'])
    def authorize(self, request, pk=None):
        return self._domain_action_response(
            lambda product_return: product_return.authorize(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def receive(self, request, pk=None):
        quantity = request.data.get('quantity')
        return self._domain_action_response(
            lambda product_return: product_return.receive(quantity=quantity, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def inspect(self, request, pk=None):
        disposition = request.data.get('disposition', '')
        notes = request.data.get('notes', '')
        return self._domain_action_response(
            lambda product_return: product_return.inspect(
                disposition=disposition, notes=notes, user=request.user
            )
        )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        summary = request.data.get('summary', '')
        return self._domain_action_response(
            lambda product_return: product_return.close(summary=summary, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('reason', '')
        return self._domain_action_response(
            lambda product_return: product_return.cancel(reason=reason, user=request.user)
        )


class RecallCampaignViewSet(SingleInstanceRecallsViewSet):
    queryset = RecallCampaign.objects.select_related(
        'product',
        'stock_lot',
        'complaint',
        'deviation_event',
        'capa',
        'responsible',
        'approved_by',
        'started_by',
        'closed_by',
    )
    serializer_class = RecallCampaignSerializer
    filterset_fields = (
        'campaign_type',
        'trigger',
        'status',
        'product',
        'stock_lot',
        'complaint',
        'criticality',
        'responsible',
        'target_completion_date',
    )
    search_fields = (
        'campaign_number',
        'reason',
        'closure_summary',
        'product__code',
        'stock_lot__lot_number',
    )
    ordering = ('-decision_date', '-created_at')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._domain_action_response(lambda campaign: campaign.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._domain_action_response(lambda campaign: campaign.start(user=request.user))

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        summary = request.data.get('summary', '')
        return self._domain_action_response(
            lambda campaign: campaign.close(summary=summary, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('reason', '')
        return self._domain_action_response(
            lambda campaign: campaign.cancel(reason=reason, user=request.user)
        )


class RecallImpactedCustomerViewSet(SingleInstanceRecallsViewSet):
    queryset = RecallImpactedCustomer.objects.select_related(
        'campaign', 'customer', 'sales_order', 'fiscal_document'
    )
    serializer_class = RecallImpactedCustomerSerializer
    filterset_fields = ('campaign', 'customer', 'sales_order', 'fiscal_document', 'response_status')
    search_fields = (
        'campaign__campaign_number',
        'customer__legal_name',
        'contact_name',
        'contact_email',
        'response_notes',
    )
    ordering = ('campaign__campaign_number', 'customer__legal_name')

    @action(detail=True, methods=['post'])
    def record_response(self, request, pk=None):
        response_status = request.data.get('status', '')
        notes = request.data.get('notes', '')
        return self._domain_action_response(
            lambda impacted: impacted.record_response(status=response_status, notes=notes)
        )

    @action(detail=True, methods=['post'])
    def record_return(self, request, pk=None):
        quantity = request.data.get('quantity')
        notes = request.data.get('notes', '')
        return self._domain_action_response(
            lambda impacted: impacted.record_return(quantity=quantity, notes=notes)
        )


class RecallCommunicationViewSet(SingleInstanceRecallsViewSet):
    queryset = RecallCommunication.objects.select_related(
        'campaign', 'impacted_customer', 'sent_by'
    )
    serializer_class = RecallCommunicationSerializer
    filterset_fields = ('campaign', 'impacted_customer', 'channel', 'status', 'response_due_date')
    search_fields = ('campaign__campaign_number', 'subject', 'message', 'content_hash')
    ordering = ('campaign__campaign_number', '-created_at')

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        return self._domain_action_response(
            lambda communication: communication.send(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        return self._domain_action_response(lambda communication: communication.acknowledge())


class RecallEffectivenessReportViewSet(SingleInstanceRecallsViewSet):
    queryset = RecallEffectivenessReport.objects.select_related('campaign', 'generated_by')
    serializer_class = RecallEffectivenessReportSerializer
    filterset_fields = ('campaign', 'report_type', 'status', 'generated_by', 'generated_at')
    search_fields = ('campaign__campaign_number', 'title', 'content_reference')
    ordering = ('campaign__campaign_number', '-created_at')

    @action(detail=True, methods=['post'])
    def generate(self, request, pk=None):
        content_reference = request.data.get('content_reference', '')
        return self._domain_action_response(
            lambda report: report.generate(user=request.user, content_reference=content_reference)
        )
