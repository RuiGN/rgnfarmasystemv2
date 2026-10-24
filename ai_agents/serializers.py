from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from ai_agents.models import AIAgentProfile, AIAgentRun, AIInsightSuggestion, AIPromptAuditLog


class SingleInstanceAISerializerMixin(ModelSerializerContractMixin):
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
        instance._state.db = self.instance._state.db
        return instance

    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            if hasattr(error, 'message_dict'):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error


class AIAgentProfileSerializer(SingleInstanceAISerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AIAgentProfile
        fields = '__all__'
        read_only_fields = ('id', 'created_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AIAgentRunSerializer(SingleInstanceAISerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AIAgentRun
        fields = '__all__'
        read_only_fields = (
            'id',
            'run_number',
            'execution_mode',
            'celery_task_name',
            'task_id',
            'status',
            'graph_engine',
            'prompt_text',
            'model_name',
            'output_payload',
            'output_text',
            'error_message',
            'requested_by',
            'started_at',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AIInsightSuggestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIInsightSuggestion
        fields = '__all__'
        read_only_fields = (
            'id',
            'run',
            'suggestion_type',
            'title',
            'description',
            'confidence',
            'status',
            'source_module',
            'source_model',
            'source_record_id',
            'reviewed_by',
            'reviewed_at',
            'review_comments',
            'created_at',
            'updated_at',
        )


class AIPromptAuditLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = AIPromptAuditLog
        fields = '__all__'
        read_only_fields = (
            'id',
            'run',
            'agent',
            'user',
            'prompt_text',
            'model_name',
            'input_payload',
            'output_payload',
            'output_text',
            'status',
            'error_message',
            'occurred_at',
            'created_at',
            'updated_at',
        )


class AIAgentRunRequestSerializer(serializers.Serializer):
    source_module = serializers.ChoiceField(choices=AIAgentProfile.SourceModule.choices)
    source_model = serializers.CharField(max_length=120)
    source_record_id = serializers.CharField(max_length=120)
    input_payload = serializers.DictField(default=dict)
    run_immediately = serializers.BooleanField(default=False)
    dispatch = serializers.BooleanField(default=False)
