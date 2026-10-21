"""Agrupamento visual; não cria campos, formsets ou permissões."""

from typing import Any

from .form_tab_groups import FORM_TAB_GROUPS


def _domain_parent_tabs(resource, fields):
    groups = FORM_TAB_GROUPS.get((resource.app_label, resource.slug), ())
    # First assignment wins, even if a future declaration accidentally repeats a name.
    owners = {}
    for key, _label, names in groups:
        for name in names:
            owners.setdefault(name, key)
    tabs = [
        {
            'key': key,
            'label': label,
            'fields': [field for field in fields if owners.get(field.name, 'general') == key],
            'inline': None,
        }
        for key, label, _names in groups
    ]
    tabs = [tab for tab in tabs if tab['fields']]
    # Sparse/authorized forms keep their existing general layout, not empty panels.
    if len(tabs) < 2 or tabs[0]['key'] != 'general':
        return []
    return tabs


def build_resource_form_layout(resource, form, inline_formsets):
    is_formula = (resource.app_label, resource.slug) == ('formulations', 'formulas')
    fields = list(form.visible_fields())
    parent_tabs = [] if is_formula else _domain_parent_tabs(resource, fields)
    if not is_formula and not inline_formsets and not parent_tabs:
        return {'form_tabs': [], 'active_form_tab': ''}

    tabs: list[dict[str, Any]]
    if is_formula:
        tabs = [
            {
                'key': 'formula',
                'label': 'Fórmula mestra',
                'fields': fields,
                'inline': None,
            },
        ]
        main_key = 'formula'
    else:
        tabs = parent_tabs or [
            {'key': 'general', 'label': 'Informações gerais', 'fields': fields, 'inline': None}
        ]
        main_key = 'general'

    for item in inline_formsets:
        tabs.append(
            {
                'key': f'inline-{item["key"]}',
                'label': 'Componentes'
                if is_formula and item['key'] == 'components'
                else item['title'],
                'fields': [],
                'inline': item,
            }
        )

    for tab in tabs:
        tab['has_errors'] = any(bool(field.errors) for field in tab['fields'])
        item = tab['inline']
        if item is not None and item['available'] and item['formset'] is not None:
            formset = item['formset']
            tab['has_errors'] = bool(any(formset.errors) or formset.non_form_errors())

    if form.non_field_errors():
        active_key = main_key
        next(tab for tab in tabs if tab['key'] == main_key)['has_errors'] = True
    else:
        active_key = next((tab['key'] for tab in tabs if tab['has_errors']), tabs[0]['key'])
    for tab in tabs:
        tab['active'] = tab['key'] == active_key
    return {'form_tabs': tabs, 'active_form_tab': active_key}
