from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from risks.models import (
    RiskAlert,
    RiskAssessment,
    RiskControl,
    RiskLink,
    RiskMitigationAction,
    RiskRecord,
    RiskReview,
)
from risks.serializers import (
    RiskAlertSerializer,
    RiskAssessmentSerializer,
    RiskControlSerializer,
    RiskLinkSerializer,
    RiskMitigationActionSerializer,
    RiskRecordSerializer,
    RiskReviewSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


class SingleInstanceRiskViewSet(viewsets.ModelViewSet):
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


class RiskRecordViewSet(SingleInstanceRiskViewSet):
    queryset = RiskRecord.objects.select_related(
        'owner', 'identified_by', 'treatment_started_by', 'monitoring_started_by', 'closed_by'
    )
    serializer_class = RiskRecordSerializer
    filterset_fields = (
        'risk_category',
        'status',
        'owner',
        'due_date',
        'next_review_date',
        'initial_level',
        'residual_level',
    )
    search_fields = ('risk_number', 'title', 'description', 'process_area')
    ordering = ('-created_at',)

    def perform_create(self, serializer):
        serializer.save(identified_by=self.request.user)

    @action(detail=True, methods=['post'])
    def start_treatment(self, request, pk=None):
        return self._domain_action_response(lambda risk: risk.start_treatment(user=request.user))

    @action(detail=True, methods=['post'])
    def start_monitoring(self, request, pk=None):
        return self._domain_action_response(lambda risk: risk.start_monitoring(user=request.user))

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        summary = request.data.get('summary', '')
        return self._domain_action_response(
            lambda risk: risk.close(summary=summary, user=request.user)
        )

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('reason', '')
        return self._domain_action_response(lambda risk: risk.cancel(reason=reason))

    @action(detail=True, methods=['post'])
    def generate_alerts(self, request, pk=None):
        risk = self.get_object()
        generated = risk.generate_alerts()
        serializer = self.get_serializer(risk)
        return Response({'generated': generated, 'risk': serializer.data})


class RiskAssessmentViewSet(SingleInstanceRiskViewSet):
    queryset = RiskAssessment.objects.select_related('risk', 'assessed_by')
    serializer_class = RiskAssessmentSerializer
    filterset_fields = ('risk', 'assessment_type', 'method', 'risk_level', 'assessed_by')
    search_fields = ('risk__risk_number', 'rationale')
    ordering = ('risk__risk_number', '-assessed_at')


class RiskControlViewSet(SingleInstanceRiskViewSet):
    queryset = RiskControl.objects.select_related('risk', 'owner')
    serializer_class = RiskControlSerializer
    filterset_fields = ('risk', 'control_type', 'status', 'owner')
    search_fields = (
        'risk__risk_number',
        'title',
        'description',
        'evidence_reference',
        'content_hash',
    )
    ordering = ('risk__risk_number', 'control_type', 'title')


class RiskMitigationActionViewSet(SingleInstanceRiskViewSet):
    queryset = RiskMitigationAction.objects.select_related('risk', 'responsible', 'completed_by')
    serializer_class = RiskMitigationActionSerializer
    filterset_fields = (
        'risk',
        'action_type',
        'status',
        'responsible',
        'mandatory',
        'evidence_required',
        'due_date',
    )
    search_fields = (
        'risk__risk_number',
        'title',
        'description',
        'completion_notes',
        'evidence_reference',
        'content_hash',
    )
    ordering = ('risk__risk_number', 'due_date')

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


class RiskLinkViewSet(SingleInstanceRiskViewSet):
    queryset = RiskLink.objects.select_related(
        'risk',
        'product',
        'document',
        'deviation_event',
        'capa',
        'change_control',
        'audit',
        'supplier',
    )
    serializer_class = RiskLinkSerializer
    filterset_fields = (
        'risk',
        'link_type',
        'product',
        'document',
        'deviation_event',
        'capa',
        'change_control',
        'audit',
        'supplier',
    )
    search_fields = ('risk__risk_number', 'reference_code', 'impact_description')
    ordering = ('risk__risk_number', 'link_type')


class RiskReviewViewSet(SingleInstanceRiskViewSet):
    queryset = RiskReview.objects.select_related('risk', 'reviewer', 'completed_by')
    serializer_class = RiskReviewSerializer
    filterset_fields = ('risk', 'status', 'reviewer', 'planned_date', 'next_review_date')
    search_fields = ('risk__risk_number', 'review_scope', 'result')
    ordering = ('risk__risk_number', 'planned_date')

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        result = request.data.get('result', '')
        next_review_date = request.data.get('next_review_date')
        return self._domain_action_response(
            lambda review: review.complete(
                result=result, next_review_date=next_review_date, user=request.user
            )
        )


class RiskAlertViewSet(SingleInstanceRiskViewSet):
    action_permission_map = {'generate': ('risks.add_riskalert',)}
    queryset = RiskAlert.objects.select_related('risk', 'action', 'acknowledged_by')
    serializer_class = RiskAlertSerializer
    filterset_fields = ('risk', 'action', 'alert_type', 'severity', 'status', 'due_date')
    search_fields = ('risk__risk_number', 'message')
    ordering = ('-created_at',)

    @action(detail=False, methods=['post'])
    def generate(self, request):
        generated = RiskAlert.generate_all()
        return Response({'generated': generated})

    @action(detail=True, methods=['post'])
    def acknowledge(self, request, pk=None):
        return self._domain_action_response(lambda alert: alert.acknowledge(user=request.user))
