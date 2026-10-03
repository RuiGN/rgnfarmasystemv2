from django.contrib import admin
from django.core.exceptions import PermissionDenied
from files.selectors import accessible_protected_files
from base.admin_mixins import GxpRetentionModelAdmin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin, ImmutableAuditAdminMixin
from files.models import (
    ProtectedFile,
    ProtectedFileAccessRule,
    ProtectedFileAuditTrail,
    SecureFileLink,
)


class FileObjectScopeAdminMixin(admin.ModelAdmin):
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        permission = 'manage' if self.model is ProtectedFileAccessRule else 'view'
        allowed = accessible_protected_files(request.user, permission).values('pk')
        lookup = 'pk__in' if self.model is ProtectedFile else 'protected_file_id__in'
        return queryset.filter(**{lookup: allowed})

    def has_change_permission(self, request, obj=None):
        allowed = super().has_change_permission(request, obj)
        target = obj if self.model is ProtectedFile else getattr(obj, 'protected_file', None)
        return allowed and (
            target is None or target.user_can_access(request.user, permission='manage')
        )

    def save_model(self, request, obj, form, change):
        targets = []
        if self.model is ProtectedFile:
            if change:
                targets.append(ProtectedFile.objects.get(pk=obj.pk))
            else:
                obj.uploaded_by = request.user
        else:
            targets.append(obj.protected_file)
            if change:
                targets.append(self.model.objects.get(pk=obj.pk).protected_file)
        if any(not target.user_can_access(request.user, permission='manage') for target in targets):
            raise PermissionDenied('A alteração administrativa exige gestão de ambos os arquivos.')
        super().save_model(request, obj, form, change)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.related_model is ProtectedFile:
            permission = 'manage' if self.model is ProtectedFileAccessRule else 'view'
            kwargs['queryset'] = accessible_protected_files(request.user, permission)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)


@admin.register(ProtectedFile)
class ProtectedFileAdmin(
    FileObjectScopeAdminMixin, AutomaticGeneratedFieldsAdminMixin, GxpRetentionModelAdmin
):
    list_display = (
        'file_number',
        'title',
        'source_module',
        'file_type',
        'status',
        'encryption_algorithm',
        'responsible',
        'uploaded_by',
        'valid_until',
    )
    list_filter = (
        'source_module',
        'file_type',
        'origin',
        'criticality',
        'confidentiality',
        'status',
        'encryption_algorithm',
        'valid_until',
    )
    search_fields = (
        'file_number',
        'title',
        'file_name',
        'file_reference',
        'content_hash',
        'source_model',
        'source_record_id',
    )
    autocomplete_fields = (
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
    readonly_fields = (
        'file_number',
        'encryption_algorithm',
        'encryption_key_id',
        'encrypted_at',
        'encrypted_size',
        'uploaded_at',
        'deleted_at',
        'created_at',
        'updated_at',
    )


@admin.register(ProtectedFileAccessRule)
class ProtectedFileAccessRuleAdmin(FileObjectScopeAdminMixin, GxpRetentionModelAdmin):
    list_display = (
        'protected_file',
        'rule_type',
        'permission',
        'user',
        'role',
        'source_module',
        'is_active',
    )
    list_filter = ('rule_type', 'permission', 'role', 'source_module', 'is_active')
    search_fields = (
        'protected_file__file_number',
        'protected_file__title',
        'user__email',
        'source_model',
        'source_record_id',
        'notes',
    )
    autocomplete_fields = ('protected_file', 'user')


@admin.register(SecureFileLink)
class SecureFileLinkAdmin(FileObjectScopeAdminMixin, GxpRetentionModelAdmin):
    list_display = (
        'protected_file',
        'purpose',
        'requested_by',
        'expires_at',
        'use_count',
        'max_uses',
        'is_revoked',
    )
    list_filter = ('purpose', 'expires_at', 'is_revoked')
    search_fields = (
        'protected_file__file_number',
        'protected_file__title',
        'token',
        'requested_by__email',
    )
    autocomplete_fields = ('protected_file', 'requested_by', 'revoked_by')
    readonly_fields = ('token', 'use_count', 'used_at', 'revoked_at', 'created_at', 'updated_at')


@admin.register(ProtectedFileAuditTrail)
class ProtectedFileAuditTrailAdmin(
    FileObjectScopeAdminMixin, ImmutableAuditAdminMixin, GxpRetentionModelAdmin
):
    list_display = ('protected_file', 'action', 'actor', 'occurred_at')
    list_filter = ('action', 'occurred_at')
    search_fields = (
        'protected_file__file_number',
        'protected_file__title',
        'actor__email',
        'user_agent',
        'details',
    )
    autocomplete_fields = ('protected_file', 'secure_link', 'actor')
    readonly_fields = (
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
