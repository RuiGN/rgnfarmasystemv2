"""Runtime contracts for the typing-only resource form base correction."""

from dataclasses import replace
from decimal import Decimal

import pytest
from django import forms

from base.ui.forms import build_resource_form
from base.ui.registry import get_resource
from finance.models import FinancialAccount, FinancialTitle
from formulations.reuse import build_master_formula_reuse_form
from governance.forms import GovernanceParameterForm
from governance.models import GovernanceParameter


@pytest.mark.parametrize('update', [False, True])
@pytest.mark.parametrize(
    ('module', 'slug'),
    [
        ('finance', 'accounts'),
        ('finance', 'titles'),
        ('governance', 'parameters'),
        ('formulations', 'formulas'),
        ('procurement', 'orders'),
        ('procurement', 'receipts'),
    ],
)
def test_resource_form_preserves_exact_base_and_meta(module, slug, update):
    resource = get_resource(module, slug)
    form_class = build_resource_form(resource, update=update)
    expected_base = resource.form_base or forms.ModelForm

    assert form_class.__bases__ == (expected_base,)
    assert form_class.__mro__ == (form_class, *expected_base.__mro__)
    assert issubclass(form_class, forms.ModelForm)
    assert form_class.__name__ == 'ResourceForm'
    assert form_class._meta.model is resource.model
    fields = (
        resource.update_form_fields
        if update and resource.update_form_fields is not None
        else resource.form_fields
    )
    if fields is not None:
        if resource.model in (FinancialTitle, FinancialAccount):
            fields = tuple(name for name in fields if name not in resource.model.SERVICE_FIELDS)
        assert form_class._meta.fields == fields
    form = form_class()
    if resource.model in (FinancialTitle, FinancialAccount):
        assert not resource.model.SERVICE_FIELDS.intersection(form.fields)
    for field in form.fields.values():
        assert field.widget.attrs['data-field-size']


@pytest.mark.django_db
@pytest.mark.parametrize('commit', [False, True])
def test_custom_governance_form_cooperatively_initializes_cleans_and_saves_once(commit):
    calls = []

    class CustomGovernanceForm(GovernanceParameterForm):
        extra = forms.CharField(required=False)

        def __init__(self, *args, **kwargs):
            calls.append('__init__')
            super().__init__(*args, **kwargs)

        def clean(self):
            calls.append('clean')
            return super().clean()

        def _post_clean(self):
            calls.append('_post_clean')
            super()._post_clean()

        def save(self, commit=True):
            calls.append(('save', commit))
            return super().save(commit=commit)

    resource = replace(get_resource('governance', 'parameters'), form_base=CustomGovernanceForm)
    form_class = build_resource_form(resource)
    assert form_class.__bases__ == (CustomGovernanceForm,)
    assert form_class.__mro__ == (form_class, *CustomGovernanceForm.__mro__)
    form = form_class(
        data={
            'scope': GovernanceParameter.Scope.GLOBAL,
            'module': 'governance',
            'key': 'typing_cooperative_probe',
            'value_type': GovernanceParameter.ValueType.DECIMAL,
            'value': '12.50',
            'default_value': '5.00',
            'rules': '{}',
            'description': '',
            'is_active': 'on',
            'extra': 'declared custom field',
        }
    )
    assert isinstance(form.fields['value'], forms.DecimalField)
    assert form.fields['extra'].widget.attrs['data-field-size']
    assert form.is_valid(), form.errors.as_json()
    assert form.is_valid()  # Cached validation must not invoke custom clean again.
    assert form.cleaned_data['value'] == '12.50'
    assert form.cleaned_data['default_value'] == '5.00'
    assert form.cleaned_data['extra'] == 'declared custom field'
    assert form.resource_save_kwargs() == {}
    instance = form.save(commit=commit)
    if not commit:
        assert instance.pk is None
        instance.save()
        form.save_m2m()
    instance.refresh_from_db()
    assert instance.value == '12.50'
    assert instance.default_value == '5.00'
    assert calls == ['__init__', 'clean', '_post_clean', ('save', commit)]


@pytest.mark.django_db
@pytest.mark.parametrize('commit', [False, True])
@pytest.mark.parametrize('update', [False, True])
def test_financial_custom_form_preserves_save_protocol_and_derived_balance(commit, update):
    calls = []

    class CustomAccountForm(forms.ModelForm):
        class Meta:
            model = FinancialAccount
            fields = ()

        def __init__(self, *args, **kwargs):
            calls.append('__init__')
            super().__init__(*args, **kwargs)

        def clean(self):
            calls.append('clean')
            return super().clean()

        def _post_clean(self):
            calls.append('_post_clean')
            super()._post_clean()

        def save(self, commit=True):
            calls.append(('save', commit))
            return super().save(commit=commit)

    instance = FinancialAccount(
        name='Typing financial probe',
        account_type=FinancialAccount.AccountType.BANK,
        opening_balance=Decimal('100'),
    )
    if update:
        instance.save()
    resource = replace(get_resource('finance', 'accounts'), form_base=CustomAccountForm)
    form_class = build_resource_form(resource, update=update)
    assert form_class.__bases__ == (CustomAccountForm,)
    assert form_class.__mro__ == (form_class, *CustomAccountForm.__mro__)
    form = form_class(
        data={
            'name': 'Typing financial edit',
            'account_type': instance.account_type,
            'opening_balance': '80',
            'current_balance': '999',
            'is_active': 'on',
        },
        instance=instance,
    )
    assert not FinancialAccount.SERVICE_FIELDS.intersection(form.fields)
    assert form.is_valid(), form.errors.as_json()
    assert form.is_valid()
    kwargs = form.resource_save_kwargs()
    if update:
        assert kwargs == {'update_fields': {'name', 'opening_balance'}}
        assert not FinancialAccount.SERVICE_FIELDS.intersection(kwargs['update_fields'])
    else:
        assert kwargs == {}
    result = form.save(commit=commit)
    if not commit:
        result.save(**kwargs)
        form.save_m2m()
    result.refresh_from_db()
    assert result.name == 'Typing financial edit'
    assert result.opening_balance == result.current_balance == Decimal('80')
    # The public financial save always delegates with commit=False before its locked save.
    assert calls == ['__init__', 'clean', '_post_clean', ('save', False)]


def test_formula_reuse_keeps_generated_parent_and_custom_fields():
    resource = get_resource('formulations', 'formulas')
    form_class = build_master_formula_reuse_form(resource)
    parent = form_class.__bases__[0]
    assert parent.__name__ == 'ResourceForm'
    assert parent.__bases__ == (forms.ModelForm,)
    assert form_class.__mro__ == (form_class, parent, *forms.ModelForm.__mro__)
    form = form_class()
    assert 'copied_from' not in form.fields
    assert form.fields['status'].disabled
    assert form.fields['status'].initial == resource.model.Status.DRAFT
    assert form.fields['status'].widget.attrs['data-field-size']
