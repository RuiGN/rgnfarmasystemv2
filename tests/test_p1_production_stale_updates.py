"""Atualizações de metadados não podem sobrescrever transições concorrentes de OP."""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from governance.models import GovernanceAuditLog
from production.models import ProductionOrder
from production.serializers import ProductionOrderSerializer
from tests.test_production import create_released_manufacturing_set


@pytest.fixture
def running_order(db):
    actor = get_user_model().objects.create_superuser(
        username='p1-production', email='p1-production@example.test'
    )
    unit, product, _, formula, _, route = create_released_manufacturing_set('P1-STALE')
    order = ProductionOrder.objects.create(
        product=product,
        formula=formula,
        route=route,
        planned_quantity=Decimal('100'),
        unit=unit,
    )
    order.approve(actor)
    order.release(actor)
    order.start(actor)
    return order, actor


def lifecycle_snapshot(order):
    return {
        field: getattr(order, field)
        for field in (
            'status',
            'approved_by_id',
            'approved_at',
            'released_by_id',
            'released_at',
            'started_by_id',
            'actual_start',
            'completed_by_id',
            'actual_end',
            'actual_yield_quantity',
            'cancelled_by_id',
            'cancelled_at',
            'cancel_reason',
        )
    }


@pytest.mark.parametrize('transition', ['complete', 'pause', 'cancel'])
def test_stale_notes_preserve_latest_lifecycle(running_order, transition):
    order, actor = running_order
    stale = ProductionOrder.objects.get(pk=order.pk)
    serializer = ProductionOrderSerializer(stale, data={'notes': 'Observação tardia'}, partial=True)
    assert serializer.is_valid(), serializer.errors
    current = ProductionOrder.objects.get(pk=order.pk)
    if transition == 'complete':
        current.complete(Decimal('95'), actor)
    elif transition == 'pause':
        current.pause(actor)
    else:
        current.cancel('Cancelamento justificado', actor)
    current.refresh_from_db()
    expected = lifecycle_snapshot(current)
    audit_count = GovernanceAuditLog.objects.count()

    saved = serializer.save()

    current.refresh_from_db()
    assert lifecycle_snapshot(current) == expected
    assert lifecycle_snapshot(saved) == expected
    assert current.notes == 'Observação tardia'
    assert GovernanceAuditLog.objects.count() == audit_count


def test_stale_patch_preserves_other_metadata_written_after_validation(running_order):
    order, _ = running_order
    serializer = ProductionOrderSerializer(order, data={'notes': 'Nova observação'}, partial=True)
    assert serializer.is_valid(), serializer.errors
    current = ProductionOrder.objects.get(pk=order.pk)
    current.production_line = 'Linha atualizada'
    current.save(update_fields=['production_line', 'updated_at'])

    serializer.save()

    current.refresh_from_db()
    assert current.production_line == 'Linha atualizada'
    assert current.notes == 'Nova observação'


@pytest.mark.parametrize('prefix', ['/api/', '/api/v1/'])
def test_http_patch_preserves_completion_after_serializer_validation(
    running_order, monkeypatch, prefix
):
    order, actor = running_order
    original_update = ProductionOrderSerializer.update

    def complete_then_update(serializer, instance, validated_data):
        current = ProductionOrder.objects.get(pk=instance.pk)
        current.complete(Decimal('95'), actor)
        return original_update(serializer, instance, validated_data)

    monkeypatch.setattr(ProductionOrderSerializer, 'update', complete_then_update)
    api = APIClient()
    api.force_authenticate(actor)
    response = api.patch(
        f'{prefix}production/orders/{order.pk}/', {'notes': 'Observação via API'}, format='json'
    )

    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.COMPLETED
    assert order.completed_by_id == actor.pk
    assert order.actual_end is not None
    assert order.actual_yield_quantity == Decimal('95')
    assert response.data['status'] == ProductionOrder.Status.COMPLETED
    assert order.notes == 'Observação via API'


def test_update_revalidates_current_formula_after_initial_validation(running_order):
    from formulations.models import MasterFormula
    from rest_framework.exceptions import ValidationError

    order, _ = running_order
    serializer = ProductionOrderSerializer(order, data={'notes': 'Não deve gravar'}, partial=True)
    assert serializer.is_valid(), serializer.errors
    formula = MasterFormula.objects.get(pk=order.formula_id)
    formula.status = MasterFormula.Status.DRAFT
    formula.save(update_fields=['status'])

    with pytest.raises(ValidationError) as error:
        serializer.save()

    assert 'formula' in error.value.detail
    order.refresh_from_db()
    assert order.notes == ''


@pytest.mark.django_db(transaction=True)
def test_http_patch_and_completion_on_separate_connections_preserve_state(
    running_order, monkeypatch
):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from django.db import close_old_connections, connection
    from production.views import ProductionOrderViewSet

    assert connection.vendor == 'postgresql'
    order, actor = running_order
    loaded = Event()
    proceed = Event()
    original_get_object = ProductionOrderViewSet.get_object

    def load_then_wait(view):
        instance = original_get_object(view)
        loaded.set()
        assert proceed.wait(15)
        return instance

    monkeypatch.setattr(ProductionOrderViewSet, 'get_object', load_then_wait)

    def patch_notes():
        close_old_connections()
        try:
            api = APIClient()
            api.force_authenticate(actor)
            return api.patch(
                f'/api/production/orders/{order.pk}/',
                {'notes': 'Edição concorrente'},
                format='json',
            )
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(patch_notes)
        try:
            assert loaded.wait(15)
            order.complete(Decimal('95'), actor)
        finally:
            proceed.set()
        response = future.result(timeout=30)

    assert response.status_code == 200, response.data
    order.refresh_from_db()
    assert order.status == ProductionOrder.Status.COMPLETED
    assert order.completed_by_id == actor.pk
    assert order.actual_end is not None
    assert order.actual_yield_quantity == Decimal('95')
    assert order.notes == 'Edição concorrente'
    assert (
        GovernanceAuditLog.objects.filter(
            action='production.order.completed', target_record_id=str(order.pk)
        ).count()
        == 1
    )
