from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import Http404
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from capa.models import CapaRecord
from deviations.models import QualityEvent
from inventory.models import StockBalance
from qa.models import QualityBlock
from quality.models import QualityAnalysis, QualitySample
from recalls.models import (
    MarketComplaint,
    ProductReturn,
    RecallCampaign,
    RecallCommunication,
    RecallEffectivenessReport,
    RecallImpactedCustomer,
)


class MarketComplaintCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de Cosmetovigilância, Reclamações de Mercado e Recolhimento (Recall 360°)."""

    template_name = 'app/market_complaint_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not MarketComplaint:
            raise Http404('Cockpit disponível apenas para reclamações de mercado.')
        if not request.user.has_perm('recalls.view_marketcomplaint'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit de cosmetovigilância.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        resource = self.get_resource()

        # Obter a reclamação pós-mercado com otimização de select_related
        complaint = (
            MarketComplaint.objects.select_related(
                'customer',
                'product',
                'product__unit',
                'stock_lot',
                'sales_order',
                'fiscal_document',
                'customer_complaint',
                'quality_sample',
                'deviation_event',
                'capa',
                'document',
                'responsible',
                'reported_by',
                'triaged_by',
                'investigation_started_by',
                'regulatory_communicated_by',
                'closed_by',
                'country_ref',
                'state_ref',
                'city_ref',
                'criticality_ref',
            )
            .get(pk=self.kwargs['pk'])
        )

        # Segregação de Deveres (SoD) por aba
        can_view_triage = user.has_perm('recalls.view_marketcomplaint')
        can_view_crm = user.has_perm('crm.view_customercomplaint')
        can_view_analysis = user.has_perm('quality.view_qualitysample') or user.has_perm(
            'quality.view_qualityanalysis'
        )
        can_view_deviations = user.has_perm('deviations.view_qualityevent')
        can_view_returns = user.has_perm('recalls.view_productreturn')
        can_view_inventory = user.has_perm('inventory.view_stockbalance') or user.has_perm(
            'qa.view_qualityblock'
        )
        can_view_recalls = user.has_perm('recalls.view_recallcampaign')
        can_view_impacted_customers = user.has_perm('recalls.view_recallimpactedcustomer')
        can_view_communications = user.has_perm('recalls.view_recallcommunication')
        can_view_effectiveness = user.has_perm('recalls.view_recalleffectivenessreport')
        can_view_capa = user.has_perm('capa.view_caparecord')
        can_manage_complaint = user.has_perm('recalls.change_marketcomplaint')

        available_complaint_actions = available_actions(self.request, resource, complaint)

        # Localização geográfica formatada
        location_parts = []
        if complaint.city_ref:
            location_parts.append(complaint.city_ref.name)
        if complaint.state_ref:
            location_parts.append(complaint.state_ref.code)
        if complaint.country_ref:
            location_parts.append(complaint.country_ref.code)
        location_str = ' - '.join(location_parts) if location_parts else 'Não informada'

        # Aba 2: Amostroteca e Investigação Analítica
        sample = complaint.quality_sample
        if not sample and complaint.stock_lot:
            sample = QualitySample.objects.filter(
                product=complaint.product, stock_lot=complaint.stock_lot
            ).first()

        analyses = []
        sample_results = []
        if can_view_analysis and sample:
            analyses = list(
                QualityAnalysis.objects.filter(sample=sample)
                .select_related('analyst', 'reviewer', 'approver', 'specification')
                .prefetch_related('results', 'results__unit')
                .order_by('-created_at')
            )
            for an in analyses:
                for res in an.results.all():
                    sample_results.append(
                        {
                            'analysis': an,
                            'result': res,
                            'parameter': res.parameter_name,
                            'result_status': res.result_status,
                            'numeric_result': res.numeric_result,
                            'text_result': res.text_result,
                            'unit': res.unit.code if res.unit else '',
                        }
                    )

        deviation = complaint.deviation_event
        if not deviation and complaint.stock_lot:
            deviation = QualityEvent.objects.filter(
                product=complaint.product, stock_lot=complaint.stock_lot
            ).first()

        # Aba 3: Devoluções de Produto e Quarentena (Logística Reversa & WMS)
        returns = []
        total_return_quantity_requested = Decimal('0.0000')
        total_return_quantity_received = Decimal('0.0000')
        if can_view_returns:
            return_query = Q(complaint=complaint)
            if complaint.stock_lot:
                return_query |= Q(
                    customer=complaint.customer,
                    product=complaint.product,
                    stock_lot=complaint.stock_lot,
                )
            returns = list(
                ProductReturn.objects.filter(return_query)
                .distinct()
                .select_related(
                    'customer',
                    'product',
                    'stock_lot',
                    'unit',
                    'requested_by',
                    'authorized_by',
                    'received_by',
                    'inspected_by',
                    'closed_by',
                )
                .order_by('-created_at')
            )
            total_return_quantity_requested = sum(
                (r.quantity for r in returns), Decimal('0.0000')
            )
            total_return_quantity_received = sum(
                (r.received_quantity for r in returns), Decimal('0.0000')
            )

        quarantine_balances = []
        quality_blocks = []
        if can_view_inventory and complaint.stock_lot:
            quarantine_balances = list(
                StockBalance.objects.filter(lot=complaint.stock_lot)
                .select_related('warehouse', 'location', 'unit')
                .order_by('-quantity')
            )
            quality_blocks = list(
                QualityBlock.objects.filter(stock_lot=complaint.stock_lot)
                .select_related('blocked_by', 'unblocked_by')
                .order_by('-blocked_at')
            )

        # Aba 4: Recolhimento de Mercado (Recall) e Clientes Impactados
        campaigns = []
        main_campaign = None
        impacted_customers = []
        communications = []
        total_impacted = 0
        total_distributed = Decimal('0.0000')
        total_to_recall = Decimal('0.0000')
        total_returned_by_customers = Decimal('0.0000')
        recovery_rate = Decimal('0.00')

        if can_view_recalls:
            campaign_query = Q(complaint=complaint)
            if complaint.stock_lot:
                campaign_query |= Q(
                    product=complaint.product,
                    stock_lot=complaint.stock_lot,
                )
            campaigns = list(
                RecallCampaign.objects.filter(campaign_query)
                .distinct()
                .select_related('product', 'stock_lot', 'responsible', 'approved_by', 'started_by', 'closed_by')
                .order_by('-decision_date', '-created_at')
            )
            main_campaign = campaigns[0] if campaigns else None

            if main_campaign:
                if can_view_impacted_customers:
                    impacted_customers = list(
                        main_campaign.impacted_customers.select_related(
                            'customer', 'sales_order', 'fiscal_document'
                        ).order_by('customer__legal_name')
                    )
                    total_impacted = len(impacted_customers)
                    total_distributed = sum(
                        (c.quantity_distributed for c in impacted_customers), Decimal('0.0000')
                    )
                    total_to_recall = sum(
                        (c.quantity_recalled for c in impacted_customers), Decimal('0.0000')
                    )
                    total_returned_by_customers = sum(
                        (c.quantity_returned for c in impacted_customers), Decimal('0.0000')
                    )
                    if total_to_recall > Decimal('0'):
                        recovery_rate = (
                            (total_returned_by_customers / total_to_recall) * Decimal('100')
                        ).quantize(Decimal('0.01'))

                if can_view_communications:
                    communications = list(
                        main_campaign.communications.select_related(
                            'impacted_customer', 'impacted_customer__customer', 'sent_by'
                        ).order_by('-sent_at', '-created_at')
                    )

        # Aba 5: Dossiê Regulatório ANVISA, Eficácia e Fechamento
        effectiveness_reports = []
        if can_view_effectiveness and campaigns:
            effectiveness_reports = list(
                RecallEffectivenessReport.objects.filter(campaign__in=campaigns)
                .select_related('campaign', 'generated_by')
                .order_by('-generated_at', '-created_at')
            )

        capa = complaint.capa
        capa_actions = []
        if can_view_capa and capa:
            capa_actions = list(
                capa.actions.select_related('responsible', 'completed_by').order_by(
                    'action_type', 'created_at'
                )
            )

        # Checklist Regulatório de Encerramento (Cosmetovigilância & ANVISA)
        has_triage = complaint.triaged_at is not None
        has_investigation = bool(complaint.investigation_summary)
        has_regulatory_communication = (
            bool(complaint.regulatory_communication_reference)
            if complaint.regulatory_communication_required
            else True
        )
        has_returns_processed = (
            all(
                r.status in [ProductReturn.Status.INSPECTED, ProductReturn.Status.CLOSED]
                for r in returns
            )
            if returns
            else True
        )
        has_recall_effectiveness = bool(effectiveness_reports) if main_campaign else True
        all_regulatory_checks_ok = all(
            [
                has_triage,
                has_investigation,
                has_regulatory_communication,
                has_returns_processed,
                has_recall_effectiveness,
            ]
        )

        context.update(
            {
                'complaint': complaint,
                'customer': complaint.customer,
                'product': complaint.product,
                'stock_lot': complaint.stock_lot,
                'location_str': location_str,
                'available_complaint_actions': available_complaint_actions,
                # Permissões SoD
                'can_view_triage': can_view_triage,
                'can_view_crm': can_view_crm,
                'can_view_analysis': can_view_analysis,
                'can_view_deviations': can_view_deviations,
                'can_view_returns': can_view_returns,
                'can_view_inventory': can_view_inventory,
                'can_view_recalls': can_view_recalls,
                'can_view_impacted_customers': can_view_impacted_customers,
                'can_view_communications': can_view_communications,
                'can_view_effectiveness': can_view_effectiveness,
                'can_view_capa': can_view_capa,
                'can_manage_complaint': can_manage_complaint,
                # Dados da Aba 2
                'sample': sample,
                'analyses': analyses,
                'sample_results': sample_results,
                'deviation': deviation,
                # Dados da Aba 3
                'returns': returns,
                'total_return_quantity_requested': total_return_quantity_requested,
                'total_return_quantity_received': total_return_quantity_received,
                'quarantine_balances': quarantine_balances,
                'quality_blocks': quality_blocks,
                # Dados da Aba 4
                'campaigns': campaigns,
                'main_campaign': main_campaign,
                'impacted_customers': impacted_customers,
                'communications': communications,
                'total_impacted': total_impacted,
                'total_distributed': total_distributed,
                'total_to_recall': total_to_recall,
                'total_returned_by_customers': total_returned_by_customers,
                'recovery_rate': recovery_rate,
                # Dados da Aba 5
                'effectiveness_reports': effectiveness_reports,
                'capa': capa,
                'capa_actions': capa_actions,
                # Checklist Regulatório
                'has_triage': has_triage,
                'has_investigation': has_investigation,
                'has_regulatory_communication': has_regulatory_communication,
                'has_returns_processed': has_returns_processed,
                'has_recall_effectiveness': has_recall_effectiveness,
                'all_regulatory_checks_ok': all_regulatory_checks_ok,
            }
        )
        return context
