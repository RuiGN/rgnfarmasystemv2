from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from audits.models import (
    AuditChecklistItem,
    AuditEvidence,
    AuditFinding,
    AuditFindingLink,
    AuditFollowUpAction,
    AuditPlan,
    AuditProgram,
    AuditReport,
)
from audits.serializers import (
    AuditChecklistItemSerializer,
    AuditEvidenceSerializer,
    AuditFindingLinkSerializer,
    AuditFindingSerializer,
    AuditFollowUpActionSerializer,
    AuditPlanSerializer,
    AuditProgramSerializer,
    AuditReportSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


class SingleInstanceAuditViewSet(viewsets.ModelViewSet):
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


class AuditProgramViewSet(SingleInstanceAuditViewSet):
    queryset = AuditProgram.objects.select_related('owner')
    serializer_class = AuditProgramSerializer
    filterset_fields = ('audit_type', 'status', 'year', 'owner')
    search_fields = ('program_number', 'title', 'scope', 'criteria')
    ordering = ('-year', 'title')

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        return self._domain_action_response(lambda program: program.activate())

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        return self._domain_action_response(lambda program: program.close())


class AuditPlanViewSet(SingleInstanceAuditViewSet):
    queryset = AuditPlan.objects.select_related(
        'program',
        'supplier',
        'lead_auditor',
        'submitted_by',
        'started_by',
        'completed_by',
        'closed_by',
        'venue_state_ref',
        'venue_city_ref',
    )
    serializer_class = AuditPlanSerializer
    filterset_fields = (
        'program',
        'audit_type',
        'status',
        'supplier',
        'lead_auditor',
        'area',
        'scheduled_start',
        'venue_state_ref',
        'venue_city_ref',
    )
    search_fields = (
        'audit_number',
        'title',
        'scope',
        'criteria',
        'agenda',
        'auditee_name',
        'area',
        'venue_city_ref__name',
        'venue_state_ref__name',
    )
    ordering = ('-scheduled_start',)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        return self._domain_action_response(lambda audit: audit.submit(user=request.user))

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._domain_action_response(lambda audit: audit.start(user=request.user))

    @action(detail=True, methods=['post'])
    def complete_execution(self, request, pk=None):
        return self._domain_action_response(
            lambda audit: audit.complete_execution(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        summary = request.data.get('summary', '')
        return self._domain_action_response(
            lambda audit: audit.close(summary=summary, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('reason', '')
        return self._domain_action_response(lambda audit: audit.cancel(reason=reason))


class AuditChecklistItemViewSet(SingleInstanceAuditViewSet):
    queryset = AuditChecklistItem.objects.select_related('audit', 'answered_by')
    serializer_class = AuditChecklistItemSerializer
    filterset_fields = ('audit', 'section', 'required', 'status', 'answered_by')
    search_fields = (
        'audit__audit_number',
        'section',
        'question',
        'requirement_reference',
        'answer_text',
    )
    ordering = ('audit__audit_number', 'section', 'id')

    @action(detail=True, methods=['post'])
    def answer(self, request, pk=None):
        status_value = request.data.get('status', '')
        answer = request.data.get('answer', '')
        return self._domain_action_response(
            lambda item: item.answer(status=status_value, answer=answer, user=request.user)
        )


class AuditFindingViewSet(SingleInstanceAuditViewSet):
    queryset = AuditFinding.objects.select_related('audit', 'checklist_item', 'responsible')
    serializer_class = AuditFindingSerializer
    filterset_fields = (
        'audit',
        'classification',
        'criticality',
        'status',
        'responsible',
        'due_date',
    )
    search_fields = ('audit__audit_number', 'title', 'description', 'responsible__email')
    ordering = ('audit__audit_number', '-criticality', 'due_date')

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        return self._domain_action_response(lambda finding: finding.close(user=request.user))


class AuditEvidenceViewSet(SingleInstanceAuditViewSet):
    queryset = AuditEvidence.objects.select_related('audit', 'finding', 'uploaded_by')
    serializer_class = AuditEvidenceSerializer
    filterset_fields = ('audit', 'finding', 'uploaded_by')
    search_fields = (
        'audit__audit_number',
        'finding__title',
        'title',
        'file_reference',
        'content_hash',
        'notes',
    )
    ordering = ('audit__audit_number', 'title')

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class AuditFollowUpActionViewSet(SingleInstanceAuditViewSet):
    queryset = AuditFollowUpAction.objects.select_related(
        'finding', 'finding__audit', 'responsible', 'completed_by'
    )
    serializer_class = AuditFollowUpActionSerializer
    filterset_fields = (
        'finding',
        'status',
        'responsible',
        'mandatory',
        'evidence_required',
        'due_date',
    )
    search_fields = (
        'finding__audit__audit_number',
        'finding__title',
        'title',
        'description',
        'completion_notes',
        'evidence_reference',
        'content_hash',
    )
    ordering = ('finding__audit__audit_number', 'due_date')

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._domain_action_response(lambda action_obj: action_obj.start())

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        completion_notes = request.data.get('completion_notes', '')
        evidence_reference = request.data.get('evidence_reference', '')
        content_hash = request.data.get('content_hash', '')
        return self._domain_action_response(
            lambda action_obj: action_obj.complete(
                user=request.user,
                completion_notes=completion_notes,
                evidence_reference=evidence_reference,
                content_hash=content_hash,
            )
        )


class AuditFindingLinkViewSet(SingleInstanceAuditViewSet):
    queryset = AuditFindingLink.objects.select_related(
        'finding',
        'finding__audit',
        'capa',
        'deviation_event',
        'change_control',
        'supplier',
        'document',
    )
    serializer_class = AuditFindingLinkSerializer
    filterset_fields = (
        'finding',
        'link_type',
        'capa',
        'deviation_event',
        'change_control',
        'supplier',
        'document',
    )
    search_fields = ('finding__audit__audit_number', 'finding__title', 'reference_code')
    ordering = ('finding__audit__audit_number', 'link_type')


class AuditReportViewSet(SingleInstanceAuditViewSet):
    queryset = AuditReport.objects.select_related('audit', 'issued_by')
    serializer_class = AuditReportSerializer
    filterset_fields = ('audit', 'status', 'issued_by', 'issued_at')
    search_fields = ('audit__audit_number', 'executive_summary', 'conclusion')
    ordering = ('audit__audit_number', '-created_at')

    @action(detail=True, methods=['post'])
    def issue(self, request, pk=None):
        return self._domain_action_response(lambda report: report.issue(user=request.user))
