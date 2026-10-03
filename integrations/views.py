from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from integrations.models import (
    ApiCallLog,
    ApiClientApplication,
    IntegrationConnector,
    IntegrationEvent,
    LabelPrinterSettings,
)
from integrations.serializers import (
    ApiCallLogSerializer,
    ApiClientApplicationSerializer,
    IntegrationConnectorSerializer,
    IntegrationEventSerializer,
    LabelPrinterSettingsSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


class SingleInstanceIntegrationViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()

    def _domain_action_response(
        self, callback, serializer_class=None, response_status=status.HTTP_200_OK
    ):
        obj = self.get_object()
        try:
            result = callback(obj) or obj
        except DjangoValidationError as error:
            return Response(_validation_payload(error), status=status.HTTP_400_BAD_REQUEST)
        serializer = (serializer_class or self.get_serializer_class())(
            result, context=self.get_serializer_context()
        )
        return Response(serializer.data, status=response_status)


class LabelPrinterSettingsViewSet(SingleInstanceIntegrationViewSet):
    queryset = LabelPrinterSettings.objects.all()
    serializer_class = LabelPrinterSettingsSerializer
    filterset_fields = ('protocol', 'is_active')
    search_fields = ('name', 'host')
    ordering = ('name',)


class IntegrationConnectorViewSet(SingleInstanceIntegrationViewSet):
    queryset = IntegrationConnector.objects.select_related('responsible')
    serializer_class = IntegrationConnectorSerializer
    filterset_fields = ('provider_type', 'auth_type', 'status', 'is_active', 'responsible')
    search_fields = ('code', 'name', 'base_url', 'secret_reference', 'responsible__email')
    ordering = ('provider_type', 'code')

    def get_object(self):
        connector = super().get_object()
        if self.action in {'activate', 'suspend', 'test_success', 'test_failure', 'destroy'}:
            from rest_framework.exceptions import PermissionDenied

            try:
                connector.validate_fiscal_management(self.request.user, {})
            except DjangoValidationError as error:
                raise PermissionDenied(_validation_payload(error)) from error
        return connector

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        return self._domain_action_response(lambda connector: connector.activate(user=request.user))

    @action(detail=True, methods=['post'])
    def suspend(self, request, pk=None):
        return self._domain_action_response(
            lambda connector: connector.suspend(
                reason=request.data.get('reason', ''), user=request.user
            )
        )

    @action(detail=True, methods=['post'])
    def test_success(self, request, pk=None):
        return self._domain_action_response(
            lambda connector: connector.record_test_success(request.data.get('details') or {})
        )

    @action(detail=True, methods=['post'])
    def test_failure(self, request, pk=None):
        error_message = request.data.get('error_message') or ''
        if not error_message:
            self.get_object()
            return Response(
                {'error_message': ['Informe a mensagem de erro.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return self._domain_action_response(
            lambda connector: connector.record_test_failure(
                error_message, request.data.get('details') or {}
            )
        )


class ApiClientApplicationViewSet(SingleInstanceIntegrationViewSet):
    queryset = ApiClientApplication.objects.select_related('created_by')
    serializer_class = ApiClientApplicationSerializer
    filterset_fields = ('status', 'created_by', 'expires_at')
    search_fields = ('code', 'name', 'client_id', 'created_by__email')
    ordering = ('code',)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'])
    def rotate_secret(self, request, pk=None):
        return self._domain_action_response(
            lambda api_client: api_client.rotate_secret(
                request.data.get('secret') or '', user=request.user
            )
        )


class ApiCallLogViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = ApiCallLog.objects.select_related('user', 'client_application')
    serializer_class = ApiCallLogSerializer
    filterset_fields = (
        'api_version',
        'method',
        'path',
        'endpoint_name',
        'status_code',
        'outcome',
        'user',
        'client_application',
    )
    search_fields = ('request_id', 'path', 'endpoint_name', 'user__email', 'error_message')
    ordering = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()


class IntegrationEventViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = IntegrationEvent.objects.select_related(
        'connector', 'api_client_application', 'actor'
    )
    serializer_class = IntegrationEventSerializer
    filterset_fields = ('connector', 'api_client_application', 'event_type', 'actor', 'occurred_at')
    search_fields = (
        'connector__code',
        'connector__name',
        'api_client_application__code',
        'actor__email',
        'message',
    )
    ordering = ('-occurred_at',)

    def get_queryset(self):
        return self.queryset.all()
