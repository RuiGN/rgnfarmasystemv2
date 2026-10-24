from django.core.exceptions import ValidationError as DjangoValidationError
from files.selectors import accessible_protected_files
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from files.downloads import protected_file_client_metadata, protected_file_download_response
from files.models import (
    ProtectedFile,
    ProtectedFileAccessRule,
    ProtectedFileAuditTrail,
    SecureFileLink,
)
from files.serializers import (
    ProtectedFileAccessRuleSerializer,
    ProtectedFileAuditTrailSerializer,
    ProtectedFileSerializer,
    SecureFileLinkSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


def _validation_payload(error):
    if hasattr(error, 'message_dict'):
        return error.message_dict
    return {'detail': error.messages}


def _accessible_protected_files(user):
    return accessible_protected_files(user)


class SingleInstanceFileViewSet(viewsets.ModelViewSet):
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


class ProtectedFileViewSet(SingleInstanceFileViewSet):
    action_permission_map = {
        'generate_link': ('files.view_protectedfile', 'files.add_securefilelink'),
        'replace': ('files.change_protectedfile', 'files.add_protectedfile'),
        'record_view': (
            'files.view_protectedfile',
            'files.add_protectedfileaudittrail',
        ),
        'download': ('files.view_protectedfile',),
    }
    queryset = ProtectedFile.objects.select_related(
        'controlled_document',
        'fiscal_document',
        'quality_document',
        'financial_title',
        'responsible',
        'uploaded_by',
        'supersedes',
        'replaced_by',
        'deleted_by',
    )
    serializer_class = ProtectedFileSerializer
    filterset_fields = (
        'source_module',
        'source_model',
        'source_record_id',
        'file_type',
        'origin',
        'criticality',
        'confidentiality',
        'status',
        'responsible',
        'uploaded_by',
        'valid_until',
    )
    search_fields = (
        'file_number',
        'title',
        'description',
        'file_name',
        'file_reference',
        'content_hash',
        'source_model',
        'source_record_id',
    )
    ordering = ('-created_at', 'file_number')

    def perform_create(self, serializer):
        protected_file = serializer.save(uploaded_by=self.request.user)
        protected_file.record_audit(
            ProtectedFileAuditTrail.Action.UPLOAD,
            user=self.request.user,
            **protected_file_client_metadata(self.request),
            details={'file_reference': protected_file.file_reference},
        )

    def get_queryset(self):
        permission = 'view'
        if self.action == 'download':
            permission = 'download'
        elif self.action == 'generate_link':
            permission = (
                'download' if self.request.data.get('purpose', 'download') == 'download' else 'view'
            )
        accessible_ids = accessible_protected_files(self.request.user, permission).values('pk')
        return self.queryset.filter(pk__in=accessible_ids)

    def get_object(self):
        protected_file = super().get_object()
        if self.action in {'delete_secure', 'expire', 'replace'}:
            from rest_framework.exceptions import PermissionDenied

            if not protected_file.user_can_access(self.request.user, permission='manage'):
                raise PermissionDenied('Alteração de arquivo exige gestão do arquivo.')
        return protected_file

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        protected_file = self.get_object()
        try:
            return protected_file_download_response(
                protected_file,
                user=request.user,
                **protected_file_client_metadata(request),
            )
        except DjangoValidationError as error:
            return Response(_validation_payload(error), status=status.HTTP_403_FORBIDDEN)

    @action(detail=True, methods=['post'])
    def generate_link(self, request, pk=None):
        purpose = request.data.get('purpose', SecureFileLink.Purpose.DOWNLOAD)
        expires_in_minutes = request.data.get('expires_in_minutes', 15)
        return self._domain_action_response(
            lambda protected_file: protected_file.generate_secure_link(
                user=request.user,
                purpose=purpose,
                expires_in_minutes=expires_in_minutes,
                **protected_file_client_metadata(request),
            ),
            serializer_class=SecureFileLinkSerializer,
            response_status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def replace(self, request, pk=None):
        return self._domain_action_response(
            lambda protected_file: protected_file.replace(
                new_file_reference=request.data.get('new_file_reference', ''),
                new_file_name=request.data.get('new_file_name', ''),
                content_hash=request.data.get('content_hash', ''),
                user=request.user,
                reason=request.data.get('reason', ''),
                file_size=request.data.get('file_size'),
                mime_type=request.data.get('mime_type', ''),
                content=request.FILES.get('file'),
            ),
            serializer_class=ProtectedFileSerializer,
            response_status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['post'])
    def delete_secure(self, request, pk=None):
        return self._domain_action_response(
            lambda protected_file: protected_file.delete_secure(
                reason=request.data.get('reason', ''), user=request.user
            )
        )

    @action(detail=True, methods=['post'])
    def expire(self, request, pk=None):
        return self._domain_action_response(
            lambda protected_file: protected_file.expire(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def record_view(self, request, pk=None):
        return self._domain_action_response(
            lambda protected_file: protected_file.record_access(
                user=request.user,
                action=ProtectedFileAuditTrail.Action.VIEW,
                **protected_file_client_metadata(request),
            ),
            serializer_class=ProtectedFileAuditTrailSerializer,
            response_status=status.HTTP_201_CREATED,
        )


class ProtectedFileAccessRuleViewSet(SingleInstanceFileViewSet):
    queryset = ProtectedFileAccessRule.objects.select_related('protected_file', 'user')
    serializer_class = ProtectedFileAccessRuleSerializer
    filterset_fields = (
        'protected_file',
        'rule_type',
        'user',
        'role',
        'source_module',
        'source_model',
        'source_record_id',
        'permission',
        'is_active',
    )
    search_fields = (
        'protected_file__file_number',
        'protected_file__title',
        'source_model',
        'source_record_id',
        'notes',
    )
    ordering = ('protected_file__file_number', 'rule_type', 'permission')

    def get_queryset(self):
        manageable_ids = accessible_protected_files(self.request.user, permission='manage').values(
            'pk'
        )
        return self.queryset.filter(protected_file_id__in=manageable_ids)

    def perform_destroy(self, instance):
        from rest_framework.exceptions import PermissionDenied

        if not instance.protected_file.user_can_access(self.request.user, permission='manage'):
            raise PermissionDenied('A remoção de ACL exige gestão do arquivo.')
        instance.delete()


class SecureFileLinkViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = SecureFileLink.objects.select_related('protected_file', 'requested_by', 'revoked_by')
    serializer_class = SecureFileLinkSerializer
    filterset_fields = ('protected_file', 'purpose', 'requested_by', 'expires_at', 'is_revoked')
    search_fields = ('protected_file__file_number', 'protected_file__title')
    ordering = ('-created_at',)

    def get_queryset(self):
        accessible_ids = _accessible_protected_files(self.request.user).values('pk')
        return self.queryset.filter(protected_file_id__in=accessible_ids)

    @action(detail=True, methods=['post'])
    def use(self, request, pk=None):
        secure_link = self.get_object()
        try:
            secure_link.use(
                user=request.user,
                **protected_file_client_metadata(request),
            )
        except DjangoValidationError as error:
            return Response(_validation_payload(error), status=status.HTTP_400_BAD_REQUEST)
        secure_link.refresh_from_db()
        return Response(
            {
                'file_name': secure_link.protected_file.file_name,
                'mime_type': secure_link.protected_file.mime_type,
                'purpose': secure_link.purpose,
                'used_at': secure_link.used_at,
                'use_count': secure_link.use_count,
            }
        )

    @action(detail=True, methods=['post'])
    def revoke(self, request, pk=None):
        secure_link = self.get_object()
        from rest_framework.exceptions import PermissionDenied

        if not secure_link.protected_file.user_can_access(request.user, permission='manage'):
            raise PermissionDenied('Revogação de link exige gestão do arquivo.')
        try:
            secure_link.revoke(reason=request.data.get('reason', ''), user=request.user)
        except DjangoValidationError as error:
            return Response(_validation_payload(error), status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(secure_link)
        return Response(serializer.data)


class ProtectedFileAuditTrailViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    queryset = ProtectedFileAuditTrail.objects.select_related(
        'protected_file', 'secure_link', 'actor'
    )
    serializer_class = ProtectedFileAuditTrailSerializer
    filterset_fields = ('protected_file', 'secure_link', 'action', 'actor', 'occurred_at')
    search_fields = (
        'protected_file__file_number',
        'protected_file__title',
        'actor__email',
        'user_agent',
        'details',
    )
    ordering = ('-occurred_at',)

    def get_queryset(self):
        accessible_ids = _accessible_protected_files(self.request.user).values('pk')
        return self.queryset.filter(protected_file_id__in=accessible_ids)
