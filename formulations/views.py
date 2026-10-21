from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets

from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula, RouteStep
from formulations.serializers import (
    FormulaComponentSerializer,
    ManufacturingRouteSerializer,
    MasterFormulaSerializer,
    RouteStepSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions
from formulations.writers import WriterViewSetMixin


class SingleInstanceFormulationViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('code',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class MasterFormulaViewSet(WriterViewSetMixin, SingleInstanceFormulationViewSet):
    queryset = MasterFormula.objects.select_related(
        'product', 'batch_unit', 'copied_from', 'approved_by'
    )
    serializer_class = MasterFormulaSerializer
    filterset_fields = ('product', 'status', 'version')
    search_fields = ('code', 'product__code', 'product__description')
    ordering = ('product__code', '-version')


class FormulaComponentViewSet(WriterViewSetMixin, SingleInstanceFormulationViewSet):
    queryset = FormulaComponent.objects.select_related('formula', 'material', 'unit')
    serializer_class = FormulaComponentSerializer
    filterset_fields = ('formula', 'material', 'role', 'is_active')
    search_fields = ('formula__code', 'material__code', 'material__description')
    ordering = ('formula__code', 'line_number')


class ManufacturingRouteViewSet(SingleInstanceFormulationViewSet):
    queryset = ManufacturingRoute.objects.select_related('product', 'formula')
    serializer_class = ManufacturingRouteSerializer
    filterset_fields = ('product', 'formula', 'status', 'version')
    search_fields = ('code', 'product__code', 'product__description', 'formula__code')
    ordering = ('product__code', '-version')


class RouteStepViewSet(SingleInstanceFormulationViewSet):
    queryset = RouteStep.objects.select_related('route', 'route__product')
    serializer_class = RouteStepSerializer
    filterset_fields = ('route', 'work_center')
    search_fields = ('route__code', 'operation', 'work_center', 'resource')
    ordering = ('route__code', 'sequence')
