from rest_framework import serializers

from base.serializer_mixins import ModelSerializerContractMixin, instance_for_clean
from base.aggregate_writes import WriterSerializerMixin
from masters.models import (
    BusinessPartner,
    MasterCategory,
    Product,
    Site,
    StorageLocation,
    UnitOfMeasure,
    Warehouse,
)


class SingleInstanceSerializerMixin(ModelSerializerContractMixin):
    def _instance_for_clean(self, attrs):
        return instance_for_clean(self.Meta.model, self.instance, attrs)

    def _run_model_clean(self, instance):
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            instance.full_clean(validate_unique=False)
        except DjangoValidationError as error:
            raise serializers.ValidationError(error.message_dict) from error

    def _validate_category_kind(self, attrs, field_name, expected_kind):
        category = attrs.get(field_name)
        if category and category.kind != expected_kind:
            raise serializers.ValidationError(
                {field_name: f'A categoria deve ser do tipo {expected_kind}.'}
            )


class UnitOfMeasureSerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = UnitOfMeasure
        fields = ('id', 'code', 'name', 'symbol', 'is_active', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


class MasterCategorySerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = MasterCategory
        fields = (
            'id',
            'code',
            'name',
            'kind',
            'parent',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        return attrs


class ProductSerializer(
    WriterSerializerMixin, SingleInstanceSerializerMixin, serializers.ModelSerializer
):
    is_operationally_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            'id',
            'code',
            'description',
            'item_type',
            'unit',
            'category',
            'product_line',
            'cosmetic_form',
            'application_area',
            'status',
            'storage_condition',
            'shelf_life_days',
            'requires_quality_release',
            'requires_approved_supplier',
            'fiscal_ncm',
            'fiscal_cest',
            'is_operationally_available',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'is_operationally_available',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        for field_name in (
            'unit',
            'category',
            'product_line',
            'cosmetic_form',
            'application_area',
        ):
            pass
        self._validate_category_kind(attrs, 'category', MasterCategory.Kind.CATEGORY)
        self._validate_category_kind(attrs, 'product_line', MasterCategory.Kind.PRODUCT_LINE)
        self._validate_category_kind(attrs, 'cosmetic_form', MasterCategory.Kind.COSMETIC_FORM)
        self._validate_category_kind(
            attrs, 'application_area', MasterCategory.Kind.APPLICATION_AREA
        )
        return attrs


class BusinessPartnerSerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    is_qualification_valid = serializers.BooleanField(read_only=True)
    is_operationally_available = serializers.BooleanField(read_only=True)

    class Meta:
        model = BusinessPartner
        fields = (
            'id',
            'code',
            'legal_name',
            'trade_name',
            'document',
            'partner_type',
            'qualification_status',
            'qualification_valid_until',
            'email',
            'phone',
            'zipcode',
            'street',
            'street_number',
            'complement',
            'neighborhood',
            'state_ref',
            'city_ref',
            'is_active',
            'is_blocked',
            'is_qualification_valid',
            'is_operationally_available',
            'created_at',
            'updated_at',
        )
        read_only_fields = (
            'id',
            'is_qualification_valid',
            'is_operationally_available',
            'created_at',
            'updated_at',
        )

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class SiteSerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = (
            'id',
            'code',
            'name',
            'site_type',
            'zipcode',
            'street',
            'street_number',
            'complement',
            'neighborhood',
            'state_ref',
            'city_ref',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        self._run_model_clean(self._instance_for_clean(attrs))
        return attrs


class WarehouseSerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = Warehouse
        fields = (
            'id',
            'site',
            'code',
            'name',
            'warehouse_type',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        return attrs


class StorageLocationSerializer(SingleInstanceSerializerMixin, serializers.ModelSerializer):
    class Meta:
        model = StorageLocation
        fields = (
            'id',
            'warehouse',
            'code',
            'name',
            'is_active',
            'created_at',
            'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        return attrs
