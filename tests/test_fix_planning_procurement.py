from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from governance.models import GovernanceAuditLog
from planning.models import MPSLine, MRPRun, MRPSuggestion, MasterProductionSchedule
from procurement.models import PurchaseOrder, PurchaseReceipt, PurchaseRequisition
from tests.test_planning import create_planning_product
from tests.test_procurement import create_purchase_item, create_supplier

User = get_user_model()


def create_calculated_run():
    today = timezone.localdate()
    unit, product = create_planning_product()
    schedule = MasterProductionSchedule.objects.create(
        code='MPS-FIX',
        name='Plano correcao',
        period_start=today,
        period_end=today + timedelta(days=30),
    )
    MPSLine.objects.create(
        schedule=schedule,
        product=product,
        due_date=today + timedelta(days=10),
        demand_quantity=Decimal('120.0000'),
        unit=unit,
        source=MPSLine.Source.FORECAST,
    )
    run = MRPRun.objects.create(schedule=schedule)
    run.calculate()
    return run


class MRPRecalculationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='mrp@example.com', email='mrp@example.com', password='S3curePass!123'
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_recalculation_allowed_without_requisitions(self):
        run = create_calculated_run()
        first_ids = set(run.suggestions.values_list('pk', flat=True))
        assert first_ids

        run.calculate()

        assert run.suggestions.count() == len(first_ids)
        assert not first_ids & set(run.suggestions.values_list('pk', flat=True))

    def test_recalculation_blocked_when_requisition_exists(self):
        run = create_calculated_run()
        suggestion = run.suggestions.first()
        PurchaseRequisition.create_from_mrp_suggestion(suggestion, justification='Ruptura')

        with pytest.raises(ValidationError) as error:
            run.calculate()

        assert 'requisições' in str(error.value.message_dict['id'])
        assert MRPSuggestion.objects.filter(pk=suggestion.pk).exists()

    def test_api_recalculation_blocked_returns_400(self):
        run = create_calculated_run()
        PurchaseRequisition.create_from_mrp_suggestion(
            run.suggestions.first(), justification='Ruptura'
        )

        response = self.client.post(f'/api/planning/mrp-runs/{run.pk}/calculate/', {})

        assert response.status_code == 400

    def test_api_recalculation_refreshes_suggestions_count(self):
        run = create_calculated_run()

        response = self.client.post(f'/api/planning/mrp-runs/{run.pk}/calculate/', {})

        assert response.status_code == 200
        assert response.json()['suggestions_count'] == run.suggestions.count()

    def test_list_counts_match(self):
        run = create_calculated_run()

        response = self.client.get('/api/planning/mrp-runs/')

        assert response.json()['results'][0]['suggestions_count'] == run.suggestions.count()


class ReceiptQualityReleaseAuditTests(TestCase):
    def _receipt(self):
        unit, product = create_purchase_item()
        order = PurchaseOrder.objects.create(
            order_number='PC-FIX',
            supplier=create_supplier(),
            issue_date=timezone.localdate(),
            expected_delivery_date=timezone.localdate() + timedelta(days=5),
        )
        return PurchaseReceipt.objects.create(
            receipt_number='REC-FIX',
            order=order,
            fiscal_document_number='NF-1',
            physical_received_at=timezone.now(),
        )

    def test_release_quality_records_audit_with_user(self):
        user = User.objects.create_user(
            username='qa@example.com', email='qa@example.com', password='S3curePass!123'
        )
        receipt = self._receipt()

        receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=user)

        log = GovernanceAuditLog.objects.get(
            action='receipt_quality_released', target_record_id=str(receipt.pk)
        )
        assert log.user == user
        assert log.safe_context['to_quality_status'] == PurchaseReceipt.QualityStatus.APPROVED

    def test_release_quality_requires_user(self):
        receipt = self._receipt()

        with pytest.raises(TypeError):
            receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED)

    def test_release_quality_invalid_status_writes_no_audit(self):
        user = User.objects.create_user(
            username='qa2@example.com', email='qa2@example.com', password='S3curePass!123'
        )
        receipt = self._receipt()

        with pytest.raises(ValidationError):
            receipt.release_quality('pending', user=user)

        assert not GovernanceAuditLog.objects.filter(action='receipt_quality_released').exists()
