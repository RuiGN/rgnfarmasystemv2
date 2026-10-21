"""Native temporal controls must preserve values independently of locale."""

from datetime import date, datetime, time
from html.parser import HTMLParser

import pytest
from django import forms
from django.utils import translation

from base.ui.actions.forms import _build_field
from base.ui.actions.types import ActionField, FieldKind
from base.ui.forms import _apply_widget_metadata, build_resource_form
from base.ui.registry import get_resource
from reports.filtering import ReportFilterSpec
from reports.forms import _filter_field


class InputAttributes(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'input':
            self.inputs.append(attrs)


def input_attributes(bound_field):
    parser = InputAttributes(bound_field.as_widget())
    assert len(parser.inputs) == 1
    pairs = parser.inputs[0]
    assert sum(name == 'type' for name, _ in pairs) == 1
    return dict(pairs)


@pytest.mark.parametrize('language', ['pt-br', 'en-us'])
@pytest.mark.parametrize('update', [False, True])
def test_purchase_order_native_date_keeps_initial_and_existing_value(language, update):
    resource = get_resource('procurement', 'orders')
    assert resource is not None
    value = date(2026, 1, 10)
    with translation.override(language):
        form_class = build_resource_form(resource, update=update)
        form = (
            form_class(instance=resource.model(issue_date=value))
            if update
            else form_class(initial={'issue_date': value})
        )
        attributes = input_attributes(form['issue_date'])
    assert attributes['type'] == 'date'
    assert attributes['value'] == '2026-01-10'
    assert 'data-mask' not in attributes


@pytest.mark.parametrize('language', ['pt-br', 'en-us'])
def test_datetime_local_has_one_native_type_and_keeps_seconds(language):
    with translation.override(language):
        field = forms.DateTimeField(initial=datetime(2026, 1, 10, 12, 34, 56), localize=True)
        _apply_widget_metadata('scheduled_start', field)
        form = forms.Form()
        form.fields['scheduled_start'] = field
        attributes = input_attributes(form['scheduled_start'])
    assert attributes['type'] == 'datetime-local'
    assert attributes['value'] == '2026-01-10T12:34:56'
    assert attributes['step'] == '1'
    assert 'data-mask' not in attributes


@pytest.mark.parametrize('language', ['pt-br', 'en-us'])
def test_time_has_one_native_type_and_keeps_seconds(language):
    with translation.override(language):
        field = forms.TimeField(initial=time(12, 34, 56), localize=True)
        _apply_widget_metadata('starts_at', field)
        form = forms.Form()
        form.fields['starts_at'] = field
        attributes = input_attributes(form['starts_at'])
    assert attributes['type'] == 'time'
    assert attributes['value'] == '12:34:56'
    assert attributes['step'] == '1'
    assert 'data-mask' not in attributes


@pytest.mark.parametrize('language', ['pt-br', 'en-us'])
def test_report_filter_native_date_keeps_initial_value(language):
    specification = ReportFilterSpec('period_start', 'date', 'Início', False)
    with translation.override(language):
        field = _filter_field(specification)
        field.initial = date(2026, 1, 10)
        form = forms.Form()
        form.fields['period_start'] = field
        attributes = input_attributes(form['period_start'])
    assert attributes['type'] == 'date'
    assert attributes['value'] == '2026-01-10'


@pytest.mark.parametrize('language', ['pt-br', 'en-us'])
@pytest.mark.parametrize(
    ('kind', 'value', 'native_type', 'rendered'),
    [
        (FieldKind.DATE, date(2026, 1, 10), 'date', '2026-01-10'),
        (
            FieldKind.DATETIME,
            datetime(2026, 1, 10, 12, 34, 56),
            'datetime-local',
            '2026-01-10T12:34:56',
        ),
    ],
)
def test_action_forms_use_the_same_native_temporal_contract(
    language, kind, value, native_type, rendered
):
    metadata = ActionField('when', 'Quando', kind=kind, initial_factory=lambda request, obj: value)
    with translation.override(language):
        form = forms.Form()
        form.fields['when'] = _build_field(metadata, None, None)
        attributes = input_attributes(form['when'])
    assert attributes['type'] == native_type
    assert attributes['value'] == rendered


@pytest.mark.parametrize(
    ('field_type', 'value'),
    [
        (forms.DateField, '2026-01-10'),
        (forms.DateTimeField, '2026-01-10T12:34:56'),
        (forms.TimeField, '12:34:56'),
    ],
)
def test_bound_native_temporal_values_are_not_reformatted_or_dropped(field_type, value):
    with translation.override('pt-br'):
        form = forms.Form(data={'when': value})
        field = field_type()
        _apply_widget_metadata('when', field)
        form.fields['when'] = field
        assert form.is_valid(), form.errors
        assert input_attributes(form['when'])['value'] == value


@pytest.mark.parametrize('widget_type', [forms.DateTimeInput, forms.TimeInput])
def test_explicit_temporal_step_is_preserved(widget_type):
    field = forms.DateTimeField(widget=widget_type(attrs={'step': 'any'}))
    _apply_widget_metadata('when', field)
    widget = field.widget
    assert isinstance(widget, forms.Widget)
    assert widget.attrs['step'] == 'any'
