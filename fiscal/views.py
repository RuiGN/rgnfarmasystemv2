from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from fiscal.models import (
    FiscalAuditTrail,
    FiscalBookEntry,
    FiscalCompany,
    FiscalDocument,
    FiscalDocumentItem,
    FiscalEmailDelivery,
    FiscalEmissionEvent,
    FiscalMunicipality,
    FiscalNCM,
    FiscalObligation,
    FiscalOperationCode,
    FiscalTax,
    FiscalUnit,
    TaxAssessmentPeriod,
    TaxRule,
    TaxSituation,
)
from fiscal.serializers import (
    FiscalAuditTrailSerializer,
    FiscalBookEntrySerializer,
    FiscalCompanySerializer,
    FiscalDocumentItemSerializer,
    FiscalDocumentSerializer,
    FiscalEmailDeliverySerializer,
    FiscalEmissionEventSerializer,
    FiscalMunicipalitySerializer,
    FiscalNCMSerializer,
    FiscalObligationSerializer,
    FiscalOperationCodeSerializer,
    FiscalTaxSerializer,
    FiscalUnitSerializer,
    TaxAssessmentPeriodSerializer,
    TaxRuleSerializer,
    TaxSituationSerializer,
)
from fiscal.services import FiscalEmissionService
from base.permissions import SingleInstanceDjangoModelPermissions


class SingleInstanceFiscalViewSet(viewsets.ModelViewSet):
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


class SingleInstanceFiscalReadOnlyViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = (SingleInstanceDjangoModelPermissions,)
    filter_backends = (DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter)
    ordering: tuple[str, ...] = ('-created_at',)

    def get_queryset(self):
        return self.queryset.all()


class FiscalCompanyViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalCompany.objects.select_related('city_ref', 'state_ref')
    serializer_class = FiscalCompanySerializer
    filterset_fields = ('tax_regime', 'is_active', 'state_ref', 'city_ref')
    search_fields = (
        'legal_name',
        'document',
        'state_registration',
        'municipal_registration',
        'city_ref__name',
        'state_ref__name',
        'state_ref__name',
    )
    ordering = ('legal_name',)


class FiscalMunicipalityViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalMunicipality.objects.select_related('city_ref', 'state_ref')
    serializer_class = FiscalMunicipalitySerializer
    filterset_fields = ('state_ref', 'city_ref', 'is_active')
    search_fields = ('ibge_code', 'name', 'city_ref__name', 'state_ref__name')
    ordering = ('state_ref__name', 'name')


class FiscalUnitViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalUnit.objects.all()
    serializer_class = FiscalUnitSerializer
    filterset_fields = ('is_active',)
    search_fields = ('code', 'description')
    ordering = ('code',)


class FiscalNCMViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalNCM.objects.all()
    serializer_class = FiscalNCMSerializer
    filterset_fields = ('is_active', 'cest')
    search_fields = ('code', 'description', 'cest')
    ordering = ('code',)


class FiscalOperationCodeViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalOperationCode.objects.all()
    serializer_class = FiscalOperationCodeSerializer
    filterset_fields = ('direction', 'is_active')
    search_fields = ('code', 'description')
    ordering = ('code',)


class TaxSituationViewSet(SingleInstanceFiscalViewSet):
    queryset = TaxSituation.objects.all()
    serializer_class = TaxSituationSerializer
    filterset_fields = ('tax_kind', 'regime_kind', 'is_active')
    search_fields = ('code', 'description')
    ordering = ('tax_kind', 'regime_kind', 'code')


class TaxRuleViewSet(SingleInstanceFiscalViewSet):
    queryset = TaxRule.objects.select_related(
        'company', 'product', 'partner', 'ncm', 'cfop', 'tax_situation', 'approved_by'
    )
    serializer_class = TaxRuleSerializer
    filterset_fields = ('tax_kind', 'status', 'ncm', 'cfop', 'tax_situation', 'effective_from')
    search_fields = ('name', 'ncm__code', 'cfop__code', 'tax_situation__code')
    ordering = ('tax_kind', 'name')

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._domain_action_response(lambda rule: rule.approve(user=request.user))


class FiscalDocumentViewSet(SingleInstanceFiscalViewSet):
    action_permission_map = {
        'send_email': (
            'fiscal.change_fiscaldocument',
            'fiscal.add_fiscalemaildelivery',
        ),
    }
    queryset = FiscalDocument.objects.select_related(
        'company',
        'partner',
        'purchase_order',
        'purchase_receipt',
        'financial_title',
        'reviewed_by',
        'approved_by',
        'posted_by',
    )
    serializer_class = FiscalDocumentSerializer
    filterset_fields = (
        'document_type',
        'operation_type',
        'status',
        'emission_status',
        'environment',
        'partner',
        'issue_date',
    )
    search_fields = ('number', 'series', 'access_key', 'partner__legal_name')
    ordering = ('-issue_date', 'number')

    def _ensure_document_permission(self, action):
        permission = f'fiscal.{action}_fiscaldocument'
        if not self.request.user.has_perm(permission):
            raise PermissionDenied(f'Usuário sem permissão {permission}.')

    @action(detail=True, methods=['post'])
    def recalculate(self, request, pk=None):
        return self._domain_action_response(lambda document: document.recalculate_totals())

    @action(detail=True, methods=['post'])
    def submit_for_review(self, request, pk=None):
        return self._domain_action_response(lambda document: document.submit_for_review())

    @action(detail=True, methods=['post'])
    def review(self, request, pk=None):
        return self._domain_action_response(lambda document: document.review(user=request.user))

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        return self._domain_action_response(lambda document: document.approve(user=request.user))

    @action(detail=True, methods=['post'])
    def post_entry(self, request, pk=None):
        return self._domain_action_response(lambda document: document.post_entry(user=request.user))

    @action(detail=True, methods=['post'])
    def create_financial_title(self, request, pk=None):
        document = self.get_object()
        category_id = request.data.get('category')
        due_date = request.data.get('due_date')
        if not due_date:
            return Response(
                {'due_date': 'Informe o vencimento.'}, status=status.HTTP_400_BAD_REQUEST
            )
        from finance.models import FinancialCategory

        category = FinancialCategory.objects.filter(pk=category_id).first()
        if category is None:
            return Response(
                {'category': 'Categoria financeira não encontrada.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            document.create_financial_title(category=category, due_date=due_date)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        serializer = self.get_serializer(document)
        return Response(serializer.data)

    @action(detail=True, methods=['post'])
    def issue(self, request, pk=None):
        self._ensure_document_permission('issue')
        document = self.get_object()
        try:
            FiscalEmissionService().issue(document, user=request.user)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=['post'])
    def check_status(self, request, pk=None):
        document = self.get_object()
        try:
            FiscalEmissionService().check_status(document, user=request.user)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        self._ensure_document_permission('cancel')
        document = self.get_object()
        try:
            FiscalEmissionService().cancel(
                document, request.data.get('justification') or '', user=request.user
            )
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        document.refresh_from_db()
        return Response(self.get_serializer(document).data)

    @action(detail=True, methods=['post'])
    def send_email(self, request, pk=None):
        self._ensure_document_permission('send_email')
        document = self.get_object()
        try:
            delivery = FiscalEmissionService().schedule_email_delivery(document, user=request.user)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            FiscalEmailDeliverySerializer(delivery, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=['get'])
    def xml(self, request, pk=None):
        self._ensure_document_permission('download')
        return self._artifact_response('.xml', 'application/xml')

    @action(detail=True, methods=['get'])
    def danfe(self, request, pk=None):
        self._ensure_document_permission('download')
        return self._artifact_response('.pdf', 'application/pdf')

    def _artifact_response(self, suffix, mime_type):
        document = self.get_object()
        protected_file = (
            document.protected_files.filter(file_name__endswith=suffix)
            .order_by('-created_at')
            .first()
        )
        if protected_file is None:
            return Response(
                {'artifact': 'Arquivo fiscal não encontrado.'}, status=status.HTTP_404_NOT_FOUND
            )
        try:
            content = protected_file.read_encrypted_content(self.request.user)
        except DjangoValidationError as error:
            return Response(error.message_dict, status=status.HTTP_403_FORBIDDEN)
        response = HttpResponse(content, content_type=protected_file.mime_type or mime_type)
        response['Content-Disposition'] = f'attachment; filename="{protected_file.file_name}"'
        return response


class FiscalEmissionEventViewSet(SingleInstanceFiscalReadOnlyViewSet):
    queryset = FiscalEmissionEvent.objects.select_related(
        'document', 'actor', 'xml_file', 'danfe_file'
    )
    serializer_class = FiscalEmissionEventSerializer
    filterset_fields = ('document', 'event_type', 'provider', 'status', 'actor')
    search_fields = ('document__number', 'access_key', 'protocol', 'message')
    ordering = ('-created_at',)


class FiscalEmailDeliveryViewSet(SingleInstanceFiscalReadOnlyViewSet):
    queryset = FiscalEmailDelivery.objects.select_related(
        'document', 'requested_by', 'xml_file', 'danfe_file'
    )
    serializer_class = FiscalEmailDeliverySerializer
    filterset_fields = ('document', 'status', 'recipient_email', 'scheduled_at', 'sent_at')
    search_fields = ('document__number', 'recipient_email', 'subject', 'last_error')
    ordering = ('-scheduled_at', '-created_at')


class FiscalDocumentItemViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalDocumentItem.objects.select_related(
        'document', 'product', 'fiscal_unit', 'ncm', 'cfop', 'tax_situation'
    )
    serializer_class = FiscalDocumentItemSerializer
    filterset_fields = ('document', 'product', 'ncm', 'cfop')
    search_fields = (
        'document__number',
        'product__code',
        'product__description',
        'ncm__code',
        'cfop__code',
    )
    ordering = ('document__number', 'line_number')


class FiscalTaxViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalTax.objects.select_related('document', 'item', 'tax_rule')
    serializer_class = FiscalTaxSerializer
    filterset_fields = ('document', 'item', 'tax_kind', 'is_retained')
    search_fields = ('document__number', 'tax_kind')
    ordering = ('document__number', 'tax_kind')

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        return self._domain_action_response(lambda tax: tax.calculate())


class TaxAssessmentPeriodViewSet(SingleInstanceFiscalViewSet):
    queryset = TaxAssessmentPeriod.objects.select_related('closed_by')
    serializer_class = TaxAssessmentPeriodSerializer
    filterset_fields = ('period_year', 'period_month', 'tax_kind', 'status')
    search_fields = ('notes',)
    ordering = ('-period_year', '-period_month', 'tax_kind')

    @action(detail=True, methods=['post'])
    def calculate(self, request, pk=None):
        return self._domain_action_response(lambda assessment: assessment.calculate())

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        return self._domain_action_response(lambda assessment: assessment.close(user=request.user))


class FiscalBookEntryViewSet(SingleInstanceFiscalViewSet):
    action_permission_map = {'from_document': ('fiscal.add_fiscalbookentry',)}
    queryset = FiscalBookEntry.objects.select_related('document')
    serializer_class = FiscalBookEntrySerializer
    filterset_fields = ('book_type', 'document', 'entry_date')
    search_fields = ('document__number', 'notes')
    ordering = ('-entry_date', 'document__number')

    @action(detail=False, methods=['post'])
    def from_document(self, request):
        document_id = request.data.get('document')
        document = FiscalDocument.objects.filter(pk=document_id).first()
        if document is None:
            return Response(
                {'document': 'Documento fiscal não encontrado.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        entry = FiscalBookEntry.create_from_document(document)
        serializer = self.get_serializer(entry)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class FiscalObligationViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalObligation.objects.select_related('submitted_by')
    serializer_class = FiscalObligationSerializer
    filterset_fields = ('obligation_type', 'period_year', 'period_month', 'status', 'due_date')
    search_fields = ('protocol_number', 'notes')
    ordering = ('due_date', 'obligation_type')

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        protocol_number = request.data.get('protocol_number', '')
        return self._domain_action_response(
            lambda obligation: obligation.submit(user=request.user, protocol_number=protocol_number)
        )


class FiscalAuditTrailViewSet(SingleInstanceFiscalViewSet):
    queryset = FiscalAuditTrail.objects.select_related('actor')
    serializer_class = FiscalAuditTrailSerializer
    http_method_names = ('get', 'head', 'options')
    filterset_fields = ('entity_name', 'object_id', 'action', 'actor')
    search_fields = ('entity_name', 'object_id', 'action')
    ordering = ('-created_at',)
