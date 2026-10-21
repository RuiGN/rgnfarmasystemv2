"""Dependencies proved by domain clean(), not by coincidentally matching FK names."""

import json

import pytest
from django import forms
from django.apps import apps

from base.ui.forms import build_resource_form
from base.ui.registry import ResourceConfig
from base.ui.related_fields import configure_related_fields, validate_related_fields
from tests.test_receipt_inline_dependencies import receipt_case as receipt_case


def resource_form(model, fields, **kwargs):
    resource = ResourceConfig(
        slug='proven-related', label='Teste', model=model, list_display=(), form_fields=fields
    )
    return build_resource_form(resource)(**kwargs)


def metadata(form, name):
    return json.loads(str(form.fields[name].widget.attrs['data-related-rules']))


@pytest.mark.parametrize(
    ('model_label', 'controller'),
    (
        ('procurement.PurchaseReceiptItem', 'order_item'),
        ('procurement.PurchaseOrderItem', 'requisition_item'),
        ('procurement.PurchaseRequisitionItem', 'mrp_suggestion'),
    ),
)
def test_purchase_item_controls_product_without_database(model_label, controller):
    model = apps.get_model(model_label)
    form = resource_form(model, ('product', controller), prefix='items-__prefix__')
    rules = form._related_field_rules.get('product', [])
    assert any(rule['field'] == controller for rule in rules)
    assert rules[0]['controller'] == f'items-__prefix__-{controller}'
    assert rules[0]['path'] == 'pk'


@pytest.mark.django_db
def test_receipt_product_metadata_and_forged_post_keep_model_clean_and_units(
    django_assert_num_queries,
):
    from masters.models import BusinessPartner, Product, UnitOfMeasure
    from procurement.models import (
        PurchaseOrder,
        PurchaseOrderItem,
        PurchaseReceipt,
        PurchaseReceiptItem,
    )

    unit = UnitOfMeasure.objects.create(code='PROVEN-KG', name='Kg', symbol='kg')
    other_unit = UnitOfMeasure.objects.create(code='PROVEN-G', name='Grama', symbol='g')
    products = [Product.objects.create(description=f'Material {i}', unit=unit) for i in range(2)]
    supplier = BusinessPartner.objects.create(
        legal_name='Synthetic supplier', partner_type='supplier'
    )
    order = PurchaseOrder.objects.create(supplier=supplier)
    item = PurchaseOrderItem.objects.create(
        order=order, product=products[0], quantity=10, unit=unit, unit_price=1
    )
    receipt = PurchaseReceipt.objects.create(order=order)
    fields = ('receipt', 'order_item', 'product', 'unit', 'received_quantity')
    with django_assert_num_queries(0):
        form = resource_form(PurchaseReceiptItem, fields)
    values = metadata(form, 'product')[0]['values']
    assert values[str(products[0].pk)] == [str(item.pk)]
    assert values[str(products[1].pk)] == []
    assert other_unit.pk in form.fields['unit'].queryset.values_list('pk', flat=True)
    data = dict(
        receipt=receipt.pk,
        order_item=item.pk,
        product=products[0].pk,
        unit=other_unit.pk,
        received_quantity='1',
    )
    valid = resource_form(PurchaseReceiptItem, fields, data=data)
    assert valid.is_valid(), valid.errors
    data['product'] = products[1].pk
    invalid = resource_form(PurchaseReceiptItem, fields, data=data)
    assert not invalid.is_valid()
    assert 'product' in invalid.errors
    assert invalid.instance.product_id == products[1].pk  # model clean was not bypassed
    with pytest.raises(ValueError):
        invalid.save()
    assert not PurchaseReceiptItem.objects.exists()


@pytest.fixture
def production_pair(db):
    from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula
    from inventory.models import StockLot
    from masters.models import Product, UnitOfMeasure
    from production.models import ProductionOrder

    unit = UnitOfMeasure.objects.create(code='PROVEN-P', name='Kg', symbol='kg')
    product = Product.objects.create(description='Creme sintético', unit=unit, status='approved')
    route = ManufacturingRoute.objects.create(product=product, version=1)
    result = []
    for i in range(2):
        material = Product.objects.create(
            description=f'Emoliente {i}', unit=unit, status='approved'
        )
        formula = MasterFormula.objects.create(
            product=product, version=i + 1, batch_size=1, batch_unit=unit
        )
        component = FormulaComponent.objects.create(
            formula=formula, material=material, line_number=10, quantity=1, unit=unit
        )
        lot = StockLot.objects.create(product=material, lot_number=f'PROVEN-{i}')
        order = ProductionOrder.objects.create(
            product=product, formula=formula, route=route, planned_quantity=1, unit=unit
        )
        result.append(
            dict(
                unit=unit,
                material=material,
                formula=formula,
                component=component,
                lot=lot,
                order=order,
            )
        )
    return result


def test_consumption_dependencies_are_constructed_without_database():
    from production.models import MaterialConsumption

    form = resource_form(MaterialConsumption, ('order', 'component', 'material', 'stock_lot'))
    rules = form._related_field_rules
    assert rules['component'][0]['field'] == 'order'
    assert rules['component'][0]['path'] == 'formula'
    assert rules['material'][0]['field'] == 'component'
    assert rules['stock_lot'][0]['field'] == 'material'


def test_consumption_metadata_and_post_use_order_formula_component_material(production_pair):
    from production.models import MaterialConsumption

    a, b = production_pair
    fields = ('order', 'component', 'material', 'stock_lot', 'unit')
    form = resource_form(MaterialConsumption, fields, prefix='rows-__prefix__')
    rules = metadata(form, 'component')
    assert rules[0]['values'][str(a['component'].pk)] == [str(a['order'].pk)]
    assert set(metadata(form, 'material')[0]['values'][str(a['material'].pk)]) == {
        str(a['component'].pk),
        '',
    }
    values = dict(
        order=a['order'].pk,
        component=a['component'].pk,
        material=a['material'].pk,
        stock_lot=a['lot'].pk,
        unit=a['unit'].pk,
    )
    good = resource_form(MaterialConsumption, fields, data=values)
    assert good.is_valid(), good.errors
    for field, foreign in (
        ('component', b['component']),
        ('material', b['material']),
        ('stock_lot', b['lot']),
    ):
        invalid = resource_form(MaterialConsumption, fields, data={**values, field: foreign.pk})
        assert not invalid.is_valid()
        assert field in invalid.errors
        with pytest.raises(ValueError):
            invalid.save()
    assert not MaterialConsumption.objects.exists()


def test_consumption_inline_uses_validated_parent_formula_after_hidden_injection(production_pair):
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    from base.ui.registry import InlineResourceConfig
    from base.ui.views import _build_inline_formset
    from production.models import MaterialConsumption, ProductionOrder

    a, b = production_pair
    parent = resource_form(
        ProductionOrder,
        ('formula',),
        instance=a['order'],
        data={'parent-formula': b['formula'].pk},
        prefix='parent',
    )
    assert parent.is_valid(), parent.errors
    inline = InlineResourceConfig(
        'rows',
        'Consumos',
        MaterialConsumption,
        'order',
        ('component', 'material', 'stock_lot', 'unit'),
    )
    resource = ResourceConfig(
        'proven-orders', 'Ordens', ProductionOrder, (), form_fields=('formula',), inlines=(inline,)
    )
    request = RequestFactory().get('/')
    request.user = get_user_model()(is_staff=True, is_superuser=True, is_active=True)
    payload = {
        'rows-TOTAL_FORMS': '1',
        'rows-INITIAL_FORMS': '0',
        'rows-0-order': a['order'].pk,
        'rows-0-component': a['component'].pk,
        'rows-0-material': a['material'].pk,
        'rows-0-stock_lot': a['lot'].pk,
        'rows-0-unit': a['unit'].pk,
    }
    formset = _build_inline_formset(
        request, resource, inline, instance=parent.instance, parent_form=parent, data=payload
    )
    empty = formset.empty_form
    assert empty.fields['order'].widget.is_hidden
    rules = metadata(empty, 'component')
    assert rules[0]['controller'] == 'parent-formula'
    assert rules[0]['values'][str(a['component'].pk)] == [str(a['formula'].pk)]
    assert not formset.is_valid()
    assert 'component' in formset.forms[0].errors
    payload.update(
        {
            'rows-0-component': b['component'].pk,
            'rows-0-material': b['material'].pk,
            'rows-0-stock_lot': b['lot'].pk,
        }
    )
    valid = _build_inline_formset(
        request, resource, inline, instance=parent.instance, parent_form=parent, data=payload
    )
    assert valid.is_valid(), valid.errors
    payload['rows-0-order'] = b['order'].pk
    forged = _build_inline_formset(
        request, resource, inline, instance=parent.instance, parent_form=parent, data=payload
    )
    assert not forged.is_valid()
    assert 'order' in forged.forms[0].errors


@pytest.mark.parametrize(
    ('model_label', 'controller', 'controller_path'),
    (
        ('quality.QualityAnalysis', 'sample', 'product'),
        ('quality.QualityResult', 'analysis', 'sample__product'),
    ),
)
def test_quality_indirect_product_dependency_without_database(
    model_label, controller, controller_path
):
    from base.ui.related_fields import related_field_specs

    form = resource_form(apps.get_model(model_label), ('specification', controller))
    assert ('specification', controller, 'product', False, controller_path) in related_field_specs(
        form
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('model_label', 'controller'),
    (
        ('quality.QualityAnalysis', 'sample'),
        ('quality.QualityResult', 'analysis'),
    ),
)
def test_quality_indirect_map_matches_product_not_exact_sample(
    model_label, controller, django_assert_num_queries
):
    from quality.models import QualityAnalysis, QualitySample
    from tests.test_quality import create_quality_item, create_specification

    unit, product, lot = create_quality_item('PROVEN-A')
    other_unit, other_product, other_lot = create_quality_item('PROVEN-B')
    spec = create_specification(product, unit, 'PROVEN-A')
    other_spec = create_specification(other_product, other_unit, 'PROVEN-B')
    samples = [
        QualitySample.objects.create(product=product, stock_lot=lot, quantity=1) for _ in range(2)
    ]
    samples.append(
        QualitySample.objects.create(product=other_product, stock_lot=other_lot, quantity=1)
    )
    analyses = [QualityAnalysis.objects.create(sample=sample) for sample in samples]
    controllers = samples if controller == 'sample' else analyses
    model = apps.get_model(model_label)
    fields = (
        ('specification', controller)
        if controller == 'sample'
        else ('specification', controller, 'parameter_name', 'numeric_result')
    )
    with django_assert_num_queries(0):
        form = resource_form(model, fields, prefix='inline-__prefix__')
    with django_assert_num_queries(2):
        values = metadata(form, 'specification')[0]['values']
    assert set(values[str(spec.pk)]) == {str(row.pk) for row in controllers[:2]}
    assert values[str(other_spec.pk)] == [str(controllers[2].pk)]
    data = {
        controller: controllers[1].pk,
        'specification': spec.pk,
        'parameter_name': 'pH',
        'numeric_result': '7',
    }
    good = resource_form(model, fields, data=data)
    assert good.is_valid(), good.errors
    data['specification'] = other_spec.pk
    invalid = resource_form(model, fields, data=data)
    assert not invalid.is_valid()
    assert 'specification' in invalid.errors
    with pytest.raises(ValueError):
        invalid.save()


LOT_PRODUCT_OWNERS = (
    'changes.ChangeStockAssessment',
    'crm.CustomerComplaint',
    'deviations.QualityEvent',
    'qa.LotRelease',
    'qa.QualityBlock',
    'quality.AnalyticalSpecification',
    'quality.QualitySample',
    'quality.QualityDocument',
    'recalls.MarketComplaint',
    'recalls.ProductReturn',
    'recalls.RecallCampaign',
)


@pytest.mark.parametrize('model_label', LOT_PRODUCT_OWNERS + ('inventory.StockBalance',))
def test_proven_lot_product_edges_without_database(model_label):
    model = apps.get_model(model_label)
    lot_name = 'lot' if model_label == 'inventory.StockBalance' else 'stock_lot'
    form = resource_form(model, (lot_name, 'product'))
    assert form._related_field_rules[lot_name][0]['field'] == 'product'
    assert form._related_field_rules[lot_name][0]['path'] == 'product'


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('model_label', 'lot_name'),
    (
        ('inventory.StockBalance', 'lot'),
        ('quality.QualitySample', 'stock_lot'),
    ),
)
def test_lot_product_choices_and_post_match_domain(model_label, lot_name):
    from tests.test_quality import create_quality_item

    unit, product, lot = create_quality_item('PROVEN-LA')
    other_unit, other_product, other_lot = create_quality_item('PROVEN-LB')
    model = apps.get_model(model_label)
    fields = ('product', lot_name)
    data = {'product': product.pk, lot_name: lot.pk}
    if model_label == 'inventory.StockBalance':
        from tests.test_inventory import create_stock_address

        warehouse, location = create_stock_address('PROVEN-LOT')
        fields += ('warehouse', 'location', 'unit')
        data.update(warehouse=warehouse.pk, location=location.pk, unit=unit.pk)
    form = resource_form(model, fields)
    values = metadata(form, lot_name)[0]['values']
    assert values[str(lot.pk)] == [str(product.pk)]
    assert values[str(other_lot.pk)] == [str(other_product.pk)]
    good = resource_form(model, fields, data=data)
    assert good.is_valid(), good.errors
    bad = resource_form(model, fields, data={**data, lot_name: other_lot.pk})
    assert not bad.is_valid()
    assert lot_name in bad.errors
    with pytest.raises(ValueError):
        bad.save()


@pytest.mark.django_db
def test_optional_component_and_requisition_controller_do_not_require_a_selection(production_pair):
    from procurement.models import PurchaseOrderItem
    from production.models import MaterialConsumption

    a, _b = production_pair
    form = resource_form(
        MaterialConsumption,
        ('order', 'component', 'material', 'unit'),
        data={
            'order': a['order'].pk,
            'material': a['material'].pk,
            'unit': a['unit'].pk,
        },
    )
    assert form.is_valid(), form.errors
    assert '' in metadata(form, 'material')[0]['values'][str(a['material'].pk)]
    purchase = resource_form(PurchaseOrderItem, ('product', 'requisition_item'))
    assert '' in metadata(purchase, 'product')[0]['values'][str(a['material'].pk)]


@pytest.mark.django_db
def test_optional_lot_product_controller_preserves_domain_null_semantics():
    from qa.models import QualityBlock
    from tests.test_quality import create_quality_item

    _unit, _product, lot = create_quality_item('PROVEN-NULL')
    form = resource_form(QualityBlock, ('product', 'stock_lot'), data={'stock_lot': lot.pk})
    assert form.is_valid(), form.errors
    assert '' in metadata(form, 'stock_lot')[0]['values'][str(lot.pk)]


@pytest.mark.parametrize(
    ('model_label', 'dependent'),
    (
        ('fiscal.TaxRule', 'tax_situation'),
        ('fiscal.FiscalTax', 'tax_rule'),
    ),
)
def test_fiscal_enum_dependencies_are_lazy_without_database(model_label, dependent):
    form = resource_form(apps.get_model(model_label), (dependent, 'tax_kind'))
    assert form._related_field_rules[dependent][0]['field'] == 'tax_kind'
    assert form._related_field_rules[dependent][0]['path'] == 'tax_kind'


@pytest.mark.django_db
def test_tax_situation_and_tax_rule_match_tax_kind_on_server_and_in_metadata():
    from fiscal.models import FiscalNCM, FiscalOperationCode, TaxRule, TaxSituation

    ncm = FiscalNCM.objects.create(code='33049990')
    cfop = FiscalOperationCode.objects.create(code='5102', direction='outbound')
    situations = [
        TaxSituation.objects.create(code=f'P-{kind}', tax_kind=kind, regime_kind='cst')
        for kind in ('icms', 'pis')
    ]
    rules = [
        TaxRule.objects.create(
            name=f'PROVEN-{kind}',
            tax_kind=kind,
            tax_situation=situation,
            effective_from='2026-01-01',
            ncm=ncm,
            cfop=cfop,
        )
        for kind, situation in zip(('icms', 'pis'), situations, strict=True)
    ]
    fields = ('tax_kind', 'tax_situation')
    form = resource_form(TaxRule, fields)
    assert metadata(form, 'tax_situation')[0]['values'][str(situations[0].pk)] == ['icms']
    good = resource_form(
        TaxRule, fields, data={'tax_kind': 'icms', 'tax_situation': situations[0].pk}
    )
    assert good.is_valid(), good.errors
    bad = resource_form(
        TaxRule, fields, data={'tax_kind': 'icms', 'tax_situation': situations[1].pk}
    )
    assert not bad.is_valid()
    assert 'tax_situation' in bad.errors
    from fiscal.models import FiscalTax

    form = resource_form(FiscalTax, ('tax_rule', 'tax_kind'))
    assert metadata(form, 'tax_rule')[0]['values'][str(rules[1].pk)] == ['pis']


@pytest.mark.django_db
def test_direct_maps_do_not_disclose_unauthorized_controller_values(django_assert_num_queries):
    from inventory.models import StockLot
    from masters.models import Product
    from quality.models import QualitySample
    from tests.test_quality import create_quality_item

    _unit, product, lot = create_quality_item('PROVEN-AUTH-A')
    _other_unit, other_product, other_lot = create_quality_item('PROVEN-AUTH-B')

    allowed_product_pk = product.pk

    class Restricted(forms.ModelForm):
        product = forms.ModelChoiceField(queryset=Product.objects.filter(pk=allowed_product_pk))
        stock_lot = forms.ModelChoiceField(queryset=StockLot.objects.all())

        class Meta:
            model = QualitySample
            fields = ('product', 'stock_lot')

    with django_assert_num_queries(0):
        form = Restricted()
        configure_related_fields(form)
    with django_assert_num_queries(1):
        values = metadata(form, 'stock_lot')[0]['values']
    assert values[str(lot.pk)] == [str(product.pk)]
    assert values.get(str(other_lot.pk), []) == []
    assert set(form.fields['stock_lot'].queryset.values_list('pk', flat=True)) == {
        lot.pk,
        other_lot.pk,
    }


def test_consumption_component_labels_are_not_n_plus_one(
    production_pair, django_assert_num_queries
):
    from production.models import MaterialConsumption

    form = resource_form(MaterialConsumption, ('order', 'component', 'material', 'stock_lot'))
    with django_assert_num_queries(1):
        labels = [str(label) for _value, label in form.fields['component'].choices]
    assert len(labels) == 3


@pytest.mark.parametrize(
    ('model_label', 'dependent', 'controller', 'path'),
    (
        ('production.ProductionOutput', 'product', 'order', 'pk'),
        ('production.ProductionOperationExecution', 'route_step', 'order', 'route'),
        ('production.ProductionLaborEntry', 'operation_execution', 'order', 'order'),
    ),
)
def test_other_explicit_production_clean_equalities_without_database(
    model_label, dependent, controller, path
):
    form = resource_form(apps.get_model(model_label), (dependent, controller))
    assert any(
        rule['field'] == controller and rule['path'] == path
        for rule in form._related_field_rules[dependent]
    )


def test_inline_identity_controller_uses_authoritative_parent_not_submitted_hidden(production_pair):
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    from base.ui.registry import InlineResourceConfig
    from base.ui.views import _build_inline_formset
    from production.models import (
        ProductionLaborEntry,
        ProductionOperationExecution,
        ProductionOrder,
    )

    a, b = production_pair
    operations = [
        ProductionOperationExecution.objects.create(
            order=row['order'], sequence=10, operation='Mistura'
        )
        for row in (a, b)
    ]
    request = RequestFactory().get('/')
    request.user = get_user_model()(is_staff=True, is_superuser=True, is_active=True)
    inline = InlineResourceConfig(
        'labor', 'Mão de obra', ProductionLaborEntry, 'order', ('operation_execution',)
    )
    resource = ResourceConfig(
        'proven-orders', 'Ordens', ProductionOrder, (), form_fields=('formula',), inlines=(inline,)
    )
    parent = resource_form(ProductionOrder, ('formula',), instance=a['order'])
    formset = _build_inline_formset(
        request, resource, inline, instance=parent.instance, parent_form=parent
    )
    form = formset.empty_form
    rules = metadata(form, 'operation_execution')
    assert rules[0]['controller'] == 'labor-__prefix__-order'
    assert rules[0]['values'][str(operations[0].pk)] == [str(a['order'].pk)]
    assert rules[0]['values'][str(operations[1].pk)] == []
    form.cleaned_data = {'operation_execution': operations[1], 'order': b['order']}
    form._errors = forms.utils.ErrorDict()
    validate_related_fields(form, form.cleaned_data)
    assert 'operation_execution' in form.errors


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_receipt_inline_http_rejects_product_foreign_to_selected_order_item(receipt_case):
    from masters.models import Product
    from procurement.models import PurchaseReceiptItem

    client, receipt, _orders, items, address, payload = receipt_case
    other = Product.objects.create(
        description='Outro emoliente sintético', unit=items[0].unit, status='approved'
    )
    payload['items-0-product'] = str(other.pk)
    response = client.post(address, payload)
    assert response.status_code == 200
    form = response.context['inline_formsets'][0]['formset'].forms[0]
    assert 'product' in form.errors
    assert not PurchaseReceiptItem.objects.filter(receipt=receipt).exists()
