from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from inventory.models import StockBalance, StockMovement
from production.models import ProductionOrder
from production.services import ProductionOrderOperations
from tests.test_inventory import grant_model_perms
from tests import test_production_operations as production_fixtures

allocation_fixture = production_fixtures.allocated_consumption
production_order = production_fixtures.production_order
stock_address = production_fixtures.stock_address
stock_lot = production_fixtures.stock_lot


@pytest.fixture
def reserved_order(allocation_fixture):
    item = allocation_fixture
    for field in ('reserved_quantity', 'issued_quantity', 'loss_quantity', 'returned_quantity'):
        setattr(item, field, Decimal('0'))
    item.save()
    balance = StockBalance.objects.create(
        product=item.material,
        lot=item.stock_lot,
        warehouse=item.warehouse,
        location=item.location,
        unit=item.unit,
        quality_status='approved',
        quantity=Decimal('100'),
    )
    user = get_user_model().objects.create_user(
        username='cancel-correction', email='cancel@example.test'
    )
    item.order.approve(user)
    ProductionOrderOperations(item.order, user).reserve_materials()
    grant_model_perms(user, ProductionOrder)
    client = APIClient()
    client.force_authenticate(user)
    return client, item, balance, user


@pytest.mark.django_db
def test_cancel_api_releases_reservation_with_linked_compensation(reserved_order):
    client, item, balance, _ = reserved_order
    url = f'/api/production/orders/{item.order_id}/cancel/'
    response = client.post(url, {'cancel_reason': 'Cancelamento operacional'}, format='json')
    assert response.status_code == 200, response.data
    balance.refresh_from_db()
    assert balance.reserved_quantity == Decimal('0')
    assert balance.quantity == Decimal('100')
    item.refresh_from_db()
    movement = StockMovement.objects.get(movement_type='release_reservation')
    assert movement.related_movement_id == item.reservation_movement_id
    assert item.return_movement_id == movement.pk
    assert item.returned_quantity == Decimal('10')
    assert movement.source_production_order_id == item.order_id
    assert client.post(url, {'cancel_reason': 'Retry'}, format='json').status_code == 200
    assert StockMovement.objects.filter(movement_type='release_reservation').count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_cancel_releases_once_postgresql(reserved_order):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection
    from governance.models import GovernanceAuditLog

    assert connection.vendor == 'postgresql'
    client, item, balance, user = reserved_order
    gate = Barrier(2)

    def run():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            gate.wait(timeout=10)
            return api.post(
                f'/api/production/orders/{item.order_id}/cancel/',
                {'cancel_reason': 'Concurrent'},
                format='json',
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results == [200, 200]
    balance.refresh_from_db()
    assert balance.quantity == Decimal('100')
    assert balance.reserved_quantity == Decimal('0')
    assert StockMovement.objects.filter(movement_type='release_reservation').count() == 1
    assert GovernanceAuditLog.objects.filter(action='production.order.cancelled').count() == 1


@pytest.mark.django_db
def test_cancel_missing_reserve_balance_rolls_back(reserved_order):
    client, item, balance, user = reserved_order
    StockBalance.objects.filter(pk=balance.pk).update(reserved_quantity=Decimal('0'))
    response = client.post(
        f'/api/production/orders/{item.order_id}/cancel/',
        {'cancel_reason': 'Invalid'},
        format='json',
    )
    assert response.status_code == 400
    item.order.refresh_from_db()
    assert item.order.status == 'approved'
    assert not StockMovement.objects.filter(movement_type='release_reservation').exists()


@pytest.mark.django_db
def test_cancel_only_releases_unconsumed_reserve(reserved_order):
    client, item, balance, user = reserved_order
    item.refresh_from_db()
    item.actual_quantity = Decimal('4')
    movement = StockMovement.issue_reserved_stock(consumption=item, user=user)
    item.issue_movement = movement
    item.issued_quantity = Decimal('4')
    item.save()
    response = client.post(
        f'/api/production/orders/{item.order_id}/cancel/',
        {'cancel_reason': 'Partial'},
        format='json',
    )
    assert response.status_code == 200, response.data
    balance.refresh_from_db()
    assert balance.quantity == Decimal('96')
    assert balance.reserved_quantity == Decimal('0')
    release = StockMovement.objects.get(movement_type='release_reservation')
    assert release.quantity == Decimal('6')
    item.refresh_from_db()
    assert item.returned_quantity == Decimal('6')


@pytest.mark.django_db(transaction=True)
def test_cancel_serializes_with_reserve_operation(reserved_order):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections
    from django.core.exceptions import ValidationError

    client, item, balance, user = reserved_order
    gate = Barrier(2)

    def run(cancel):
        close_old_connections()
        try:
            order = ProductionOrder.objects.get(pk=item.order_id)
            gate.wait(timeout=10)
            if cancel:
                order.cancel('Race', user)
                return 'cancelled'
            try:
                ProductionOrderOperations(order, user).reserve_materials()
                return 'reserved'
            except ValidationError:
                return 'rejected'
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, cancel) for cancel in (True, False)]
        results = [future.result(timeout=30) for future in futures]
    assert results[0] == 'cancelled'
    assert results[1] in {'reserved', 'rejected'}
    balance.refresh_from_db()
    item.order.refresh_from_db()
    assert item.order.status == 'cancelled'
    assert balance.quantity == Decimal('100')
    assert balance.reserved_quantity == Decimal('0')
    assert StockMovement.objects.filter(movement_type='reservation').count() == 1
    assert StockMovement.objects.filter(movement_type='release_reservation').count() == 1


@pytest.mark.django_db
def test_stale_consumption_notes_cannot_restore_cancelled_reservation(reserved_order):
    from django.core.exceptions import ValidationError
    from production.models import MaterialConsumption

    _, item, balance, user = reserved_order
    stale = MaterialConsumption.objects.get(pk=item.pk)
    item.order.cancel('Cancelled before edit', user)
    stale.notes = 'Late notes'
    with pytest.raises(ValidationError):
        stale.save()
    item.refresh_from_db()
    balance.refresh_from_db()
    assert item.returned_quantity == Decimal('10')
    assert item.return_movement_id
    assert balance.reserved_quantity == Decimal('0')


@pytest.mark.django_db(transaction=True)
def test_material_patch_serializes_after_cancel_without_stale_write(reserved_order, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections
    from production.models import MaterialConsumption
    from production.views import MaterialConsumptionViewSet

    _, item, balance, user = reserved_order
    grant_model_perms(user, MaterialConsumption)
    loaded = Event()
    proceed = Event()
    original = MaterialConsumptionViewSet.get_object

    def stale_object(view):
        obj = original(view)
        loaded.set()
        assert proceed.wait(10)
        return obj

    monkeypatch.setattr(MaterialConsumptionViewSet, 'get_object', stale_object)

    def run():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            return api.patch(
                f'/api/production/consumptions/{item.pk}/', {'notes': 'Late patch'}, format='json'
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            assert loaded.wait(10)
            item.order.cancel('Race cancellation', user)
        finally:
            proceed.set()
        assert future.result(timeout=15) == 400
    item.refresh_from_db()
    balance.refresh_from_db()
    assert item.returned_quantity == Decimal('10')
    assert item.return_movement_id
    assert balance.reserved_quantity == Decimal('0')


@pytest.mark.django_db
def test_generic_order_save_cannot_cancel_without_releasing_reserves(reserved_order):
    from django.core.exceptions import ValidationError

    _, item, balance, _ = reserved_order
    item.order.status = 'cancelled'
    with pytest.raises(ValidationError):
        item.order.save(update_fields=['status'])
    item.order.refresh_from_db()
    balance.refresh_from_db()
    assert item.order.status == 'approved'
    assert balance.reserved_quantity == Decimal('10')


def _admin_payload(request, model, obj):
    from django.contrib import admin

    form = admin.site._registry[model].get_form(request, obj)(instance=obj)
    payload = {}
    for name, field in form.fields.items():
        value = form[name].value()
        if value is not None:
            payload[name] = str(value)
    return payload


@pytest.mark.django_db
def test_admin_post_cannot_cancel_order_directly(reserved_order):
    from django.test import Client, RequestFactory

    _, item, balance, user = reserved_order
    user.is_staff = user.is_superuser = True
    user.save()
    request = RequestFactory().get('/')
    request.user = user
    payload = _admin_payload(request, ProductionOrder, item.order)
    payload.update(
        status='cancelled',
        cancel_reason='Forged cancellation',
        notes='Legitimate order notes',
        **{
            'material_consumptions-TOTAL_FORMS': '0',
            'material_consumptions-INITIAL_FORMS': '0',
            'material_consumptions-MIN_NUM_FORMS': '0',
            'material_consumptions-MAX_NUM_FORMS': '1000',
        },
    )
    client = Client()
    client.force_login(user)
    response = client.post(f'/admin/production/productionorder/{item.order_id}/change/', payload)
    assert response.status_code == 302, response.content.decode()
    item.order.refresh_from_db()
    assert item.order.notes == 'Legitimate order notes'
    balance.refresh_from_db()
    assert item.order.status == 'approved'
    assert balance.reserved_quantity == Decimal('10')
    assert not StockMovement.objects.filter(movement_type='release_reservation').exists()


@pytest.mark.django_db
@pytest.mark.parametrize('terminal', ['cancelled', 'completed', 'closed'])
def test_terminal_material_api_and_admin_edits_are_rejected(reserved_order, terminal):
    from django.test import Client
    from production.models import MaterialConsumption

    api, item, balance, user = reserved_order
    if terminal == 'cancelled':
        item.order.cancel('Terminal', user)
    else:
        ProductionOrder.objects.filter(pk=item.order_id).update(status=terminal)
    grant_model_perms(user, MaterialConsumption)
    response = api.patch(
        f'/api/production/consumptions/{item.pk}/', {'notes': 'Terminal mutation'}, format='json'
    )
    assert response.status_code == 400
    user.is_staff = user.is_superuser = True
    user.save()
    client = Client()
    client.force_login(user)
    response = client.post(
        f'/admin/production/materialconsumption/{item.pk}/change/', {'notes': 'Terminal mutation'}
    )
    assert response.status_code == 403
    item.refresh_from_db()
    assert item.notes != 'Terminal mutation'


@pytest.mark.django_db(transaction=True)
def test_legitimate_production_receipt_prelocks_entire_output_batch(reserved_order, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import close_old_connections, transaction, OperationalError
    from inventory import models as inventory_models
    from inventory.models import StockLot
    from production.models import ProductionOutput

    _, item, _, user = reserved_order
    order = item.order
    order.release(user)
    order.start(user)
    item.refresh_from_db()
    item.actual_quantity = Decimal('10')
    item.save(update_fields=['actual_quantity'])
    ProductionOrderOperations(order, user).issue_materials()
    outputs = [
        ProductionOutput.objects.create(
            order=order,
            product=order.product,
            unit=order.unit,
            warehouse=item.warehouse,
            location=item.location,
            lot_number=f'BATCH-{index}',
            planned_quantity=50,
            produced_quantity=50,
        )
        for index in (1, 2)
    ]
    output_balances = []
    for output in outputs:
        lot = StockLot.objects.create(
            product=order.product,
            lot_number=output.lot_number,
            quality_status='quarantine',
            source_production_order=order,
        )
        output_balances.append(
            StockBalance.objects.create(
                product=order.product,
                lot=lot,
                warehouse=item.warehouse,
                location=item.location,
                unit=order.unit,
                quality_status='quarantine',
                quantity=0,
            )
        )
    order.complete(Decimal('100'), user)
    sequence = inventory_models._sequence_code
    checked = []

    def can_lock_second_balance():
        close_old_connections()
        try:
            try:
                with transaction.atomic():
                    StockBalance.objects.select_for_update(nowait=True).get(
                        pk=output_balances[1].pk
                    )
                return True
            except OperationalError:
                return False
        finally:
            close_old_connections()

    def assert_batch_locked(*args, **kwargs):
        if not checked:
            with ThreadPoolExecutor(max_workers=1) as pool:
                assert not pool.submit(can_lock_second_balance).result(timeout=10)
            checked.append(True)
        return sequence(*args, **kwargs)

    monkeypatch.setattr(inventory_models, '_sequence_code', assert_batch_locked)
    received = ProductionOrderOperations(order, user).receive_outputs()
    assert checked == [True]
    assert [output.pk for output in received] == [output.pk for output in outputs]
    assert StockMovement.objects.filter(movement_type='production_receipt').count() == 2
    assert sum(
        StockBalance.objects.filter(product=order.product).values_list('quantity', flat=True)
    ) == Decimal('100')
