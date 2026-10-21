"""Contracts for authorized, progressively enhanced resource FK choices."""

import pytest
from django import forms

from base.ui.forms import build_resource_form
from base.ui.registry import ResourceConfig
from masters.models import MasterCategory, Product

pytestmark = pytest.mark.django_db


def resource_form(model, fields, **kwargs):
    resource = ResourceConfig(
        slug='related-test', label='Teste', model=model, list_display=(), form_fields=fields
    )
    return build_resource_form(resource)(**kwargs)


def category(name, kind, parent=None):
    return MasterCategory.objects.create(name=name, kind=kind, parent=parent)


def test_category_kind_filters_parent_in_html_and_rejects_forged_post():
    family = category('Família', 'family')
    form_kind = category('Forma', 'cosmetic_form')
    form = resource_form(
        MasterCategory,
        ('name', 'kind', 'parent'),
        data={'name': 'Filha', 'kind': 'category', 'parent': form_kind.pk},
    )
    assert 'data-related-rules' in str(form['parent'])
    assert not form.is_valid()
    assert 'parent' in form.errors
    allowed = resource_form(
        MasterCategory,
        ('name', 'kind', 'parent'),
        data={'name': 'Filha', 'kind': 'category', 'parent': family.pk},
    )
    assert allowed.is_valid(), allowed.errors


def test_product_category_fields_have_exact_kind_choices():
    kinds = {
        'category': 'category',
        'product_line': 'product_line',
        'cosmetic_form': 'cosmetic_form',
        'application_area': 'application_area',
    }
    rows = {kind: category(kind, kind) for kind in (*kinds.values(), 'family')}
    form = resource_form(Product, tuple(kinds))
    for field_name, expected_kind in kinds.items():
        field = form.fields[field_name]
        assert isinstance(field, forms.ModelChoiceField)
        assert list(field.queryset.values_list('pk', flat=True)) == [rows[expected_kind].pk]


class RelatedActionForm(forms.Form):
    """Same two hooks expected from the action/inline builders."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from base.ui.related_fields import configure_related_fields

        configure_related_fields(self)

    def clean(self):
        from base.ui.related_fields import validate_related_fields

        return validate_related_fields(self, super().clean())


def test_prefixed_geography_preserves_authorized_queryset_and_rejects_post(
    django_assert_num_queries,
):
    import json
    from auxiliary.models import City, Country, StateProvince

    br = Country.objects.create(name='Brasil')
    pt = Country.objects.create(name='Portugal')
    sp = StateProvince.objects.create(name='São Paulo', country=br)
    lx = StateProvince.objects.create(name='Lisboa', country=pt)
    hidden = StateProvince.objects.create(name='Não autorizado', country=br)
    city = City.objects.create(name='São Paulo', state=sp)

    class Address(RelatedActionForm):
        shipping_country_ref = forms.ModelChoiceField(queryset=Country.objects.all())
        shipping_state_ref = forms.ModelChoiceField(
            queryset=StateProvince.objects.exclude(pk=hidden.pk)
        )
        shipping_city_ref = forms.ModelChoiceField(queryset=City.objects.all(), required=False)

    with django_assert_num_queries(0):
        initial = Address(prefix='rows-2')
    with django_assert_num_queries(2):
        rules = json.loads(
            str(initial.fields['shipping_state_ref'].widget.attrs['data-related-rules'])
        )
        str(initial.fields['shipping_city_ref'].widget.attrs['data-related-rules'])
    assert rules[0]['controller'] == 'rows-2-shipping_country_ref'
    assert str(hidden.pk) not in rules[0]['values']
    assert set(initial.fields['shipping_state_ref'].queryset.values_list('pk', flat=True)) == {
        sp.pk,
        lx.pk,
    }
    data = {'rows-2-shipping_country_ref': br.pk, 'rows-2-shipping_state_ref': lx.pk}
    invalid = Address(data, prefix='rows-2')
    assert not invalid.is_valid()
    assert 'shipping_state_ref' in invalid.errors
    data['rows-2-shipping_state_ref'] = hidden.pk
    assert not Address(data, prefix='rows-2').is_valid()
    data['rows-2-shipping_state_ref'] = sp.pk
    data['rows-2-shipping_city_ref'] = city.pk
    valid = Address(data, prefix='rows-2')
    assert valid.is_valid(), valid.errors


def test_category_edit_excludes_self_descendants_even_through_unauthorized_nodes():
    import json
    from base.ui.related_fields import configure_related_fields

    root = category('Root', 'family')
    hidden = category('Hidden child', 'category', root)
    descendant = category('Grandchild', 'category', hidden)
    sibling = category('Sibling', 'group')
    form = resource_form(MasterCategory, ('name', 'kind', 'parent'), instance=root)
    assert set(form.fields['parent'].queryset.values_list('pk', flat=True)) == {sibling.pk}

    # A separately narrowed queryset never regains excluded ancestors/options.
    class Restricted(forms.ModelForm):
        parent = forms.ModelChoiceField(
            queryset=MasterCategory.objects.exclude(pk=hidden.pk), required=False
        )

        class Meta:
            model = MasterCategory
            fields = ('kind', 'parent')

    restricted = Restricted(instance=root)
    configure_related_fields(restricted)
    rules = json.loads(str(restricted.fields['parent'].widget.attrs['data-related-rules']))
    assert str(descendant.pk) not in rules[0]['values']
    invalid = resource_form(
        MasterCategory,
        ('name', 'kind', 'parent'),
        instance=root,
        data={'name': 'Root', 'kind': 'family', 'parent': descendant.pk},
    )
    assert not invalid.is_valid()
    assert 'parent' in invalid.errors


def test_unchanged_legacy_parent_survives_but_new_incompatible_link_fails():
    parent = category('Legado', 'presentation')
    child = category('Filha', 'category', parent)
    fields = ('name', 'kind', 'parent')
    data = {'name': 'Nome atualizado', 'kind': 'category', 'parent': parent.pk}
    edit = resource_form(MasterCategory, fields, instance=child, data=data)
    assert edit.is_valid(), edit.errors
    new = resource_form(MasterCategory, fields, data=data)
    assert not new.is_valid()
    data['kind'] = 'cosmetic_form'
    changed = resource_form(MasterCategory, fields, instance=child, data=data)
    assert not changed.is_valid()


def test_hidden_disabled_and_excluded_fields_are_never_restored():
    from auxiliary.models import Country, StateProvince
    from base.ui.related_fields import configure_related_fields

    class Hidden(forms.Form):
        country_ref = forms.ModelChoiceField(
            queryset=Country.objects.none(), widget=forms.HiddenInput
        )
        state_ref = forms.ModelChoiceField(queryset=StateProvince.objects.none())

    hidden = Hidden()
    configure_related_fields(hidden)
    assert 'data-related-rules' not in hidden.fields['state_ref'].widget.attrs
    hidden = Hidden()
    del hidden.fields['country_ref']
    hidden.fields['state_ref'].disabled = True
    configure_related_fields(hidden)
    assert set(hidden.fields) == {'state_ref'}
    assert hidden.fields['state_ref'].disabled
    assert hidden.fields['state_ref'].queryset.count() == 0


def test_same_target_product_fields_do_not_invent_dependencies():
    from base.ui.related_fields import configure_related_fields

    class DifferentProducts(forms.Form):
        product = forms.ModelChoiceField(queryset=Product.objects.none())
        material = forms.ModelChoiceField(queryset=Product.objects.none())

    form = DifferentProducts()
    configure_related_fields(form)
    assert all('data-related-rules' not in field.widget.attrs for field in form.fields.values())


def test_routes_allow_generic_formula_and_reject_other_formula():
    from formulations.models import MasterFormula, ManufacturingRoute
    from masters.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code='KG', name='Kg', symbol='kg')
    product = Product.objects.create(description='P', item_type='finished_product', unit=unit)
    f1 = MasterFormula.objects.create(product=product, version=1, batch_size=1, batch_unit=unit)
    f2 = MasterFormula.objects.create(product=product, version=2, batch_size=1, batch_unit=unit)
    generic = ManufacturingRoute.objects.create(product=product, version=1)
    specific = ManufacturingRoute.objects.create(product=product, version=2, formula=f2)

    class RouteSelection(RelatedActionForm):
        product = forms.ModelChoiceField(queryset=Product.objects.all())
        formula = forms.ModelChoiceField(queryset=MasterFormula.objects.all())
        route = forms.ModelChoiceField(queryset=ManufacturingRoute.objects.all())

    data = {'product': product.pk, 'formula': f1.pk, 'route': generic.pk}
    assert RouteSelection(data).is_valid()
    data['route'] = specific.pk
    invalid = RouteSelection(data)
    assert not invalid.is_valid()
    assert 'route' in invalid.errors


def test_receipt_order_filters_order_item_without_visible_order_field():
    from procurement.models import PurchaseOrderItem, PurchaseReceipt
    from base.ui.related_fields import related_field_specs

    class Receiving(RelatedActionForm):
        receipt = forms.ModelChoiceField(queryset=PurchaseReceipt.objects.none())
        order_item = forms.ModelChoiceField(queryset=PurchaseOrderItem.objects.none())

    form = Receiving()
    # Each order item belongs to receipt.order, not to receipt itself.
    assert any(
        spec[0] == 'order_item' and spec[1] == 'receipt' for spec in related_field_specs(form)
    )


def test_formula_copied_from_is_not_assumed_to_belong_to_current_product():
    from formulations.models import MasterFormula
    from base.ui.related_fields import configure_related_fields

    class Copy(forms.ModelForm):
        class Meta:
            model = MasterFormula
            fields = ('product', 'copied_from')

    form = Copy()
    configure_related_fields(form)
    assert 'data-related-rules' not in form.fields['copied_from'].widget.attrs


def test_invalid_formula_product_combination_is_error_not_model_clean_500():
    from formulations.models import MasterFormula, ManufacturingRoute
    from masters.models import UnitOfMeasure
    from production.models import ProductionOrder

    unit = UnitOfMeasure.objects.create(code='KG', name='Kg', symbol='kg')
    product = Product.objects.create(description='P', item_type='finished_product', unit=unit)
    other = Product.objects.create(description='Outro', item_type='finished_product', unit=unit)
    formula = MasterFormula.objects.create(product=other, version=1, batch_size=1, batch_unit=unit)
    route = ManufacturingRoute.objects.create(product=product, version=1)
    fields = ('product', 'formula', 'route', 'planned_quantity', 'unit')
    form = resource_form(
        ProductionOrder,
        fields,
        data={
            'product': product.pk,
            'formula': formula.pk,
            'route': route.pk,
            'planned_quantity': '1',
            'unit': unit.pk,
        },
    )
    assert not form.is_valid()
    assert 'formula' in form.errors
    with pytest.raises(ValueError):
        form.save()
    assert not ProductionOrder.objects.exists()


def test_receipt_item_post_uses_receipt_order_not_any_order():
    from procurement.models import PurchaseOrder, PurchaseOrderItem, PurchaseReceipt
    from masters.models import BusinessPartner, UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code='KG', name='Kg', symbol='kg')
    product = Product.objects.create(description='P', item_type='raw_material', unit=unit)
    supplier = BusinessPartner.objects.create(legal_name='Fornecedor', partner_type='supplier')
    order = PurchaseOrder.objects.create(supplier=supplier)
    other = PurchaseOrder.objects.create(supplier=supplier)
    receipt = PurchaseReceipt.objects.create(order=order)
    matching = PurchaseOrderItem.objects.create(
        order=order, product=product, quantity=1, unit=unit, unit_price=1
    )
    foreign = PurchaseOrderItem.objects.create(
        order=other, product=product, quantity=1, unit=unit, unit_price=1
    )

    class Receiving(RelatedActionForm):
        receipt = forms.ModelChoiceField(queryset=PurchaseReceipt.objects.all())
        order_item = forms.ModelChoiceField(queryset=PurchaseOrderItem.objects.all())

    good = Receiving({'receipt': receipt.pk, 'order_item': matching.pk})
    assert good.is_valid(), good.errors
    bad = Receiving({'receipt': receipt.pk, 'order_item': foreign.pk})
    assert not bad.is_valid()
    assert 'order_item' in bad.errors


def test_commercial_terms_keep_authorization_and_filter_semantic_kind():
    from auxiliary.models import CommercialTerm
    from procurement.models import PurchaseOrder
    from base.ui.related_fields import configure_related_fields

    payment = CommercialTerm.objects.create(name='Pagamento', term_type='payment')
    delivery = CommercialTerm.objects.create(name='Entrega', term_type='delivery')
    forbidden = CommercialTerm.objects.create(name='Segredo', term_type='payment')

    class Terms(forms.ModelForm):
        payment_term_ref = forms.ModelChoiceField(
            queryset=CommercialTerm.objects.exclude(pk=forbidden.pk)
        )

        class Meta:
            model = PurchaseOrder
            fields = ('payment_terms', 'payment_term_ref', 'delivery_terms', 'delivery_term_ref')

    form = Terms()
    configure_related_fields(form)
    assert list(form.fields['payment_term_ref'].queryset.values_list('pk', flat=True)) == [
        payment.pk
    ]
    assert list(form.fields['delivery_term_ref'].queryset.values_list('pk', flat=True)) == [
        delivery.pk
    ]
    assert not form.fields['payment_terms'].widget.is_hidden
    assert not form.fields['delivery_terms'].widget.is_hidden


def test_dependency_to_field_name_uses_real_choice_value():
    from auxiliary.models import Country, StateProvince

    country = Country.objects.create(name='Brasil')
    state = StateProvince.objects.create(name='São Paulo', country=country)

    class Address(RelatedActionForm):
        country = forms.ModelChoiceField(queryset=Country.objects.all(), to_field_name='name')
        state = forms.ModelChoiceField(queryset=StateProvince.objects.all(), to_field_name='name')

    good = Address({'country': country.name, 'state': state.name})
    assert good.is_valid(), good.errors


def test_formula_option_labels_do_not_issue_a_query_per_product(django_assert_num_queries):
    from formulations.models import MasterFormula
    from masters.models import UnitOfMeasure

    unit = UnitOfMeasure.objects.create(code='KG', name='Kg', symbol='kg')
    for index in range(4):
        product = Product.objects.create(
            description=f'P{index}', item_type='finished_product', unit=unit
        )
        MasterFormula.objects.create(product=product, version=1, batch_size=1, batch_unit=unit)

    class Choice(RelatedActionForm):
        product = forms.ModelChoiceField(queryset=Product.objects.all())
        formula = forms.ModelChoiceField(queryset=MasterFormula.objects.all())

    form = Choice()
    with django_assert_num_queries(1):
        labels = [str(label) for _, label in form.fields['formula'].choices]
    assert len(labels) == 5
