from django.contrib import admin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin, ImmutableAuditAdminMixin
from compliance.models import (
    ComplianceChecklistItem,
    CriticalActionExecution,
    RecordStatusHistory,
    TransversalRequirementPolicy,
)


@admin.register(TransversalRequirementPolicy)
class TransversalRequirementPolicyAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = ('code', 'title', 'source_module', 'enforcement_level', 'is_active', 'owner')
    list_filter = ('source_module', 'enforcement_level', 'is_active')
    search_fields = ('code', 'title', 'description', 'owner__email')
    autocomplete_fields = ('owner',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(RecordStatusHistory)
class RecordStatusHistoryAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        'target_model',
        'target_record_id',
        'previous_status',
        'new_status',
        'source_module',
        'actor',
        'occurred_at',
    )
    list_filter = ('source_module', 'new_status', 'occurred_at')
    search_fields = (
        'target_model',
        'target_record_id',
        'previous_status',
        'new_status',
        'action',
        'reason',
        'actor__email',
    )
    autocomplete_fields = ('actor',)
    readonly_fields = ('occurred_at', 'created_at', 'updated_at')


@admin.register(CriticalActionExecution)
class CriticalActionExecutionAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        'action_code',
        'source_module',
        'status',
        'actor',
        'requires_transaction',
        'started_at',
        'completed_at',
    )
    list_filter = ('source_module', 'status', 'requires_transaction', 'started_at', 'completed_at')
    search_fields = (
        'action_code',
        'target_model',
        'target_record_id',
        'message',
        'error_message',
        'transaction_id',
        'actor__email',
    )
    autocomplete_fields = ('actor',)
    readonly_fields = (
        'action_code',
        'source_module',
        'target_model',
        'target_record_id',
        'status',
        'actor',
        'requires_transaction',
        'transaction_id',
        'message',
        'safe_context',
        'started_at',
        'completed_at',
        'error_message',
        'created_at',
        'updated_at',
    )


@admin.register(ComplianceChecklistItem)
class ComplianceChecklistItemAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('source_module', 'check_type', 'status', 'checked_by', 'checked_at')
    list_filter = ('source_module', 'check_type', 'status', 'checked_at')
    search_fields = ('source_module', 'check_type', 'evidence', 'checked_by__email')
    autocomplete_fields = ('checked_by',)
    readonly_fields = ('checked_at', 'created_at', 'updated_at')
