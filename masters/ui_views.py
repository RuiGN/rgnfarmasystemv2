"""Product editor composed from the existing authorized resource workflow."""

from dataclasses import replace
from typing import TYPE_CHECKING, TypeAlias

from django import forms
from django.contrib import messages
from django.core.exceptions import NON_FIELD_ERRORS, PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from base.ui.registry import get_module, get_resource
from base.ui.views import (
    ResourceCreateView,
    ResourceUpdateView,
    _add_validation_error_to_form,
    _annotate_form_accessibility,
    _build_authorized_resource_form,
)
from formulations.models import MasterFormula
from formulations.writers import write_gate
from masters.related_create import RELATED_ACTIONS, related_context, save_related


if TYPE_CHECKING:
    IntegratedFormBase: TypeAlias = forms.ModelForm


class FormulaEditor(ResourceCreateView):
    """Reuse inline authorization, actor attribution and generic audit writes."""

    def prepare_object_for_save(self, obj, *, action):
        obj = super().prepare_object_for_save(obj, action=action)
        obj.full_clean()
        return obj

    def get_inline_formsets(self, **kwargs):
        inlines = super().get_inline_formsets(**kwargs)
        for inline in inlines:
            formset = inline['formset']
            if formset is not None:
                for form in formset.forms:
                    # Django's default hidden identity field can accept a row
                    # outside this parent even when it will not update that row.
                    form.fields[formset.model._meta.pk.name].queryset = formset.get_queryset()
        return inlines


def integrated_formula_form(resource, *, update):
    if not TYPE_CHECKING:
        IntegratedFormBase = _build_authorized_resource_form(resource, update=update)

    class IntegratedFormulaForm(IntegratedFormBase):
        def _update_errors(self, errors):
            if hasattr(errors, 'error_dict'):
                normalized = {}
                for name, values in errors.error_dict.items():
                    normalized.setdefault(
                        name if name in self.fields else NON_FIELD_ERRORS, []
                    ).extend(values)
                errors = ValidationError(normalized)
            super()._update_errors(errors)

    return IntegratedFormulaForm


class ProductWorkflowMixin(ResourceCreateView):
    def formula_editor(self):
        editor = FormulaEditor()
        editor.request = self.request
        editor.kwargs = {'module_slug': 'formulations', 'resource_slug': 'formulas'}
        editor.module = get_module('formulations')
        editor.resource = get_resource('formulations', 'formulas')
        return editor

    def build_workflow(self, form, *, data=None, selection='none', load=False):
        editor = self.formula_editor()
        can_view = editor.resource.can_view(self.request.user)
        if selection != 'none' and not can_view:
            raise PermissionDenied('Usuário sem permissão para visualizar fórmulas.')
        versions = MasterFormula.objects.none()
        if can_view and form.instance.pk:
            versions = editor.resource.get_queryset(self.request).filter(product=form.instance)
        formula = None
        if selection not in ('none', 'new'):
            if not selection.isdecimal():
                raise Http404('Versão inválida.')
            try:
                queryset = (
                    versions.select_for_update() if self.request.method == 'POST' else versions
                )
                formula = queryset.get(pk=selection)
            except MasterFormula.DoesNotExist as exc:
                raise Http404('Versão não pertence a este produto.') from exc
        formula_form = None
        inlines = []
        if selection != 'none':
            formula = formula or MasterFormula(product=form.instance)
            formula.product = form.instance
            fields = editor.resource.update_form_fields
            config = replace(
                editor.resource,
                form_fields=tuple(name for name in fields if name != 'product'),
                update_form_fields=None,
            )
            form_class = integrated_formula_form(config, update=bool(formula.pk))
            formula_form = form_class(
                data if not load else None, instance=formula, request=self.request, prefix='formula'
            )
            if formula.pk:
                formula_form.fields['version'].disabled = True
                formula_form.fields[
                    'version'
                ].help_text = 'Versão preservada; use Nova versão para criar outra.'
            inlines = editor.get_inline_formsets(data=data if not load else None, instance=formula)
        return {
            'editor': editor,
            'formula_form': formula_form,
            'inlines': inlines,
            'versions': versions,
            'selection': selection,
            'can_view': can_view,
        }

    def get_context_data(self, **kwargs):
        workflow = kwargs.pop('workflow', None)
        related = kwargs.pop('related', None)
        context = super().get_context_data(**kwargs)
        form = context['form']
        workflow = workflow or self.build_workflow(
            form, selection=self.request.GET.get('formula_version', 'none')
        )
        formula_form = workflow['formula_form']
        tabs = [
            {
                'key': 'product',
                'label': 'Produto',
                'fields': list(form.visible_fields()),
                'inline': None,
                'has_errors': bool(form.errors),
            },
            {
                'key': 'formula',
                'label': 'Fórmula mestra',
                'fields': list(formula_form.visible_fields()) if formula_form else [],
                'inline': None,
                'has_errors': bool(formula_form.errors) if formula_form else False,
            },
            {
                'key': 'inline-components',
                'label': 'Componentes',
                'fields': [],
                'inline': workflow['inlines'][0] if workflow['inlines'] else None,
                'has_errors': False,
            },
        ]
        if workflow['inlines']:
            item = workflow['inlines'][0]
            if item['formset'] is not None:
                tabs[-1]['has_errors'] = bool(
                    any(item['formset'].errors) or item['formset'].non_form_errors()
                )
        active = next((tab['key'] for tab in tabs if tab['has_errors']), 'product')
        if self.request.POST.get('workflow_action') == 'load_formula' and not any(
            tab['has_errors'] for tab in tabs
        ):
            active = 'formula'
        if self.request.POST.get('workflow_action') in RELATED_ACTIONS:
            active = 'inline-components'
        for tab in tabs:
            tab['active'] = tab['key'] == active
        context.update(
            product_workflow=True,
            formula_form=formula_form,
            formula_versions=workflow['versions'],
            formula_selection=workflow['selection'],
            can_view_formulas=workflow['can_view'],
            can_add_formula=workflow['editor'].resource.can_add(self.request.user),
            form_tabs=tabs,
            active_form_tab=active,
        )
        context.update(related if related is not None else related_context(self.request))
        return context

    def post(self, request, *args, **kwargs):
        with write_gate():
            obj = None
            if 'pk' in self.kwargs:
                obj = get_object_or_404(
                    self.get_queryset().select_for_update(), pk=self.kwargs['pk']
                )
            form = self.get_form_class()(request.POST, instance=obj, request=request)
            selection = request.POST.get('loaded_formula_selection', 'none')
            load = request.POST.get('workflow_action') == 'load_formula'
            if load:
                selection = request.POST.get('formula_selection', 'none')
            workflow = self.build_workflow(form, data=request.POST, selection=selection, load=load)
            if request.POST.get('workflow_action') in RELATED_ACTIONS:
                related = related_context(request)
                save_related(request, related)
                return self.render_to_response(
                    self.get_context_data(form=form, workflow=workflow, related=related)
                )
            if load:
                return self.render_to_response(self.get_context_data(form=form, workflow=workflow))
            valid = form.is_valid()
            if request.POST.get('formula_selection', 'none') != selection:
                form.add_error(None, 'Carregue a versão selecionada antes de salvar.')
                valid = False
            formula_form = workflow['formula_form']
            editor = workflow['editor']
            inlines = workflow['inlines']
            if formula_form is None:
                if any(key.startswith(('formula-', 'components-')) for key in request.POST):
                    raise PermissionDenied(
                        'Selecione e carregue uma fórmula antes de enviar seus dados.'
                    )
            else:
                allowed = (
                    editor.resource.can_change(request.user)
                    if formula_form.instance.pk
                    else editor.resource.can_add(request.user)
                )
                if not allowed:
                    raise PermissionDenied('Usuário sem permissão para salvar esta fórmula.')
                valid = formula_form.is_valid() and valid
                for inline in inlines:
                    if not inline['available'] and inline['submitted']:
                        raise PermissionDenied('Usuário sem permissão para componentes.')
                    if inline['available']:
                        valid = inline['formset'].is_valid() and valid
                if valid:
                    editor.validate_inline_formset_permissions(inlines)
            if valid:
                target_form = form
                try:
                    with transaction.atomic():
                        product = self.save_object_and_inline_formsets(
                            form, [], action='updated' if obj else 'created'
                        )
                        if formula_form:
                            target_form = formula_form
                            formula_form.instance.product = product
                            editor.save_object_and_inline_formsets(
                                formula_form,
                                inlines,
                                action='updated' if formula_form.instance.pk else 'created',
                            )
                except ValidationError as exc:
                    _add_validation_error_to_form(target_form, exc)
                except IntegrityError:
                    target_form.add_error(
                        None,
                        'Conflito de gravação. Confira a versão e os identificadores antes de tentar novamente.',
                    )
                else:
                    messages.success(request, 'Produto e fórmula selecionada salvos.')
                    return redirect(
                        reverse(
                            'app:resource_detail',
                            kwargs={
                                'module_slug': 'masters',
                                'resource_slug': 'products',
                                'pk': product.pk,
                            },
                        )
                    )
            _annotate_form_accessibility(form)
            if formula_form:
                _annotate_form_accessibility(formula_form)
                editor.annotate_inline_formsets(inlines)
            return self.render_to_response(self.get_context_data(form=form, workflow=workflow))


class ProductCreateView(ProductWorkflowMixin):
    pass


class ProductUpdateView(ProductWorkflowMixin, ResourceUpdateView):
    pass
