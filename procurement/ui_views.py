from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, Q, Sum
from django.http import Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.generic import TemplateView

from audits.models import (
    AuditChecklistItem,
    AuditEvidence,
    AuditFinding,
    AuditFindingLink,
    AuditPlan,
    AuditReport,
)
from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from deviations.models import QualityEvent
from masters.models import BusinessPartner, Product
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierQuotation,
    SupplierQualificationEvent,
)
from qa.models import QualityBlock
from quality.models import LaboratoryInvestigation, QualitySample


class SupplierCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado de Homologação, Qualificação e Desempenho de Fornecedores (Vendor Lifecycle 360°)."""

    template_name = 'app/supplier_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not BusinessPartner:
            raise Http404('Cockpit disponível apenas para parceiros de negócio / fornecedores.')
        if not request.user.has_perm('masters.view_businesspartner'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit de qualificação de fornecedor.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        resource = self.get_resource()

        partner = get_object_or_404(
            BusinessPartner.objects.select_related(
                'country_ref',
                'state_ref',
                'city_ref',
            ),
            pk=self.kwargs['pk'],
        )

        # Segregação de Deveres (SoD) por aba
        can_view_cadastral = user.has_perm('masters.view_businesspartner')
        can_view_events = user.has_perm('procurement.view_supplierqualificationevent')
        can_view_audits = user.has_perm('audits.view_auditplan') or user.has_perm(
            'audits.view_auditreport'
        )
        can_view_deliveries = user.has_perm('procurement.view_purchaseorder') or user.has_perm(
            'procurement.view_purchasereceipt'
        )
        can_view_quality = (
            user.has_perm('quality.view_qualitysample')
            or user.has_perm('deviations.view_qualityevent')
            or user.has_perm('quality.view_laboratoryinvestigation')
        )
        can_view_products = user.has_perm('masters.view_product') or user.has_perm(
            'procurement.view_purchaseorder'
        )
        can_view_scorecard = user.has_perm('masters.view_businesspartner')
        can_manage_partner = user.has_perm('masters.change_businesspartner')
        can_manage_events = user.has_perm(
            'procurement.add_supplierqualificationevent'
        ) or user.has_perm('procurement.change_supplierqualificationevent')
        can_view_blocks = user.has_perm('qa.view_qualityblock')

        available_partner_actions = available_actions(self.request, resource, partner)

        # Endereço formatado e localização
        address_components = []
        if partner.street:
            street_part = partner.street
            if partner.street_number:
                street_part += f', {partner.street_number}'
            if partner.complement:
                street_part += f' ({partner.complement})'
            address_components.append(street_part)
        if partner.neighborhood:
            address_components.append(partner.neighborhood)
        if partner.city_ref:
            address_components.append(partner.city_ref.name)
        if partner.state_ref:
            address_components.append(partner.state_ref.abbreviation)
        if partner.zipcode:
            address_components.append(f'CEP: {partner.zipcode}')
        if partner.country_ref:
            address_components.append(partner.country_ref.name)
        formatted_address = ' - '.join(address_components) if address_components else 'Endereço não cadastrado'

        # Validade da qualificação
        days_until_expiry = None
        is_expired = False
        if partner.qualification_valid_until:
            delta = (partner.qualification_valid_until - timezone.localdate()).days
            days_until_expiry = delta
            is_expired = delta < 0

        # Bloqueios e Restrições Ativas
        active_supplier_event_blocks = SupplierQualificationEvent.objects.filter(
            supplier=partner,
            blocks_purchases=True,
            resolved_at__isnull=True,
        ).filter(Q(valid_until__isnull=True) | Q(valid_until__gte=timezone.localdate()))

        active_qa_blocks = QualityBlock.objects.filter(
            supplier=partner,
            status=QualityBlock.Status.ACTIVE,
        )

        has_active_block = (
            partner.is_blocked
            or active_supplier_event_blocks.exists()
            or active_qa_blocks.exists()
        )

        # --- TAB 1: DADOS CADASTRAIS & LICENÇAS SANITÁRIAS ---
        qualification_events = (
            SupplierQualificationEvent.objects.filter(supplier=partner)
            .select_related('severity_ref', 'site', 'event_city_ref', 'event_state_ref')
            .order_by('-event_date', '-created_at')
        )
        license_events = qualification_events.filter(
            event_type=SupplierQualificationEvent.EventType.DOCUMENT
        )
        restriction_events = qualification_events.filter(
            event_type__in=[
                SupplierQualificationEvent.EventType.RESTRICTION,
                SupplierQualificationEvent.EventType.OCCURRENCE,
            ]
        )
        qa_blocks_history = (
            QualityBlock.objects.filter(supplier=partner)
            .select_related('blocked_by', 'unblocked_by', 'product')
            .order_by('-created_at')
        )

        # --- TAB 2: AUDITORIAS DE FORNECEDOR BPF ---
        supplier_audits = (
            AuditPlan.objects.filter(supplier=partner)
            .select_related('program', 'lead_auditor', 'area_ref')
            .prefetch_related('reports', 'checklist_items', 'findings', 'evidences')
            .order_by('-scheduled_start', '-created_at')
        )
        supplier_findings = (
            AuditFinding.objects.filter(audit__supplier=partner)
            .select_related('audit', 'responsible', 'criticality_ref')
            .order_by('-created_at')
        )
        linked_findings = (
            AuditFindingLink.objects.filter(supplier=partner)
            .select_related('finding', 'finding__audit')
            .order_by('-created_at')
        )
        audit_qualification_events = qualification_events.filter(
            event_type=SupplierQualificationEvent.EventType.AUDIT
        )

        total_audits_count = supplier_audits.count()
        closed_audits_count = supplier_audits.filter(status=AuditPlan.Status.CLOSED).count()
        critical_findings_count = supplier_findings.filter(criticality='critical').count()
        critical_findings_open = supplier_findings.filter(
            criticality='critical'
        ).exclude(status='closed').count()
        major_findings_count = supplier_findings.filter(criticality='major').count()
        minor_findings_count = supplier_findings.filter(criticality='minor').count()

        issued_audit_reports = AuditReport.objects.filter(
            audit__supplier=partner, status=AuditReport.Status.ISSUED
        )
        avg_audit_compliance = (
            issued_audit_reports.aggregate(avg=Avg('compliance_rate'))['avg']
        )
        if avg_audit_compliance is not None:
            avg_audit_compliance_pct = Decimal(str(avg_audit_compliance)).quantize(Decimal('0.01'))
        else:
            avg_audit_compliance_pct = None

        # --- TAB 3: HISTÓRICO DE ENTREGAS & OOS NO RECEBIMENTO ---
        purchase_orders = (
            PurchaseOrder.objects.filter(supplier=partner)
            .select_related('approved_by')
            .prefetch_related('items', 'items__product', 'items__unit')
            .order_by('-created_at')
        )
        purchase_receipts = (
            PurchaseReceipt.objects.filter(order__supplier=partner)
            .select_related('order', 'received_by')
            .prefetch_related('items', 'items__product', 'items__unit')
            .order_by('-physical_received_at', '-created_at')
        )
        quality_samples = (
            QualitySample.objects.filter(source_purchase_receipt__order__supplier=partner)
            .select_related('product', 'collected_by', 'approved_by', 'rejected_by')
            .prefetch_related('investigations', 'analyses')
            .order_by('-collected_at', '-created_at')
        )
        lab_investigations = (
            LaboratoryInvestigation.objects.filter(
                sample__source_purchase_receipt__order__supplier=partner
            )
            .select_related('sample', 'sample__product', 'opened_by', 'concluded_by')
            .order_by('-created_at')
        )
        quality_events = (
            QualityEvent.objects.filter(supplier=partner)
            .select_related('opened_by', 'responsible', 'closed_by')
            .order_by('-detected_at', '-created_at')
        )

        total_orders_count = purchase_orders.count()
        total_receipts_count = purchase_receipts.count()
        approved_receipts_count = purchase_receipts.filter(
            quality_status=PurchaseReceipt.QualityStatus.APPROVED
        ).count()
        quarantine_receipts_count = purchase_receipts.filter(
            quality_status=PurchaseReceipt.QualityStatus.QUARANTINE
        ).count()
        rejected_receipts_count = purchase_receipts.filter(
            quality_status=PurchaseReceipt.QualityStatus.REJECTED
        ).count()

        receipt_items = PurchaseReceiptItem.objects.filter(receipt__order__supplier=partner)
        total_received_qty = receipt_items.aggregate(s=Sum('received_quantity'))['s'] or Decimal('0.0000')
        total_accepted_qty = receipt_items.aggregate(s=Sum('accepted_quantity'))['s'] or Decimal('0.0000')
        total_rejected_qty = receipt_items.aggregate(s=Sum('rejected_quantity'))['s'] or Decimal('0.0000')

        if total_received_qty > Decimal('0'):
            receipt_acceptance_rate = (
                (total_accepted_qty / total_received_qty) * Decimal('100.0')
            ).quantize(Decimal('0.01'))
        elif total_receipts_count > 0 and rejected_receipts_count == 0:
            receipt_acceptance_rate = Decimal('100.00')
        else:
            receipt_acceptance_rate = Decimal('0.00')

        total_oos_count = lab_investigations.count()
        total_deviations_count = quality_events.count()

        # --- TAB 4: MATÉRIAS-PRIMAS HOMOLOGADAS ---
        order_product_ids = set(
            PurchaseOrderItem.objects.filter(order__supplier=partner).values_list(
                'product_id', flat=True
            )
        )
        receipt_product_ids = set(
            PurchaseReceiptItem.objects.filter(receipt__order__supplier=partner).values_list(
                'product_id', flat=True
            )
        )
        all_product_ids = order_product_ids | receipt_product_ids

        homologated_products_raw = (
            Product.objects.filter(id__in=all_product_ids)
            .select_related('unit', 'category')
            .order_by('code')
        )

        homologated_products = []
        for prod in homologated_products_raw:
            p_receipt_items = receipt_items.filter(product=prod)
            p_received = p_receipt_items.aggregate(s=Sum('received_quantity'))['s'] or Decimal('0.0000')
            p_accepted = p_receipt_items.aggregate(s=Sum('accepted_quantity'))['s'] or Decimal('0.0000')
            p_rejected = p_receipt_items.aggregate(s=Sum('rejected_quantity'))['s'] or Decimal('0.0000')
            last_receipt = (
                purchase_receipts.filter(items__product=prod)
                .order_by('-physical_received_at')
                .first()
            )
            has_product_block = QualityBlock.objects.filter(
                product=prod, supplier=partner, status=QualityBlock.Status.ACTIVE
            ).exists()
            homologated_products.append(
                {
                    'product': prod,
                    'total_received': p_received,
                    'total_accepted': p_accepted,
                    'total_rejected': p_rejected,
                    'last_delivery_date': (
                        last_receipt.physical_received_at.date()
                        if last_receipt and last_receipt.physical_received_at
                        else None
                    ),
                    'has_block': has_product_block,
                }
            )

        supplier_quotations = (
            SupplierQuotation.objects.filter(supplier=partner)
            .select_related('rfq', 'currency_ref', 'payment_term_ref', 'delivery_term_ref')
            .order_by('-valid_until', '-created_at')
        )

        # --- TAB 5: SCORECARD & STATUS DE QUALIFICAÇÃO (5 GATES) ---
        # Gate 1: Cadastro e Regularidade Fiscal
        has_tax_document = bool(partner.document and partner.document.strip())
        has_legal_name = bool(partner.legal_name and partner.legal_name.strip())
        has_normalized_location = bool(
            partner.city_ref_id and partner.state_ref_id and partner.zipcode
        )
        gate1_passed = has_tax_document and has_legal_name and has_normalized_location

        # Gate 2: Licenças Sanitárias e AFE/VISA Vigentes
        has_active_event_block = active_supplier_event_blocks.exists()
        gate2_passed = not has_active_event_block and (
            partner.qualification_valid_until is None
            or partner.qualification_valid_until >= timezone.localdate()
        )

        # Gate 3: Auditoria BPF e Avaliação Técnica
        gate3_passed = critical_findings_open == 0 and (
            total_audits_count > 0 or license_events.exists()
        )

        # Gate 4: Homologação de Matérias-Primas e CQ
        gate4_passed = (
            rejected_receipts_count == 0
            or receipt_acceptance_rate >= Decimal('90.00')
            or total_receipts_count == 0
        )

        # Gate 5: Parecer Sanitário e Ausência de Bloqueios QA
        gate5_passed = (
            not active_qa_blocks.exists()
            and not partner.is_blocked
            and partner.is_active
        )

        gates_passed_count = sum(
            [1 if g else 0 for g in [gate1_passed, gate2_passed, gate3_passed, gate4_passed, gate5_passed]]
        )

        # Parecer Geral de Qualificação
        if (
            gates_passed_count == 5
            and partner.qualification_status == BusinessPartner.QualificationStatus.QUALIFIED
            and not has_active_block
        ):
            regulatory_verdict = 'Apto para fornecimento'
            regulatory_verdict_badge = 'bg-success'
            regulatory_verdict_desc = (
                'Fornecedor homologado e qualificado conforme as Boas Práticas de Fabricação (BPF), '
                'com licenças sanitárias vigentes, auditorias conformes e controle de qualidade aprovado.'
            )
        elif has_active_block or partner.is_blocked or active_qa_blocks.exists():
            regulatory_verdict = 'Fornecimento bloqueado sanitariamente'
            regulatory_verdict_badge = 'bg-danger'
            regulatory_verdict_desc = (
                'Fornecedor com bloqueio cautelar ativo emitido pela Garantia da Qualidade (QA) '
                'ou restrição sanitária impeditiva no recebimento.'
            )
        elif is_expired or partner.qualification_status == BusinessPartner.QualificationStatus.EXPIRED:
            regulatory_verdict = 'Qualificação sanitária vencida'
            regulatory_verdict_badge = 'bg-warning'
            regulatory_verdict_desc = (
                'Prazo de qualificação do fornecedor expirado. Requer revalidação cadastral, '
                'nova auditoria BPF ou renovação das licenças sanitárias (AFE/VISA).'
            )
        else:
            regulatory_verdict = 'Qualificação em andamento / Restrito'
            regulatory_verdict_badge = 'bg-info'
            regulatory_verdict_desc = (
                'Fornecedor em processo de homologação ou com pendências documentais parciais. '
                'Fornecimento sujeito a inspeção lote a lote (CQ 100%).'
            )

        context.update(
            {
                'partner': partner,
                'formatted_address': formatted_address,
                'days_until_expiry': days_until_expiry,
                'is_expired': is_expired,
                'has_active_block': has_active_block,
                'available_partner_actions': available_partner_actions,
                # Permissões SoD
                'can_view_cadastral': can_view_cadastral,
                'can_view_events': can_view_events,
                'can_view_audits': can_view_audits,
                'can_view_deliveries': can_view_deliveries,
                'can_view_quality': can_view_quality,
                'can_view_products': can_view_products,
                'can_view_scorecard': can_view_scorecard,
                'can_manage_partner': can_manage_partner,
                'can_manage_events': can_manage_events,
                'can_view_blocks': can_view_blocks,
                # Tab 1
                'qualification_events': qualification_events,
                'license_events': license_events,
                'restriction_events': restriction_events,
                'qa_blocks_history': qa_blocks_history,
                'active_qa_blocks': active_qa_blocks,
                'active_supplier_event_blocks': active_supplier_event_blocks,
                # Tab 2
                'supplier_audits': supplier_audits,
                'supplier_findings': supplier_findings,
                'linked_findings': linked_findings,
                'audit_qualification_events': audit_qualification_events,
                'total_audits_count': total_audits_count,
                'closed_audits_count': closed_audits_count,
                'critical_findings_count': critical_findings_count,
                'critical_findings_open': critical_findings_open,
                'major_findings_count': major_findings_count,
                'minor_findings_count': minor_findings_count,
                'avg_audit_compliance_pct': avg_audit_compliance_pct,
                # Tab 3
                'purchase_orders': purchase_orders[:20],
                'purchase_receipts': purchase_receipts[:20],
                'quality_samples': quality_samples[:20],
                'lab_investigations': lab_investigations[:20],
                'quality_events': quality_events[:20],
                'total_orders_count': total_orders_count,
                'total_receipts_count': total_receipts_count,
                'approved_receipts_count': approved_receipts_count,
                'quarantine_receipts_count': quarantine_receipts_count,
                'rejected_receipts_count': rejected_receipts_count,
                'total_received_qty': total_received_qty,
                'total_accepted_qty': total_accepted_qty,
                'total_rejected_qty': total_rejected_qty,
                'receipt_acceptance_rate': receipt_acceptance_rate,
                'total_oos_count': total_oos_count,
                'total_deviations_count': total_deviations_count,
                # Tab 4
                'homologated_products': homologated_products,
                'supplier_quotations': supplier_quotations[:20],
                # Tab 5
                'gate1_passed': gate1_passed,
                'gate2_passed': gate2_passed,
                'gate3_passed': gate3_passed,
                'gate4_passed': gate4_passed,
                'gate5_passed': gate5_passed,
                'gates_passed_count': gates_passed_count,
                'regulatory_verdict': regulatory_verdict,
                'regulatory_verdict_badge': regulatory_verdict_badge,
                'regulatory_verdict_desc': regulatory_verdict_desc,
            }
        )
        return context
