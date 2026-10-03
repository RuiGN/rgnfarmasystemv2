from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin, ImmutableAuditAdminMixin
from workflow.models import (
    ApprovalQueue,
    ApprovalTask,
    AsyncJobStatus,
    WorkflowAttachment,
    WorkflowComment,
    WorkflowDelegation,
    WorkflowHistory,
    WorkflowNotification,
)


@admin.register(WorkflowNotification)
class WorkflowNotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'channel', 'recipient', 'status', 'criticality', 'due_at')
    list_filter = ('category', 'channel', 'status', 'source_module', 'criticality', 'due_at')
    search_fields = ('title', 'message', 'recipient__email', 'source_model', 'source_record_id')
    autocomplete_fields = ('recipient',)
    readonly_fields = (
        'sent_at',
        'read_at',
        'archived_at',
        'error_message',
        'created_at',
        'updated_at',
    )


@admin.register(ApprovalQueue)
class ApprovalQueueAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'module',
        'area',
        'profile_role',
        'criticality',
        'approval_limit',
        'is_active',
    )
    list_filter = ('module', 'profile_role', 'criticality', 'is_active')
    search_fields = ('code', 'name', 'area', 'description', 'created_by__email')
    autocomplete_fields = ('created_by',)


@admin.register(ApprovalTask)
class ApprovalTaskAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'task_number',
        'title',
        'queue',
        'status',
        'criticality',
        'requested_by',
        'assigned_to',
        'due_at',
    )
    list_filter = ('status', 'source_module', 'criticality', 'due_at')
    search_fields = (
        'task_number',
        'title',
        'description',
        'source_model',
        'source_record_id',
        'requested_by__email',
        'assigned_to__email',
    )
    autocomplete_fields = ('queue', 'requested_by', 'assigned_to', 'decided_by')
    readonly_fields = (
        'task_number',
        'requested_by',
        'status',
        'decided_by',
        'decided_at',
        'decision_comments',
        'created_at',
        'updated_at',
    )

    def save_model(self, request, obj, form, change):
        if change:
            previous = ApprovalTask.objects.get(pk=obj.pk)
            attrs = {field.name: getattr(obj, field.name) for field in obj._meta.concrete_fields}
            try:
                previous.validate_sensitive_changes(request.user, attrs)
            except ValidationError as error:
                raise PermissionDenied(error.message_dict) from error
        else:
            obj.requested_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(WorkflowDelegation)
class WorkflowDelegationAdmin(admin.ModelAdmin):
    def save_model(self, request, obj, form, change):
        previous = WorkflowDelegation.objects.get(pk=obj.pk) if change else obj
        try:
            previous.validate_actor(request.user, {'from_user': obj.from_user})
        except ValidationError as error:
            raise PermissionDenied(error.message_dict) from error
        super().save_model(request, obj, form, change)

    list_display = ('from_user', 'to_user', 'module', 'starts_at', 'ends_at', 'is_active')
    list_filter = ('module', 'starts_at', 'ends_at', 'is_active')
    search_fields = ('from_user__email', 'to_user__email', 'reason')
    autocomplete_fields = ('from_user', 'to_user')


@admin.register(WorkflowComment)
class WorkflowCommentAdmin(admin.ModelAdmin):
    list_display = ('task', 'author', 'is_internal', 'created_at')
    list_filter = ('is_internal', 'created_at')
    search_fields = ('task__task_number', 'task__title', 'author__email', 'comment')
    autocomplete_fields = ('task', 'author')


@admin.register(WorkflowAttachment)
class WorkflowAttachmentAdmin(admin.ModelAdmin):
    list_display = ('task', 'file_name', 'content_hash', 'uploaded_by')
    list_filter = ('uploaded_by',)
    search_fields = (
        'task__task_number',
        'task__title',
        'file_name',
        'file_reference',
        'content_hash',
    )
    autocomplete_fields = ('task', 'uploaded_by')


@admin.register(AsyncJobStatus)
class AsyncJobStatusAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'job_number',
        'title',
        'task_name',
        'status',
        'progress_percent',
        'requested_by',
    )
    list_filter = ('status', 'source_module', 'task_name')
    search_fields = (
        'job_number',
        'task_name',
        'task_id',
        'title',
        'loading_message',
        'message',
        'result_reference',
        'requested_by__email',
    )
    autocomplete_fields = ('requested_by',)
    readonly_fields = (
        'job_number',
        'started_at',
        'completed_at',
        'result_reference',
        'error_message',
        'created_at',
        'updated_at',
    )


@admin.register(WorkflowHistory)
class WorkflowHistoryAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('action', 'snapshot', 'actor', 'occurred_at')
    list_filter = ('action', 'occurred_at')
    search_fields = ('snapshot', 'actor__email', 'details')
    autocomplete_fields = ('task', 'notification', 'async_job', 'actor')
    readonly_fields = (
        'task',
        'notification',
        'async_job',
        'action',
        'actor',
        'occurred_at',
        'snapshot',
        'details',
        'created_at',
        'updated_at',
    )
