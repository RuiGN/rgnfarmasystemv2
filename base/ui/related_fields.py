"""Small allowlisted dependency contract shared by ModelForms and action Forms.

Only existing ModelChoiceFields are narrowed. Metadata never expands a queryset;
server clean validates the same rules even when JavaScript is absent.
"""

import json
from functools import partial

from django import forms
from django.db.models import BooleanField, Case, Q, Value, When
from django.utils.functional import SimpleLazyObject, lazy


CATEGORY_PARENTS: dict[str, tuple[str, ...]] = {
    # Existing composite-identity fixtures permit Category -> Family. Do not
    # invent a strict taxonomy for the three historical hierarchy kinds.
    kind: ('family', 'group', 'category')
    for kind in ('family', 'group', 'category')
}
CATEGORY_PARENTS.update(
    {
        kind: (kind,)
        for kind in (
            'product_line',
            'cosmetic_form',
            'presentation',
            'concentration',
            'application_area',
        )
    }
)
PRODUCT_KINDS = {
    'category': 'category',
    'product_line': 'product_line',
    'cosmetic_form': 'cosmetic_form',
    'application_area': 'application_area',
}
# (child target, relation path, sibling name, null is a generic match).
# Exact names and model identities are intentional: two FKs to Product need
# not describe the same product (formula material, genealogy, substitution).
DEPENDENCIES = (
    ('masters.warehouse', 'site', 'site', False),
    ('masters.storagelocation', 'warehouse', 'warehouse', False),
    ('formulations.masterformula', 'product', 'product', False),
    ('formulations.manufacturingroute', 'product', 'product', False),
    ('formulations.manufacturingroute', 'formula', 'formula', True),
    ('procurement.purchaseorderitem', 'order', 'order', False),
    ('procurement.purchaseorderitem', 'order', 'receipt__order', False),
    ('procurement.purchasereceiptitem', 'receipt', 'receipt', False),
)

# Owner model -> (dependent field, controller[__path], dependent path, generic).
# Equalities in the named owner's clean(), not target/name guesses. Inverse
# item -> product avoids keeping an unrelated product after changing an item.
# 'pk' explicitly denotes identity, not a join.
MODEL_DEPENDENCIES = {
    'procurement.purchasereceiptitem': (('product', 'order_item__product', 'pk', False),),
    'procurement.purchaseorderitem': (('product', 'requisition_item__product', 'pk', False),),
    'procurement.purchaserequisitionitem': (('product', 'mrp_suggestion__product', 'pk', False),),
    'quality.qualityanalysis': (('specification', 'sample__product', 'product', False),),
    'quality.qualityresult': (('specification', 'analysis__sample__product', 'product', False),),
    'inventory.stockbalance': (('lot', 'product', 'product', False),),
    **{
        owner: (('stock_lot', 'product', 'product', False),)
        for owner in (
            'changes.changestockassessment',
            'crm.customercomplaint',
            'deviations.qualityevent',
            'qa.lotrelease',
            'qa.qualityblock',
            'quality.analyticalspecification',
            'quality.qualitysample',
            'quality.qualitydocument',
            'recalls.marketcomplaint',
            'recalls.productreturn',
            'recalls.recallcampaign',
        )
    },
    'production.materialconsumption': (
        ('component', 'order__formula', 'formula', False),
        ('material', 'component__material', 'pk', False),
        ('stock_lot', 'material', 'product', False),
    ),
    'production.productionoutput': (('product', 'order__product', 'pk', False),),
    'production.productionoperationexecution': (('route_step', 'order__route', 'route', False),),
    'production.productionlaborentry': (('operation_execution', 'order', 'order', False),),
}

# Shared descriptors still list each proven owner explicitly. In particular,
# complaint/customer differs from complaint/product; no same-target heuristic.
for _owners, _rules in (
    (('audits.auditfinding',), (('checklist_item', 'audit', 'audit', False),)),
    (
        ('capa.capanotification',),
        (
            ('action', 'capa', 'capa', False),
            ('approval', 'capa', 'capa', False),
            ('effectiveness_check', 'capa', 'capa', False),
        ),
    ),
    (
        ('crm.opportunity', 'crm.customerinteraction', 'crm.customercomplaint'),
        (('contact', 'customer', 'customer', False),),
    ),
    (
        ('crm.salesproposal', 'crm.salescontract', 'crm.customerinteraction'),
        (('opportunity', 'customer', 'customer', False),),
    ),
    (('crm.salescontract', 'crm.salesorder'), (('proposal', 'customer', 'customer', False),)),
    (('crm.salesorder',), (('contract', 'customer', 'customer', False),)),
    (
        (
            'crm.customercomplaint',
            'recalls.marketcomplaint',
            'recalls.productreturn',
            'recalls.recallimpactedcustomer',
        ),
        (
            ('sales_order', 'customer', 'customer', False),
            ('fiscal_document', 'customer', 'partner', False),
        ),
    ),
    (('fiscal.fiscaldocument',), (('purchase_receipt', 'purchase_order', 'order', False),)),
    (('fiscal.fiscaltax',), (('item', 'document', 'document', False),)),
    (('fiscal.fiscaltax',), (('tax_rule', 'tax_kind', 'tax_kind', False),)),
    (('fiscal.taxrule',), (('tax_situation', 'tax_kind', 'tax_kind', False),)),
    (('qa.qareview',), (('quality_document', 'stock_lot', 'stock_lot', False),)),
    (
        ('qa.lotrelease',),
        (
            ('qa_review', 'stock_lot', 'stock_lot', False),
            ('qa_review', 'quality_document', 'quality_document', True),
            ('qa_review', 'production_order', 'production_order', True),
            ('quality_document', 'stock_lot', 'stock_lot', False),
            ('quality_document', 'product', 'product', False),
            ('production_order', 'product', 'product', False),
            ('production_order', 'stock_lot__source_production_order', 'pk', False),
        ),
    ),
    (
        ('quality.laboratoryinvestigation',),
        (
            ('analysis', 'sample', 'sample', False),
            ('result', 'analysis', 'analysis', False),
        ),
    ),
    (('quality.qualitydocument',), (('sample', 'product', 'product', False),)),
    (('quality.qualitysample',), (('specification', 'product', 'product', False),)),
    (
        ('recalls.marketcomplaint',),
        (
            ('customer_complaint', 'customer', 'customer', False),
            ('quality_sample', 'product', 'product', False),
        ),
    ),
    (('recalls.productreturn',), (('complaint', 'customer', 'customer', False),)),
    (('recalls.recallcampaign',), (('complaint', 'product', 'product', False),)),
    (('training.trainingenrollment',), (('session', 'requirement', 'requirement', False),)),
    (
        ('training.trainingrequirement', 'training.trainingmatrixrequirement'),
        (('function', 'job_position', 'job_position', True),),
    ),
):
    for _owner in _owners:
        MODEL_DEPENDENCIES[_owner] = MODEL_DEPENDENCIES.get(_owner, ()) + _rules

# clean() compares these pairs only when the optional controller is present.
# A blank match uses the existing JSON protocol, not a client-side exception.
ALLOW_EMPTY_CONTROLLERS = {
    ('procurement.purchaseorderitem', 'product', 'requisition_item'),
    ('procurement.purchaserequisitionitem', 'product', 'mrp_suggestion'),
    ('production.materialconsumption', 'material', 'component'),
    ('crm.customercomplaint', 'stock_lot', 'product'),
    ('deviations.qualityevent', 'stock_lot', 'product'),
    ('qa.qualityblock', 'stock_lot', 'product'),
    ('qa.qareview', 'quality_document', 'stock_lot'),
    ('fiscal.fiscaldocument', 'purchase_receipt', 'purchase_order'),
    ('quality.laboratoryinvestigation', 'result', 'analysis'),
    ('training.trainingrequirement', 'function', 'job_position'),
}

# Relations actually dereferenced by these option labels. Joining never changes
# authorization/membership and does not load one object per rendered option.
LABEL_RELATIONS = {
    'formulations.formulacomponent': ('formula', 'material'),
    'procurement.purchaserequisitionitem': ('requisition', 'product'),
    'procurement.purchaseorderitem': ('order', 'product'),
    'procurement.purchasereceiptitem': ('receipt', 'product'),
    'quality.analyticalspecification': ('product',),
    'quality.qualityresult': ('analysis',),
    'inventory.stocklot': ('product',),
}


def _choice(field):
    return isinstance(field, forms.ModelChoiceField) and not isinstance(
        field, forms.ModelMultipleChoiceField
    )


def _visible(field):
    return not field.widget.is_hidden and isinstance(field.widget, forms.Select)


def _initial(form, name):
    value = form.get_initial_for_field(form.fields[name], name)
    return str(getattr(value, 'pk', value) or '')


def _descendants(model, pk):
    """One graph query, including hidden ancestors; IDs are never sent to HTML."""
    edges = list(model._default_manager.values_list('pk', 'parent_id'))
    excluded = {pk}
    while True:
        more = {child for child, parent in edges if parent in excluded} - excluded
        if not more:
            return excluded
        excluded.update(more)


def related_field_specs(form):
    """Discover only explicit supported edges among fields already on this form.

    Also works for forms.Form: targets come from field.queryset.model. A hidden
    controller is not enhanced or reconstructed (inline parent FKs are usually
    injected later by Django); model/domain validation still owns those paths.
    """
    specs = []
    fields = form.fields
    for name, field in fields.items():
        if not _choice(field) or not _visible(field) or field.disabled:
            continue
        target = field.queryset.model
        label = target._meta.label_lower
        if label == 'auxiliary.stateprovince':
            suffix = 'state_ref' if name.endswith('state_ref') else 'state'
            prefix = name[: -len(suffix)] if name.endswith(suffix) else None
            controller = f'{prefix}country_ref' if suffix == 'state_ref' else f'{prefix}country'
            if prefix is not None:
                specs.append((name, controller, 'country', False))
        elif label == 'auxiliary.city':
            suffix = 'city_ref' if name.endswith('city_ref') else 'city'
            prefix = name[: -len(suffix)] if name.endswith(suffix) else None
            controller = f'{prefix}state_ref' if suffix == 'city_ref' else f'{prefix}state'
            if prefix is not None:
                specs.append((name, controller, 'state', False))
        for child_label, path, controller, generic in DEPENDENCIES:
            canonical_names = {
                'masters.warehouse': 'warehouse',
                'masters.storagelocation': 'location',
                'formulations.masterformula': 'formula',
                'formulations.manufacturingroute': 'route',
                'procurement.purchaseorderitem': 'order_item',
                'procurement.purchasereceiptitem': 'receipt_item',
            }
            if label == child_label and name == canonical_names[child_label] and name != controller:
                specs.append((name, controller, path, generic))
        if label == 'auxiliary.catalogvalue':
            specs.append((name, 'catalog_type', 'catalog_type', False))
    model = getattr(getattr(form, '_meta', None), 'model', None)
    if model:
        specs.extend(MODEL_DEPENDENCIES.get(model._meta.label_lower, ()))
    supported = []
    for name, controller, path, generic in specs:
        field = fields.get(name)
        if not _choice(field) or not _visible(field) or field.disabled:
            continue
        controller, _, controller_path = controller.partition('__')
        other = fields.get(controller)
        if (
            model
            and (name, controller, path, generic)
            in MODEL_DEPENDENCIES.get(model._meta.label_lower, ())
            and path == 'tax_kind'
            and isinstance(other, forms.ChoiceField)
            and not _choice(other)
            and _visible(other)
        ):
            supported.append((name, controller, path, generic, controller_path))
            continue
        if not _choice(other) or not _visible(other):
            continue
        related = fields[name].queryset.model
        for part in () if path == 'pk' else path.split('__'):
            related = related._meta.get_field(part).related_model
        controller_model = other.queryset.model
        if controller_path:
            for part in controller_path.split('__'):
                controller_model = controller_model._meta.get_field(part).related_model
        if controller_model is related and (path == 'pk' or related is not field.queryset.model):
            supported.append((name, controller, path, generic, controller_path))
    return supported


def configure_related_fields(form):
    """Call at the END of __init__, after custom permissions/disabled handling.

    Idempotent per form instance. Dynamic inline prefixes must be replaced in
    data-related-rules along with normal name/id attrs by the inline renderer.
    """
    if getattr(form, '_related_fields_configured', False):
        return
    form._related_fields_configured = True
    form._related_field_rules = {}
    model = getattr(getattr(form, '_meta', None), 'model', None)
    label = model._meta.label_lower if model else ''
    for name, field in form.fields.items():
        if not _choice(field) or field.disabled or not _visible(field):
            continue
        target = field.queryset.model._meta.label_lower
        if target in LABEL_RELATIONS:
            field.queryset = field.queryset.select_related(*LABEL_RELATIONS[target])
        if (
            label == 'masters.product'
            and target == 'masters.mastercategory'
            and name in PRODUCT_KINDS
        ):
            field.queryset = field.queryset.filter(kind=PRODUCT_KINDS[name])
        if target == 'auxiliary.commercialterm' and name in (
            'payment_term_ref',
            'delivery_term_ref',
        ):
            field.queryset = field.queryset.filter(term_type=name.split('_')[0])

    if label == 'masters.mastercategory' and 'kind' in form.fields and 'parent' in form.fields:
        field = form.fields['parent']
        if (
            _choice(field)
            and _visible(field)
            and not field.disabled
            and not form.fields['kind'].widget.is_hidden
        ):
            if form.instance.pk:
                field.queryset = field.queryset.exclude(
                    pk__in=_descendants(model, form.instance.pk)
                )
            values = SimpleLazyObject(partial(_category_values, form, field))
            _add_rule(form, 'parent', 'kind', values, path='kind')

    for name, controller, path, generic, controller_path in related_field_specs(form):
        field = form.fields[name]
        # Labels such as MasterFormula.__str__ dereference product. Join only
        # the proven path; select_related changes loading, never row membership.
        if path not in ('pk', 'tax_kind'):
            field.queryset = field.queryset.select_related(path)
        controller_field = form.fields[controller]
        values = SimpleLazyObject(
            partial(
                _relation_values,
                field,
                controller_field,
                path,
                generic,
                controller_path,
                (label, name, controller) in ALLOW_EMPTY_CONTROLLERS,
            )
        )
        _add_rule(form, name, controller, values, path=path, controller_path=controller_path)


def _category_values(form, field):
    key = field.to_field_name or field.queryset.model._meta.pk.name
    rows = list(field.queryset.values_list(key, 'kind', 'pk'))
    values = {
        str(value): [kind for kind, allowed in CATEGORY_PARENTS.items() if parent_kind in allowed]
        for value, parent_kind, _pk in rows
    }
    old_parent = str(form.instance.parent_id or '')
    old_kind = _initial(form, 'kind')
    for value, _kind, pk in rows:
        # Preserve an unchanged authorized historical edge, never a cycle.
        if form.instance.pk and str(pk) == old_parent and old_kind not in values[str(value)]:
            values[str(value)].append(old_kind)
    return values


def _relation_values(field, controller_field, path, generic, controller_path, allow_empty=False):
    key = field.to_field_name or field.queryset.model._meta.pk.name
    if not _choice(controller_field):
        return {str(pk): [str(value)] for pk, value in field.queryset.values_list(key, path)}
    target_key = controller_field.to_field_name or controller_field.queryset.model._meta.pk.name
    if controller_path or path == 'pk':
        # Match item.order to receipt.order, using only authorized receipts.
        controllers = {}
        for pk, value in controller_field.queryset.values_list(
            target_key, f'{controller_path}__pk' if controller_path else 'pk'
        ):
            controllers.setdefault(value, []).append(str(pk))
        values = {
            str(pk): controllers.get(value, [])
            for pk, value in field.queryset.values_list(
                key, f'{path}__pk' if path != 'pk' else 'pk'
            )
        }
    else:
        # Keep the authorized dependent queryset intact while withholding IDs
        # outside the controller queryset. The subquery is part of this one
        # SQL statement, not an eager lookup or a query per option.
        authorized = Case(
            When(Q(**{f'{path}__in': controller_field.queryset.values('pk')}), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )
        values = {
            str(pk): (
                ['*']
                if value is None and generic
                else [str(value or '')]
                if allowed or value is None
                else []
            )
            for pk, value, allowed in field.queryset.values_list(
                key, f'{path}__{target_key}', authorized
            )
        }
    if allow_empty:
        values = {pk: [*allowed, ''] for pk, allowed in values.items()}
    return values


def _serialize_rules(rules):
    return json.dumps(
        [{'controller': rule['controller'], 'values': dict(rule['values'])} for rule in rules],
        separators=(',', ':'),
    )


def configure_inline_parent_fields(form, parent_form):
    """Bind explicit paths after Django injects its authoritative parent FK."""
    from django.forms.models import InlineForeignKeyField

    if parent_form is None:
        return
    label = form._meta.model._meta.label_lower
    specs = list(MODEL_DEPENDENCIES.get(label, ()))
    if label == 'procurement.purchasereceiptitem':
        specs.append(('order_item', 'receipt__order', 'order', False))
    for name, expression, path, generic in specs:
        parent_name, _, parent_path = expression.partition('__')
        injected = form.fields.get(parent_name)
        if not isinstance(injected, InlineForeignKeyField):
            continue
        if (
            injected.parent_instance._meta.model is not parent_form.instance._meta.model
            or injected.parent_instance.pk != parent_form.instance.pk
        ):
            continue
        field = form.fields.get(name)
        if not _choice(field) or not _visible(field) or field.disabled:
            continue
        if not parent_path:
            values = SimpleLazyObject(
                partial(_inline_identity_values, field, path, generic, parent_form)
            )
            rule = _add_rule(
                form, name, parent_name, values, path=path, controller_form=parent_form
            )
            # The hidden field is only a frontend locator. Server validation
            # takes identity from the authoritative parent, never posted data.
            rule['controller'] = form.add_prefix(parent_name)
            rule['controller_instance'] = parent_form.instance
            continue
        controller_name, _, controller_path = parent_path.partition('__')
        controller = parent_form.fields.get(controller_name)
        if not _choice(controller) or not _visible(controller):
            continue
        if path != 'pk':
            field.queryset = field.queryset.select_related(path)
        values = SimpleLazyObject(
            partial(_relation_values, field, controller, path, generic, controller_path)
        )
        _add_rule(
            form,
            name,
            controller_name,
            values,
            path=path,
            controller_form=parent_form,
            controller_path=controller_path,
        )


def _inline_identity_values(field, path, generic, parent_form):
    key = field.to_field_name or field.queryset.model._meta.pk.name
    parent_pk = parent_form.instance.pk
    return {
        str(pk): ['*']
        if value is None and generic
        else [str(parent_pk or '')]
        if value == parent_pk
        else []
        for pk, value in field.queryset.values_list(key, f'{path}__pk' if path != 'pk' else 'pk')
    }


def _add_rule(form, name, controller, values, *, path, controller_form=None, controller_path=''):
    rules = form._related_field_rules.setdefault(name, [])
    source = controller_form if controller_form is not None else form
    rule = {
        'controller': source.add_prefix(controller),
        'field': controller,
        'values': values,
        'path': path,
        'controller_path': controller_path,
    }
    if controller_form is not None:
        rule['controller_form'] = controller_form
    rules.append(rule)
    form.fields[name].widget.attrs['data-related-rules'] = lazy(_serialize_rules, str)(rules)
    return rule


def validate_related_fields(form, cleaned_data):
    """Call from clean() AFTER super().clean(); errors stay on the dependent FK.

    Metadata values are loaded lazily once per rule (render or validation),
    never trusted from the browser. ModelChoiceField enforces authorization.
    Disabled fields and deleted formset rows are untouched.
    """
    if cleaned_data.get('DELETE'):
        return cleaned_data
    for name, rules in getattr(form, '_related_field_rules', {}).items():
        value = cleaned_data.get(name)
        if value is None or form.fields[name].disabled:
            continue
        field = form.fields[name]
        selected = str(getattr(value, field.to_field_name or value._meta.pk.attname))
        for rule in rules:
            controller_name = rule['field']
            source = rule.get('controller_form', form)
            source_data = cleaned_data if source is form else getattr(source, 'cleaned_data', {})
            if 'controller_instance' in rule:
                controller = rule['controller_instance'].pk
            else:
                if controller_name not in source_data:
                    continue
                controller = source_data[controller_name]
                controller_field = source.fields[controller_name]
                if _choice(controller_field) and controller is not None:
                    controller = getattr(
                        controller, controller_field.to_field_name or controller._meta.pk.attname
                    )
            controller = str(controller or '')
            allowed = rule['values'].get(selected, [])
            if '*' not in allowed and controller not in allowed:
                form.add_error(name, 'A seleção é incompatível com o campo relacionado.')
                if isinstance(form, forms.ModelForm):
                    # Keep the already-authorized object available to construct_instance
                    # and Model.clean; many domain models dereference required FKs.
                    # The field error still prevents is_valid/save; no guard is skipped.
                    cleaned_data[name] = value
                break
    return cleaned_data
