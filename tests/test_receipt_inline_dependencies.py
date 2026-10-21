"""Receipt rows depend on the authoritative parent order, not a hidden POST ID."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from masters.models import Product, UnitOfMeasure
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
)
from tests.test_procurement import create_supplier

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


@pytest.fixture
def receipt_case(client):
    user = get_user_model().objects.create_superuser(
        'receipt-fk', 'receipt-fk@example.invalid', None
    )
    client.force_login(user)
    unit = UnitOfMeasure.objects.create(code='RC-KG', name='Quilograma', symbol='kg')
    product = Product.objects.create(
        description='Glicerina cosmética sintética',
        item_type='raw_material',
        unit=unit,
        requires_approved_supplier=False,
    )
    supplier = create_supplier(suffix='INLINE')
    orders = [
        PurchaseOrder.objects.create(supplier=supplier, issue_date=timezone.localdate())
        for _ in range(2)
    ]
    items = [
        PurchaseOrderItem.objects.create(
            order=order, product=product, quantity=10, unit=unit, unit_price=1
        )
        for order in orders
    ]
    receipt = PurchaseReceipt.objects.create(order=orders[0])
    address = reverse(
        'app:resource_edit',
        kwargs={
            'module_slug': 'procurement',
            'resource_slug': 'receipts',
            'pk': receipt.pk,
        },
    )
    payload = {
        'order': str(orders[0].pk),
        'status': 'draft',
        'quality_status': 'pending',
        'stock_entry_status': 'pending',
        'items-TOTAL_FORMS': '1',
        'items-INITIAL_FORMS': '0',
        'items-MIN_NUM_FORMS': '0',
        'items-MAX_NUM_FORMS': '1000',
        'items-0-order_item': str(items[0].pk),
        'items-0-product': str(product.pk),
        'items-0-unit': str(unit.pk),
        'items-0-received_quantity': '1',
        'items-0-accepted_quantity': '0',
        'items-0-rejected_quantity': '0',
        'items-0-receipt': str(receipt.pk),
    }
    return client, receipt, orders, items, address, payload


def test_receipt_empty_inline_filters_by_visible_parent_order(receipt_case):
    client, receipt, orders, items, address, payload = receipt_case
    response = client.get(address)
    assert response.status_code == 200
    form = response.context['inline_formsets'][0]['formset'].empty_form
    metadata = form.fields['order_item'].widget.attrs.get('data-related-rules')
    assert metadata, 'An injected hidden receipt FK must not prevent parent-order filtering.'
    rules = json.loads(str(metadata))
    assert rules[0]['controller'] == 'order'
    assert rules[0]['values'][str(items[0].pk)] == [str(orders[0].pk)]
    assert rules[0]['values'][str(items[1].pk)] == [str(orders[1].pk)]
    assert form.fields['receipt'].widget.is_hidden


def test_receipt_inline_rejects_item_from_another_parent_order(receipt_case):
    client, receipt, orders, items, address, payload = receipt_case
    payload['items-0-order_item'] = str(items[1].pk)
    response = client.post(address, payload)
    assert response.status_code == 200
    formset = response.context['inline_formsets'][0]['formset']
    assert 'order_item' in formset.forms[0].errors
    assert not PurchaseReceiptItem.objects.filter(receipt=receipt).exists()
    receipt.refresh_from_db()
    assert receipt.order_id == orders[0].pk


def test_receipt_inline_uses_changed_parent_order_from_validated_post(receipt_case):
    client, receipt, orders, items, address, payload = receipt_case
    payload['order'] = str(orders[1].pk)
    payload['items-0-order_item'] = str(items[1].pk)
    response = client.post(address, payload)
    assert response.status_code == 302
    receipt.refresh_from_db()
    saved = receipt.items.get()
    assert receipt.order_id == orders[1].pk
    assert saved.order_item_id == items[1].pk
    assert saved.receipt_id == receipt.pk


def test_receipt_inline_hidden_parent_cannot_redirect_the_row(receipt_case):
    client, receipt, orders, items, address, payload = receipt_case
    other = PurchaseReceipt.objects.create(order=orders[1])
    payload['items-0-receipt'] = str(other.pk)
    response = client.post(address, payload)
    assert response.status_code == 200
    assert not PurchaseReceiptItem.objects.exists()
    assert 'receipt' in response.context['inline_formsets'][0]['formset'].forms[0].errors


def test_receipt_order_change_cannot_skip_incompatible_persisted_rows(receipt_case):
    client, receipt, orders, items, address, payload = receipt_case
    row = PurchaseReceiptItem.objects.create(
        receipt=receipt,
        order_item=items[0],
        product=items[0].product,
        unit=items[0].unit,
        received_quantity=1,
    )
    payload['order'] = str(orders[1].pk)
    payload['items-TOTAL_FORMS'] = '0'
    response = client.post(address, payload)
    assert response.status_code == 200
    receipt.refresh_from_db()
    row.refresh_from_db()
    assert receipt.order_id == orders[0].pk
    assert row.order_item_id == items[0].pk


@pytest.mark.parametrize(
    'missing',
    (
        'order_item',
        'product',
        'unit',
        'received_quantity',
        'accepted_quantity',
        'rejected_quantity',
    ),
)
def test_receipt_incomplete_inline_returns_field_errors_not_http_500(receipt_case, missing):
    client, receipt, orders, items, address, payload = receipt_case
    payload[f'items-0-{missing}'] = ''
    response = client.post(address, payload)
    assert response.status_code == 200
    assert missing in response.context['inline_formsets'][0]['formset'].forms[0].errors
    assert not PurchaseReceiptItem.objects.filter(receipt=receipt).exists()
