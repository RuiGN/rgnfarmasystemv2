from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deviations.models import QualityEvent
from inventory.models import (
    StockBalance,
    StockLot,
    StockLotGenealogy,
    StockQualityStatus,
    StorageLocation,
    Warehouse,
)
from masters.models import Product, Site, UnitOfMeasure
from qa.models import (
    BatchRecordChecklistItem,
    LotRelease,
    QAReview,
    QualityBlock,
)
from quality.models import (
    QualityAnalysis,
    QualityDocument,
    QualityResult,
    QualitySample,
)


class LotReleaseCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='farmaceutico-qa',
            email='qa@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar a liberação de lote
        view_release_perm = Permission.objects.get(
            content_type__app_label='qa', codename='view_lotrelease'
        )
        self.user.user_permissions.add(view_release_perm)

        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')
        self.unit_kg = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')

        self.product = Product.objects.create(
            code='PA-CREME-01',
            description='Creme Facial Hidratante FPS 30',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        self.raw_material = Product.objects.create(
            code='MP-ACIDO-01',
            description='Ácido Hialurônico 1%',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit_kg,
            status=Product.Status.APPROVED,
        )

        today = timezone.now().date()
        self.lot = StockLot.objects.create(
            product=self.product,
            lot_number='LOT-CRM-2026',
            quality_status=StockQualityStatus.QUARANTINE,
            manufacturing_date=today,
            expiry_date=today + timedelta(days=730),
        )

        self.input_lot = StockLot.objects.create(
            product=self.raw_material,
            lot_number='LOT-MP-001',
            quality_status=StockQualityStatus.APPROVED,
            manufacturing_date=today - timedelta(days=30),
            expiry_date=today + timedelta(days=365),
        )

        self.site = Site.objects.create(
            code='PL-QA-01',
            name='Planta QA Principal',
            site_type=Site.SiteType.PLANT,
        )
        self.warehouse = Warehouse.objects.create(
            site=self.site,
            code='ALM-01',
            name='Almoxarifado Geral',
            warehouse_type=Warehouse.WarehouseType.FINISHED_PRODUCT,
        )
        self.location = StorageLocation.objects.create(
            warehouse=self.warehouse, code='R01-P01', name='Rua 1 Prateleira 1'
        )

        self.balance = StockBalance.objects.create(
            product=self.product,
            lot=self.lot,
            warehouse=self.warehouse,
            location=self.location,
            quality_status=StockQualityStatus.QUARANTINE,
            quantity=Decimal('1000.0000'),
            reserved_quantity=Decimal('100.0000'),
            unit=self.unit_un,
        )

        self.genealogy = StockLotGenealogy.objects.create(
            input_lot=self.input_lot,
            output_lot=self.lot,
            relation_type=StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
            quantity=Decimal('15.5000'),
            unit=self.unit_kg,
        )

        self.sample = QualitySample.objects.create(
            product=self.product,
            stock_lot=self.lot,
            sample_type=QualitySample.SampleType.PRODUCTION,
            status=QualitySample.Status.APPROVED,
        )

        self.analysis = QualityAnalysis.objects.create(
            sample=self.sample,
            status=QualityAnalysis.Status.APPROVED,
            analyst=self.user,
        )

        self.result = QualityResult.objects.create(
            analysis=self.analysis,
            parameter_name='pH a 25°C',
            result_type=QualityResult.ResultType.QUANTITATIVE,
            numeric_result=Decimal('5.5000'),
            unit=self.unit_un,
            result_status=QualityResult.ResultStatus.COMPLIANT,
        )

        self.quality_document = QualityDocument.objects.create(
            document_type=QualityDocument.DocumentType.CERTIFICATE_OF_ANALYSIS,
            sample=self.sample,
            product=self.product,
            stock_lot=self.lot,
            status=QualityDocument.Status.ISSUED,
            conclusion='Lote conforme especificação analítica.',
            issued_by=self.user,
            issued_at=timezone.now(),
        )

        self.qa_review = QAReview.objects.create(
            review_type=QAReview.ReviewType.LOT_RELEASE,
            title='Revisão de Batch Record - Lote LOT-CRM-2026',
            stock_lot=self.lot,
            quality_document=self.quality_document,
            status=QAReview.Status.IN_REVIEW,
            submitted_by=self.user,
            submitted_at=timezone.now(),
        )

        self.checklist_item = BatchRecordChecklistItem.objects.create(
            review=self.qa_review,
            title='Conferência das assinaturas e pesos da fórmula mestre',
            status=BatchRecordChecklistItem.Status.COMPLETED,
            evidence_reference='DOC-VERIF-001',
            responsible=self.user,
            completed_by=self.user,
            completed_at=timezone.now(),
        )

        self.release = LotRelease.objects.create(
            product=self.product,
            stock_lot=self.lot,
            qa_review=self.qa_review,
            quality_document=self.quality_document,
            release_status=LotRelease.ReleaseStatus.UNDER_REVIEW,
        )

        self.cockpit_url = reverse('app:qa_lot_release_cockpit', kwargs={'pk': self.release.pk})

    def test_cockpit_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_cockpit_requires_view_permission(self):
        user_no_perm = get_user_model().objects.create_user(
            username='user-no-perm',
            email='noperm@example.com',
            password='Password123!',
        )
        self.client.force_login(user_no_perm)
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_renders_header_and_kpis(self):
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cockpit de liberação de lote')
        self.assertContains(response, self.release.release_number)
        self.assertContains(response, 'LOT-CRM-2026')
        self.assertContains(response, 'Creme Facial Hidratante FPS 30')
        self.assertContains(response, 'Em revisão')
        self.assertContains(response, 'Quarentena')

    def test_sod_locked_tabs_show_permission_warnings(self):
        # Usuário possui apenas 'qa.view_lotrelease'. Deve ver alertas SoD nas outras abas.
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'inventory.view_stockbalance')
        self.assertContains(response, 'inventory.view_stocklotgenealogy')
        self.assertContains(response, 'quality.view_qualitysample')
        self.assertContains(response, 'qa.view_qualityblock')
        self.assertContains(response, 'deviations.view_qualityevent')

    def test_tab1_renders_balances_and_genealogy_with_permission(self):
        perm_balance = Permission.objects.get(
            content_type__app_label='inventory', codename='view_stockbalance'
        )
        perm_genealogy = Permission.objects.get(
            content_type__app_label='inventory', codename='view_stocklotgenealogy'
        )
        self.user.user_permissions.add(perm_balance, perm_genealogy)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Almoxarifado Geral')
        self.assertContains(response, 'R01-P01')
        self.assertContains(response, '1000,0000')  # pt-BR decimal
        self.assertContains(response, '900,0000')   # disponível
        self.assertContains(response, 'LOT-MP-001')
        self.assertContains(response, '15,5000')

    def test_tab2_renders_qc_samples_and_documents_with_permission(self):
        perm_sample = Permission.objects.get(
            content_type__app_label='quality', codename='view_qualitysample'
        )
        self.user.user_permissions.add(perm_sample)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.quality_document.document_number)
        self.assertContains(response, 'Lote conforme especificação analítica.')
        self.assertContains(response, self.sample.sample_number)
        self.assertContains(response, 'pH a 25°C')
        self.assertContains(response, '5,5000')

    def test_tab3_renders_qa_review_and_checklist_items(self):
        perm_review = Permission.objects.get(
            content_type__app_label='qa', codename='view_qareview'
        )
        perm_checklist = Permission.objects.get(
            content_type__app_label='qa', codename='view_batchrecordchecklistitem'
        )
        self.user.user_permissions.add(perm_review, perm_checklist)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.qa_review.review_number)
        self.assertContains(response, 'Conferência das assinaturas e pesos da fórmula mestre')
        self.assertContains(response, 'DOC-VERIF-001')
        self.assertContains(response, '100%')

    def test_tab4_renders_blocks_and_deviations(self):
        perm_block = Permission.objects.get(
            content_type__app_label='qa', codename='view_qualityblock'
        )
        perm_dev = Permission.objects.get(
            content_type__app_label='deviations', codename='view_qualityevent'
        )
        self.user.user_permissions.add(perm_block, perm_dev)

        QualityBlock.objects.create(
            target_type=QualityBlock.TargetType.LOT,
            stock_lot=self.lot,
            reason='Suspeita de contaminação microbiológica',
            status=QualityBlock.Status.ACTIVE,
            blocked_by=self.user,
        )

        QualityEvent.objects.create(
            event_type=QualityEvent.EventType.DEVIATION,
            origin=QualityEvent.Origin.QUALITY_CONTROL,
            area='Laboratório Físico-Químico',
            product=self.product,
            stock_lot=self.lot,
            severity=QualityEvent.Severity.LOW,
            criticality=QualityEvent.Criticality.MINOR,
            status=QualityEvent.Status.OPEN,
            description='Temperatura da estufa variou 1 grau por 10 minutos',
            detected_at=timezone.now(),
            responsible=self.user,
        )

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Suspeita de contaminação microbiológica')
        self.assertContains(response, 'Temperatura da estufa variou 1 grau por 10 minutos')
        self.assertContains(response, '1 bloqueio(s) ativo(s)')

    def test_tab5_renders_readiness_criteria_and_action_buttons(self):
        perm_manage = Permission.objects.get(
            content_type__app_label='qa', codename='change_lotrelease'
        )
        self.user.user_permissions.add(perm_manage)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Critérios de prontidão regulatória (ALCOA+)')
        self.assertContains(response, 'Amostras de Controle de Qualidade Aprovadas')
        self.assertContains(response, 'Laudo Analítico / Certificado de Análise Emitido')
        # Ações disponíveis para status UNDER_REVIEW
        self.assertContains(response, 'Aprovar')
        self.assertContains(response, 'Bloquear')
        self.assertContains(response, 'Rejeitar')

    def test_stock_lot_dossier_view_redirects_to_cockpit(self):
        dossier_url = reverse('app:stock_lot_dossier', kwargs={'pk': self.lot.pk})
        response = self.client.get(dossier_url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, self.cockpit_url)

    def test_resource_detail_shows_cockpit_buttons(self):
        # Detalhe da liberação QA
        qa_detail_url = reverse(
            'app:resource_detail',
            kwargs={'module_slug': 'qa', 'resource_slug': 'lot-releases', 'pk': self.release.pk},
        )
        response = self.client.get(qa_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dossiê de liberação')

        # Detalhe do lote no estoque
        perm_stock = Permission.objects.get(
            content_type__app_label='inventory', codename='view_stocklot'
        )
        self.user.user_permissions.add(perm_stock)
        lot_detail_url = reverse(
            'app:resource_detail',
            kwargs={'module_slug': 'inventory', 'resource_slug': 'lots', 'pk': self.lot.pk},
        )
        response = self.client.get(lot_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Dossiê QA / Liberação')
