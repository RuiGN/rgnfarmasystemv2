import json
from decimal import Decimal

from django import forms

from governance.models import GovernanceParameter


BOOLEAN_DEFAULT_CHOICES = (
    ('', 'Não definido'),
    ('true', 'Ativado'),
    ('false', 'Desativado'),
)


def _boolean_default(value):
    if value in ('', None, {}):
        return {}
    return str(value).lower() == 'true'


class GovernanceParameterForm(forms.ModelForm):
    class Meta:
        model = GovernanceParameter
        fields = ()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        value_type = self._effective_value_type()
        rules = self._effective_rules()
        self.fields['value'] = self._typed_field('value', value_type, required=True, rules=rules)
        self.fields['default_value'] = self._typed_field(
            'default_value',
            value_type,
            required=False,
            rules=rules,
            is_default=True,
        )
        self.fields['value'].widget.attrs['data-governance-value'] = 'current'
        self.fields['default_value'].widget.attrs['data-governance-value'] = 'default'
        self.fields['value_type'].widget.attrs['data-governance-value-type'] = 'true'
        self.fields['rules'].widget.attrs['data-governance-rules'] = 'true'
        self._normalize_boolean_initial(value_type)

    def _effective_value_type(self):
        if self.is_bound:
            return self.data.get(self.add_prefix('value_type'), '')
        return self.initial.get('value_type') or getattr(self.instance, 'value_type', '')

    def _effective_rules(self):
        if self.is_bound:
            raw = self.data.get(self.add_prefix('rules'), '{}')
            try:
                return json.loads(raw) if isinstance(raw, str) else raw
            except TypeError, json.JSONDecodeError:
                return {}
        return self.initial.get('rules') or getattr(self.instance, 'rules', {}) or {}

    def _typed_field(self, name, value_type, *, required, rules, is_default=False):
        label = GovernanceParameter._meta.get_field(name).verbose_name
        if value_type == GovernanceParameter.ValueType.BOOLEAN:
            if is_default:
                return forms.TypedChoiceField(
                    label=label,
                    choices=BOOLEAN_DEFAULT_CHOICES,
                    coerce=_boolean_default,
                    empty_value={},
                    required=False,
                )
            return forms.BooleanField(
                label=label,
                required=False,
                widget=forms.CheckboxInput(attrs={'role': 'switch'}),
            )
        if value_type in {
            GovernanceParameter.ValueType.INTEGER,
            GovernanceParameter.ValueType.DAYS,
        }:
            return forms.IntegerField(label=label, required=required)
        if value_type == GovernanceParameter.ValueType.DECIMAL:
            return forms.DecimalField(label=label, required=required)
        if value_type == GovernanceParameter.ValueType.CHOICE:
            choices = tuple((str(item), str(item)) for item in rules.get('choices', ()))
            return forms.ChoiceField(label=label, required=required, choices=choices)
        if value_type == GovernanceParameter.ValueType.JSON:
            return forms.JSONField(label=label, required=required, widget=forms.Textarea)
        return forms.CharField(label=label, required=required)

    def _normalize_boolean_initial(self, value_type):
        if self.is_bound or value_type != GovernanceParameter.ValueType.BOOLEAN:
            return
        default_value = self.initial.get(
            'default_value', getattr(self.instance, 'default_value', {})
        )
        if default_value in ({}, None, ''):
            self.initial['default_value'] = ''
        else:
            self.initial['default_value'] = 'true' if bool(default_value) else 'false'

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('default_value') in ('', None):
            cleaned['default_value'] = {}
        if self._effective_value_type() == GovernanceParameter.ValueType.DECIMAL:
            for name in ('value', 'default_value'):
                value = cleaned.get(name)
                if isinstance(value, Decimal):
                    cleaned[name] = format(value, 'f')
        return cleaned
