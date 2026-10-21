"""Approving a parent must revalidate persisted, even omitted, formula rows."""

import pytest
from django.urls import reverse

from formulations.models import FormulaComponent
from governance.models import GovernanceAuditLog
from masters.models import Product
from tests.test_product_formula_workflow import (
    FORMULA_PERMISSIONS,
    PRODUCT_PERMISSIONS,
    existing_case,
    login_with,
    url,
)
from tests.test_product_formula_workflow import case as case

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
    payload.update(
        status='approved',
        formula_selection=str(formula.pk),
        loaded_formula_selection=str(formula.pk),
        **{'formula-status': 'approved', 'formula-effective_from': '2026-01-01'},
    )
    return client, product, first, formula, material, row, payload


def test_approval_rejects_blocked_persisted_component_omitted_by_management_form(case):
    client, product, first, formula, material, row, payload = approval_case(case)
    payload.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    before = GovernanceAuditLog.objects.count()
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    formula.refresh_from_db()
    product.refresh_from_db()
    assert formula.status == 'draft'
    assert product.description == 'Produto existente'
    assert formula.components.get().pk == row.pk
    assert GovernanceAuditLog.objects.count() == before


def test_formula_approval_cannot_hide_components_by_lacking_view_permission(case):
    _, product, first, formula, material, row, payload = approval_case(case)
    client = login_with(case, PRODUCT_PERMISSIONS + FORMULA_PERMISSIONS)
    before = GovernanceAuditLog.objects.count()
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    formula.refresh_from_db()
    product.refresh_from_db()
    assert formula.status == 'draft'
    assert product.description == 'Produto existente'
    assert formula.components.get().pk == row.pk
    assert GovernanceAuditLog.objects.count() == before


def test_standalone_formula_approval_revalidates_omitted_components(case):
    client, product, first, formula, material, row, payload = approval_case(case)
    address = reverse(
        'app:resource_edit',
        kwargs={
            'module_slug': 'formulations',
            'resource_slug': 'formulas',
            'pk': formula.pk,
        },
    )
    data = {
        key.removeprefix('formula-'): value
        for key, value in payload.items()
        if key.startswith('formula-')
    }
    data.update(product=str(product.pk), version=str(formula.version))
    data.update({'components-TOTAL_FORMS': '0', 'components-INITIAL_FORMS': '0'})
    before = GovernanceAuditLog.objects.count()
    response = client.post(address, data)
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
    assert client.post(url(product.pk), payload).status_code == 302
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
    assert client.post(url(product.pk), payload).status_code == 302
    formula.refresh_from_db()
    row.refresh_from_db()
    material.refresh_from_db()
    assert formula.status == 'approved'
    assert row.material_id == replacement.pk
    assert material.status == 'blocked'
