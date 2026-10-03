from typing import Any

from datetime import date, datetime
from decimal import Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, mixins, status, viewsets
from rest_framework.authentication import (
    BaseAuthentication,
    BasicAuthentication,
    SessionAuthentication,
)
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.response import Response

from base.permissions import SingleInstanceDjangoModelPermissions
from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)
from production.serializers import (
    MaterialConsumptionSerializer,
    ProductionCostActionSerializer,
    ProductionLaborEntrySerializer,
    ProductionOperationExecutionSerializer,
    ProductionOrderSerializer,
    ProductionOutputSerializer,
)
from production.services import ProductionOrderOperations


class SingleInstanceProductionViewSetMixin:
    queryset: Any
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()


class SingleInstanceProductionViewSet(SingleInstanceProductionViewSetMixin, viewsets.ModelViewSet):
    pass


class NonDestructiveProductionViewSet(
    SingleInstanceProductionViewSetMixin,
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    audit_resource_name = ''
    audit_fields: tuple[str, ...] = ()

    @staticmethod
    def _safe_audit_value(value):
        if isinstance(value, Decimal):
            return str(value)
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    def _audit_snapshot(self, instance):
        return {
            field_name: self._safe_audit_value(getattr(instance, field_name))
            for field_name in self.audit_fields
        }

    def get_serializer_save_kwargs(self):
        return {}

    @staticmethod
    def _lock_order(order_id):
        return (
            ProductionOrder.objects.select_for_update()
            .select_related('product', 'formula', 'route', 'unit')
            .get(pk=order_id)
        )

    def _lock_requested_order(self, request):
        order_id = request.data.get('order')
        if order_id in (None, ''):
            return None
        try:
            return self._lock_order(order_id)
        except (
            DjangoValidationError,
            ProductionOrder.DoesNotExist,
            TypeError,
            ValueError,
        ):
            return None

    def _locked_instance(self, instance):
        return self.get_queryset().select_for_update(of=('self',)).get(pk=instance.pk)

    def _record_audit(self, instance, action, before):
        from governance.models import GovernanceAuditLog

        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module='production',
            action=f'api.{self.audit_resource_name}.{action}',
            target_model=instance.__class__.__name__,
            target_record_id=instance.pk,
            user=self.request.user,
            message=f'Recurso operacional de produção {action} via API.',
            safe_context={
                'before': before or {'record_exists': False},
                'after': self._audit_snapshot(instance),
            },
            request_id=self.request.META.get('HTTP_X_REQUEST_ID', ''),
        )

    def _save_and_audit(self, serializer, action, before):
        instance = serializer.save(**self.get_serializer_save_kwargs())
        self._record_audit(instance, action, before)
        return instance

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        locked_order = self._lock_requested_order(request)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        validated_order = serializer.validated_data.get('order')
        if locked_order is None or validated_order.pk != locked_order.pk:
            raise DRFValidationError({'order': 'Informe uma ordem de produção válida.'})
        serializer.validated_data['order'] = locked_order
        self._save_and_audit(serializer, 'created', {})
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        initial_instance = self.get_object()
        locked_order = self._lock_order(initial_instance.order_id)
        requested_order_id = request.data.get('order')
        if requested_order_id not in (None, '') and str(requested_order_id) != str(
            initial_instance.order_id
        ):
            raise DRFValidationError(
                {'order': 'A ordem de um recurso existente não pode ser alterada.'}
            )

        locked_instance = self._locked_instance(initial_instance)
        locked_instance.order = locked_order
        serializer = self.get_serializer(
            locked_instance,
            data=request.data,
            partial=partial,
        )
        serializer.is_valid(raise_exception=True)
        if 'order' in serializer.validated_data:
            serializer.validated_data['order'] = locked_order
        before = self._audit_snapshot(locked_instance)
        self._save_and_audit(serializer, 'updated', before)
        return Response(serializer.data)


class OperationalActionAuthenticationHeader(BaseAuthentication):
    """Advertise the global Basic challenge without changing credential precedence.

    DRF's default SessionAuthentication is intentionally kept ahead of BasicAuthentication
    for these operational actions. This no-op authenticator only supplies the challenge used
    for anonymous requests, allowing them to receive 401 instead of SessionAuthentication's
    default 403 response.
    """

    def authenticate(self, request):
        return None

    def authenticate_header(self, request):
        return BasicAuthentication().authenticate_header(request)


OPERATIONAL_ACTION_AUTHENTICATION_CLASSES = (
    OperationalActionAuthenticationHeader,
    SessionAuthentication,
    BasicAuthentication,
)


class ProductionOrderViewSet(SingleInstanceProductionViewSet):
    queryset = ProductionOrder.objects.select_related(
        'product', 'formula', 'route', 'unit', 'responsible'
    )
    serializer_class = ProductionOrderSerializer
    filterset_fields = ('product', 'formula', 'route', 'status')
    search_fields = ('order_number', 'batch_number', 'product__code', 'product__description')
    action_permission_map = {
        'reserve_materials': (
            'production.change_productionorder',
            'production.change_materialconsumption',
            'inventory.add_stockmovement',
        ),
        'issue_materials': (
            'production.change_productionorder',
            'production.change_materialconsumption',
            'inventory.add_stockmovement',
        ),
        'receive_outputs': (
            'production.receive_productionoutput',
            'inventory.add_stockmovement',
        ),
        'calculate_cost': (
            'production.change_productionorder',
            'costing.add_productioncostcapture',
        ),
    }

    def _transition_response(self, transition, *args):
        order = self.get_object()
        try:
            transition(order, *args)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(order)
        return Response(serializer.data)

    def _operational_action_response(self, callback, response_key):
        try:
            result = callback()
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response({response_key: [item.pk for item in result]})

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._transition_response(lambda order: order.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        return self._transition_response(lambda order: order.release(user=request.user))

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        return self._transition_response(lambda order: order.start(user=request.user))

    @action(detail=True, methods=['post'])
    def pause(self, request, pk=None):
        return self._transition_response(lambda order: order.pause(user=request.user))

    @action(detail=True, methods=['post'])
    def resume(self, request, pk=None):
        return self._transition_response(lambda order: order.resume(user=request.user))

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        quantity = request.data.get('actual_yield_quantity')
        if quantity is None:
            return Response(
                {'actual_yield_quantity': 'Informe o rendimento real.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return self._transition_response(lambda order: order.complete(quantity, user=request.user))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        reason = request.data.get('cancel_reason', '')
        return self._transition_response(
            lambda order: order.cancel(reason=reason, user=request.user)
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='reserve_materials',
        authentication_classes=OPERATIONAL_ACTION_AUTHENTICATION_CLASSES,
    )
    def reserve_materials(self, request, pk=None):
        return self._operational_action_response(
            lambda: ProductionOrderOperations(self.get_object(), request.user).reserve_materials(),
            'movement_ids',
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='issue_materials',
        authentication_classes=OPERATIONAL_ACTION_AUTHENTICATION_CLASSES,
    )
    def issue_materials(self, request, pk=None):
        return self._operational_action_response(
            lambda: ProductionOrderOperations(self.get_object(), request.user).issue_materials(),
            'movement_ids',
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='receive_outputs',
        authentication_classes=OPERATIONAL_ACTION_AUTHENTICATION_CLASSES,
    )
    def receive_outputs(self, request, pk=None):
        return self._operational_action_response(
            lambda: ProductionOrderOperations(self.get_object(), request.user).receive_outputs(),
            'output_ids',
        )

    @action(
        detail=True,
        methods=['post'],
        url_path='calculate_cost',
        authentication_classes=OPERATIONAL_ACTION_AUTHENTICATION_CLASSES,
    )
    def calculate_cost(self, request, pk=None):
        serializer = ProductionCostActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            capture = ProductionOrderOperations(self.get_object(), request.user).calculate_cost(
                **serializer.validated_data
            )
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response({'cost_capture_id': capture.pk})


class MaterialConsumptionViewSet(NonDestructiveProductionViewSet):
    audit_resource_name = 'material_consumption'
    audit_fields = ('order_id', 'actual_quantity', 'returned_quantity', 'return_movement_id')

    def _save_and_audit(self, serializer, action, before):
        try:
            return super()._save_and_audit(serializer, action, before)
        except DjangoValidationError as error:
            raise DRFValidationError(
                error.message_dict
                if hasattr(error, 'message_dict')
                else {'non_field_errors': error.messages}
            ) from error

    queryset = MaterialConsumption.objects.select_related(
        'order',
        'component',
        'material',
        'unit',
        'stock_lot',
        'warehouse',
        'location',
        'reservation_movement',
        'issue_movement',
        'loss_movement',
        'return_movement',
    )
    serializer_class = MaterialConsumptionSerializer
    filterset_fields = ('order', 'material', 'quality_status')
    search_fields = (
        'order__order_number',
        'order__batch_number',
        'material__code',
        'material__description',
        'lot_number',
    )
    ordering = ('order__order_number', 'material__code')


class ProductionOutputViewSet(NonDestructiveProductionViewSet):
    queryset = ProductionOutput.objects.select_related(
        'order',
        'product',
        'unit',
        'warehouse',
        'location',
        'stock_lot',
        'stock_movement',
        'received_by',
    )
    serializer_class = ProductionOutputSerializer
    audit_resource_name = 'production_output'
    audit_fields = (
        'order_id',
        'status',
        'planned_quantity',
        'produced_quantity',
    )
    filterset_fields = ('order', 'product', 'status', 'warehouse', 'location')
    search_fields = ('order__order_number', 'lot_number', 'sublot_number', 'product__code')
    ordering = ('order__order_number', 'lot_number', 'sublot_number')


class ProductionOperationExecutionViewSet(NonDestructiveProductionViewSet):
    queryset = ProductionOperationExecution.objects.select_related(
        'order', 'route_step', 'recorded_by'
    )
    serializer_class = ProductionOperationExecutionSerializer
    audit_resource_name = 'production_operation_execution'
    audit_fields = (
        'order_id',
        'status',
        'started_at',
        'ended_at',
        'actual_minutes',
        'recorded_by_id',
    )
    filterset_fields = ('order', 'route_step', 'status')
    search_fields = ('order__order_number', 'operation', 'work_center')
    ordering = ('order__order_number', 'sequence')

    def get_serializer_save_kwargs(self):
        return {'recorded_by': self.request.user}


class ProductionLaborEntryViewSet(NonDestructiveProductionViewSet):
    queryset = ProductionLaborEntry.objects.select_related('order', 'operation_execution', 'user')
    serializer_class = ProductionLaborEntrySerializer
    audit_resource_name = 'production_labor_entry'
    audit_fields = (
        'order_id',
        'operation_execution_id',
        'user_id',
        'started_at',
        'ended_at',
        'duration_minutes',
    )
    filterset_fields = ('order', 'operation_execution', 'user')
    search_fields = ('order__order_number', 'role', 'user__username')
    ordering = ('order__order_number', 'started_at')
