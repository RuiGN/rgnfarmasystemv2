import re
import unicodedata
from typing import TYPE_CHECKING, TypeAlias

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import URLField
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError

from base.automatic_fields import automatic_generated_fields
from finance.models import FinancialAccount, FinancialTitle


if TYPE_CHECKING:
    ResourceFormBase: TypeAlias = forms.ModelForm


SYSTEM_FIELD_NAMES = {
    'id',
    'created_at',
    'updated_at',
    'created_by',
    'updated_by',
    'accepted_at',
    'accepted_by',
    'approved_at',
    'approved_by',
    'archived_at',
    'archived_by',
    'blocked_at',
    'blocked_by',
    'cancelled_at',
    'cancelled_by',
    'closed_at',
    'closed_by',
    'collected_at',
    'collected_by',
    'completed_at',
    'completed_by',
    'concluded_at',
    'concluded_by',
    'confirmed_at',
    'confirmed_by',
    'decided_at',
    'decided_by',
    'generated_at',
    'issued_at',
    'issued_by',
    'opened_by',
    'opened_at',
    'posted_at',
    'posted_by',
    'published_at',
    'published_by',
    'received_at',
    'received_by',
    'reconciled_at',
    'reconciled_by',
    'recorded_at',
    'recorded_by',
    'rejected_at',
    'rejected_by',
    'released_at',
    'released_by',
    'reviewed_at',
    'reviewed_by',
    'reversed_at',
    'reversed_by',
    'requested_by',
    'sent_at',
    'submitted_at',
    'submitted_by',
    'unblocked_at',
    'unblocked_by',
    'uploaded_by',
    'content_hash',
}


DOCUMENT_VALIDATION_ERROR = 'CPF/CNPJ inválido.'


def _secure_formfield(db_field, **kwargs):
    if isinstance(db_field, URLField):
        kwargs['assume_scheme'] = 'https'
    return db_field.formfield(**kwargs)


def _only_digits(value):
    return re.sub(r'\D', '', str(value or ''))


def _ascii(value):
    normalized = unicodedata.normalize('NFKD', str(value or ''))
    return normalized.encode('ascii', 'ignore').decode('ascii').lower()


def _field_context(name, field):
    return f'{_ascii(name)} {_ascii(getattr(field, "label", ""))}'


def _field_mask(name, field):
    context = _field_context(name, field)
    compact_name = _ascii(name).replace('_', '')

    if 'cnpj' in context and 'cpf' in context:
        return 'cpf-cnpj'
    if 'cnpj' in context:
        return 'cnpj'
    if 'cpf' in context:
        return 'cpf'
    if compact_name == 'document':
        return 'cpf-cnpj'
    if (
        compact_name in {'cep', 'zipcode', 'postalcode'}
        or compact_name.endswith('cep')
        or compact_name.endswith('zipcode')
        or compact_name.endswith('postalcode')
        or ' cep' in f' {context} '
    ):
        return 'cep'
    if (
        compact_name in {'phone', 'telefone', 'cellphone', 'mobile', 'whatsapp', 'celular'}
        or any(
            token in compact_name
            for token in ('phone', 'telefone', 'cellphone', 'whatsapp', 'celular')
        )
        or 'telefone' in context
    ):
        return 'phone'
    if ' ncm' in f' {context} ':
        return 'ncm'
    if ' cfop' in f' {context} ':
        return 'cfop'
    if ' cest' in f' {context} ':
        return 'cest'
    if isinstance(field.widget, forms.DateInput):
        return 'date'
    if isinstance(field.widget, forms.DateTimeInput):
        return 'datetime'
    if isinstance(field.widget, forms.TimeInput):
        return 'time'
    return ''


ADDRESS_GROUPS = ('shipping', 'billing', 'location', 'venue', 'event', 'delivery', 'holder')


def _split_address_group(compact_name):
    for group in ADDRESS_GROUPS:
        if compact_name.startswith(group) and len(compact_name) > len(group):
            return group, compact_name[len(group) :]
    return '', compact_name


def _address_target(name, field):
    context = _field_context(name, field)
    compact_name = _ascii(name).replace('_', '')
    if 'email' in context:
        return ''

    group, remainder = _split_address_group(compact_name)
    suffix = f'_{group}' if group and group != 'billing' else ''

    if remainder in {'street', 'logradouro', 'address', 'addressline', 'addressline1'}:
        return f'street{suffix}'
    if remainder in {'streetnumber', 'numero', 'number'}:
        return f'street_number{suffix}'
    if remainder in {'complemento', 'complement'}:
        return f'complement{suffix}'
    if remainder in {'neighborhood', 'bairro', 'district'}:
        return f'neighborhood{suffix}'
    if (
        remainder in {'city', 'cidade', 'municipio', 'municipality', 'cityref'}
        or 'municipio' in context
    ):
        return f'city{suffix}'
    if remainder in {'state', 'uf', 'estado', 'stateref'} or context.strip() == 'uf':
        return f'state{suffix}'
    if remainder in {'country', 'pais', 'nation', 'countryref'} or context.strip() == 'pais':
        return f'country{suffix}'
    return ''


def _uses_text_input(field):
    return isinstance(
        field.widget, (forms.TextInput, forms.EmailInput, forms.URLInput, forms.NumberInput)
    )


def _append_widget_class(widget, class_name):
    classes = widget.attrs.get('class', '').split()
    if class_name not in classes:
        classes.append(class_name)
    widget.attrs['class'] = ' '.join(classes)


def _field_size(name, field, mask, address_target):
    context = _field_context(name, field)
    compact_name = _ascii(name).replace('_', '')
    widget = field.widget

    if isinstance(widget, forms.CheckboxInput):
        return 'xs'
    if isinstance(widget, (forms.Textarea, forms.SelectMultiple, forms.ClearableFileInput)):
        return 'full'
    if isinstance(field, forms.ModelMultipleChoiceField):
        return 'full'
    if isinstance(field, forms.ModelChoiceField):
        return 'lg'

    if address_target == 'state' or compact_name in {'uf', 'state', 'estado'}:
        return 'xs'
    if address_target in {'street', 'neighborhood', 'city'}:
        return 'lg'

    if mask in {'cep', 'ncm', 'cfop', 'cest'}:
        return 'xs'
    if mask in {'cpf', 'cnpj', 'cpf-cnpj', 'phone', 'date', 'time'}:
        return 'sm'
    if mask == 'datetime':
        return 'md'

    if isinstance(widget, forms.DateTimeInput):
        return 'md'
    if isinstance(widget, (forms.DateInput, forms.TimeInput)):
        return 'sm'

    if isinstance(field, forms.BooleanField):
        return 'xs'
    if isinstance(field, forms.DecimalField):
        return 'sm'
    if isinstance(field, forms.IntegerField):
        short_numeric_tokens = ('year', 'month', 'day', 'days', 'sequence', 'line', 'version')
        return 'xs' if any(token in compact_name for token in short_numeric_tokens) else 'sm'

    if isinstance(widget, forms.EmailInput) or 'email' in context:
        return 'lg'
    if isinstance(widget, forms.URLInput) or 'url' in context:
        return 'lg'

    full_text_tokens = (
        'description',
        'notes',
        'summary',
        'conclusion',
        'content',
        'rationale',
        'justification',
        'reason',
        'criteria',
        'scope',
        'comments',
        'terms',
        'prompt',
        'payload',
        'metadata',
        'instructions',
    )
    if any(token in compact_name or token in context for token in full_text_tokens):
        return 'full'

    long_text_tokens = ('name', 'title', 'subject', 'legalname', 'tradename', 'address')
    if any(token in compact_name for token in long_text_tokens):
        return 'lg'

    compact_tokens = (
        'code',
        'slug',
        'number',
        'series',
        'document',
        'registration',
        'status',
        'type',
        'kind',
        'role',
        'source',
        'priority',
        'severity',
        'criticality',
    )
    if any(token in compact_name for token in compact_tokens):
        return 'sm'

    return 'md'


def _apply_field_size_metadata(name, field, mask, address_target):
    size = _field_size(name, field, mask, address_target)
    field.rgn_layout_class = f'form-field--{size}'
    field.rgn_control_size = f'control-size--{size}'
    field.widget.attrs['data-field-size'] = size
    _append_widget_class(field.widget, field.rgn_control_size)


def _apply_placeholder_metadata(name, field, mask):
    attrs = field.widget.attrs
    context = _field_context(name, field)
    compact_name = _ascii(name).replace('_', '')
    if mask == 'cpf-cnpj':
        attrs['placeholder'] = '000.000.000-00 ou 00.000.000/0000-00'
    elif mask == 'cpf':
        attrs['placeholder'] = '000.000.000-00'
    elif mask == 'cnpj':
        attrs['placeholder'] = '00.000.000/0000-00'
    elif mask == 'cep':
        attrs['placeholder'] = '00000-000'
    elif mask == 'date':
        attrs['placeholder'] = 'dd/mm/aaaa'
    elif mask == 'datetime':
        attrs['placeholder'] = 'dd/mm/aaaa hh:mm'
    elif mask == 'time':
        attrs['placeholder'] = 'hh:mm'
    elif mask == 'phone':
        attrs['placeholder'] = '(00) 00000-0000'
    elif 'email' in context:
        attrs['placeholder'] = 'nome@empresa.com'
    elif isinstance(field.widget, forms.URLInput) or 'url' in context:
        attrs['placeholder'] = 'https://exemplo.com'
    elif isinstance(field, forms.DecimalField) and any(
        token in compact_name or token in context
        for token in ('percent', 'percentage', 'percentual', 'taxa')
    ):
        attrs['placeholder'] = '0,00%'
    elif isinstance(field, forms.DecimalField) and any(
        token in compact_name or token in context
        for token in ('amount', 'valor', 'price', 'cost', 'total')
    ):
        attrs['placeholder'] = '0,00'
    elif isinstance(field, forms.DecimalField) and any(
        token in compact_name or token in context
        for token in ('quantity', 'quantidade', 'qty', 'volume', 'peso', 'weight')
    ):
        attrs['placeholder'] = '0,0000'
    elif field.label:
        attrs.setdefault('placeholder', str(field.label))


def _apply_widget_metadata(name, field):
    widget = field.widget
    attrs = widget.attrs
    native_temporal_widget = isinstance(
        widget,
        (forms.DateInput, forms.DateTimeInput, forms.TimeInput),
    )
    mask = None if native_temporal_widget else _field_mask(name, field)
    address_target = _address_target(name, field)
    _apply_field_size_metadata(name, field, mask, address_target)

    if isinstance(widget, (forms.Select, forms.SelectMultiple)):
        _append_widget_class(widget, 'form-select')
    elif isinstance(widget, forms.CheckboxInput):
        _append_widget_class(widget, 'form-check-input')
    else:
        _append_widget_class(widget, 'form-control')

    _apply_placeholder_metadata(name, field, mask)

    if isinstance(widget, forms.DateInput):
        attrs.pop('type', None)
        widget.input_type = 'date'
        widget.format = '%Y-%m-%d'
    elif isinstance(widget, forms.DateTimeInput):
        attrs.pop('type', None)
        widget.input_type = 'datetime-local'
        widget.format = '%Y-%m-%dT%H:%M:%S'
        attrs.setdefault('step', '1')
    elif isinstance(widget, forms.TimeInput):
        attrs.pop('type', None)
        widget.input_type = 'time'
        widget.format = '%H:%M:%S'
        attrs.setdefault('step', '1')
    elif isinstance(widget, forms.Textarea):
        attrs.setdefault('rows', '4')
    elif isinstance(field, forms.DecimalField):
        attrs.setdefault('inputmode', 'decimal')
        attrs.setdefault('step', '0.0001')
    elif isinstance(field, forms.IntegerField):
        attrs.setdefault('inputmode', 'numeric')
        attrs.setdefault('step', '1')

    if mask and _uses_text_input(field):
        attrs['data-mask'] = mask
        attrs.setdefault('autocomplete', 'off')
        if mask in {
            'cpf',
            'cnpj',
            'cpf-cnpj',
            'cep',
            'phone',
            'ncm',
            'cfop',
            'cest',
            'date',
            'datetime',
            'time',
        }:
            attrs.setdefault('inputmode', 'numeric')
        if mask == 'cpf':
            attrs.setdefault('maxlength', '14')
            attrs['data-validate'] = 'cpf'
        elif mask == 'cnpj':
            attrs.setdefault('maxlength', '18')
            attrs['data-validate'] = 'cnpj'
        elif mask == 'cpf-cnpj':
            attrs.setdefault('maxlength', '18')
            attrs['data-validate'] = 'cpf-cnpj'
        elif mask == 'cep':
            attrs.setdefault('maxlength', '9')
            attrs['data-cep-source'] = 'true'
        elif mask == 'phone':
            attrs['type'] = 'tel'
            attrs.setdefault('maxlength', '15')
            attrs.setdefault('autocomplete', 'tel')
        elif mask == 'ncm':
            attrs.setdefault('maxlength', '10')
        elif mask == 'cfop':
            attrs.setdefault('maxlength', '4')
        elif mask == 'cest':
            attrs.setdefault('maxlength', '9')

    if address_target and (
        _uses_text_input(field)
        or getattr(field, 'widget', None)
        and isinstance(field.widget, forms.Select)
    ):
        attrs['data-address-target'] = address_target
        if address_target == 'state' and _uses_text_input(field):
            attrs.setdefault('maxlength', '2')


def _validate_cpf(value):
    digits = _only_digits(value)
    if len(digits) != 11 or digits == digits[0] * 11:
        return False

    first_sum = sum(int(digits[index]) * (10 - index) for index in range(9))
    first_digit = 11 - (first_sum % 11)
    first_digit = 0 if first_digit >= 10 else first_digit
    second_sum = sum(int(digits[index]) * (11 - index) for index in range(10))
    second_digit = 11 - (second_sum % 11)
    second_digit = 0 if second_digit >= 10 else second_digit
    return digits[-2:] == f'{first_digit}{second_digit}'


def _validate_cnpj(value):
    digits = _only_digits(value)
    if len(digits) != 14 or digits == digits[0] * 14:
        return False

    first_weights = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    second_weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    first_sum = sum(
        int(digit) * weight for digit, weight in zip(digits[:12], first_weights, strict=True)
    )
    first_digit = 0 if first_sum % 11 < 2 else 11 - (first_sum % 11)
    second_sum = sum(
        int(digit) * weight for digit, weight in zip(digits[:13], second_weights, strict=True)
    )
    second_digit = 0 if second_sum % 11 < 2 else 11 - (second_sum % 11)
    return digits[-2:] == f'{first_digit}{second_digit}'


def _document_is_valid(mask, value):
    digits = _only_digits(value)
    if mask == 'cpf':
        return _validate_cpf(digits)
    if mask == 'cnpj':
        return _validate_cnpj(digits)
    if mask == 'cpf-cnpj':
        if len(digits) == 11:
            return _validate_cpf(digits)
        if len(digits) == 14:
            return _validate_cnpj(digits)
        return False
    return True


def build_resource_form(resource, *, update=False):
    if update and resource.update_form_fields is not None:
        form_fields = resource.update_form_fields
    else:
        form_fields = resource.form_fields or tuple(
            field.name
            for field in resource.model._meta.fields
            if field.editable and not field.auto_created and field.name not in SYSTEM_FIELD_NAMES
        )
    financial_metadata_form = resource.model in (FinancialTitle, FinancialAccount)
    if financial_metadata_form:
        form_fields = tuple(
            name for name in form_fields if name not in resource.model.SERVICE_FIELDS
        )
    User = get_user_model()
    form_base = resource.form_base or forms.ModelForm

    if not TYPE_CHECKING:
        # Keep the resource's custom form and cooperative MRO unchanged at runtime.
        ResourceFormBase = form_base

    class ResourceForm(ResourceFormBase):
        def __init__(self, *args, request=None, **kwargs):
            super().__init__(*args, **kwargs)

            for field_name in automatic_generated_fields(resource.model):
                if field_name not in self.fields:
                    continue
                field = self.fields[field_name]
                field.disabled = True
                if update:
                    field.help_text = 'Identificador imutável após o cadastro.'
                else:
                    field.required = False
                    field.initial = None
                    field.help_text = 'Gerado automaticamente pelo sistema ao salvar.'
                    field.widget.attrs['placeholder'] = 'Gerado automaticamente ao salvar'

            for name, field in self.fields.items():
                _apply_widget_metadata(name, field)

            if request is None:
                return

            for field in self.fields.values():
                queryset = getattr(field, 'queryset', None)
                if queryset is None:
                    continue

                model = queryset.model
                if model is User:
                    field.queryset = queryset.filter(is_active=True)

        def _get_validation_exclusions(self):
            exclusions = super()._get_validation_exclusions()
            if not update:
                exclusions.update(
                    field_name
                    for field_name in automatic_generated_fields(resource.model)
                    if field_name in self.fields
                )
            return exclusions

        def resource_save_kwargs(self):
            if financial_metadata_form and not self.instance._state.adding:
                # Validation may derive balances on the form's stale instance.
                # Only submitted editable changes reach the locked model protocol.
                return {'update_fields': set(self.changed_data) & set(self.fields)}
            return {}

        def save(self, commit=True):
            if not financial_metadata_form or not commit:
                return super().save(commit=commit)
            instance = super().save(commit=False)
            instance.save(**self.resource_save_kwargs())
            self._save_m2m()
            return instance

        def _update_errors(self, errors):
            if financial_metadata_form and hasattr(errors, 'error_dict'):
                normalized = {}
                for name, error_list in errors.error_dict.items():
                    target = name if name in self.fields else NON_FIELD_ERRORS
                    normalized.setdefault(target, []).extend(error_list)
                errors = ValidationError(normalized)
            super()._update_errors(errors)

        def clean(self):
            cleaned_data = super().clean()
            if resource.model is FinancialTitle and 'original_amount' in cleaned_data:
                # Model.clean runs in _post_clean, before save can derive this.
                # This is validation-only; the locked model derives it again.
                self.instance.open_amount = (
                    cleaned_data['original_amount'] - self.instance.paid_amount
                )
            for name, field in self.fields.items():
                mask = field.widget.attrs.get('data-validate')
                if mask not in {'cpf', 'cnpj', 'cpf-cnpj'}:
                    continue

                value = cleaned_data.get(name)
                if value and not _document_is_valid(mask, value):
                    self.add_error(name, DOCUMENT_VALIDATION_ERROR)
            return cleaned_data

        class Meta:
            model = resource.model
            fields = form_fields
            formfield_callback = _secure_formfield

    return ResourceForm
