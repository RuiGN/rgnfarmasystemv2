import csv
import re
from datetime import timedelta
from decimal import Decimal
from typing import Any

import httpx
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import (
    NON_FIELD_ERRORS,
    FieldDoesNotExist,
    PermissionDenied,
    ValidationError,
)
from django.db import IntegrityError, models, transaction
from django.core.paginator import Paginator
from django.db.models import Q
from django.forms import inlineformset_factory
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.utils.dateparse import parse_date, parse_datetime
from django.utils import timezone
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from auxiliary.models import City, StateProvince
from base.ui.actions.context import available_actions
from base.ui.audit import get_audit_entries
from base.ui.forms import _apply_widget_metadata, build_resource_form
from base.ui.personal_area import build_personal_area
from base.ui.presentation import ProgressMetric, build_detail_summary, resolve_status
from base.ui.registry import get_module, get_visible_modules, get_resource
from base.ui.search import search_visible_resources
from base.ui.workspaces import get_workspace
from base.templatetags.ui_query import build_query_string
from costing.models import ProductionCostCapture
from documents.models import ControlledDocument, DocumentAuditTrail
from governance.models import GovernanceAuditLog
from inventory.models import StockLot, StockLotGenealogy, StockMovement
from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)
from quality.models import LaboratoryInvestigation, QualityAnalysis, QualitySample
from finance.models import FinancialTitle
from reports.forms import (
    InvalidReportFilterSchema,
    ReportRunForm,
    annotate_report_form_accessibility,
)
from reports.models import ReportDefinition
from reports.services import run_report_definition


def _build_inline_form_class(inline):
    class InlineResourceForm(forms.ModelForm):
        def __init__(self, *args, request=None, **kwargs):
            super().__init__(*args, **kwargs)

            for name, field in self.fields.items():
                _apply_widget_metadata(name, field)
                if name in inline.read_only_fields:
                    field.disabled = True

            if (
                self.instance.pk
                and inline.is_instance_mutable is not None
                and not inline.is_instance_mutable(self.instance)
            ):
                for field in self.fields.values():
                    field.disabled = True

            # This value is intentionally never client-editable.  Disabled
            # terminal rows must remain untouched, while bound rows that truly
            # changed receive the actor before ModelForm._post_clean() invokes
            # model.full_clean().
            if (
                inline.actor_field
                and request is not None
                and self.is_bound
                and self.has_changed()
                and (
                    self.instance.pk is None
                    or inline.is_instance_mutable is None
                    or inline.is_instance_mutable(self.instance)
                )
            ):
                setattr(self.instance, inline.actor_field, request.user)

        def _update_errors(self, errors):
            """Keep validation of server-controlled fields on the form safely.

            Django's ModelForm cannot attach an error to a field deliberately
            omitted from the UI.  Normalise those errors into non-field errors
            instead of allowing a ValueError to escape as an HTTP 500.
            """
            if hasattr(errors, 'error_dict'):
                normalized_errors = {}
                for field_name, error_list in errors.error_dict.items():
                    target = field_name if field_name in self.fields else NON_FIELD_ERRORS
                    normalized_errors.setdefault(target, []).extend(error_list)
                errors = ValidationError(normalized_errors)
            super()._update_errors(errors)

        def _post_clean(self):
            # An immutable persisted child is rendered as disabled controls.
            # Do not round-trip its dates/derived values through ModelForm's
            # coercion merely because the parent form is being submitted.
            if (
                self.instance.pk
                and inline.is_instance_mutable is not None
                and not inline.is_instance_mutable(self.instance)
                and not self.has_changed()
            ):
                return
            super()._post_clean()

        class Meta:
            model = inline.child_model
            fields = inline.fields

    return InlineResourceForm


def _build_inline_formset(
    request,
    resource,
    inline,
    *,
    data=None,
    instance=None,
    allow_add=True,
    initial=None,
):
    formset_class = inlineformset_factory(
        resource.model,
        inline.child_model,
        fk_name=inline.parent_field,
        form=_build_inline_form_class(inline),
        fields=inline.fields,
        extra=(
            max(inline.extra, len(initial or ()))
            if allow_add and inline.can_add(request.user)
            else 0
        ),
        can_delete=inline.can_delete(request.user),
        max_num=None if allow_add else 0,
        validate_max=not allow_add,
    )
    return formset_class(
        data=data,
        instance=instance,
        prefix=inline.key,
        form_kwargs={'request': request},
        initial=initial,
    )


class _InlineRevalidationError(ValidationError):
    """Carries the locked inline that became invalid during persistence."""

    def __init__(self, inline, form, error):
        super().__init__(error)
        self.inline = inline
        self.form = form
        self.error = error


class _OrderRevalidationError(ValidationError):
    """Carries a locked parent validation error back to its main form."""

    def __init__(self, form, error):
        super().__init__(error)
        self.form = form
        self.error = error


def _add_validation_error_to_form(form, error):
    """Attach model errors to visible fields or the form-level error bucket."""
    if hasattr(error, 'error_dict'):
        for field_name, error_list in error.error_dict.items():
            form.add_error(field_name if field_name in form.fields else None, error_list)
        return
    form.add_error(None, error)


def _annotate_formset_accessibility(formset):
    for form in formset.forms:
        _annotate_form_accessibility(form)


def _status_tone(value):
    """Compatibilidade temporária para consumidores que precisam apenas do tom."""
    return resolve_status(value).tone


def _object_value(obj, field_name):
    parts = field_name.split('__')
    value = obj
    for part in parts:
        value = getattr(value, part, None)
        if value is None:
            return '-'
    if len(parts) == 1:
        display_method = getattr(obj, f'get_{parts[0]}_display', None)
        if display_method:
            value = display_method()
    if isinstance(value, bool):
        return 'Sim' if value else 'Não'
    if value == '':
        return '-'
    return value


def _is_status_field(field_name):
    return field_name.split('__')[-1] in {'status', 'criticality', 'severity'}


def _field_label(model, field_name):
    field_root = field_name.split('__')[0]
    try:
        return model._meta.get_field(field_root).verbose_name
    except Exception:
        return field_root.replace('_', ' ')


def _parse_filter_value(parser, value):
    if not value:
        return None
    try:
        return parser(value)
    except ValueError:
        return None


def build_advanced_filters(resource, params):
    """Build safe controls and ORM lookups exclusively from configured model fields."""
    definitions = []
    for field_name in resource.advanced_filter_fields:
        try:
            model_field = resource.model._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue

        label = str(model_field.verbose_name).capitalize()
        choices = tuple(
            (str(value), choice_label) for value, choice_label in model_field.flatchoices
        )
        if choices:
            raw_value = params.get(field_name, '').strip()
            allowed_values = {value for value, _label in choices}
            is_invalid = bool(raw_value and raw_value not in allowed_values)
            definitions.append(
                {
                    'name': field_name,
                    'label': label,
                    'kind': 'choice',
                    'value': raw_value,
                    'choices': choices,
                    'query_filters': (
                        ((field_name, raw_value),) if raw_value in allowed_values else ()
                    ),
                    'active_count': int(raw_value in allowed_values),
                    'is_invalid': is_invalid,
                    'has_submitted_value': bool(raw_value),
                }
            )
            continue

        if isinstance(model_field, models.DateTimeField):
            kind = 'datetime'
            input_type = 'datetime-local'
            parser = parse_datetime
        elif isinstance(model_field, models.DateField):
            kind = 'date'
            input_type = 'date'
            parser = parse_date
        else:
            continue

        from_name = f'{field_name}_from'
        to_name = f'{field_name}_to'
        from_value = params.get(from_name, '').strip()
        to_value = params.get(to_name, '').strip()
        parsed_from = _parse_filter_value(parser, from_value)
        parsed_to = _parse_filter_value(parser, to_value)
        from_invalid = bool(from_value and parsed_from is None)
        to_invalid = bool(to_value and parsed_to is None)
        query_filters = []
        if parsed_from is not None:
            query_filters.append((f'{field_name}__gte', parsed_from))
        if parsed_to is not None:
            query_filters.append((f'{field_name}__lte', parsed_to))
        definitions.append(
            {
                'name': field_name,
                'label': label,
                'kind': kind,
                'input_type': input_type,
                'from_name': from_name,
                'to_name': to_name,
                'from_value': from_value,
                'to_value': to_value,
                'from_invalid': from_invalid,
                'to_invalid': to_invalid,
                'query_filters': tuple(query_filters),
                'active_count': int(bool(query_filters)),
                'has_submitted_value': bool(from_value or to_value),
            }
        )
    return tuple(definitions)


def _annotate_form_accessibility(form):
    for name, field in form.fields.items():
        bound_field = form[name]
        described_by = []
        if form.errors.get(name):
            field.widget.attrs['aria-invalid'] = 'true'
            described_by.append(f'{bound_field.id_for_label}_errors')
        if field.help_text:
            described_by.append(f'{bound_field.id_for_label}_help')
        if described_by:
            field.widget.attrs['aria-describedby'] = ' '.join(described_by)


class ModuleContextMixin:
    kwargs: dict[str, Any]
    module = None

    def get_module(self):
        if self.module is None:
            self.module = get_module(self.kwargs['module_slug'])
        if self.module is None:
            raise Http404('Módulo não encontrado.')
        return self.module


class ResourceContextMixin(ModuleContextMixin):
    request: Any
    resource = None

    def get_resource(self):
        if self.resource is None:
            self.resource = get_resource(self.kwargs['module_slug'], self.kwargs['resource_slug'])
        if self.resource is None:
            raise Http404('Recurso não encontrado.')
        return self.resource

    def get_queryset(self):
        return self.get_resource().get_queryset(self.request)

    def get_object(self):
        try:
            return self.get_queryset().get(pk=self.kwargs['pk'])
        except self.get_resource().model.DoesNotExist as exc:
            raise Http404('Registro não encontrado.') from exc

    def dispatch(self, request, *args, **kwargs):
        self.get_module()
        self.get_resource()
        if not self.get_resource().can_view(request.user):
            raise PermissionDenied('Usuário sem permissão para visualizar este recurso.')
        # Método cooperativo: a implementação concreta vem da CBV à direita no MRO.
        return super().dispatch(request, *args, **kwargs)  # type: ignore[misc]

    def get_context_data(self, **kwargs):
        # Método cooperativo: a implementação concreta vem da CBV à direita no MRO.
        context = super().get_context_data(**kwargs)  # type: ignore[misc]
        resource = self.get_resource()
        context['module'] = self.get_module()
        context['resource'] = resource
        context['can_add'] = resource.can_add(self.request.user)
        context['can_change'] = resource.can_change(self.request.user)
        context['can_delete'] = resource.can_delete(self.request.user)
        context['can_mutate'] = resource.can_mutate(self.request.user)
        context['can_reuse'] = resource.can_reuse(self.request.user)
        return context

    def ensure_can_add(self):
        if not self.get_resource().can_add(self.request.user):
            raise PermissionDenied('Usuário sem permissão para criar este recurso.')

    def ensure_can_change(self):
        if not self.get_resource().can_change(self.request.user):
            raise PermissionDenied('Usuário sem permissão para alterar este recurso.')

    def ensure_can_delete(self):
        if not self.get_resource().can_delete(self.request.user):
            raise PermissionDenied('Usuário sem permissão para excluir este recurso.')


class AppIndexView(LoginRequiredMixin, TemplateView):
    template_name = 'app/index.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['modules'] = get_visible_modules(self.request.user)
        return context


class PersonalAreaView(LoginRequiredMixin, TemplateView):
    template_name = 'app/personal_area.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['sections'] = build_personal_area(self.request)
        return context


class GlobalSearchView(LoginRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        results = search_visible_resources(request, request.GET.get('q', ''))
        return JsonResponse({'results': [result.as_dict() for result in results]})


class DashboardHubView(LoginRequiredMixin, TemplateView):
    template_name = 'dashboards/hub.html'
    dashboards = {
        'executive': {'title': 'Executivo', 'module': 'production'},
        'operations': {'title': 'Operação e PCP', 'module': 'production'},
        'inventory': {'title': 'Estoque', 'module': 'inventory'},
        'quality': {'title': 'Qualidade', 'module': 'quality'},
        'finance': {'title': 'Financeiro', 'module': 'finance'},
    }

    def get(self, request, *args, **kwargs):
        if self.kwargs['dashboard_slug'] not in self.dashboards:
            raise Http404('Dashboard não encontrado.')
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        slug = self.kwargs['dashboard_slug']
        config = self.dashboards.get(slug)
        if config is None:
            raise Http404('Dashboard não encontrado.')
        module = get_module(config['module'])
        if module is not None and not module.can_view(self.request.user):
            raise PermissionDenied('Usuário sem permissão para visualizar este dashboard.')
        dashboard_options = {
            option_slug: option
            for option_slug, option in self.dashboards.items()
            if get_module(option['module']) is None
            or get_module(option['module']).can_view(self.request.user)
        }
        dashboard_data = self._build_data(slug, self.request.user)
        chart = dashboard_data['chart']
        context.update(
            {
                'dashboard_slug': slug,
                'dashboard': config,
                'dashboard_options': dashboard_options,
                'dashboard_data': dashboard_data,
                'generated_at': timezone.localtime(),
                'chart_rows': tuple(zip(chart['labels'], chart['series'], strict=False)),
            }
        )
        return context

    def _build_data(self, slug, user):
        empty = {'labels': [], 'series': []}
        data: dict[str, Any] = {
            'kpis': [],
            'chart': empty,
            'table': [],
        }
        if slug == 'operations':
            if not user.has_perm('production.view_productionorder'):
                return data
            orders = ProductionOrder.objects.all()
            active_orders = orders.exclude(
                status__in=(
                    ProductionOrder.Status.COMPLETED,
                    ProductionOrder.Status.CANCELLED,
                    ProductionOrder.Status.CLOSED,
                )
            )
            active_orders_count = active_orders.count()
            data['kpis'] = [
                ProgressMetric(
                    'Ordens ativas',
                    active_orders_count,
                    'feather-play-circle',
                    'primary',
                    'Produção',
                    reverse('app:resource_list', args=('production', 'orders')),
                    required_permission='production.view_productionorder',
                ),
                ProgressMetric(
                    'Em execução',
                    orders.filter(status=ProductionOrder.Status.IN_PROGRESS).count(),
                    'feather-activity',
                    'success',
                    'Produção',
                    reverse('app:resource_list', args=('production', 'orders')),
                    active_orders_count,
                    required_permission='production.view_productionorder',
                ),
                ProgressMetric(
                    'Ordens liberadas',
                    orders.filter(status=ProductionOrder.Status.RELEASED).count(),
                    'feather-unlock',
                    'warning',
                    'Produção',
                    reverse('app:resource_list', args=('production', 'orders')),
                    active_orders_count,
                    required_permission='production.view_productionorder',
                ),
            ]
            data['chart'] = self._status_chart(orders, ProductionOrder.Status, 'status')
            data['table'] = list(
                orders.order_by('-created_at').values('order_number', 'batch_number', 'status')[:8]
            )
        elif slug == 'inventory':
            if not user.has_perm('inventory.view_stocklot'):
                return data
            lots = StockLot.objects.all()
            expiring = lots.filter(
                expiry_date__isnull=False,
                expiry_date__lte=timezone.localdate() + timedelta(days=90),
            ).count()
            data['kpis'] = [
                ProgressMetric(
                    'Lotes cadastrados',
                    lots.count(),
                    'feather-archive',
                    'primary',
                    'Estoque',
                    reverse('app:resource_list', args=('inventory', 'lots')),
                    required_permission='inventory.view_stocklot',
                ),
                ProgressMetric(
                    'Em quarentena',
                    lots.filter(quality_status='quarantine').count(),
                    'feather-alert-triangle',
                    'warning',
                    'Estoque',
                    reverse('app:resource_list', args=('inventory', 'lots')),
                    lots.count(),
                    required_permission='inventory.view_stocklot',
                ),
                ProgressMetric(
                    'Vencendo em 90 dias',
                    expiring,
                    'feather-clock',
                    'danger',
                    'Estoque',
                    reverse('app:resource_list', args=('inventory', 'lots')),
                    lots.count(),
                    required_permission='inventory.view_stocklot',
                ),
            ]
            data['chart'] = {
                'labels': ['Quarentena', 'Liberado', 'Reprovado'],
                'series': [
                    lots.filter(quality_status=s).count()
                    for s in ('quarantine', 'released', 'rejected')
                ],
            }
            data['table'] = list(
                lots.order_by('expiry_date').values('lot_number', 'quality_status', 'expiry_date')[
                    :8
                ]
            )
        elif slug == 'quality':
            if user.has_perm('quality.view_qualitysample'):
                samples = QualitySample.objects.all()
                pending_quality = samples.exclude(
                    status__in=(
                        QualitySample.Status.APPROVED,
                        QualitySample.Status.REJECTED,
                        QualitySample.Status.CANCELLED,
                    )
                ).count()
                data['kpis'].append(
                    ProgressMetric(
                        'Amostras pendentes',
                        pending_quality,
                        'feather-droplet',
                        'warning',
                        'Qualidade',
                        reverse('app:resource_list', args=('quality', 'samples')),
                        required_permission='quality.view_qualitysample',
                    )
                )
                data['chart'] = self._status_chart(samples, QualitySample.Status, 'status')
                data['table'] = list(
                    samples.order_by('-created_at').values(
                        'sample_number', 'sample_type', 'status'
                    )[:8]
                )
            if user.has_perm('quality.view_qualityanalysis'):
                analyses = QualityAnalysis.objects.all()
                data['kpis'].append(
                    ProgressMetric(
                        'Análises pendentes',
                        analyses.filter(status=QualityAnalysis.Status.PENDING).count(),
                        'feather-search',
                        'primary',
                        'Qualidade',
                        reverse('app:resource_list', args=('quality', 'analyses')),
                        analyses.exclude(
                            status__in=(
                                QualityAnalysis.Status.APPROVED,
                                QualityAnalysis.Status.REJECTED,
                            )
                        ).count(),
                        required_permission='quality.view_qualityanalysis',
                    )
                )
            if user.has_perm('quality.view_laboratoryinvestigation'):
                investigations = LaboratoryInvestigation.objects.all()
                data['kpis'].append(
                    ProgressMetric(
                        'Investigações abertas',
                        investigations.exclude(
                            status__in=(
                                LaboratoryInvestigation.Status.CONCLUDED,
                                LaboratoryInvestigation.Status.CANCELLED,
                            )
                        ).count(),
                        'feather-alert-circle',
                        'danger',
                        'Qualidade',
                        reverse('app:resource_list', args=('quality', 'investigations')),
                        required_permission='quality.view_laboratoryinvestigation',
                    )
                )
        elif slug == 'finance':
            if not user.has_perm('finance.view_financialtitle'):
                return data
            titles = FinancialTitle.objects.all()
            open_titles = titles.exclude(
                status__in=(FinancialTitle.Status.SETTLED, FinancialTitle.Status.CANCELLED)
            )
            data['kpis'] = [
                ProgressMetric(
                    'Títulos em aberto',
                    open_titles.count(),
                    'feather-credit-card',
                    'primary',
                    'Financeiro',
                    reverse('app:resource_list', args=('finance', 'titles')),
                    required_permission='finance.view_financialtitle',
                ),
                ProgressMetric(
                    'Títulos vencidos',
                    titles.filter(status=FinancialTitle.Status.OVERDUE).count(),
                    'feather-alert-triangle',
                    'danger',
                    'Financeiro',
                    reverse('app:resource_list', args=('finance', 'titles')),
                    open_titles.count(),
                    required_permission='finance.view_financialtitle',
                ),
                ProgressMetric(
                    'A receber',
                    float(
                        titles.filter(title_type=FinancialTitle.TitleType.RECEIVABLE)
                        .exclude(status=FinancialTitle.Status.SETTLED)
                        .aggregate(total=models.Sum('open_amount'))['total']
                        or 0
                    ),
                    'feather-arrow-down-circle',
                    'success',
                    'Financeiro',
                    reverse('app:resource_list', args=('finance', 'titles')),
                    required_permission='finance.view_financialtitle',
                ),
            ]
            data['chart'] = {
                'labels': ['A pagar', 'A receber'],
                'series': [
                    titles.filter(title_type=title_type)
                    .exclude(status=FinancialTitle.Status.SETTLED)
                    .count()
                    for title_type in (
                        FinancialTitle.TitleType.PAYABLE,
                        FinancialTitle.TitleType.RECEIVABLE,
                    )
                ],
            }
            data['table'] = list(
                titles.order_by('due_date').values(
                    'title_number', 'title_type', 'status', 'due_date'
                )[:8]
            )
        else:
            chart_labels = []
            chart_series = []
            if user.has_perm('production.view_productionorder'):
                active_orders = ProductionOrder.objects.exclude(
                    status__in=(
                        ProductionOrder.Status.COMPLETED,
                        ProductionOrder.Status.CANCELLED,
                        ProductionOrder.Status.CLOSED,
                    )
                )
                active_orders_count = active_orders.count()
                data['kpis'].append(
                    ProgressMetric(
                        'Ordens ativas',
                        active_orders_count,
                        'feather-play-circle',
                        'primary',
                        'Produção',
                        reverse('app:resource_list', args=('production', 'orders')),
                        required_permission='production.view_productionorder',
                    )
                )
                chart_labels.append('Produção')
                chart_series.append(active_orders_count)
                data['table'].append({'item': 'Ordens ativas', 'value': active_orders_count})
            if user.has_perm('inventory.view_stocklot'):
                lots_count = StockLot.objects.count()
                data['kpis'].append(
                    ProgressMetric(
                        'Lotes em estoque',
                        lots_count,
                        'feather-archive',
                        'success',
                        'Estoque',
                        reverse('app:resource_list', args=('inventory', 'lots')),
                        required_permission='inventory.view_stocklot',
                    )
                )
                chart_labels.append('Estoque')
                chart_series.append(lots_count)
                data['table'].append({'item': 'Lotes cadastrados', 'value': lots_count})
            if user.has_perm('quality.view_qualitysample'):
                pending_quality = QualitySample.objects.exclude(
                    status__in=(
                        QualitySample.Status.APPROVED,
                        QualitySample.Status.REJECTED,
                        QualitySample.Status.CANCELLED,
                    )
                ).count()
                data['kpis'].append(
                    ProgressMetric(
                        'Pendências de qualidade',
                        pending_quality,
                        'feather-check-square',
                        'warning',
                        'Qualidade',
                        reverse('app:resource_list', args=('quality', 'samples')),
                        required_permission='quality.view_qualitysample',
                    )
                )
                chart_labels.append('Qualidade')
                chart_series.append(pending_quality)
                data['table'].append({'item': 'Amostras pendentes', 'value': pending_quality})
            if user.has_perm('quality.view_laboratoryinvestigation'):
                investigations_count = LaboratoryInvestigation.objects.exclude(
                    status__in=(
                        LaboratoryInvestigation.Status.CONCLUDED,
                        LaboratoryInvestigation.Status.CANCELLED,
                    )
                ).count()
                data['kpis'].append(
                    ProgressMetric(
                        'Investigações abertas',
                        investigations_count,
                        'feather-award',
                        'danger',
                        'Qualidade',
                        reverse('app:resource_list', args=('quality', 'investigations')),
                        required_permission='quality.view_laboratoryinvestigation',
                    )
                )
                chart_labels.append('Investigações')
                chart_series.append(investigations_count)
            data['chart'] = {'labels': chart_labels, 'series': chart_series}
        return data

    @staticmethod
    def _status_chart(queryset, status_enum, field):
        values = [choice.value for choice in status_enum]
        return {
            'labels': [choice.label for choice in status_enum],
            'series': [queryset.filter(**{field: value}).count() for value in values],
        }


class WorkspaceView(LoginRequiredMixin, TemplateView):
    template_name = 'workspaces/workspace.html'
    workspace_slug = ''
    workspace = None

    def get_workspace(self):
        if self.workspace is None:
            self.workspace = get_workspace(self.workspace_slug)
        if self.workspace is None:
            raise Http404('Workspace não encontrado.')
        return self.workspace

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        workspace = self.get_workspace()
        module = get_module(workspace.module_slug)
        if module is None or not module.can_view(request.user):
            raise PermissionDenied('Usuário sem permissão para visualizar este workspace.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        workspace = self.get_workspace()
        content = workspace.build_content(self.request)
        context.update(
            {
                'workspace': workspace,
                'metrics': content.metrics,
                'quick_links': content.quick_links,
                'deadlines': workspace.build_deadlines(self.request),
            }
        )
        return context


class ModuleView(LoginRequiredMixin, ModuleContextMixin, TemplateView):
    template_name = 'app/module.html'

    def dispatch(self, request, *args, **kwargs):
        if not self.get_module().can_view(request.user):
            raise PermissionDenied('Usuário sem permissão para visualizar este módulo.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        module = self.get_module()
        context['module'] = module
        context['resources'] = module.visible_resources(self.request.user)
        context['show_report_catalog'] = module.slug == 'reports' and bool(
            _visible_report_definitions(self.request.user)
        )
        return context


def _visible_report_definitions(user):
    definitions = ReportDefinition.objects.filter(
        is_system_managed=True,
        is_active=True,
    ).order_by('module', 'code')
    return [
        definition
        for definition in definitions
        if definition.required_permission and user.has_perm(definition.required_permission)
    ]


class ReportCatalogView(LoginRequiredMixin, TemplateView):
    template_name = 'app/report_catalog.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perm('reports.view_reportdefinition'):
            raise PermissionDenied('Usuário sem permissão para consultar o catálogo.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        grouped = []
        module_labels = dict(ReportDefinition.Module.choices)
        for definition in _visible_report_definitions(self.request.user):
            if not grouped or grouped[-1]['module'] != definition.module:
                grouped.append(
                    {
                        'module': definition.module,
                        'label': module_labels[definition.module],
                        'reports': [],
                    }
                )
            grouped[-1]['reports'].append(definition)
        context.update(
            {
                'module': get_module('reports'),
                'report_groups': grouped,
                'can_run_reports': self.request.user.has_perm('reports.add_reportexecution'),
            }
        )
        return context


class ReportRunView(LoginRequiredMixin, TemplateView):
    template_name = 'app/report_run.html'
    definition = None

    def get_definition(self):
        if self.definition is None:
            try:
                self.definition = ReportDefinition.objects.get(
                    pk=self.kwargs['pk'],
                    is_system_managed=True,
                    is_active=True,
                )
            except ReportDefinition.DoesNotExist as exc:
                raise Http404('Relatório não encontrado.') from exc
        return self.definition

    def dispatch(self, request, *args, **kwargs):
        if not request.user.has_perms(
            ('reports.view_reportdefinition', 'reports.add_reportexecution')
        ):
            raise PermissionDenied('Usuário sem permissão para executar relatórios.')
        definition = self.get_definition()
        if not definition.required_permission or not request.user.has_perm(
            definition.required_permission
        ):
            raise PermissionDenied('Usuário sem permissão para este relatório.')
        return super().dispatch(request, *args, **kwargs)

    def get_form(self, data=None):
        try:
            return ReportRunForm(data=data, definition=self.get_definition())
        except InvalidReportFilterSchema as exc:
            raise Http404('Esquema de filtros indisponível.') from exc

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                'module': get_module('reports'),
                'definition': self.get_definition(),
                'form': kwargs.get('form') or self.get_form(),
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form(request.POST)
        if form.is_valid():
            try:
                execution = run_report_definition(
                    definition=self.get_definition(),
                    user=request.user,
                    filters=form.cleaned_filters,
                    export_format=form.cleaned_data['export_format'],
                )
            except ValidationError as error:
                _add_validation_error_to_form(form, error)
            else:
                return redirect('reports:execution-download', pk=execution.pk)
        annotate_report_form_accessibility(form)
        return self.render_to_response(self.get_context_data(form=form))


class ResourceListView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_list.html'
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset()
        return self._apply_filters(queryset)

    def _apply_filters(self, queryset):
        query = self.request.GET.get('q', '').strip()
        resource = self.get_resource()
        status_filter = self.request.GET.get('status', '').strip()
        active_filter = self.request.GET.get('is_active', '').strip()
        ordering = self.request.GET.get('ordering', '').strip()
        created_from = _parse_filter_value(
            parse_date, self.request.GET.get('created_from', '').strip()
        )
        created_to = _parse_filter_value(parse_date, self.request.GET.get('created_to', '').strip())
        if (
            status_filter
            and self._status_choices()
            and status_filter in {value for value, _ in self._status_choices()}
        ):
            queryset = queryset.filter(status=status_filter)
        if active_filter in {'0', '1'} and self._has_active_field():
            queryset = queryset.filter(is_active=active_filter == '1')
        if self._has_created_at_field():
            if created_from:
                queryset = queryset.filter(created_at__date__gte=created_from)
            if created_to:
                queryset = queryset.filter(created_at__date__lte=created_to)
        if ordering in self._ordering_values():
            queryset = queryset.order_by(ordering)
        for definition in self._advanced_filter_definitions():
            for lookup, value in definition['query_filters']:
                queryset = queryset.filter(**{lookup: value})
        if query and resource.search_fields:
            criteria = Q()
            for field in resource.search_fields:
                criteria |= Q(**{f'{field}__icontains': query})
            queryset = queryset.filter(criteria)
        return queryset

    def _status_choices(self):
        try:
            field = self.get_resource().model._meta.get_field('status')
        except Exception:
            return ()
        return tuple(field.choices or ())

    def _has_active_field(self):
        try:
            self.get_resource().model._meta.get_field('is_active')
        except Exception:
            return False
        return True

    def _has_created_at_field(self):
        try:
            self.get_resource().model._meta.get_field('created_at')
        except Exception:
            return False
        return True

    def _ordering_options(self):
        resource = self.get_resource()
        options = []
        for field_name in resource.list_display:
            label = _field_label(resource.model, field_name).capitalize()
            options.extend(((field_name, label), (f'-{field_name}', f'{label} (Z-A)')))
        return tuple(options)

    def _ordering_values(self):
        return {value for value, _ in self._ordering_options()}

    def _advanced_filter_definitions(self):
        if not hasattr(self, '_cached_advanced_filter_definitions'):
            self._cached_advanced_filter_definitions = build_advanced_filters(
                self.get_resource(), self.request.GET
            )
        return self._cached_advanced_filter_definitions

    def _allowed_query_params(self):
        params = [
            'q',
            'status',
            'is_active',
            'created_from',
            'created_to',
            'ordering',
            'page',
        ]
        for definition in self._advanced_filter_definitions():
            if definition['kind'] == 'choice':
                params.append(definition['name'])
            else:
                params.extend((definition['from_name'], definition['to_name']))
        return tuple(params)

    def _active_filter_count(self):
        count = 0
        status_filter = self.request.GET.get('status', '').strip()
        if status_filter in {str(value) for value, _label in self._status_choices()}:
            count += 1
        if self._has_active_field() and self.request.GET.get('is_active', '').strip() in {
            '0',
            '1',
        }:
            count += 1
        if self._has_created_at_field():
            has_created_range = any(
                _parse_filter_value(
                    parse_date,
                    self.request.GET.get(name, '').strip(),
                )
                is not None
                for name in ('created_from', 'created_to')
            )
            count += int(has_created_range)
        count += sum(
            definition['active_count'] for definition in self._advanced_filter_definitions()
        )
        return count

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.get_resource()
        queryset = self.get_queryset()
        paginator = Paginator(queryset, self.paginate_by)
        page_obj = paginator.get_page(self.request.GET.get('page'))
        context['page_obj'] = page_obj
        context['query'] = self.request.GET.get('q', '').strip()
        context['status_filter'] = self.request.GET.get('status', '').strip()
        context['status_choices'] = self._status_choices()
        context['active_filter'] = self.request.GET.get('is_active', '').strip()
        context['has_active_field'] = self._has_active_field()
        context['created_from'] = self.request.GET.get('created_from', '').strip()
        context['created_to'] = self.request.GET.get('created_to', '').strip()
        context['has_created_at_field'] = self._has_created_at_field()
        context['ordering'] = self.request.GET.get('ordering', '').strip()
        context['ordering_options'] = self._ordering_options()
        context['advanced_filters'] = self._advanced_filter_definitions()
        context['active_filter_count'] = self._active_filter_count()
        context['has_active_advanced_filters'] = any(
            definition['active_count'] for definition in context['advanced_filters']
        )
        context['has_submitted_advanced_filters'] = any(
            definition['has_submitted_value'] for definition in context['advanced_filters']
        )
        context['allowed_query_params'] = self._allowed_query_params()
        context['clear_url'] = reverse(
            'app:resource_list',
            kwargs={
                'module_slug': self.get_module().slug,
                'resource_slug': self.get_resource().slug,
            },
        )
        export_base_url = reverse(
            'app:resource_export',
            kwargs={
                'module_slug': self.get_module().slug,
                'resource_slug': self.get_resource().slug,
            },
        )
        export_query_params = tuple(key for key in context['allowed_query_params'] if key != 'page')
        query_string = build_query_string(self.request.GET, export_query_params)
        context['export_url'] = (
            f'{export_base_url}?{query_string}' if query_string else export_base_url
        )
        context['rows'] = [
            {
                'object': obj,
                'values': [_object_value(obj, field) for field in resource.list_display],
                'cells': [
                    {
                        'field': field,
                        'value': _object_value(obj, field),
                        'is_status': _is_status_field(field),
                        'status': (
                            resolve_status(_object_value(obj, field))
                            if _is_status_field(field)
                            else None
                        ),
                    }
                    for field in resource.list_display
                ],
            }
            for obj in page_obj.object_list
        ]
        context['headers'] = [
            _field_label(resource.model, field) for field in resource.list_display
        ]
        context['collection_actions'] = available_actions(self.request, resource)
        return context


class ResourceKanbanView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_kanban.html'

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'has_kanban_view', False):
            from django.http import Http404

            raise Http404('Resource does not support kanban view')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.get_resource()

        # Get all objects
        objects = self.get_queryset()

        # Determine status field and its choices
        status_field = resource.model._meta.get_field('status')
        status_choices = status_field.choices if status_field.choices else []

        columns = []
        for choice_val, choice_label in status_choices:
            column_objects = objects.filter(status=choice_val)
            columns.append(
                {
                    'key': choice_val,
                    'label': choice_label,
                    'objects': column_objects,
                    'count': column_objects.count(),
                }
            )

        context['kanban_columns'] = columns
        return context


class ResourceGanttView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_gantt.html'

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'has_gantt_view', False):
            from django.http import Http404

            raise Http404('Resource does not support gantt view')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['objects'] = self.get_queryset()
        return context


class ResourceDetailView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_detail.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        resource = self.get_resource()
        obj = self.get_object()
        context['object'] = obj
        try:
            resource.model._meta.get_field('status')
        except Exception:
            raw_detail_status = ''
            context['detail_status'] = None
        else:
            raw_detail_status = _object_value(obj, 'status')
            context['detail_status'] = resolve_status(raw_detail_status)
        context['detail_summary'] = build_detail_summary(obj, raw_detail_status)
        primary_field_names = {field_name.split('__')[0] for field_name in resource.list_display}
        context['has_detail_sidebar'] = any(
            item.field_name == 'status'
            or (
                item.field_name not in primary_field_names
                and item.field_name not in {'created_at', 'updated_at'}
            )
            for item in context['detail_summary']
        )
        summary_field_names = {item.field_name for item in context['detail_summary']}
        context['fields'] = [
            (_field_label(resource.model, field), _object_value(obj, field))
            for field in resource.list_display
            if not (context['has_detail_sidebar'] and field.split('__')[0] in summary_field_names)
        ]
        context['resource_actions'] = available_actions(self.request, resource, obj)
        context['audit_entries'] = get_audit_entries(obj) if resource.audit_trail else ()
        context['can_view_production_maps'] = isinstance(
            obj, ProductionOrder
        ) and self.request.user.has_perms(
            (
                'production.view_productionorder',
                'production.view_production_maps',
            )
        )
        context['can_print_labels'] = isinstance(obj, StockLot) and self.request.user.has_perm(
            'inventory.view_stocklot'
        )
        context['can_view_formula_cockpit'] = (
            self.get_module().slug == 'formulations'
            and resource.slug == 'formulas'
            and self.request.user.has_perm('formulations.view_masterformula')
        )
        context['can_view_production_cockpit'] = (
            self.get_module().slug == 'production'
            and resource.slug == 'orders'
            and self.request.user.has_perm('production.view_productionorder')
        )
        context['can_view_lot_release_cockpit'] = (
            self.get_module().slug == 'qa'
            and resource.slug == 'lot-releases'
            and self.request.user.has_perm('qa.view_lotrelease')
        )
        context['can_view_stock_lot_dossier'] = (
            self.get_module().slug == 'inventory'
            and resource.slug == 'lots'
            and (
                self.request.user.has_perm('qa.view_lotrelease')
                or self.request.user.has_perm('inventory.view_stocklot')
            )
        )
        context['can_view_quality_event_cockpit'] = (
            self.get_module().slug == 'deviations'
            and resource.slug == 'events'
            and self.request.user.has_perm('deviations.view_qualityevent')
        )
        return context


class ProductionOrderMapMixin(LoginRequiredMixin, TemplateView):
    """Read-only, permission-segmented production batch maps."""

    template_name = 'app/production_order_map.html'
    map_kind = ''
    quantity_scale = Decimal('0.0001')
    money_scale = Decimal('0.0001')
    time_scale = Decimal('0.01')
    zero = Decimal('0.0000')

    section_permissions = {
        'materials': (MaterialConsumption, 'view'),
        'outputs': (ProductionOutput, 'view'),
        'operations': (ProductionOperationExecution, 'view'),
        'labor_entries': (ProductionLaborEntry, 'view'),
        'movements': (StockMovement, 'view'),
        'genealogy': (StockLotGenealogy, 'view'),
        'cost_captures': (ProductionCostCapture, 'view'),
        'events': (GovernanceAuditLog, 'view'),
    }

    def dispatch(self, request, *args, **kwargs):
        # Preserve LoginRequiredMixin's redirect contract for anonymous users.
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if not request.user.has_perms(
            (
                'production.view_productionorder',
                'production.view_production_maps',
            )
        ):
            raise PermissionDenied('Usuário sem permissão para visualizar esta ordem.')
        self.order = self._get_order(kwargs['pk'])
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def _get_order(pk):
        from django.shortcuts import get_object_or_404

        return get_object_or_404(
            ProductionOrder.objects.select_related(
                'product',
                'formula__product',
                'route__product',
                'responsible',
                'unit',
            ),
            pk=pk,
        )

    def can_view_section(self, section):
        model, action = self.section_permissions[section]
        return self.request.user.has_perm(
            f'{model._meta.app_label}.{action}_{model._meta.model_name}'
        )

    def get_section_records(self):
        """Return `None` for unavailable sections, never a deferred queryset."""
        records = dict.fromkeys(self.section_permissions)
        if self.can_view_section('materials'):
            records['materials'] = list(
                self.order.material_consumptions.select_related(
                    'component',
                    'material',
                    'stock_lot__product',
                    'warehouse',
                    'location__warehouse',
                    'unit',
                )
            )
        if self.can_view_section('outputs'):
            records['outputs'] = list(
                self.order.outputs.select_related(
                    'product',
                    'unit',
                    'warehouse',
                    'location__warehouse',
                    'stock_lot',
                    'received_by',
                )
            )
        if self.can_view_section('operations'):
            records['operations'] = list(
                self.order.operation_executions.select_related('route_step', 'recorded_by')
            )
        if self.can_view_section('labor_entries'):
            records['labor_entries'] = list(self.order.labor_entries.select_related('user'))
        if self.can_view_section('movements'):
            records['movements'] = list(
                StockMovement.objects.filter(source_production_order=self.order).select_related(
                    'product',
                    'lot__product',
                    'unit',
                    'from_warehouse',
                    'from_location__warehouse',
                    'to_warehouse',
                    'to_location__warehouse',
                    'created_by',
                )
            )
        if self.can_view_section('genealogy'):
            records['genealogy'] = list(
                StockLotGenealogy.objects.filter(production_order=self.order).select_related(
                    'input_lot__product', 'output_lot__product', 'unit'
                )
            )
        if self.can_view_section('cost_captures'):
            records['cost_captures'] = list(self.order.cost_captures.all())
        if self.can_view_section('events'):
            records['events'] = list(
                GovernanceAuditLog.objects.filter(
                    module='production',
                    target_model='ProductionOrder',
                    target_record_id=str(self.order.pk),
                ).select_related('user')
            )
        return records

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        records = self.get_section_records()
        context.update(order=self.order, map_kind=self.map_kind, **records)
        context['section_available'] = {
            section: records[section] is not None for section in self.section_permissions
        }
        return context


class ProductionControlMapView(ProductionOrderMapMixin):
    map_kind = 'control'


class ProductionResultsMapView(ProductionOrderMapMixin):
    map_kind = 'results'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        planned = self.order.planned_quantity or self.zero
        actual = self.order.actual_yield_quantity or self.zero
        yield_percent = (
            ((actual / planned) * Decimal('100')).quantize(self.quantity_scale)
            if planned
            else self.zero
        )
        captures = context['cost_captures']
        if captures is None:
            planned_cost = actual_cost = cost_variance = None
        else:
            planned_cost = sum((capture.planned_cost for capture in captures), self.zero).quantize(
                self.money_scale
            )
            actual_cost = sum(
                (capture.total_actual_cost for capture in captures), self.zero
            ).quantize(self.money_scale)
            cost_variance = sum(
                (capture.variance_amount for capture in captures), self.zero
            ).quantize(self.money_scale)
        operations = context['operations']
        process_minutes = (
            sum((operation.actual_minutes for operation in operations), Decimal('0.00')).quantize(
                self.time_scale
            )
            if operations is not None
            else None
        )
        labor_entries = context['labor_entries']
        labor_minutes = (
            sum((entry.duration_minutes for entry in labor_entries), Decimal('0.00')).quantize(
                self.time_scale
            )
            if labor_entries is not None
            else None
        )
        context['summary'] = {
            'yield_percent': yield_percent,
            'loss_quantity': (self.order.real_loss_quantity or self.zero).quantize(
                self.quantity_scale
            ),
            'rework_quantity': (self.order.rework_quantity or self.zero).quantize(
                self.quantity_scale
            ),
            'process_minutes': process_minutes,
            'labor_minutes': labor_minutes,
            'planned_cost': planned_cost,
            'actual_cost': actual_cost,
            'cost_variance': cost_variance,
        }
        materials = context['materials']
        context['material_variances'] = (
            [
                {
                    'material': material,
                    'planned_quantity': material.planned_quantity.quantize(self.quantity_scale),
                    'actual_quantity': material.actual_quantity.quantize(self.quantity_scale),
                    # Positive means consumption exceeded the approved plan.
                    'variance_quantity': (
                        material.actual_quantity - material.planned_quantity
                    ).quantize(self.quantity_scale),
                    'loss_quantity': material.loss_quantity.quantize(self.quantity_scale),
                    'returned_quantity': material.returned_quantity.quantize(self.quantity_scale),
                }
                for material in materials
            ]
            if materials is not None
            else None
        )
        return context


class ResourceDocumentView(ResourceDetailView):
    template_name = 'app/resource_document_viewer.html'

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'has_document_viewer', False):
            from django.http import Http404

            raise Http404('Resource does not support document viewer')
        return super().dispatch(request, *args, **kwargs)


class ResourceTreeView(ResourceDetailView):
    template_name = 'app/resource_tree.html'

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'has_tree_view', False):
            from django.http import Http404

            raise Http404('Resource does not support tree view')
        return super().dispatch(request, *args, **kwargs)


class ResourceChatView(ResourceDetailView):
    template_name = 'app/resource_chat.html'

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'has_chat_view', False):
            raise Http404('Resource does not support chat view')
        if not request.user.has_perm('knowledge.view_ragchatsession'):
            raise PermissionDenied('Usuário sem permissão para utilizar o chat RAG.')
        return super().dispatch(request, *args, **kwargs)


class ResourceCreateView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_form.html'
    uses_operational_inline_locks = False

    def dispatch(self, request, *args, **kwargs):
        self.get_module()
        self.get_resource()
        self.ensure_can_add()
        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return build_resource_form(self.get_resource())

    def get_form_initial(self):
        return {}

    def get_inline_initial(self):
        return {}

    def prepare_object_for_save(self, obj, *, action):
        del action
        actor_field = self.get_resource().actor_field
        if actor_field:
            setattr(obj, actor_field, self.request.user)
        return obj

    def handle_integrity_error(self, form, error):
        del form, error
        return False

    def get_inline_formsets(self, *, data=None, instance=None, initial_by_key=None):
        resource = self.get_resource()
        inline_formsets = []
        initial_by_key = initial_by_key or {}
        for inline in resource.inlines:
            can_view = inline.can_view(self.request.user)
            allow_add = not (
                resource.app_label == 'production'
                and resource.slug == 'orders'
                and (instance is None or instance.pk is None)
            )
            submitted = bool(data and any(key.startswith(f'{inline.key}-') for key in data))
            formset = None
            if can_view:
                formset = _build_inline_formset(
                    self.request,
                    resource,
                    inline,
                    data=data,
                    instance=instance,
                    allow_add=allow_add,
                    initial=initial_by_key.get(inline.key) if data is None else None,
                )
            inline_formsets.append(
                {
                    'config': inline,
                    'key': inline.key,
                    'title': inline.title,
                    'description': inline.description,
                    'add_label': inline.add_label,
                    'available': can_view,
                    'submitted': submitted,
                    'can_add': can_view and allow_add and inline.can_add(self.request.user),
                    'can_change': can_view and inline.can_change(self.request.user),
                    'can_delete': can_view and inline.can_delete(self.request.user),
                    'inline_style': getattr(inline, 'inline_style', 'stacked'),
                    'formset': formset,
                }
            )
        return inline_formsets

    def annotate_inline_formsets(self, inline_formsets):
        for inline in inline_formsets:
            if inline['formset'] is not None:
                _annotate_formset_accessibility(inline['formset'])

    def validate_inline_formset_permissions(self, inline_formsets):
        for inline in inline_formsets:
            config = inline['config']
            formset = inline['formset']
            if not inline['available']:
                if inline['submitted']:
                    raise PermissionDenied(
                        'Usuário sem permissão para visualizar ou alterar registros vinculados.'
                    )
                continue
            for form in formset.forms:
                if not form.has_changed():
                    continue
                if form.cleaned_data.get('DELETE'):
                    if not config.can_delete(self.request.user):
                        raise PermissionDenied(
                            'Usuário sem permissão para excluir registros vinculados.'
                        )
                    continue
                if form.instance.pk:
                    if not config.can_change(self.request.user):
                        raise PermissionDenied(
                            'Usuário sem permissão para alterar registros vinculados.'
                        )
                    continue
                if not config.can_add(self.request.user):
                    raise PermissionDenied('Usuário sem permissão para criar registros vinculados.')

    def save_object_and_inline_formsets(self, form, inline_formsets, *, action):
        from governance.models import GovernanceAuditLog

        with transaction.atomic():
            obj = form.save(commit=False)
            obj = self.prepare_object_for_save(obj, action=action)
            is_production_order_ui = (
                isinstance(obj, ProductionOrder)
                and self.get_module().slug == 'production'
                and self.get_resource().slug == 'orders'
            )
            is_existing_production_order_ui = is_production_order_ui and obj.pk is not None
            if is_existing_production_order_ui:
                # The UI shares the same order-first locking discipline as the
                # operational API.  Reapplying cleaned changes onto the locked
                # rows prevents a stale formset from overwriting a receipt or a
                # terminal process state committed while the form was open.
                locked_order = ProductionOrder.objects.select_for_update().get(pk=obj.pk)
                for field_name in form.changed_data:
                    setattr(locked_order, field_name, form.cleaned_data[field_name])
                try:
                    locked_order.full_clean()
                except ValidationError as exc:
                    raise _OrderRevalidationError(form, exc) from exc
                locked_order.save()
                obj = locked_order
            else:
                obj.save()
            form.instance = obj
            form.save_m2m()
            inline_change_counts = {}
            for inline in inline_formsets:
                config = inline['config']
                formset = inline['formset']
                if not inline['available']:
                    inline_change_counts[inline['key']] = 0
                    continue
                formset.instance = obj
                if not is_production_order_ui:
                    children = formset.save(commit=False)
                    for deleted_object in formset.deleted_objects:
                        deleted_object.delete()
                    for child in children:
                        setattr(child, config.parent_field, obj)
                        if config.actor_field and not getattr(
                            child, f'{config.actor_field}_id', None
                        ):
                            setattr(child, config.actor_field, self.request.user)
                        child.save()
                    inline_change_counts[inline['key']] = (
                        len(formset.changed_objects)
                        + len(formset.new_objects)
                        + len(formset.deleted_objects)
                    )
                    formset.save_m2m()
                    continue

                existing_ids = [
                    bound_form.instance.pk for bound_form in formset.forms if bound_form.instance.pk
                ]
                locked_children = {}
                if is_existing_production_order_ui:
                    locked_children = {
                        child.pk: child
                        for child in config.child_model.objects.select_for_update().filter(
                            pk__in=existing_ids
                        )
                    }
                changed_count = 0
                for bound_form in formset.forms:
                    if not bound_form.has_changed():
                        continue
                    if bound_form.cleaned_data.get('DELETE'):
                        raise PermissionDenied('Registros operacionais não podem ser excluídos.')

                    child = locked_children.get(bound_form.instance.pk, bound_form.instance)
                    if (
                        child.pk
                        and config.is_instance_mutable
                        and not config.is_instance_mutable(child)
                    ):
                        raise PermissionDenied(
                            'Registro operacional imutável não pode ser alterado.'
                        )
                    for field_name in bound_form.changed_data:
                        setattr(child, field_name, bound_form.cleaned_data[field_name])
                    setattr(child, config.parent_field, obj)
                    if config.actor_field:
                        setattr(child, config.actor_field, self.request.user)
                    try:
                        child.full_clean()
                    except ValidationError as exc:
                        raise _InlineRevalidationError(inline, bound_form, exc) from exc
                    child.save()
                    changed_count += 1
                inline_change_counts[inline['key']] = changed_count
                # Operational inlines intentionally have no M2M fields.  Calling
                # formset.save_m2m() here would require formset.save(commit=False)
                # and would reintroduce stale instance persistence.
            if action == 'created' and isinstance(obj, ControlledDocument):
                obj.record_audit(
                    DocumentAuditTrail.Action.CREATED,
                    user=self.request.user,
                    reason=obj.change_summary,
                )
            GovernanceAuditLog.record(
                log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
                severity=GovernanceAuditLog.Severity.INFO,
                module=obj._meta.app_label,
                action=f'ui.resource.{action}',
                target_model=obj.__class__.__name__,
                target_record_id=obj.pk,
                user=self.request.user,
                message=f'Recurso {action} pela interface operacional.',
                safe_context={
                    'changed_fields': sorted(form.changed_data),
                    'inline_resources': {
                        inline['key']: inline_change_counts[inline['key']]
                        for inline in inline_formsets
                    },
                },
                request_id=self.request.META.get('HTTP_X_REQUEST_ID', ''),
            )
        return obj

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = kwargs.get('form') or self.get_form_class()(
            request=self.request,
            initial=self.get_form_initial(),
        )
        context['form'] = form
        inline_formsets = kwargs.get('inline_formsets')
        if inline_formsets is None:
            inline_formsets = self.get_inline_formsets(
                instance=getattr(form, 'instance', None),
                initial_by_key=self.get_inline_initial(),
            )
        context['inline_formsets'] = inline_formsets
        context['has_inline_formsets'] = bool(inline_formsets)
        context['form_mode'] = 'create'
        context['cancel_url'] = reverse(
            'app:resource_list',
            kwargs={
                'module_slug': self.get_module().slug,
                'resource_slug': self.get_resource().slug,
            },
        )
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form_class()(request.POST, request=request)
        form_is_valid = form.is_valid()
        if form_is_valid:
            obj = form.save(commit=False)
        else:
            obj = getattr(form, 'instance', None)
        inline_formsets = self.get_inline_formsets(data=request.POST, instance=obj)
        inline_formsets_are_valid = all(
            not inline['available'] or inline['formset'].is_valid() for inline in inline_formsets
        )
        if not form_is_valid or not inline_formsets_are_valid:
            _annotate_form_accessibility(form)
            self.annotate_inline_formsets(inline_formsets)
            return self.render_to_response(
                self.get_context_data(form=form, inline_formsets=inline_formsets)
            )

        self.validate_inline_formset_permissions(inline_formsets)
        try:
            obj = self.save_object_and_inline_formsets(form, inline_formsets, action='created')
        except (_InlineRevalidationError, _OrderRevalidationError) as exc:
            _add_validation_error_to_form(exc.form, exc.error)
            self.annotate_inline_formsets(inline_formsets)
            return self.render_to_response(
                self.get_context_data(form=form, inline_formsets=inline_formsets)
            )
        except IntegrityError as exc:
            if not self.handle_integrity_error(form, exc):
                raise
            _annotate_form_accessibility(form)
            self.annotate_inline_formsets(inline_formsets)
            return self.render_to_response(
                self.get_context_data(form=form, inline_formsets=inline_formsets)
            )
        messages.success(request, 'Registro criado.')
        return redirect(
            reverse(
                'app:resource_detail',
                kwargs={
                    'module_slug': self.get_module().slug,
                    'resource_slug': self.get_resource().slug,
                    'pk': obj.pk,
                },
            )
        )


class ResourceExportView(ResourceListView):
    def get(self, request, *args, **kwargs):
        resource = self.get_resource()
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{resource.slug}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [_field_label(resource.model, field).capitalize() for field in resource.list_display]
        )
        for obj in self.get_queryset().iterator():
            writer.writerow([_object_value(obj, field) for field in resource.list_display])
        return response


class ResourceUpdateView(ResourceCreateView):
    def dispatch(self, request, *args, **kwargs):
        self.get_module()
        self.get_resource()
        self.ensure_can_change()
        return super(ResourceCreateView, self).dispatch(request, *args, **kwargs)

    def get_form_class(self):
        return build_resource_form(self.get_resource(), update=True)

    def get_context_data(self, **kwargs):
        obj = self.get_object()
        form = kwargs.get('form') or self.get_form_class()(instance=obj, request=self.request)
        inline_formsets = kwargs.get('inline_formsets')
        if inline_formsets is None:
            inline_formsets = self.get_inline_formsets(instance=obj)
        context = super().get_context_data(
            **{**kwargs, 'form': form, 'inline_formsets': inline_formsets}
        )
        context['object'] = obj
        context['form_mode'] = 'edit'
        context['cancel_url'] = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': self.get_module().slug,
                'resource_slug': self.get_resource().slug,
                'pk': context['object'].pk,
            },
        )
        return context

    def post(self, request, *args, **kwargs):
        obj = self.get_object()
        form = self.get_form_class()(request.POST, instance=obj, request=request)
        inline_formsets = self.get_inline_formsets(data=request.POST, instance=obj)
        form_is_valid = form.is_valid()
        inline_formsets_are_valid = all(
            not inline['available'] or inline['formset'].is_valid() for inline in inline_formsets
        )
        if not form_is_valid or not inline_formsets_are_valid:
            _annotate_form_accessibility(form)
            self.annotate_inline_formsets(inline_formsets)
            return self.render_to_response(
                self.get_context_data(form=form, inline_formsets=inline_formsets)
            )

        self.validate_inline_formset_permissions(inline_formsets)
        try:
            self.save_object_and_inline_formsets(form, inline_formsets, action='updated')
        except (_InlineRevalidationError, _OrderRevalidationError) as exc:
            _add_validation_error_to_form(exc.form, exc.error)
            self.annotate_inline_formsets(inline_formsets)
            return self.render_to_response(
                self.get_context_data(form=form, inline_formsets=inline_formsets)
            )
        messages.success(request, 'Registro atualizado.')
        return redirect(
            reverse(
                'app:resource_detail',
                kwargs={
                    'module_slug': self.get_module().slug,
                    'resource_slug': self.get_resource().slug,
                    'pk': obj.pk,
                },
            )
        )


class ResourceExecutionView(ResourceUpdateView):
    template_name = 'app/resource_execution_board.html'
    uses_operational_inline_locks = True

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if not getattr(resource, 'is_executable', False):
            from django.http import Http404

            raise Http404('Resource is not executable')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['is_execution'] = True
        context['form_mode'] = 'execute'
        context['resource_actions'] = available_actions(
            self.request, self.get_resource(), context['object']
        )
        context['active_inline_key'] = next(
            (
                inline['key']
                for inline in context['inline_formsets']
                if inline['formset'] is not None
                and (inline['formset'].errors or inline['formset'].non_form_errors())
            ),
            next(
                (inline['key'] for inline in context['inline_formsets'] if inline['available']),
                context['inline_formsets'][0]['key'] if context['inline_formsets'] else '',
            ),
        )
        return context


class ResourceDeleteView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/resource_confirm_delete.html'

    def dispatch(self, request, *args, **kwargs):
        self.get_module()
        self.get_resource()
        self.ensure_can_delete()
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['object'] = self.get_object()
        return context

    def post(self, request, *args, **kwargs):
        from governance.models import GovernanceAuditLog
        from django.db.models.deletion import ProtectedError

        obj = self.get_object()
        try:
            with transaction.atomic():
                target_model = obj.__class__.__name__
                target_record_id = obj.pk
                module = obj._meta.app_label
                obj.delete()
                GovernanceAuditLog.record(
                    log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
                    severity=GovernanceAuditLog.Severity.WARNING,
                    module=module,
                    action='ui.resource.deleted',
                    target_model=target_model,
                    target_record_id=target_record_id,
                    user=request.user,
                    message='Recurso não regulado excluído pela interface operacional.',
                    request_id=request.META.get('HTTP_X_REQUEST_ID', ''),
                )
            messages.success(request, 'Registro excluído.')
            return redirect(
                reverse(
                    'app:resource_list',
                    kwargs={
                        'module_slug': self.get_module().slug,
                        'resource_slug': self.get_resource().slug,
                    },
                )
            )
        except ProtectedError:
            messages.error(
                request,
                'Não é possível excluir este registro pois ele está em uso por outros registros.',
            )
            return redirect(
                reverse(
                    'app:resource_detail',
                    kwargs={
                        'module_slug': self.get_module().slug,
                        'resource_slug': self.get_resource().slug,
                        'pk': obj.pk,
                    },
                )
            )


VIA_CEP_TIMEOUT = 5.0
CEP_DIGITS_RE = re.compile(r'\D')


def _clean_cep(raw):
    return CEP_DIGITS_RE.sub('', raw or '').zfill(8)[:8]


class CepLookupView(LoginRequiredMixin, View):
    def get(self, request):
        cep = _clean_cep(request.GET.get('cep', ''))
        if len(cep) != 8:
            return JsonResponse({'error': 'CEP deve conter 8 dígitos.'}, status=400)

        try:
            viacep_response = httpx.get(
                f'https://viacep.com.br/ws/{cep}/json/',
                timeout=VIA_CEP_TIMEOUT,
            )
            viacep_response.raise_for_status()
            data = viacep_response.json()
        except Exception:
            return JsonResponse({'error': 'Não foi possível consultar o CEP.'}, status=502)

        if data.get('erro'):
            return JsonResponse({'error': 'CEP não encontrado.'}, status=404)

        uf = str(data.get('uf', '')).upper().strip()
        localidade = str(data.get('localidade', '')).strip()

        city_record, state_record, country_record = self._ensure_city(
            request,
            localidade,
            uf,
            str(data.get('ibge', '')).strip(),
        )

        return JsonResponse(
            {
                'logradouro': data.get('logradouro', ''),
                'bairro': data.get('bairro', ''),
                'cidade': localidade,
                'uf': uf,
                'ibge_code': data.get('ibge', ''),
                'city_id': city_record.pk if city_record else None,
                'state_id': state_record.pk if state_record else None,
                'country_id': country_record.pk if country_record else None,
            }
        )

    @staticmethod
    def _ensure_city(request, name, uf, ibge_code=''):
        if not name or not uf:
            return None, None, None

        uf_map = {
            'AC': 'Acre',
            'AL': 'Alagoas',
            'AP': 'Amapá',
            'AM': 'Amazonas',
            'BA': 'Bahia',
            'CE': 'Ceará',
            'DF': 'Distrito Federal',
            'ES': 'Espírito Santo',
            'GO': 'Goiás',
            'MA': 'Maranhão',
            'MT': 'Mato Grosso',
            'MS': 'Mato Grosso do Sul',
            'MG': 'Minas Gerais',
            'PA': 'Pará',
            'PB': 'Paraíba',
            'PR': 'Paraná',
            'PE': 'Pernambuco',
            'PI': 'Piauí',
            'RJ': 'Rio de Janeiro',
            'RN': 'Rio Grande do Norte',
            'RS': 'Rio Grande do Sul',
            'RO': 'Rondônia',
            'RR': 'Roraima',
            'SC': 'Santa Catarina',
            'SP': 'São Paulo',
            'SE': 'Sergipe',
            'TO': 'Tocantins',
        }
        state_name = uf_map.get(uf.upper(), uf)
        state = StateProvince.objects.filter(name__iexact=state_name).first()
        country = state.country if state else None

        city = City.objects.filter(ibge_code=ibge_code).first() if ibge_code else None

        if city:
            return city, state, country

        city = City.objects.filter(name__iexact=name, state=state).first()

        if city:
            if not city.state and state:
                city.state = state
                city.save(update_fields=['state'])
            return city, state, country

        city = City.objects.create(name=name, state=state)
        return city, state, country
