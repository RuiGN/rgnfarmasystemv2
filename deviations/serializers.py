from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin, incoming_value_changes_field

from deviations.models import (
    DeviationApproval,
    DeviationEvidence,
    DeviationImpactAssessment,
    DeviationInvestigation,
    DeviationLink,
    QualityEvent,
)


class SingleInstanceDeviationSerializerMixin(ModelSerializerContractMixin):
    immutable_update_fields: tuple[str, ...] = ()

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

    def _reject_immutable_on_update(self, data):
        immutable = [
            field_name
            for field_name in self.immutable_update_fields
            if self.instance is not None
            and field_name in data
            and incoming_value_changes_field(self.instance, field_name, data[field_name])
        ]
        if immutable:
            raise serializers.ValidationError(
                {
                    field_name: 'Campo de identidade imutável após a criação.'
                    for field_name in immutable
                }
            )

    def to_internal_value(self, data):
        self._reject_immutable_on_update(data)
        return serializers.ModelSerializer.to_internal_value(self, data)

    def _run_model_clean(self, instance):
        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            if hasattr(error, 'message_dict'):
                raise serializers.ValidationError(error.message_dict) from error
            raise serializers.ValidationError(error.messages) from error


class QualityEventSerializer(SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = QualityEvent
        fields = '__all__'
        read_only_fields = (
            'id',
            'event_number',
            'status',
            'opened_by',
            'opened_at',
            'closed_by',
            'closed_at',
            'closure_summary',
            'cancel_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        if (
            self.instance is not None
            and attrs
            and self.instance.status in {QualityEvent.Status.CLOSED, QualityEvent.Status.CANCELLED}
        ):
            raise serializers.ValidationError(
                {'status': 'Evento encerrado ou cancelado não pode ser editado.'}
            )
        for field_name in ('product', 'stock_lot', 'controlled_document', 'supplier', 'customer'):
            pass
        for field_name in ('responsible', 'opened_by', 'closed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DeviationEvidenceSerializer(
    SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DeviationEvidence
        fields = '__all__'
        read_only_fields = ('id', 'uploaded_by', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DeviationInvestigationSerializer(
    SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DeviationInvestigation
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'root_cause',
            'impact_conclusion',
            'conclusion',
            'concluded_by',
            'concluded_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('investigator', 'concluded_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DeviationImpactAssessmentSerializer(
    SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DeviationImpactAssessment
        fields = '__all__'
        read_only_fields = (
            'id',
            'is_completed',
            'completed_by',
            'completed_at',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('assessed_by', 'completed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DeviationApprovalSerializer(
    SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DeviationApproval
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

    immutable_update_fields = ('approver',)

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DeviationLinkSerializer(SingleInstanceDeviationSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = DeviationLink
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        for field_name in (
            'event',
            'customer_complaint',
            'quality_result',
            'stock_lot',
            'controlled_document',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs
