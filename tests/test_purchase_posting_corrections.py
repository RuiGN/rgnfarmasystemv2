from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from inventory.models import StockBalance, StockMovement
from procurement.models import PurchaseReceipt
from tests.test_inventory import (
    create_purchase_receipt_item,
    create_stock_address,
    grant_model_perms,
)


@pytest.fixture
def receipt_operation():
    _, _, _, item = create_purchase_receipt_item('POSTING')
    item.receipt.status = PurchaseReceipt.Status.QUALITY_RELEASED
    item.receipt.save()
    warehouse, location = create_stock_address('POSTING')
    user = get_user_model().objects.create_user(
        username='receipt-correction', email='receipt@example.test'
    )
    grant_model_perms(user, PurchaseReceipt)
    client = APIClient()
    client.force_authenticate(user)
    return client, item, {'warehouse': warehouse.pk, 'location': location.pk}


@pytest.mark.django_db
def test_api_post_stock_creates_real_entry_exactly_once(receipt_operation):
    client, item, payload = receipt_operation
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    response = client.post(url, payload, format='json')
    assert response.status_code == 200, response.data
    assert StockMovement.objects.filter(source_purchase_receipt_item=item).count() == 1
    balance = StockBalance.objects.get(product=item.product)
    assert balance.quantity == Decimal('48')
    assert balance.quality_status == 'approved'
    movement = StockMovement.objects.get(source_purchase_receipt_item=item)
    assert movement.created_by_id == client.handler._force_user.pk
    assert movement.lot.expiry_date == item.expiry_date
    assert client.post(url, payload, format='json').status_code == 200
    balance.refresh_from_db()
    assert balance.quantity == Decimal('48')
    assert StockMovement.objects.count() == 1
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'posted'


@pytest.mark.django_db
@pytest.mark.parametrize(
    'invalid',
    [
        'missing_lot',
        'unreconciled',
        'wrong_order',
        'wrong_unit',
        'expired',
        'cancelled',
        'inactive_location',
    ],
)
def test_invalid_receipt_never_marks_or_moves_stock(receipt_operation, invalid):
    from masters.models import UnitOfMeasure, StorageLocation
    from tests.test_inventory import create_purchase_receipt_item

    client, item, payload = receipt_operation
    if invalid == 'missing_lot':
        item.lot_number = ''
    elif invalid == 'unreconciled':
        item.accepted_quantity = Decimal('47')
    elif invalid == 'wrong_order':
        _, _, _, other = create_purchase_receipt_item('OTHER')
        item.order_item = other.order_item
    elif invalid == 'wrong_unit':
        item.unit = UnitOfMeasure.objects.create(code='OTHER', name='Other', symbol='x')
    elif invalid == 'expired':
        from datetime import timedelta
        from django.utils import timezone

        item.expiry_date = timezone.localdate() - timedelta(days=1)
    elif invalid == 'cancelled':
        item.receipt.status = 'cancelled'
        item.receipt.save()
    else:
        StorageLocation.objects.filter(pk=payload['location']).update(is_active=False)
    item.save()
    response = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
    )
    assert response.status_code == 400, response.data
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'pending'
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()


@pytest.mark.django_db
def test_posted_receipt_items_and_lifecycle_cannot_be_rewritten(receipt_operation):
    from django.core.exceptions import ValidationError

    client, item, payload = receipt_operation
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    assert client.post(url, payload, format='json').status_code == 200
    item.accepted_quantity = Decimal('40')
    with pytest.raises(ValidationError):
        item.save()
    item.refresh_from_db()
    assert item.accepted_quantity == Decimal('48')
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/mark_received/', {}, format='json'
        ).status_code
        == 400
    )
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/release_quality/',
            {'quality_status': 'rejected'},
            format='json',
        ).status_code
        == 400
    )


@pytest.mark.django_db
def test_retry_with_changed_destination_is_rejected(receipt_operation):
    client, item, payload = receipt_operation
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    assert client.post(url, payload, format='json').status_code == 200
    warehouse, location = create_stock_address('RETRY')
    response = client.post(url, {'warehouse': warehouse.pk, 'location': location.pk}, format='json')
    assert response.status_code == 400
    assert StockBalance.objects.get().quantity == Decimal('48')
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_existing_lot_conflict_rolls_back_every_item(receipt_operation):
    from inventory.models import StockLot
    from procurement.models import PurchaseReceiptItem

    client, item, payload = receipt_operation
    other = PurchaseReceiptItem.objects.create(
        receipt=item.receipt,
        order_item=item.order_item,
        product=item.product,
        unit=item.unit,
        received_quantity=Decimal('1'),
        accepted_quantity=Decimal('1'),
        lot_number='ZZ-CONFLICT',
        expiry_date=item.expiry_date,
    )
    StockLot.objects.create(
        product=item.product,
        lot_number=other.lot_number,
        quality_status='approved',
        supplier=item.receipt.order.supplier,
        expiry_date=None,
    )
    response = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
    )
    assert response.status_code == 400
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'pending'


@pytest.mark.django_db(transaction=True)
def test_concurrent_post_stock_accounts_once_postgresql(receipt_operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    assert connection.vendor == 'postgresql'
    client, item, payload = receipt_operation
    user = client.handler._force_user
    gate = Barrier(2)

    def run():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            gate.wait(timeout=10)
            return api.post(
                f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run) for _ in range(2)]
        results = [future.result(timeout=30) for future in futures]
    assert results == [200, 200]
    assert StockMovement.objects.count() == 1
    assert StockBalance.objects.get().quantity == Decimal('48')


@pytest.mark.django_db
def test_posted_receipt_generic_patch_returns_validation_not_server_error(receipt_operation):
    client, item, payload = receipt_operation
    url = f'/api/procurement/receipts/{item.receipt_id}/'
    assert client.post(url + 'post_stock/', payload, format='json').status_code == 200
    response = client.patch(url, {'fiscal_document_number': 'ADULTERADO'}, format='json')
    assert response.status_code == 400, response.data
    assert 'receipt' in response.data, response.data
    item.receipt.refresh_from_db()
    assert item.receipt.fiscal_document_number == 'NF-POSTING'


@pytest.mark.django_db
def test_legacy_posted_flag_without_ledger_is_not_silently_repaired(receipt_operation):
    client, item, payload = receipt_operation
    PurchaseReceipt.objects.filter(pk=item.receipt_id).update(
        status='stock_posted', stock_entry_status='posted'
    )
    response = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
    )
    assert response.status_code == 400
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()


@pytest.mark.django_db
def test_fully_rejected_item_is_not_deposited_with_accepted_items(receipt_operation):
    from procurement.models import PurchaseReceiptItem

    client, item, payload = receipt_operation
    PurchaseReceiptItem.objects.create(
        receipt=item.receipt,
        order_item=item.order_item,
        product=item.product,
        unit=item.unit,
        received_quantity=Decimal('1'),
        accepted_quantity=Decimal('0'),
        rejected_quantity=Decimal('1'),
    )
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    response = client.post(url, payload, format='json')
    assert response.status_code == 200, response.data
    assert StockMovement.objects.count() == 1
    assert StockBalance.objects.get().quantity == Decimal('48')
    assert client.post(url, payload, format='json').status_code == 200
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_receipt_helper_uses_locked_quantity_not_stale_instance(receipt_operation):
    from django.core.exceptions import ValidationError
    from masters.models import Warehouse, StorageLocation
    from procurement.models import PurchaseReceiptItem

    _, item, payload = receipt_operation
    PurchaseReceiptItem.objects.filter(pk=item.pk).update(
        accepted_quantity=Decimal('0'), rejected_quantity=Decimal('50')
    )
    with pytest.raises(ValidationError):
        StockMovement.receive_purchase_receipt_item(
            item,
            Warehouse.objects.get(pk=payload['warehouse']),
            StorageLocation.objects.get(pk=payload['location']),
            quality_status='approved',
        )
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_receipt_and_issue_take_balance_before_movement_sequence(receipt_operation, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections, connection
    from inventory import models as inventory_models
    from inventory.models import StockLot
    from masters.models import Warehouse, StorageLocation

    assert connection.vendor == 'postgresql'
    _, item, payload = receipt_operation
    warehouse = Warehouse.objects.get(pk=payload['warehouse'])
    location = StorageLocation.objects.get(pk=payload['location'])
    lot = StockLot.objects.create(
        product=item.product,
        lot_number=item.lot_number,
        quality_status='approved',
        supplier=item.receipt.order.supplier,
        expiry_date=item.expiry_date,
    )
    balance = StockBalance.objects.create(
        product=item.product,
        lot=lot,
        warehouse=warehouse,
        location=location,
        quality_status='approved',
        unit=item.unit,
        quantity=Decimal('100'),
    )
    issue_args = dict(
        product=item.product,
        lot=lot,
        warehouse=warehouse,
        location=location,
        unit=item.unit,
        quantity=Decimal('1'),
        reason='Initialize sequence',
    )
    StockMovement.issue_stock(**issue_args)
    receive_at_balance = Event()
    issue_at_sequence = Event()
    proceed = Event()
    increase = StockMovement._increase_balance
    sequence = inventory_models._sequence_code

    def paused_increase(cls, *args, **kwargs):
        receive_at_balance.set()
        assert proceed.wait(10)
        return increase(*args, **kwargs)

    def traced_sequence(*args, **kwargs):
        from threading import current_thread

        if current_thread().name.startswith('issue'):
            issue_at_sequence.set()
        return sequence(*args, **kwargs)

    monkeypatch.setattr(StockMovement, '_increase_balance', classmethod(paused_increase))
    monkeypatch.setattr(inventory_models, '_sequence_code', traced_sequence)

    def run(receive):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            if receive:
                return StockMovement.receive_purchase_receipt_item(
                    item, warehouse, location, quality_status='approved'
                ).pk
            return StockMovement.issue_stock(**{**issue_args, 'quantity': Decimal('5')}).pk
        finally:
            close_old_connections()

    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='receive') as receipts,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='issue') as issues,
    ):
        receipt_future = receipts.submit(run, True)
        assert receive_at_balance.wait(10)
        issue_future = issues.submit(run, False)
        try:
            assert issue_at_sequence.wait(10)
        finally:
            proceed.set()
        assert receipt_future.result(timeout=15)
        assert issue_future.result(timeout=15)
    balance.refresh_from_db()
    assert balance.quantity == Decimal('142')
    assert StockMovement.objects.count() == 3


@pytest.mark.django_db
def test_generic_receipt_save_cannot_mark_posted_without_ledger(receipt_operation):
    from django.core.exceptions import ValidationError

    _, item, _ = receipt_operation
    item.receipt.status = 'stock_posted'
    item.receipt.stock_entry_status = 'posted'
    with pytest.raises(ValidationError):
        item.receipt.save()
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'pending'
    assert not StockMovement.objects.exists()


@pytest.mark.django_db
def test_admin_post_cannot_mark_receipt_posted_without_ledger(receipt_operation):
    from django.test import Client, RequestFactory
    from tests.test_production_cancellation_corrections import _admin_payload

    _, item, _ = receipt_operation
    user = get_user_model().objects.create_superuser(
        username='receipt-admin', email='admin@example.test'
    )
    request = RequestFactory().get('/')
    request.user = user
    payload = _admin_payload(request, PurchaseReceipt, item.receipt)
    payload.update(
        status='stock_posted',
        stock_entry_status='posted',
        notes='Legitimate admin notes',
        **{
            'items-TOTAL_FORMS': '0',
            'items-INITIAL_FORMS': '0',
            'items-MIN_NUM_FORMS': '0',
            'items-MAX_NUM_FORMS': '1000',
        },
    )
    client = Client()
    client.force_login(user)
    response = client.post(f'/admin/procurement/purchasereceipt/{item.receipt_id}/change/', payload)
    assert response.status_code == 302, response.content.decode()
    item.receipt.refresh_from_db()
    assert item.receipt.notes == 'Legitimate admin notes'
    assert item.receipt.stock_entry_status == 'pending'
    assert item.receipt.status == 'quality_released'
    assert not StockMovement.objects.exists()


def _additional_receipt_item(
    item, *, same_receipt=False, accepted='48', rejected='0', lot='OTHER-LOT'
):
    from procurement.models import PurchaseReceiptItem

    receipt = (
        item.receipt
        if same_receipt
        else PurchaseReceipt.objects.create(
            order=item.receipt.order, quality_status='approved', status='quality_released'
        )
    )
    return PurchaseReceiptItem.objects.create(
        receipt=receipt,
        order_item=item.order_item,
        product=item.product,
        unit=item.unit,
        received_quantity=Decimal(accepted) + Decimal(rejected),
        accepted_quantity=Decimal(accepted),
        rejected_quantity=Decimal(rejected),
        lot_number=lot,
        expiry_date=item.expiry_date,
    )


@pytest.mark.django_db
def test_duplicate_order_items_in_one_receipt_cannot_overfulfil(receipt_operation):
    client, item, payload = receipt_operation
    _additional_receipt_item(item, same_receipt=True, accepted='3')
    response = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
    )
    assert response.status_code == 400, response.data
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'pending'


@pytest.mark.django_db(transaction=True)
def test_different_receipts_serialize_cumulative_accepted_quantity(receipt_operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    assert connection.vendor == 'postgresql'
    client, item, payload = receipt_operation
    other = _additional_receipt_item(item)
    user = client.handler._force_user
    gate = Barrier(2)

    def run(receipt_id):
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(user)
            gate.wait(10)
            return api.post(
                f'/api/procurement/receipts/{receipt_id}/post_stock/', payload, format='json'
            ).status_code
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, pk) for pk in (item.receipt_id, other.receipt_id)]
        assert sorted(future.result(timeout=20) for future in futures) == [200, 400]
    assert sum(StockBalance.objects.values_list('quantity', flat=True)) == Decimal('48')
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_rejected_quantity_does_not_fulfil_order_and_replacement_is_allowed(receipt_operation):
    client, item, payload = receipt_operation
    assert (
        client.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/', payload, format='json'
        ).status_code
        == 200
    )
    replacement = _additional_receipt_item(item, accepted='2')
    url = f'/api/procurement/receipts/{replacement.receipt_id}/post_stock/'
    assert client.post(url, payload, format='json').status_code == 200
    assert client.post(url, payload, format='json').status_code == 200
    excessive = _additional_receipt_item(item, accepted='1', lot='EXCESS')
    response = client.post(
        f'/api/procurement/receipts/{excessive.receipt_id}/post_stock/', payload, format='json'
    )
    assert response.status_code == 400
    assert sum(StockBalance.objects.values_list('quantity', flat=True)) == Decimal('50')
    assert StockMovement.objects.count() == 2


@pytest.mark.django_db
def test_html_post_stock_action_uses_address_choices_and_posts_real_balance(receipt_operation):
    from django.test import Client
    from django.urls import reverse
    from masters.models import StorageLocation, Warehouse
    from django import forms

    api, item, payload = receipt_operation
    user = api.handler._force_user
    grant_model_perms(user, Warehouse, StorageLocation)
    client = Client()
    client.force_login(user)
    url = reverse(
        'app:resource_action',
        kwargs=dict(
            module_slug='procurement',
            resource_slug='receipts',
            pk=item.receipt_id,
            action_name='post_stock',
        ),
    )
    response = client.get(url)
    assert response.status_code == 200
    form = response.context['form']
    assert isinstance(form.fields.get('warehouse'), forms.ModelChoiceField)
    assert isinstance(form.fields.get('location'), forms.ModelChoiceField)
    response = client.post(url, payload)
    assert response.status_code == 302, response.content.decode()
    assert StockBalance.objects.get().quantity == Decimal('48')
    assert StockMovement.objects.get().source_purchase_receipt_item_id == item.pk
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'posted'


@pytest.mark.django_db
def test_html_post_stock_rejects_mismatched_address_and_filters_inactive_choices(receipt_operation):
    from django.test import Client
    from django.urls import reverse
    from masters.models import StorageLocation, Warehouse

    api, item, payload = receipt_operation
    user = api.handler._force_user
    grant_model_perms(user, Warehouse, StorageLocation)
    other_warehouse, other_location = create_stock_address('BAD-ADDRESS')
    inactive_warehouse, inactive_location = create_stock_address('INACTIVE-ADDRESS')
    StorageLocation.objects.filter(pk=inactive_location.pk).update(is_active=False)
    Warehouse.objects.filter(pk=inactive_warehouse.pk).update(is_active=False)
    client = Client()
    client.force_login(user)
    url = reverse(
        'app:resource_action',
        kwargs=dict(
            module_slug='procurement',
            resource_slug='receipts',
            pk=item.receipt_id,
            action_name='post_stock',
        ),
    )
    response = client.get(url, {'warehouse': payload['warehouse']})
    assert response.status_code == 200
    form = response.context['form']
    assert not form.fields['warehouse'].queryset.filter(pk=inactive_warehouse.pk).exists()
    assert list(form.fields['location'].queryset.values_list('pk', flat=True)) == [
        payload['location']
    ]
    response = client.post(url, {**payload, 'location': other_location.pk})
    assert response.status_code == 200
    assert 'location' in response.context['form'].errors
    assert not StockBalance.objects.exists()
    assert not StockMovement.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_receipt_batch_locks_all_balances_before_first_sequence(receipt_operation, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread
    from time import monotonic, sleep
    from django.db import close_old_connections, connection
    from django.core.exceptions import ValidationError
    from inventory import models as inventory_models
    from inventory.models import StockLot
    from masters.models import Warehouse, StorageLocation
    from procurement.models import PurchaseOrderItem, PurchaseReceiptItem

    _, item, payload = receipt_operation
    warehouse = Warehouse.objects.get(pk=payload['warehouse'])
    location = StorageLocation.objects.get(pk=payload['location'])
    order_item = PurchaseOrderItem.objects.create(
        order=item.receipt.order,
        product=item.product,
        unit=item.unit,
        quantity=Decimal('10'),
        unit_price=1,
    )
    second = PurchaseReceiptItem.objects.create(
        receipt=item.receipt,
        order_item=order_item,
        product=item.product,
        unit=item.unit,
        lot_number='ZZ-BATCH',
        expiry_date=item.expiry_date,
        received_quantity=1,
        accepted_quantity=1,
    )
    balances = []
    for receipt_item in (item, second):
        lot = StockLot.objects.create(
            product=item.product,
            lot_number=receipt_item.lot_number,
            quality_status='approved',
            supplier=item.receipt.order.supplier,
            expiry_date=item.expiry_date,
        )
        balances.append(
            StockBalance.objects.create(
                product=item.product,
                lot=lot,
                warehouse=warehouse,
                location=location,
                unit=item.unit,
                quality_status='approved',
                quantity=100,
            )
        )
    StockMovement.issue_stock(
        product=item.product,
        lot=balances[0].lot,
        warehouse=warehouse,
        location=location,
        unit=item.unit,
        quantity=Decimal('1'),
        reason='Seed',
    )
    at_sequence, proceed, abort = Event(), Event(), Event()
    sequence = inventory_models._sequence_code

    def paused_sequence(*args, **kwargs):
        value = sequence(*args, **kwargs)
        if current_thread().name.startswith('receipt-batch') and not at_sequence.is_set():
            at_sequence.set()
            assert proceed.wait(10)
            if abort.is_set():
                raise ValidationError('Abort diagnostic transaction')
        return value

    monkeypatch.setattr(inventory_models, '_sequence_code', paused_sequence)

    def run(receive):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SET application_name = 'stock-review-batch-receive'"
                    if receive
                    else "SET application_name = 'stock-review-batch-issue'"
                )
                cursor.execute("SET lock_timeout = '8s'")
            if receive:
                item.receipt.post_stock(warehouse, location)
            else:
                StockMovement.issue_stock(
                    product=item.product,
                    lot=balances[1].lot,
                    warehouse=warehouse,
                    location=location,
                    unit=item.unit,
                    quantity=Decimal('5'),
                    reason='Concurrent issue',
                )
        finally:
            close_old_connections()

    with (
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='receipt-batch') as receipts,
        ThreadPoolExecutor(max_workers=1, thread_name_prefix='issue-batch') as issues,
    ):
        receiving = receipts.submit(run, True)
        assert at_sequence.wait(10)
        issuing = issues.submit(run, False)
        query = ''
        try:
            deadline = monotonic() + 5
            while monotonic() < deadline:
                with connection.cursor() as cursor:
                    cursor.execute(
                        'SELECT query FROM pg_stat_activity WHERE application_name = '
                        "'stock-review-batch-issue' AND wait_event_type = 'Lock'"
                    )
                    row = cursor.fetchone()
                if row:
                    query = row[0]
                    break
                sleep(0.01)
            assert 'inventory_stockbalance' in query, query
        except BaseException:
            abort.set()
            raise
        finally:
            proceed.set()
        receiving.result(timeout=15)
        issuing.result(timeout=15)
    for balance in balances:
        balance.refresh_from_db()
    assert [balance.quantity for balance in balances] == [Decimal('147'), Decimal('96')]


@pytest.mark.django_db
def test_posted_retry_does_not_rewrite_lot_disposition_or_repair_missing_balance(receipt_operation):
    from inventory.models import StockLot

    client, item, payload = receipt_operation
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    assert client.post(url, payload, format='json').status_code == 200
    StockLot.objects.filter(product=item.product).update(quality_status='blocked')
    StockBalance.objects.all().delete()
    assert client.post(url, payload, format='json').status_code == 200
    assert not StockBalance.objects.exists()
    assert StockMovement.objects.count() == 1
    assert StockLot.objects.get().quality_status == 'blocked'
