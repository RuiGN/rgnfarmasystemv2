"""Executable, exhaustive schema inventory; writes only isolated QA artifacts."""

import json
from collections import Counter
from pathlib import Path

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from base.ui.actions.forms import build_action_form
from base.ui.actions.registry import action_registry
from base.ui.forms import build_resource_form
from base.ui.registry import get_modules
from base.ui.related_fields import configure_related_fields, related_field_specs
from base.ui.views import _build_inline_formset

OUTPUT = Path(
    '/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/related-input-inventory.json'
)


def describe(form, model, context):
    entries = []
    specs = related_field_specs(form)
    model_fields = {field.name: field for field in model._meta.get_fields()}
    for name, field in form.fields.items():
        db_field = model_fields.get(name)
        target = getattr(getattr(field, 'queryset', None), 'model', None)
        ref = None
        if isinstance(field, (forms.CharField, forms.ChoiceField)) and not isinstance(
            field, forms.ModelChoiceField
        ):
            aliases = [f'{name}_ref']
            if name.endswith('_terms'):
                aliases.append(f'{name[:-1]}_ref')
            for candidate in aliases:
                candidate_field = model_fields.get(candidate)
                if candidate_field is not None and candidate_field.is_relation:
                    ref = candidate
                    break
        dependencies = [
            dict(controller=spec[1], path=spec[2], generic=spec[3], controller_path=spec[4])
            for spec in specs
            if spec[0] == name
        ]
        for rule in getattr(form, '_related_field_rules', {}).get(name, []):
            if not any(item['controller'] == rule['field'] for item in dependencies):
                dependencies.append(
                    {
                        'controller': rule['field'],
                        'path': rule['path'],
                        'controller_scope': 'parent' if 'controller_form' in rule else 'self',
                        'generic': False,
                        'controller_path': rule.get('controller_path', ''),
                        'controller_identity_authoritative': 'controller_instance' in rule,
                    }
                )
        status = 'native_scalar'
        reason = 'Sem FK comprovada; manter campo do domínio, sem inferir relação pelo nome.'
        if isinstance(field, forms.ChoiceField):
            status, reason = 'native_choice', 'Enumeração definida pelo modelo/ação; não é uma FK.'
        if target:
            status, reason = (
                'fk_model_choice',
                'ModelChoiceField já valida a queryset existente; nenhuma expansão autorizada.',
            )
            if isinstance(field, forms.ModelMultipleChoiceField):
                status, reason = (
                    'm2m_model_multiple_choice',
                    'Seleção múltipla existente preservada, sem inferir dependência escalar.',
                )
        if ref:
            status, reason = (
                'retained_normalized_text',
                'FK normalizada existente; texto legado preservado: sincronização/contrato consumidores não substituído.',
            )
        if dependencies or field.widget.attrs.get('data-related-rules'):
            status, reason = (
                'supported_dependency',
                'Regra explícita pelo modelo; metadados somente de escolhas já autorizadas e validação servidor.',
            )
        if model._meta.label_lower == 'masters.product' and name in (
            'category',
            'product_line',
            'cosmetic_form',
            'application_area',
        ):
            status, reason = (
                'supported_kind_filter',
                'Product._validate_category define o kind exato.',
            )
        if (
            target
            and target._meta.label_lower == 'auxiliary.commercialterm'
            and name in ('payment_term_ref', 'delivery_term_ref')
        ):
            status, reason = (
                'supported_kind_filter',
                'CommercialTerm.TermType PAYMENT/DELIVERY; sem substituir texto comercial histórico.',
            )
        if field.widget.is_hidden:
            status, reason = (
                'excluded_hidden',
                'Campo oculto de infraestrutura/identidade/parent; não recriar nem alterar widget.',
            )
        elif field.disabled:
            status, reason = (
                'excluded_disabled',
                'Controle imutável/sem edição; preservar queryset e valor inicial.',
            )
        candidates = []
        if target:
            for relation in target._meta.fields:
                if not relation.many_to_one:
                    continue
                for sibling_name, sibling in form.fields.items():
                    sibling_target = getattr(getattr(sibling, 'queryset', None), 'model', None)
                    if sibling_name == name or sibling_target is not relation.related_model:
                        continue
                    supported = any(
                        spec[0] == name and spec[1] == sibling_name and spec[2] == relation.name
                        for spec in specs
                    )
                    candidates.append(
                        {
                            'controller': sibling_name,
                            'path': relation.name,
                            'status': 'supported'
                            if supported
                            else 'excluded_not_in_domain_allowlist',
                            'reason': 'Correspondência explícita na allowlist.'
                            if supported
                            else 'FK no alvo não prova que os dois campos representam o mesmo contexto; manter domínio existente (cópia, origem, evidência ou relação independente). Suporte adicional exige regra/teste do fluxo.',
                        }
                    )
        normalized_target = model_fields[ref].related_model._meta.label_lower if ref else None
        entries.append(
            {
                **context,
                'field': name,
                'form_field_type': type(field).__name__,
                'widget': type(field.widget).__name__,
                'model_field_type': type(db_field).__name__ if db_field else None,
                'target_model': (
                    target._meta.label_lower
                    if target
                    else db_field.related_model._meta.label_lower
                    if db_field is not None and db_field.is_relation
                    else normalized_target
                ),
                'status': status,
                'reason': reason,
                'dependencies': dependencies,
                'relationship_candidates': candidates,
                'normalized_reference': ref,
                'reference_rendered': ref in form.fields if ref else None,
                'required': field.required,
                'disabled': field.disabled,
                'hidden': field.widget.is_hidden,
            }
        )
    return entries


@pytest.mark.django_db
def test_inventory_covers_every_registry_resource_inline_and_action():
    request = RequestFactory().get('/')
    request.user = get_user_model()(is_staff=True, is_superuser=True, is_active=True)
    rows, forms_index = [], []
    expected_resources = set()
    for module in get_modules():
        for resource in module.resources:
            expected_resources.add((module.slug, resource.slug))
            base = {
                'module': module.slug,
                'resource': resource.slug,
                'model': resource.model._meta.label_lower,
                'read_only_resource': resource.read_only,
            }
            for update in (False, True):
                form = build_resource_form(resource, update=update)(request=request)
                context = {
                    **base,
                    'surface': 'resource',
                    'variant': 'update' if update else 'create',
                    'form_key': None,
                }
                rows.extend(describe(form, resource.model, context))
                forms_index.append({**context, 'field_count': len(form.fields)})
            for inline in resource.inlines:
                formset = _build_inline_formset(
                    request,
                    resource,
                    inline,
                    instance=resource.model(),
                    parent_form=build_resource_form(resource)(request=request),
                )
                form = formset.empty_form
                context = {
                    **base,
                    'surface': 'inline',
                    'variant': 'empty_form',
                    'form_key': inline.key,
                    'child_model': inline.child_model._meta.label_lower,
                    'parent_field': inline.parent_field,
                }
                rows.extend(describe(form, inline.child_model, context))
                forms_index.append({**context, 'field_count': len(form.fields)})
                context = {**context, 'surface': 'management'}
                rows.extend(describe(formset.management_form, inline.child_model, context))
                forms_index.append({**context, 'field_count': len(formset.management_form.fields)})
    actions = action_registry.all()
    for config in actions:
        form = build_action_form(config, request)()
        configure_related_fields(form)
        context = {
            'module': config.module_slug,
            'resource': config.resource_slug,
            'model': config.model._meta.label_lower,
            'surface': 'action',
            'variant': 'action',
            'form_key': config.action_name,
            'read_only_resource': False,
        }
        rows.extend(describe(form, config.model, context))
        forms_index.append({**context, 'field_count': len(form.fields)})
    observed_resources = {
        (row['module'], row['resource']) for row in forms_index if row['surface'] == 'resource'
    }
    assert observed_resources == expected_resources
    assert len([row for row in forms_index if row['surface'] == 'action']) == len(actions)
    assert len(rows) == sum(row['field_count'] for row in forms_index)
    keys = [
        (
            row['module'],
            row['resource'],
            row['surface'],
            row['variant'],
            row['form_key'],
            row['field'],
        )
        for row in rows
    ]
    assert len(keys) == len(set(keys))
    receipt_item = next(
        row
        for row in rows
        if row['module'] == 'procurement'
        and row['resource'] == 'receipts'
        and row['surface'] == 'inline'
        and row['field'] == 'order_item'
    )
    assert any(
        rule['controller'] == 'order'
        and rule['path'] == 'order'
        and rule.get('controller_scope') == 'parent'
        for rule in receipt_item['dependencies']
    ), 'Inventory must exercise the real authoritative inline-parent builder.'
    output = {
        'schema': 'related-input-inventory/v1',
        'scope': 'registry resource create/update, inline empty+management, all action forms; schema, not permission-specific live DOM',
        'resources': len(expected_resources),
        'actions': len(actions),
        'forms': len(forms_index),
        'fields': len(rows),
        'counts_by_status': dict(Counter(row['status'] for row in rows)),
        'counts_by_surface': dict(Counter(row['surface'] for row in rows)),
        'exclusions': [
            'Read-only resources are inventoried as definitions, not editable endpoints.',
            'Optional historical orphan geography is retained in storage; incompatible new selections are rejected in HTML forms.',
            'Other self-references, polymorphic links and same-target siblings have no inferred hierarchy.',
            'Actions have no ModelForm model context: category-parent and Product kind specialization require ModelForm; relation dependencies use queryset.model.',
            'No legacy/regulatory text was deleted, hidden or migrated by this mechanism.',
            'Generic routes formula=None remain valid; no status/lifecycle authorization is changed.',
        ],
        'forms_index': forms_index,
        'entries': rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, indent=2, ensure_ascii=False) + '\n')
    print(
        json.dumps(
            {key: value for key, value in output.items() if key not in ('entries', 'forms_index')},
            ensure_ascii=False,
        )
    )
