from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from training.models import (
    Competency,
    CriticalActivityRule,
    JobPosition,
    TrainingEnrollment,
    TrainingIndicatorReport,
    TrainingMatrixRequirement,
    TrainingRequirement,
    TrainingSession,
    WorkFunction,
)


class SingleInstanceTrainingSerializerMixin(ModelSerializerContractMixin):
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


class JobPositionSerializer(SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = JobPosition
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class WorkFunctionSerializer(SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = WorkFunction
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CompetencySerializer(SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Competency
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')


class TrainingRequirementSerializer(
    SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = TrainingRequirement
        ref_name = 'PeopleTrainingRequirement'
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('job_position', 'function', 'competency', 'document'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class TrainingMatrixRequirementSerializer(
    SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = TrainingMatrixRequirement
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('job_position', 'function', 'competency', 'requirement'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class TrainingSessionSerializer(SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = TrainingSession
        fields = '__all__'
        read_only_fields = ('id', 'session_number', 'status', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class TrainingEnrollmentSerializer(
    SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer
):
    is_valid = serializers.BooleanField(read_only=True)

    class Meta:
        model = TrainingEnrollment
        fields = '__all__'
        read_only_fields = (
            'id',
            'enrollment_number',
            'status',
            'convoked_by',
            'convoked_at',
            'started_by',
            'started_at',
            'completed_by',
            'completed_at',
            'score',
            'evidence_reference',
            'content_hash',
            'approved_by',
            'approved_at',
            'valid_until',
            'recertification_due_date',
            'certificate_number',
            'certificate_reference',
            'failure_reason',
            'revoked_by',
            'revoked_at',
            'revocation_reason',
            'is_valid',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('requirement', 'session'):
            pass
        for field_name in (
            'user',
            'convoked_by',
            'started_by',
            'completed_by',
            'approved_by',
            'revoked_by',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class CriticalActivityRuleSerializer(
    SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = CriticalActivityRule
        ref_name = 'PeopleTrainingCriticalActivityRule'
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class TrainingIndicatorReportSerializer(
    SingleInstanceTrainingSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = TrainingIndicatorReport
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'total_required',
            'total_completed',
            'total_valid',
            'overdue_trainings',
            'due_soon_trainings',
            'compliance_rate',
            'content_reference',
            'generated_by',
            'generated_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('job_position', 'function'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
