"""O produto identifica o lote e não pode mudar após o cadastro."""

import pytest
from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIClient

from base.ui.forms import build_resource_form
from base.ui.registry import get_resource
from inventory.models import StockLot
from tests import test_p1_stock_balance_retention as stock_fixtures
from tests.test_inventory import create_stock_item

posted_balance = stock_fixtures.posted_balance
stock_admin = stock_fixtures.stock_admin


@pytest.fixture
def lot_change(posted_balance):
    balance, movement = posted_balance
    _, other_product = create_stock_item('P1-OTHER')
    return balance.lot, other_product, balance, movement


@pytest.mark.parametrize('prefix', ['/api/', '/api/v1/'])
def test_api_cannot_change_product_of_posted_lot(lot_change, stock_admin, prefix):
    lot, other_product, balance, movement = lot_change
    original_product = lot.product_id
    api = APIClient()
    api.force_authenticate(stock_admin)

    response = api.patch(
        f'{prefix}inventory/lots/{lot.pk}/', {'product': other_product.pk}, format='json'
    )

    assert response.status_code == 400
    assert 'product' in response.data
    lot.refresh_from_db()
    balance.refresh_from_db()
    movement.refresh_from_db()
    assert lot.product_id == balance.product_id == movement.product_id == original_product


@pytest.mark.parametrize('operation', ['full_clean', 'save'])
def test_model_rejects_product_change(lot_change, operation):
    lot, other_product, balance, _ = lot_change
    lot.product = other_product

    with pytest.raises(ValidationError) as error:
        getattr(lot, operation)()

    assert 'product' in error.value.message_dict
    lot.refresh_from_db()
    assert lot.product_id == balance.product_id


def test_product_is_immutable_even_before_first_movement(db):
    _, product = create_stock_item('P1-UNUSED')
    _, other_product = create_stock_item('P1-UNUSED-OTHER')
    lot = StockLot.objects.create(product=product, lot_number='P1-UNUSED')
    lot.product = other_product
    with pytest.raises(ValidationError):
        lot.save(update_fields=['product'])


def test_html_update_ignores_forged_product_and_preserves_notes(lot_change, stock_admin, client):
    lot, other_product, balance, _ = lot_change
    resource = get_resource('inventory', 'lots')
    assert 'product' in build_resource_form(resource)().fields
    assert 'product' not in build_resource_form(resource, update=True)(instance=lot).fields
    client.force_login(stock_admin)
    url = reverse(
        'app:resource_edit',
        kwargs={'module_slug': 'inventory', 'resource_slug': 'lots', 'pk': lot.pk},
    )
    response = client.post(
        url,
        {'product': other_product.pk, 'lot_number': lot.lot_number, 'notes': 'Nota autorizada'},
    )
    assert response.status_code == 302
    lot.refresh_from_db()
    assert lot.product_id == balance.product_id
    assert lot.notes == 'Nota autorizada'


def test_admin_product_is_readonly_only_after_creation(lot_change, stock_admin):
    lot, _, _, _ = lot_change
    request = RequestFactory().get('/admin/inventory/stocklot/')
    request.user = stock_admin
    model_admin = admin.site._registry[StockLot]
    assert 'product' in model_admin.get_readonly_fields(request, lot)
    assert 'product' not in model_admin.get_readonly_fields(request, None)


def test_notes_update_remains_available(lot_change, stock_admin):
    lot, _, balance, _ = lot_change
    api = APIClient()
    api.force_authenticate(stock_admin)
    response = api.patch(
        f'/api/inventory/lots/{lot.pk}/', {'notes': 'Observação legítima'}, format='json'
    )
    assert response.status_code == 200, response.data
    lot.refresh_from_db()
    assert lot.product_id == balance.product_id
    assert lot.notes == 'Observação legítima'
