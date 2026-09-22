from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import models
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.views import View
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from deviations.models import QualityEvent
from inventory.models import StockLot, StockQualityStatus
from qa.models import BatchRecordChecklistItem, LotRelease, QAReview, QualityBlock
from quality.models import QualityDocument, QualitySample


class LotReleaseCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de liberação de lote e revisão de batch record da Garantia da Qualidade (QA)."""

    template_name = 'app/lot_release_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not LotRelease:
            raise Http404('Cockpit disponível apenas para liberações de lote.')
        if not request.user.has_perm('qa.view_lotrelease'):
            raise PermissionDenied('Você não possui permissão para visualizar o cockpit de liberação de lote.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        release = self.get_object()
        lot = release.stock_lot
        product = release.product
        order = release.production_order or getattr(lot, 'source_production_order', None)
        user = self.request.user

        # Segregação de Deveres (SoD) por aba
        can_view_inventory = user.has_perm('inventory.view_stockbalance')
        can_view_genealogy = user.has_perm('inventory.view_stocklotgenealogy')
        can_view_qc = user.has_perm('quality.view_qualitysample')
        can_view_reviews = user.has_perm('qa.view_qareview')
        can_view_checklist = user.has_perm('qa.view_batchrecordchecklistitem')
        can_view_blocks = user.has_perm('qa.view_qualityblock')
        can_view_deviations = user.has_perm('deviations.view_qualityevent')
        can_manage_release = user.has_perm('qa.change_lotrelease')

        resource = self.get_resource()
        available_release_actions = available_actions(self.request, resource, release)

        # Aba 1: Ficha do Lote, Saldos & Genealogia
        balances = []
        balances_summary = {
            'total_quantity': Decimal('0.0000'),
            'total_reserved': Decimal('0.0000'),
            'total_available': Decimal('0.0000'),
            'count': 0,
        }
        if can_view_inventory and lot:
            balances = list(
                lot.balances.select_related('warehouse', 'location', 'unit').order_by(
                    'warehouse__name', 'location__code'
                )
            )
            balances_summary['count'] = len(balances)
            for b in balances:
                balances_summary['total_quantity'] += b.quantity or Decimal('0.0000')
                balances_summary['total_reserved'] += b.reserved_quantity or Decimal('0.0000')
                balances_summary['total_available'] += b.available_quantity

        upstream_genealogy = []
        downstream_genealogy = []
        if can_view_genealogy and lot:
            upstream_genealogy = list(
                lot.input_genealogy_links.select_related(
                    'input_lot__product', 'unit', 'production_order'
                ).order_by('input_lot__lot_number')
            )
            downstream_genealogy = list(
                lot.output_genealogy_links.select_related(
                    'output_lot__product', 'unit', 'production_order'
                ).order_by('output_lot__lot_number')
            )

        # Aba 2: Controle de Qualidade & Laudos Analíticos
        quality_samples = []
        quality_documents = []
        qc_summary = {
            'total_samples': 0,
            'approved_samples': 0,
            'pending_samples': 0,
            'rejected_samples': 0,
            'total_analyses': 0,
        }
        if can_view_qc and lot:
            quality_samples = list(
                lot.quality_samples.select_related(
                    'specification',
                    'unit',
                    'collected_by',
                    'started_by',
                    'approved_by',
                )
                .prefetch_related(
                    'analyses__results__unit',
                    'analyses__analyst',
                    'analyses__reviewer',
                    'analyses__approver',
                )
                .order_by('-collected_at')
            )
            qc_summary['total_samples'] = len(quality_samples)
            for s in quality_samples:
                if s.status == QualitySample.Status.APPROVED:
                    qc_summary['approved_samples'] += 1
                elif s.status in (QualitySample.Status.REJECTED, QualitySample.Status.CANCELLED):
                    qc_summary['rejected_samples'] += 1
                else:
                    qc_summary['pending_samples'] += 1
                qc_summary['total_analyses'] += s.analyses.count()

            quality_documents = list(
                lot.quality_documents.select_related('sample', 'issued_by').order_by(
                    '-issued_at', '-created_at'
                )
            )

        # Aba 3: Revisão do Batch Record & Checklist QA
        qa_review = release.qa_review or (lot.qa_reviews.first() if lot else None)
        checklist_items = []
        checklist_summary = {
            'total': 0,
            'completed': 0,
            'pending': 0,
            'completion_percentage': 0,
        }
        if can_view_reviews and qa_review:
            if can_view_checklist:
                checklist_items = list(
                    qa_review.checklist_items.select_related('responsible', 'completed_by').order_by(
                        'created_at'
                    )
                )
                checklist_summary['total'] = len(checklist_items)
                checklist_summary['completed'] = sum(
                    1 for item in checklist_items if item.status == BatchRecordChecklistItem.Status.COMPLETED
                )
                checklist_summary['pending'] = sum(
                    1 for item in checklist_items if item.status == BatchRecordChecklistItem.Status.PENDING
                )
                if checklist_summary['total'] > 0:
                    checklist_summary['completion_percentage'] = int(
                        (checklist_summary['completed'] / checklist_summary['total']) * 100
                    )
                else:
                    checklist_summary['completion_percentage'] = 100 if qa_review.status == QAReview.Status.APPROVED else 0

        # Aba 4: Bloqueios Sanitários & Desvios
        quality_blocks = []
        active_blocks_count = 0
        if can_view_blocks and lot:
            quality_blocks = list(
                QualityBlock.objects.filter(stock_lot=lot)
                .select_related('blocked_by', 'unblocked_by')
                .order_by('-blocked_at')
            )
            active_blocks_count = sum(
                1 for b in quality_blocks if b.status == QualityBlock.Status.ACTIVE
            )

        deviations = []
        open_deviations_count = 0
        if can_view_deviations and lot:
            q_filter = models.Q(stock_lot=lot) | models.Q(
                product=lot.product, origin=QualityEvent.Origin.QUALITY_CONTROL
            )
            if order:
                q_filter |= models.Q(links__reference_code=order.order_number)
            deviations = list(
                QualityEvent.objects.filter(q_filter)
                .select_related('responsible', 'opened_by', 'closed_by')
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

        # Aba 5: Decisão e Liberação Sanitária (ALCOA+)
        has_approved_samples = bool(
            quality_samples and qc_summary['approved_samples'] == qc_summary['total_samples']
        )
        has_issued_document = bool(
            quality_documents
            and any(d.status == QualityDocument.Status.ISSUED for d in quality_documents)
        )
        has_approved_review = bool(qa_review and qa_review.status == QAReview.Status.APPROVED)
        has_clean_checklist = bool(
            checklist_summary['total'] > 0 and checklist_summary['pending'] == 0
        )
        has_no_active_blocks = active_blocks_count == 0
        has_no_open_deviations = open_deviations_count == 0

        readiness_criteria = [
            {
                'title': 'Amostras de Controle de Qualidade Aprovadas',
                'passed': has_approved_samples,
                'detail': (
                    f"{qc_summary['approved_samples']} de {qc_summary['total_samples']} amostras aprovadas"
                    if quality_samples
                    else 'Nenhuma amostra coletada'
                ),
                'icon': 'feather-check-circle' if has_approved_samples else 'feather-alert-circle',
            },
            {
                'title': 'Laudo Analítico / Certificado de Análise Emitido',
                'passed': has_issued_document,
                'detail': (
                    f"{sum(1 for d in quality_documents if d.status == QualityDocument.Status.ISSUED)} laudo(s) emitido(s)"
                    if quality_documents
                    else 'Laudo pendente de emissão'
                ),
                'icon': 'feather-check-circle' if has_issued_document else 'feather-alert-circle',
            },
            {
                'title': 'Revisão do Batch Record Aprovada pela Garantia',
                'passed': has_approved_review,
                'detail': (
                    f"Status: {qa_review.get_status_display()}"
                    if qa_review
                    else 'Revisão QA não iniciada'
                ),
                'icon': 'feather-check-circle' if has_approved_review else 'feather-alert-circle',
            },
            {
                'title': 'Checklist de Verificação Sem Pendências',
                'passed': has_clean_checklist,
                'detail': (
                    f"{checklist_summary['completed']} de {checklist_summary['total']} itens concluídos"
                    if checklist_summary['total'] > 0
                    else 'Checklist não configurado'
                ),
                'icon': 'feather-check-circle' if has_clean_checklist else 'feather-alert-circle',
            },
            {
                'title': 'Ausência de Bloqueios Sanitários Ativos',
                'passed': has_no_active_blocks,
                'detail': (
                    'Nenhum bloqueio ativo no lote'
                    if has_no_active_blocks
                    else f"{active_blocks_count} bloqueio(s) ativo(s)"
                ),
                'icon': 'feather-check-circle' if has_no_active_blocks else 'feather-slash',
            },
            {
                'title': 'Ausência de Desvios Críticos em Aberto',
                'passed': has_no_open_deviations,
                'detail': (
                    'Nenhum desvio pendente'
                    if has_no_open_deviations
                    else f"{open_deviations_count} desvio(s) aberto(s)"
                ),
                'icon': 'feather-check-circle' if has_no_open_deviations else 'feather-alert-triangle',
            },
        ]
        all_readiness_passed = all(c['passed'] for c in readiness_criteria)

        context.update(
            {
                'release': release,
                'lot': lot,
                'product': product,
                'order': order,
                'available_release_actions': available_release_actions,
                # Permissões SoD
                'can_view_inventory': can_view_inventory,
                'can_view_genealogy': can_view_genealogy,
                'can_view_qc': can_view_qc,
                'can_view_reviews': can_view_reviews,
                'can_view_checklist': can_view_checklist,
                'can_view_blocks': can_view_blocks,
                'can_view_deviations': can_view_deviations,
                'can_manage_release': can_manage_release,
                # Aba 1
                'balances': balances,
                'balances_summary': balances_summary,
                'upstream_genealogy': upstream_genealogy,
                'downstream_genealogy': downstream_genealogy,
                # Aba 2
                'quality_samples': quality_samples,
                'quality_documents': quality_documents,
                'qc_summary': qc_summary,
                # Aba 3
                'qa_review': qa_review,
                'checklist_items': checklist_items,
                'checklist_summary': checklist_summary,
                # Aba 4
                'quality_blocks': quality_blocks,
                'active_blocks_count': active_blocks_count,
                'deviations': deviations,
                'open_deviations_count': open_deviations_count,
                # Aba 5
                'readiness_criteria': readiness_criteria,
                'all_readiness_passed': all_readiness_passed,
            }
        )
        return context


class StockLotDossierView(LoginRequiredMixin, View):
    """Localiza ou cria o registro de liberação QA para o lote e redireciona ao cockpit."""

    def get(self, request, pk, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not (
            request.user.has_perm('qa.view_lotrelease')
            or request.user.has_perm('inventory.view_stocklot')
        ):
            raise PermissionDenied('Você não possui permissão para visualizar o dossiê do lote.')

        lot = get_object_or_404(
            StockLot.objects.select_related('product', 'source_production_order'), pk=pk
        )
        release = lot.qa_lot_releases.first()
        if not release:
            if request.user.has_perm('qa.add_lotrelease'):
                release = LotRelease.objects.create(
                    product=lot.product,
                    stock_lot=lot,
                    production_order=lot.source_production_order,
                )
                messages.success(
                    request,
                    f'Dossiê de liberação QA iniciado com sucesso para o lote {lot.lot_number}.',
                )
            else:
                messages.warning(
                    request,
                    f'O lote {lot.lot_number} ainda não possui liberação cadastrada pela Garantia da Qualidade.',
                )
                return redirect(
                    'app:resource_detail',
                    module_slug='inventory',
                    resource_slug='lots',
                    pk=lot.pk,
                )
        return redirect('app:qa_lot_release_cockpit', pk=release.pk)
