"""Contratos de tipagem compartilhados por mixins de serializers DRF."""

from typing import Any
from copy import copy


def instance_for_clean(model, original, attrs):
    if original is None:
        return model(**attrs)
    instance = copy(original)
    instance._state = copy(original._state)
    instance._state.fields_cache = original._state.fields_cache.copy()
    for name, value in attrs.items():
        setattr(instance, name, value)
    return instance


def incoming_value_changes_field(instance, field_name, incoming):
    """Indica se o valor recebido difere do persistido (FK compara pela chave)."""
    field = instance._meta.get_field(field_name)
    current = getattr(instance, field.attname)
    if incoming in (None, ''):
        return current not in (None, '')
    if current is None:
        return True
    if field.is_relation:
        return str(incoming) != str(current)
    try:
        return field.to_python(incoming) != current
    except Exception:
        return True


class ModelSerializerContractMixin:
    """Declara atributos fornecidos pelo ``ModelSerializer`` na classe final."""

    instance: Any
    Meta: Any

    def get_fields(self):
        fields = getattr(super(), 'get_fields')()
        from base.automatic_fields import automatic_generated_fields

        for field_name in automatic_generated_fields(self.Meta.model):
            if field_name in fields:
                fields[field_name].read_only = True
        return fields
