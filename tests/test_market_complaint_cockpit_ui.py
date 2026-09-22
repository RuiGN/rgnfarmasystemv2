from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from capa.models import CapaAction, CapaRecord
from deviations.models import QualityEvent
from inventory.models import StockBalance, StockLot, StockQualityStatus, StorageLocation, Warehouse
from masters.models import BusinessPartner, Product, Site, UnitOfMeasure
from qa.models import QualityBlock
from quality.models import QualityAnalysis, QualityResult, QualitySample
from recalls.models import (
    MarketComplaint,
    ProductReturn,
    RecallCampaign,
    RecallCommunication,
    RecallEffectivenessReport,
    RecallImpactedCustomer,
)


class MarketComplaintCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='vigilance-specialist',
            email='vigilance@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar a reclamação pós-mercado
        view_complaint_perm = Permission.objects.get(
            content_type__app_label='recalls', codename='view_marketcomplaint'
        )
        self.user.user_permissions.add(view_complaint_perm)

        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')

        self.customer = BusinessPartner.objects.create(
            legal_name='Drogaria Cosméticos Saúde S.A.',
            trade_name='Drogarias Saúde',
            document='12.345.678/0001-90',
            partner_type=BusinessPartner.PartnerType.CUSTOMER,
            email='sac@drogariasaude.com.br',
        )

        self.product = Product.objects.create(
            code='PA-CREME-01',
            description='Creme Facial Anti-Idade FPS 30 50g',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        self.lot = StockLot.objects.create(
            product=self.product,
            lot_number='LOT-CREME-2026-01',
            quality_status=StockQualityStatus.APPROVED,
            manufacturing_date=timezone.now().date() - timedelta(days=30),
            expiry_date=timezone.now().date() + timedelta(days=700),
        )

        self.complaint = MarketComplaint.objects.create(
            complaint_type=MarketComplaint.ComplaintType.TECHNICAL_COMPLAINT,
            source=MarketComplaint.Source.CUSTOMER,
            customer=self.customer,
            product=self.product,
            stock_lot=self.lot,
            criticality=MarketComplaint.Criticality.HIGH,
            description='Consumidor relatou dermatite de contato e vermelhidão após aplicação do creme.',
            received_at=timezone.now(),
            regulatory_communication_required=True,
            responsible=self.user,
            reported_by=self.user,
        )

        self.cockpit_url = reverse(
            'app:market_complaint_cockpit', kwargs={'pk': self.complaint.pk}
        )

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_user_without_permission_receives_403(self):
        unauthorized_user = get_user_model().objects.create_user(
            username='user-no-perm',
            email='noperm@example.com',
            password='Password123!',
        )
        self.client.force_login(unauthorized_user)
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_renders_executive_kpis_and_identification(self):
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)

        # Identificação executiva e cabeçalho
        self.assertContains(response, self.complaint.complaint_number)
        self.assertContains(response, 'Drogaria Cosméticos Saúde S.A.')
        self.assertContains(response, 'PA-CREME-01')
        self.assertContains(response, 'Creme Facial Anti-Idade FPS 30 50g')
        self.assertContains(response, 'LOT-CREME-2026-01')

        # Badges e KPIs
        self.assertContains(response, 'Criticidade Alta')
        self.assertContains(response, 'Rascunho')
        self.assertContains(response, 'Notificação ANVISA Obrigatória')
        self.assertContains(response, 'Devoluções Físicas')
        self.assertContains(response, 'Recuperação de Recall')

        # Abas de navegação presentes
        self.assertContains(response, '1. Notificação e triagem clínica')
        self.assertContains(response, '2. Amostroteca e investigação analítica')
        self.assertContains(response, '3. Devoluções e quarentena')
        self.assertContains(response, '4. Recolhimento e clientes impactados')
        self.assertContains(response, '5. Dossiê regulatório ANVISA e eficácia')

    def test_sod_analysis_tab_permissions(self):
        sample = QualitySample.objects.create(
            sample_number='AM-2026-001',
            sample_type=QualitySample.SampleType.COMPLAINT,
            product=self.product,
            stock_lot=self.lot,
            quantity=Decimal('2.0000'),
            unit=self.unit_un,
            status=QualitySample.Status.APPROVED,
        )
        self.complaint.quality_sample = sample
        self.complaint.save()

        analysis = QualityAnalysis.objects.create(
            analysis_number='AN-2026-001',
            sample=sample,
            status=QualityAnalysis.Status.COMPLETED,
            method_reference='Farmacopeia Brasileira 6ª Ed.',
        )

        QualityResult.objects.create(
            analysis=analysis,
            parameter_name='Determinação de pH',
            numeric_result=Decimal('5.5000'),
            result_status='conforming',
            unit=self.unit_un,
        )

        # Sem permissão de laboratório -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(
            response,
            'Você não possui permissão para visualizar amostras e laudos analíticos',
        )
        self.assertNotContains(response, 'Determinação de pH')

        # Com permissão de qualidade -> tabela analítica renderizada
        perm = Permission.objects.get(
            content_type__app_label='quality', codename='view_qualitysample'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'AM-2026-001')
        self.assertContains(response, 'Determinação de pH')
        self.assertContains(response, '5,5000')

    def test_sod_returns_tab_permissions(self):
        ret = ProductReturn.objects.create(
            complaint=self.complaint,
            return_type=ProductReturn.ReturnType.CUSTOMER_RETURN,
            customer=self.customer,
            product=self.product,
            stock_lot=self.lot,
            quantity=Decimal('15.0000'),
            unit=self.unit_un,
            reason='Devolução por irritação cutânea',
            status=ProductReturn.Status.RECEIVED,
            received_quantity=Decimal('15.0000'),
            disposition=ProductReturn.Disposition.QUARANTINE,
            inspection_notes='Embalagens violadas e frascos recolhidos em quarentena técnica.',
        )

        # Sem permissão de devolução -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(
            response,
            'Você não possui permissão para visualizar devoluções de produto pós-mercado',
        )
        self.assertNotContains(response, ret.return_number)

        # Com permissão de devolução -> tabela de devoluções renderizada
        perm = Permission.objects.get(
            content_type__app_label='recalls', codename='view_productreturn'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, ret.return_number)
        self.assertContains(response, '15,00 UN')
        self.assertContains(response, 'Quarentena')
        self.assertContains(response, 'Recebida')
        self.assertContains(
            response, 'Embalagens violadas e frascos recolhidos em quarentena técnica.'
        )

    def test_sod_recalls_tab_permissions(self):
        campaign = RecallCampaign.objects.create(
            campaign_type=RecallCampaign.CampaignType.VOLUNTARY_RECALL,
            trigger=RecallCampaign.Trigger.TECHNICAL_COMPLAINT,
            product=self.product,
            stock_lot=self.lot,
            complaint=self.complaint,
            criticality=RecallCampaign.Criticality.HIGH,
            reason='Recolhimento voluntário do lote por potencial desvio microbiológico.',
            decision_date=timezone.now().date(),
            target_completion_date=timezone.now().date() + timedelta(days=30),
            responsible=self.user,
            status=RecallCampaign.Status.IN_EXECUTION,
        )

        impacted = RecallImpactedCustomer.objects.create(
            campaign=campaign,
            customer=self.customer,
            quantity_distributed=Decimal('100.0000'),
            quantity_recalled=Decimal('80.0000'),
            quantity_returned=Decimal('60.0000'),
            response_status=RecallImpactedCustomer.ResponseStatus.RETURNED,
            contact_name='Farmacêutico Responsável',
            contact_email='farmacia@drogariasaude.com.br',
        )

        # Sem permissão de campanhas -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(
            response,
            'Você não possui permissão para visualizar campanhas de recall',
        )

        # Com permissão de campanha de recall
        perm_camp = Permission.objects.get(
            content_type__app_label='recalls', codename='view_recallcampaign'
        )
        perm_imp = Permission.objects.get(
            content_type__app_label='recalls', codename='view_recallimpactedcustomer'
        )
        self.user.user_permissions.add(perm_camp, perm_imp)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, campaign.campaign_number)
        self.assertContains(response, 'Recolhimento voluntário')
        self.assertContains(response, 'Drogaria Cosméticos Saúde S.A.')
        self.assertContains(response, '100,00')
        self.assertContains(response, '80,00')
        self.assertContains(response, '60,00')
        self.assertContains(response, '75,00%')

    def test_sod_regulatory_and_capa_tab(self):
        self.complaint.regulatory_communication_reference = 'NOTIF-ANVISA-2026-9988'
        self.complaint.save()

        capa = CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.COMPLAINT,
            title='Investigação de irritação cutânea e revisão da fórmula PA-CREME-01',
            root_cause='Possível interação entre conservante e fragrância na emulsão.',
            owner=self.user,
            due_date=timezone.now().date() + timedelta(days=60),
            status=CapaRecord.Status.IN_PROGRESS,
            opened_by=self.user,
            opened_at=timezone.now(),
        )
        self.complaint.capa = capa
        self.complaint.save()

        CapaAction.objects.create(
            capa=capa,
            action_type=CapaAction.ActionType.CORRECTIVE,
            title='Reforçar testes de compatibilidade dérmica em voluntários',
            responsible=self.user,
            due_date=timezone.now().date() + timedelta(days=45),
            status=CapaAction.Status.PENDING,
        )

        # Permissão de CAPA
        perm_capa = Permission.objects.get(
            content_type__app_label='capa', codename='view_caparecord'
        )
        self.user.user_permissions.add(perm_capa)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'NOTIF-ANVISA-2026-9988')
        self.assertContains(response, capa.capa_number)
        self.assertContains(
            response, 'Investigação de irritação cutânea e revisão da fórmula PA-CREME-01'
        )
        self.assertContains(
            response, 'Reforçar testes de compatibilidade dérmica em voluntários'
        )
        self.assertContains(response, 'Checklist Regulatório de Encerramento (Cosmetovigilância)')

    def test_resource_detail_has_cockpit_action_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'recalls',
                'resource_slug': 'complaints',
                'pk': self.complaint.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cockpit de cosmetovigilância / Recall')
        self.assertContains(response, self.cockpit_url)
