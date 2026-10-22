from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from base.permissions import SingleInstanceDjangoModelPermissions

User = get_user_model()


def grant_model_perm(user, model, action):
    permission = Permission.objects.get(
        content_type__app_label=model._meta.app_label,
        content_type__model=model._meta.model_name,
        codename=f'{action}_{model._meta.model_name}',
    )
    user.user_permissions.add(permission)
    for cache_name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
        if hasattr(user, cache_name):
            delattr(user, cache_name)


def test_custom_post_action_requires_change_instead_of_add_permission(db):
    from masters.models import Product

    user = User.objects.create_user(
        username='Action Permission User',
        email='action.permission@example.com',
        password='S3curePass!123',
    )
    permission = SingleInstanceDjangoModelPermissions()
    request = SimpleNamespace(method='POST', user=user)
    view = SimpleNamespace(action='create', queryset=Product.objects.none())

    grant_model_perm(user, Product, 'add')
    assert permission.has_permission(request, view) is True

    view.action = 'approve'
    assert permission.has_permission(request, view) is False

    grant_model_perm(user, Product, 'change')
    assert permission.has_permission(request, view) is True


def test_custom_post_action_honors_explicit_source_and_target_permissions(db):
    from documents.models import ControlledDocument

    user = User.objects.create_user(
        username='Revision Permission User',
        email='revision.permission@example.com',
        password='S3curePass!123',
    )
    request = SimpleNamespace(method='POST', user=user)
    view = SimpleNamespace(
        action='create_revision',
        detail=True,
        queryset=ControlledDocument.objects.none(),
        action_permission_map={
            'create_revision': (
                'documents.change_controlleddocument',
                'documents.add_controlleddocument',
            )
        },
    )
    permission = SingleInstanceDjangoModelPermissions()

    grant_model_perm(user, ControlledDocument, 'change')
    assert permission.has_permission(request, view) is False

    grant_model_perm(user, ControlledDocument, 'add')
    assert permission.has_permission(request, view) is True


def test_collection_post_action_requires_add_permission(db):
    from finance.models import CashFlowEntry
    from finance.views import CashFlowEntryViewSet

    user = User.objects.create_user(
        username='Collection Action User',
        email='collection.action@example.com',
        password='S3curePass!123',
    )
    request = SimpleNamespace(method='POST', user=user)
    view = SimpleNamespace(
        action='from_title',
        detail=False,
        queryset=CashFlowEntry.objects.none(),
        action_permission_map=CashFlowEntryViewSet.action_permission_map,
    )
    permission = SingleInstanceDjangoModelPermissions()

    grant_model_perm(user, CashFlowEntry, 'change')
    assert permission.has_permission(request, view) is False

    grant_model_perm(user, CashFlowEntry, 'add')
    assert permission.has_permission(request, view) is True


class MasterDataModelTests(TestCase):
    def test_product_code_is_unique_globally(self):
        from masters.models import Product, UnitOfMeasure

        unit = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        other_unit = UnitOfMeasure.objects.create(
            code='KG-999',
            name='Quilograma',
            symbol='kg',
        )

        Product.objects.create(
            code='MP-001',
            description='Amido farmacêutico',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=unit,
            status=Product.Status.APPROVED,
        )

        duplicate = Product(
            code='MP-001',
            description='Amido duplicado',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        with pytest.raises(ValidationError):
            duplicate.full_clean()

        duplicate_from_secondary_unit = Product(
            code='MP-001',
            description='Amido com unidade secundaria',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=other_unit,
            status=Product.Status.APPROVED,
        )
        with pytest.raises(ValidationError):
            duplicate_from_secondary_unit.full_clean()

    def test_product_operational_availability_depends_on_approval_and_active_unit(self):
        from masters.models import Product, UnitOfMeasure

        unit = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')
        approved = Product.objects.create(
            code='PA-001',
            description='Comprimido 500mg',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        blocked = Product.objects.create(
            code='PA-002',
            description='Comprimido bloqueado',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.BLOCKED,
        )

        assert approved.is_operationally_available is True
        assert blocked.is_operationally_available is False

        unit.is_active = False
        unit.save(update_fields=['is_active'])
        approved.refresh_from_db()
        assert approved.is_operationally_available is False

    def test_partner_operational_availability_depends_on_qualification_validity(self):
        from masters.models import BusinessPartner

        qualified = BusinessPartner.objects.create(
            code='FOR-001',
            legal_name='Fornecedor Qualificado Ltda',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
            qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
            qualification_valid_until=timezone.localdate() + timedelta(days=30),
        )
        expired = BusinessPartner.objects.create(
            code='FOR-002',
            legal_name='Fornecedor Vencido Ltda',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
            qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
            qualification_valid_until=timezone.localdate() - timedelta(days=1),
        )
        blocked = BusinessPartner.objects.create(
            code='FOR-003',
            legal_name='Fornecedor Bloqueado Ltda',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
            qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
            qualification_valid_until=timezone.localdate() + timedelta(days=30),
            is_blocked=True,
        )

        assert qualified.is_operationally_available is True
        assert expired.is_operationally_available is False
        assert blocked.is_operationally_available is False


@pytest.mark.django_db
class TestMasterDataApi:
    def test_product_api_requires_django_view_permission(self):
        from masters.models import Product, UnitOfMeasure

        unit = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        Product.objects.create(
            code='MP-001',
            description='Amido farmacêutico',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        client = APIClient()
        client.force_authenticate(user)

        response = client.get('/api/masters/products/')

        assert response.status_code == 403

    def test_product_api_uses_single_instance_global_scope(self):
        from masters.models import Product, UnitOfMeasure

        unit = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        other_unit = UnitOfMeasure.objects.create(
            code='KG-999',
            name='Quilograma',
            symbol='kg',
        )
        Product.objects.create(
            code='MP-001',
            description='Amido farmacêutico',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        Product.objects.create(
            code='MP-999',
            description='Item secundario',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=other_unit,
            status=Product.Status.APPROVED,
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        grant_model_perm(user, Product, 'view')
        client = APIClient()
        client.force_authenticate(user)

        response = client.get('/api/masters/products/')

        assert response.status_code == 200
        codes = {item['code'] for item in response.json()['results']}
        assert codes == {'MP-001', 'MP-999'}

    def test_product_api_create_requires_add_permission(self):
        from masters.models import MasterCategory, Product, UnitOfMeasure

        unit = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        other_unit = UnitOfMeasure.objects.create(
            code='UN',
            name='Unidade',
            symbol='un',
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        grant_model_perm(user, Product, 'view')
        client = APIClient()
        client.force_authenticate(user)

        denied = client.post(
            '/api/masters/products/',
            {
                'code': 'MP-009',
                'description': 'Sem permissao de criacao',
                'item_type': Product.ItemType.EXCIPIENT,
                'unit': unit.id,
                'status': Product.Status.APPROVED,
            },
        )

        assert denied.status_code == 403

        grant_model_perm(user, Product, 'add')

        response = client.post(
            '/api/masters/products/',
            {
                'code': 'MP-010',
                'description': 'Celulose microcristalina',
                'item_type': Product.ItemType.EXCIPIENT,
                'unit': unit.id,
                'status': Product.Status.APPROVED,
            },
        )

        assert response.status_code == 201
        created_product = response.json()
        assert created_product['code'] == f'PRD-{created_product["id"]}'

        valid_global_unit_response = client.post(
            '/api/masters/products/',
            {
                'code': 'MP-011',
                'description': 'Unidade global',
                'item_type': Product.ItemType.EXCIPIENT,
                'unit': other_unit.id,
                'status': Product.Status.APPROVED,
            },
        )

        assert valid_global_unit_response.status_code == 201
        other_product = valid_global_unit_response.json()
        assert other_product['code'] == f'PRD-{other_product["id"]}'

        wrong_kind = MasterCategory.objects.create(
            code='CAT-001',
            name='Categoria geral',
            kind=MasterCategory.Kind.CATEGORY,
        )
        invalid_kind_response = client.post(
            '/api/masters/products/',
            {
                'code': 'MP-012',
                'description': 'Forma inválida',
                'item_type': Product.ItemType.EXCIPIENT,
                'unit': unit.id,
                'cosmetic_form': wrong_kind.id,
                'status': Product.Status.APPROVED,
            },
        )

        assert invalid_kind_response.status_code == 400
        assert 'cosmetic_form' in invalid_kind_response.json()

    def test_product_taxonomy_uses_cosmetics_domain_names(self):
        from masters.models import MasterCategory, Product

        assert MasterCategory.Kind.PRODUCT_LINE == 'product_line'
        assert MasterCategory.Kind.COSMETIC_FORM == 'cosmetic_form'
        assert MasterCategory.Kind.APPLICATION_AREA == 'application_area'
        assert 'pharmaceutical_form' not in {field.name for field in Product._meta.fields}
        assert {'product_line', 'cosmetic_form', 'application_area'} <= {
            field.name for field in Product._meta.fields
        }
