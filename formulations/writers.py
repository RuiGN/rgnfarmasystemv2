"""Application write protocol for Product / MasterFormula / FormulaComponent.

The transaction gate deliberately serializes this small maintenance surface. It
also makes parent discovery stable during moves/creates: after the gate, rows
are locked in Product -> MasterFormula -> FormulaComponent order, by primary key.
Raw SQL, queryset.update and third-party ORM writers are not covered.
"""

from contextlib import contextmanager

from django.db import connection, transaction
from base.serializer_mixins import ModelSerializerContractMixin


LABELS = {'masters.product', 'formulations.masterformula', 'formulations.formulacomponent'}
# Stable namespace, not Python's process-randomized hash().
GATE_KEY = 714036052019


def supports(instance):
    return instance._meta.label_lower in LABELS


@contextmanager
def write_gate():
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [GATE_KEY])
        yield


def apply_changes(instance, changes):
    """Drop cached related objects; validation must read current related state."""
    for name, value in changes.items():
        field = instance._meta.get_field(name)
        if field.is_relation:
            setattr(instance, field.attname, getattr(value, 'pk', value))
            if field.is_cached(instance):
                field.delete_cached_value(instance)
        else:
            setattr(instance, name, value)
    instance._state.fields_cache.clear()
    return instance


@contextmanager
def locked_instance(instance, changes=None):
    from formulations.models import FormulaComponent, MasterFormula
    from masters.models import Product

    changes = changes or {}
    with write_gate():
        current = type(instance).objects.get(pk=instance.pk) if instance.pk else instance
        product_ids, formula_ids = set(), set()
        candidates = [current]
        if changes:
            from copy import copy

            candidate = copy(current)
            candidate._state = copy(current._state)
            candidate._state.fields_cache = {}
            candidates.append(apply_changes(candidate, changes))
        for candidate in candidates:
            if isinstance(candidate, Product):
                product_ids.add(candidate.pk)
            elif isinstance(candidate, MasterFormula):
                product_ids.add(candidate.product_id)
                formula_ids.add(candidate.pk)
            elif isinstance(candidate, FormulaComponent):
                formula_ids.add(candidate.formula_id)
                # Material is a reference, not another aggregate parent. Its
                # supported writes share the gate; acquiring a new Product row
                # here would invert the outer formula/inlines lock hierarchy.
        formula_ids.discard(None)
        product_ids.update(
            MasterFormula.objects.filter(pk__in=formula_ids).values_list('product_id', flat=True)
        )
        product_ids.discard(None)
        list(Product.objects.filter(pk__in=product_ids).order_by('pk').select_for_update())
        list(MasterFormula.objects.filter(pk__in=formula_ids).order_by('pk').select_for_update())
        if isinstance(current, FormulaComponent) and current.pk:
            current = FormulaComponent.objects.select_for_update().get(pk=current.pk)
        elif current.pk:
            current = type(current).objects.get(pk=current.pk)
        yield apply_changes(current, changes)


def validate_final(instance):
    from formulations.models import MasterFormula

    if isinstance(instance, MasterFormula) and instance.status == MasterFormula.Status.APPROVED:
        for component in instance.components.select_related('formula', 'material'):
            component.full_clean()


def save_changes(instance, changes, *, final=True):
    with locked_instance(instance, changes) as current:
        current.full_clean()
        current.save()
        if final:
            validate_final(current)
        return current


def form_changes(form):
    names = form.changed_data if form.instance.pk else form.cleaned_data
    concrete = {field.name for field in form.instance._meta.concrete_fields}
    return {
        name: form.cleaned_data[name]
        for name in names
        if name in concrete and name in form.cleaned_data
    }


def save_form(form, *, final=True):
    current = save_changes(form.instance, form_changes(form), final=final)
    form.instance = current
    return current


def delete_instance(instance):
    with locked_instance(instance) as current:
        return current.delete()


class WriterViewSetMixin:
    def perform_destroy(self, instance):
        from django.db.models.deletion import ProtectedError
        from rest_framework.exceptions import ValidationError

        try:
            delete_instance(instance)
        except ProtectedError as error:
            raise ValidationError('O registro está em uso e não pode ser excluído.') from error


class WriterSerializerMixin(ModelSerializerContractMixin):
    def create(self, validated_data):
        return self._write(self.Meta.model(), validated_data)

    def update(self, instance, validated_data):
        return self._write(instance, validated_data)

    def _write(self, instance, attrs):
        from django.core.exceptions import ValidationError
        from rest_framework.exceptions import ValidationError as APIValidationError

        try:
            return save_changes(instance, attrs)
        except ValidationError as error:
            raise APIValidationError(getattr(error, 'message_dict', error.messages)) from error
