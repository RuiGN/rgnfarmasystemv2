from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from documents.models import (
    ControlledDocument,
    DocumentApproval,
    DocumentAttachment,
    DocumentAuditTrail,
    DocumentDistribution,
    DocumentRelationship,
)
from governance.models import GovernanceAuditLog
from qa.models import QAReview, QualityBlock
from training.models import (
    TrainingEnrollment,
    TrainingRequirement,
)


class ControlledDocumentCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de Gestão de Documentos Controlados e Treinamentos (DMS & Capacitação)."""

    template_name = 'app/controlled_document_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not ControlledDocument:
            raise Http404('Cockpit disponível apenas para documentos controlados.')
        if not request.user.has_perm('documents.view_controlleddocument'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit de documento controlado.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        resource = self.get_resource()

        doc = get_object_or_404(
            ControlledDocument.objects.select_related(
                'owner',
                'area_ref',
                'supersedes',
                'submitted_by',
                'reviewed_by',
                'approved_by',
                'published_by',
                'obsoleted_by',
                'cancelled_by',
                'archived_by',
            ),
            pk=self.kwargs['pk'],
        )

        # Segregação de Deveres (SoD) por aba
        can_view_metadata = user.has_perm('documents.view_controlleddocument')
        can_view_matrix = (
            user.has_perm('training.view_trainingrequirement')
            or user.has_perm('training.view_jobposition')
            or user.has_perm('documents.view_controlleddocument')
        )
        can_view_enrollments = (
            user.has_perm('training.view_trainingenrollment')
            or user.has_perm('training.view_trainingsession')
        )
        can_view_approvals = (
            user.has_perm('documents.view_documentapproval')
            or user.has_perm('documents.view_controlleddocument')
        )
        can_view_governance = (
            user.has_perm('documents.view_documentdistribution')
            or user.has_perm('documents.view_documentaudittrail')
            or user.has_perm('governance.view_governanceauditlog')
        )
        can_manage_document = user.has_perm('documents.change_controlleddocument')
        can_manage_training = (
            user.has_perm('training.add_trainingrequirement')
            or user.has_perm('training.add_trainingenrollment')
        )
        can_manage_qa = (
            user.has_perm('qa.change_qareview')
            or user.has_perm('qa.add_qualityblock')
        )

        available_document_actions = available_actions(self.request, resource, doc)

        # Vigência Sanitária e Vencimento
        days_until_expiry = None
        is_expired = False
        if doc.valid_until:
            delta = (doc.valid_until - timezone.localdate()).days
            days_until_expiry = delta
            is_expired = delta < 0

        # Bloqueios Ativos de Garantia da Qualidade (QA)
        qa_blocks = (
            QualityBlock.objects.filter(
                target_type=QualityBlock.TargetType.DOCUMENT,
                document_reference=doc.code,
            )
            .select_related('blocked_by', 'unblocked_by')
            .order_by('-blocked_at')
        )
        active_qa_block = qa_blocks.filter(status=QualityBlock.Status.ACTIVE).first()
        has_active_block = active_qa_block is not None

        # Aba 1: Metadados, Conteúdo e Anexos
        attachments = (
            doc.attachments.select_related('uploaded_by')
            .order_by('file_name')
        ) if can_view_metadata else DocumentAttachment.objects.none()

        # Aba 2: Matriz de Treinamentos Requeridos
        training_requirements = (
            TrainingRequirement.objects.filter(document=doc)
            .select_related('job_position', 'function', 'competency')
            .annotate(
                total_enrolled=Count('enrollments', distinct=True),
                total_approved=Count(
                    'enrollments',
                    filter=Q(enrollments__status=TrainingEnrollment.Status.APPROVED),
                    distinct=True,
                ),
            )
            .order_by('code')
        ) if can_view_matrix else TrainingRequirement.objects.none()

        total_requirements_count = training_requirements.count() if can_view_matrix else 0
        active_requirements_count = (
            training_requirements.filter(is_active=True).count() if can_view_matrix else 0
        )

        # Aba 3: Colaboradores Treinados & Provas de Eficácia (ALCOA+)
        enrollments = (
            TrainingEnrollment.objects.filter(requirement__document=doc)
            .select_related(
                'user',
                'requirement',
                'requirement__job_position',
                'requirement__function',
                'session',
                'convoked_by',
                'approved_by',
                'completed_by',
            )
            .order_by('-convoked_at', '-created_at')
        ) if can_view_enrollments else TrainingEnrollment.objects.none()

        total_enrollments = enrollments.count() if can_view_enrollments else 0
        approved_enrollments_count = (
            enrollments.filter(status=TrainingEnrollment.Status.APPROVED).count()
            if can_view_enrollments
            else 0
        )
        in_progress_count = (
            enrollments.filter(
                status__in=[
                    TrainingEnrollment.Status.CONVOKED,
                    TrainingEnrollment.Status.IN_PROGRESS,
                    TrainingEnrollment.Status.COMPLETED,
                ]
            ).count()
            if can_view_enrollments
            else 0
        )
        failed_count = (
            enrollments.filter(status=TrainingEnrollment.Status.FAILED).count()
            if can_view_enrollments
            else 0
        )
        expired_count = (
            enrollments.filter(status=TrainingEnrollment.Status.EXPIRED).count()
            if can_view_enrollments
            else 0
        )
        revoked_count = (
            enrollments.filter(status=TrainingEnrollment.Status.REVOKED).count()
            if can_view_enrollments
            else 0
        )

        if total_enrollments > 0:
            compliance_rate = round((approved_enrollments_count / total_enrollments) * 100, 1)
        elif total_requirements_count == 0:
            compliance_rate = 100.0
        else:
            compliance_rate = 0.0

        avg_score = (
            enrollments.filter(score__isnull=False).aggregate(avg=Avg('score'))['avg']
            if can_view_enrollments
            else None
        )

        # Aba 4: Fluxo de Aprovação, Assinaturas e Linhagem de Revisões
        approvals = (
            doc.approvals.select_related('user')
            .order_by('role', 'created_at')
        ) if can_view_approvals else DocumentApproval.objects.none()

        successors = (
            doc.revisions.select_related('owner', 'approved_by', 'published_by')
            .order_by('-version')
        ) if can_view_approvals else ControlledDocument.objects.none()

        lineage = (
            ControlledDocument.objects.filter(code=doc.code)
            .select_related('owner', 'approved_by', 'published_by')
            .order_by('version')
        ) if can_view_approvals else ControlledDocument.objects.none()

        qa_reviews = (
            QAReview.objects.filter(
                Q(
                    review_type=QAReview.ReviewType.CONTROLLED_DOCUMENT,
                    controlled_document_reference=doc.code,
                )
                | Q(title__icontains=doc.code)
            )
            .select_related('submitted_by', 'approved_by')
            .order_by('-created_at')
        ) if can_view_approvals else QAReview.objects.none()

        # Aba 5: Distribuição Controlada, Vínculos & Trilha ALCOA+
        distributions = (
            doc.distributions.select_related('recipient', 'distributed_by', 'confirmed_by')
            .order_by('due_date', '-created_at')
        ) if can_view_governance else DocumentDistribution.objects.none()

        distributions_total = distributions.count() if can_view_governance else 0
        distributions_confirmed = (
            distributions.filter(status=DocumentDistribution.Status.CONFIRMED).count()
            if can_view_governance
            else 0
        )

        outgoing_relationships = (
            doc.outgoing_relationships.select_related('related_document')
            .order_by('relationship_type')
        ) if can_view_governance else DocumentRelationship.objects.none()

        incoming_relationships = (
            doc.incoming_relationships.select_related('source_document')
            .order_by('relationship_type')
        ) if can_view_governance else DocumentRelationship.objects.none()

        audit_trail = (
            doc.audit_trail.select_related('actor')
            .order_by('-created_at')
        ) if can_view_governance else DocumentAuditTrail.objects.none()

        governance_logs = (
            GovernanceAuditLog.objects.filter(
                target_model='ControlledDocument',
                target_record_id__in=[str(doc.pk), doc.code],
            )
            .select_related('user', 'severity_ref', 'module_ref')
            .order_by('-created_at')[:20]
        ) if can_view_governance else GovernanceAuditLog.objects.none()

        # 5 Gates de Prontidão e Governança Sanitária (DMS Readiness Gates)
        gate1_passed = bool(
            doc.code
            and doc.title
            and doc.version
            and (doc.area or doc.area_ref_id)
            and doc.content
        )
        gate2_passed = doc.status in [
            ControlledDocument.Status.APPROVED,
            ControlledDocument.Status.PUBLISHED,
        ]
        gate3_passed = (
            doc.status == ControlledDocument.Status.PUBLISHED
            and not is_expired
        )
        gate4_passed = active_requirements_count > 0
        gate5_passed = (not has_active_block) and (
            compliance_rate >= 80.0 if total_enrollments > 0 else True
        )

        gates_passed_count = sum(
            [gate1_passed, gate2_passed, gate3_passed, gate4_passed, gate5_passed]
        )

        if has_active_block:
            regulatory_verdict = 'Documento sob bloqueio sanitário QA'
            regulatory_verdict_badge = 'bg-danger'
        elif is_expired:
            regulatory_verdict = 'Vigência sanitária expirada'
            regulatory_verdict_badge = 'bg-danger'
        elif (
            gate1_passed
            and gate2_passed
            and gate3_passed
            and gate4_passed
            and gate5_passed
        ):
            regulatory_verdict = 'Vigente & Capacitação Conforme (BPF)'
            regulatory_verdict_badge = 'bg-success'
        elif doc.status == ControlledDocument.Status.PUBLISHED:
            regulatory_verdict = 'Publicado com pendências de capacitação'
            regulatory_verdict_badge = 'bg-warning text-dark'
        elif doc.status == ControlledDocument.Status.APPROVED:
            regulatory_verdict = 'Aprovado aguardando publicação'
            regulatory_verdict_badge = 'bg-info text-dark'
        else:
            regulatory_verdict = f'Em elaboração ({doc.get_status_display()})'
            regulatory_verdict_badge = 'bg-secondary'

        context.update({
            'doc': doc,
            'can_view_metadata': can_view_metadata,
            'can_view_matrix': can_view_matrix,
            'can_view_enrollments': can_view_enrollments,
            'can_view_approvals': can_view_approvals,
            'can_view_governance': can_view_governance,
            'can_manage_document': can_manage_document,
            'can_manage_training': can_manage_training,
            'can_manage_qa': can_manage_qa,
            'available_document_actions': available_document_actions,
            'days_until_expiry': days_until_expiry,
            'is_expired': is_expired,
            'qa_blocks': qa_blocks,
            'active_qa_block': active_qa_block,
            'has_active_block': has_active_block,
            'attachments': attachments,
            'training_requirements': training_requirements,
            'total_requirements_count': total_requirements_count,
            'active_requirements_count': active_requirements_count,
            'enrollments': enrollments,
            'total_enrollments': total_enrollments,
            'approved_enrollments_count': approved_enrollments_count,
            'in_progress_count': in_progress_count,
            'failed_count': failed_count,
            'expired_count': expired_count,
            'revoked_count': revoked_count,
            'compliance_rate': compliance_rate,
            'avg_score': avg_score,
            'approvals': approvals,
            'successors': successors,
            'lineage': lineage,
            'qa_reviews': qa_reviews,
            'distributions': distributions,
            'distributions_total': distributions_total,
            'distributions_confirmed': distributions_confirmed,
            'outgoing_relationships': outgoing_relationships,
            'incoming_relationships': incoming_relationships,
            'audit_trail': audit_trail,
            'governance_logs': governance_logs,
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
