from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audits.models import AuditFinding, AuditPlan, AuditProgram, AuditReport
from auxiliary.models import City, Country, StateProvince
from masters.models import BusinessPartner, Product, UnitOfMeasure
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    SupplierQualificationEvent,
    SupplierQuotation,
)
from qa.models import QualityBlock
from quality.models import LaboratoryInvestigation, QualitySample


class SupplierCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='procurement-qa-lead',
            email='procurement.qa@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar o fornecedor/parceiro
        view_partner_perm = Permission.objects.get(
            content_type__app_label='masters', codename='view_businesspartner'
        )
        self.user.user_permissions.add(view_partner_perm)

        # Localização geográfica
        self.country = Country.objects.create(
            name='Brasil', iso_alpha2='BR', iso_alpha3='BRA', numeric_code='076'
        )
        self.state = StateProvince.objects.create(name='São Paulo', abbreviation='SP', country=self.country)
        self.city = City.objects.create(name='Campinas', state=self.state)

        # Unidade de medida e Insumo
        self.unit_kg = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        self.product = Product.objects.create(
            code='MP-ALOE-01',
            description='Extrato Glicólico de Aloe Vera 20%',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit_kg,
            status=Product.Status.APPROVED,
            requires_quality_release=True,
            requires_approved_supplier=True,
        )

        # Fornecedor qualificado
        self.supplier = BusinessPartner.objects.create(
            code='FOR-001',
            legal_name='Botânica Extratos Naturais do Brasil Ltda',
            trade_name='Botânica Fitoquímica',
            document='33.444.555/0001-22',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
            qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
            qualification_valid_until=timezone.localdate() + timedelta(days=180),
            email='qualidade@botanica.com.br',
            phone='(19) 3344-5566',
            street='Avenida Industrial Farmacêutica',
            street_number='1500',
            complement='Galpão 3',
            neighborhood='Distrito Industrial',
            zipcode='13080-000',
            city_ref=self.city,
            state_ref=self.state,
            country_ref=self.country,
            is_active=True,
            is_blocked=False,
        )

        # Licença Sanitária (AFE ANVISA)
        self.license_event = SupplierQualificationEvent.objects.create(
            supplier=self.supplier,
            event_type=SupplierQualificationEvent.EventType.DOCUMENT,
            event_date=timezone.localdate() - timedelta(days=60),
            valid_until=timezone.localdate() + timedelta(days=300),
            severity='Alta',
            description='Autorização de Funcionamento de Empresa - AFE ANVISA nº 2026/0129-88',
        )

        # Programa e Plano de Auditoria BPF
        self.audit_program = AuditProgram.objects.create(
            program_number='AUDPRG-2026-01',
            audit_type=AuditProgram.AuditType.SUPPLIER,
            title='Programa Anual de Auditorias BPF em Fornecedores de Insumos',
            year=timezone.localdate().year,
            scope='Fornecedores de matérias-primas cosméticas críticas',
            criteria='RDC 48/2013 e ISO 22716',
            owner=self.user,
            starts_on=timezone.localdate() - timedelta(days=90),
            ends_on=timezone.localdate() + timedelta(days=270),
            status=AuditProgram.Status.ACTIVE,
        )

        self.audit_plan = AuditPlan.objects.create(
            audit_number='AUD-FOR-2026-01',
            program=self.audit_program,
            audit_type=AuditPlan.AuditType.SUPPLIER,
            supplier=self.supplier,
            title='Auditoria de Qualificação BPF em Planta Fabril de Extratos',
            scope='Boas Práticas de Fabricação, controle de processos e microbiologia',
            criteria='ISO 22716:2007 Cosméticos BPF',
            agenda='Reunião inicial, inspeção de áreas limpas, controle analítico, reunião final',
            lead_auditor=self.user,
            auditee_name='Botânica Extratos',
            area='Garantia da Qualidade',
            scheduled_start=timezone.now() - timedelta(days=30),
            scheduled_end=timezone.now() - timedelta(days=29),
            actual_start=timezone.now() - timedelta(days=30),
            actual_end=timezone.now() - timedelta(days=29),
            status=AuditPlan.Status.CLOSED,
        )

        self.audit_report = AuditReport.objects.create(
            audit=self.audit_plan,
            executive_summary='Fornecedor apresenta excelente conformidade com BPF e rastreabilidade total.',
            conclusion='Fornecedor Aprovado para fornecimento de extratos botânicos.',
            status=AuditReport.Status.ISSUED,
            compliance_rate=Decimal('96.50'),
            total_findings=1,
            minor_findings=1,
        )

        self.audit_finding = AuditFinding.objects.create(
            audit=self.audit_plan,
            classification='Documentação',
            criticality='minor',
            title='Controle de temperatura do almoxarifado necessita ajuste de calibração secundária',
            description='Termohigrômetro reserva aguardando certificado rastreável RBC.',
            responsible=self.user,
            due_date=timezone.localdate() + timedelta(days=30),
            status='closed',
        )

        # Pedido de Compra e Recebimento Físico
        self.purchase_order = PurchaseOrder.objects.create(
            order_number='PC-2026-0001',
            supplier=self.supplier,
            issue_date=timezone.localdate() - timedelta(days=20),
            expected_delivery_date=timezone.localdate() - timedelta(days=10),
            status=PurchaseOrder.Status.RECEIVED,
            total_amount=Decimal('12750.0000'),
            approved_by=self.user,
            approved_at=timezone.now() - timedelta(days=20),
        )

        self.order_item = PurchaseOrderItem.objects.create(
            order=self.purchase_order,
            product=self.product,
            quantity=Decimal('500.0000'),
            unit=self.unit_kg,
            unit_price=Decimal('25.5000'),
        )

        self.purchase_receipt = PurchaseReceipt.objects.create(
            receipt_number='REC-2026-0001',
            order=self.purchase_order,
            status=PurchaseReceipt.Status.RECEIVED,
            fiscal_document_number='NF-10492',
            nfe_access_key='35260933444555000122550010000104921000104923',
            physical_received_at=timezone.now() - timedelta(days=10),
            quality_status=PurchaseReceipt.QualityStatus.APPROVED,
            stock_entry_status=PurchaseReceipt.StockEntryStatus.POSTED,
            received_by=self.user,
        )

        self.receipt_item = PurchaseReceiptItem.objects.create(
            receipt=self.purchase_receipt,
            order_item=self.order_item,
            product=self.product,
            received_quantity=Decimal('500.0000'),
            accepted_quantity=Decimal('500.0000'),
            rejected_quantity=Decimal('0.0000'),
            unit=self.unit_kg,
            lot_number='LOT-ALOE-2026-A',
            manufacturing_date=timezone.localdate() - timedelta(days=40),
            expiry_date=timezone.localdate() + timedelta(days=700),
        )

        self.cockpit_url = reverse('app:supplier_cockpit', kwargs={'pk': self.supplier.pk})

    def _grant_all_permissions(self):
        perms = [
            ('procurement', 'view_supplierqualificationevent'),
            ('procurement', 'add_supplierqualificationevent'),
            ('procurement', 'change_supplierqualificationevent'),
            ('procurement', 'view_purchaseorder'),
            ('procurement', 'view_purchasereceipt'),
            ('audits', 'view_auditplan'),
            ('audits', 'view_auditreport'),
            ('qa', 'view_qualityblock'),
            ('quality', 'view_qualitysample'),
            ('deviations', 'view_qualityevent'),
            ('masters', 'view_product'),
            ('masters', 'change_businesspartner'),
        ]
        for app, codename in perms:
            p = Permission.objects.filter(content_type__app_label=app, codename=codename).first()
            if p:
                self.user.user_permissions.add(p)

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_user_without_permission_receives_403(self):
        unauthorized = get_user_model().objects.create_user(
            username='no-perm-user',
            email='noperm@example.com',
            password='Password123!',
        )
        self.client.force_login(unauthorized)
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_non_existent_supplier_returns_404(self):
        url = reverse('app:supplier_cockpit', kwargs={'pk': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_full_cockpit_rendering_with_all_tabs_and_kpis(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/supplier_cockpit.html')

        content = response.content.decode('utf-8')

        # Cabeçalho executivo e identidade visual
        self.assertIn('Botânica Extratos Naturais do Brasil Ltda', content)
        self.assertIn('FOR-001', content)
        self.assertIn('33.444.555/0001-22', content)
        self.assertIn('Qualificado', content)
        self.assertIn('Operacionalmente disponível', content)
        self.assertIn('Sem bloqueios sanitários', content)

        # 5 Abas do Cockpit
        self.assertIn('Dados Cadastrais & Licenças Sanitárias (AFE/VISA)', content)
        self.assertIn('Auditorias de Fornecedor BPF', content)
        self.assertIn('Histórico de Entregas & OOS no Recebimento', content)
        self.assertIn('Matérias-Primas Homologadas', content)
        self.assertIn('Scorecard & Status de Qualificação', content)

        # KPIs
        self.assertIn('Índice IQF / Aceite', content)
        self.assertIn('100,00%', content)
        self.assertIn('Auditorias BPF', content)
        self.assertIn('Pedidos & Entregas', content)

        # Dados da Aba 1 (Licença e Endereço)
        self.assertIn('Autorização de Funcionamento de Empresa - AFE ANVISA', content)
        self.assertIn('Avenida Industrial Farmacêutica', content)
        self.assertIn('Campinas', content)

        # Dados da Aba 2 (Auditoria BPF)
        self.assertIn('AUD-FOR-2026-01', content)
        self.assertIn('Auditoria de Qualificação BPF em Planta Fabril de Extratos', content)

        # Dados da Aba 3 (Recebimento)
        self.assertIn('REC-2026-0001', content)
        self.assertIn('NF-10492', content)

        # Dados da Aba 4 (Matérias-Primas)
        self.assertIn('MP-ALOE-01', content)
        self.assertIn('Extrato Glicólico de Aloe Vera 20%', content)

        # Dados da Aba 5 (Scorecard e 5 Gates)
        self.assertIn('Apto para fornecimento', content)
        self.assertIn('Gate 1: Cadastro e Regularidade Fiscal', content)
        self.assertIn('Gate 2: Licenças Sanitárias e AFE/VISA Vigentes', content)
        self.assertIn('Gate 3: Auditoria BPF e Avaliação Técnica', content)
        self.assertIn('Gate 4: Homologação de Matérias-Primas e Laudos de CQ', content)
        self.assertIn('Gate 5: Parecer Sanitário e Ausência de Bloqueios QA', content)

    def test_sod_audits_tab_permission_segmented(self):
        # Usuário possui apenas permissão cadastral, sem permissão de auditorias
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar auditorias de fornecedor.', content)
        self.assertNotIn('AUD-FOR-2026-01', content)

    def test_sod_deliveries_tab_permission_segmented(self):
        # Usuário sem permissão de compras/recebimentos
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn(
            'Você não possui permissão para visualizar o histórico de compras e entregas.',
            content,
        )
        self.assertNotIn('REC-2026-0001', content)

    def test_sod_products_tab_permission_segmented(self):
        # Usuário sem permissão de produtos
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn(
            'Você não possui permissão para visualizar matérias-primas e insumos.', content
        )
        self.assertNotIn('Extrato Glicólico de Aloe Vera 20%', content)

    def test_scorecard_5_gates_evaluation_qualified_vs_blocked(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['gates_passed_count'], 5)
        self.assertEqual(response.context['regulatory_verdict'], 'Apto para fornecimento')

        # Aplicar Bloqueio Cautelar da Garantia da Qualidade (QA)
        qa_block = QualityBlock.objects.create(
            target_type=QualityBlock.TargetType.SUPPLIER,
            supplier=self.supplier,
            reason='Contaminação microbiana detectada em insumo natural; fornecedor sob investigação.',
            status=QualityBlock.Status.ACTIVE,
            blocked_by=self.user,
            blocked_at=timezone.now(),
        )

        response_blocked = self.client.get(self.cockpit_url)
        self.assertEqual(response_blocked.status_code, 200)
        self.assertFalse(response_blocked.context['gate5_passed'])
        self.assertEqual(
            response_blocked.context['regulatory_verdict'],
            'Fornecimento bloqueado sanitariamente',
        )
        self.assertEqual(response_blocked.context['regulatory_verdict_badge'], 'bg-danger')
        self.assertTrue(response_blocked.context['has_active_block'])

    def test_resource_detail_renders_cockpit_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={'module_slug': 'masters', 'resource_slug': 'partners', 'pk': self.supplier.pk},
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Cockpit do fornecedor (360°)', content)
        self.assertIn(self.cockpit_url, content)
