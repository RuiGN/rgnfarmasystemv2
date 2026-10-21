"""Saldos não podem ser apagados por interfaces genéricas de manutenção."""

from decimal import Decimal

import pytest
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIClient

from base.ui.registry import get_resource
from inventory.models import StockBalance, StockLot, StockMovement
from tests.test_inventory import create_stock_address, create_stock_item


@pytest.fixture
def posted_balance(db):
    unit, product = create_stock_item('P1-RETENTION')
    warehouse, location = create_stock_address('P1-RETENTION')
    lot = StockLot.objects.create(product=product, lot_number='P1-RETENTION')
    balance = StockBalance.objects.create(
        product=product,
        lot=lot,
        warehouse=warehouse,
        location=location,
        quality_status='approved',
        quantity=Decimal('10'),
        unit=unit,
    )
    movement = StockMovement.issue_stock(
        product=product,
        lot=lot,
        warehouse=warehouse,
        location=location,
        quantity=Decimal('3'),
        unit=unit,
        reason='Regressão de retenção',
    )
    return balance, movement


@pytest.fixture
def stock_admin(db):
    return get_user_model().objects.create_superuser(
        username='p1-stock-admin', email='p1-stock-admin@example.test'
    )


@pytest.mark.parametrize('prefix', ['/api/', '/api/v1/'])
def test_api_cannot_delete_posted_balance(posted_balance, stock_admin, prefix):
    balance, movement = posted_balance
    api = APIClient()
    api.force_authenticate(stock_admin)
    before_movements = StockMovement.objects.count()

    response = api.delete(f'{prefix}inventory/balances/{balance.pk}/')

    assert response.status_code in {403, 405}
    balance.refresh_from_db()
    assert balance.quantity == Decimal('7')
    assert StockMovement.objects.filter(pk=movement.pk).exists()
    assert StockMovement.objects.count() == before_movements


def test_html_cannot_delete_balance_even_for_superuser(posted_balance, stock_admin, client):
    balance, _ = posted_balance
    resource = get_resource('inventory', 'balances')
    assert not resource.can_delete(stock_admin)
    client.force_login(stock_admin)
    url = reverse(
        'app:resource_delete',
        kwargs={'module_slug': 'inventory', 'resource_slug': 'balances', 'pk': balance.pk},
    )
    assert client.get(url).status_code == 403
    assert client.post(url).status_code == 403
    assert StockBalance.objects.filter(pk=balance.pk).exists()


def test_admin_cannot_delete_balance_individually_or_in_bulk(posted_balance, stock_admin):
    balance, _ = posted_balance
    request = RequestFactory().get('/admin/inventory/stockbalance/')
    request.user = stock_admin
    model_admin = admin.site._registry[StockBalance]

    assert not model_admin.has_delete_permission(request, balance)
    assert 'delete_selected' not in model_admin.get_actions(request)
