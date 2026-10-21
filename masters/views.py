from rest_framework import filters, viewsets
from django_filters.rest_framework import DjangoFilterBackend

from base.permissions import SingleInstanceDjangoModelPermissions
from formulations.writers import WriterViewSetMixin
from masters.models import (
    BusinessPartner,
    MasterCategory,
    Product,
    Site,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
)
from masters.serializers import (
    BusinessPartnerSerializer,
    MasterCategorySerializer,
    ProductSerializer,
    SiteSerializer,
    StorageLocationSerializer,
    UnitOfMeasureSerializer,
    WarehouseSerializer,
)


class SingleInstanceMasterViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('code',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class UnitOfMeasureViewSet(SingleInstanceMasterViewSet):
    queryset = UnitOfMeasure.objects.all()
    serializer_class = UnitOfMeasureSerializer
    filterset_fields = ('is_active',)
    search_fields = ('code', 'name', 'symbol')


class MasterCategoryViewSet(SingleInstanceMasterViewSet):
    queryset = MasterCategory.objects.select_related('parent')
    serializer_class = MasterCategorySerializer
    filterset_fields = ('kind', 'is_active')
    search_fields = ('code', 'name')
    ordering = ('kind', 'name')


class ProductViewSet(WriterViewSetMixin, SingleInstanceMasterViewSet):
    queryset = Product.objects.select_related(
        'unit',
        'category',
        'product_line',
        'cosmetic_form',
        'application_area',
    )
    serializer_class = ProductSerializer
    filterset_fields = (
        'item_type',
        'status',
        'requires_quality_release',
        'requires_approved_supplier',
    )
    search_fields = ('code', 'description', 'fiscal_ncm')


class BusinessPartnerViewSet(SingleInstanceMasterViewSet):
    queryset = BusinessPartner.objects.select_related('city_ref', 'state_ref')
    serializer_class = BusinessPartnerSerializer
    filterset_fields = (
        'partner_type',
        'qualification_status',
        'is_active',
        'is_blocked',
        'state_ref',
        'city_ref',
    )
    search_fields = (
        'code',
        'legal_name',
        'trade_name',
        'document',
        'city_ref__name',
        'state_ref__name',
        'state_ref__name',
    )
    ordering = ('legal_name',)


class SiteViewSet(SingleInstanceMasterViewSet):
    queryset = Site.objects.select_related('city_ref', 'state_ref')
    serializer_class = SiteSerializer
    filterset_fields = ('site_type', 'is_active', 'state_ref', 'city_ref')
    search_fields = ('code', 'name', 'city_ref__name', 'state_ref__name')
    ordering = ('name',)


class WarehouseViewSet(SingleInstanceMasterViewSet):
    queryset = Warehouse.objects.select_related('site')
    serializer_class = WarehouseSerializer
    filterset_fields = ('warehouse_type', 'is_active', 'site')
    search_fields = ('code', 'name', 'site__name')
    ordering = ('site__name', 'name')


class StorageLocationViewSet(SingleInstanceMasterViewSet):
    queryset = StorageLocation.objects.select_related('warehouse', 'warehouse__site')
    serializer_class = StorageLocationSerializer
    filterset_fields = ('warehouse', 'is_active')
    search_fields = ('code', 'name', 'warehouse__name')
    ordering = ('warehouse__name', 'code')
