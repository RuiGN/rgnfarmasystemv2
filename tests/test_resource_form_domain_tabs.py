"""Domain grouping contracts; the shared renderer and persistence stay unchanged."""

from collections import Counter
from types import SimpleNamespace

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.urls import reverse

from base.ui.form_layouts import build_resource_form_layout
from base.ui.forms import build_resource_form
from base.ui.registry import get_resource


def test_purchase_order_groups_commercial_and_delivery_fields_once():
    resource = get_resource('procurement', 'orders')
    form = build_resource_form(resource)()
    layout = build_resource_form_layout(resource, form, [])
    tabs = layout['form_tabs']
    assert [tab['key'] for tab in tabs] == ['general', 'commercial', 'delivery', 'notes']
    assert [tab['label'] for tab in tabs] == [
        'Geral',
        'Condições comerciais',
        'Entrega e endereço',
        'Observações',
    ]
    owners = {field.name: tab['key'] for tab in tabs for field in tab['fields']}
    assert owners['supplier'] == 'general'
    assert owners['payment_term_ref'] == 'commercial'
    assert owners['delivery_city_ref'] == 'delivery'
    assert owners['notes'] == 'notes'
    assert Counter(field.name for tab in tabs for field in tab['fields']) == Counter(
        field.name for field in form.visible_fields()
    )
    assert layout['active_form_tab'] == 'general'


DOMAIN_CASES = [
    ('procurement', 'orders', ('general', 'commercial', 'delivery', 'notes')),
    ('procurement', 'receipts', ('general', 'quality-fiscal', 'notes')),
    ('procurement', 'supplier-quotations', ('general', 'commercial', 'delivery', 'notes')),
    ('procurement', 'supplier-qualification-events', ('general', 'qualification', 'address')),
    ('masters', 'products', ('general', 'classification', 'quality', 'fiscal')),
    ('masters', 'partners', ('general', 'qualification', 'contact', 'address')),
    ('masters', 'sites', ('general', 'address')),
    ('inventory', 'lots', ('general', 'traceability', 'validity', 'notes')),
    ('production', 'orders', ('general', 'planning', 'notes')),
    ('planning', 'mrp-runs', ('general', 'scenario', 'notes')),
    ('costing', 'standard-costs', ('general', 'costs', 'notes')),
    ('costing', 'simulations', ('general', 'costs', 'assumptions')),
    ('costing', 'production-captures', ('general', 'costs', 'notes')),
    ('finance', 'titles', ('general', 'references', 'amounts', 'notes')),
    ('fiscal', 'companies', ('general', 'address')),
    ('fiscal', 'documents', ('general', 'electronic', 'references', 'totals', 'notes')),
    ('fiscal', 'tax-rules', ('general', 'scope', 'rates', 'notes')),
    ('crm', 'customer-profiles', ('general', 'commercial', 'notes')),
    ('crm', 'opportunities', ('general', 'forecast', 'outcome', 'notes')),
    ('crm', 'contracts', ('general', 'commercial', 'regulatory', 'notes')),
    ('crm', 'orders', ('general', 'commercial', 'shipping', 'notes')),
    ('crm', 'complaints', ('general', 'traceability', 'resolution', 'address')),
    ('quality', 'specifications', ('general', 'limits', 'validity', 'notes')),
    ('quality', 'samples', ('general', 'origin', 'collection', 'notes')),
    ('quality', 'analyses', ('general', 'method', 'review', 'notes')),
    ('quality', 'investigations', ('general', 'investigation', 'retesting')),
    ('quality', 'documents', ('general', 'conclusion')),
    ('qa', 'reviews', ('general', 'references', 'notes')),
    ('qa', 'blocks', ('general', 'scope', 'resolution')),
    ('qa', 'training-requirements', ('general', 'scope', 'validity', 'notes')),
    ('documents', 'controlled-documents', ('general', 'validity', 'content')),
    ('deviations', 'events', ('general', 'scope', 'assessment', 'closure')),
    ('capa', 'records', ('general', 'origin', 'plan', 'effectiveness', 'closure')),
    ('changes', 'controls', ('general', 'impact', 'plans', 'closure')),
    ('audits', 'plans', ('general', 'scope', 'schedule', 'address', 'closure')),
    ('risks', 'records', ('general', 'assessment', 'monitoring', 'closure')),
    (
        'recalls',
        'complaints',
        ('general', 'traceability', 'investigation', 'regulatory', 'address', 'closure'),
    ),
    ('recalls', 'returns', ('general', 'traceability', 'inspection', 'closure')),
    ('recalls', 'campaigns', ('general', 'origin', 'execution', 'closure')),
    ('training', 'requirements', ('general', 'scope', 'evaluation', 'notes')),
    ('training', 'sessions', ('general', 'schedule', 'address', 'notes')),
    ('training', 'enrollments', ('general', 'progress', 'certification', 'revocation')),
    ('files', 'access-rules', ('general', 'scope', 'notes')),
    ('reports', 'definitions', ('general', 'configuration', 'access')),
    ('workflow', 'tasks', ('general', 'origin', 'assignment')),
    ('ai_agents', 'profiles', ('general', 'model', 'scope')),
    ('governance', 'institution-settings', ('general', 'contact', 'address')),
    ('compliance', 'policies', ('general', 'requirements')),
]


@pytest.mark.parametrize(('module', 'slug', 'keys'), DOMAIN_CASES)
@pytest.mark.parametrize('update', [False, True])
def test_selected_domains_group_actual_fields_once(module, slug, keys, update):
    resource = get_resource(module, slug)
    form = build_resource_form(resource, update=update)()
    original = list(form.fields.items())
    layout = build_resource_form_layout(resource, form, [])
    tabs = layout['form_tabs']
    assert tuple(tab['key'] for tab in tabs) == keys
    assert all(tab['fields'] for tab in tabs)
    assert Counter(field.name for tab in tabs for field in tab['fields']) == Counter(
        field.name for field in form.visible_fields()
    )
    assert all(field.form is form for tab in tabs for field in tab['fields'])
    assert list(form.fields.items()) == original
    assert layout['active_form_tab'] == 'general'


@pytest.fixture
def domain_admin(db, client):
    user = get_user_model().objects.create_superuser(
        username='domain-tabs-admin', email='domain-tabs@example.com', password=None
    )
    client.force_login(user)
    return client


def create_url(module, slug):
    return reverse('app:resource_create', kwargs={'module_slug': module, 'resource_slug': slug})


@pytest.mark.parametrize(('module', 'slug', 'keys'), DOMAIN_CASES)
def test_selected_domain_create_http_preserves_field_and_management_identity(
    domain_admin, module, slug, keys
):
    response = domain_admin.get(create_url(module, slug))
    assert response.status_code == 200
    tabs = response.context['form_tabs']
    parent_tabs = [tab for tab in tabs if tab['inline'] is None]
    # The authorized view can remove service/decision fields; keys must follow that subset.
    if (module, slug) == ('masters', 'products'):
        # Product HTTP editing now composes its principal form with an explicitly
        # selected formula. The pure generic grouping contract above is unchanged.
        assert tuple(tab['key'] for tab in tabs) == ('product', 'formula', 'inline-components')
        assert Counter(field.name for field in tabs[0]['fields']) == Counter(
            field.name for field in response.context['form'].visible_fields()
        )
        assert response.context['formula_form'] is None
    else:
        assert tuple(tab['key'] for tab in parent_tabs) == keys
    html = response.content.decode()
    form = response.context['form']
    for field in [*form.visible_fields(), *form.hidden_fields()]:
        assert html.count(f'name="{field.html_name}"') == 1
    for tab in tabs:
        assert html.count(f'id="resource-tab-{tab["key"]}"') == 1
        assert html.count(f'id="resource-pane-{tab["key"]}"') == 1
    for inline in response.context['inline_formsets']:
        if inline['available']:
            assert html.count(f'name="{inline["key"]}-TOTAL_FORMS"') == 1
    assert [tab['inline'] for tab in tabs if tab['inline'] is not None] == response.context[
        'inline_formsets'
    ]


def order_form(names, *, data=None, hidden=()):
    return type(
        'OrderFields',
        (forms.Form,),
        {
            name: forms.CharField(
                required=False, widget=forms.HiddenInput if name in hidden else forms.TextInput
            )
            for name in names
        },
    )(data=data)


def test_missing_and_extra_authorized_fields_never_disappear_or_reappear():
    resource = get_resource('procurement', 'orders')
    form = order_form(
        ('supplier', 'payment_terms', 'extension', 'notes', 'token'), hidden=('token',)
    )
    form.fields['payment_terms'].disabled = True
    layout = build_resource_form_layout(resource, form, [])
    tabs = layout['form_tabs']
    assert [tab['key'] for tab in tabs] == ['general', 'commercial', 'notes']
    assert [field.name for field in tabs[0]['fields']] == ['supplier', 'extension']
    assert Counter(field.name for tab in tabs for field in tab['fields']) == Counter(
        form.fields.keys() - {'token'}
    )
    assert tabs[1]['fields'][0].field is form.fields['payment_terms']
    assert tabs[1]['fields'][0].field.disabled is True
    assert list(form.fields) == ['supplier', 'payment_terms', 'extension', 'notes', 'token']


@pytest.mark.parametrize(
    'names', [('product', 'version'), ('supplier',), ('payment_terms', 'currency')]
)
@pytest.mark.parametrize('with_inline', [False, True])
def test_sparse_forms_keep_general_fallback_without_empty_panels(names, with_inline):
    form = order_form(names)
    child = {'key': 'items', 'title': 'Itens', 'available': False, 'formset': None}
    layout = build_resource_form_layout(
        get_resource('procurement', 'orders'), form, [child] if with_inline else []
    )
    if with_inline:
        assert [tab['key'] for tab in layout['form_tabs']] == ['general', 'inline-items']
        assert [field.name for field in layout['form_tabs'][0]['fields']] == list(names)
    else:
        assert layout == {'form_tabs': [], 'active_form_tab': ''}


@pytest.mark.parametrize(
    ('name', 'active'),
    [
        ('supplier', 'general'),
        ('payment_terms', 'commercial'),
        ('delivery_street', 'delivery'),
        ('notes', 'notes'),
        ('new_field', 'general'),
    ],
)
def test_field_errors_activate_their_domain_panel(name, active):
    names = ('supplier', 'payment_terms', 'delivery_street', 'notes', 'new_field')
    form = order_form(names, data={key: 'value' for key in names})
    assert form.is_valid()
    form.add_error(name, 'Erro de validação do domínio.')
    layout = build_resource_form_layout(get_resource('procurement', 'orders'), form, [])
    assert layout['active_form_tab'] == active
    assert [tab['key'] for tab in layout['form_tabs'] if tab['has_errors']] == [active]
    assert form[name].value() == 'value'


def test_non_field_errors_take_priority_in_general():
    form = order_form(('supplier', 'payment_terms'), data={'supplier': 'A', 'payment_terms': 'B'})
    assert form.is_valid()
    form.add_error('payment_terms', 'Condição inválida.')
    form.add_error(None, 'Conflito do registro.')
    layout = build_resource_form_layout(get_resource('procurement', 'orders'), form, [])
    assert layout['active_form_tab'] == 'general'
    assert all(tab['has_errors'] for tab in layout['form_tabs'])


def test_unavailable_inline_cannot_change_parent_field_groups():
    resource = get_resource('procurement', 'orders')
    form = build_resource_form(resource)()
    child = {'key': 'items', 'title': 'Itens', 'available': False, 'formset': None}
    without_child = build_resource_form_layout(resource, form, [])
    with_child = build_resource_form_layout(resource, form, [child])
    assert with_child['form_tabs'][:-1] == without_child['form_tabs']
    assert with_child['form_tabs'][-1]['inline'] is child
    assert with_child['form_tabs'][-1]['has_errors'] is False


def test_declarations_reference_only_real_editable_resources_and_unique_fields():
    from base.ui.form_tab_groups import FORM_TAB_GROUPS

    assert set(FORM_TAB_GROUPS) == {
        (get_resource(module, slug).app_label, slug) for module, slug, _ in DOMAIN_CASES
    }
    for module, slug, _ in DOMAIN_CASES:
        resource = get_resource(module, slug)
        assert not resource.read_only
        groups = FORM_TAB_GROUPS[resource.app_label, slug]
        keys = [key for key, _, _ in groups]
        assert keys[0] == 'general'
        assert len(keys) == len(set(keys))
        names = [name for _, _, fields in groups for name in fields]
        assert len(names) == len(set(names))
        allowed = set(build_resource_form(resource).base_fields) | set(
            build_resource_form(resource, update=True).base_fields
        )
        assert set(names) <= allowed


@pytest.mark.parametrize(
    ('module', 'slug'),
    [
        ('masters', 'units'),
        ('auxiliary', 'commercial-terms'),
        ('procurement', 'requisitions'),
        ('procurement', 'rfqs'),
        ('inventory', 'balances'),
        ('training', 'competencies'),
        ('integrations', 'connectors'),
    ],
)
def test_short_auxiliary_forms_remain_plain(module, slug):
    resource = get_resource(module, slug)
    assert build_resource_form_layout(resource, build_resource_form(resource)(), []) == {
        'form_tabs': [],
        'active_form_tab': '',
    }


@pytest.fixture
def procurement_case(db):
    from datetime import date
    from masters.models import BusinessPartner, Product, UnitOfMeasure
    from procurement.models import (
        PurchaseOrder,
        PurchaseOrderItem,
        PurchaseReceipt,
        PurchaseRequisition,
        QuotationRequest,
        SupplierQualificationEvent,
        SupplierQuotation,
    )

    unit = UnitOfMeasure.objects.create(code='DT-KG', name='Quilograma sintético', symbol='kg')
    product = Product.objects.create(code='DT-MAT', description='Insumo sintético', unit=unit)
    supplier = BusinessPartner.objects.create(
        code='DT-SUP', legal_name='Fornecedor sintético de abas', partner_type='supplier'
    )
    order = PurchaseOrder.objects.create(supplier=supplier, issue_date=date(2026, 1, 10))
    item = PurchaseOrderItem.objects.create(
        order=order, product=product, quantity=2, unit=unit, unit_price=5
    )
    receipt = PurchaseReceipt.objects.create(order=order)
    requisition = PurchaseRequisition.objects.create(justification='QA sintético de abas')
    rfq = QuotationRequest.objects.create(requisition=requisition)
    quotation = SupplierQuotation.objects.create(
        rfq=rfq, supplier=supplier, quoted_quantity=2, unit_price=5
    )
    event = SupplierQualificationEvent.objects.create(
        supplier=supplier,
        event_type='document',
        event_date=date(2026, 1, 10),
        description='Verificação sintética documental',
    )
    return SimpleNamespace(
        order=order,
        item=item,
        receipt=receipt,
        quotation=quotation,
        event=event,
        supplier=supplier,
        product=product,
        unit=unit,
    )


def edit_url(module, slug, obj):
    return reverse(
        'app:resource_edit',
        kwargs={
            'module_slug': module,
            'resource_slug': slug,
            'pk': obj.pk,
        },
    )


def assert_rendered_once(response):
    assert response.status_code == 200
    form = response.context['form']
    html = response.content.decode()
    for field in form:
        assert html.count(f'name="{field.html_name}"') == 1
    for inline in response.context['inline_formsets']:
        if inline['available']:
            for field in inline['formset'].management_form:
                assert html.count(f'name="{field.html_name}"') == 1
            for child in inline['formset']:
                for field in child.hidden_fields():
                    assert html.count(f'name="{field.html_name}"') == 1


@pytest.mark.parametrize(
    ('slug', 'attribute', 'keys'),
    [
        ('orders', 'order', ('general', 'commercial', 'delivery', 'notes', 'inline-items')),
        ('receipts', 'receipt', ('general', 'quality-fiscal', 'notes', 'inline-items')),
        ('supplier-quotations', 'quotation', ('general', 'commercial', 'delivery', 'notes')),
        ('supplier-qualification-events', 'event', ('general', 'qualification', 'address')),
    ],
)
def test_procurement_update_http_keeps_groups_and_unique_controls(
    domain_admin, procurement_case, slug, attribute, keys
):
    obj = getattr(procurement_case, attribute)
    before = type(obj).objects.values().get(pk=obj.pk)
    response = domain_admin.get(edit_url('procurement', slug, obj))
    assert_rendered_once(response)
    assert tuple(tab['key'] for tab in response.context['form_tabs']) == keys
    assert type(obj).objects.values().get(pk=obj.pk) == before


def order_payload(case):
    return {
        'supplier': str(case.supplier.pk),
        'status': 'draft',
        'issue_date': '2026-01-10',
        'currency': 'BRL',
        'freight_amount': '0',
        'total_amount': '10',
        'payment_terms': '30 dias',
        'delivery_street': 'Rua sintética de QA',
        'expected_delivery_date': '2026-01-20',
        'notes': 'Notas preservadas entre abas',
        'items-TOTAL_FORMS': '1',
        'items-INITIAL_FORMS': '0',
        'items-MIN_NUM_FORMS': '0',
        'items-MAX_NUM_FORMS': '1000',
        'items-0-product': str(case.product.pk),
        'items-0-quantity': '2',
        'items-0-unit': str(case.unit.pk),
        'items-0-unit_price': '5',
        'items-0-tax_amount': '0',
        'items-0-expected_delivery_date': '2026-01-20',
    }


@pytest.mark.parametrize(
    ('field', 'value', 'active'),
    [
        ('supplier', '', 'general'),
        ('freight_amount', '-1', 'commercial'),
        ('expected_delivery_date', '2026-01-01', 'delivery'),
        ('items-0-quantity', '-1', 'inline-items'),
    ],
)
def test_purchase_order_invalid_http_opens_exact_panel_and_rolls_back(
    domain_admin, procurement_case, field, value, active
):
    from procurement.models import PurchaseOrder, PurchaseOrderItem

    payload = order_payload(procurement_case)
    payload[field] = value
    before = (list(PurchaseOrder.objects.values()), list(PurchaseOrderItem.objects.values()))
    response = domain_admin.post(create_url('procurement', 'orders'), payload)
    assert_rendered_once(response)
    assert response.context['active_form_tab'] == active
    assert response.context['form']['notes'].value() == payload['notes']
    assert next(tab for tab in response.context['form_tabs'] if tab['key'] == active)['has_errors']
    assert (
        list(PurchaseOrder.objects.values()),
        list(PurchaseOrderItem.objects.values()),
    ) == before


def test_purchase_order_valid_create_and_edit_preserve_single_transaction(
    domain_admin, procurement_case
):
    from procurement.models import PurchaseOrder

    response = domain_admin.post(
        create_url('procurement', 'orders'), order_payload(procurement_case)
    )
    assert response.status_code == 302
    obj = PurchaseOrder.objects.exclude(pk=procurement_case.order.pk).get()
    assert obj.payment_terms == '30 dias'
    assert obj.delivery_street == 'Rua sintética de QA'
    assert obj.notes == 'Notas preservadas entre abas'
    item = obj.items.get()
    assert item.quantity == 2
    payload = order_payload(procurement_case) | {
        'items-INITIAL_FORMS': '1',
        'items-0-id': str(item.pk),
        'items-0-order': str(obj.pk),
        'notes': 'Edição com abas',
    }
    response = domain_admin.post(edit_url('procurement', 'orders', obj), payload)
    assert response.status_code == 302
    obj.refresh_from_db()
    assert obj.notes == 'Edição com abas'
    assert obj.items.count() == 1
    assert obj.items.get().pk == item.pk


@pytest.mark.permission_strict
@pytest.mark.parametrize('slug', ['orders', 'receipts'])
def test_procurement_parent_only_permissions_do_not_reveal_or_accept_children(
    client, procurement_case, slug
):
    from django.contrib.auth.models import Permission

    resource = get_resource('procurement', slug)
    user = get_user_model().objects.create_user(
        username=f'domain-limited-{slug}', email='limited-tabs@example.com'
    )
    user.user_permissions.set(
        Permission.objects.filter(
            content_type__app_label='procurement',
            codename__in=[
                f'{action}_{resource.model_name}' for action in ('view', 'add', 'change')
            ],
        )
    )
    client.force_login(user)
    obj = procurement_case.order if slug == 'orders' else procurement_case.receipt
    for url in (create_url('procurement', slug), edit_url('procurement', slug, obj)):
        response = client.get(url)
        assert response.status_code == 200
        assert response.context['inline_formsets'][0]['available'] is False
        assert response.context['form_tabs'][-1]['inline']['available'] is False
        html = response.content.decode()
        assert 'name="items-TOTAL_FORMS"' not in html
        assert 'name="items-0-product"' not in html
        assert Counter(
            field.name for tab in response.context['form_tabs'] for field in tab['fields']
        ) == Counter(field.name for field in response.context['form'].visible_fields())
    payload = (
        order_payload(procurement_case)
        if slug == 'orders'
        else {
            'order': str(procurement_case.order.pk),
            'status': 'draft',
            'quality_status': 'pending',
            'stock_entry_status': 'pending',
            'items-TOTAL_FORMS': '0',
            'items-INITIAL_FORMS': '0',
        }
    )
    before = list(resource.model.objects.values())
    response = client.post(create_url('procurement', slug), payload)
    assert response.status_code == 403
    assert list(resource.model.objects.values()) == before


def test_financial_service_controls_remain_absent_from_domain_tabs(domain_admin):
    from finance.models import FinancialTitle

    response = domain_admin.get(create_url('finance', 'titles'))
    assert_rendered_once(response)
    names = {field.name for tab in response.context['form_tabs'] for field in tab['fields']}
    assert not FinancialTitle.SERVICE_FIELDS.intersection(names)
    form = response.context['form']
    assert names == {field.name for field in form.visible_fields()}
    hidden = {field.name: field for field in form.hidden_fields()}
    assert names.isdisjoint(hidden)
    assert names | hidden.keys() == set(form.fields)
    assert hidden['title_number'].field.disabled is True
    assert hidden['title_number'].field.widget.is_hidden is True
    assert response.content.decode().count('name="title_number"') == 1
    assert not FinancialTitle.SERVICE_FIELDS.intersection(form.fields)


@pytest.mark.parametrize(
    ('field', 'value'),
    [
        ('nfe_access_key', '1' * 45),
        ('quality_status', 'invalid'),
        ('fiscal_received_at', 'not-a-date'),
    ],
)
def test_receipt_invalid_quality_fiscal_data_selects_quality_panel(
    domain_admin, procurement_case, field, value
):
    from procurement.models import PurchaseReceipt

    payload = {
        'order': str(procurement_case.order.pk),
        'status': 'draft',
        'quality_status': 'pending',
        'stock_entry_status': 'pending',
        'notes': 'Recebimento sintético preservado',
        'items-TOTAL_FORMS': '0',
        'items-INITIAL_FORMS': '0',
    } | {field: value}
    before = list(PurchaseReceipt.objects.values())
    response = domain_admin.post(create_url('procurement', 'receipts'), payload)
    assert_rendered_once(response)
    assert response.context['active_form_tab'] == 'quality-fiscal'
    assert response.context['form']['notes'].value() == payload['notes']
    assert list(PurchaseReceipt.objects.values()) == before


def test_missing_procurement_management_form_opens_items(domain_admin, procurement_case):
    payload = order_payload(procurement_case)
    del payload['items-TOTAL_FORMS']
    response = domain_admin.post(create_url('procurement', 'orders'), payload)
    assert response.status_code == 200
    assert response.context['active_form_tab'] == 'inline-items'
    assert response.context['inline_formsets'][0]['formset'].non_form_errors()


def test_receipt_valid_create_and_edit_do_not_post_stock(domain_admin, procurement_case):
    from procurement.models import PurchaseReceipt
    from inventory.models import StockMovement

    payload = {
        'order': str(procurement_case.order.pk),
        'status': 'draft',
        'quality_status': 'pending',
        'stock_entry_status': 'pending',
        'fiscal_document_number': 'NF-SINTETICA-ABAS',
        'notes': 'Recebimento agrupado',
        'items-TOTAL_FORMS': '0',
        'items-INITIAL_FORMS': '0',
    }
    before_movements = list(StockMovement.objects.values())
    response = domain_admin.post(create_url('procurement', 'receipts'), payload)
    assert response.status_code == 302
    obj = PurchaseReceipt.objects.exclude(pk=procurement_case.receipt.pk).get()
    assert obj.status == 'draft' and obj.stock_entry_status == 'pending'
    assert obj.fiscal_document_number == payload['fiscal_document_number']
    response = domain_admin.post(
        edit_url('procurement', 'receipts', obj), payload | {'notes': 'Recebimento editado'}
    )
    assert response.status_code == 302
    obj.refresh_from_db()
    assert obj.notes == 'Recebimento editado'
    assert obj.stock_entry_status == 'pending'
    assert list(StockMovement.objects.values()) == before_movements
