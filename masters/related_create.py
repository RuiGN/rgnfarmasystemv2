"""Related master creation without committing the bound principal editor."""

from dataclasses import replace

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from base.ui.registry import get_module, get_resource
from base.ui.related_fields import CATEGORY_PARENTS
from masters.models import MasterCategory, Product

RELATED_ACTIONS = {'create_material': 'material', 'create_category': 'category'}


def related_context(request):
    from base.ui.views import _build_authorized_resource_form

    context = {}
    container_allowed = request.user.has_perms(
        ('formulations.view_masterformula', 'formulations.view_formulacomponent')
    )
    for kind, slug in (('material', 'products'), ('category', 'categories')):
        resource = get_resource('masters', slug)
        if (
            not container_allowed
            or not resource.can_view(request.user)
            or not resource.can_add(request.user)
        ):
            continue
        instance = None
        if kind == 'category':
            instance = MasterCategory(kind=MasterCategory.Kind.CATEGORY)
            resource = replace(resource, form_fields=('code', 'name', 'parent', 'is_active'))
        else:
            instance = Product(item_type=Product.ItemType.RAW_MATERIAL)
            resource = replace(
                resource, form_fields=('description', 'item_type', 'unit', 'category')
            )
        form_class = _build_authorized_resource_form(resource)
        prefix = f'related-{kind}'
        active = RELATED_ACTIONS.get(request.POST.get('workflow_action')) == kind
        initial = {
            name: request.POST[f'{prefix}-{name}']
            for name in form_class.base_fields
            if f'{prefix}-{name}' in request.POST
        }
        form = form_class(
            request.POST if active else None,
            initial=initial,
            instance=instance,
            request=request,
            prefix=prefix,
        )
        # Required is still enforced by Django, not by unrelated principal saves.
        form.use_required_attribute = False
        if kind == 'material':
            form.fields['category'].queryset = form.fields['category'].queryset.filter(
                kind=MasterCategory.Kind.CATEGORY
            )
        else:
            # This quick form deliberately omits the fixed kind controller.
            # Apply the shared taxonomy's static rule to its existing queryset.
            form.fields['parent'].queryset = form.fields['parent'].queryset.filter(
                kind__in=CATEGORY_PARENTS[str(MasterCategory.Kind.CATEGORY)]
            )
        context[f'related_{kind}_form'] = form
    return context


def save_related(request, context):
    from base.ui.views import (
        ResourceCreateView,
        _add_validation_error_to_form,
        _annotate_form_accessibility,
    )

    kind = RELATED_ACTIONS[request.POST['workflow_action']]
    form = context.get(f'related_{kind}_form')
    if form is None:
        raise PermissionDenied('Usuário sem permissão para criar este cadastro relacionado.')
    if form.is_valid():
        editor = ResourceCreateView()
        editor.request = request
        editor.kwargs = {
            'module_slug': 'masters',
            'resource_slug': 'products' if kind == 'material' else 'categories',
        }
        editor.module = get_module('masters')
        editor.resource = get_resource('masters', editor.kwargs['resource_slug'])
        try:
            with transaction.atomic():
                form.instance.full_clean(exclude=['code'])
                obj = editor.save_object_and_inline_formsets(form, [], action='created')
        except ValidationError as exc:
            _add_validation_error_to_form(form, exc)
        except IntegrityError:
            form.add_error(
                None, 'Conflito de gravação no cadastro relacionado; confira os identificadores.'
            )
        else:
            messages.success(
                request, f'{obj} cadastrado. O formulário principal ainda não foi salvo.'
            )
    _annotate_form_accessibility(form)


def handle_formula_related_post(view, *, instance=None):
    """Used by the ordinary formula editor as well as its reuse subclass."""
    form = view.get_form_class()(view.request.POST, instance=instance, request=view.request)
    inlines = view.get_inline_formsets(data=view.request.POST, instance=form.instance)
    context = related_context(view.request)
    save_related(view.request, context)
    response_context = view.get_context_data(form=form, inline_formsets=inlines)
    response_context.update(context)
    for tab in response_context['form_tabs']:
        tab['active'] = tab['key'] == 'inline-components'
    response_context['active_form_tab'] = 'inline-components'
    return view.render_to_response(response_context)
