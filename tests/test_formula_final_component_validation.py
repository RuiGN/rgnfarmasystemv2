"""Approving a parent must revalidate persisted, even omitted, formula rows."""

import pytest

from formulations.models import FormulaComponent
from governance.models import GovernanceAuditLog
from masters.models import Product
from tests.formula_editor_cases import (
    FORMULA_PERMISSIONS,
    PRODUCT_PERMISSIONS,
    existing_case,
    login_with,
    product_url,
    url,
)
from tests.formula_editor_cases import case as case

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def approval_case(case):
    client, product, first, formula, original = existing_case(case)
    material = case[3]
    material.status = 'blocked'
    material.save(update_fields=['status'])
    row = FormulaComponent.objects.create(
        formula=formula, line_number=10, material=material, quantity=1, unit=case[2]
    )
    payload = {key: value for key, value in original.items() if not key.startswith('components-')}
    payload.update(status='approved', effective_from='2026-01-01')
    return client, product, first, formula, material, row, payload


def test_approval_rejects_blocked_persisted_component_omitted_by_management_form(case):
    client, product, first, formula, material, row, payload = approval_case(case)
    payload.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    before = GovernanceAuditLog.objects.count()
    response = client.post(url(formula.pk), payload)
    assert response.status_code == 200
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert formula.components.get().pk == row.pk
    assert GovernanceAuditLog.objects.count() == before


def test_forged_component_management_form_is_denied_without_view_permission(case):
    """Produto é um FK do formulário; componentes ficam de fora de propósito."""

    _, product, first, formula, material, row, payload = approval_case(case)
    client = login_with(case, PRODUCT_PERMISSIONS + FORMULA_PERMISSIONS)
    payload.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    before = GovernanceAuditLog.objects.count()
    response = client.post(url(formula.pk), payload)
    assert response.status_code == 403
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert formula.components.get().pk == row.pk
    assert GovernanceAuditLog.objects.count() == before


def test_formula_approval_cannot_hide_components_by_lacking_view_permission(case):
    """Sem o formset forjado, a aprovação ainda revalida as linhas persistidas."""

    _, product, first, formula, material, row, payload = approval_case(case)
    client = login_with(case, PRODUCT_PERMISSIONS + FORMULA_PERMISSIONS)
    payload = {key: value for key, value in payload.items() if not key.startswith('components-')}
    before = GovernanceAuditLog.objects.count()
    response = client.post(url(formula.pk), payload)
    assert response.status_code == 200
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert formula.components.get().pk == row.pk
    assert GovernanceAuditLog.objects.count() == before


def test_formula_approval_accepts_available_persisted_components(case):
    client, product, first, formula, material, row, payload = approval_case(case)
    material.status = 'approved'
    material.save(update_fields=['status'])
    payload.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    assert client.post(url(formula.pk), payload).status_code == 302
    formula.refresh_from_db()
    first.refresh_from_db()
    assert formula.status == 'approved'
    assert first.status == 'approved' and first.version == 1
    assert formula.components.get().pk == row.pk


def test_formula_approval_accepts_component_repaired_in_the_same_post(case):
    client, product, first, formula, material, row, payload = approval_case(case)
    replacement = Product.objects.create(
        description='Material substituto aprovado',
        item_type='raw_material',
        unit=case[2],
        status='approved',
    )
    payload.update({key: value for key, value in case[-1].items() if key.startswith('components-')})
    payload.update(
        {
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '1',
            'components-0-id': str(row.pk),
            'components-0-material': str(replacement.pk),
        }
    )
    assert client.post(url(formula.pk), payload).status_code == 302
    formula.refresh_from_db()
    row.refresh_from_db()
    material.refresh_from_db()
    assert formula.status == 'approved'
    assert row.material_id == replacement.pk
    assert material.status == 'blocked'


def test_product_editor_cannot_reach_formula_rows(case):
    """The product form is a plain masters record: no formula fields, no writes."""

    client, product, first, formula, material, row, payload = approval_case(case)
    client = login_with(case, ['masters.view_product', 'masters.change_product'])
    response = client.post(
        product_url(product.pk),
        {
            'description': 'Produto existente',
            'item_type': 'finished_product',
            'unit': str(case[2].pk),
            'status': 'approved',
            'version': '2',
            'batch_size': '999',
        },
    )
    assert response.status_code in (200, 302)
    formula.refresh_from_db()
    assert formula.status == 'draft'
    assert formula.batch_size == 200
