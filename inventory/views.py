from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from base.permissions import SingleInstanceDjangoModelPermissions
from inventory.label_service import (
    LabelDataError,
    LabelPrinterConfigurationError,
    LabelPrinterConnectionError,
    print_lot_label,
)
from inventory.models import StockBalance, StockLot, StockLotGenealogy, StockMovement
from inventory.serializers import (
    StockBalanceSerializer,
    StockIssueSerializer,
    StockLotGenealogySerializer,
    StockLotSerializer,
    StockMovementSerializer,
)


class SingleInstanceInventoryViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class StockLotViewSet(SingleInstanceInventoryViewSet):
    exclude_from_action_registry = True
    action_permission_map = {'print_label': ('inventory.view_stocklot',)}
    queryset = StockLot.objects.select_related(
        'product', 'supplier', 'source_purchase_receipt_item', 'source_production_order'
    )
    serializer_class = StockLotSerializer
    filterset_fields = (
        'product',
        'lot_number',
        'sublot_number',
        'quality_status',
        'supplier',
        'expiry_date',
    )
    search_fields = (
        'product__code',
        'product__description',
        'lot_number',
        'sublot_number',
        'supplier__legal_name',
    )
    ordering = ('product__code', 'lot_number', 'sublot_number')

    def get_permissions(self):
        if getattr(self, 'action', '') == 'print_label':
            return [IsAuthenticated()]
        return super().get_permissions()

    @action(detail=True, methods=('post',), url_path='print_label')
    def print_label(self, request, pk=None):
        if not request.user.has_perm('inventory.view_stocklot'):
            return Response(
                {'detail': 'Você não tem permissão para imprimir etiquetas de lote.'},
                status=status.HTTP_403_FORBIDDEN,
            )
        try:
            result = print_lot_label(self.get_object(), request.user)
        except LabelDataError as error:
            return Response({'detail': str(error)}, status=status.HTTP_400_BAD_REQUEST)
        except (LabelPrinterConfigurationError, LabelPrinterConnectionError) as error:
            return Response({'detail': str(error)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        return Response(
            {'detail': 'Etiqueta enviada à impressora.', **result},
            status=status.HTTP_200_OK,
        )


class StockBalanceViewSet(SingleInstanceInventoryViewSet):
    queryset = StockBalance.objects.select_related(
        'product', 'lot', 'warehouse', 'location', 'unit'
    )
    serializer_class = StockBalanceSerializer
    filterset_fields = ('product', 'lot', 'warehouse', 'location', 'quality_status')
    search_fields = (
        'product__code',
        'product__description',
        'lot__lot_number',
        'warehouse__name',
        'location__code',
    )
    ordering = ('warehouse__name', 'location__code', 'product__code', 'lot__lot_number')


class StockMovementViewSet(SingleInstanceInventoryViewSet):
    def create(self, request, *args, **kwargs):
        return Response(
            {'detail': 'Ledger somente leitura. Utilize as operações de domínio.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    action_permission_map = {'issue': ('inventory.add_stockmovement',)}

    @action(detail=False, methods=['post'], serializer_class=StockIssueSerializer)
    def issue(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            with transaction.atomic():
                movement = StockMovement.issue_stock(
                    product=data['product'],
                    lot=data['lot'],
                    warehouse=data['from_warehouse'],
                    location=data['from_location'],
                    quantity=data['quantity'],
                    unit=data['unit'],
                    reason=data['reason'],
                    stock_balance_id=data.get('stock_balance_id'),
                )
                movement.created_by = request.user
                movement.document_reference = data['document_reference']
                movement.save(update_fields=['created_by', 'document_reference', 'updated_at'])
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(StockMovementSerializer(movement).data, status=status.HTTP_201_CREATED)

    update = create
    partial_update = create
    destroy = create

    queryset = StockMovement.objects.select_related(
        'product',
        'lot',
        'unit',
        'from_warehouse',
        'from_location',
        'to_warehouse',
        'to_location',
        'created_by',
    )
    serializer_class = StockMovementSerializer
    filterset_fields = ('movement_type', 'product', 'lot', 'quality_status', 'movement_date')
    search_fields = (
        'movement_number',
        'product__code',
        'product__description',
        'lot__lot_number',
        'document_reference',
        'reason',
    )
    ordering = ('-movement_date', '-created_at')


class StockLotGenealogyViewSet(SingleInstanceInventoryViewSet):
    queryset = StockLotGenealogy.objects.select_related(
        'input_lot', 'output_lot', 'unit', 'production_order'
    )
    serializer_class = StockLotGenealogySerializer
    filterset_fields = ('input_lot', 'output_lot', 'relation_type', 'production_order')
    search_fields = (
        'input_lot__lot_number',
        'output_lot__lot_number',
        'document_reference',
        'notes',
    )
    ordering = ('output_lot__lot_number', 'input_lot__lot_number')
