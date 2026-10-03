from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from masters.models import BusinessPartner, Product, UnitOfMeasure


User = get_user_model()


def create_purchase_item(suffix='001', requires_approved_supplier=True):
    unit = UnitOfMeasure.objects.create(
        code=f'KG-{suffix}',
        name='Quilograma',
        symbol='kg',
    )
    product = Product.objects.create(
        code=f'MP-{suffix}',
        description='Insumo farmacêutico',
        item_type=Product.ItemType.RAW_MATERIAL,
        unit=unit,
        status=Product.Status.APPROVED,
        requires_approved_supplier=requires_approved_supplier,
    )
    return unit, product


def create_supplier(suffix='001', qualified=True, blocked=False):
    valid_until = (
        timezone.localdate() + timedelta(days=30)
        if qualified
        else timezone.localdate() - timedelta(days=1)
    )
    return BusinessPartner.objects.create(
        code=f'FOR-{suffix}',
        legal_name=f'Fornecedor {suffix}',
        partner_type=BusinessPartner.PartnerType.SUPPLIER,
        qualification_status=(
            BusinessPartner.QualificationStatus.QUALIFIED
            if qualified
            else BusinessPartner.QualificationStatus.EXPIRED
        ),
        qualification_valid_until=valid_until,
        is_blocked=blocked,
    )


def create_mrp_suggestion(product, quantity=Decimal('75.0000')):
    from planning.models import MRPRun, MRPSuggestion, MasterProductionSchedule

    today = timezone.localdate()
    schedule = MasterProductionSchedule.objects.create(
        code='MPS-COMPRAS',
        name='Plano compras',
        period_start=today,
        period_end=today + timedelta(days=30),
    )
    run = MRPRun.objects.create(schedule=schedule)
    return MRPSuggestion.objects.create(
        run=run,
        product=product,
        suggestion_type=MRPSuggestion.SuggestionType.BUY,
        due_date=today + timedelta(days=10),
        required_quantity=quantity,
        available_quantity=Decimal('0.0000'),
        net_requirement=quantity,
        suggested_quantity=quantity,
        lead_time_days=7,
        release_date=today + timedelta(days=3),
        alert_level=MRPSuggestion.AlertLevel.SHORTAGE,
    )


class ProcurementModelTests(TestCase):
    def test_requisition_is_created_from_mrp_suggestion_and_approved(self):
        from procurement.models import PurchaseRequisition

        unit, product = create_purchase_item()
        suggestion = create_mrp_suggestion(product)

        requisition = PurchaseRequisition.create_from_mrp_suggestion(
            suggestion, justification='Ruptura MRP'
        )
        item = requisition.items.get()

        assert requisition.source == PurchaseRequisition.Source.MRP
        assert requisition.status == PurchaseRequisition.Status.DRAFT
        assert requisition.requisition_number.startswith(f'REQ-{timezone.localdate():%Y%m%d}-')
        assert item.product == product
        assert item.quantity == Decimal('75.0000')
        assert item.unit == unit
        assert item.mrp_suggestion == suggestion

        requisition.submit()
        requisition.approve()

        assert requisition.status == PurchaseRequisition.Status.APPROVED
        assert requisition.approved_at is not None

    def test_rfq_selects_best_valid_supplier_quotation(self):
        from procurement.models import (
            PurchaseRequisition,
            PurchaseRequisitionItem,
            QuotationRequest,
            SupplierQuotation,
        )

        unit, product = create_purchase_item()
        requisition = PurchaseRequisition.objects.create(
            requisition_number='REQ-0001',
            source=PurchaseRequisition.Source.MANUAL,
            justification='Compra planejada',
        )
        PurchaseRequisitionItem.objects.create(
            requisition=requisition,
            product=product,
            quantity=Decimal('100.0000'),
            unit=unit,
            needed_by=timezone.localdate() + timedelta(days=15),
        )
        requisition.submit()
        requisition.approve()
        rfq = QuotationRequest.objects.create(
            rfq_number='COT-0001',
            requisition=requisition,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        expensive_supplier = create_supplier(suffix='001')
        best_supplier = create_supplier(suffix='002')
        expired_supplier = create_supplier(suffix='003', qualified=False)
        SupplierQuotation.objects.create(
            rfq=rfq,
            supplier=expensive_supplier,
            quoted_quantity=Decimal('100.0000'),
            unit_price=Decimal('10.0000'),
            lead_time_days=10,
            supplier_performance_score=Decimal('88.00'),
            valid_until=timezone.localdate() + timedelta(days=10),
        )
        expected_best = SupplierQuotation.objects.create(
            rfq=rfq,
            supplier=best_supplier,
            quoted_quantity=Decimal('100.0000'),
            unit_price=Decimal('9.5000'),
            lead_time_days=15,
            supplier_performance_score=Decimal('82.00'),
            valid_until=timezone.localdate() + timedelta(days=10),
        )
        SupplierQuotation.objects.create(
            rfq=rfq,
            supplier=expired_supplier,
            quoted_quantity=Decimal('100.0000'),
            unit_price=Decimal('7.0000'),
            lead_time_days=5,
            supplier_performance_score=Decimal('96.00'),
            valid_until=timezone.localdate() + timedelta(days=10),
        )

        assert rfq.best_quotation() == expected_best
        assert expected_best.total_amount == Decimal('950.0000')

    def test_purchase_order_blocks_unqualified_supplier_for_controlled_item(self):
        from procurement.models import PurchaseOrder, PurchaseOrderItem

        unit, product = create_purchase_item(requires_approved_supplier=True)
        expired_supplier = create_supplier(suffix='001', qualified=False)
        order = PurchaseOrder.objects.create(
            order_number='PC-0001',
            supplier=expired_supplier,
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        PurchaseOrderItem.objects.create(
            order=order,
            product=product,
            quantity=Decimal('10.0000'),
            unit=unit,
            unit_price=Decimal('12.5000'),
        )

        with pytest.raises(ValidationError) as error:
            order.approve()

        assert 'supplier' in error.value.message_dict

    def test_purchase_order_blocks_active_supplier_restriction_event(self):
        from procurement.models import PurchaseOrder, PurchaseOrderItem, SupplierQualificationEvent

        unit, product = create_purchase_item(requires_approved_supplier=True)
        supplier = create_supplier(suffix='001', qualified=True)
        SupplierQualificationEvent.objects.create(
            supplier=supplier,
            event_type=SupplierQualificationEvent.EventType.RESTRICTION,
            event_date=timezone.localdate(),
            valid_until=timezone.localdate() + timedelta(days=30),
            blocks_purchases=True,
            description='Restrição ativa por auditoria',
        )
        order = PurchaseOrder.objects.create(
            order_number='PC-0001',
            supplier=supplier,
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        PurchaseOrderItem.objects.create(
            order=order,
            product=product,
            quantity=Decimal('10.0000'),
            unit=unit,
            unit_price=Decimal('12.5000'),
        )

        with pytest.raises(ValidationError) as error:
            order.approve()

        assert 'supplier' in error.value.message_dict

    def test_purchase_receipt_validates_quality_and_stock_quantities(self):
        from procurement.models import (
            PurchaseOrder,
            PurchaseOrderItem,
            PurchaseReceipt,
            PurchaseReceiptItem,
        )

        unit, product = create_purchase_item()
        supplier = create_supplier()
        order = PurchaseOrder.objects.create(
            order_number='PC-0001',
            supplier=supplier,
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        order_item = PurchaseOrderItem.objects.create(
            order=order,
            product=product,
            quantity=Decimal('50.0000'),
            unit=unit,
            unit_price=Decimal('10.0000'),
        )
        receipt = PurchaseReceipt.objects.create(
            receipt_number='REC-0001',
            order=order,
            fiscal_document_number='NF-123',
            physical_received_at=timezone.now(),
            quality_status=PurchaseReceipt.QualityStatus.APPROVED,
        )
        item = PurchaseReceiptItem.objects.create(
            receipt=receipt,
            order_item=order_item,
            product=product,
            received_quantity=Decimal('50.0000'),
            accepted_quantity=Decimal('48.0000'),
            rejected_quantity=Decimal('2.0000'),
            unit=unit,
            lot_number='LOTE-001',
            expiry_date=timezone.localdate() + timedelta(days=365),
        )

        # post_stock sem destino apenas marcava flags; o contrato seguro exige entrada real.
        from inventory.models import StockBalance, StockMovement
        from tests.test_inventory import create_stock_address

        warehouse, location = create_stock_address(suffix='PROCUREMENT-POST')
        receipt.post_stock(warehouse=warehouse, location=location)
        receipt.refresh_from_db()

        assert item.accepted_quantity + item.rejected_quantity == item.received_quantity
        assert receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.POSTED
        movement = StockMovement.objects.get(source_purchase_receipt_item=item)
        assert movement.quantity == item.accepted_quantity
        assert StockBalance.objects.get(lot=movement.lot, location=location).quantity == Decimal(
            '48.0000'
        )

        invalid_item = PurchaseReceiptItem(
            receipt=receipt,
            order_item=order_item,
            product=product,
            received_quantity=Decimal('10.0000'),
            accepted_quantity=Decimal('9.0000'),
            rejected_quantity=Decimal('2.0000'),
            unit=unit,
        )
        with pytest.raises(ValidationError) as error:
            invalid_item.full_clean()
        assert 'accepted_quantity' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestProcurementApi:
    def test_requisition_api_omits_legacy_scope_and_runs_approval_workflow(self):
        from procurement.models import PurchaseRequisition

        unit, product = create_purchase_item()
        user = User.objects.create_user(
            username='compras@example.com', email='compras@example.com', password='S3curePass!123'
        )
        client = APIClient()
        client.force_authenticate(user)

        create_response = client.post(
            '/api/procurement/requisitions/',
            {
                'requisition_number': 'REQ-API-001',
                'source': PurchaseRequisition.Source.MANUAL,
                'justification': 'Compra manual',
            },
        )
        assert create_response.status_code == 201

        item_response = client.post(
            '/api/procurement/requisition-items/',
            {
                'requisition': create_response.json()['id'],
                'product': product.id,
                'quantity': '25.0000',
                'unit': unit.id,
                'needed_by': str(timezone.localdate() + timedelta(days=7)),
            },
        )
        assert item_response.status_code == 201

        submit_response = client.post(
            f'/api/procurement/requisitions/{create_response.json()["id"]}/submit/',
            {},
        )
        approve_response = client.post(
            f'/api/procurement/requisitions/{create_response.json()["id"]}/approve/',
            {},
        )

        assert submit_response.status_code == 200
        assert approve_response.status_code == 200
        assert approve_response.json()['status'] == PurchaseRequisition.Status.APPROVED

    @pytest.mark.permission_strict
    def test_procurement_api_requires_view_permission(self):
        from procurement.models import PurchaseRequisition

        PurchaseRequisition.objects.create(
            requisition_number='REQ-0001',
            source=PurchaseRequisition.Source.MANUAL,
            justification='Compra manual',
        )
        user = User.objects.create_user(
            username='compras@example.com', email='compras@example.com', password='S3curePass!123'
        )
        client = APIClient()
        client.login(username=user.username, password='S3curePass!123')

        response = client.get('/api/procurement/requisitions/')

        assert response.status_code == 403
