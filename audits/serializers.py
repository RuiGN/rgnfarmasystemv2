from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from audits.models import (
    AuditChecklistItem,
    AuditEvidence,
    AuditFinding,
    AuditFindingLink,
    AuditFollowUpAction,
    AuditPlan,
    AuditProgram,
    AuditReport,
)


class SingleInstanceAuditSerializerMixin(ModelSerializerContractMixin):
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


class AuditProgramSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditProgram
        fields = '__all__'
        read_only_fields = ('id', 'program_number', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditPlanSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditPlan
        fields = '__all__'
        read_only_fields = (
            'id',
            'audit_number',
            'status',
            'actual_start',
            'actual_end',
            'submitted_by',
            'submitted_at',
            'started_by',
            'completed_by',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('program', 'supplier'):
            pass
        for field_name in (
            'lead_auditor',
            'submitted_by',
            'started_by',
            'completed_by',
            'closed_by',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditChecklistItemSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    answer = serializers.CharField(source='answer_text', read_only=True)

    class Meta:
        model = AuditChecklistItem
        fields = (
            'id',
            'audit',
            'section',
            'question',
            'requirement_reference',
            'required',
            'status',
            'answer',
            'answered_by',
            'answered_at',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'status',
            'answer',
            'answered_by',
            'answered_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditFindingSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditFinding
        fields = '__all__'
        read_only_fields = ('id', 'status', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('audit', 'checklist_item'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditEvidenceSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditEvidence
        fields = '__all__'
        read_only_fields = ('id', 'uploaded_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('audit', 'finding'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditFollowUpActionSerializer(
    SingleInstanceAuditSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = AuditFollowUpAction
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'completion_notes',
            'evidence_reference',
            'content_hash',
            'completed_by',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('responsible', 'completed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditFindingLinkSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditFindingLink
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in (
            'finding',
            'capa',
            'deviation_event',
            'change_control',
            'supplier',
            'document',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class AuditReportSerializer(SingleInstanceAuditSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = AuditReport
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'total_findings',
            'critical_findings',
            'major_findings',
            'minor_findings',
            'opportunities',
            'total_checklist_items',
            'conform_items',
            'nonconform_items',
            'compliance_rate',
            'issued_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
