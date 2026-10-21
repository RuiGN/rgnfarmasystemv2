"""Simplification must remove noise, never business data or identifier guards."""

import pytest
from django import forms

from base.ui.forms import build_resource_form
from base.ui.registry import get_resource


@pytest.mark.parametrize(
    ('module', 'resource', 'name'),
    [
        ('masters', 'products', 'code'),
        ('masters', 'categories', 'code'),
        ('formulations', 'formulas', 'code'),
        ('procurement', 'orders', 'order_number'),
        ('production', 'orders', 'order_number'),
    ],
)
def test_new_record_does_not_ask_for_a_server_generated_identifier(module, resource, name):
    form = build_resource_form(get_resource(module, resource))()
    field = form.fields[name]
    assert isinstance(field.widget, forms.HiddenInput)
    assert field.disabled and not field.required
    assert name not in {bound.name for bound in form.visible_fields()}
    assert name in {bound.name for bound in form.hidden_fields()}
    assert field.bound_data('FORGED-IDENTIFIER', field.initial) is None


def test_existing_identifier_remains_visible_and_immutable():
    form = build_resource_form(get_resource('masters', 'products'), update=True)()
    assert not form.fields['code'].widget.is_hidden
    assert form.fields['code'].disabled


def test_manual_identifiers_and_business_fields_remain_editable():
    currency = build_resource_form(get_resource('auxiliary', 'currencies'))()
    assert not currency.fields['code'].disabled
    assert not currency.fields['code'].widget.is_hidden
    product = build_resource_form(get_resource('masters', 'products'))()
    for name in (
        'description',
        'item_type',
        'unit',
        'category',
        'status',
        'storage_condition',
        'shelf_life_days',
        'requires_quality_release',
        'requires_approved_supplier',
        'fiscal_ncm',
        'fiscal_cest',
    ):
        assert name in product.fields
        assert not product.fields[name].disabled
        assert not product.fields[name].widget.is_hidden
