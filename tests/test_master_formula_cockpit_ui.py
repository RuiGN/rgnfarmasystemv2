from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from formulations.models import FormulaComponent, MasterFormula
from masters.models import BusinessPartner, Product, UnitOfMeasure
from procurement.models import (
    PurchaseOrder,
    PurchaseOrderItem,
    PurchaseReceipt,
    PurchaseReceiptItem,
    PurchaseRequisition,
    PurchaseRequisitionItem,
    QuotationRequest,
    SupplierQuotation,
)


class MasterFormulaCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='operador-formulas',
            email='operador@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Grant formulations.view_masterformula
        view_formula_perm = Permission.objects.get(
            content_type__app_label='formulations', codename='view_masterformula'
        )
        self.user.user_permissions.add(view_formula_perm)

        self.unit_kg = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')

        self.finished_product = Product.objects.create(
            code='PA-CREME-01',
            description='Creme Hidratante Facial 50g',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        self.raw_material = Product.objects.create(
            code='MP-OLEO-01',
            description='Óleo de Jojoba Puro',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit_kg,
            status=Product.Status.APPROVED,
        )

        self.formula = MasterFormula.objects.create(
            product=self.finished_product,
            code='MF-CREME-01',
            version=1,
            status=MasterFormula.Status.APPROVED,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit_kg,
            expected_yield_percent=Decimal('98.0000'),
        )

        self.component = FormulaComponent.objects.create(
            formula=self.formula,
            line_number=1,
            material=self.raw_material,
            role=FormulaComponent.Role.ACTIVE,
            quantity=Decimal('15.0000'),
            unit=self.unit_kg,
            expected_loss_percent=Decimal('2.0000'),
        )

        self.supplier = BusinessPartner.objects.create(
            code='FORN-001',
            legal_name='Fornecedora de Insumos Naturais Ltda',
            trade_name='BioInsumos',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
            qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
            is_active=True,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        url = reverse('app:master_formula_cockpit', kwargs={'pk': self.formula.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_user_without_view_permission_is_denied(self):
        self.user.user_permissions.clear()
        url = reverse('app:master_formula_cockpit', kwargs={'pk': self.formula.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_404_for_nonexistent_formula(self):
        url = reverse('app:master_formula_cockpit', kwargs={'pk': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_authorized_user_can_view_cockpit(self):
        url = reverse('app:master_formula_cockpit', kwargs={'pk': self.formula.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        self.assertIn('Ciclo de abastecimento', content)
        self.assertIn(self.formula.code, content)
        self.assertIn(self.finished_product.description, content)
        self.assertIn(self.raw_material.description, content)
        self.assertIn('1. Formulação e BOM', content)
        self.assertIn('2. Orçamentos e cotações', content)
        self.assertIn('3. Pedidos de compra', content)
        self.assertIn('4. Recebimento e lotes', content)

    def test_detail_page_exposes_cockpit_button_for_authorized_user(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': self.formula.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)

        cockpit_url = reverse('app:master_formula_cockpit', kwargs={'pk': self.formula.pk})
        self.assertContains(response, cockpit_url)
        self.assertContains(response, 'Ciclo de abastecimento')

    def test_detail_page_hides_cockpit_button_without_permission(self):
        self.user.user_permissions.clear()
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': self.formula.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 403)

    def test_procurement_tabs_with_related_records(self):
        # Grant procurement permissions to user
        perms = Permission.objects.filter(
            content_type__app_label='procurement',
            codename__in=[
                'view_quotationrequest',
                'view_purchaseorder',
                'view_purchasereceipt',
            ],
        )
        self.user.user_permissions.add(*perms)

        # 1. Create Requisition and Quotation
        req = PurchaseRequisition.objects.create(
            requisition_number='REQ-TEST-001',
            requested_by=self.user,
            justification='Abastecimento de insumo para formulação',
            status=PurchaseRequisition.Status.SUBMITTED,
        )
        PurchaseRequisitionItem.objects.create(
            requisition=req,
            product=self.raw_material,
            quantity=Decimal('50.0000'),
            unit=self.unit_kg,
        )
        rfq = QuotationRequest.objects.create(
            rfq_number='COT-TEST-001',
            requisition=req,
            status=QuotationRequest.Status.SENT,
        )
        SupplierQuotation.objects.create(
            rfq=rfq,
            supplier=self.supplier,
            quoted_quantity=Decimal('50.0000'),
            unit_price=Decimal('120.0000'),
            tax_amount=Decimal('0.0000'),
            freight_amount=Decimal('50.0000'),
            status=SupplierQuotation.Status.SUBMITTED,
        )

        # 2. Create Purchase Order
        po = PurchaseOrder.objects.create(
            order_number='PC-TEST-001',
            supplier=self.supplier,
            requisition=req,
            status=PurchaseOrder.Status.APPROVED,
        )
        po_item = PurchaseOrderItem.objects.create(
            order=po,
            product=self.raw_material,
            quantity=Decimal('50.0000'),
            unit=self.unit_kg,
            unit_price=Decimal('120.0000'),
        )

        # 3. Create Purchase Receipt
        receipt = PurchaseReceipt.objects.create(
            receipt_number='REC-TEST-001',
            order=po,
            fiscal_document_number='NF-998877',
            status=PurchaseReceipt.Status.RECEIVED,
            quality_status=PurchaseReceipt.QualityStatus.PENDING,
        )
        PurchaseReceiptItem.objects.create(
            receipt=receipt,
            order_item=po_item,
            product=self.raw_material,
            received_quantity=Decimal('50.0000'),
            unit=self.unit_kg,
            lot_number='LOTE-FORN-2026',
        )

        url = reverse('app:master_formula_cockpit', kwargs={'pk': self.formula.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Check that quotations, purchase orders and receipts appear
        self.assertIn('COT-TEST-001', content)
        self.assertIn('PC-TEST-001', content)
        self.assertIn('REC-TEST-001', content)
        self.assertIn('NF-998877', content)
        self.assertIn('BioInsumos', content)
