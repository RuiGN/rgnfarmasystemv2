from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

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


class SingleInstanceWorkflowSerializerMixin(ModelSerializerContractMixin):
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


class WorkflowNotificationSerializer(
    SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = WorkflowNotification
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'sent_at',
            'read_at',
            'archived_at',
            'error_message',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ApprovalQueueSerializer(SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ApprovalQueue
        fields = '__all__'
        read_only_fields = ('id', 'created_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ApprovalTaskSerializer(SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ApprovalTask
        fields = '__all__'
        read_only_fields = (
            'id',
            'task_number',
            'status',
            'requested_by',
            'decided_by',
            'decided_at',
            'decision_comments',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        if self.instance is not None:
            from rest_framework.exceptions import PermissionDenied

            try:
                self.instance.validate_sensitive_changes(
                    getattr(self.context.get('request'), 'user', None), attrs
                )
            except DjangoValidationError as error:
                raise PermissionDenied(error.message_dict) from error
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class WorkflowDelegationSerializer(
    SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = WorkflowDelegation
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        from rest_framework.exceptions import PermissionDenied

        instance = self.instance or WorkflowDelegation(**attrs)
        try:
            instance.validate_actor(getattr(self.context.get('request'), 'user', None), attrs)
        except DjangoValidationError as error:
            raise PermissionDenied(error.message_dict) from error
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class WorkflowCommentSerializer(SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = WorkflowComment
        fields = '__all__'
        read_only_fields = ('id', 'author', 'created_at', 'updated_at')

    def validate(self, attrs):
        attrs_for_clean = dict(attrs)
        if self.instance is None:
            attrs_for_clean['author'] = self.context['request'].user
        self._run_model_clean(self._instance_for_clean(attrs_for_clean))
        return attrs


class WorkflowAttachmentSerializer(
    SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = WorkflowAttachment
        fields = '__all__'
        read_only_fields = ('id', 'uploaded_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AsyncJobStatusSerializer(SingleInstanceWorkflowSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AsyncJobStatus
        fields = '__all__'
        read_only_fields = (
            'id',
            'job_number',
            'task_id',
            'status',
            'progress_percent',
            'message',
            'requested_by',
            'started_at',
            'completed_at',
            'result_reference',
            'error_message',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class WorkflowHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkflowHistory
        fields = '__all__'
        read_only_fields = (
            'id',
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
