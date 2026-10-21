from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from compliance.models import (
    ComplianceChecklistItem,
    CriticalActionExecution,
    RecordStatusHistory,
    TransversalRequirementPolicy,
)
from compliance.serializers import (
    ComplianceChecklistItemSerializer,
    CriticalActionExecutionSerializer,
    ModuleEvaluationRequestSerializer,
    RecordStatusHistorySerializer,
    TransversalRequirementPolicySerializer,
)
from compliance.services import evaluate_module_readiness
from base.permissions import SingleInstanceDjangoModelPermissions


class SingleInstanceComplianceViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class TransversalRequirementPolicyViewSet(SingleInstanceComplianceViewSet):
    queryset = TransversalRequirementPolicy.objects.select_related('owner')
    serializer_class = TransversalRequirementPolicySerializer
    filterset_fields = ('source_module', 'enforcement_level', 'is_active', 'owner')
    search_fields = ('code', 'title', 'description', 'owner__email')
    ordering = ('source_module', 'code')

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)


class RecordStatusHistoryViewSet(SingleInstanceComplianceViewSet):
    queryset = RecordStatusHistory.objects.select_related('actor')
    serializer_class = RecordStatusHistorySerializer
    filterset_fields = (
        'source_module',
        'target_model',
        'target_record_id',
        'new_status',
        'actor',
        'occurred_at',
    )
    search_fields = (
        'target_model',
        'target_record_id',
        'previous_status',
        'new_status',
        'action',
        'reason',
        'actor__email',
    )
    ordering = ('-occurred_at',)


class CriticalActionExecutionViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = CriticalActionExecution.objects.select_related('actor')
    serializer_class = CriticalActionExecutionSerializer
    filterset_fields = (
        'source_module',
        'status',
        'actor',
        'requires_transaction',
        'started_at',
        'completed_at',
    )
    search_fields = (
        'action_code',
        'target_model',
        'target_record_id',
        'message',
        'error_message',
        'transaction_id',
        'actor__email',
    )
    ordering = ('-started_at',)

    def get_queryset(self):
        return self.queryset.all()


class ComplianceChecklistItemViewSet(viewsets.ReadOnlyModelViewSet):
    action_permission_map = {
        'evaluate_module': (
            'compliance.add_compliancechecklistitem',
            'compliance.change_compliancechecklistitem',
        ),
    }
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = ComplianceChecklistItem.objects.select_related('checked_by')
    serializer_class = ComplianceChecklistItemSerializer
    filterset_fields = ('source_module', 'check_type', 'status', 'checked_by', 'checked_at')
    search_fields = ('source_module', 'check_type', 'status', 'evidence', 'checked_by__email')
    ordering = ('source_module', 'check_type')

    def get_queryset(self):
        return self.queryset.all()

    @action(detail=False, methods=['post'])
    def evaluate_module(self, request):
        request_serializer = ModuleEvaluationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        result = evaluate_module_readiness(
            module=request_serializer.validated_data['module'],
            user=request.user,
        )
        item_serializer = self.get_serializer(result['items'], many=True)
        return Response(
            {
                'module': result['module'],
                'passed': result['passed'],
                'items': item_serializer.data,
            },
            status=status.HTTP_200_OK,
        )
