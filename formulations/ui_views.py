from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.generic import TemplateView

from base.ui.views import ResourceContextMixin, ResourceCreateView
from formulations.models import MasterFormula
from formulations.reuse import (
    VERSION_CONFLICT_MESSAGE,
    build_master_formula_reuse_form,
    component_reuse_initial,
    is_formula_version_conflict,
    master_formula_reuse_initial,
)
from masters.models import Product
from procurement.models import (
    PurchaseOrder,
    PurchaseReceipt,
    QuotationRequest,
    SupplierQuotation,
)


class MasterFormulaReuseView(ResourceCreateView):
    source = None

    def dispatch(self, request, *args, **kwargs):
        resource = self.get_resource()
        if resource.model is not MasterFormula:
            raise Http404('Reaproveitamento disponível somente para fórmulas mestras.')
        if not resource.can_reuse(request.user):
            raise PermissionDenied('Usuário sem permissão para reaproveitar esta fórmula.')
        self.get_source()
        return super().dispatch(request, *args, **kwargs)

    def get_source(self):
        if self.source is None:
            try:
                self.source = (
                    self.get_queryset()
                    .select_related('product', 'batch_unit')
                    .prefetch_related('components')
                    .get(pk=self.kwargs['pk'])
                )
            except MasterFormula.DoesNotExist as exc:
                raise Http404('Fórmula de origem não encontrada.') from exc
        return self.source

    def get_form_class(self):
        return build_master_formula_reuse_form(self.get_resource())

    def get_form_initial(self):
        return master_formula_reuse_initial(self.get_source())

    def get_inline_initial(self):
        return {'components': component_reuse_initial(self.get_source())}

    def prepare_object_for_save(self, obj, *, action):
        del action
        Product.objects.select_for_update().only('pk').get(pk=obj.product_id)
        obj.code = ''
        obj.status = MasterFormula.Status.DRAFT
        obj.copied_from = self.get_source()
        obj.approved_by = None
        obj.approved_at = None
        return obj

    def handle_integrity_error(self, form, error):
        if not is_formula_version_conflict(error):
            return False
        form.add_error('version', VERSION_CONFLICT_MESSAGE)
        return True

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reuse_source'] = self.get_source()
        return context


class MasterFormulaCockpitView(LoginRequiredMixin, ResourceContextMixin, TemplateView):
    template_name = 'app/master_formula_cockpit.html'

    def dispatch(self, request, *args, **kwargs):
        if self.get_resource().model is not MasterFormula:
            raise Http404('Cockpit disponível apenas para fórmulas mestras.')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        formula = self.get_object()
        components = list(
            formula.components.select_related('material', 'unit')
            .filter(is_active=True)
            .order_by('line_number')
        )
        material_ids = [comp.material_id for comp in components]

        quotations = []
        active_rfqs_count = 0
        can_view_rfqs = self.request.user.has_perm('procurement.view_quotationrequest')
        if can_view_rfqs and material_ids:
            quotations = list(
                SupplierQuotation.objects.filter(
                    rfq__requisition__items__product_id__in=material_ids
                )
                .select_related('rfq', 'supplier', 'currency_ref')
                .distinct()
                .order_by('-created_at')[:20]
            )
            active_rfqs_count = (
                QuotationRequest.objects.filter(
                    requisition__items__product_id__in=material_ids,
                    status__in=[QuotationRequest.Status.SENT, QuotationRequest.Status.QUOTED],
                )
                .distinct()
                .count()
            )

        purchase_orders = []
        open_orders_count = 0
        can_view_orders = self.request.user.has_perm('procurement.view_purchaseorder')
        if can_view_orders and material_ids:
            purchase_orders = list(
                PurchaseOrder.objects.filter(items__product_id__in=material_ids)
                .select_related('supplier', 'currency_ref')
                .distinct()
                .order_by('-created_at')[:20]
            )
            open_orders_count = (
                PurchaseOrder.objects.filter(
                    items__product_id__in=material_ids,
                    status__in=[
                        PurchaseOrder.Status.APPROVED,
                        PurchaseOrder.Status.SENT,
                        PurchaseOrder.Status.PARTIALLY_RECEIVED,
                    ],
                )
                .distinct()
                .count()
            )

        receipts = []
        pending_receipts_count = 0
        can_view_receipts = self.request.user.has_perm('procurement.view_purchasereceipt')
        if can_view_receipts and material_ids:
            receipts = list(
                PurchaseReceipt.objects.filter(items__product_id__in=material_ids)
                .select_related('order', 'order__supplier')
                .prefetch_related('items__product', 'items__unit')
                .distinct()
                .order_by('-created_at')[:20]
            )
            pending_receipts_count = (
                PurchaseReceipt.objects.filter(
                    items__product_id__in=material_ids,
                    status__in=[
                        PurchaseReceipt.Status.DRAFT,
                        PurchaseReceipt.Status.RECEIVED,
                    ],
                )
                .distinct()
                .count()
            )

        context.update(
            {
                'formula': formula,
                'components': components,
                'quotations': quotations,
                'active_rfqs_count': active_rfqs_count,
                'can_view_rfqs': can_view_rfqs,
                'purchase_orders': purchase_orders,
                'open_orders_count': open_orders_count,
                'can_view_orders': can_view_orders,
                'receipts': receipts,
                'pending_receipts_count': pending_receipts_count,
                'can_view_receipts': can_view_receipts,
            }
        )
        return context
