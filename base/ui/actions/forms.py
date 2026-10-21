from decimal import Decimal

from django import forms
from django.db.models import Model

from base.ui.forms import _apply_widget_metadata
from base.ui.actions.types import ActionConfig, ActionField, FieldKind
from base.ui.related_fields import configure_related_fields, validate_related_fields


class ActionForm(forms.Form):
    declared_action_fields: tuple[ActionField, ...] = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        configure_related_fields(self)

    def cleaned_payload(self):
        payload = {}
        for metadata in self.declared_action_fields:
            value = self.cleaned_data[metadata.name]
            if isinstance(value, Decimal):
                value = str(value)
            elif hasattr(value, 'isoformat'):
                value = value.isoformat()
            elif isinstance(value, Model):
                value = value.pk
            payload[metadata.name] = value
        return payload


def build_action_form(config: ActionConfig, request, obj=None):
    form_fields = {
        metadata.name: _build_field(metadata, request, obj) for metadata in config.fields
    }
    if config.confirmation and config.confirmation.typed_phrase:
        confirmation_phrase = forms.CharField(
            label=f'Digite {config.confirmation.typed_phrase} para confirmar',
            required=True,
        )
        _apply_widget_metadata('confirmation_phrase', confirmation_phrase)
        form_fields['confirmation_phrase'] = confirmation_phrase
    if config.confirmation and config.confirmation.acknowledge_label:
        confirmation_acknowledged = forms.BooleanField(
            label=config.confirmation.acknowledge_label,
            required=True,
        )
        _apply_widget_metadata('confirmation_acknowledged', confirmation_acknowledged)
        form_fields['confirmation_acknowledged'] = confirmation_acknowledged

    typed_phrase = config.confirmation.typed_phrase if config.confirmation else ''

    def clean(form):
        cleaned_data = forms.Form.clean(form)
        if typed_phrase and cleaned_data.get('confirmation_phrase') != typed_phrase:
            form.add_error('confirmation_phrase', 'Digite a frase de confirmação exatamente.')
        return validate_related_fields(form, cleaned_data)

    dynamic_form = type(
        f'{config.model.__name__}{config.action_name.title()}ActionForm',
        (ActionForm,),
        {
            'declared_action_fields': config.fields,
            'clean': clean,
            **form_fields,
        },
    )
    return dynamic_form


def _build_field(metadata: ActionField, request, obj):
    common = {
        'label': metadata.label,
        'required': metadata.required,
        'help_text': metadata.help_text,
    }
    if metadata.max_length is not None:
        common['max_length'] = metadata.max_length
    if metadata.initial_factory:
        common['initial'] = metadata.initial_factory(request, obj)

    def relation_queryset():
        if metadata.queryset_factory is None:
            raise ValueError(f'Campo relacional {metadata.name} sem queryset_factory.')
        return metadata.queryset_factory(request)

    factories = {
        FieldKind.TEXT: lambda: forms.CharField(**common),
        FieldKind.TEXTAREA: lambda: forms.CharField(widget=forms.Textarea, **common),
        FieldKind.INTEGER: lambda: forms.IntegerField(
            min_value=metadata.min_value,
            max_value=metadata.max_value,
            **common,
        ),
        FieldKind.DECIMAL: lambda: forms.DecimalField(
            min_value=metadata.min_value,
            max_value=metadata.max_value,
            **common,
        ),
        FieldKind.BOOLEAN: lambda: forms.BooleanField(**common),
        FieldKind.DATE: lambda: forms.DateField(
            widget=forms.DateInput(attrs={'type': 'date'}), **common
        ),
        FieldKind.DATETIME: lambda: forms.DateTimeField(
            widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            **common,
        ),
        FieldKind.CHOICE: lambda: forms.ChoiceField(choices=metadata.choices, **common),
        FieldKind.RELATION: lambda: forms.ModelChoiceField(
            queryset=relation_queryset(),
            **common,
        ),
        FieldKind.FILE: lambda: forms.FileField(**common),
        FieldKind.HIDDEN: lambda: forms.CharField(
            widget=forms.HiddenInput, disabled=True, **common
        ),
        FieldKind.JSON: lambda: forms.JSONField(widget=forms.Textarea, **common),
    }
    field = factories[metadata.kind]()
    if metadata.widget_factory:
        field.widget = metadata.widget_factory()
    _apply_widget_metadata(metadata.name, field)
    if metadata.placeholder:
        field.widget.attrs['placeholder'] = metadata.placeholder
    return field
