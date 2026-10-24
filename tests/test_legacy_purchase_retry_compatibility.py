"""NF-e retry compatibility, including the limits of missing historical metadata.

The three embedded methods are exact source-v2 first-entry methods, extracted
without importing/re-registering its models. They run only inside a synthetic
fixture; retries exercise the current, unpatched HTTP/helper entrypoints.
"""

from datetime import timedelta
from decimal import Decimal
import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from inventory import models as inventory_models
from inventory.models import StockBalance, StockLot, StockMovement
from integrations.models import ApiCallLog
from masters.models import UnitOfMeasure
from procurement import models as procurement_models
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from tests.test_inventory import create_purchase_receipt_item, create_stock_address
from tests.test_review_purchase_entrypoints_corrections import _posting_client

_V2_RECEIVE_PURCHASE_RECEIPT_ITEM = """@classmethod
def receive_purchase_receipt_item(
    cls,
    receipt_item,
    warehouse,
    location,
    quality_status=StockQualityStatus.QUARANTINE,
    user=None,
):
    if receipt_item.accepted_quantity <= 0:
        raise ValidationError({'quantity': 'A quantidade aceita deve ser maior que zero.'})
    product = receipt_item.product
    unit = receipt_item.unit
    cls._validate_address(warehouse, location)
    with transaction.atomic():
        from procurement.models import PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem
        from django.db.models import Sum

        PurchaseReceipt.objects.select_for_update().get(pk=receipt_item.receipt_id)
        receipt_item = PurchaseReceiptItem.objects.select_for_update().get(pk=receipt_item.pk)
        order_item = PurchaseOrderItem.objects.select_for_update(no_key=True).get(
            pk=receipt_item.order_item_id
        )
        if receipt_item.accepted_quantity <= 0:
            raise ValidationError({'quantity': 'A quantidade aceita deve ser maior que zero.'})
        existing = cls.objects.filter(
            source_purchase_receipt_item=receipt_item, movement_type=cls.MovementType.RECEIPT
        ).first()
        if existing:
            if (
                existing.product_id != receipt_item.product_id
                or existing.unit_id != receipt_item.unit_id
                or existing.quantity != receipt_item.accepted_quantity
                or existing.lot.lot_number != receipt_item.lot_number
                or existing.to_warehouse_id != warehouse.pk
                or existing.to_location_id != location.pk
                or existing.quality_status != quality_status
            ):
                raise ValidationError(
                    {'movement': 'O lançamento existente difere do recebimento ou destino.'}
                )
            return existing
        accepted_posted = (
            cls.objects.filter(
                movement_type=cls.MovementType.RECEIPT,
                source_purchase_receipt_item__order_item_id=order_item.pk,
            ).aggregate(quantity=Sum('quantity'))['quantity']
            or ZERO_QUANTITY
        )
        if accepted_posted + receipt_item.accepted_quantity > order_item.quantity:
            raise ValidationError(
                {
                    'accepted_quantity': 'A quantidade aceita acumulada não pode superar a quantidade do pedido.'
                }
            )
        product = receipt_item.product
        unit = receipt_item.unit
        lot = cls._purchase_receipt_lot(receipt_item, quality_status)
        cls._increase_balance(
            product,
            lot,
            warehouse,
            location,
            quality_status,
            receipt_item.accepted_quantity,
            unit,
        )
        movement = cls.objects.create(
            movement_type=cls.MovementType.RECEIPT,
            product=product,
            lot=lot,
            quantity=receipt_item.accepted_quantity,
            unit=unit,
            quality_status=quality_status,
            to_warehouse=warehouse,
            to_location=location,
            source_purchase_receipt_item=receipt_item,
            created_by=user,
            document_reference=receipt_item.receipt.fiscal_document_number,
            reason='Recebimento de compra',
        )
        return movement
"""

_V2__PURCHASE_RECEIPT_LOT = """@classmethod
def _purchase_receipt_lot(cls, receipt_item, quality_status):
    product = receipt_item.product
    lot, _created = StockLot.objects.select_for_update(no_key=True).get_or_create(
        product=product,
        lot_number=receipt_item.lot_number,
        sublot_number='',
        defaults={
            'quality_status': quality_status,
            'supplier': receipt_item.receipt.order.supplier,
            'source_purchase_receipt_item': receipt_item,
            'expiry_date': receipt_item.expiry_date,
        },
    )
    if lot.quality_status != quality_status:
        raise ValidationError(
            {
                'quality_status': (
                    'O status do recebimento deve corresponder à disposição atual do lote.'
                )
            }
        )
    if lot.source_production_order_id or (
        lot.supplier_id is not None
        and (
            lot.supplier_id != receipt_item.receipt.order.supplier_id
            or lot.expiry_date != receipt_item.expiry_date
        )
    ):
        raise ValidationError(
            {'lot': 'Lote existente com fornecedor, origem ou validade incompatível.'}
        )
    if lot.supplier_id is None:
        lot.supplier = receipt_item.receipt.order.supplier
        lot.source_purchase_receipt_item = receipt_item
        lot.expiry_date = receipt_item.expiry_date
        lot.save(
            update_fields=[
                'supplier',
                'source_purchase_receipt_item',
                'expiry_date',
                'updated_at',
            ]
        )
    return lot
"""

_V2_POST_STOCK = """@transaction.atomic
def post_stock(self, warehouse=None, location=None, user=None):
    from inventory.models import StockMovement, StockQualityStatus

    receipt = type(self).objects.select_for_update().get(pk=self.pk)
    if receipt.status == self.Status.CANCELLED:
        raise ValidationError({'status': 'Recebimento cancelado não pode ser lançado.'})
    if receipt.quality_status != self.QualityStatus.APPROVED:
        raise ValidationError(
            {'quality_status': 'A entrada em estoque exige qualidade aprovada.'}
        )
    items = list(receipt.items.select_for_update().order_by('product_id', 'lot_number', 'pk'))
    if not items:
        raise ValidationError({'items': 'O recebimento precisa de ao menos um item.'})
    if not any(item.accepted_quantity > ZERO_QUANTITY for item in items):
        raise ValidationError(
            {'accepted_quantity': 'O lançamento exige quantidade aceita positiva.'}
        )
    if (
        receipt.status == self.Status.STOCK_POSTED
        or receipt.stock_entry_status == self.StockEntryStatus.POSTED
    ):
        if (
            receipt.status != self.Status.STOCK_POSTED
            or receipt.stock_entry_status != self.StockEntryStatus.POSTED
            or any(
                item.stock_movements.filter(
                    movement_type=StockMovement.MovementType.RECEIPT
                ).count()
                != 1
                for item in items
                if item.accepted_quantity > ZERO_QUANTITY
            )
        ):
            raise ValidationError(
                {
                    'stock_entry_status': 'Lançamento histórico inconsistente exige reconciliação auditada.'
                }
            )
    StockMovement._validate_address(warehouse, location)
    from django.db.models import Sum

    order_items = list(
        PurchaseOrderItem.objects.select_for_update(no_key=True)
        .filter(pk__in={item.order_item_id for item in items})
        .order_by('pk')
    )
    for order_item in order_items:
        accepted_here = sum(
            (item.accepted_quantity for item in items if item.order_item_id == order_item.pk),
            ZERO_QUANTITY,
        )
        accepted_posted = (
            StockMovement.objects.filter(
                movement_type=StockMovement.MovementType.RECEIPT,
                source_purchase_receipt_item__order_item_id=order_item.pk,
            )
            .exclude(source_purchase_receipt_item__receipt_id=receipt.pk)
            .aggregate(quantity=Sum('quantity'))['quantity']
            or ZERO_QUANTITY
        )
        if accepted_posted + accepted_here > order_item.quantity:
            raise ValidationError(
                {
                    'accepted_quantity': 'A quantidade aceita acumulada não pode superar a quantidade do pedido.'
                }
            )
    for item in items:
        item.full_clean()
        if item.order_item.order_id != receipt.order_id:
            raise ValidationError(
                {'order_item': 'O item deve pertencer ao pedido do recebimento.'}
            )
        if item.unit_id != item.order_item.unit_id or item.unit_id != item.product.unit_id:
            raise ValidationError({'unit': 'Unidade incompatível; conversão não configurada.'})
        if item.accepted_quantity + item.rejected_quantity != item.received_quantity:
            raise ValidationError({'quantity': 'Reconcilie as quantidades aceita e rejeitada.'})
        if item.accepted_quantity == ZERO_QUANTITY:
            continue
        if not item.lot_number.strip():
            raise ValidationError({'lot_number': 'Informe o lote recebido.'})
        if item.expiry_date and item.expiry_date < timezone.localdate():
            raise ValidationError(
                {'expiry_date': 'Lote vencido não pode entrar como aprovado.'}
            )
    # Validate the entire receipt before prelocking lots and balances. No sequence
    # lock may be held while this batch is still acquiring a new balance lock.
    accepted_items = [item for item in items if item.accepted_quantity > ZERO_QUANTITY]
    pending_items = [
        item
        for item in accepted_items
        if not item.stock_movements.filter(
            movement_type=StockMovement.MovementType.RECEIPT
        ).exists()
    ]
    lots = [
        StockMovement._purchase_receipt_lot(item, StockQualityStatus.APPROVED)
        for item in pending_items
    ]
    StockMovement._lock_receiving_balances(
        (item.product, lot, warehouse, location, StockQualityStatus.APPROVED, item.unit)
        for item, lot in zip(pending_items, lots)
    )
    for item in accepted_items:
        StockMovement.receive_purchase_receipt_item(
            item, warehouse, location, quality_status=StockQualityStatus.APPROVED, user=user
        )
    receipt.status = self.Status.STOCK_POSTED
    receipt.stock_entry_status = self.StockEntryStatus.POSTED
    receipt.save(
        update_fields=['status', 'stock_entry_status', 'updated_at'], _stock_posting=True
    )
    self.__dict__.update(receipt.__dict__)
"""


def _post_with_v2(item, warehouse, location, client, monkeypatch):
    # Compile only the proven methods, not the frozen modules or their imports.
    inventory_namespace = dict(vars(inventory_models))
    procurement_namespace = dict(vars(procurement_models))
    exec(_V2_RECEIVE_PURCHASE_RECEIPT_ITEM, inventory_namespace)
    exec(_V2__PURCHASE_RECEIPT_LOT, inventory_namespace)
    exec(_V2_POST_STOCK, procurement_namespace)
    with monkeypatch.context() as historical:
        historical.setattr(
            StockMovement,
            'receive_purchase_receipt_item',
            inventory_namespace['receive_purchase_receipt_item'],
        )
        historical.setattr(
            StockMovement, '_purchase_receipt_lot', inventory_namespace['_purchase_receipt_lot']
        )
        historical.setattr(PurchaseReceipt, 'post_stock', procurement_namespace['post_stock'])
        response = client.post(
            f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
            {'warehouse': warehouse.pk, 'location': location.pk},
            format='json',
        )
    assert response.status_code == 200, response.data
    lot = StockLot.objects.get(source_purchase_receipt_item=item)
    assert lot.manufacturing_date is None
    assert item.manufacturing_date is not None
    assert lot.expiry_date == item.expiry_date
    assert lot.supplier_id == item.receipt.order.supplier_id
    assert StockMovement.objects.get().quantity == item.accepted_quantity
    assert StockBalance.objects.get().quantity == item.accepted_quantity
    item.receipt.refresh_from_db()
    assert item.receipt.status == PurchaseReceipt.Status.STOCK_POSTED
    assert item.receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.POSTED


@pytest.fixture
def nfe_entry(settings, tmp_path):
    from governance.models import InstitutionSettings
    from procurement.nfe_xml_import import import_nfe_into_purchase_order
    from tests.test_procurement_nfe_import import authorized_nfe_xml, NFE_KEY

    settings.MEDIA_ROOT = str(tmp_path)
    _, _, _, original = create_purchase_receipt_item('LEGACY-NFE')
    warehouse, location = create_stock_address('LEGACY-NFE')
    original.receipt.status = 'cancelled'
    original.receipt.save()
    order = original.receipt.order
    order.status = 'approved'
    order.save()
    order.supplier.document = '11222333000181'
    order.supplier.save()
    InstitutionSettings.objects.create(
        legal_name='Synthetic NF-e buyer', trade_name='Synthetic buyer', document='99888777000166'
    )
    client = _posting_client(original)
    xml = authorized_nfe_xml(product_code=original.product.code, unit_code=original.unit.symbol)
    xml = xml.replace(
        b'2026-08-01', (timezone.localdate() - timedelta(days=30)).isoformat().encode()
    )
    xml = xml.replace(
        b'2027-08-01', (timezone.localdate() + timedelta(days=365)).isoformat().encode()
    )
    receipt = import_nfe_into_purchase_order(
        xml, purchase_order=order, user=client.handler._force_user
    )
    item = receipt.items.get()
    assert receipt.nfe_access_key == NFE_KEY
    assert receipt.nfe_xml_file_id is not None
    assert receipt.nfe_xml_sha256
    assert item.manufacturing_date == timezone.localdate() - timedelta(days=30)
    item.accepted_quantity = item.received_quantity
    item.save()
    receipt.mark_received(user=client.handler._force_user)
    receipt.release_quality('approved', user=client.handler._force_user)
    return item, warehouse, location, client


@pytest.fixture
def historical_nfe(nfe_entry, monkeypatch):
    item, warehouse, location, client = nfe_entry
    _post_with_v2(item, warehouse, location, client, monkeypatch)
    return nfe_entry


def _snapshot():
    return {
        model._meta.label: list(model.objects.order_by('pk').values())
        for model in (
            StockLot,
            StockMovement,
            StockBalance,
            PurchaseReceipt,
            PurchaseReceiptItem,
            PurchaseOrder,
            PurchaseOrderItem,
        )
    }


def _split_retry_writes(captured_queries):
    writes = [
        query['sql']
        for query in captured_queries
        if re.match(r'\s*(INSERT|UPDATE|DELETE)\b', query['sql'], re.IGNORECASE)
    ]
    # Permit exactly the existing HTTP audit INSERT, not UPDATE/DELETE, other
    # tables or any stock/receipt write, even if its net field changes are zero.
    audit_insert = rf'\s*INSERT\s+INTO\s+"{re.escape(ApiCallLog._meta.db_table)}"\s*\('
    audit_writes = [sql for sql in writes if re.match(audit_insert, sql, re.IGNORECASE)]
    unexpected_writes = [sql for sql in writes if sql not in audit_writes]
    return unexpected_writes, audit_writes


@pytest.mark.parametrize(
    'sql',
    [
        'INSERT INTO "inventory_stocklot" (id) VALUES (1)',
        'UPDATE "inventory_stockbalance" SET quantity = quantity',
        'DELETE FROM "procurement_purchasereceipt"',
        'UPDATE "integrations_apicalllog" SET status_code = 200',
        'DELETE FROM "integrations_apicalllog"',
        'INSERT INTO "integrations_apicalllog_other" (id) VALUES (1)',
    ],
)
def test_retry_sql_guard_rejects_domain_and_non_insert_audit_writes(sql):
    writes, audit_writes = _split_retry_writes([{'sql': sql}])
    assert writes == [sql]
    assert audit_writes == []


def _retry_read_only(entry, status, entrypoint='http'):
    item, warehouse, location, client = entry
    before = _snapshot()
    audit_ids_before = set(ApiCallLog.objects.values_list('pk', flat=True))
    with CaptureQueriesContext(connection) as queries:
        if entrypoint == 'http':
            response = client.post(
                f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
                {'warehouse': warehouse.pk, 'location': location.pk},
                format='json',
            )
            assert response.status_code == status, response.data
        else:
            movement_id = StockMovement.objects.get().pk
            movement = StockMovement.receive_purchase_receipt_item(
                item, warehouse, location, quality_status='approved'
            )
            assert movement.pk == movement_id
    assert _snapshot() == before
    writes, audit_writes = _split_retry_writes(queries.captured_queries)
    assert writes == []
    expected_audit_count = 1 if entrypoint == 'http' else 0
    assert len(audit_writes) == expected_audit_count
    audit_rows = list(ApiCallLog.objects.exclude(pk__in=audit_ids_before))
    assert len(audit_rows) == expected_audit_count
    if entrypoint == 'http':
        assert audit_rows[0].method == 'POST'
        assert audit_rows[0].path == f'/api/procurement/receipts/{item.receipt_id}/post_stock/'
        assert audit_rows[0].status_code == status
        assert audit_rows[0].user_id == client.handler._force_user.pk
        assert audit_rows[0].outcome == ('success' if status < 400 else 'error')


@pytest.mark.django_db
@pytest.mark.parametrize('entrypoint', ['http', 'helper'])
def test_v2_nfe_manufacturing_omission_allows_read_only_retry(historical_nfe, entrypoint):
    _retry_read_only(historical_nfe, 200, entrypoint)
    _retry_read_only(historical_nfe, 200, entrypoint)
    assert StockLot.objects.get().manufacturing_date is None


@pytest.mark.django_db
@pytest.mark.parametrize('date_change', ['different', 'removed'])
def test_modern_known_manufacturing_date_still_rejects_divergence(nfe_entry, date_change):
    item, warehouse, location, client = nfe_entry
    first = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
        {'warehouse': warehouse.pk, 'location': location.pk},
        format='json',
    )
    assert first.status_code == 200, first.data
    assert StockLot.objects.get().manufacturing_date == item.manufacturing_date
    changed = item.manufacturing_date + timedelta(days=1) if date_change == 'different' else None
    PurchaseReceiptItem.objects.filter(pk=item.pk).update(manufacturing_date=changed)
    _retry_read_only(nfe_entry, 400)


@pytest.mark.django_db
def test_legitimate_nfe_without_manufacturing_date_remains_idempotent(nfe_entry):
    item, warehouse, location, client = nfe_entry
    item.manufacturing_date = None
    item.save()
    first = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
        {'warehouse': warehouse.pk, 'location': location.pk},
        format='json',
    )
    assert first.status_code == 200, first.data
    assert StockLot.objects.get().manufacturing_date is None
    _retry_read_only(nfe_entry, 200)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'change',
    [
        'missing_movement',
        'quantity',
        'zero_quantity',
        'received_quantity',
        'rejected_quantity',
        'unit',
        'product',
        'lot',
        'expiry',
        'supplier',
        'document',
        'quality',
        'movement_quality',
        'destination',
        'inactive_location',
        'inactive_warehouse',
        'inactive_site',
        'wrong_location_warehouse',
        'wrong_order',
        'lot_source',
        'production_source',
        'sublot',
        'missing_nfe_key',
        'missing_nfe_xml',
        'missing_nfe_hash',
    ],
)
def test_historical_nfe_missing_date_does_not_bypass_other_guards(historical_nfe, change):
    item, warehouse, location, client = historical_nfe
    if change == 'missing_movement':
        StockMovement.objects.all().delete()
    elif change == 'quantity':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            accepted_quantity=item.accepted_quantity - Decimal('1'), rejected_quantity=Decimal('1')
        )
    elif change == 'zero_quantity':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            accepted_quantity=0, rejected_quantity=item.received_quantity
        )
    elif change == 'received_quantity':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(received_quantity=99)
    elif change == 'rejected_quantity':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(rejected_quantity=-1)
    elif change == 'unit':
        unit = UnitOfMeasure.objects.create(code='LEGACY-OTHER', name='Other', symbol='x')
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(unit=unit)
    elif change == 'product':
        _, _, _, other = create_purchase_receipt_item('LEGACY-OTHER')
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(product=other.product)
    elif change == 'lot':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(lot_number='REWRITTEN')
    elif change == 'expiry':
        PurchaseReceiptItem.objects.filter(pk=item.pk).update(
            expiry_date=item.expiry_date + timedelta(days=1)
        )
    elif change == 'supplier':
        _, _, _, other = create_purchase_receipt_item('LEGACY-OTHER')
        StockLot.objects.all().update(supplier=other.receipt.order.supplier)
    elif change == 'document':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(
            fiscal_document_number='REWRITTEN'
        )
    elif change == 'quality':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(quality_status='pending')
    elif change == 'movement_quality':
        StockMovement.objects.all().update(quality_status='quarantine')
    elif change == 'destination':
        warehouse, location = create_stock_address('LEGACY-OTHER')
    elif change.startswith('inactive_'):
        target = {
            'inactive_location': location,
            'inactive_warehouse': warehouse,
            'inactive_site': warehouse.site,
        }[change]
        type(target).objects.filter(pk=target.pk).update(is_active=False)
    elif change == 'wrong_location_warehouse':
        other_warehouse, _ = create_stock_address('LEGACY-OTHER')
        type(location).objects.filter(pk=location.pk).update(warehouse=other_warehouse)
    elif change == 'wrong_order':
        _, _, _, other = create_purchase_receipt_item('LEGACY-OTHER')
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(order=other.receipt.order)
    elif change == 'lot_source':
        StockLot.objects.all().update(source_purchase_receipt_item=None)
    elif change == 'production_source':
        # A non-NULL production source must not qualify for the NULL compatibility exception.
        from production.models import ProductionOrder
        from tests.test_costing import create_production_order

        order = create_production_order('LEGACY-SOURCE')
        assert isinstance(order, ProductionOrder)
        StockLot.objects.all().update(source_production_order=order)
    elif change == 'sublot':
        StockLot.objects.all().update(sublot_number='REWRITTEN')
    elif change == 'missing_nfe_key':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(nfe_access_key='')
    elif change == 'missing_nfe_xml':
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(nfe_xml_file=None)
    else:
        PurchaseReceipt.objects.filter(pk=item.receipt_id).update(nfe_xml_sha256='')
    _retry_read_only((item, warehouse, location, client), 400)


@pytest.mark.django_db
def test_nfe_null_has_no_provenance_to_distinguish_historical_omission_from_erasure(nfe_entry):
    # This documents a limitation, not a claim of tamper protection: the existing
    # schema has no immutable first-entry manufacturing-date/version record.
    item, warehouse, location, client = nfe_entry
    first = client.post(
        f'/api/procurement/receipts/{item.receipt_id}/post_stock/',
        {'warehouse': warehouse.pk, 'location': location.pk},
        format='json',
    )
    assert first.status_code == 200, first.data
    assert StockLot.objects.get().manufacturing_date == item.manufacturing_date
    StockLot.objects.all().update(manufacturing_date=None)
    _retry_read_only(nfe_entry, 200)
    assert StockLot.objects.get().manufacturing_date is None
