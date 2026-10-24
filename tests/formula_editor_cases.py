"""Shared HTTP fixtures for the standalone master formula editor.

Product and MasterFormula are separate resources: the product is a plain
``masters`` record and the formula is edited in ``formulations`` with its own
components inline. These helpers drive that surface, which is the only HTML
writer for the Product / MasterFormula / FormulaComponent aggregate.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from formulations.models import MasterFormula
from masters.models import Product, UnitOfMeasure


def url(pk=None):
    return reverse(
        'app:resource_edit' if pk else 'app:resource_create',
        kwargs={
            'module_slug': 'formulations',
            'resource_slug': 'formulas',
            **({'pk': pk} if pk else {}),
        },
    )


def product_url(pk=None):
    return reverse(
        'app:resource_edit' if pk else 'app:resource_create',
        kwargs={
            'module_slug': 'masters',
            'resource_slug': 'products',
            **({'pk': pk} if pk else {}),
        },
    )


@pytest.fixture
def case(client):
    user = get_user_model().objects.create_superuser('workflow-admin', 'workflow@example.com', None)
    client.force_login(user)
    unit = UnitOfMeasure.objects.create(code='WF-KG', name='Quilograma', symbol='kg')
    material = Product.objects.create(
        description='Material sintético', item_type='raw_material', unit=unit, status='approved'
    )
    product = Product.objects.create(
        description='Creme sintético', item_type='finished_product', unit=unit, status='approved'
    )
    payload = {
        'product': str(product.pk),
        'version': '1',
        'status': 'draft',
        'batch_size': '100',
        'batch_unit': str(unit.pk),
        'expected_yield_percent': '100',
        'notes': 'Observação preservada',
        'components-TOTAL_FORMS': '1',
        'components-INITIAL_FORMS': '0',
        'components-MIN_NUM_FORMS': '0',
        'components-MAX_NUM_FORMS': '1000',
        'components-0-line_number': '10',
        'components-0-material': str(material.pk),
        'components-0-role': 'excipient',
        'components-0-quantity': '5',
        'components-0-unit': str(unit.pk),
        'components-0-expected_loss_percent': '0',
        'components-0-conversion_factor': '1',
        'components-0-is_active': 'on',
    }
    return client, user, unit, material, payload


def existing_case(case):
    """An approved v1 and a draft v2 of the same product, plus the editor payload."""

    client, _, unit, _, payload = case
    product = Product.objects.create(
        description='Produto existente', item_type='finished_product', unit=unit, status='approved'
    )
    first = MasterFormula.objects.create(
        product=product,
        version=1,
        batch_size=100,
        batch_unit=unit,
        status='approved',
        effective_from='2026-01-01',
    )
    second = MasterFormula.objects.create(
        product=product, version=2, batch_size=200, batch_unit=unit
    )
    payload = dict(payload, product=str(product.pk), version='2', batch_size='200')
    return client, product, first, second, payload


def login_with(case, permissions):
    from django.contrib.auth.models import Permission

    client = case[0]
    user = get_user_model().objects.create_user('workflow-limited', 'limited@example.com')
    for name in permissions:
        app, codename = name.split('.')
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=codename)
        )
    client.force_login(user)
    return client


PRODUCT_PERMISSIONS = ['masters.view_product', 'masters.add_product', 'masters.change_product']
FORMULA_PERMISSIONS = [
    'formulations.view_masterformula',
    'formulations.add_masterformula',
    'formulations.change_masterformula',
]
COMPONENT_PERMISSIONS = [
    'formulations.view_formulacomponent',
    'formulations.add_formulacomponent',
    'formulations.change_formulacomponent',
]
