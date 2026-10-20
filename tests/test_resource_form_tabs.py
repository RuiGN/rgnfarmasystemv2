import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from types import SimpleNamespace

from django import forms
from django.forms import formset_factory


def resource(app='formulations', slug='formulas'):
    return SimpleNamespace(app_label=app, slug=slug)


def parent_form(data=None):
    class Parent(forms.Form):
        product = forms.CharField()
        version = forms.IntegerField(min_value=1)
        token = forms.CharField(widget=forms.HiddenInput, required=False)

    return Parent(data)


def inline(data=None):
    class Row(forms.Form):
        quantity = forms.DecimalField(min_value=1)

    factory = formset_factory(Row, extra=1)
    return {
        'key': 'components',
        'title': 'Componentes da fórmula',
        'available': True,
        'formset': factory(data, prefix='components'),
    }


def test_formula_groups_visible_fields_once():
    from base.ui.form_layouts import build_resource_form_layout

    form = parent_form()
    layout = build_resource_form_layout(resource(), form, [inline()])
    tabs = layout['form_tabs']
    assert [tab['key'] for tab in tabs] == ['product', 'formula', 'inline-components']
    assert [field.name for field in tabs[0]['fields']] == ['product']
    assert [field.name for field in tabs[1]['fields']] == ['version']
    assert sum(len(tab['fields']) for tab in tabs) == len(form.visible_fields())
    assert layout['active_form_tab'] == 'product'
    assert not form.is_bound


def test_generic_inlines_get_general_then_child_tabs():
    from base.ui.form_layouts import build_resource_form_layout

    layout = build_resource_form_layout(
        resource('procurement', 'orders'), parent_form(), [inline()]
    )
    assert [tab['key'] for tab in layout['form_tabs']] == ['general', 'inline-components']


def test_simple_resource_has_no_tabs():
    from base.ui.form_layouts import build_resource_form_layout

    assert build_resource_form_layout(resource('masters', 'units'), parent_form(), []) == {
        'form_tabs': [],
        'active_form_tab': '',
    }


def test_child_errors_activate_child_panel():
    from base.ui.form_layouts import build_resource_form_layout

    child = inline(
        {
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            'components-0-quantity': '0',
        }
    )
    layout = build_resource_form_layout(
        resource(),
        parent_form({'product': '1', 'version': '1'}),
        [child],
    )
    assert layout['active_form_tab'] == 'inline-components'
    assert layout['form_tabs'][-1]['has_errors'] is True


def test_unavailable_inline_is_not_dereferenced():
    from base.ui.form_layouts import build_resource_form_layout

    child = {'key': 'components', 'title': 'Componentes', 'available': False, 'formset': None}
    layout = build_resource_form_layout(resource(), parent_form(), [child])
    assert layout['form_tabs'][-1]['inline'] is child
    assert layout['form_tabs'][-1]['has_errors'] is False


def test_valid_bound_child_does_not_get_an_error_badge():
    from base.ui.form_layouts import build_resource_form_layout

    child = inline(
        {
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            'components-0-quantity': '1',
        }
    )
    layout = build_resource_form_layout(
        resource(),
        parent_form({'product': '1', 'version': '1'}),
        [child],
    )
    assert layout['form_tabs'][-1]['has_errors'] is False
    assert layout['active_form_tab'] == 'product'


def test_non_field_parent_error_activates_formula():
    from base.ui.form_layouts import build_resource_form_layout

    form = parent_form({'product': '1', 'version': '1'})
    form.is_valid()
    form.add_error(None, 'Conflito de versão.')
    layout = build_resource_form_layout(resource(), form, [inline()])
    assert layout['active_form_tab'] == 'formula'
    assert layout['form_tabs'][1]['has_errors'] is True


INLINE_RESOURCES = [
    ('formulations', 'formulas'),
    ('production', 'orders'),
    ('procurement', 'orders'),
    ('procurement', 'receipts'),
    ('quality', 'analyses'),
    ('documents', 'controlled-documents'),
    ('deviations', 'events'),
    ('capa', 'records'),
    ('audits', 'plans'),
    ('audits', 'findings'),
    ('risks', 'records'),
    ('recalls', 'campaigns'),
]


@pytest.fixture
def tab_admin(db, client):
    user = get_user_model().objects.create_superuser(
        username='tabs-admin',
        email='tabs-admin@example.com',
        password=None,
    )
    client.force_login(user)
    return client


def create_url(module, slug):
    return reverse('app:resource_create', kwargs={'module_slug': module, 'resource_slug': slug})


def test_formula_page_renders_three_unique_panels(tab_admin):
    response = tab_admin.get(create_url('formulations', 'formulas'))
    assert response.status_code == 200
    tabs = response.context['form_tabs']
    assert [tab['key'] for tab in tabs] == ['product', 'formula', 'inline-components']
    html = response.content.decode()
    assert 'data-ui="resource-form-tabs"' in html
    for tab in tabs:
        assert html.count(f'id="resource-tab-{tab["key"]}"') == 1
        assert html.count(f'id="resource-pane-{tab["key"]}"') == 1
    for field in response.context['form'].visible_fields():
        assert html.count(f'name="{field.html_name}"') == 1
    assert html.count('name="components-TOTAL_FORMS"') == 1


@pytest.mark.parametrize(('module', 'slug'), INLINE_RESOURCES)
def test_every_inline_resource_uses_the_shared_tabs(tab_admin, module, slug):
    response = tab_admin.get(create_url(module, slug))
    assert response.status_code == 200
    tabs = response.context['form_tabs']
    expected = {'inline-' + item['key'] for item in response.context['inline_formsets']}
    assert {tab['key'] for tab in tabs if tab['inline'] is not None} == expected
    assert 'data-ui="resource-form-tabs"' in response.content.decode()


def test_simple_resource_keeps_plain_form(tab_admin):
    response = tab_admin.get(create_url('masters', 'units'))
    assert response.status_code == 200
    assert response.context['form_tabs'] == []
    assert 'data-ui="resource-form-tabs"' not in response.content.decode()


def test_field_renderer_preserves_ids_and_errors():
    from django.template.loader import render_to_string

    form = parent_form({'product': '', 'version': '1'})
    form.is_valid()
    html = render_to_string(
        'app/includes/resource_form_field.html',
        {
            'field': form['product'],
            'horizontal': True,
        },
    )
    assert 'col-lg-4' in html and 'col-lg-8' in html
    assert 'for="id_product"' in html
    assert 'id="id_product_errors"' in html
    assert 'name="product"' in html


def test_tabular_delete_control_keeps_accessible_icon():
    from django.template.loader import render_to_string

    class Row(forms.Form):
        quantity = forms.DecimalField()

    factory = formset_factory(Row, extra=1, can_delete=True)
    html = render_to_string(
        'app/includes/inline_tabular.html',
        {
            'inline': {
                'key': 'items',
                'title': 'Itens',
                'description': '',
                'can_add': True,
                'add_label': 'Adicionar item',
                'formset': factory(prefix='items'),
            },
        },
    )
    assert '>Ações</th>' in html
    assert '>Excluir</th>' not in html
    assert 'data-inline-formset-delete' in html
    assert 'aria-label="Excluir item"' in html


def test_styles_are_scoped_and_have_no_script_fallback():
    from pathlib import Path

    css = Path('static/css/app.css').read_text()
    assert '.resource-form-tabs:not([data-tabs-ready]) > .card-header' in css
    assert '.resource-form-tabs:not([data-tabs-ready]) > .tab-content > .tab-pane' in css
    assert '.resource-form-tabs .nav-link:focus-visible' in css
    assert '.resource-form-tabs .resource-inline-formset .form-grid {' in css
    assert 'grid-template-columns: minmax(0, 1fr);' in css


def test_stacked_delete_preserves_labeled_native_fallback():
    from pathlib import Path
    from django.template.loader import render_to_string

    class Row(forms.Form):
        quantity = forms.DecimalField(required=False)

    factory = formset_factory(Row, extra=1, can_delete=True)
    html = render_to_string(
        'app/includes/inline_stacked.html',
        {
            'inline': {'key': 'rows', 'title': 'Itens', 'formset': factory(prefix='rows')},
        },
    )
    assert html.count('data-inline-delete-fallback') == 2
    assert 'for="id_rows-0-DELETE"' in html
    assert 'for="id_rows-__prefix__-DELETE"' in html
    assert html.count('data-inline-delete-action') == 2
    assert '<span class="d-none">' not in html
    css = Path('static/css/app.css').read_text()
    assert '.resource-inline-formset [data-inline-delete-action] {' in css
    assert '.resource-inline-formset[data-inline-ready] [data-inline-delete-fallback] {' in css
    assert '.resource-inline-formset[data-inline-ready] [data-inline-delete-action] {' in css
    script = Path('templates/app/resource_form.html').read_text()
    assert "formset.dataset.inlineReady = 'true';" in script


def test_discarded_controls_are_disabled_without_bootstrap_tabs():
    from pathlib import Path

    script = Path('templates/app/resource_form.html').read_text()
    assert 'if (deleteField && !deleteField.disabled)' in script
    assert 'control !== deleteField' in script
    assert "control.type !== 'hidden'" in script
    assert script.index('control.disabled = true;') < script.index('deleteField.checked = true;')
    tabs = Path('static/js/resource-form-tabs.js').read_text()
    assert 'data-inline-formset-delete' not in tabs


@pytest.fixture
def formula_case(tab_admin):
    from decimal import Decimal

    from formulations.models import FormulaComponent, MasterFormula
    from masters.models import Product, UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code='TAB-KG', name='Quilograma', symbol='kg')
    product = Product.objects.create(
        code='TAB-CREME',
        description='Creme QA',
        unit=unit,
        item_type=Product.ItemType.FINISHED_PRODUCT,
        status=Product.Status.APPROVED,
    )
    material = Product.objects.create(
        code='TAB-INSUMO',
        description='Insumo QA',
        unit=unit,
        item_type=Product.ItemType.RAW_MATERIAL,
        status=Product.Status.APPROVED,
    )
    source = MasterFormula.objects.create(
        product=product,
        version=1,
        batch_size=Decimal('100'),
        batch_unit=unit,
    )
    component = FormulaComponent.objects.create(
        formula=source,
        line_number=10,
        material=material,
        quantity=Decimal('5'),
        unit=unit,
    )
    payload = {
        'product': str(product.pk),
        'version': '2',
        'status': 'draft',
        'batch_size': '100',
        'batch_unit': str(unit.pk),
        'expected_yield_percent': '100',
        'effective_from': '',
        'effective_to': '',
        'notes': 'QA de abas',
        'components-TOTAL_FORMS': '1',
        'components-INITIAL_FORMS': '0',
        'components-MIN_NUM_FORMS': '0',
        'components-MAX_NUM_FORMS': '1000',
        'components-0-line_number': '10',
        'components-0-material': str(material.pk),
        'components-0-role': 'active',
        'components-0-quantity': '5',
        'components-0-unit': str(unit.pk),
        'components-0-expected_loss_percent': '0',
        'components-0-conversion_factor': '1',
        'components-0-is_active': 'on',
    }
    return source, component, payload


@pytest.mark.parametrize(
    ('field', 'value', 'active'),
    [
        ('product', '', 'product'),
        ('batch_size', '0', 'formula'),
        ('components-0-quantity', '0', 'inline-components'),
    ],
)
def test_invalid_post_opens_corresponding_tab_without_saving(
    tab_admin, formula_case, field, value, active
):
    from formulations.models import MasterFormula

    source, _, payload = formula_case
    payload[field] = value
    response = tab_admin.post(create_url('formulations', 'formulas'), payload)
    assert response.status_code == 200
    assert response.context['active_form_tab'] == active
    tab = next(item for item in response.context['form_tabs'] if item['key'] == active)
    assert tab['has_errors'] is True
    assert response.context['form']['notes'].value() == payload['notes']
    assert list(MasterFormula.objects.values_list('pk', flat=True)) == [source.pk]


def test_missing_management_form_opens_components(tab_admin, formula_case):
    _, _, payload = formula_case
    del payload['components-TOTAL_FORMS']
    response = tab_admin.post(create_url('formulations', 'formulas'), payload)
    assert response.status_code == 200
    assert response.context['active_form_tab'] == 'inline-components'
    assert response.context['inline_formsets'][0]['formset'].non_form_errors()


def test_duplicate_component_lines_open_components(tab_admin, formula_case):
    _, _, payload = formula_case
    payload.update(
        {
            key.replace('components-0-', 'components-1-'): value
            for key, value in list(payload.items())
            if key.startswith('components-0-')
        }
    )
    payload['components-TOTAL_FORMS'] = '2'
    response = tab_admin.post(create_url('formulations', 'formulas'), payload)
    assert response.status_code == 200
    assert response.context['active_form_tab'] == 'inline-components'
    assert response.context['form_tabs'][-1]['has_errors'] is True


def test_edit_and_reuse_preserve_tab_layout_and_locked_fields(tab_admin, formula_case):
    from formulations.models import MasterFormula

    source, _, _ = formula_case
    urls = [
        reverse(
            'app:resource_edit',
            kwargs={'module_slug': 'formulations', 'resource_slug': 'formulas', 'pk': source.pk},
        ),
        reverse('app:master_formula_reuse', kwargs={'pk': source.pk}),
    ]
    for url in urls:
        response = tab_admin.get(url)
        assert response.status_code == 200
        assert [tab['key'] for tab in response.context['form_tabs']] == [
            'product',
            'formula',
            'inline-components',
        ]
        assert response.context['form'].fields['code'].disabled is True
        assert response.content.decode().count('name="components-TOTAL_FORMS"') == 1
    assert response.context['form'].fields['status'].disabled is True
    assert response.context['form'].initial['status'] == MasterFormula.Status.DRAFT
    assert MasterFormula.objects.count() == 1


@pytest.mark.permission_strict
def test_unavailable_components_stay_private_and_forged_post_is_denied(client, formula_case):
    from django.contrib.auth.models import Permission
    from formulations.models import MasterFormula

    _, _, payload = formula_case
    user = get_user_model().objects.create_user(
        username='tabs-limited', email='tabs-limited@example.com'
    )
    user.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label='formulations',
            codename__in=['view_masterformula', 'add_masterformula', 'change_masterformula'],
        )
    )
    client.force_login(user)
    response = client.get(create_url('formulations', 'formulas'))
    assert response.status_code == 200
    assert response.context['form_tabs'][-1]['inline']['available'] is False
    html = response.content.decode()
    assert 'Você não possui permissão para visualizar estes registros.' in html
    assert 'name="components-TOTAL_FORMS"' not in html
    assert 'name="components-0-material"' not in html
    response = client.post(create_url('formulations', 'formulas'), payload)
    assert response.status_code == 403
    assert MasterFormula.objects.count() == 1


def test_deleted_component_needs_only_its_identity_and_delete_flag(tab_admin, formula_case):
    from formulations.models import FormulaComponent

    source, component, payload = formula_case
    payload = {key: value for key, value in payload.items() if not key.startswith('components-0-')}
    payload.update(
        {
            'version': '1',
            'components-INITIAL_FORMS': '1',
            'components-0-id': str(component.pk),
            'components-0-formula': str(source.pk),
            'components-0-DELETE': 'on',
        }
    )
    response = tab_admin.post(
        reverse(
            'app:resource_edit',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': source.pk,
            },
        ),
        payload,
    )
    assert response.status_code == 302
    assert not FormulaComponent.objects.filter(pk=component.pk).exists()


def test_discarded_new_blank_component_does_not_run_model_validation(tab_admin, formula_case):
    from formulations.models import FormulaComponent

    source, component, payload = formula_case
    payload.update(
        {
            'version': '1',
            'components-TOTAL_FORMS': '2',
            'components-INITIAL_FORMS': '1',
            'components-0-id': str(component.pk),
            'components-0-formula': str(source.pk),
            'components-1-id': '',
            'components-1-formula': str(source.pk),
            'components-1-DELETE': 'on',
        }
    )
    response = tab_admin.post(
        reverse(
            'app:resource_edit',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': source.pk,
            },
        ),
        payload,
    )
    assert response.status_code == 302
    assert list(FormulaComponent.objects.values_list('pk', flat=True)) == [component.pk]
