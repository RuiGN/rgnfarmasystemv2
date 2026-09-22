from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from capa.models import CapaAction, CapaRecord
from deviations.models import (
    DeviationApproval,
    DeviationImpactAssessment,
    DeviationInvestigation,
    QualityEvent,
)


class QualityEventCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de gestão de não-conformidade, investigação e CAPA (Quality Event 360°)."""

    template_name = 'app/quality_event_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not QualityEvent:
            raise Http404('Cockpit disponível apenas para eventos de qualidade.')
        if not request.user.has_perm('deviations.view_qualityevent'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit do evento de qualidade.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        event = self.get_object()
        user = self.request.user
        resource = self.get_resource()

        # Segregação de Deveres (SoD) por aba
        can_view_evidence = user.has_perm('deviations.view_deviationevidence')
        can_view_investigation = user.has_perm('deviations.view_deviationinvestigation')
        can_view_impact = user.has_perm('deviations.view_deviationimpactassessment')
        can_view_capa = user.has_perm('capa.view_caparecord')
        can_view_capa_actions = user.has_perm('capa.view_capaaction')
        can_view_approvals = user.has_perm('deviations.view_deviationapproval')
        can_view_effectiveness = user.has_perm('capa.view_effectivenesscheck')
        can_manage_event = user.has_perm('deviations.change_qualityevent')

        available_event_actions = available_actions(self.request, resource, event)

        # Aba 1: Notificação, Triagem & Contenção Imediata
        evidences = []
        if can_view_evidence:
            evidences = list(event.evidences.select_related('uploaded_by').order_by('title'))

        links = list(
            event.links.select_related(
                'customer_complaint', 'quality_result', 'stock_lot', 'controlled_document'
            ).order_by('created_at')
        )

        # Aba 2: Investigação & Causa Raiz
        investigations = []
        main_investigation = None
        if can_view_investigation:
            investigations = list(
                event.investigations.select_related('investigator', 'concluded_by').order_by(
                    '-created_at'
                )
            )
            main_investigation = investigations[0] if investigations else None

        # Aba 3: Avaliação de Impacto Regulatório
        impact = None
        impact_axes = []
        if can_view_impact:
            try:
                impact = event.impact_assessment
            except DeviationImpactAssessment.DoesNotExist:
                impact = None

            if impact:
                impact_axes = [
                    {
                        'label': 'Qualidade do produto',
                        'impacts': impact.impacts_quality,
                        'icon': 'feather-award',
                    },
                    {
                        'label': 'Segurança sanitária',
                        'impacts': impact.impacts_safety,
                        'icon': 'feather-shield',
                    },
                    {
                        'label': 'Eficácia cosmética',
                        'impacts': impact.impacts_efficacy,
                        'icon': 'feather-zap',
                    },
                    {
                        'label': 'Assuntos regulatórios / ANVISA',
                        'impacts': impact.impacts_regulatory,
                        'icon': 'feather-file-text',
                    },
                    {
                        'label': 'Consumidor / Paciente',
                        'impacts': impact.impacts_patient,
                        'icon': 'feather-user',
                    },
                    {
                        'label': 'Estoque e quarentena',
                        'impacts': impact.impacts_inventory,
                        'icon': 'feather-box',
                    },
                    {
                        'label': 'Custos e perdas',
                        'impacts': impact.impacts_cost,
                        'icon': 'feather-dollar-sign',
                    },
                    {
                        'label': 'Prazo operacional',
                        'impacts': impact.impacts_deadline,
                        'icon': 'feather-calendar',
                    },
                ]

        # Aba 4: Planos de Ação Corretiva e Preventiva (CAPA)
        capas = []
        all_capa_actions = []
        capa_summary = {
            'total_capas': 0,
            'total_actions': 0,
            'completed_actions': 0,
            'pending_actions': 0,
            'completion_percentage': 0,
        }
        if can_view_capa:
            capas = list(
                event.capa_records.select_related('owner', 'opened_by', 'closed_by')
                .prefetch_related(
                    'actions__responsible',
                    'effectiveness_checks__verified_by',
                )
                .order_by('-created_at')
            )
            capa_summary['total_capas'] = len(capas)
            for c in capas:
                if can_view_capa_actions:
                    all_capa_actions.extend(list(c.actions.all()))

            capa_summary['total_actions'] = len(all_capa_actions)
            capa_summary['completed_actions'] = sum(
                1 for a in all_capa_actions if a.status == CapaAction.Status.COMPLETED
            )
            capa_summary['pending_actions'] = (
                capa_summary['total_actions'] - capa_summary['completed_actions']
            )
            if capa_summary['total_actions'] > 0:
                capa_summary['completion_percentage'] = int(
                    (capa_summary['completed_actions'] / capa_summary['total_actions']) * 100
                )
            else:
                capa_summary['completion_percentage'] = 100 if capas else 0

        # Aba 5: Aprovações Multidisciplinares, Eficácia & Fechamento
        approvals = []
        pending_required_approvals = []
        if can_view_approvals:
            approvals = list(
                event.approvals.select_related('approver', 'decided_by').order_by(
                    'role', 'approver__email'
                )
            )
            pending_required_approvals = [
                a
                for a in approvals
                if a.required and a.decision != DeviationApproval.Decision.APPROVED
            ]

        all_effectiveness_checks = []
        if can_view_effectiveness and capas:
            for c in capas:
                all_effectiveness_checks.extend(list(c.effectiveness_checks.all()))

        # Critérios para Encerramento da Não Conformidade
        has_concluded_investigation = bool(
            main_investigation
            and main_investigation.status == DeviationInvestigation.Status.CONCLUDED
        )
        has_completed_impact = bool(impact and impact.is_completed)
        has_approved_approvals = bool(approvals and len(pending_required_approvals) == 0)
        has_completed_capas = bool(
            not capas or (all_capa_actions and capa_summary['pending_actions'] == 0)
        )

        closure_checklist = [
            {
                'title': 'Investigação Concluída com Causa Raiz',
                'passed': has_concluded_investigation,
                'detail': (
                    'Investigação concluída'
                    if has_concluded_investigation
                    else 'Investigação pendente de conclusão'
                ),
                'icon': 'feather-search',
            },
            {
                'title': 'Avaliação de Impacto Regulatório Concluída',
                'passed': has_completed_impact,
                'detail': (
                    'Impacto avaliado e formalizado'
                    if has_completed_impact
                    else 'Avaliação de impacto pendente'
                ),
                'icon': 'feather-activity',
            },
            {
                'title': 'Aprovações Multidisciplinares Obrigatórias',
                'passed': has_approved_approvals,
                'detail': (
                    'Todas as aprovações obrigatórias obtidas'
                    if has_approved_approvals
                    else f'{len(pending_required_approvals)} aprovação(ões) pendente(s)'
                ),
                'icon': 'feather-user-check',
            },
            {
                'title': 'Ações CAPA Concluídas',
                'passed': has_completed_capas,
                'detail': (
                    'Sem ações CAPA pendentes'
                    if has_completed_capas
                    else f"{capa_summary['pending_actions']} ação(ões) pendente(s)"
                ),
                'icon': 'feather-check-circle',
            },
        ]
        all_closure_criteria_met = all(c['passed'] for c in closure_checklist)

        context.update(
            {
                'event': event,
                'product': event.product,
                'lot': event.stock_lot,
                'available_event_actions': available_event_actions,
                # Permissões SoD
                'can_view_evidence': can_view_evidence,
                'can_view_investigation': can_view_investigation,
                'can_view_impact': can_view_impact,
                'can_view_capa': can_view_capa,
                'can_view_capa_actions': can_view_capa_actions,
                'can_view_approvals': can_view_approvals,
                'can_view_effectiveness': can_view_effectiveness,
                'can_manage_event': can_manage_event,
                # Aba 1
                'evidences': evidences,
                'links': links,
                # Aba 2
                'investigations': investigations,
                'main_investigation': main_investigation,
                # Aba 3
                'impact': impact,
                'impact_axes': impact_axes,
                # Aba 4
                'capas': capas,
                'all_capa_actions': all_capa_actions,
                'capa_summary': capa_summary,
                # Aba 5
                'approvals': approvals,
                'pending_required_approvals': pending_required_approvals,
                'all_effectiveness_checks': all_effectiveness_checks,
                'closure_checklist': closure_checklist,
                'all_closure_criteria_met': all_closure_criteria_met,
            }
        )
        return context
