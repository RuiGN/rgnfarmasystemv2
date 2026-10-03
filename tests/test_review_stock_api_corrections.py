"""Regression tests for the final stock review API seams."""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework.exceptions import ValidationError as DRFValidationError

from inventory.models import StockBalance, StockMovement
from procurement.models import PurchaseOrderItem
from production.serializers import ProductionOrderSerializer
from tests import test_inventory_corrections as inventory_fixtures
from tests import test_production_cancellation_corrections as cancellation_fixtures
from tests import test_purchase_posting_corrections as purchase_fixtures
from tests.test_inventory import grant_model_perms

allocation_fixture = cancellation_fixtures.allocation_fixture
production_order = cancellation_fixtures.production_order
reserved_order = cancellation_fixtures.reserved_order
stock_address = cancellation_fixtures.stock_address
stock_lot = cancellation_fixtures.stock_lot
stock_operation = inventory_fixtures.stock_operation
receipt_operation = purchase_fixtures.receipt_operation


@pytest.mark.django_db
def test_cancelled_order_reason_patch_returns_400_preserving_metadata(reserved_order):
    client, item, balance, user = reserved_order
    url = f'/api/production/orders/{item.order_id}/'
    response = client.post(url + 'cancel/', {'cancel_reason': 'Original'}, format='json')
    assert response.status_code == 200, response.data
    item.order.refresh_from_db()
    original = (item.order.cancelled_at, item.order.cancelled_by_id)
    client.raise_request_exception = False
    response = client.patch(url, {'cancel_reason': 'Changed'}, format='json')
    assert response.status_code == 400
    item.order.refresh_from_db()
    assert item.order.status == 'cancelled'
    assert item.order.cancel_reason == 'Original'
    assert (item.order.cancelled_at, item.order.cancelled_by_id) == original
    balance.refresh_from_db()
    assert balance.quantity == Decimal('100')
    assert balance.reserved_quantity == Decimal('0')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'field,value', [('status', 'draft'), ('cancelled_at', None), ('cancelled_by', None)]
)
def test_cancelled_order_readonly_metadata_is_rejected_not_ignored(reserved_order, field, value):
    client, item, _, _ = reserved_order
    url = f'/api/production/orders/{item.order_id}/'
    assert (
        client.post(url + 'cancel/', {'cancel_reason': 'Original'}, format='json').status_code
        == 200
    )
    item.order.refresh_from_db()
    before = (
        item.order.status,
        item.order.cancel_reason,
        item.order.cancelled_at,
        item.order.cancelled_by_id,
    )
    response = client.patch(url, {field: value}, format='json')
    assert response.status_code == 400, response.data
    assert field in response.data
    item.order.refresh_from_db()
    assert (
        item.order.status,
        item.order.cancel_reason,
        item.order.cancelled_at,
        item.order.cancelled_by_id,
    ) == before


@pytest.mark.django_db
def test_order_patch_validated_before_cancel_rechecks_terminal_guard(reserved_order):
    _, item, _, user = reserved_order
    serializer = ProductionOrderSerializer(
        item.order, data={'cancel_reason': 'Changed'}, partial=True
    )
    assert serializer.is_valid(), serializer.errors
    item.order.__class__.objects.get(pk=item.order_id).cancel('Original', user)
    with pytest.raises(DRFValidationError):
        serializer.save()
    item.order.refresh_from_db()
    assert item.order.status == 'cancelled'
    assert item.order.cancel_reason == 'Original'


def sibling_balance(balance, status, quantity):
    return StockBalance.objects.create(
        product=balance.product,
        lot=balance.lot,
        warehouse=balance.warehouse,
        location=balance.location,
        unit=balance.unit,
        quality_status=status,
        quantity=Decimal(quantity),
    )


@pytest.mark.django_db
def test_issue_blocked_selected_id_never_debits_approved_sibling(stock_operation):
    client, approved, _ = stock_operation
    blocked = sibling_balance(approved, 'blocked', '10')
    response = client.post(
        '/api/inventory/movements/issue/',
        {'stock_balance': blocked.pk, 'quantity': '1'},
        format='json',
    )
    assert response.status_code == 400, response.data
    approved.refresh_from_db()
    blocked.refresh_from_db()
    assert approved.quantity == Decimal('10')
    assert blocked.quantity == Decimal('10')
    assert not StockMovement.objects.exists()


@pytest.mark.django_db
def test_issue_rechecks_selected_row_blocked_after_validation(stock_operation):
    from unittest.mock import patch

    from inventory.serializers import StockIssueSerializer

    client, selected, _ = stock_operation
    real_validate = StockIssueSerializer.is_valid
    other_ids = []

    def block_after_validation(serializer, **kwargs):
        result = real_validate(serializer, **kwargs)
        StockBalance.objects.filter(pk=selected.pk).update(quality_status='blocked')
        other_ids.append(sibling_balance(selected, 'approved', '7').pk)
        return result

    with patch.object(StockIssueSerializer, 'is_valid', block_after_validation):
        response = client.post(
            '/api/inventory/movements/issue/',
            {'stock_balance': selected.pk, 'quantity': '1'},
            format='json',
        )
    assert response.status_code == 400, response.data
    selected.refresh_from_db()
    assert selected.quality_status == 'blocked'
    assert selected.quantity == Decimal('10')
    assert StockBalance.objects.get(pk=other_ids[0]).quantity == Decimal('7')
    assert not StockMovement.objects.exists()


@pytest.mark.django_db
def test_order_item_quantity_cannot_fall_below_posted_accepted_http(receipt_operation):
    client, item, payload = receipt_operation
    grant_model_perms(client.handler._force_user, PurchaseOrderItem)
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
        ).status_code
        == 200
    )
    response = client.patch(
        f'/api/procurement/order-items/{item.order_item_id}/', {'quantity': '1'}, format='json'
    )
    assert response.status_code == 400, response.data
    assert 'quantity' in response.data
    item.order_item.refresh_from_db()
    assert item.order_item.quantity == Decimal('50')
    assert StockBalance.objects.get(product=item.product).quantity == Decimal('48')


@pytest.mark.django_db
@pytest.mark.parametrize('quantity', ['48', '49', '60'])
def test_order_item_quantity_at_or_above_accepted_remains_editable(receipt_operation, quantity):
    client, item, payload = receipt_operation
    grant_model_perms(client.handler._force_user, PurchaseOrderItem)
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
        ).status_code
        == 200
    )
    response = client.patch(
        f'/api/procurement/order-items/{item.order_item_id}/', {'quantity': quantity}, format='json'
    )
    assert response.status_code == 200, response.data
    item.order_item.refresh_from_db()
    assert item.order_item.quantity == Decimal(quantity)


@pytest.mark.django_db(transaction=True)
def test_order_item_http_rechecks_receipt_posted_after_validation(receipt_operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from unittest.mock import patch
    from django.db import close_old_connections, connection
    from procurement.serializers import PurchaseOrderItemSerializer

    assert connection.vendor == 'postgresql'
    client, item, payload = receipt_operation
    user = client.handler._force_user
    grant_model_perms(user, PurchaseOrderItem)
    validated, posted = Event(), Event()
    real_validate = PurchaseOrderItemSerializer.is_valid

    def wait_for_post(serializer, **kwargs):
        result = real_validate(serializer, **kwargs)
        validated.set()
        assert posted.wait(15)
        return result

    def edit_quantity():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            return api.patch(
                f'/api/procurement/order-items/{item.order_item_id}/',
                {'quantity': '1'},
                format='json',
            )
        finally:
            close_old_connections()

    with patch.object(PurchaseOrderItemSerializer, 'is_valid', wait_for_post):
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(edit_quantity)
            try:
                assert validated.wait(15)
                response = client.post(
                    f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
                    payload,
                    format='json',
                )
                assert response.status_code == 200, response.data
            finally:
                posted.set()
            result = future.result(timeout=20)
    assert result.status_code == 400, result.data
    item.order_item.refresh_from_db()
    assert item.order_item.quantity == Decimal('50')
    assert StockMovement.objects.get(source_purchase_receipt_item=item).quantity == Decimal('48')


@pytest.mark.django_db
def test_order_item_direct_save_rejects_quantity_below_accepted(receipt_operation):
    from django.core.exceptions import ValidationError

    client, item, payload = receipt_operation
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
        ).status_code
        == 200
    )
    item.order_item.quantity = Decimal('1')
    with pytest.raises(ValidationError):
        item.order_item.save(update_fields=['quantity', 'updated_at'])
    item.order_item.refresh_from_db()
    assert item.order_item.quantity == Decimal('50')


@pytest.mark.django_db
@pytest.mark.parametrize('pending_receipt', [False, True])
def test_order_item_without_posted_accepted_can_reduce_quantity(receipt_operation, pending_receipt):
    client, item, _ = receipt_operation
    grant_model_perms(client.handler._force_user, PurchaseOrderItem)
    if not pending_receipt:
        item.delete()
        item.receipt.delete()
    response = client.patch(
        f'/api/procurement/order-items/{item.order_item_id}/', {'quantity': '1'}, format='json'
    )
    assert response.status_code == 200, response.data
    item.order_item.refresh_from_db()
    assert item.order_item.quantity == Decimal('1')


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('first_writer', ['posting', 'quantity'])
def test_order_item_edit_and_posting_use_same_postgresql_lock(receipt_operation, first_writer):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic, sleep
    from django.db import close_old_connections, connection, transaction

    assert connection.vendor == 'postgresql'
    client, item, payload = receipt_operation
    user = client.handler._force_user
    grant_model_perms(user, PurchaseOrderItem)
    started = Event()
    worker_pid = []

    def edit(api):
        return api.patch(
            f'/api/procurement/order-items/{item.order_item_id}/', {'quantity': '1'}, format='json'
        )

    def post(api):
        return api.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
        )

    first, second = (post, edit) if first_writer == 'posting' else (edit, post)

    def run_second():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                worker_pid.append(cursor.fetchone()[0])
            api = APIClient()
            api.force_authenticate(user)
            started.set()
            return second(api)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with transaction.atomic():
            PurchaseOrderItem.objects.select_for_update(no_key=True).get(pk=item.order_item_id)
            future = pool.submit(run_second)
            assert started.wait(10)
            deadline = monotonic() + 10
            blocked = False
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute('SELECT cardinality(pg_blocking_pids(%s))', [worker_pid[0]])
                    blocked = cursor.fetchone()[0] > 0
                if blocked:
                    break
                if future.done():
                    break
                sleep(0.02)
            assert blocked, 'The competing HTTP write must wait on the shared PO-item lock'
            first_response = first(client)
            assert first_response.status_code == 200, first_response.data
        second_response = future.result(timeout=20)
    assert second_response.status_code == 400, second_response.data
    item.order_item.refresh_from_db()
    if first_writer == 'posting':
        assert item.order_item.quantity == Decimal('50')
        assert StockMovement.objects.get(source_purchase_receipt_item=item).quantity == Decimal(
            '48'
        )
    else:
        assert item.order_item.quantity == Decimal('1')
        assert not StockMovement.objects.exists()
        item.receipt.refresh_from_db()
        assert item.receipt.stock_entry_status == 'pending'


@pytest.mark.django_db
@pytest.mark.parametrize('selected_id', [True, False])
def test_issue_approved_selection_and_legacy_dimensions_work(stock_operation, selected_id):
    client, balance, legacy = stock_operation
    payload = (
        {'stock_balance': balance.pk, 'quantity': '1', 'reference': 'Review'}
        if selected_id
        else {
            key: value
            for key, value in legacy.items()
            if key not in {'movement_type', 'quality_status'}
        }
    )
    response = client.post('/api/inventory/movements/issue/', payload, format='json')
    assert response.status_code == 201, response.data
    balance.refresh_from_db()
    assert balance.quantity == (Decimal('9') if selected_id else Decimal('7'))
    assert response.data['quality_status'] == 'approved'
    if selected_id:
        assert response.data['document_reference'] == 'Review'


@pytest.mark.django_db
@pytest.mark.parametrize('mismatch', ['dimensions', 'unit'])
def test_issue_selected_id_revalidates_dimensions_and_unit(stock_operation, mismatch):
    from django.core.exceptions import ValidationError
    from tests.test_inventory import create_stock_address
    from masters.models import UnitOfMeasure

    _, balance, _ = stock_operation
    warehouse, location = balance.warehouse, balance.location
    unit = balance.unit
    if mismatch == 'dimensions':
        warehouse, location = create_stock_address('OTHER-DIMENSIONS')
    else:
        unit = UnitOfMeasure.objects.create(code='OTHER-UNIT', name='Other unit', symbol='x')
    with pytest.raises(ValidationError):
        StockMovement.issue_stock(
            product=balance.product,
            lot=balance.lot,
            warehouse=warehouse,
            location=location,
            unit=unit,
            quantity=Decimal('1'),
            reason='Review',
            stock_balance_id=balance.pk,
        )
    balance.refresh_from_db()
    assert balance.quantity == Decimal('10')
    assert not StockMovement.objects.exists()
