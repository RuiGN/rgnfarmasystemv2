"""Focused HTTP and two-connection proofs for the shared maintenance writer."""

from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from time import monotonic

import pytest

from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.db import connection, connections

from django.urls import reverse
from rest_framework.test import APIClient

from formulations.models import FormulaComponent, MasterFormula
from formulations.serializers import MasterFormulaSerializer
from base.aggregate_writes import write_gate
from masters.models import Product
from tests.test_formula_final_component_validation import approval_case
from tests.formula_editor_cases import case as case
from tests.formula_editor_cases import existing_case, url
from tests.test_product_formula_writer_concurrency import backend_pid, interleave

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def api_for(case):
    api = APIClient()
    api.force_authenticate(case[1])
    return api


@pytest.mark.parametrize('prefix', ['/api', '/api/v1'])
def test_formula_patch_identity_and_component_failure_roll_back(case, prefix):
    _, _, _, formula, material, row, _ = approval_case(case)
    api = api_for(case)
    response = api.patch(
        f'{prefix}/formulations/formulas/{formula.pk}/',
        {
            'status': 'approved',
            'effective_from': '2026-01-01',
            'batch_size': '333',
        },
        format='json',
    )
    assert response.status_code == 400, response.data
    formula.refresh_from_db()
    assert formula.status == 'draft' and formula.batch_size == 200
    response = api.patch(
        f'{prefix}/formulations/formulas/{formula.pk}/',
        {
            'batch_size': '333',
        },
        format='json',
    )
    assert response.status_code == 200, response.data
    assert response.data['notes'] == formula.notes


@pytest.mark.django_db(transaction=True)
def test_component_commits_before_api_approval_is_rechecked(case, monkeypatch):
    client, product, _, formula, payload = existing_case(case)
    material = case[3]
    material.status = 'blocked'
    material.save(update_fields=['status'])

    def writer():
        return api_for(case).patch(
            f'/api/formulations/formulas/{formula.pk}/',
            {
                'status': 'approved',
                'effective_from': '2026-01-01',
            },
            format='json',
        )

    def integrated():
        assert client.post(url(formula.pk), payload).status_code == 302
        assert formula.components.get().material_id == material.pk

    response = interleave(monkeypatch, MasterFormulaSerializer, 'update', writer, integrated)
    assert response.status_code == 400
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert formula.components.count() == 1


@pytest.mark.django_db(transaction=True)
def test_real_api_writer_waits_for_shared_transaction_gate(case):
    _, product, _, _, _ = existing_case(case)
    pids = Queue()
    main_pid = backend_pid()

    def writer():
        try:
            pids.put(backend_pid())
            return api_for(case).patch(
                f'/api/v1/masters/products/{product.pk}/',
                {
                    'fiscal_ncm': '33049990',
                },
                format='json',
            )
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            with write_gate():
                future = pool.submit(writer)
                worker_pid = pids.get(timeout=5)
                assert worker_pid != main_pid
                deadline = monotonic() + 3
                blocked = False
                while monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute(
                            'SELECT %s = ANY(pg_blocking_pids(%s))', [main_pid, worker_pid]
                        )
                        blocked = cursor.fetchone()[0]
                    if blocked:
                        break
                    Event().wait(0.01)
                assert blocked, 'No database lock wait was observed.'
                assert not future.done()
            assert future.result(timeout=10).status_code == 200
            product.refresh_from_db()
            assert product.fiscal_ncm == '33049990'
        finally:
            with connection.cursor() as cursor:
                cursor.execute('RESET statement_timeout')
                cursor.execute('RESET lock_timeout')


@pytest.mark.parametrize('repair', [False, True])
def test_admin_checks_final_set_after_inline_repair_and_preserves_audit(case, repair):
    client, product, _, formula, material, row, payload = approval_case(case)
    data = {
        key: value for key, value in payload.items() if not key.startswith('components-')
    }
    data.update(product=str(product.pk), version=str(formula.version), _save='Salvar')
    data.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    replacement = Product.objects.create(
        description='Substituto', item_type='raw_material', unit=case[2], status='approved'
    )
    if repair:
        data.update(
            {key: value for key, value in case[-1].items() if key.startswith('components-')}
        )
        data.update(
            {
                'components-INITIAL_FORMS': '1',
                'components-0-id': str(row.pk),
                'components-0-material': str(replacement.pk),
            }
        )
    before = LogEntry.objects.count()
    response = client.post(
        reverse('admin:formulations_masterformula_change', args=[formula.pk]), data
    )
    assert response.status_code == (302 if repair else 200)
    formula.refresh_from_db()
    row.refresh_from_db()
    assert formula.status == ('approved' if repair else 'draft')
    assert row.material_id == (replacement.pk if repair else material.pk)
    assert LogEntry.objects.count() == before + int(repair)
    if repair:
        assert 'changed' in LogEntry.objects.latest('pk').change_message


@pytest.mark.parametrize('prefix', ['/api', '/api/v1'])
def test_unprivileged_api_cannot_patch_or_delete_triad(case, prefix):
    _, product, _, formula, _ = existing_case(case)
    row = FormulaComponent.objects.create(
        formula=formula, material=case[3], line_number=1, quantity=1, unit=case[2]
    )
    user = get_user_model().objects.create_user('writer-denied', 'denied@example.com', None)
    api = APIClient()
    api.force_authenticate(user)
    for path, pk in [
        ('masters/products', product.pk),
        ('formulations/formulas', formula.pk),
        ('formulations/components', row.pk),
    ]:
        address = f'{prefix}/{path}/{pk}/'
        assert api.patch(address, {}, format='json').status_code == 403
        assert api.delete(address).status_code == 403
    assert FormulaComponent.objects.filter(pk=row.pk).exists()
    assert MasterFormula.objects.filter(pk=formula.pk).exists()
    assert Product.objects.filter(pk=product.pk).exists()


def test_admin_bulk_delete_component_keeps_standard_audit(case):
    client, _, _, formula, _ = existing_case(case)
    rows = [
        FormulaComponent.objects.create(
            formula=formula, material=case[3], line_number=n, quantity=1, unit=case[2]
        )
        for n in [1, 2]
    ]
    ids = [row.pk for row in rows]
    before = LogEntry.objects.count()
    response = client.post(
        reverse('admin:formulations_formulacomponent_changelist'),
        {
            'action': 'delete_selected',
            '_selected_action': ids,
            'post': 'yes',
        },
    )
    assert response.status_code == 302
    assert not FormulaComponent.objects.filter(pk__in=ids).exists()
    assert LogEntry.objects.count() == before + 2


def test_component_move_revalidates_new_parent_and_preserves_old_parent(case):
    _, product, approved, draft, _ = existing_case(case)
    material = case[3]
    material.status = 'blocked'
    material.save(update_fields=['status'])
    row = FormulaComponent.objects.create(
        formula=draft, material=material, line_number=1, quantity=1, unit=case[2]
    )
    response = api_for(case).patch(
        f'/api/formulations/components/{row.pk}/', {'formula': approved.pk}, format='json'
    )
    assert response.status_code == 400
    row.refresh_from_db()
    assert row.formula_id == draft.pk


def test_admin_bulk_delete_protected_product_does_not_delete_or_log(case):
    client, product, _, formula, _ = existing_case(case)
    before = LogEntry.objects.count()
    response = client.post(
        reverse('admin:masters_product_changelist'),
        {
            'action': 'delete_selected',
            '_selected_action': [product.pk],
            'post': 'yes',
        },
    )
    assert response.status_code == 200
    assert Product.objects.filter(pk=product.pk).exists()
    assert MasterFormula.objects.filter(pk=formula.pk).exists()
    assert LogEntry.objects.count() == before


def test_demo_triad_upserts_validate_and_roll_back_instead_of_bypassing(case):
    from django.core.exceptions import ValidationError
    from governance.demo_seeders import DemoSeeder

    _, product, _, formula, material, row, _ = approval_case(case)
    seed = DemoSeeder(user=case[1])
    with pytest.raises(ValidationError):
        seed._upsert(
            MasterFormula,
            'formulas',
            {'pk': formula.pk},
            {
                'status': 'approved',
                'effective_from': '2026-01-01',
            },
        )
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert seed.counts == {}
    current = seed._upsert(Product, 'products', {'pk': product.pk}, {'fiscal_ncm': '33049990'})
    assert current.description == product.description
    assert current.fiscal_ncm == '33049990'
    component = seed._upsert(FormulaComponent, 'components', {'pk': row.pk}, {'quantity': 2})
    assert component.quantity == 2 and component.material_id == material.pk


def test_api_protected_delete_returns_validation_error_without_mutation(case):
    _, product, _, formula, _ = existing_case(case)
    response = api_for(case).delete(f'/api/v1/masters/products/{product.pk}/')
    assert response.status_code == 400
    assert Product.objects.filter(pk=product.pk).exists()
    assert MasterFormula.objects.filter(pk=formula.pk).exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('surface', ['standalone', 'admin'])
def test_component_html_create_rechecks_concurrent_approval(case, monkeypatch, surface):
    from django.test import Client
    from base.ui.views import ResourceCreateView
    from formulations.admin import FormulaComponentAdmin

    client, product, _, formula, payload = existing_case(case)
    material = case[3]
    material.status = 'blocked'
    material.save(update_fields=['status'])
    payload.update(
        {
            'status': 'approved',
            'effective_from': '2026-01-01',
            'components-TOTAL_FORMS': '0',
            'components-INITIAL_FORMS': '0',
        }
    )
    data = {
        'formula': formula.pk,
        'material': material.pk,
        'line_number': '10',
        'role': 'excipient',
        'quantity': '1',
        'unit': case[2].pk,
        'expected_loss_percent': '0',
        'conversion_factor': '1',
        'is_active': 'on',
    }

    def writer():
        other = Client()
        other.force_login(case[1])
        address = (
            reverse('admin:formulations_formulacomponent_add')
            if surface == 'admin'
            else reverse(
                'app:resource_create',
                kwargs={'module_slug': 'formulations', 'resource_slug': 'components'},
            )
        )
        return other.post(address, {**data, '_save': 'Salvar'})

    def integrated():
        assert client.post(url(formula.pk), payload).status_code == 302

    owner, method = (
        (FormulaComponentAdmin, 'save_model')
        if surface == 'admin'
        else (ResourceCreateView, 'save_object_and_inline_formsets')
    )
    response = interleave(monkeypatch, owner, method, writer, integrated)
    assert response.status_code == 200
    assert not formula.components.exists()
    formula.refresh_from_db()
    assert formula.status == 'approved'
