from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from files.models import (
    ProtectedFile,
    ProtectedFileAccessRule,
    ProtectedFileAuditTrail,
    SecureFileLink,
)


class SingleInstanceFileSerializerMixin(ModelSerializerContractMixin):
    def _instance_for_clean(self, attrs):
        model = self.Meta.model
        if self.instance is None:
            return model(**attrs)
        values = {}
        for field in model._meta.concrete_fields:
            if field.primary_key:
                continue
            values[field.name] = attrs.get(field.name, getattr(self.instance, field.name))
        instance = model(**values)
        instance.pk = self.instance.pk
        instance._state.adding = False
        return instance

    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            if hasattr(error, 'message_dict'):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error


class ProtectedFileSerializer(SingleInstanceFileSerializerMixin, serializers.ModelSerializer):
    is_current = serializers.BooleanField(read_only=True)
    file_reference = serializers.CharField(write_only=True)

    class Meta:
        model = ProtectedFile
        fields = '__all__'
        read_only_fields = (
            'id',
            'file_number',
            'status',
            'uploaded_by',
            'uploaded_at',
            'replaced_by',
            'deleted_by',
            'deleted_at',
            'deletion_reason',
            'encryption_algorithm',
            'encryption_key_id',
            'encrypted_at',
            'encrypted_size',
            'is_current',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        if self.instance is not None:
            from rest_framework.exceptions import PermissionDenied

            user = getattr(self.context.get('request'), 'user', None)
            if not self.instance.user_can_access(user, permission='manage'):
                raise PermissionDenied('Alteração de arquivo exige gestão do arquivo.')
        for field_name in (
            'controlled_document',
            'fiscal_document',
            'quality_document',
            'financial_title',
            'supersedes',
            'replaced_by',
        ):
            pass
        for field_name in ('responsible', 'uploaded_by', 'deleted_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ProtectedFileAccessRuleSerializer(
    SingleInstanceFileSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ProtectedFileAccessRule
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        from rest_framework.exceptions import PermissionDenied

        request = self.context.get('request')
        user = getattr(request, 'user', None)
        targets = [attrs.get('protected_file')]
        if self.instance is not None:
            targets.append(self.instance.protected_file)
        for target in targets:
            if target is not None and not target.user_can_access(user, permission='manage'):
                raise PermissionDenied('A gestão da ACL exige permissão manage no arquivo alvo.')
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SecureFileLinkSerializer(SingleInstanceFileSerializerMixin, serializers.ModelSerializer):
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = SecureFileLink
        fields = '__all__'
        read_only_fields = (
            'id',
            'token',
            'requested_by',
            'use_count',
            'used_at',
            'is_revoked',
            'revoked_by',
            'revoked_at',
            'revocation_reason',
            'is_valid',
            'created_at',
            'updated_at',
        )

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        user = getattr(request, 'user', None)
        # O token em texto claro só é exibido ao solicitante do link.
        if not (
            user is not None
            and getattr(user, 'is_authenticated', False)
            and instance.requested_by_id == user.pk
        ):
            data.pop('token', None)
        return data

    def validate(self, attrs):
        for field_name in ('requested_by', 'revoked_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ProtectedFileAuditTrailSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProtectedFileAuditTrail
        fields = '__all__'
        read_only_fields = (
            'id',
            'protected_file',
            'secure_link',
            'action',
            'actor',
            'occurred_at',
            'ip_address',
            'user_agent',
            'details',
            'created_at',
            'updated_at',
        )

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        representation['details'] = _without_internal_references(representation.get('details', {}))
        return representation


def _without_internal_references(value):
    if type(value) is dict:
        return {
            key: _without_internal_references(item)
            for key, item in value.items()
            if key not in {'file_reference', 'result_reference', 'storage_path'}
        }
    if type(value) is list:
        return [_without_internal_references(item) for item in value]
    return value
