from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from masters.models import Product, UnitOfMeasure


User = get_user_model()


def grant_model_perms(user, *models):
    for model in models:
        content_type = ContentType.objects.get_for_model(model)
        permissions = Permission.objects.filter(
            content_type=content_type,
            codename__in=[
                f'view_{model._meta.model_name}',
                f'add_{model._meta.model_name}',
                f'change_{model._meta.model_name}',
                f'delete_{model._meta.model_name}',
            ],
        )
        user.user_permissions.add(*permissions)
    if hasattr(user, '_perm_cache'):
        del user._perm_cache
    if hasattr(user, '_user_perm_cache'):
        del user._user_perm_cache


def create_product_set(suffix='001'):
    unit = UnitOfMeasure.objects.create(
        code=f'KG-{suffix}',
        name='Quilograma',
        symbol='kg',
    )
    finished_product = Product.objects.create(
        code=f'PA-{suffix}',
        description='Comprimido 500mg',
        item_type=Product.ItemType.FINISHED_PRODUCT,
        unit=unit,
        status=Product.Status.APPROVED,
    )
    material = Product.objects.create(
        code=f'MP-{suffix}',
        description='Celulose microcristalina',
        item_type=Product.ItemType.EXCIPIENT,
        unit=unit,
        status=Product.Status.APPROVED,
    )
    return unit, finished_product, material


class FormulationModelTests(TestCase):
    def test_formula_code_version_is_unique_globally(self):
        from formulations.models import MasterFormula

        today = timezone.localdate()
        unit, product, _material = create_product_set()
        other_unit, other_product, _other_material = create_product_set(suffix='999')

        formula = MasterFormula.objects.create(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            expected_yield_percent=Decimal('98.5000'),
            status=MasterFormula.Status.APPROVED,
            effective_from=today,
        )

        assert formula.is_released is True
        assert formula.is_effective_on(today) is True

        duplicate = MasterFormula(
            product=product,
            code='F-PA-001-B',
            version=1,
            batch_size=Decimal('50.0000'),
            batch_unit=unit,
        )
        with pytest.raises(ValidationError):
            duplicate.full_clean()

        same_code_version_secondary_product = MasterFormula(
            product=other_product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=other_unit,
        )
        with pytest.raises(ValidationError):
            same_code_version_secondary_product.full_clean()

    def test_approved_formula_requires_available_product_and_valid_effective_period(self):
        from formulations.models import MasterFormula

        today = timezone.localdate()
        unit, product, _material = create_product_set()
        product.status = Product.Status.BLOCKED
        product.save(update_fields=['status'])

        formula = MasterFormula(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            expected_yield_percent=Decimal('99.0000'),
            status=MasterFormula.Status.APPROVED,
            effective_from=today,
            effective_to=today.replace(year=today.year - 1),
        )

        with pytest.raises(ValidationError) as error:
            formula.full_clean()

        assert 'product' in error.value.message_dict
        assert 'effective_to' in error.value.message_dict

    def test_formula_component_validates_material_status_and_loss_factor(self):
        from formulations.models import FormulaComponent, MasterFormula

        unit, product, material = create_product_set()
        _other_unit, _other_product, other_material = create_product_set(suffix='999')
        formula = MasterFormula.objects.create(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            status=MasterFormula.Status.APPROVED,
            effective_from=timezone.localdate(),
        )

        component = FormulaComponent(
            formula=formula,
            line_number=10,
            material=material,
            quantity=Decimal('10.0000'),
            unit=unit,
            expected_loss_percent=Decimal('5.0000'),
        )
        component.full_clean()
        assert component.planned_quantity_with_loss == Decimal('10.5000')

        secondary_material_component = FormulaComponent(
            formula=formula,
            line_number=20,
            material=other_material,
            quantity=Decimal('1.0000'),
            unit=unit,
        )
        secondary_material_component.full_clean()

    def test_route_requires_approved_formula_and_unique_step_sequence(self):
        from formulations.models import (
            FormulaComponent,
            ManufacturingRoute,
            MasterFormula,
            RouteStep,
        )

        today = timezone.localdate()
        unit, product, material = create_product_set()
        formula = MasterFormula.objects.create(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            status=MasterFormula.Status.APPROVED,
            effective_from=today,
        )
        FormulaComponent.objects.create(
            formula=formula,
            line_number=10,
            material=material,
            quantity=Decimal('10.0000'),
            unit=unit,
        )
        route = ManufacturingRoute.objects.create(
            product=product,
            formula=formula,
            code='R-PA-001',
            version=1,
            status=ManufacturingRoute.Status.APPROVED,
            effective_from=today,
        )
        RouteStep.objects.create(
            route=route,
            sequence=10,
            operation='Pesagem',
            work_center='Sala de pesagem',
            standard_time_minutes=Decimal('30.00'),
            critical_parameters='Balança calibrada; sala liberada.',
            instructions='Pesar matérias-primas conforme fórmula aprovada.',
        )

        assert route.is_released is True
        assert route.is_effective_on(today) is True

        duplicate_step = RouteStep(
            route=route,
            sequence=10,
            operation='Mistura',
            work_center='Misturador',
            standard_time_minutes=Decimal('45.00'),
        )
        with pytest.raises(ValidationError):
            duplicate_step.full_clean()


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestFormulationApi:
    def test_formula_api_uses_single_instance_global_scope(self):
        from formulations.models import MasterFormula

        unit, product, _material = create_product_set()
        other_unit, other_product, _other_material = create_product_set(suffix='999')
        MasterFormula.objects.create(
            product=other_product,
            code='F-OTHER',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=other_unit,
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        grant_model_perms(user, MasterFormula)
        client = APIClient()
        client.force_authenticate(user)

        create_response = client.post(
            '/api/formulations/formulas/',
            {
                'product': product.id,
                'code': 'F-PA-001',
                'version': 1,
                'batch_size': '100.0000',
                'batch_unit': unit.id,
                'expected_yield_percent': '98.5000',
                'status': MasterFormula.Status.DRAFT,
            },
        )

        assert create_response.status_code == 201
        created_formula = create_response.json()
        assert created_formula['code'] == f'MF-{created_formula["id"]}'

        list_response = client.get('/api/formulations/formulas/')

        assert list_response.status_code == 200
        assert {item['code'] for item in list_response.json()['results']} == {
            'F-OTHER',
            created_formula['code'],
        }

    def test_component_api_accepts_secondary_global_material(self):
        from formulations.models import FormulaComponent, MasterFormula

        unit, product, _material = create_product_set()
        _other_unit, _other_product, other_material = create_product_set(suffix='999')
        formula = MasterFormula.objects.create(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        grant_model_perms(user, FormulaComponent)
        client = APIClient()
        client.force_authenticate(user)

        response = client.post(
            '/api/formulations/components/',
            {
                'formula': formula.id,
                'line_number': 10,
                'material': other_material.id,
                'quantity': '1.0000',
                'unit': unit.id,
            },
        )

        assert response.status_code == 201
        assert response.json()['material'] == other_material.id

    @pytest.mark.permission_strict
    def test_route_api_requires_view_permission(self):
        from formulations.models import ManufacturingRoute, MasterFormula

        unit, product, _material = create_product_set()
        formula = MasterFormula.objects.create(
            product=product,
            code='F-PA-001',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            status=MasterFormula.Status.APPROVED,
            effective_from=timezone.localdate(),
        )
        ManufacturingRoute.objects.create(
            product=product,
            formula=formula,
            code='R-PA-001',
            version=1,
        )
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        client = APIClient()
        client.login(username=user.username, password='S3curePass!123')

        response = client.get('/api/formulations/routes/')

        assert response.status_code == 403
