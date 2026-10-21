from django import forms
from django.core.exceptions import ValidationError

from reports.filtering import (
    InvalidReportFilterSchema,
    compile_filter_schema,
    form_value,
)
from reports.models import ALLOWED_FILTER_FIELDS, ReportExecution


def _filter_field(specification):
    common = {'label': specification.label, 'required': specification.required}
    if specification.field_type == 'date':
        return forms.DateField(
            widget=forms.DateInput(format='%Y-%m-%d', attrs={'type': 'date'}), **common
        )
    if specification.field_type == 'choice':
        serialized_choices = [
            ('', '---------'),
            *((str(value), label) for value, label in specification.choices),
        ]
        typed_values = {str(value): value for value, _label in specification.choices}
        return forms.TypedChoiceField(
            choices=serialized_choices,
            coerce=typed_values.__getitem__,
            **common,
        )
    if specification.field_type == 'integer':
        return forms.IntegerField(widget=forms.NumberInput(), **common)
    return forms.CharField(**common)


class ReportRunForm(forms.Form):
    def __init__(self, *args, definition, **kwargs):
        self.definition = definition
        self.cleaned_filters = {}
        super().__init__(*args, **kwargs)
        specifications = compile_filter_schema(
            definition.filter_schema,
            definition.required_filters,
            allowed_fields=ALLOWED_FILTER_FIELDS,
        )
        self.filter_names = tuple(specification.name for specification in specifications)

        format_labels = dict(ReportExecution.ExportFormat.choices)
        allowed_formats = definition.allowed_export_formats
        if (
            type(allowed_formats) is not list
            or not allowed_formats
            or any(value not in format_labels for value in allowed_formats)
        ):
            raise InvalidReportFilterSchema
        self.fields['export_format'] = forms.ChoiceField(
            label='Formato de exportação',
            choices=[(value, format_labels[value]) for value in allowed_formats],
        )
        defaults = definition.default_filters if type(definition.default_filters) is dict else {}
        for specification in specifications:
            field = _filter_field(specification)
            if specification.name in defaults:
                field.initial = defaults[specification.name]
            self.fields[specification.name] = field

        for field in self.fields.values():
            css_class = 'form-select' if isinstance(field.widget, forms.Select) else 'form-control'
            field.widget.attrs['class'] = css_class
            if field.required:
                field.widget.attrs['required'] = 'required'

    def clean(self):
        cleaned_data = super().clean()
        if self.errors:
            return cleaned_data
        filters = {}
        for name in self.filter_names:
            value = cleaned_data.get(name)
            if value in (None, ''):
                continue
            filters[name] = form_value(value)
        try:
            self.cleaned_filters = self.definition.normalize_filters(filters)
        except ValidationError as error:
            if hasattr(error, 'message_dict'):
                for name, messages in error.message_dict.items():
                    self.add_error(name if name in self.fields else None, messages)
            else:
                self.add_error(None, error)
        return cleaned_data


def annotate_report_form_accessibility(form):
    for name, field in form.fields.items():
        if form.errors.get(name):
            field.widget.attrs['aria-invalid'] = 'true'
            field.widget.attrs['aria-describedby'] = f'id_{name}_errors'
