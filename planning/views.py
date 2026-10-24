from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from planning.models import (
    CapacityLoad,
    CapacityResource,
    InventoryPosition,
    MPSLine,
    MRPRun,
    MRPSuggestion,
    MasterProductionSchedule,
    PlanningPolicy,
)
from planning.serializers import (
    CapacityLoadSerializer,
    CapacityResourceSerializer,
    InventoryPositionSerializer,
    MPSLineSerializer,
    MRPRunSerializer,
    MRPSuggestionSerializer,
    MasterProductionScheduleSerializer,
    PlanningPolicySerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_response_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


class SingleInstancePlanningMixin:
    queryset: Any
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()


class SingleInstancePlanningViewSet(SingleInstancePlanningMixin, viewsets.ModelViewSet):
    def perform_create(self, serializer):
        serializer.save()


class SingleInstancePlanningReadOnlyViewSet(
    SingleInstancePlanningMixin, viewsets.ReadOnlyModelViewSet
):
    pass


class PlanningPolicyViewSet(SingleInstancePlanningViewSet):
    queryset = PlanningPolicy.objects.select_related('product')
    serializer_class = PlanningPolicySerializer
    filterset_fields = ('product', 'preferred_source', 'is_active')
    search_fields = ('product__code', 'product__description')
    ordering = ('product__code',)


class MasterProductionScheduleViewSet(SingleInstancePlanningViewSet):
    queryset = MasterProductionSchedule.objects.annotate(
        annotated_lines_count=Count('lines', distinct=True)
    )
    serializer_class = MasterProductionScheduleSerializer
    filterset_fields = ('status', 'period_start', 'period_end')
    search_fields = ('code', 'name')
    ordering = ('-period_start', 'code')


class MPSLineViewSet(SingleInstancePlanningViewSet):
    queryset = MPSLine.objects.select_related('schedule', 'product', 'unit')
    serializer_class = MPSLineSerializer
    filterset_fields = ('schedule', 'product', 'source', 'due_date')
    search_fields = (
        'schedule__code',
        'product__code',
        'product__description',
        'customer_reference',
    )
    ordering = ('due_date', 'product__code')


class InventoryPositionViewSet(SingleInstancePlanningViewSet):
    queryset = InventoryPosition.objects.select_related('product', 'unit')
    serializer_class = InventoryPositionSerializer
    filterset_fields = ('product', 'expiry_date')
    search_fields = ('product__code', 'product__description')
    ordering = ('product__code',)


class MRPRunViewSet(SingleInstancePlanningViewSet):
    queryset = (
        MRPRun.objects.select_related('schedule')
        .prefetch_related('suggestions')
        .annotate(annotated_suggestions_count=Count('suggestions', distinct=True))
    )
    serializer_class = MRPRunSerializer
    filterset_fields = ('schedule', 'status')
    search_fields = ('schedule__code', 'scenario_name', 'notes')

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        run = self.get_object()
        try:
            run.calculate()
        except DjangoValidationError as error:
            return Response(_validation_response_payload(error), status=status.HTTP_400_BAD_REQUEST)
        # A anotação carregada antes do cálculo ficou desatualizada.
        run.annotated_suggestions_count = None
        serializer = self.get_serializer(run)
        return Response(serializer.data)


class MRPSuggestionViewSet(SingleInstancePlanningReadOnlyViewSet):
    queryset = MRPSuggestion.objects.select_related('run', 'product')
    serializer_class = MRPSuggestionSerializer
    filterset_fields = ('run', 'product', 'suggestion_type', 'alert_level', 'due_date')
    search_fields = ('product__code', 'product__description', 'notes')
    ordering = ('due_date', 'product__code')


class CapacityResourceViewSet(SingleInstancePlanningViewSet):
    queryset = CapacityResource.objects.all()
    serializer_class = CapacityResourceSerializer
    filterset_fields = ('resource_type', 'work_center', 'is_active')
    search_fields = ('code', 'name', 'work_center')
    ordering = ('code',)


class CapacityLoadViewSet(SingleInstancePlanningViewSet):
    queryset = CapacityLoad.objects.select_related('run', 'resource')
    serializer_class = CapacityLoadSerializer
    filterset_fields = ('run', 'resource', 'period_date', 'shift')
    search_fields = ('resource__code', 'resource__name', 'shift', 'notes')
    ordering = ('period_date', 'resource__code')
