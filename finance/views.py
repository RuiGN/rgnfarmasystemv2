from django.core.exceptions import ValidationError as DjangoValidationError
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from finance.models import (
    CashFlowEntry,
    ChartOfAccount,
    FinancialAccount,
    FinancialCategory,
    FinancialPeriodClosing,
    FinancialSettlement,
    FinancialTitle,
)
from finance.serializers import (
    CashFlowEntrySerializer,
    ChartOfAccountSerializer,
    FinancialAccountSerializer,
    FinancialCategorySerializer,
    FinancialPeriodClosingSerializer,
    FinancialSettlementSerializer,
    FinancialTitleSerializer,
)
from base.permissions import SingleInstanceDjangoModelPermissions


class SingleInstanceFinanceViewSet(viewsets.ModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()

    def perform_create(self, serializer):
        serializer.save()

    def _domain_action_response(self, callback):
        obj = self.get_object()
        try:
            callback(obj)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


class ChartOfAccountViewSet(SingleInstanceFinanceViewSet):
    queryset = ChartOfAccount.objects.select_related('parent')
    serializer_class = ChartOfAccountSerializer
    filterset_fields = ('account_type', 'is_active', 'parent')
    search_fields = ('code', 'name')
    ordering = ('code',)


class FinancialCategoryViewSet(SingleInstanceFinanceViewSet):
    queryset = FinancialCategory.objects.select_related('chart_account')
    serializer_class = FinancialCategorySerializer
    filterset_fields = ('category_type', 'chart_account', 'is_active')
    search_fields = ('code', 'name', 'chart_account__code', 'chart_account__name')
    ordering = ('category_type', 'code')


class FinancialAccountViewSet(SingleInstanceFinanceViewSet):
    queryset = FinancialAccount.objects.all()
    serializer_class = FinancialAccountSerializer
    filterset_fields = ('account_type', 'is_active')
    search_fields = ('code', 'name', 'bank_name', 'agency_number', 'account_number')
    ordering = ('code',)


class FinancialTitleViewSet(SingleInstanceFinanceViewSet):
    queryset = FinancialTitle.objects.select_related(
        'partner',
        'category',
        'financial_account',
        'purchase_order',
        'approved_by',
    )
    serializer_class = FinancialTitleSerializer
    filterset_fields = ('title_type', 'source_type', 'partner', 'category', 'status', 'due_date')
    search_fields = (
        'title_number',
        'partner__legal_name',
        'fiscal_document_number',
        'contract_reference',
        'sale_reference',
    )
    ordering = ('due_date', 'title_number')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._domain_action_response(lambda title: title.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        return self._domain_action_response(lambda title: title.cancel())

    @action(detail=True, methods=['post'])
    def mark_overdue(self, request, pk=None):
        return self._domain_action_response(lambda title: title.mark_overdue())


class FinancialSettlementViewSet(SingleInstanceFinanceViewSet):
    http_method_names = ('get', 'post', 'put', 'patch', 'head', 'options')
    queryset = FinancialSettlement.objects.select_related(
        'title', 'financial_account', 'reconciled_by', 'reversed_by'
    )
    serializer_class = FinancialSettlementSerializer
    filterset_fields = ('title', 'financial_account', 'settlement_date', 'method', 'status')
    search_fields = ('title__title_number', 'reference', 'notes')
    ordering = ('-settlement_date', '-created_at')

    def perform_create(self, serializer):
        serializer.save()

    @action(detail=True, methods=['post'])
    def reconcile(self, request, pk=None):
        return self._domain_action_response(
            lambda settlement: settlement.reconcile(user=request.user)
        )

    @action(detail=True, methods=['post'])
    def reverse(self, request, pk=None):
        reason = request.data.get('reversal_reason', '')
        return self._domain_action_response(
            lambda settlement: settlement.reverse(reason=reason, user=request.user)
        )


class CashFlowEntryViewSet(SingleInstanceFinanceViewSet):
    queryset = CashFlowEntry.objects.select_related('title', 'settlement', 'financial_account')
    serializer_class = CashFlowEntrySerializer
    filterset_fields = (
        'flow_type',
        'direction',
        'title',
        'financial_account',
        'cash_date',
        'status',
    )
    search_fields = ('title__title_number', 'description')
    ordering = ('cash_date', 'direction')

    @action(detail=False, methods=['post'])
    def from_title(self, request):
        title_id = request.data.get('title')
        title = FinancialTitle.objects.filter(pk=title_id).first()
        if title is None:
            return Response(
                {'title': 'Título não encontrado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = CashFlowEntry.create_from_title(title)
        serializer = self.get_serializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def from_settlement(self, request):
        settlement_id = request.data.get('settlement')
        settlement = FinancialSettlement.objects.filter(pk=settlement_id).first()
        if settlement is None:
            return Response(
                {'settlement': 'Baixa não encontrada.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = CashFlowEntry.create_from_settlement(settlement)
        serializer = self.get_serializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FinancialPeriodClosingViewSet(SingleInstanceFinanceViewSet):
    queryset = FinancialPeriodClosing.objects.select_related('closed_by')
    serializer_class = FinancialPeriodClosingSerializer
    filterset_fields = ('period_year', 'period_month', 'status')
    search_fields = ('validation_notes',)
    ordering = ('-period_year', '-period_month')

    @action(detail=True, methods=['post'])
    def validate_period(self, request, pk=None):
        notes = request.data.get('validation_notes', '')
        return self._domain_action_response(lambda closing: closing.validate_period(notes=notes))

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        return self._domain_action_response(lambda closing: closing.close(user=request.user))

    @action(detail=True, methods=['post'])
    def reopen(self, request, pk=None):
        reason = request.data.get('validation_notes', '')
        return self._domain_action_response(
            lambda closing: closing.reopen(reason=reason, user=request.user)
        )
