from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin

from documents.models import (
    ControlledDocument,
    DocumentApproval,
    DocumentAttachment,
    DocumentAuditTrail,
    DocumentDistribution,
    DocumentRelationship,
)


class SingleInstanceDocumentSerializerMixin(ModelSerializerContractMixin):
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


class ControlledDocumentSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = ControlledDocument
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'submitted_by',
            'submitted_at',
            'reviewed_by',
            'reviewed_at',
            'approved_by',
            'approved_at',
            'published_by',
            'published_at',
            'obsoleted_by',
            'obsoleted_at',
            'obsolete_reason',
            'cancelled_by',
            'cancelled_at',
            'cancel_reason',
            'archived_by',
            'archived_at',
            'archive_reason',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'owner',
            'submitted_by',
            'reviewed_by',
            'approved_by',
            'published_by',
            'obsoleted_by',
            'cancelled_by',
            'archived_by',
        ):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DocumentAttachmentSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DocumentAttachment
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DocumentRelationshipSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DocumentRelationship
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DocumentApprovalSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DocumentApproval
        fields = '__all__'
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DocumentDistributionSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DocumentDistribution
        fields = '__all__'
        read_only_fields = (
            'id',
            'status',
            'distributed_by',
            'confirmed_by',
            'confirmed_at',
            'confirmation_text',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in ('recipient', 'distributed_by', 'confirmed_by'):
            pass
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class DocumentAuditTrailSerializer(
    SingleInstanceDocumentSerializerMixin, serializers.ModelSerializer
):
    class Meta:
        model = DocumentAuditTrail
        fields = '__all__'
        read_only_fields = (
            'id',
            'document',
            'action',
            'actor',
            'reason',
            'snapshot',
            'created_at',
            'updated_at',
        )
