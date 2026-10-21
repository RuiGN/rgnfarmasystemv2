"""Authenticated HTTP contract for the integrated product editor."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from formulations.models import MasterFormula
from masters.models import Product, UnitOfMeasure

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def url(pk=None):
    return reverse(
        'app:resource_edit' if pk else 'app:resource_create',
        kwargs={
            'module_slug': 'masters',
            'resource_slug': 'products',
            **({'pk': pk} if pk else {}),
        },
    )


@pytest.fixture
def case(client):
    user = get_user_model().objects.create_superuser('workflow-admin', 'workflow@example.com', None)
    client.force_login(user)
    unit = UnitOfMeasure.objects.create(code='WF-KG', name='Quilograma', symbol='kg')
    material = Product.objects.create(
        description='Material sintético', item_type='raw_material', unit=unit, status='approved'
    )
    payload = {
        'description': 'Creme sintético',
        'item_type': 'finished_product',
        'unit': str(unit.pk),
        'status': 'draft',
        'requires_quality_release': 'on',
        'formula_selection': 'new',
        'loaded_formula_selection': 'new',
        'formula-version': '1',
        'formula-status': 'draft',
        'formula-batch_size': '100',
        'formula-batch_unit': str(unit.pk),
        'formula-expected_yield_percent': '100',
        'formula-notes': 'Observação preservada',
        'components-TOTAL_FORMS': '1',
        'components-INITIAL_FORMS': '0',
        'components-MIN_NUM_FORMS': '0',
        'components-MAX_NUM_FORMS': '1000',
        'components-0-line_number': '10',
        'components-0-material': str(material.pk),
        'components-0-role': 'excipient',
        'components-0-quantity': '5',
        'components-0-unit': str(unit.pk),
        'components-0-expected_loss_percent': '0',
        'components-0-conversion_factor': '1',
        'components-0-is_active': 'on',
    }
    return client, user, unit, material, payload


def test_product_create_saves_formula_components_and_audits_in_one_post(case):
    from governance.models import GovernanceAuditLog

    client, user, unit, material, payload = case
    response = client.post(url(), payload)
    assert response.status_code == 302
    product = Product.objects.get(description=payload['description'])
    assert product.formulas.count() == 1
    formula = product.formulas.get()
    assert formula.version == 1 and formula.batch_size == 100
    component = formula.components.get()
    assert component.material == material and component.quantity == 5
    assert GovernanceAuditLog.objects.filter(
        target_model='Product', target_record_id=str(product.pk), user=user
    ).exists()
    assert GovernanceAuditLog.objects.filter(
        target_model='MasterFormula', target_record_id=str(formula.pk), user=user
    ).exists()


def test_product_get_renders_three_real_panels(case):
    client, *_ = case
    response = client.get(url())
    assert response.status_code == 200
    assert [tab['label'] for tab in response.context['form_tabs']] == [
        'Produto',
        'Fórmula mestra',
        'Componentes',
    ]
    html = response.content.decode()
    assert html.count('class="resource-form"') == 1
    assert 'name="formula_selection"' in html
    assert 'name="description"' in html


def test_csrf_rejects_integrated_post_before_any_write(case):
    _, user, _, _, payload = case
    client = Client(enforce_csrf_checks=True)
    client.force_login(user)
    response = client.post(url(), payload)
    assert response.status_code == 403
    assert not Product.objects.filter(description=payload['description']).exists()
    assert MasterFormula.objects.count() == 0


@pytest.mark.parametrize(
    'field',
    [
        'description',
        'unit',
        'formula-version',
        'formula-batch_size',
        'formula-batch_unit',
        'formula-expected_yield_percent',
        'components-0-quantity',
        'components-0-material',
        'components-0-conversion_factor',
    ],
)
def test_incomplete_post_returns_errors_without_saving(case, field):
    client, _, _, _, payload = case
    payload[field] = ''
    response = client.post(url(), payload)
    assert response.status_code == 200
    assert not Product.objects.filter(description='Creme sintético').exists()
    assert not MasterFormula.objects.exists()
    assert 'errorlist' in response.content.decode() or 'is-invalid' in response.content.decode()


def test_late_component_failure_rolls_back_product_formula_and_audit(case, monkeypatch):
    from django.core.exceptions import ValidationError
    from formulations.models import FormulaComponent
    from governance.models import GovernanceAuditLog

    client, _, _, _, payload = case

    def refuse_save(self, *args, **kwargs):
        raise ValidationError('Falha tardia sintética.')

    monkeypatch.setattr(FormulaComponent, 'save', refuse_save)
    response = client.post(url(), payload)
    assert response.status_code == 200
    assert 'Falha tardia sintética.' in response.content.decode()
    assert not Product.objects.filter(description=payload['description']).exists()
    assert not MasterFormula.objects.exists()
    assert not GovernanceAuditLog.objects.filter(
        target_model__in=['Product', 'MasterFormula']
    ).exists()


def existing_case(case):
    client, _, unit, _, payload = case
    product = Product.objects.create(
        description='Produto existente', item_type='finished_product', unit=unit, status='approved'
    )
    first = MasterFormula.objects.create(
        product=product,
        version=1,
        batch_size=100,
        batch_unit=unit,
        status='approved',
        effective_from='2026-01-01',
    )
    second = MasterFormula.objects.create(
        product=product, version=2, batch_size=200, batch_unit=unit
    )
    return client, product, first, second, payload


def test_explicit_existing_version_edit_preserves_approved_and_version_identity(case):
    client, product, first, second, payload = existing_case(case)
    payload.update(formula_selection=str(second.pk), loaded_formula_selection=str(second.pk))
    payload['formula-version'] = '999'
    payload['formula-batch_size'] = '250'
    response = client.post(url(product.pk), payload)
    assert response.status_code == 302
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == 'approved' and first.batch_size == 100 and first.version == 1
    assert second.batch_size == 250 and second.version == 2
    assert product.formulas.count() == 2


def test_new_version_preserves_every_existing_version(case):
    client, product, first, second, payload = existing_case(case)
    payload['formula-version'] = '3'
    assert client.post(url(product.pk), payload).status_code == 302
    assert list(product.formulas.order_by('version').values_list('version', flat=True)) == [1, 2, 3]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.batch_size == 100 and second.batch_size == 200


def test_duplicate_version_is_error_and_rolls_back_parent(case):
    client, product, _, _, payload = existing_case(case)
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    product.refresh_from_db()
    assert product.description == 'Produto existente'
    assert product.formulas.count() == 2


def test_foreign_formula_selection_is_denied_without_writes(case):
    client, product, first, _, payload = existing_case(case)
    other = Product.objects.create(
        description='Outro produto', unit=product.unit, item_type='finished_product'
    )
    payload.update(formula_selection=str(first.pk), loaded_formula_selection=str(first.pk))
    assert client.post(url(other.pk), payload).status_code == 404
    other.refresh_from_db()
    assert other.description == 'Outro produto'


def test_switch_requires_load_and_preserves_posted_state(case):
    client, product, first, _, payload = existing_case(case)
    payload['formula_selection'] = str(first.pk)
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    assert 'Carregue a versão selecionada' in response.content.decode()
    product.refresh_from_db()
    assert product.description == 'Produto existente'
    assert response.context['formula_form']['notes'].value() == payload['formula-notes']


def test_load_existing_preserves_product_values_without_saving(case):
    client, product, first, _, payload = existing_case(case)
    payload.update(formula_selection=str(first.pk), workflow_action='load_formula')
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    assert response.context['form']['description'].value() == payload['description']
    assert response.context['formula_form'].instance.pk == first.pk
    product.refresh_from_db()
    assert product.description == 'Produto existente'


def test_related_category_creation_keeps_main_state_and_imposes_kind(case):
    from masters.models import MasterCategory

    client, _, _, _, payload = case
    payload.update(
        workflow_action='create_category',
        **{
            'related-category-name': 'Categoria sintética',
            'related-category-kind': 'family',
            'related-category-is_active': 'on',
        },
    )
    response = client.post(url(), payload)
    assert response.status_code == 200
    category = MasterCategory.objects.get(name='Categoria sintética')
    assert category.kind == MasterCategory.Kind.CATEGORY
    assert response.context['form']['description'].value() == payload['description']
    assert response.context['formula_form']['notes'].value() == payload['formula-notes']
    assert response.context['form_tabs'][-1]['active']
    assert not MasterFormula.objects.exists()
    assert not Product.objects.filter(description=payload['description']).exists()


def login_with(case, permissions):
    from django.contrib.auth.models import Permission

    client, _, _, _, _ = case
    user = get_user_model().objects.create_user('workflow-limited', 'limited@example.com')
    for name in permissions:
        app, codename = name.split('.')
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=codename)
        )
    client.force_login(user)
    return client


PRODUCT_PERMISSIONS = ['masters.view_product', 'masters.add_product', 'masters.change_product']
FORMULA_PERMISSIONS = [
    'formulations.view_masterformula',
    'formulations.add_masterformula',
    'formulations.change_masterformula',
]
COMPONENT_PERMISSIONS = [
    'formulations.view_formulacomponent',
    'formulations.add_formulacomponent',
    'formulations.change_formulacomponent',
]


@pytest.mark.parametrize(
    'missing',
    [
        'formulations.view_masterformula',
        'formulations.add_masterformula',
        'formulations.view_formulacomponent',
        'formulations.add_formulacomponent',
    ],
)
def test_missing_related_permission_denies_combined_write(case, missing):
    permissions = PRODUCT_PERMISSIONS + FORMULA_PERMISSIONS + COMPONENT_PERMISSIONS
    client = login_with(case, [p for p in permissions if p != missing])
    response = client.post(url(), case[-1])
    assert response.status_code == 403
    assert not MasterFormula.objects.exists()
    assert not Product.objects.filter(description=case[-1]['description']).exists()


def test_combined_create_accepts_exact_view_and_add_grants(case):
    client = login_with(
        case,
        [
            'masters.view_product',
            'masters.add_product',
            'formulations.view_masterformula',
            'formulations.add_masterformula',
            'formulations.view_formulacomponent',
            'formulations.add_formulacomponent',
        ],
    )
    response = client.post(url(), case[-1])
    assert response.status_code == 302
    assert MasterFormula.objects.get().components.count() == 1


def test_existing_formula_edit_requires_change_even_with_add_grant(case):
    _, product, _, second, payload = existing_case(case)
    client = login_with(
        case,
        PRODUCT_PERMISSIONS
        + COMPONENT_PERMISSIONS
        + ['formulations.view_masterformula', 'formulations.add_masterformula'],
    )
    payload.update(formula_selection=str(second.pk), loaded_formula_selection=str(second.pk))
    response = client.post(url(product.pk), payload)
    assert response.status_code == 403
    product.refresh_from_db()
    assert product.description == 'Produto existente'
    assert product.formulas.count() == 2


def test_product_only_does_not_require_formula_permissions_or_change_versions(case):
    _, product, first, _, payload = existing_case(case)
    client = login_with(case, PRODUCT_PERMISSIONS)
    payload = {k: v for k, v in payload.items() if not k.startswith(('formula-', 'components-'))}
    payload.update(formula_selection='none', loaded_formula_selection='none')
    response = client.get(url(product.pk))
    assert response.status_code == 200
    assert 'name="related-material-description"' not in response.content.decode()
    assert 'name="formula-batch_size"' not in response.content.decode()
    assert client.post(url(product.pk), payload).status_code == 302
    first.refresh_from_db()
    assert first.status == 'approved' and first.batch_size == 100


@pytest.mark.parametrize('action', ['create_material', 'create_category'])
def test_related_action_requires_own_view_and_add_permissions(case, action):
    from masters.models import MasterCategory

    client = login_with(
        case,
        ['masters.view_product', 'masters.change_product']
        + FORMULA_PERMISSIONS
        + COMPONENT_PERMISSIONS,
    )
    product = case[3]
    payload = {
        **case[-1],
        'workflow_action': action,
        'related-category-name': 'Negada',
        'related-material-description': 'Negado',
    }
    before = Product.objects.count()
    assert client.post(url(product.pk), payload).status_code == 403
    assert Product.objects.count() == before and not MasterCategory.objects.exists()
    assert not MasterFormula.objects.exists()


def test_related_material_rejects_wrong_category_kind_and_preserves_data(case):
    from masters.models import MasterCategory

    client, _, unit, _, payload = case
    wrong = MasterCategory.objects.create(name='Família não é categoria', kind='family')
    payload.update(
        workflow_action='create_material',
        **{
            'related-material-description': 'Inválido',
            'related-material-unit': str(unit.pk),
            'related-material-item_type': 'raw_material',
            'related-material-status': 'draft',
            'related-material-category': str(wrong.pk),
        },
    )
    response = client.post(url(), payload)
    assert response.status_code == 200
    assert response.context['related_material_form'].errors['category']
    assert response.context['form']['description'].value() == payload['description']
    assert not Product.objects.filter(description='Inválido').exists()
    assert not MasterFormula.objects.exists()


@pytest.mark.parametrize('field', ['status', 'material'])
def test_approved_formula_preserves_model_availability_rules(case, field):
    client, _, _, material, payload = case
    payload['formula-status'] = 'approved'
    payload['formula-effective_from'] = '2026-01-01'
    if field == 'material':
        payload['status'] = 'approved'
        material.status = 'blocked'
        material.save()
    response = client.post(url(), payload)
    assert response.status_code == 200
    assert 'operacionalmente disponível' in response.content.decode()
    assert not MasterFormula.objects.exists()
    assert not Product.objects.filter(description=payload['description']).exists()


def test_foreign_component_identity_rejects_main_transaction(case):
    from formulations.models import FormulaComponent

    client, product, first, second, payload = existing_case(case)
    child = FormulaComponent.objects.create(
        formula=first, line_number=10, material=case[3], unit=case[2], quantity=5
    )
    payload.update(formula_selection=str(second.pk), loaded_formula_selection=str(second.pk))
    payload.update(
        {
            'components-INITIAL_FORMS': '1',
            'components-0-id': str(child.pk),
            'components-0-formula': str(second.pk),
        }
    )
    response = client.post(url(product.pk), payload)
    assert response.status_code == 200
    product.refresh_from_db()
    child.refresh_from_db()
    assert product.description == 'Produto existente'
    assert child.formula_id == first.pk and child.quantity == 5


@pytest.mark.parametrize('action', ['create_category', 'create_material'])
def test_related_creation_in_regular_formula_components_keeps_main_unsaved(case, action):
    from masters.models import MasterCategory

    client, _, unit, product, payload = case
    data = {k.removeprefix('formula-'): v for k, v in payload.items() if k.startswith('formula-')}
    data.update({k: v for k, v in payload.items() if k.startswith('components-')})
    data.update(
        product=str(product.pk),
        workflow_action=action,
        **{
            'related-category-name': 'Categoria da fórmula',
            'related-category-is_active': 'on',
            'related-material-description': 'Material da fórmula',
            'related-material-unit': str(unit.pk),
            'related-material-item_type': 'raw_material',
            'related-material-status': 'draft',
        },
    )
    target = reverse(
        'app:resource_create', kwargs={'module_slug': 'formulations', 'resource_slug': 'formulas'}
    )
    response = client.post(target, data)
    assert response.status_code == 200
    if action == 'create_category':
        assert MasterCategory.objects.get(name='Categoria da fórmula').kind == 'category'
    else:
        assert Product.objects.filter(description='Material da fórmula').exists()
    assert response.context['form']['notes'].value() == payload['formula-notes']
    assert response.context['active_form_tab'] == 'inline-components'
    assert not MasterFormula.objects.exists()


def test_quick_material_has_only_essential_fields_and_preserves_model_defaults(case):
    client, _, unit, _, payload = case
    response = client.get(url())
    form = response.context['related_material_form']
    assert list(form.fields) == ['description', 'item_type', 'unit', 'category']
    assert form['item_type'].value() == Product.ItemType.RAW_MATERIAL
    assert form.use_required_attribute is False
    payload.update(
        workflow_action='create_material',
        **{
            'related-material-description': 'Material mínimo',
            'related-material-item_type': 'raw_material',
            'related-material-unit': str(unit.pk),
            'related-material-status': 'approved',
            'related-material-fiscal_ncm': '12345678',
            'related-material-requires_quality_release': '',
        },
    )
    response = client.post(url(), payload)
    assert response.status_code == 200
    material = Product.objects.get(description='Material mínimo')
    assert material.status == Product.Status.DRAFT
    assert material.requires_quality_release is True
    assert material.fiscal_ncm == '' and material.fiscal_cest == ''


@pytest.mark.django_db(transaction=True)
def test_concurrent_new_version_serializes_on_product_and_preserves_history(case):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from django.db import close_old_connections, connection

    _, product, first, second, payload = existing_case(case)
    payload['formula-version'] = '3'
    barrier = Barrier(2)
    user_id = case[1].pk
    target = url(product.pk)

    def post_version():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            client = Client()
            client.force_login(get_user_model().objects.get(pk=user_id))
            barrier.wait(timeout=10)
            return client.post(target, payload).status_code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(post_version) for _ in range(2)]
        statuses = [future.result(timeout=25) for future in futures]
    assert sorted(statuses) == [200, 302]
    assert list(product.formulas.order_by('version').values_list('version', flat=True)) == [1, 2, 3]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.batch_size == 100 and first.status == 'approved'
    assert second.batch_size == 200


def test_missing_product_post_returns_404(case):
    client, _, _, _, payload = case
    response = client.post(url(999999999), payload)
    assert response.status_code == 404
    assert not MasterFormula.objects.exists()


def test_quick_category_rejects_parent_of_incompatible_kind(case):
    from masters.models import MasterCategory

    client, _, _, _, payload = case
    parent = MasterCategory.objects.create(name='Área de aplicação', kind='application_area')
    payload.update(
        workflow_action='create_category',
        **{
            'related-category-name': 'Categoria incompatível',
            'related-category-parent': str(parent.pk),
            'related-category-is_active': 'on',
        },
    )
    response = client.post(url(), payload)
    assert response.status_code == 200
    assert response.context['related_category_form'].errors['parent']
    assert not MasterCategory.objects.filter(name='Categoria incompatível').exists()
    assert not MasterFormula.objects.exists()


def test_related_material_creation_keeps_components_and_uses_category(case):
    from masters.models import MasterCategory

    client, _, unit, material, payload = case
    category = MasterCategory.objects.create(name='Categoria QA', kind='category')
    payload.update(
        workflow_action='create_material',
        **{
            'related-material-description': 'Novo material sintético',
            'related-material-item_type': 'raw_material',
            'related-material-unit': str(unit.pk),
            'related-material-category': str(category.pk),
            'related-material-status': 'draft',
            'related-material-requires_quality_release': 'on',
        },
    )
    response = client.post(url(), payload)
    assert response.status_code == 200
    new = Product.objects.get(description='Novo material sintético')
    assert new.category == category
    inline = response.context['form_tabs'][-1]['inline']['formset']
    assert inline.forms[0]['material'].value() == str(material.pk)
    assert inline.forms[0].fields['material'].queryset.filter(pk=new.pk).exists()
    assert response.context['formula_form']['notes'].value() == payload['formula-notes']
    assert not MasterFormula.objects.exists()
