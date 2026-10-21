"""Real action builders must apply the same FK contract as resource forms."""

import json

import pytest
from django.test import RequestFactory

from auxiliary.models import Country, StateProvince
from base.ui.actions.forms import build_action_form
from base.ui.actions.types import ActionField, FieldKind
from tests.test_action_forms import action_with_fields


def address_action(country_queryset, state_queryset):
    config = action_with_fields(
        ActionField(
            'shipping_country_ref',
            'País',
            FieldKind.RELATION,
            queryset_factory=lambda request: country_queryset,
        ),
        ActionField(
            'shipping_state_ref',
            'UF',
            FieldKind.RELATION,
            queryset_factory=lambda request: state_queryset,
        ),
    )
    return build_action_form(config, RequestFactory().get('/'))


def test_action_initialization_configures_dependent_select_without_database_access():
    form = address_action(Country.objects.none(), StateProvince.objects.none())(prefix='row-2')
    assert 'data-related-rules' in form.fields['shipping_state_ref'].widget.attrs
    assert form.fields['shipping_state_ref'].queryset.model is StateProvince


@pytest.mark.django_db
def test_action_filters_are_prefixed_and_cannot_expand_authorized_choices():
    br = Country.objects.create(name='Brasil')
    pt = Country.objects.create(name='Portugal')
    sp = StateProvince.objects.create(name='São Paulo', country=br)
    lisbon = StateProvince.objects.create(name='Lisboa', country=pt)
    forbidden = StateProvince.objects.create(name='Não autorizado', country=br)
    form_class = address_action(
        Country.objects.all(), StateProvince.objects.exclude(pk=forbidden.pk)
    )
    initial = form_class(prefix='row-2')
    metadata = json.loads(
        str(initial.fields['shipping_state_ref'].widget.attrs['data-related-rules'])
    )
    assert metadata[0]['controller'] == 'row-2-shipping_country_ref'
    assert str(forbidden.pk) not in metadata[0]['values']
    data = {'row-2-shipping_country_ref': br.pk, 'row-2-shipping_state_ref': lisbon.pk}
    wrong_parent = form_class(data, prefix='row-2')
    assert not wrong_parent.is_valid()
    assert 'shipping_state_ref' in wrong_parent.errors
    data['row-2-shipping_state_ref'] = forbidden.pk
    assert not form_class(data, prefix='row-2').is_valid()
    data['row-2-shipping_state_ref'] = sp.pk
    valid = form_class(data, prefix='row-2')
    assert valid.is_valid(), valid.errors
    assert valid.cleaned_payload() == {'shipping_country_ref': br.pk, 'shipping_state_ref': sp.pk}
