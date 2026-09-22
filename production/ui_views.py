from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import Http404
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from costing.models import ProductionCostCapture
from deviations.models import QualityEvent
from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)
from quality.models import QualitySample


class ProductionOrderCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de execução e prontuário eletrônico da ordem de produção (e-Batch Record)."""

    template_name = 'app/production_order_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if self.get_resource().model is not ProductionOrder:
            raise Http404('Cockpit disponível apenas para ordens de produção.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_object()
        user = self.request.user

        # Segregação de Deveres (SoD) por aba
        can_view_materials = user.has_perm('production.view_materialconsumption')
        can_view_operations = user.has_perm('production.view_productionoperationexecution')
        can_view_labor = user.has_perm('production.view_productionlaborentry')
        can_view_quality = user.has_perm('quality.view_qualitysample')
        can_view_deviations = user.has_perm('deviations.view_qualityevent')
        can_view_outputs = user.has_perm('production.view_productionoutput')
        can_view_costs = user.has_perm('costing.view_productioncostcapture')

        resource = self.get_resource()
        available_order_actions = available_actions(self.request, resource, order)

        # Aba 2: Separação, Pesagem & Consumo de Insumos
        materials = []
        materials_summary = {
            'planned_total': Decimal('0.0000'),
            'actual_total': Decimal('0.0000'),
            'loss_total': Decimal('0.0000'),
            'count': 0,
        }
        if can_view_materials:
            materials = list(
                order.material_consumptions.select_related(
                    'component',
                    'material',
                    'stock_lot',
                    'warehouse',
                    'location',
                    'unit',
                ).order_by('material__code')
            )
            materials_summary['count'] = len(materials)
            for mat in materials:
                materials_summary['planned_total'] += mat.planned_quantity or Decimal('0.0000')
                materials_summary['actual_total'] += mat.actual_quantity or Decimal('0.0000')
                materials_summary['loss_total'] += mat.loss_quantity or Decimal('0.0000')

        # Aba 3: Fases / Operações e Mão de Obra
        operations = []
        if can_view_operations:
            operations = list(
                order.operation_executions.select_related('route_step', 'recorded_by').order_by(
                    'sequence', 'created_at'
                )
            )

        labor_entries = []
        labor_summary = {
            'total_minutes': Decimal('0.00'),
            'total_cost': Decimal('0.0000'),
            'count': 0,
        }
        if can_view_labor:
            labor_entries = list(
                order.labor_entries.select_related('user', 'operation_execution').order_by(
                    '-started_at'
                )
            )
            labor_summary['count'] = len(labor_entries)
            for lab in labor_entries:
                minutes = lab.duration_minutes or Decimal('0.00')
                hourly_cost = lab.hourly_cost or Decimal('0.0000')
                entry_cost = (minutes / Decimal('60')) * hourly_cost
                setattr(lab, 'entry_cost', entry_cost)
                labor_summary['total_minutes'] += minutes
                labor_summary['total_cost'] += entry_cost

        # Aba 4: Controle em Processo (IPC) & Amostragens de Qualidade
        quality_samples = []
        pending_samples_count = 0
        if can_view_quality:
            quality_samples = list(
                order.quality_samples.select_related(
                    'specification',
                    'unit',
                    'collected_by',
                    'started_by',
                    'approved_by',
                )
                .prefetch_related('analyses__results')
                .order_by('-collected_at')
            )
            pending_samples_count = sum(
                1
                for s in quality_samples
                if s.status
                not in (
                    QualitySample.Status.APPROVED,
                    QualitySample.Status.REJECTED,
                    QualitySample.Status.CANCELLED,
                )
            )

        # Aba 5: Desvios & Ocorrências da Batelada
        deviations = []
        open_deviations_count = 0
        if can_view_deviations:
            deviations = list(
                QualityEvent.objects.filter(
                    models.Q(product=order.product, stock_lot__lot_number=order.batch_number)
                    | models.Q(links__reference_code=order.order_number)
                    | models.Q(product=order.product, origin=QualityEvent.Origin.PRODUCTION)
                )
                .select_related('responsible', 'opened_by')
                .distinct()
                .order_by('-opened_at')[:25]
            )
            open_deviations_count = sum(
                1
                for d in deviations
                if d.status
                in (
                    QualityEvent.Status.OPEN,
                    QualityEvent.Status.UNDER_INVESTIGATION,
                    QualityEvent.Status.PENDING_APPROVAL,
                )
            )

        # Aba 6: Rendimento, Entrada do Acabado & Apropriação de Custos
        outputs = []
        pending_outputs_count = 0
        if can_view_outputs:
            outputs = list(
                order.outputs.select_related(
                    'product',
                    'unit',
                    'warehouse',
                    'location',
                    'stock_lot',
                    'received_by',
                ).order_by('lot_number', 'sublot_number')
            )
            pending_outputs_count = sum(
                1 for out in outputs if out.status == ProductionOutput.Status.PENDING
            )

        cost_captures = []
        if can_view_costs:
            cost_captures = list(order.cost_captures.order_by('-created_at')[:10])

        # Rendimento percentual teórico vs. real
        yield_percentage = None
        if order.actual_yield_quantity and order.planned_quantity and order.planned_quantity > 0:
            yield_percentage = (order.actual_yield_quantity / order.planned_quantity) * Decimal(
                '100'
            )

        context.update(
            {
                'order': order,
                'available_order_actions': available_order_actions,
                'yield_percentage': yield_percentage,
                # Permissões SoD
                'can_view_materials': can_view_materials,
                'can_view_operations': can_view_operations,
                'can_view_labor': can_view_labor,
                'can_view_quality': can_view_quality,
                'can_view_deviations': can_view_deviations,
                'can_view_outputs': can_view_outputs,
                'can_view_costs': can_view_costs,
                # Dados das seções
                'materials': materials,
                'materials_summary': materials_summary,
                'operations': operations,
                'labor_entries': labor_entries,
                'labor_summary': labor_summary,
                'quality_samples': quality_samples,
                'pending_samples_count': pending_samples_count,
                'deviations': deviations,
                'open_deviations_count': open_deviations_count,
                'outputs': outputs,
                'pending_outputs_count': pending_outputs_count,
                'cost_captures': cost_captures,
            }
        )
        return context
