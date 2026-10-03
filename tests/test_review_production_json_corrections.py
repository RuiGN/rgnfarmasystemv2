"""HTTP regressions for production-order JSON shape validation."""

import json

import pytest

from governance.models import GovernanceAuditLog
from inventory.models import StockBalance, StockMovement
from production.models import MaterialConsumption, ProductionOrder
from tests import test_production_cancellation_corrections as cancellation_fixtures

allocation_fixture = cancellation_fixtures.allocation_fixture
production_order = cancellation_fixtures.production_order
reserved_order = cancellation_fixtures.reserved_order
stock_address = cancellation_fixtures.stock_address
stock_lot = cancellation_fixtures.stock_lot


def domain_snapshot():
    """Include identities, metadata and full linked rows, not just row counts."""
    return {
        'orders': list(ProductionOrder.objects.order_by('pk').values()),
        'consumptions': list(MaterialConsumption.objects.order_by('pk').values()),
        'balances': list(StockBalance.objects.order_by('pk').values()),
        'movements': list(StockMovement.objects.order_by('pk').values()),
        'events': list(
            GovernanceAuditLog.objects.filter(action='production.order.cancelled')
            .order_by('pk')
            .values()
        ),
    }


@pytest.fixture
def cancelled_order_http(reserved_order):
    client, item, _, _ = reserved_order
    url = f'/api/production/orders/{item.order_id}/'
    response = client.post(url + 'cancel/', {'cancel_reason': 'Original'}, format='json')
    assert response.status_code == 200, response.data
    item.order.refresh_from_db()
    assert item.order.status == ProductionOrder.Status.CANCELLED
    assert item.order.cancel_reason == 'Original'
    assert GovernanceAuditLog.objects.filter(action='production.order.cancelled').count() == 1
    client.raise_request_exception = False
    return client, item.order, url


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'patch'])
@pytest.mark.parametrize(
    'payload',
    [42, [{'cancel_reason': 'Changed'}], None, 'Changed', True, False],
    ids=['integer', 'list-of-objects', 'null', 'string', 'true', 'false'],
)
def test_non_object_json_returns_400_without_domain_mutation(cancelled_order_http, method, payload):
    client, _, detail_url = cancelled_order_http
    url = '/api/production/orders/' if method == 'post' else detail_url
    before = domain_snapshot()
    response = getattr(client, method)(url, json.dumps(payload), content_type='application/json')
    assert domain_snapshot() == before
    assert response.status_code == 400, response.content.decode()
    assert response['Content-Type'].startswith('application/json')
    assert 'non_field_errors' in response.data


def valid_create_payload(order):
    return {
        'product': order.product_id,
        'formula': order.formula_id,
        'route': order.route_id,
        'planned_quantity': '100.0000',
        'unit': order.unit_id,
        'notes': 'Valid JSON object',
    }


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'patch'])
@pytest.mark.parametrize(
    'protected',
    [
        {'status': 'draft'},
        {'cancelled_by': None},
        {'cancelled_at': None},
        {'status': 'draft', 'cancelled_by': None, 'cancelled_at': None},
    ],
    ids=['status', 'cancelled-by', 'cancelled-at', 'all-metadata'],
)
def test_protected_object_metadata_is_explicitly_rejected(cancelled_order_http, method, protected):
    client, order, detail_url = cancelled_order_http
    url = '/api/production/orders/' if method == 'post' else detail_url
    payload = valid_create_payload(order) if method == 'post' else {'notes': 'Forbidden edit'}
    payload.update(protected)
    before = domain_snapshot()
    response = getattr(client, method)(url, payload, format='json')
    assert domain_snapshot() == before
    assert response.status_code == 400, response.content.decode()
    for field in protected:
        assert str(response.data[field]) == 'Campo controlado pelo fluxo de domínio.'


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'patch'])
def test_valid_object_remains_accepted_preserving_cancelled_order_evidence(
    cancelled_order_http, method
):
    client, order, detail_url = cancelled_order_http
    before = domain_snapshot()
    if method == 'post':
        response = client.post(
            '/api/production/orders/', valid_create_payload(order), format='json'
        )
        assert response.status_code == 201, response.content.decode()
        created = ProductionOrder.objects.get(pk=response.data['id'])
        assert created.pk != order.pk
        assert created.order_number and created.batch_number
        assert created.order_number != order.order_number
        assert created.batch_number != order.batch_number
        assert created.status == ProductionOrder.Status.DRAFT
        assert created.product_id == order.product_id
        assert created.formula_id == order.formula_id
        assert created.route_id == order.route_id
        assert created.unit_id == order.unit_id
        assert created.notes == 'Valid JSON object'
        assert not created.cancel_reason
        assert created.cancelled_at is None
        assert created.cancelled_by_id is None
        after = domain_snapshot()
        assert len(after['orders']) == len(before['orders']) + 1
        after['orders'] = [row for row in after['orders'] if row['id'] != created.pk]
    else:
        response = client.patch(detail_url, {'notes': 'Valid JSON object'}, format='json')
        assert response.status_code == 200, response.content.decode()
        order.refresh_from_db()
        assert order.notes == 'Valid JSON object'
        after = domain_snapshot()
        for rows in (before['orders'], after['orders']):
            for row in rows:
                row.pop('notes')
                row.pop('updated_at')
    assert after == before


@pytest.mark.django_db
@pytest.mark.parametrize('method', ['post', 'patch'])
def test_object_still_runs_domain_quantity_validation(cancelled_order_http, method):
    client, order, detail_url = cancelled_order_http
    url = '/api/production/orders/' if method == 'post' else detail_url
    payload = valid_create_payload(order) if method == 'post' else {}
    payload['planned_quantity'] = '0'
    before = domain_snapshot()
    response = getattr(client, method)(url, payload, format='json')
    assert domain_snapshot() == before
    assert response.status_code == 400, response.content.decode()
    assert 'planned_quantity' in response.data


@pytest.mark.django_db
def test_cancel_reason_object_edit_remains_rejected_without_mutation(cancelled_order_http):
    client, _, url = cancelled_order_http
    before = domain_snapshot()
    response = client.patch(url, {'cancel_reason': 'Changed'}, format='json')
    assert domain_snapshot() == before
    assert response.status_code == 400, response.content.decode()
    assert 'status' in response.data
