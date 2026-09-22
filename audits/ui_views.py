from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from audits.models import (
    AuditChecklistItem,
    AuditEvidence,
    AuditFinding,
    AuditFindingLink,
    AuditFollowUpAction,
    AuditPlan,
    AuditProgram,
    AuditReport,
)
from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from capa.models import CapaRecord
from deviations.models import QualityEvent


class AuditCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de Auditorias da Qualidade e Planos de Ação (Audits 360°)."""

    template_name = 'app/audit_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not AuditPlan:
            raise Http404('Cockpit disponível apenas para planos de auditoria.')
        if not request.user.has_perm('audits.view_auditplan'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit de auditoria da qualidade.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        resource = self.get_resource()

        audit = get_object_or_404(
            AuditPlan.objects.select_related(
                'program',
                'supplier',
                'lead_auditor',
                'area_ref',
                'site',
                'venue_country_ref',
                'venue_state_ref',
                'venue_city_ref',
                'submitted_by',
                'started_by',
                'completed_by',
                'closed_by',
            ),
            pk=self.kwargs['pk'],
        )

        # Segregação de Deveres (SoD) por aba
        can_view_scope = user.has_perm('audits.view_auditplan')
        can_view_checklist = user.has_perm('audits.view_auditchecklistitem')
        can_view_findings = user.has_perm('audits.view_auditfinding') or user.has_perm(
            'audits.view_auditevidence'
        )
        can_view_actions = (
            user.has_perm('audits.view_auditfollowupaction')
            or user.has_perm('audits.view_auditfindinglink')
            or user.has_perm('capa.view_caparecord')
        )
        can_view_report = user.has_perm('audits.view_auditreport')

        can_manage_audit = user.has_perm('audits.change_auditplan')
        can_manage_checklist = user.has_perm('audits.change_auditchecklistitem') or user.has_perm(
            'audits.add_auditchecklistitem'
        )
        can_manage_findings = user.has_perm('audits.change_auditfinding') or user.has_perm(
            'audits.add_auditfinding'
        )
        can_manage_actions = user.has_perm('audits.change_auditfollowupaction') or user.has_perm(
            'audits.add_auditfollowupaction'
        )
        can_manage_report = user.has_perm('audits.change_auditreport') or user.has_perm(
            'audits.add_auditreport'
        )

        available_audit_actions = available_actions(self.request, resource, audit)

        # Endereço / Local formatado da auditoria
        address_components = []
        if audit.venue_street:
            street_part = audit.venue_street
            if audit.venue_street_number:
                street_part += f', {audit.venue_street_number}'
            if audit.venue_complement:
                street_part += f' ({audit.venue_complement})'
            address_components.append(street_part)
        if audit.venue_neighborhood:
            address_components.append(audit.venue_neighborhood)
        if audit.venue_city_ref:
            address_components.append(audit.venue_city_ref.name)
        if audit.venue_state_ref:
            address_components.append(audit.venue_state_ref.abbreviation)
        if audit.venue_zipcode:
            address_components.append(f'CEP: {audit.venue_zipcode}')
        if audit.venue_country_ref:
            address_components.append(audit.venue_country_ref.name)
        formatted_address = ' - '.join(address_components) if address_components else 'Local não especificado'

        # Aba 2: Checklist de Verificação BPF / ISO 22716
        checklist_items = (
            audit.checklist_items.select_related('answered_by').order_by('section', 'id')
            if can_view_checklist
            else AuditChecklistItem.objects.none()
        )
        checklist_total = checklist_items.count() if can_view_checklist else 0
        checklist_conform = (
            checklist_items.filter(status=AuditChecklistItem.Status.CONFORM).count()
            if can_view_checklist
            else 0
        )
        checklist_non_conform = (
            checklist_items.filter(status=AuditChecklistItem.Status.NON_CONFORM).count()
            if can_view_checklist
            else 0
        )
        checklist_na = (
            checklist_items.filter(status=AuditChecklistItem.Status.NOT_APPLICABLE).count()
            if can_view_checklist
            else 0
        )
        checklist_pending = (
            checklist_items.filter(status=AuditChecklistItem.Status.NOT_EVALUATED).count()
            if can_view_checklist
            else 0
        )
        checklist_required_pending = (
            checklist_items.filter(
                required=True, status=AuditChecklistItem.Status.NOT_EVALUATED
            ).count()
            if can_view_checklist
            else 0
        )
        applicable_items = (
            checklist_items.exclude(
                status__in=[
                    AuditChecklistItem.Status.NOT_EVALUATED,
                    AuditChecklistItem.Status.NOT_APPLICABLE,
                ]
            ).count()
            if can_view_checklist
            else 0
        )
        checklist_evaluated = checklist_total - checklist_pending
        compliance_rate = (
            round((checklist_conform / applicable_items * 100), 1) if applicable_items > 0 else 0.0
        )

        # Aba 3: Constatações, Evidências & Não-Conformidades
        findings = (
            audit.findings.select_related('checklist_item', 'responsible', 'criticality_ref')
            .prefetch_related('evidences', 'actions', 'links')
            .order_by('-criticality', 'due_date')
            if can_view_findings
            else AuditFinding.objects.none()
        )
        findings_total = findings.count() if can_view_findings else 0
        findings_critical = (
            findings.filter(criticality=AuditFinding.Criticality.CRITICAL).count()
            if can_view_findings
            else 0
        )
        findings_major = (
            findings.filter(criticality=AuditFinding.Criticality.MAJOR).count()
            if can_view_findings
            else 0
        )
        findings_minor = (
            findings.filter(criticality=AuditFinding.Criticality.MINOR).count()
            if can_view_findings
            else 0
        )
        findings_open = (
            findings.filter(
                status__in=[AuditFinding.Status.OPEN, AuditFinding.Status.IN_ACTION]
            ).count()
            if can_view_findings
            else 0
        )
        findings_closed = (
            findings.filter(status=AuditFinding.Status.CLOSED).count() if can_view_findings else 0
        )

        evidences = (
            audit.evidences.select_related('finding', 'uploaded_by').order_by('title')
            if can_view_findings
            else AuditEvidence.objects.none()
        )
        evidences_total = evidences.count() if can_view_findings else 0

        # Aba 4: Planos de Ação, CAPAs & Vínculos Transversais
        actions = (
            AuditFollowUpAction.objects.filter(finding__audit=audit)
            .select_related('finding', 'responsible', 'completed_by')
            .order_by('due_date')
            if can_view_actions
            else AuditFollowUpAction.objects.none()
        )
        actions_total = actions.count() if can_view_actions else 0
        actions_completed = (
            actions.filter(status=AuditFollowUpAction.Status.COMPLETED).count()
            if can_view_actions
            else 0
        )
        actions_pending = (
            actions.filter(
                status__in=[
                    AuditFollowUpAction.Status.PENDING,
                    AuditFollowUpAction.Status.IN_PROGRESS,
                ]
            ).count()
            if can_view_actions
            else 0
        )
        if actions_total > 0:
            actions_completion_rate = round((actions_completed / actions_total * 100), 1)
        elif findings_total == 0:
            actions_completion_rate = 100.0
        else:
            actions_completion_rate = 0.0

        finding_links = (
            AuditFindingLink.objects.filter(finding__audit=audit)
            .select_related(
                'finding',
                'capa',
                'deviation_event',
                'change_control',
                'supplier',
                'document',
            )
            .order_by('link_type')
            if can_view_actions
            else AuditFindingLink.objects.none()
        )

        # Aba 5: Relatório Final, Conclusão & Gates de Prontidão
        report = (
            audit.reports.select_related('issued_by').first()
            if can_view_report
            else None
        )

        # 5 Gates de Prontidão e Governança Sanitária de Auditoria (Audit Readiness Gates)
        gate1_passed = bool(
            audit.program_id
            and audit.scope
            and audit.criteria
            and audit.lead_auditor_id
            and audit.scheduled_start
            and audit.scheduled_end
        )
        gate2_passed = bool(
            audit.checklist_items.exists()
            and not audit.checklist_items.filter(
                required=True, status=AuditChecklistItem.Status.NOT_EVALUATED
            ).exists()
        )
        findings_exist = audit.findings.exists()
        gate3_passed = (
            not audit.findings.exclude(evidences__isnull=False).exists()
            if findings_exist
            else True
        )

        critical_or_major = audit.findings.filter(
            criticality__in=[AuditFinding.Criticality.CRITICAL, AuditFinding.Criticality.MAJOR]
        )
        if critical_or_major.exists():
            gate4_passed = (
                not critical_or_major.filter(actions__mandatory=True)
                .exclude(actions__status=AuditFollowUpAction.Status.COMPLETED)
                .exists()
                and not critical_or_major.exclude(actions__mandatory=True).exists()
            )
        else:
            gate4_passed = True

        gate5_passed = bool(
            audit.reports.filter(status=AuditReport.Status.ISSUED).exists()
            and audit.status in [AuditPlan.Status.REPORTING, AuditPlan.Status.CLOSED]
        )

        gates_passed_count = sum(
            [gate1_passed, gate2_passed, gate3_passed, gate4_passed, gate5_passed]
        )

        if audit.status == AuditPlan.Status.CANCELLED:
            regulatory_verdict = 'Auditoria cancelada'
            regulatory_verdict_badge = 'bg-danger'
        elif audit.status == AuditPlan.Status.CLOSED:
            regulatory_verdict = 'Auditoria concluída & Encerrada'
            regulatory_verdict_badge = 'bg-success'
        elif gate1_passed and gate2_passed and gate3_passed and gate4_passed and gate5_passed:
            regulatory_verdict = 'Apta para encerramento formal'
            regulatory_verdict_badge = 'bg-success'
        elif audit.status == AuditPlan.Status.REPORTING:
            regulatory_verdict = 'Em fase de relatório & Ações'
            regulatory_verdict_badge = 'bg-warning text-dark'
        elif audit.status == AuditPlan.Status.IN_PROGRESS:
            regulatory_verdict = 'Em execução na planta'
            regulatory_verdict_badge = 'bg-info text-dark'
        else:
            regulatory_verdict = f'Em preparação ({audit.get_status_display()})'
            regulatory_verdict_badge = 'bg-secondary'

        context.update({
            'audit': audit,
            'can_view_scope': can_view_scope,
            'can_view_checklist': can_view_checklist,
            'can_view_findings': can_view_findings,
            'can_view_actions': can_view_actions,
            'can_view_report': can_view_report,
            'can_manage_audit': can_manage_audit,
            'can_manage_checklist': can_manage_checklist,
            'can_manage_findings': can_manage_findings,
            'can_manage_actions': can_manage_actions,
            'can_manage_report': can_manage_report,
            'available_audit_actions': available_audit_actions,
            'formatted_address': formatted_address,
            'checklist_items': checklist_items,
            'checklist_total': checklist_total,
            'checklist_evaluated': checklist_evaluated,
            'checklist_conform': checklist_conform,
            'checklist_non_conform': checklist_non_conform,
            'checklist_na': checklist_na,
            'checklist_pending': checklist_pending,
            'checklist_required_pending': checklist_required_pending,
            'compliance_rate': compliance_rate,
            'findings': findings,
            'findings_total': findings_total,
            'findings_critical': findings_critical,
            'findings_major': findings_major,
            'findings_minor': findings_minor,
            'findings_open': findings_open,
            'findings_closed': findings_closed,
            'evidences': evidences,
            'evidences_total': evidences_total,
            'actions': actions,
            'actions_total': actions_total,
            'actions_completed': actions_completed,
            'actions_pending': actions_pending,
            'actions_completion_rate': actions_completion_rate,
            'finding_links': finding_links,
            'report': report,
            'gate1_passed': gate1_passed,
            'gate2_passed': gate2_passed,
            'gate3_passed': gate3_passed,
            'gate4_passed': gate4_passed,
            'gate5_passed': gate5_passed,
            'gates_passed_count': gates_passed_count,
            'regulatory_verdict': regulatory_verdict,
            'regulatory_verdict_badge': regulatory_verdict_badge,
        })
        return context
