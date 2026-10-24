from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from changes.models import (
    ChangeAction,
    ChangeAffectedItem,
    ChangeApproval,
    ChangeAssessment,
    ChangeControl,
    ChangeStockAssessment,
)


class SingleInstanceChangeSerializerMixin(ModelSerializerContractMixin):
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


class ChangeControlSerializer(SingleInstanceChangeSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ChangeControl
        fields = '__all__'
        read_only_fields = (
            'id',
            'change_number',
            'status',
            'requested_by',
            'submitted_by',
            'submitted_at',
            'approved_by',
            'approved_at',
            'implementation_started_by',
            'implementation_started_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'owner',
            'requested_by',
            'submitted_by',
            'approved_by',
            'implementation_started_by',
            'closed_by',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ChangeAffectedItemSerializer(
    SingleInstanceChangeSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ChangeAffectedItem
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in ('change', 'product', 'document', 'supplier'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ChangeAssessmentSerializer(SingleInstanceChangeSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ChangeAssessment
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'completed_by',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('assessor', 'completed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ChangeActionSerializer(SingleInstanceChangeSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ChangeAction
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


class ChangeApprovalSerializer(SingleInstanceChangeSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = ChangeApproval
        fields = '__all__'
        read_only_fields = (
            'id',
            'decision',
            'comments',
            'decided_by',
            'decided_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('approver', 'decided_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class ChangeStockAssessmentSerializer(
    SingleInstanceChangeSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ChangeStockAssessment
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'decision',
            'assessment_summary',
            'assessed_by',
            'assessed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('change', 'product', 'stock_lot'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
