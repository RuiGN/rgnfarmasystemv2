from decimal import Decimal

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.http import Http404
from django.views.generic import TemplateView

from base.ui.actions.context import available_actions
from base.ui.views import ResourceContextMixin
from crm.models import CustomerProfile, SalesOrder, SalesOrderItem
from finance.models import FinancialSettlement, FinancialTitle
from fiscal.models import FiscalDocument
from inventory.models import StockBalance, StockMovement


class SalesOrderCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    """Cockpit unificado Order-to-Cash (O2C) do pedido de venda (Visão 360°)."""

    template_name = 'app/sales_order_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if self.get_resource().model is not SalesOrder:
            raise Http404('Cockpit disponível apenas para pedidos de venda.')
        if not request.user.has_perm('crm.view_salesorder'):
            raise PermissionDenied(
                'Você não possui permissão para visualizar o cockpit do pedido de venda.'
            )
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        order = self.get_object()
        user = self.request.user
        resource = self.get_resource()

        # Segregação de Deveres (SoD) por aba
        can_view_items = user.has_perm('crm.view_salesorderitem')
        can_view_credit = user.has_perm('crm.view_customerprofile')
        can_view_inventory = user.has_perm('inventory.view_stockbalance')
        can_view_movements = user.has_perm('inventory.view_stockmovement')
        can_view_fiscal = user.has_perm('fiscal.view_fiscaldocument')
        can_view_finance = user.has_perm('finance.view_financialtitle')
        can_view_settlements = user.has_perm('finance.view_financialsettlement')
        can_manage_order = user.has_perm('crm.change_salesorder')

        available_order_actions = available_actions(self.request, resource, order)

        # Itens Comerciais
        order_items = list(
            order.items.select_related('product', 'product__unit').order_by('product__code')
        )
        items = order_items if can_view_items else []

        # Aba 2: Perfil Comercial e Análise de Crédito
        profile = None
        total_open_exposure = Decimal('0.0000')
        available_credit = Decimal('0.0000')
        projected_credit = Decimal('0.0000')
        credit_status = 'ok'  # 'ok', 'hold', 'exceeded'

        if can_view_credit:
            profile = CustomerProfile.objects.filter(
                customer=order.customer, is_active=True
            ).select_related('group', 'default_channel', 'representative').first()

            if profile:
                open_titles = FinancialTitle.objects.filter(
                    partner=order.customer,
                    title_type=FinancialTitle.TitleType.RECEIVABLE,
                ).exclude(
                    status__in=[
                        FinancialTitle.Status.SETTLED,
                        FinancialTitle.Status.CANCELLED,
                        FinancialTitle.Status.REVERSED,
                    ]
                )
                total_open_exposure = (
                    open_titles.aggregate(total=Sum('open_amount'))['total'] or Decimal('0.0000')
                )

                if profile.credit_limit > 0:
                    available_credit = profile.credit_limit - total_open_exposure
                    if order.status == SalesOrder.Status.DRAFT:
                        projected_credit = available_credit - order.total_amount
                    else:
                        projected_credit = available_credit
                else:
                    available_credit = Decimal('0.0000')
                    projected_credit = Decimal('0.0000')

                if profile.credit_hold or profile.regulatory_hold:
                    credit_status = 'hold'
                elif profile.credit_limit > 0 and available_credit < 0:
                    credit_status = 'exceeded'
                else:
                    credit_status = 'ok'

        # Aba 3: Estoque, Saldos e Separação (WMS)
        stock_items_summary = []
        order_movements = []
        all_items_in_stock = True if order_items else False

        if can_view_inventory:
            for it in order_items:
                available_qty = order._available_stock_for(it.product)
                is_sufficient = available_qty >= it.quantity
                if not is_sufficient:
                    all_items_in_stock = False

                balances = list(
                    StockBalance.objects.filter(product=it.product)
                    .select_related('lot', 'warehouse', 'location', 'unit')
                    .order_by('-quantity')
                )

                stock_items_summary.append(
                    {
                        'item': it,
                        'product': it.product,
                        'ordered_quantity': it.quantity,
                        'available_quantity': available_qty,
                        'is_sufficient': is_sufficient,
                        'balances': balances,
                    }
                )

            if can_view_movements:
                order_movements = list(
                    StockMovement.objects.filter(
                        Q(document_reference=order.order_number)
                        | Q(reason__icontains=order.order_number)
                    )
                    .select_related(
                        'product',
                        'lot',
                        'from_warehouse',
                        'from_location',
                        'to_warehouse',
                        'to_location',
                        'unit',
                        'created_by',
                    )
                    .order_by('-movement_date', '-created_at')[:20]
                )

        # Aba 4: Faturamento e Notas Fiscais (NF-e)
        fiscal_documents = []
        if can_view_fiscal:
            fiscal_documents = list(
                FiscalDocument.objects.filter(
                    partner=order.customer,
                    document_type=FiscalDocument.DocumentType.OUTBOUND,
                )
                .filter(
                    Q(notes__icontains=order.order_number)
                    | Q(financial_title__sale_reference=order.order_number)
                )
                .distinct()
                .select_related('company', 'financial_title', 'reviewed_by', 'approved_by')
                .prefetch_related('items', 'taxes')
                .order_by('-issue_date')
            )

            # Fallback por produtos caso a referência textual não tenha sido anotada
            if not fiscal_documents and items:
                product_ids = [it.product_id for it in items]
                fiscal_documents = list(
                    FiscalDocument.objects.filter(
                        partner=order.customer,
                        document_type=FiscalDocument.DocumentType.OUTBOUND,
                        items__product_id__in=product_ids,
                    )
                    .distinct()
                    .select_related('company', 'financial_title', 'reviewed_by', 'approved_by')
                    .prefetch_related('items', 'taxes')
                    .order_by('-issue_date')[:10]
                )

        # Aba 5: Títulos Financeiros e Baixas
        financial_titles = []
        finance_summary = {
            'total_billed': Decimal('0.0000'),
            'total_paid': Decimal('0.0000'),
            'total_open': Decimal('0.0000'),
            'settlement_percentage': 0,
        }
        all_settlements = []

        if can_view_finance:
            financial_titles = list(
                FinancialTitle.objects.filter(
                    partner=order.customer,
                    sale_reference=order.order_number,
                )
                .select_related('category', 'financial_account', 'approved_by')
                .prefetch_related('settlements__financial_account', 'settlements__reconciled_by')
                .order_by('due_date')
            )

            # Fallback via número das notas fiscais associadas
            if not financial_titles and fiscal_documents:
                doc_numbers = [d.number for d in fiscal_documents if d.number]
                if doc_numbers:
                    financial_titles = list(
                        FinancialTitle.objects.filter(
                            partner=order.customer,
                            fiscal_document_number__in=doc_numbers,
                        )
                        .select_related('category', 'financial_account', 'approved_by')
                        .prefetch_related(
                            'settlements__financial_account', 'settlements__reconciled_by'
                        )
                        .order_by('due_date')
                    )

            if financial_titles:
                total_billed = sum((t.original_amount for t in financial_titles), Decimal('0.0000'))
                total_paid = sum((t.paid_amount for t in financial_titles), Decimal('0.0000'))
                total_open = sum((t.open_amount for t in financial_titles), Decimal('0.0000'))
                finance_summary['total_billed'] = total_billed
                finance_summary['total_paid'] = total_paid
                finance_summary['total_open'] = total_open

                if total_billed > 0:
                    finance_summary['settlement_percentage'] = int((total_paid / total_billed) * 100)

                if can_view_settlements:
                    for t in financial_titles:
                        all_settlements.extend(list(t.settlements.all()))

        # Gates de Prontidão Order-to-Cash (O2C)
        has_approved_order = order.status in {
            SalesOrder.Status.APPROVED,
            SalesOrder.Status.FULFILLED,
        }
        has_credit_cleared = bool(
            profile
            and not profile.credit_hold
            and not profile.regulatory_hold
            and (profile.credit_limit == Decimal('0.0000') or projected_credit >= 0)
        )
        has_stock_ready = bool(items and all_items_in_stock)
        has_invoiced = bool(
            fiscal_documents
            and any(
                d.emission_status == FiscalDocument.EmissionStatus.AUTHORIZED
                for d in fiscal_documents
            )
        )
        has_settled = bool(
            financial_titles
            and all(t.status == FinancialTitle.Status.SETTLED for t in financial_titles)
        )

        o2c_gates = [
            {
                'step': 1,
                'title': 'Validação Comercial do Pedido',
                'passed': has_approved_order,
                'detail': (
                    'Pedido aprovado comercialmente'
                    if has_approved_order
                    else 'Pendente de aprovação comercial'
                ),
                'icon': 'feather-file-text',
            },
            {
                'step': 2,
                'title': 'Análise de Crédito e Risco',
                'passed': has_credit_cleared,
                'detail': (
                    'Crédito e limites aprovados'
                    if has_credit_cleared
                    else 'Bloqueio de crédito ou limite excedido'
                ),
                'icon': 'feather-credit-card',
            },
            {
                'step': 3,
                'title': 'Disponibilidade de Estoque (WMS)',
                'passed': has_stock_ready,
                'detail': (
                    'Saldo suficiente para todos os itens'
                    if has_stock_ready
                    else 'Estoque aprovado insuficiente para expedição'
                ),
                'icon': 'feather-box',
            },
            {
                'step': 4,
                'title': 'Faturamento Fiscal (NF-e)',
                'passed': has_invoiced,
                'detail': (
                    'NF-e emitida e autorizada na SEFAZ'
                    if has_invoiced
                    else 'Faturamento fiscal pendente'
                ),
                'icon': 'feather-file-check',
            },
            {
                'step': 5,
                'title': 'Liquidação Financeira',
                'passed': has_settled,
                'detail': (
                    'Títulos financeiros 100% liquidados'
                    if has_settled
                    else (
                        f"{finance_summary['settlement_percentage']}% liquidado"
                        if financial_titles
                        else 'Aguardando faturamento/títulos'
                    )
                ),
                'icon': 'feather-dollar-sign',
            },
        ]

        context.update(
            {
                'order': order,
                'customer': order.customer,
                'available_order_actions': available_order_actions,
                # Permissões SoD
                'can_view_items': can_view_items,
                'can_view_credit': can_view_credit,
                'can_view_inventory': can_view_inventory,
                'can_view_movements': can_view_movements,
                'can_view_fiscal': can_view_fiscal,
                'can_view_finance': can_view_finance,
                'can_view_settlements': can_view_settlements,
                'can_manage_order': can_manage_order,
                # Aba 1
                'items': items,
                # Aba 2
                'profile': profile,
                'total_open_exposure': total_open_exposure,
                'available_credit': available_credit,
                'projected_credit': projected_credit,
                'credit_status': credit_status,
                # Aba 3
                'stock_items_summary': stock_items_summary,
                'order_movements': order_movements,
                'all_items_in_stock': all_items_in_stock,
                # Aba 4
                'fiscal_documents': fiscal_documents,
                # Aba 5
                'financial_titles': financial_titles,
                'finance_summary': finance_summary,
                'all_settlements': all_settlements,
                # Gates O2C
                'o2c_gates': o2c_gates,
            }
        )
        return context
