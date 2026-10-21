"""The horizontal tab renderer must retain field-size metadata."""

from html.parser import HTMLParser

import pytest
from django import forms
from django.template.loader import render_to_string

from base.ui.forms import _apply_widget_metadata


class FieldMarkup(HTMLParser):
    def __init__(self):
        super().__init__()
        self.wrappers = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = (attributes.get('class') or '').split()
        if tag == 'div' and ('resource-form-field' in classes or 'form-field' in classes):
            self.wrappers.append(classes)


@pytest.mark.parametrize('horizontal', [False, True])
@pytest.mark.parametrize(
    ('name', 'size'),
    [('name', 'lg'), ('document', 'sm'), ('state', 'xs'), ('description', 'full')],
)
def test_field_renderer_preserves_responsive_size_metadata(horizontal, name, size):
    field = forms.CharField(widget=forms.Textarea if name == 'description' else forms.TextInput)
    _apply_widget_metadata(name, field)
    form = forms.Form()
    form.fields[name] = field

    markup = render_to_string(
        'app/includes/resource_form_field.html', {'field': form[name], 'horizontal': horizontal}
    )
    parsed = FieldMarkup()
    parsed.feed(markup)

    assert len(parsed.wrappers) == 1
    assert f'form-field--{size}' in parsed.wrappers[0]
    assert f'data-field-size="{size}"' in markup
