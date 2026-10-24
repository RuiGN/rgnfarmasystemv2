from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from auxiliary.models import City, StateProvince
from crm.models import CustomerComplaint, SalesOrder
from documents.models import ControlledDocument
from fiscal.models import FiscalCompany, FiscalDocument
from inventory.models import StockLot, StockQualityStatus
from masters.models import BusinessPartner, Product, UnitOfMeasure
from quality.models import QualitySample


User = get_user_model()


def create_recalls_context(owner, suffix='001'):
    state = StateProvince.objects.create(
        name=f'Pernambuco Recall {suffix}',
    )
    city = City.objects.create(
        name='Recife',
        state=state,
    )
    unit = UnitOfMeasure.objects.create(code=f'UN-REC-{suffix}', name='Unidade', symbol='un')
    product = Product.objects.create(
        code=f'REC-PROD-{suffix}',
        description=f'Produto Recall {suffix}',
        item_type=Product.ItemType.FINISHED_PRODUCT,
        unit=unit,
        status=Product.Status.APPROVED,
    )
    lot = StockLot.objects.create(
        product=product,
        lot_number=f'REC-LOTE-{suffix}',
        quality_status=StockQualityStatus.APPROVED,
        expiry_date=timezone.localdate() + timedelta(days=365),
    )
    customer = BusinessPartner.objects.create(
        code=f'CLI-REC-{suffix}',
        legal_name=f'Cliente Recall {suffix}',
        partner_type=BusinessPartner.PartnerType.CUSTOMER,
        qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
        qualification_valid_until=timezone.localdate() + timedelta(days=365),
    )
    sales_order = SalesOrder.objects.create(
        customer=customer,
        requested_delivery_date=timezone.localdate() + timedelta(days=7),
        payment_terms_days=30,
        status=SalesOrder.Status.APPROVED,
        approved_by=owner,
        approved_at=timezone.now(),
    )
    fiscal_company = FiscalCompany.objects.create(
        legal_name=f'RGN Farma {suffix}',
        document=f'00000000000{suffix}',
        tax_regime=FiscalCompany.TaxRegime.LUCRO_REAL,
        state_ref=state,
        city_ref=city,
    )
    fiscal_document = FiscalDocument.objects.create(
        company=fiscal_company,
        partner=customer,
        document_type=FiscalDocument.DocumentType.OUTBOUND,
        operation_type=FiscalDocument.OperationType.SALE,
        number=f'NF-REC-{suffix}',
        series='1',
        issue_date=timezone.localdate() - timedelta(days=10),
        operation_date=timezone.localdate() - timedelta(days=10),
        status=FiscalDocument.Status.POSTED,
        total_products=Decimal('1000.0000'),
        total_amount=Decimal('1000.0000'),
        posted_by=owner,
        posted_at=timezone.now(),
    )
    crm_complaint = CustomerComplaint.objects.create(
        customer=customer,
        product=product,
        stock_lot=lot,
        sales_order=sales_order,
        fiscal_document=fiscal_document,
        severity=CustomerComplaint.Severity.HIGH,
    )
    sample = QualitySample.objects.create(
        sample_type=QualitySample.SampleType.COMPLAINT,
        product=product,
        stock_lot=lot,
        customer_complaint=crm_complaint,
        quantity=Decimal('1.0000'),
        unit=unit,
    )
    document = ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.REPORT,
        code=f'REC-DOC-{suffix}',
        title=f'Documento Recall {suffix}',
        area='Reclamações e Recolhimento',
        version='1.0',
        effective_from=timezone.localdate(),
        owner=owner,
        content='Documento técnico para rastreabilidade de recolhimento.',
        change_summary='Emissão inicial.',
    )
    return product, lot, customer, sales_order, fiscal_document, crm_complaint, sample, document


class RecallsModelTests(TestCase):
    def test_post_market_complaint_return_and_recall_workflow_blocks_incomplete_closure(self):
        from recalls.models import (
            MarketComplaint,
            ProductReturn,
            RecallCampaign,
            RecallCommunication,
            RecallEffectivenessReport,
            RecallImpactedCustomer,
        )

        owner = User.objects.create_user(
            username='rec.owner@example.com',
            email='rec.owner@example.com',
            password='S3curePass!123',
        )
        reviewer = User.objects.create_user(
            username='rec.reviewer@example.com',
            email='rec.reviewer@example.com',
            password='S3curePass!123',
        )
        product, lot, customer, sales_order, fiscal_document, crm_complaint, sample, document = (
            create_recalls_context(owner)
        )
        complaint = MarketComplaint.objects.create(
            complaint_type=MarketComplaint.ComplaintType.TECHNICAL_COMPLAINT,
            source=MarketComplaint.Source.CUSTOMER,
            customer=customer,
            product=product,
            stock_lot=lot,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            customer_complaint=crm_complaint,
            quality_sample=sample,
            document=document,
            criticality=MarketComplaint.Criticality.CRITICAL,
            received_at=timezone.now() - timedelta(days=2),
            regulatory_communication_required=True,
            responsible=owner,
            reported_by=owner,
            description='Queixa técnica recebida do mercado para investigação e eventual recolhimento.',
        )

        with pytest.raises(ValidationError) as investigation_without_triage:
            complaint.start_investigation(user=owner)

        complaint.start_triage(user=owner)

        with pytest.raises(ValidationError) as close_without_investigation:
            complaint.close(summary='Tentativa sem investigação.', user=reviewer)

        complaint.start_investigation(user=owner)

        with pytest.raises(ValidationError) as close_without_regulatory:
            complaint.close(summary='Tentativa sem comunicação regulatória.', user=reviewer)

        complaint.record_regulatory_communication(
            reference='ANVISA-REC-2026-0001',
            user=reviewer,
        )
        complaint.close(
            summary='Investigação concluída e comunicação regulatória registrada.', user=reviewer
        )
        product_return = ProductReturn.objects.create(
            complaint=complaint,
            return_type=ProductReturn.ReturnType.CUSTOMER_RETURN,
            customer=customer,
            product=product,
            stock_lot=lot,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            quantity=Decimal('12.0000'),
            unit=product.unit,
            reason='Devolução por queixa técnica confirmada.',
            requested_by=owner,
        )

        product_return.authorize(user=reviewer)
        product_return.receive(quantity=Decimal('12.0000'), user=owner)
        product_return.inspect(
            disposition=ProductReturn.Disposition.QUARANTINE,
            notes='Material segregado.',
            user=reviewer,
        )
        product_return.close(
            summary='Devolução encerrada com material em quarentena.', user=reviewer
        )
        campaign = RecallCampaign.objects.create(
            campaign_type=RecallCampaign.CampaignType.RECALL,
            trigger=RecallCampaign.Trigger.TECHNICAL_COMPLAINT,
            product=product,
            stock_lot=lot,
            complaint=complaint,
            criticality=RecallCampaign.Criticality.CRITICAL,
            reason='Risco potencial identificado em lote distribuído.',
            decision_date=timezone.localdate(),
            target_completion_date=timezone.localdate() + timedelta(days=30),
            responsible=owner,
        )

        with pytest.raises(ValidationError) as start_without_approval:
            campaign.start(user=owner)

        campaign.approve(user=reviewer)

        with pytest.raises(ValidationError) as start_without_impacted_customers:
            campaign.start(user=owner)

        impacted = RecallImpactedCustomer.objects.create(
            campaign=campaign,
            customer=customer,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            quantity_distributed=Decimal('120.0000'),
            quantity_recalled=Decimal('100.0000'),
            contact_name='Responsável Técnico',
            contact_email='rt.cliente@example.com',
        )
        campaign.start(user=owner)
        communication = RecallCommunication.objects.create(
            campaign=campaign,
            impacted_customer=impacted,
            channel=RecallCommunication.Channel.EMAIL,
            subject='Comunicado de recolhimento',
            message='Solicitamos segregação e retorno do lote afetado.',
            response_due_date=timezone.localdate() + timedelta(days=5),
            content_hash='sha256:comunicado-recall',
        )
        communication.send(user=owner)

        with pytest.raises(ValidationError) as close_without_response:
            campaign.close(summary='Tentativa sem resposta do cliente.', user=reviewer)

        impacted.record_response(
            status=RecallImpactedCustomer.ResponseStatus.ACKNOWLEDGED,
            notes='Cliente confirmou segregação.',
        )
        impacted.record_return(
            quantity=Decimal('100.0000'), notes='Quantidade recolhida integralmente.'
        )

        with pytest.raises(ValidationError) as close_without_report:
            campaign.close(summary='Tentativa sem relatório.', user=reviewer)

        report = RecallEffectivenessReport.objects.create(
            campaign=campaign,
            report_type=RecallEffectivenessReport.ReportType.EFFECTIVENESS,
            title='Relatório de efetividade do recolhimento',
        )
        report.generate(user=reviewer, content_reference='recalls/relatorio-efetividade.pdf')
        campaign.close(
            summary='Recall encerrado com retorno integral e relatório aprovado.', user=reviewer
        )

        complaint.refresh_from_db()
        product_return.refresh_from_db()
        campaign.refresh_from_db()
        impacted.refresh_from_db()
        report.refresh_from_db()
        assert 'status' in investigation_without_triage.value.message_dict
        assert 'investigation_summary' in close_without_investigation.value.message_dict
        assert 'regulatory_communication_reference' in close_without_regulatory.value.message_dict
        assert 'status' in start_without_approval.value.message_dict
        assert 'impacted_customers' in start_without_impacted_customers.value.message_dict
        assert 'impacted_customers' in close_without_response.value.message_dict
        assert 'reports' in close_without_report.value.message_dict
        assert complaint.status == MarketComplaint.Status.CLOSED
        assert product_return.status == ProductReturn.Status.CLOSED
        assert campaign.status == RecallCampaign.Status.CLOSED
        assert impacted.response_status == RecallImpactedCustomer.ResponseStatus.RETURNED
        assert report.status == RecallEffectivenessReport.Status.GENERATED
        assert report.impacted_customers == 1
        assert report.customers_contacted == 1
        assert report.responses_received == 1
        assert report.total_distributed == Decimal('120.0000')
        assert report.total_recalled == Decimal('100.0000')
        assert report.total_returned == Decimal('100.0000')
        assert report.effectiveness_rate == Decimal('100.00')

    def test_rf22_supports_required_types_and_traceability_links(self):
        from recalls.models import MarketComplaint, RecallCampaign

        owner = User.objects.create_user(
            username='rec.links.owner@example.com',
            email='rec.links.owner@example.com',
            password='S3curePass!123',
        )
        product, lot, customer, sales_order, fiscal_document, _crm_complaint, sample, document = (
            create_recalls_context(owner)
        )
        complaint = MarketComplaint.objects.create(
            complaint_type=MarketComplaint.ComplaintType.RECALL_REQUEST,
            source=MarketComplaint.Source.AUTHORITY,
            customer=customer,
            product=product,
            stock_lot=lot,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            quality_sample=sample,
            document=document,
            criticality=MarketComplaint.Criticality.HIGH,
            received_at=timezone.now(),
            responsible=owner,
            reported_by=owner,
        )

        assert {
            MarketComplaint.ComplaintType.COMPLAINT,
            MarketComplaint.ComplaintType.TECHNICAL_COMPLAINT,
            MarketComplaint.ComplaintType.RETURN,
            MarketComplaint.ComplaintType.RECALL_REQUEST,
        }.issubset(set(MarketComplaint.ComplaintType.values))
        assert {
            RecallCampaign.CampaignType.RECALL,
            RecallCampaign.CampaignType.VOLUNTARY_RECALL,
            RecallCampaign.CampaignType.FIELD_CORRECTION,
            RecallCampaign.CampaignType.STOCK_WITHDRAWAL,
        }.issubset(set(RecallCampaign.CampaignType.values))
        assert complaint.customer == customer
        assert complaint.product == product
        assert complaint.stock_lot == lot
        assert complaint.sales_order == sales_order
        assert complaint.fiscal_document == fiscal_document
        assert complaint.quality_sample == sample
        assert complaint.document == document


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestRecallsApi:
    def test_recalls_api_uses_global_scope_and_executes_required_workflow(self):
        from recalls.models import (
            MarketComplaint,
            ProductReturn,
            RecallCampaign,
            RecallCommunication,
            RecallEffectivenessReport,
            RecallImpactedCustomer,
        )

        owner = User.objects.create_user(
            username='api.rec.owner@example.com',
            email='api.rec.owner@example.com',
            password='S3curePass!123',
        )
        User.objects.create_user(
            username='api.rec.reviewer@example.com',
            email='api.rec.reviewer@example.com',
            password='S3curePass!123',
        )
        other_owner = User.objects.create_user(
            username='api.rec.other@example.com',
            email='api.rec.other@example.com',
            password='S3curePass!123',
        )
        product, lot, customer, sales_order, fiscal_document, crm_complaint, sample, document = (
            create_recalls_context(owner, suffix='001')
        )
        (
            other_product,
            _other_lot,
            other_customer,
            _other_order,
            _other_document,
            _other_complaint,
            _other_sample,
            _other_doc,
        ) = create_recalls_context(other_owner, suffix='999')
        MarketComplaint.objects.create(
            complaint_type=MarketComplaint.ComplaintType.COMPLAINT,
            source=MarketComplaint.Source.CUSTOMER,
            customer=other_customer,
            product=other_product,
            criticality=MarketComplaint.Criticality.LOW,
            received_at=timezone.now(),
            responsible=other_owner,
            reported_by=other_owner,
        )
        client = APIClient()
        client.force_authenticate(owner)

        complaint_response = client.post(
            '/api/recalls/complaints/',
            {
                'complaint_type': MarketComplaint.ComplaintType.TECHNICAL_COMPLAINT,
                'source': MarketComplaint.Source.CUSTOMER,
                'customer': customer.id,
                'product': product.id,
                'stock_lot': lot.id,
                'sales_order': sales_order.id,
                'fiscal_document': fiscal_document.id,
                'customer_complaint': crm_complaint.id,
                'quality_sample': sample.id,
                'document': document.id,
                'criticality': MarketComplaint.Criticality.CRITICAL,
                'description': 'Queixa técnica recebida via API.',
                'received_at': timezone.now().isoformat(),
                'regulatory_communication_required': True,
                'responsible': owner.id,
            },
        )
        complaint_id = complaint_response.json()['id']
        invalid_complaint_response = client.post(
            '/api/recalls/complaints/',
            {
                'complaint_type': MarketComplaint.ComplaintType.COMPLAINT,
                'source': MarketComplaint.Source.CUSTOMER,
                'customer': customer.id,
                'product': other_product.id,
                'criticality': MarketComplaint.Criticality.LOW,
                'description': 'Produto secundario em escopo global.',
                'received_at': timezone.now().isoformat(),
                'responsible': owner.id,
            },
        )
        triage_response = client.post(f'/api/recalls/complaints/{complaint_id}/start_triage/')
        investigation_response = client.post(
            f'/api/recalls/complaints/{complaint_id}/start_investigation/',
        )
        regulatory_response = client.post(
            f'/api/recalls/complaints/{complaint_id}/record_regulatory_communication/',
            {'reference': 'ANVISA-API-REC-0001'},
        )
        close_complaint_response = client.post(
            f'/api/recalls/complaints/{complaint_id}/close/',
            {'summary': 'Reclamação encerrada com investigação e comunicação.'},
        )
        return_response = client.post(
            '/api/recalls/returns/',
            {
                'complaint': complaint_id,
                'return_type': ProductReturn.ReturnType.CUSTOMER_RETURN,
                'customer': customer.id,
                'product': product.id,
                'stock_lot': lot.id,
                'sales_order': sales_order.id,
                'fiscal_document': fiscal_document.id,
                'quantity': '8.0000',
                'unit': product.unit_id,
                'reason': 'Retorno físico do material reclamado.',
            },
        )
        return_id = return_response.json()['id']
        return_authorize_response = client.post(f'/api/recalls/returns/{return_id}/authorize/')
        return_receive_response = client.post(
            f'/api/recalls/returns/{return_id}/receive/',
            {'quantity': '8.0000'},
        )
        return_inspect_response = client.post(
            f'/api/recalls/returns/{return_id}/inspect/',
            {
                'disposition': ProductReturn.Disposition.QUARANTINE,
                'notes': 'Material recebido e segregado.',
            },
        )
        return_close_response = client.post(
            f'/api/recalls/returns/{return_id}/close/',
            {'summary': 'Devolução encerrada.'},
        )
        campaign_response = client.post(
            '/api/recalls/campaigns/',
            {
                'campaign_type': RecallCampaign.CampaignType.RECALL,
                'trigger': RecallCampaign.Trigger.TECHNICAL_COMPLAINT,
                'product': product.id,
                'stock_lot': lot.id,
                'complaint': complaint_id,
                'criticality': RecallCampaign.Criticality.CRITICAL,
                'reason': 'Recall aberto por queixa técnica crítica.',
                'decision_date': str(timezone.localdate()),
                'target_completion_date': str(timezone.localdate() + timedelta(days=30)),
                'responsible': other_owner.id,
            },
        )
        campaign_id = campaign_response.json()['id']
        impacted_response = client.post(
            '/api/recalls/impacted-customers/',
            {
                'campaign': campaign_id,
                'customer': customer.id,
                'sales_order': sales_order.id,
                'fiscal_document': fiscal_document.id,
                'quantity_distributed': '40.0000',
                'quantity_recalled': '40.0000',
                'contact_name': 'Responsável Técnico',
                'contact_email': 'rt.cliente@example.com',
            },
        )
        impacted_id = impacted_response.json()['id']
        approve_response = client.post(f'/api/recalls/campaigns/{campaign_id}/approve/')
        start_response = client.post(f'/api/recalls/campaigns/{campaign_id}/start/')
        communication_response = client.post(
            '/api/recalls/communications/',
            {
                'campaign': campaign_id,
                'impacted_customer': impacted_id,
                'channel': RecallCommunication.Channel.EMAIL,
                'subject': 'Recall API',
                'message': 'Mensagem de recolhimento.',
                'response_due_date': str(timezone.localdate() + timedelta(days=5)),
                'content_hash': 'sha256:api-recall',
            },
        )
        communication_id = communication_response.json()['id']
        communication_send_response = client.post(
            f'/api/recalls/communications/{communication_id}/send/'
        )
        impacted_response_record = client.post(
            f'/api/recalls/impacted-customers/{impacted_id}/record_response/',
            {
                'status': RecallImpactedCustomer.ResponseStatus.ACKNOWLEDGED,
                'notes': 'Cliente confirmou recebimento.',
            },
        )
        impacted_return_record = client.post(
            f'/api/recalls/impacted-customers/{impacted_id}/record_return/',
            {'quantity': '40.0000', 'notes': 'Retorno integral.'},
        )
        report_response = client.post(
            '/api/recalls/reports/',
            {
                'campaign': campaign_id,
                'report_type': RecallEffectivenessReport.ReportType.EFFECTIVENESS,
                'title': 'Relatório API de efetividade',
            },
        )
        report_id = report_response.json()['id']
        report_generate_response = client.post(
            f'/api/recalls/reports/{report_id}/generate/',
            {'content_reference': 'recalls/api-efetividade.pdf'},
        )
        close_campaign_response = client.post(
            f'/api/recalls/campaigns/{campaign_id}/close/',
            {'summary': 'Recall API encerrado.'},
        )
        list_response = client.get('/api/recalls/complaints/')

        assert complaint_response.status_code == 201
        assert invalid_complaint_response.status_code == 201
        assert triage_response.status_code == 200
        assert investigation_response.status_code == 200
        assert regulatory_response.status_code == 200
        assert close_complaint_response.status_code == 200
        assert return_response.status_code == 201
        assert return_authorize_response.status_code == 200
        assert return_receive_response.status_code == 200
        assert return_inspect_response.status_code == 200
        assert return_close_response.status_code == 200
        assert campaign_response.status_code == 201
        assert impacted_response.status_code == 201
        assert approve_response.status_code == 200
        assert start_response.status_code == 200
        assert communication_response.status_code == 201
        assert communication_send_response.status_code == 200
        assert impacted_response_record.status_code == 200
        assert impacted_return_record.status_code == 200
        assert report_response.status_code == 201
        assert report_generate_response.status_code == 200
        assert close_campaign_response.status_code == 200
        assert close_campaign_response.json()['status'] == RecallCampaign.Status.CLOSED
        assert list_response.status_code == 200
        assert complaint_response.json()['complaint_number'] in {
            item['complaint_number'] for item in list_response.json()['results']
        }
