"""Safety regressions for relevant writers, using separate PostgreSQL connections.

Known RED contracts are intentionally not xfailed: see the bounded remediation
proposal in docs/validation/formula-writer-concurrency.md before claiming closure.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident

import pytest
from django.contrib import admin
from django.db import connection, connections
from django.test import Client
from django.urls import reverse
from rest_framework.test import APIClient

from base.ui.views import ResourceUpdateView
from formulations.admin import MasterFormulaAdmin
from formulations.models import FormulaComponent, MasterFormula
from formulations.serializers import FormulaComponentSerializer
from masters.models import Product
from masters.serializers import ProductSerializer
from tests.formula_editor_cases import case as case
from tests.formula_editor_cases import existing_case, product_url, url

pytestmark = [pytest.mark.django_db(transaction=True), pytest.mark.permission_strict]


def backend_pid():
    assert connection.vendor == 'postgresql'

    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '4s'")
        cursor.execute("SET statement_timeout = '30s'")
        cursor.execute('SELECT pg_backend_pid()')
        return cursor.fetchone()[0]


def interleave(monkeypatch, owner, method, writer, integrated):
    """Pause before persistence/lock; commit the competing real HTTP POST.

    The barrier controls scheduling only. Both validation and persistence remain
    real; no ORM result is replaced. PostgreSQL sessions must have distinct PIDs.
    """
    ready, resume = Event(), Event()
    original = getattr(owner, method)
    main_pid = backend_pid()
    main_ident = get_ident()

    def paused(self, *args, **kwargs):
        if get_ident() == main_ident:
            return original(self, *args, **kwargs)
        ready.set()
        assert resume.wait(90), 'Competidor não liberou o escritor.'
        return original(self, *args, **kwargs)

    monkeypatch.setattr(owner, method, paused)

    def run_writer():
        try:
            assert backend_pid() != main_pid
            return writer()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_writer)
        try:
            if not ready.wait(60):
                if future.done():
                    response = future.result()
                    pytest.fail(
                        f'Escritor saiu antes da barreira: {response.status_code} '
                        f'{getattr(response, "data", "HTTP sem serializer")}'
                    )
                pytest.fail('Escritor não alcançou a barreira pré-save.')
            integrated()
        finally:
            resume.set()
            # Session timeouts must not leak into Django's large-schema flush.
            with connection.cursor() as cursor:
                cursor.execute('RESET statement_timeout')
                cursor.execute('RESET lock_timeout')
        return future.result(timeout=40)


def stale_form_payload(case):
    """A formula form rendered before a concurrent writer changed ``notes``."""

    client, product, _, formula, payload = existing_case(case)
    payload = {key: value for key, value in payload.items() if not key.startswith('components-')}
    payload.update(
        batch_size='333',
        notes='Nota anterior',
        **{'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'},
    )
    return client, product, formula, payload


def test_product_api_patch_preserves_fields_committed_by_the_product_editor(case, monkeypatch):
    client, product, _, _, _ = existing_case(case)
    payload = {
        'description': 'Descrição concorrente integrada',
        'item_type': 'finished_product',
        'unit': str(case[2].pk),
        'status': 'approved',
        'requires_quality_release': 'on',
    }

    def writer():
        api = APIClient()
        api.force_authenticate(case[1])
        return api.patch(
            f'/api/masters/products/{product.pk}/', {'fiscal_ncm': '33049990'}, format='json'
        )

    def integrated():
        assert client.post(product_url(product.pk), payload).status_code == 302
        assert Product.objects.get(pk=product.pk).description == payload['description']

    response = interleave(monkeypatch, ProductSerializer, 'update', writer, integrated)
    assert response.status_code == 200
    product.refresh_from_db()
    assert product.fiscal_ncm == '33049990'
    assert product.description == payload['description'], (
        'PATCH fiscal apagou descrição já confirmada.'
    )
    assert response.data['description'] == payload['description']


def test_component_api_create_rechecks_approval_committed_by_the_formula_editor(
    case, monkeypatch
):
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

    def writer():
        api = APIClient()
        api.force_authenticate(case[1])
        return api.post(
            '/api/formulations/components/',
            {
                'formula': formula.pk,
                'line_number': 10,
                'material': material.pk,
                'quantity': '1',
                'unit': case[2].pk,
            },
            format='json',
        )

    def integrated():
        assert client.post(url(formula.pk), payload).status_code == 302
        assert MasterFormula.objects.get(pk=formula.pk).status == 'approved'

    response = interleave(monkeypatch, FormulaComponentSerializer, 'create', writer, integrated)
    formula.refresh_from_db()
    assert formula.status == 'approved'
    assert response.status_code == 400, (
        'Componente validado em rascunho foi gravado após aprovação.'
    )
    assert not FormulaComponent.objects.filter(formula=formula).exists()


@pytest.mark.parametrize('surface', ['standalone', 'admin'])
def test_formula_form_preserves_unmodified_fields_committed_concurrently(
    case, monkeypatch, surface
):
    """A form rendered before a concurrent commit must not erase what it never showed."""

    client, product, formula, stale = stale_form_payload(case)
    formula.notes = stale['notes']
    formula.save(update_fields=['notes'])
    committed = 'Nota concorrente confirmada'

    def writer():
        other = Client()
        other.force_login(case[1])
        if surface == 'admin':
            assert admin.site.is_registered(MasterFormula)
            return other.post(
                reverse('admin:formulations_masterformula_change', args=[formula.pk]),
                {**stale, '_save': 'Salvar'},
            )
        return other.post(url(formula.pk), stale)

    def integrated():
        api = APIClient()
        api.force_authenticate(case[1])
        response = api.patch(
            f'/api/formulations/formulas/{formula.pk}/', {'notes': committed}, format='json'
        )
        assert response.status_code == 200, response.data
        assert MasterFormula.objects.get(pk=formula.pk).notes == committed

    owner, method = (
        (MasterFormulaAdmin, 'save_model')
        if surface == 'admin'
        else (ResourceUpdateView, 'save_object_and_inline_formsets')
    )
    response = interleave(monkeypatch, owner, method, writer, integrated)
    assert response.status_code == 302
    formula.refresh_from_db()
    assert formula.batch_size == 333
    assert formula.notes == committed, 'Formulário antigo apagou campo não alterado.'


def test_formula_api_patch_accepts_existing_identity(case):
    _, _, _, formula, _ = existing_case(case)
    api = APIClient()
    api.force_authenticate(case[1])
    response = api.patch(
        f'/api/formulations/formulas/{formula.pk}/', {'batch_size': '333'}, format='json'
    )
    assert response.status_code == 200, response.data
    formula.refresh_from_db()
    assert formula.batch_size == 333
