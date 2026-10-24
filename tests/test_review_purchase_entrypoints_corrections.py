"""Regressions for the three purchase-entrypoint review blockers."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from inventory.models import StockBalance, StockLot, StockMovement, StockQualityStatus
from masters.models import UnitOfMeasure
from procurement.models import PurchaseReceipt, PurchaseReceiptItem
from tests.test_inventory import create_purchase_receipt_item, create_stock_address


@pytest.fixture
def purchase_entry():
    _, _, _, item = create_purchase_receipt_item('ENTRY-REVIEW')
    warehouse, location = create_stock_address('ENTRY-REVIEW')
    return item, warehouse, location


@pytest.mark.django_db
@pytest.mark.parametrize(
    'invalid',
    [
        'cancelled',
        'pending_quality',
        'unreconciled',
        'wrong_order',
        'wrong_unit',
        'expired',
        'empty_lot',
    ],
)
def test_direct_approved_helper_validates_persisted_first_entry(purchase_entry, invalid):
    item, warehouse, location = purchase_entry
    # Keep the caller's objects stale: the guards must use locked database data.
    if invalid == 'cancelled':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(status='cancelled')
    elif invalid == 'pending_quality':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(quality_status='pending')
    elif invalid == 'unreconciled':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(accepted_quantity=Decimal('47'))
    elif invalid == 'wrong_order':
        _, _, _, other = create_purchase_receipt_item('OTHER-ENTRY')
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(order_id=other.receipt.order_id)
    elif invalid == 'wrong_unit':
        other_unit = UnitOfMeasure.objects.create(code='OTHER-ENTRY', name='Other', symbol='x')
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(unit=other_unit)
    elif invalid == 'expired':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            expiry_date=timezone.localdate() - timedelta(days=1)
        )
    else:
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(lot_number='')
    with pytest.raises(ValidationError):
        StockMovement.receive_purchase_receipt_item(
            item, warehouse, location, quality_status=StockQualityStatus.APPROVED
        )
    assert not StockMovement.objects.exists()
    assert not StockLot.objects.exists()
    assert not StockBalance.objects.exists()
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize('quality', ['pending', 'quarantine', 'approved'])
def test_default_helper_preserves_legitimate_quarantine(purchase_entry, quality):
    item, warehouse, location = purchase_entry
    PurchaseReceipt.objects.filter(pk=item.receipt_id).update(quality_status=quality)
    movement = StockMovement.receive_purchase_receipt_item(item, warehouse, location)
    assert movement.quality_status == StockQualityStatus.QUARANTINE
    assert StockBalance.objects.get().quantity == Decimal('48')
    assert StockLot.objects.get().quality_status == StockQualityStatus.QUARANTINE
    assert StockMovement.receive_purchase_receipt_item(item, warehouse, location).pk == movement.pk
    assert StockMovement.objects.count() == 1


@pytest.mark.django_db
def test_direct_approved_helper_preserves_valid_entry(purchase_entry):
    item, warehouse, location = purchase_entry
    movement = StockMovement.receive_purchase_receipt_item(
        item, warehouse, location, quality_status=StockQualityStatus.APPROVED
    )
    assert movement.quantity == Decimal('48')
    assert movement.document_reference == item.receipt.fiscal_document_number
    assert StockBalance.objects.get().quantity == Decimal('48')
    assert movement.lot.expiry_date == item.expiry_date


def _posting_client(item):
    from django.contrib.auth import get_user_model
    from rest_framework.test import APIClient
    from procurement.models import PurchaseOrderItem
    from tests.test_inventory import grant_model_perms

    user = get_user_model().objects.create_user(
        username='purchase-entry-review', email='entry-review@example.test'
    )
    grant_model_perms(user, PurchaseReceipt, PurchaseOrderItem)
    client = APIClient()
    client.force_authenticate(user)
    return client


def _destination(warehouse, location, target):
    return {'location': location, 'warehouse': warehouse, 'site': warehouse.site}[target]


@pytest.mark.django_db
@pytest.mark.parametrize('target', ['location', 'warehouse', 'site'])
@pytest.mark.parametrize('entrypoint', ['http', 'helper'])
def test_destination_inactivated_after_serializer_is_rejected(
    purchase_entry, monkeypatch, target, entrypoint
):
    from procurement.serializers import PurchaseReceiptStockPostingSerializer

    item, warehouse, location = purchase_entry
    destination = _destination(warehouse, location, target)
    if entrypoint == 'http':
        original = PurchaseReceiptStockPostingSerializer.is_valid

        def inactivate_after_validation(serializer, *args, **kwargs):
            result = original(serializer, *args, **kwargs)
            type(destination).objects.filter(pk=destination.pk).update(is_active=False)
            return result

        monkeypatch.setattr(
            PurchaseReceiptStockPostingSerializer, 'is_valid', inactivate_after_validation
        )
        response = _posting_client(item).post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
            {'warehouse': warehouse.pk, 'location': location.pk},
            format='json',
        )
        assert response.status_code == 400, response.data
    else:
        assert warehouse.site.is_active
        type(destination).objects.filter(pk=destination.pk).update(is_active=False)
        with pytest.raises(ValidationError):
            StockMovement.receive_purchase_receipt_item(
                item, warehouse, location, quality_status='approved'
            )
    assert not StockMovement.objects.exists()
    assert not StockLot.objects.exists()
    assert not StockBalance.objects.exists()
    item.receipt.refresh_from_db()
    assert item.receipt.stock_entry_status == 'pending'


def _wait_for_lock(application_name):
    from time import monotonic, sleep
    from django.db import connection

    deadline = monotonic() + 3
    while monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT query FROM pg_stat_activity '
                'WHERE application_name = %s AND wait_event_type = %s',
                [application_name, 'Lock'],
            )
            row = cursor.fetchone()
        if row:
            return row[0]
        sleep(0.01)
    return ''


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('target', ['location', 'warehouse', 'site'])
@pytest.mark.parametrize('entrypoint', ['batch', 'helper'])
def test_purchase_destination_locks_survive_external_transaction(
    purchase_entry, target, entrypoint
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections, connection, transaction

    assert connection.vendor == 'postgresql'
    item, warehouse, location = purchase_entry
    destination = _destination(warehouse, location, target)
    posted, release = Event(), Event()
    application_name = 'purchase-entry-destination-mutator'

    def post():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '8s'")
                if entrypoint == 'batch':
                    item.receipt.post_stock(warehouse, location)
                else:
                    StockMovement.receive_purchase_receipt_item(
                        item, warehouse, location, quality_status='approved'
                    )
                posted.set()
                assert release.wait(8)
        finally:
            close_old_connections()

    def mutate():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET LOCAL application_name = %s', [application_name])
                    cursor.execute("SET LOCAL lock_timeout = '8s'")
                return type(destination).objects.filter(pk=destination.pk).update(is_active=False)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        posting = pool.submit(post)
        try:
            assert posted.wait(8)
            mutation = pool.submit(mutate)
            query = _wait_for_lock(application_name)
            assert destination._meta.db_table in query, query
            assert not mutation.done()
        finally:
            release.set()
        posting.result(timeout=10)
        assert mutation.result(timeout=10) == 1
    destination.refresh_from_db()
    assert not destination.is_active
    assert StockMovement.objects.count() == 1
    assert StockBalance.objects.get().quantity == Decimal('48')


@pytest.mark.django_db(transaction=True)
def test_mutator_order_item_then_destination_is_compatible_with_posting(purchase_entry):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from django.db import close_old_connections, connection, transaction
    from masters.models import StorageLocation
    from procurement.models import PurchaseOrderItem

    assert connection.vendor == 'postgresql'
    item, warehouse, location = purchase_entry
    locked, release = Event(), Event()
    application_name = 'purchase-entry-orderitem-waiter'

    def mutate():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '8s'")
                PurchaseOrderItem.objects.select_for_update(no_key=True).get(pk=item.order_item_id)
                StorageLocation.objects.select_for_update().get(pk=location.pk)
                locked.set()
                assert release.wait(8)
                StorageLocation.objects.filter(pk=location.pk).update(is_active=False)
        finally:
            close_old_connections()

    def post():
        close_old_connections()
        try:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET LOCAL application_name = %s', [application_name])
                    cursor.execute("SET LOCAL lock_timeout = '8s'")
                with pytest.raises(ValidationError):
                    item.receipt.post_stock(warehouse, location)
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        mutation = pool.submit(mutate)
        try:
            assert locked.wait(8)
            posting = pool.submit(post)
            assert 'procurement_purchaseorderitem' in _wait_for_lock(application_name)
        finally:
            release.set()
        mutation.result(timeout=10)
        posting.result(timeout=10)
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('allowed_quantity', ['49', '48'])
def test_http_retry_after_allowed_order_quantity_patch_is_read_only(
    purchase_entry, allowed_quantity
):
    item, warehouse, location = purchase_entry
    client = _posting_client(item)
    payload = {'warehouse': warehouse.pk, 'location': location.pk}
    url = f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
    first = client.post(url, payload, format='json')
    assert first.status_code == 200, first.data
    movements = list(StockMovement.objects.values())
    balances = list(StockBalance.objects.values())
    lots = list(StockLot.objects.values())
    item.receipt.refresh_from_db()
    posted_at = item.receipt.updated_at
    response = client.patch(
        f'/api/procurement/order-items/{item.order_item_id}/',
        {'quantity': allowed_quantity},
        format='json',
    )
    assert response.status_code == 200, response.data
    response = client.post(url, payload, format='json')
    assert response.status_code == 200, response.data
    assert list(StockMovement.objects.values()) == movements
    assert list(StockBalance.objects.values()) == balances
    assert list(StockLot.objects.values()) == lots
    item.refresh_from_db()
    item.receipt.refresh_from_db()
    assert item.received_quantity == Decimal('50')
    assert item.accepted_quantity == Decimal('48')
    assert item.rejected_quantity == Decimal('2')
    assert item.receipt.updated_at == posted_at


@pytest.mark.django_db
@pytest.mark.parametrize('entrypoint', ['http', 'helper'])
@pytest.mark.parametrize(
    'change',
    ['quantity', 'lot', 'unit', 'quality', 'expiry', 'document', 'manufacturing', 'destination'],
)
def test_retry_confirms_historical_movement_not_changed_payload(purchase_entry, entrypoint, change):
    item, warehouse, location = purchase_entry
    item.receipt.post_stock(warehouse, location)
    movements = list(StockMovement.objects.values())
    balances = list(StockBalance.objects.values())
    if change == 'quantity':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            accepted_quantity=Decimal('47'), rejected_quantity=Decimal('3')
        )
    elif change == 'lot':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(lot_number='REWRITTEN')
    elif change == 'unit':
        unit = UnitOfMeasure.objects.create(code='RETRY-UNIT', name='Other', symbol='x')
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(unit=unit)
    elif change == 'quality':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(quality_status='pending')
    elif change == 'expiry':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            expiry_date=item.expiry_date + timedelta(days=1)
        )
    elif change == 'document':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(
            fiscal_document_number='REWRITTEN'
        )
    elif change == 'manufacturing':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            manufacturing_date=timezone.localdate()
        )
    else:
        warehouse, location = create_stock_address('RETRY-ENTRY')
    if entrypoint == 'http':
        response = _posting_client(item).post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
            {'warehouse': warehouse.pk, 'location': location.pk},
            format='json',
        )
        assert response.status_code == 400, response.data
    else:
        with pytest.raises(ValidationError):
            StockMovement.receive_purchase_receipt_item(
                item, warehouse, location, quality_status='approved'
            )
    assert list(StockMovement.objects.values()) == movements
    assert list(StockBalance.objects.values()) == balances


@pytest.mark.django_db
@pytest.mark.parametrize('entrypoint', ['batch', 'helper'])
def test_first_entry_still_rejects_received_quantity_over_current_order(purchase_entry, entrypoint):
    item, warehouse, location = purchase_entry
    item.order_item.quantity = Decimal('48')
    item.order_item.save()
    with pytest.raises(ValidationError):
        if entrypoint == 'batch':
            item.receipt.post_stock(warehouse, location)
        else:
            StockMovement.receive_purchase_receipt_item(
                item, warehouse, location, quality_status='approved'
            )
    assert not StockMovement.objects.exists()
    assert not StockBalance.objects.exists()


@pytest.mark.django_db
@pytest.mark.parametrize('entrypoint', ['batch', 'quarantine_helper'])
def test_imported_nfe_remains_valid_for_legitimate_purchase_entry(
    purchase_entry, settings, tmp_path, entrypoint
):
    from governance.models import InstitutionSettings
    from procurement.nfe_xml_import import import_nfe_into_purchase_order
    from tests.test_procurement_nfe_import import authorized_nfe_xml, NFE_KEY

    original, warehouse, location = purchase_entry
    settings.MEDIA_ROOT = str(tmp_path)
    original.receipt.status = 'cancelled'
    original.receipt.save()
    order = original.receipt.order
    order.status = 'approved'
    order.save()
    order.supplier.document = '11222333000181'
    order.supplier.save()
    InstitutionSettings.objects.create(
        legal_name='Test NF-e buyer', trade_name='Test buyer', document='99888777000166'
    )
    client = _posting_client(original)
    user = client.handler._force_user
    xml = authorized_nfe_xml(product_code=original.product.code, unit_code=original.unit.symbol)
    receipt = import_nfe_into_purchase_order(xml, purchase_order=order, user=user)
    item = receipt.items.get()
    assert receipt.nfe_access_key == NFE_KEY
    assert receipt.quality_status == 'pending'
    assert item.accepted_quantity == 0
    assert not StockMovement.objects.exists()
    item.accepted_quantity = item.received_quantity
    item.save()
    if entrypoint == 'batch':
        receipt.mark_received(user=user)
        receipt.release_quality('approved', user=user)
        receipt.post_stock(warehouse, location, user=user)
        receipt.post_stock(warehouse, location, user=user)
        expected_quality = 'approved'
    else:
        movement = StockMovement.receive_purchase_receipt_item(item, warehouse, location, user=user)
        assert (
            StockMovement.receive_purchase_receipt_item(item, warehouse, location, user=user).pk
            == movement.pk
        )
        expected_quality = 'quarantine'
    assert StockMovement.objects.count() == 1
    balance = StockBalance.objects.get()
    assert balance.quantity == Decimal('2.5')
    assert balance.quality_status == expected_quality
    assert balance.lot.expiry_date == item.expiry_date
    assert balance.lot.manufacturing_date == item.manufacturing_date
    assert receipt.nfe_xml_file.read_encrypted_content(user) == xml


@pytest.mark.django_db
def test_posted_retry_rejects_item_changed_to_zero_even_with_other_accepted_item(purchase_entry):
    from procurement.models import PurchaseOrderItem

    item, warehouse, location = purchase_entry
    other_order_item = PurchaseOrderItem.objects.create(
        order=item.receipt.order, product=item.product, unit=item.unit, quantity=10, unit_price=10
    )
    PurchaseReceiptItem.objects.create(
        receipt=item.receipt,
        order_item=other_order_item,
        product=item.product,
        unit=item.unit,
        received_quantity=1,
        accepted_quantity=1,
        lot_number='OTHER-ACCEPTED',
        expiry_date=item.expiry_date,
    )
    item.receipt.post_stock(warehouse, location)
    movements = list(StockMovement.objects.values())
    balances = list(StockBalance.objects.values())
    PurchaseReceiptItem.objects.filter(pk=item.pk).update(accepted_quantity=0, rejected_quantity=50)
    with pytest.raises(ValidationError):
        item.receipt.post_stock(warehouse, location)
    assert list(StockMovement.objects.values()) == movements
    assert list(StockBalance.objects.values()) == balances
