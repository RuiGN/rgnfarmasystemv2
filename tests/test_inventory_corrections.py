from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from inventory.models import StockBalance, StockLot, StockMovement, StockQualityStatus
from tests.test_inventory import create_stock_address, create_stock_item, grant_model_perms


@pytest.fixture
def stock_operation():
    unit, product = create_stock_item('CORRECTION')
    warehouse, location = create_stock_address('CORRECTION')
    lot = StockLot.objects.create(product=product, lot_number='CORRECTION')
    balance = StockBalance.objects.create(
        product=product,
        lot=lot,
        warehouse=warehouse,
        location=location,
        quality_status=StockQualityStatus.APPROVED,
        quantity=Decimal('10'),
        unit=unit,
    )
    user = get_user_model().objects.create_user(
        username='stock-correction', email='stock-correction@example.test'
    )
    grant_model_perms(user, StockMovement)
    client = APIClient()
    client.force_authenticate(user)
    payload = {
        'movement_type': 'issue',
        'product': product.pk,
        'lot': lot.pk,
        'unit': unit.pk,
        'quantity': '3.0000',
        'quality_status': 'approved',
        'from_warehouse': warehouse.pk,
        'from_location': location.pk,
        'reason': 'Saída real',
    }
    return client, balance, payload


@pytest.mark.django_db
def test_generic_create_cannot_write_unposted_ledger(stock_operation):
    client, balance, payload = stock_operation
    response = client.post('/api/inventory/movements/', payload, format='json')
    assert response.status_code == 405, response.data
    balance.refresh_from_db()
    assert balance.quantity == Decimal('10')
    assert not StockMovement.objects.exists()


@pytest.mark.django_db
def test_ledger_rejects_patch_put_delete_and_admin_writes(stock_operation):
    from django.contrib.admin.sites import AdminSite
    from inventory.admin import StockMovementAdmin
    from inventory.serializers import StockMovementSerializer

    client, balance, payload = stock_operation
    movement = StockMovement.issue_stock(
        product=balance.product,
        lot=balance.lot,
        warehouse=balance.warehouse,
        location=balance.location,
        quantity=Decimal('3'),
        unit=balance.unit,
        reason='Saída',
    )
    response = client.patch(
        f'/api/inventory/movements/{movement.pk}/', {'quantity': '8'}, format='json'
    )
    assert response.status_code == 405
    assert (
        client.put(f'/api/inventory/movements/{movement.pk}/', payload, format='json').status_code
        == 405
    )
    assert client.delete(f'/api/inventory/movements/{movement.pk}/').status_code in {403, 405}
    serializer = StockMovementSerializer(movement, data={'quantity': '8'}, partial=True)
    assert not serializer.is_valid()
    model_admin = StockMovementAdmin(StockMovement, AdminSite())
    assert not model_admin.has_add_permission(None)
    assert not model_admin.has_change_permission(None, movement)
    assert not model_admin.has_delete_permission(None, movement)
    movement.refresh_from_db()
    balance.refresh_from_db()
    assert movement.quantity == Decimal('3')
    assert balance.quantity == Decimal('7')


@pytest.mark.django_db
def test_issue_operation_debits_and_audits_actor(stock_operation):
    client, balance, payload = stock_operation
    response = client.post('/api/inventory/movements/issue/', payload, format='json')
    assert response.status_code == 201, response.data
    balance.refresh_from_db()
    movement = StockMovement.objects.get(pk=response.data['id'])
    assert balance.quantity == Decimal('7')
    assert movement.quantity == Decimal('3')
    assert movement.created_by_id == client.handler._force_user.pk
    response = client.post(
        '/api/inventory/movements/issue/', {**payload, 'quantity': '8'}, format='json'
    )
    assert response.status_code == 400
    balance.refresh_from_db()
    assert balance.quantity == Decimal('7')
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_issue_rejects_wrong_unit_without_debit(stock_operation):
    from masters.models import UnitOfMeasure

    client, balance, payload = stock_operation
    unit = UnitOfMeasure.objects.create(code='INCOMPATIBLE', name='Outra', symbol='x')
    response = client.post(
        '/api/inventory/movements/issue/', {**payload, 'unit': unit.pk}, format='json'
    )
    assert response.status_code == 400, response.data
    balance.refresh_from_db()
    assert balance.quantity == Decimal('10')
    assert not StockMovement.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_issue_never_overdraws_postgresql(stock_operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    assert connection.vendor == 'postgresql'
    client, balance, payload = stock_operation
    user = client.handler._force_user
    gate = Barrier(2)

    def run():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            gate.wait(timeout=10)
            return api.post(
                '/api/inventory/movements/issue/', {**payload, 'quantity': '7'}, format='json'
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert sorted(results) == [201, 400]
    balance.refresh_from_db()
    assert balance.quantity == Decimal('3')
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_html_issue_collection_action_posts_with_add_permission_only(stock_operation):
    from django.contrib.auth.models import Permission
    from django.test import Client
    from django.urls import reverse
    from base.ui.actions.registry import action_registry

    api, balance, _ = stock_operation
    user = api.handler._force_user
    user.user_permissions.set(
        Permission.objects.filter(content_type__app_label='inventory', codename='add_stockmovement')
    )
    client = Client()
    client.force_login(user)
    url = reverse(
        'app:collection_action',
        kwargs=dict(module_slug='inventory', resource_slug='movements', action_name='issue'),
    )
    response = client.get(url)
    assert response.status_code == 200
    form = response.context['form']
    assert tuple(form.fields) == (
        'stock_balance',
        'quantity',
        'reference',
        'notes',
        'confirmation_acknowledged',
    )
    config = action_registry.get('inventory', 'movements', 'issue')
    assert config.permissions == ('inventory.add_stockmovement',)
    response = client.post(
        url,
        dict(
            stock_balance=balance.pk,
            quantity='3',
            reference='DOC-HTML',
            notes='Saída operacional HTML',
            confirmation_acknowledged='on',
        ),
    )
    assert response.status_code == 302, response.content.decode()
    assert response['Location'] == url
    assert client.get(response['Location']).status_code == 200
    balance.refresh_from_db()
    assert balance.quantity == Decimal('7')
    movement = StockMovement.objects.get()
    assert movement.created_by_id == user.pk
    assert movement.document_reference == 'DOC-HTML'
    assert movement.reason == 'Saída operacional HTML'
    assert movement.from_location_id == balance.location_id
    response = client.post(
        url,
        dict(
            stock_balance=balance.pk, quantity='8', notes='Excesso', confirmation_acknowledged='on'
        ),
    )
    assert response.status_code == 200
    assert 'quantity' in response.context['form'].errors
    balance.refresh_from_db()
    assert balance.quantity == Decimal('7')
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_balance_issue_api_returns_400_for_overdraw_and_refuses_dimension_tampering(
    stock_operation,
):
    client, balance, _ = stock_operation
    response = client.post(
        '/api/inventory/movements/issue/',
        dict(stock_balance=balance.pk, quantity='11', notes='Excesso'),
        format='json',
    )
    assert response.status_code == 400
    assert 'quantity' in response.data, response.data
    response = client.post(
        '/api/inventory/movements/issue/',
        dict(stock_balance=balance.pk, quantity='1', product=balance.product_id),
        format='json',
    )
    assert response.status_code == 400
    balance.refresh_from_db()
    assert balance.quantity == Decimal('10')
    assert not StockMovement.objects.exists()


@pytest.mark.django_db
def test_html_issue_preserves_permission_and_csrf_boundaries(stock_operation):
    from django.test import Client
    from django.urls import reverse

    api, balance, _ = stock_operation
    user = api.handler._force_user
    url = reverse(
        'app:collection_action',
        kwargs=dict(module_slug='inventory', resource_slug='movements', action_name='issue'),
    )
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(user)
    response = csrf_client.post(
        url, dict(stock_balance=balance.pk, quantity='1', confirmation_acknowledged='on')
    )
    assert response.status_code == 403
    user.user_permissions.clear()
    denied_client = Client()
    denied_client.force_login(user)
    assert denied_client.get(url).status_code == 403
    assert (
        denied_client.post(
            url, dict(stock_balance=balance.pk, quantity='1', confirmation_acknowledged='on')
        ).status_code
        == 403
    )
    anonymous_client = Client()
    assert anonymous_client.get(url).status_code == 302
    balance.refresh_from_db()
    assert balance.quantity == Decimal('10')
    assert not StockMovement.objects.exists()
