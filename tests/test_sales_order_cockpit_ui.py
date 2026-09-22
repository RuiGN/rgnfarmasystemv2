from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from crm.models import CustomerProfile, SalesOrder, SalesOrderItem
from finance.models import (
    ChartOfAccount,
    FinancialAccount,
    FinancialCategory,
    FinancialSettlement,
    FinancialTitle,
)
from fiscal.models import FiscalCompany, FiscalDocument
from inventory.models import (
    StockBalance,
    StockLot,
    StockMovement,
    StockQualityStatus,
    StorageLocation,
    Warehouse,
)
from masters.models import BusinessPartner, Product, Site, UnitOfMeasure


class SalesOrderCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='sales-analyst',
            email='sales@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar o pedido de venda
        view_order_perm = Permission.objects.get(
            content_type__app_label='crm', codename='view_salesorder'
        )
        self.user.user_permissions.add(view_order_perm)

        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')

        self.customer = BusinessPartner.objects.create(
            legal_name='Drogaria Cosméticos Saúde S.A.',
            trade_name='Drogarias Saúde',
            document='12.345.678/0001-90',
            partner_type=BusinessPartner.PartnerType.CUSTOMER,
            email='contato@drogariasaude.com.br',
        )

        self.product = Product.objects.create(
            code='PA-SHAMP-01',
            description='Shampoo Hidratante Argan 300ml',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        today = timezone.now().date()
        self.order = SalesOrder.objects.create(
            customer=self.customer,
            requested_delivery_date=today + timedelta(days=10),
            payment_terms_days=30,
            status=SalesOrder.Status.APPROVED,
            total_amount=Decimal('5000.0000'),
            shipping_street='Av. Paulista',
            shipping_street_number='1000',
            shipping_neighborhood='Bela Vista',
            shipping_zipcode='01310-100',
        )

        self.cockpit_url = reverse('app:sales_order_cockpit', kwargs={'pk': self.order.pk})

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

        # Identificação e cliente
        self.assertContains(response, self.order.order_number)
        self.assertContains(response, 'Drogaria Cosméticos Saúde S.A.')
        self.assertContains(response, '12.345.678/0001-90')
        self.assertContains(response, '30 dias')

        # Badges e KPIs
        self.assertContains(response, 'Aprovado')
        self.assertContains(response, 'Valor total do pedido')
        self.assertContains(response, '5000,00')
        self.assertContains(response, 'Limite e análise de crédito')
        self.assertContains(response, 'Disponibilidade WMS')
        self.assertContains(response, 'Faturamento e liquidação')

    def test_sod_items_tab_permissions(self):
        item = SalesOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('100.0000'),
            unit_price=Decimal('50.0000'),
            discount_percent=Decimal('0.0000'),
            promised_date=timezone.now().date() + timedelta(days=7),
        )

        # Sem permissão de itens -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar os itens')
        self.assertNotContains(response, 'PA-SHAMP-01')

        # Com permissão de itens -> tabela de itens renderizada
        perm = Permission.objects.get(
            content_type__app_label='crm', codename='view_salesorderitem'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'PA-SHAMP-01')
        self.assertContains(response, 'Shampoo Hidratante Argan 300ml')
        self.assertContains(response, '100,0000')
        self.assertContains(response, '50,00')

    def test_sod_credit_tab_permissions(self):
        profile = CustomerProfile.objects.create(
            customer=self.customer,
            credit_limit=Decimal('50000.0000'),
            credit_hold=False,
            regulatory_hold=False,
            payment_terms_days=30,
            is_active=True,
        )

        # Sem permissão -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar a análise de crédito')

        # Com permissão -> Limites e régua de crédito
        perm = Permission.objects.get(
            content_type__app_label='crm', codename='view_customerprofile'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Limite de crédito total')
        self.assertContains(response, '50000,00')
        self.assertContains(response, 'Bloqueio financeiro / crédito')
        self.assertContains(response, 'Bloqueio sanitário / regulatório')
        self.assertContains(response, 'Regular')
        self.assertContains(response, 'Conforme')

    def test_sod_inventory_tab_permissions(self):
        site = Site.objects.create(code='ST-01', name='Site SP', site_type=Site.SiteType.PLANT)
        warehouse = Warehouse.objects.create(
            site=site,
            code='EXP-01',
            name='Almoxarifado de Expedição',
            warehouse_type=Warehouse.WarehouseType.FINISHED_PRODUCT,
        )
        location = StorageLocation.objects.create(
            warehouse=warehouse, code='EXP-A01', name='Expedição Box 1'
        )
        lot = StockLot.objects.create(
            product=self.product,
            lot_number='LOT-SHAMP-001',
            quality_status=StockQualityStatus.APPROVED,
            manufacturing_date=timezone.now().date() - timedelta(days=10),
            expiry_date=timezone.now().date() + timedelta(days=700),
        )
        balance = StockBalance.objects.create(
            product=self.product,
            lot=lot,
            warehouse=warehouse,
            location=location,
            quality_status=StockQualityStatus.APPROVED,
            quantity=Decimal('200.0000'),
            reserved_quantity=Decimal('0.0000'),
            unit=self.unit_un,
        )

        item = SalesOrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=Decimal('50.0000'),
            unit_price=Decimal('50.0000'),
        )

        # Sem permissão de estoque -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar o estoque')

        # Com permissão de estoque -> Tabela WMS de conferência
        perm_stock = Permission.objects.get(
            content_type__app_label='inventory', codename='view_stockbalance'
        )
        self.user.user_permissions.add(perm_stock)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Disponibilidade de lotes aprovados e endereçamento físico')
        self.assertContains(response, 'LOT-SHAMP-001')
        self.assertContains(response, 'EXP-01')
        self.assertContains(response, 'Atendido')

    def test_sod_fiscal_tab_permissions(self):
        fiscal_company = FiscalCompany.objects.create(
            legal_name='RGN Farma Cosméticos Ltda',
            document='00.111.222/0001-33',
            tax_regime=FiscalCompany.TaxRegime.LUCRO_REAL,
            zipcode='01310-000',
            street='Av. Paulista',
            street_number='500',
            neighborhood='Bela Vista',
        )
        fiscal_doc = FiscalDocument.objects.create(
            company=fiscal_company,
            partner=self.customer,
            document_type=FiscalDocument.DocumentType.OUTBOUND,
            operation_type=FiscalDocument.OperationType.SALE,
            number='10050',
            series='1',
            issue_date=timezone.now().date(),
            operation_date=timezone.now().date(),
            status=FiscalDocument.Status.APPROVED,
            emission_status=FiscalDocument.EmissionStatus.AUTHORIZED,
            access_key='35260900111222000133550010000100501234567890',
            authorization_protocol='135260000012345',
            notes=f'Ref: Pedido de venda {self.order.order_number}',
            total_products=Decimal('5000.0000'),
            total_amount=Decimal('5000.0000'),
        )

        # Sem permissão fiscal -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar documentos fiscais')

        # Com permissão fiscal -> Dados da NF-e
        perm_fiscal = Permission.objects.get(
            content_type__app_label='fiscal', codename='view_fiscaldocument'
        )
        self.user.user_permissions.add(perm_fiscal)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'NF-e 10050 (Série 1)')
        self.assertContains(response, 'Autorizada')
        self.assertContains(response, '135260000012345')
        self.assertContains(response, '35260900111222000133')

    def test_sod_finance_tab_permissions(self):
        chart_account = ChartOfAccount.objects.create(
            code='1.01.01',
            name='Receitas de Vendas',
            account_type=ChartOfAccount.AccountType.REVENUE,
        )
        category = FinancialCategory.objects.create(
            code='REC-VENDAS',
            name='Receitas de Vendas de Cosméticos',
            category_type=FinancialCategory.CategoryType.RECEIVABLE,
            chart_account=chart_account,
        )
        account = FinancialAccount.objects.create(
            code='BCO-ITAU-01',
            name='Itaú Conta Corrente',
            account_type=FinancialAccount.AccountType.BANK,
        )
        title = FinancialTitle.objects.create(
            title_type=FinancialTitle.TitleType.RECEIVABLE,
            source_type=FinancialTitle.SourceType.SALE,
            partner=self.customer,
            category=category,
            financial_account=account,
            sale_reference=self.order.order_number,
            status=FinancialTitle.Status.PARTIALLY_SETTLED,
            due_date=timezone.now().date() + timedelta(days=30),
            original_amount=Decimal('5000.0000'),
            paid_amount=Decimal('2500.0000'),
            open_amount=Decimal('2500.0000'),
        )
        settlement = FinancialSettlement.objects.create(
            title=title,
            financial_account=account,
            settlement_date=timezone.now().date(),
            method=FinancialSettlement.Method.PIX,
            amount=Decimal('2500.0000'),
            net_amount=Decimal('2500.0000'),
            status=FinancialSettlement.Status.ACTIVE,
        )

        # Sem permissão financeira -> aviso SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar os títulos financeiros')

        # Com permissão financeira e de baixas
        perm_title = Permission.objects.get(
            content_type__app_label='finance', codename='view_financialtitle'
        )
        perm_settle = Permission.objects.get(
            content_type__app_label='finance', codename='view_financialsettlement'
        )
        self.user.user_permissions.add(perm_title, perm_settle)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Contas a receber (Títulos)')
        self.assertContains(response, title.title_number)
        self.assertContains(response, 'Baixado parcialmente')
        self.assertContains(response, '50% liquidado')
        self.assertContains(response, 'Baixas e conciliações financeiras')
        self.assertContains(response, 'PIX')
        self.assertContains(response, '2500,00')

    def test_o2c_readiness_gates(self):
        # Conceder permissões para testar a régua Order-to-Cash
        perm_title = Permission.objects.get(
            content_type__app_label='finance', codename='view_financialtitle'
        )
        self.user.user_permissions.add(perm_title)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Régua de prontidão Order-to-Cash (5 Gates)')
        self.assertContains(response, '1. Validação Comercial do Pedido')
        self.assertContains(response, '2. Análise de Crédito e Risco')
        self.assertContains(response, '3. Disponibilidade de Estoque (WMS)')
        self.assertContains(response, '4. Faturamento Fiscal (NF-e)')
        self.assertContains(response, '5. Liquidação Financeira')

    def test_resource_detail_view_contains_cockpit_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={'module_slug': 'crm', 'resource_slug': 'orders', 'pk': self.order.pk},
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cockpit do pedido (O2C)')
        self.assertContains(response, self.cockpit_url)
