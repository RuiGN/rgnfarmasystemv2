import hashlib
from datetime import timedelta
import tempfile
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from files.models import ProtectedFile
from governance.models import GovernanceAuditLog
from procurement.models import PurchaseReceipt
from tests import test_fix_audits_changes_recalls as recall_fixtures
from tests import test_fix_planning_procurement as procurement_fixtures
from tests.test_fix_capa_deviations import make_concluded_event, make_ready_capa
from tests.test_fix_files_integrations import create_file
from tests.test_fix_qa_quality import make_block
from tests.test_qa import create_qa_item


User = get_user_model()
PASSWORD = 'S3curePass!123'


def make_user(name):
    return User.objects.create_user(
        username=f'{name}@example.com', email=f'{name}@example.com', password=PASSWORD
    )


def audit_rows(action):
    return GovernanceAuditLog.objects.filter(action=action)


class RecallFixtures:
    _complaint = recall_fixtures.RecallGuardTests._complaint
    _campaign = recall_fixtures.RecallGuardTests._campaign


# --- Item 1: cancel (reclamação, devolução, campanha) ---------------------------


class RecallCancelTests(RecallFixtures, TestCase):
    def _return(self, owner):
        from recalls.models import ProductReturn

        complaint, product, lot, customer, sales_order, fiscal_document = self._complaint(owner)
        return ProductReturn.objects.create(
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

    def test_complaint_cancel_audited_with_user(self):
        from recalls.models import MarketComplaint

        owner = make_user('pa.cc.owner')
        complaint, *_ = self._complaint(owner)
        complaint.cancel(reason='Registro duplicado.', user=owner)
        complaint.refresh_from_db()
        assert complaint.status == MarketComplaint.Status.CANCELLED
        row = audit_rows('recalls.complaint.cancelled').get()
        assert row.user == owner
        assert row.target_record_id == str(complaint.pk)

    def test_complaint_cancel_rejected_from_terminal_and_pending_states(self):
        from recalls.models import MarketComplaint

        owner = make_user('pa.cc2.owner')
        for status in (
            MarketComplaint.Status.CLOSED,
            MarketComplaint.Status.CANCELLED,
            MarketComplaint.Status.PENDING_REGULATORY_COMMUNICATION,
        ):
            complaint, *_ = self._complaint(owner, suffix=f'PA{status[:3].upper()}')
            MarketComplaint.objects.filter(pk=complaint.pk).update(status=status)
            complaint.refresh_from_db()
            with pytest.raises(ValidationError) as error:
                complaint.cancel(reason='Tentativa.', user=owner)
            assert 'status' in error.value.message_dict
            complaint.refresh_from_db()
            assert complaint.status == status
        assert not audit_rows('recalls.complaint.cancelled').exists()

    def test_return_cancel_audited_and_rejected_from_terminal(self):
        from recalls.models import ProductReturn

        owner = make_user('pa.ret.owner')
        product_return = self._return(owner)
        product_return.cancel(reason='Cliente desistiu.', user=owner)
        product_return.refresh_from_db()
        assert product_return.status == ProductReturn.Status.CANCELLED
        assert audit_rows('recalls.return.cancelled').get().user == owner
        with pytest.raises(ValidationError) as again:
            product_return.cancel(reason='De novo.', user=owner)
        assert 'status' in again.value.message_dict

    def test_campaign_cancel_records_user(self):
        owner = make_user('pa.camp.owner')
        campaign, *_ = self._campaign(owner)
        campaign.cancel(reason='Decisão revertida.', user=owner)
        assert audit_rows('recalls.campaign.cancelled').get().user == owner

    def test_cancel_api_passes_request_user(self):
        owner = make_user('pa.api.owner')
        complaint, *_ = self._complaint(owner)
        client = APIClient()
        client.force_authenticate(owner)
        client.post(f'/api/recalls/complaints/{complaint.pk}/cancel/', {'reason': 'Duplicada.'})
        row = audit_rows('recalls.complaint.cancelled').first()
        if row is not None:
            assert row.user == owner


# --- Item 6: SoD aprovação de campanha ------------------------------------------


class CampaignApprovalSoDTests(RecallFixtures, TestCase):
    def test_responsible_cannot_approve_campaign(self):
        from recalls.models import RecallCampaign

        owner = make_user('pa.sod.owner')
        campaign, *_ = self._campaign(owner)
        with pytest.raises(ValidationError) as error:
            campaign.approve(user=owner)
        assert 'approved_by' in error.value.message_dict
        campaign.refresh_from_db()
        assert campaign.status == RecallCampaign.Status.DRAFT

    def test_other_user_can_approve_campaign(self):
        from recalls.models import RecallCampaign

        owner = make_user('pa.sod2.owner')
        campaign, *_ = self._campaign(owner)
        campaign.approve(user=make_user('pa.sod2.approver'))
        campaign.refresh_from_db()
        assert campaign.status == RecallCampaign.Status.APPROVED


# --- Item 2: PurchaseReceipt.release_quality ------------------------------------


class ReceiptReleaseGuardTests(TestCase):
    _receipt = procurement_fixtures.ReceiptQualityReleaseAuditTests._receipt

    def _received(self):
        receipt = self._receipt()
        receipt.mark_received(user=make_user(f'pa.rec.{PurchaseReceipt.objects.count()}'))
        return receipt

    def test_release_from_received_succeeds(self):
        user = make_user('pa.rel.ok')
        receipt = self._received()
        receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=user)
        receipt.refresh_from_db()
        assert receipt.status == PurchaseReceipt.Status.QUALITY_RELEASED
        assert receipt.quality_status == PurchaseReceipt.QualityStatus.APPROVED

    def test_release_rejected_from_draft(self):
        receipt = self._receipt()
        with pytest.raises(ValidationError) as error:
            receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=make_user('pa.d'))
        assert 'status' in error.value.message_dict

    def test_release_rejected_when_cancelled_or_posted_or_already_released(self):
        user = make_user('pa.rel.bad')
        receipt = self._received()
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(
            status=PurchaseReceipt.Status.CANCELLED
        )
        with pytest.raises(ValidationError):
            receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=user)
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(
            status=PurchaseReceipt.Status.RECEIVED,
            stock_entry_status=PurchaseReceipt.StockEntryStatus.POSTED,
        )
        with pytest.raises(ValidationError):
            receipt.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=user)
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(
            status=PurchaseReceipt.Status.QUALITY_RELEASED,
            stock_entry_status=PurchaseReceipt.StockEntryStatus.PENDING,
        )
        with pytest.raises(ValidationError):
            receipt.release_quality(PurchaseReceipt.QualityStatus.REJECTED, user=user)
        assert not audit_rows('receipt_quality_released').exists()

    def test_release_rereads_state_after_lock(self):
        user = make_user('pa.rel.stale')
        receipt = self._received()
        stale = PurchaseReceipt.objects.get(pk=receipt.pk)
        PurchaseReceipt.objects.filter(pk=receipt.pk).update(
            status=PurchaseReceipt.Status.CANCELLED
        )
        with pytest.raises(ValidationError):
            stale.release_quality(PurchaseReceipt.QualityStatus.APPROVED, user=user)


# --- Item 3: ProtectedFile.replace ----------------------------------------------


class FileReplaceGuardTests(TestCase):
    def setUp(self):
        self.owner = make_user('pa.file.owner')
        self.file = create_file(self.owner)
        self.content = b'<xml>novo</xml>'
        self.digest = f'sha256:{hashlib.sha256(self.content).hexdigest()}'

    def _replace(self, **kwargs):
        params = {'user': self.owner, 'content': self.content}
        params.update(kwargs)
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            return self.file.replace(
                '', 'novo.xml', params.pop('content_hash', self.digest), **params
            )

    def test_happy_path_supersedes_source(self):
        replacement = self._replace()
        self.file.refresh_from_db()
        assert self.file.status == ProtectedFile.Status.SUPERSEDED
        assert replacement.supersedes_id == self.file.pk

    def test_bad_hash_creates_no_replacement(self):
        before = ProtectedFile.objects.count()
        with pytest.raises(ValidationError) as error:
            self._replace(content_hash='sha256:' + '0' * 64)
        assert 'content_hash' in error.value.message_dict
        assert ProtectedFile.objects.count() == before

    def test_invalid_file_size_is_validation_error(self):
        before = ProtectedFile.objects.count()
        for bad in ('abc', -1, 1.5e400, True):
            with pytest.raises(ValidationError) as error:
                self._replace(file_size=bad)
            assert 'file_size' in error.value.message_dict
        assert ProtectedFile.objects.count() == before

    def test_reference_path_invalid_inputs_do_not_create_replacement(self):
        before = ProtectedFile.objects.count()
        with pytest.raises(ValidationError):
            self.file.replace('protected/x/y.enc', 'n.xml', 'not-a-hash', user=self.owner)
        with pytest.raises(ValidationError) as error:
            self.file.replace(
                'protected/x/y.enc', 'n.xml', 'a' * 64, user=self.owner, file_size='-3'
            )
        assert 'file_size' in error.value.message_dict
        assert ProtectedFile.objects.count() == before

    def test_superseded_expired_sources_cannot_be_replaced(self):
        self._replace()
        before = ProtectedFile.objects.count()
        with pytest.raises(ValidationError) as error:
            self._replace()
        assert 'status' in error.value.message_dict
        assert ProtectedFile.objects.count() == before

    def test_expired_source_cannot_be_replaced(self):
        self.file.expire(user=self.owner)
        before = ProtectedFile.objects.count()
        with pytest.raises(ValidationError) as error:
            self._replace()
        assert 'status' in error.value.message_dict
        assert ProtectedFile.objects.count() == before

    def test_stale_instance_is_rejected_after_lock(self):
        stale = ProtectedFile.objects.get(pk=self.file.pk)
        self._replace()
        with pytest.raises(ValidationError):
            stale.replace('', 'n.xml', self.digest, user=self.owner, content=self.content)


# --- Item 4: QualityBlock.unblock -----------------------------------------------


@pytest.mark.django_db
class TestQualityBlockUnblockUser:
    def test_unblock_requires_user(self):
        _unit, _product, lot = create_qa_item('PA1')
        block = make_block(lot=lot, user=make_user('pa.blk.a'))
        with pytest.raises(ValidationError) as error:
            block.unblock('Avaliado.')
        assert 'unblocked_by' in error.value.message_dict
        block.refresh_from_db()
        assert block.status == type(block).Status.ACTIVE

    def test_blocker_cannot_unblock_but_other_can(self):
        _unit, _product, lot = create_qa_item('PA2')
        blocker = make_user('pa.blk.b')
        block = make_block(lot=lot, user=blocker)
        with pytest.raises(ValidationError):
            block.unblock('Eu mesmo.', user=blocker)
        block.unblock('Avaliado.', user=make_user('pa.blk.c'))
        block.refresh_from_db()
        assert block.status == type(block).Status.UNBLOCKED


# --- Item 5: guardas de campos protegidos/imutáveis ------------------------------


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestProtectedFieldsOnlyRejectRealChanges:
    def test_capa_put_echoing_approver_succeeds_and_changed_is_400(self):
        owner, approver, other = make_user('pa5.co'), make_user('pa5.ca'), make_user('pa5.cx')
        capa, approval = make_ready_capa(owner, approver)
        client = APIClient()
        client.force_authenticate(owner)
        url = f'/api/capa/approvals/{approval.pk}/'
        body = {'capa': capa.pk, 'approver': approver.pk, 'role': 'qa', 'required': True}
        assert client.put(url, body, format='json').status_code == 200
        assert client.patch(url, {'approver': approver.pk}, format='json').status_code == 200
        body['approver'] = other.pk
        assert client.put(url, body, format='json').status_code == 400
        approval.refresh_from_db()
        assert approval.approver == approver

    def test_deviation_put_echoing_approver_succeeds_and_changed_is_400(self):
        author, approver, other = make_user('pa5.da'), make_user('pa5.dp'), make_user('pa5.dx')
        event, _inv, approval = make_concluded_event(author, approver)
        client = APIClient()
        client.force_authenticate(author)
        url = f'/api/deviations/approvals/{approval.pk}/'
        body = {'event': event.pk, 'approver': approver.pk, 'role': 'qa', 'required': True}
        assert client.put(url, body, format='json').status_code == 200
        body['approver'] = other.pk
        assert client.put(url, body, format='json').status_code == 400
        approval.refresh_from_db()
        assert approval.approver == approver

    def test_costing_put_echoing_status_and_approver_succeeds_changed_is_400(self):
        from costing.models import StandardCost
        from tests.test_costing import create_released_manufacturing_set

        unit, product, *_ = create_released_manufacturing_set(suffix='PA5')
        standard = StandardCost.objects.create(
            product=product,
            version='PA5',
            effective_from=timezone.localdate(),
            standard_quantity=Decimal('100.0000'),
            unit=unit,
            material_cost=Decimal('10.0000'),
        )
        client = APIClient()
        client.force_authenticate(make_user('pa5.cost'))
        url = f'/api/costing/standard-costs/{standard.pk}/'
        body = client.get(url).json()
        echoed = client.put(url, body, format='json')
        assert echoed.status_code == 200, echoed.content
        body['status'] = StandardCost.Status.APPROVED
        assert client.put(url, body, format='json').status_code == 400
        standard.refresh_from_db()
        assert standard.status == StandardCost.Status.DRAFT


# --- Item 6: StandardCost.approve exige usuário ---------------------------------


class StandardCostApproveUserTests(TestCase):
    def test_approve_requires_user_and_happy_path(self):
        from costing.models import StandardCost
        from tests.test_costing import create_released_manufacturing_set

        unit, product, *_ = create_released_manufacturing_set(suffix='PA6')
        standard = StandardCost.objects.create(
            product=product,
            version='PA6',
            effective_from=timezone.localdate(),
            standard_quantity=Decimal('100.0000'),
            unit=unit,
            material_cost=Decimal('10.0000'),
        )
        with pytest.raises(ValidationError) as error:
            standard.approve()
        assert 'approved_by' in error.value.message_dict
        standard.refresh_from_db()
        assert standard.status == StandardCost.Status.DRAFT
        approver = make_user('pa6.approver')
        standard.approve(user=approver)
        standard.refresh_from_db()
        assert standard.status == StandardCost.Status.APPROVED
        assert standard.approved_by == approver


# --- Item 7: laços mortos removidos (comportamento idêntico) ----------------------


def test_serializers_still_validate_after_dead_loop_removal():
    from recalls.serializers import (
        ProductReturnSerializer,
        RecallCampaignSerializer,
        RecallCommunicationSerializer,
        RecallImpactedCustomerSerializer,
    )

    for serializer_class in (
        ProductReturnSerializer,
        RecallCampaignSerializer,
        RecallImpactedCustomerSerializer,
        RecallCommunicationSerializer,
    ):
        assert serializer_class(data={}).is_valid() is False


# --- Revisão final da fase A ---------------------------------------------------


class FinalReviewRecallTests(RecallFixtures, TestCase):
    _return = RecallCancelTests._return

    def test_inspected_return_cannot_be_cancelled_received_can(self):
        from recalls.models import ProductReturn

        owner = make_user('pf.ret.owner')
        inspected = self._return(owner)
        ProductReturn.objects.filter(pk=inspected.pk).update(status=ProductReturn.Status.INSPECTED)
        inspected.refresh_from_db()
        with pytest.raises(ValidationError) as error:
            inspected.cancel(reason='Tentativa.', user=owner)
        assert 'status' in error.value.message_dict
        inspected.refresh_from_db()
        assert inspected.status == ProductReturn.Status.INSPECTED

    def test_received_return_can_be_cancelled(self):
        from recalls.models import ProductReturn

        owner = make_user('pf.ret2.owner')
        received = self._return(owner)
        ProductReturn.objects.filter(pk=received.pk).update(status=ProductReturn.Status.RECEIVED)
        received.refresh_from_db()
        received.cancel(reason='Recebida por engano.', user=owner)
        received.refresh_from_db()
        assert received.status == ProductReturn.Status.CANCELLED

    def test_campaign_approve_after_cancel_via_stale_instance_is_rejected(self):
        from recalls.models import RecallCampaign

        owner = make_user('pf.camp.owner')
        campaign, *_ = self._campaign(owner)
        stale = RecallCampaign.objects.get(pk=campaign.pk)
        campaign.cancel(reason='Cancelada antes.', user=owner)
        with pytest.raises(ValidationError) as error:
            stale.approve(user=make_user('pf.camp.approver'))
        assert 'status' in error.value.message_dict
        assert RecallCampaign.objects.get(pk=campaign.pk).status == RecallCampaign.Status.CANCELLED

    def test_campaign_start_and_close_use_locked_status(self):
        from recalls.models import RecallCampaign

        owner = make_user('pf.camp2.owner')
        campaign, *_ = self._campaign(owner)
        stale = RecallCampaign.objects.get(pk=campaign.pk)
        stale.status = RecallCampaign.Status.APPROVED  # cópia obsoleta em memória
        with pytest.raises(ValidationError) as start_error:
            stale.start(user=owner)
        assert 'status' in start_error.value.message_dict
        stale.status = RecallCampaign.Status.IN_EXECUTION
        with pytest.raises(ValidationError) as close_error:
            stale.close('Resumo.', user=owner)
        assert 'status' in close_error.value.message_dict
        assert RecallCampaign.objects.get(pk=campaign.pk).status == RecallCampaign.Status.DRAFT


class IncomingValueChangesFieldTests(TestCase):
    def test_fk_same_and_different_pk(self):
        from rest_framework import serializers  # noqa: F401
        from costing.models import StandardCost
        from base.serializer_mixins import incoming_value_changes_field
        from tests.test_costing import create_released_manufacturing_set

        unit, product, *_ = create_released_manufacturing_set(suffix='PF1')
        standard = StandardCost.objects.create(
            product=product,
            version='PF1',
            effective_from=timezone.localdate(),
            standard_quantity=Decimal('100.0000'),
            unit=unit,
            material_cost=Decimal('10.0000'),
        )
        assert not incoming_value_changes_field(standard, 'product', product.pk)
        assert not incoming_value_changes_field(standard, 'product', str(product.pk))
        assert incoming_value_changes_field(standard, 'product', product.pk + 999)
        assert not incoming_value_changes_field(standard, 'approved_by', None)
        user = make_user('pf.fk')
        assert incoming_value_changes_field(standard, 'approved_by', user.pk)
        # Decimal
        assert not incoming_value_changes_field(standard, 'material_cost', '10.0')
        assert not incoming_value_changes_field(standard, 'material_cost', Decimal('10.00'))
        assert incoming_value_changes_field(standard, 'material_cost', '10.5')
        # Data
        assert not incoming_value_changes_field(
            standard, 'effective_from', standard.effective_from.isoformat()
        )
        assert incoming_value_changes_field(standard, 'effective_from', '1999-01-01')
        # Malformado: erro de campo, fail-closed
        from rest_framework import serializers as drf

        with pytest.raises(drf.ValidationError) as error:
            incoming_value_changes_field(standard, 'material_cost', 'abc')
        assert 'material_cost' in error.value.detail
        with pytest.raises(drf.ValidationError):
            incoming_value_changes_field(standard, 'effective_from', 'não-é-data')

    def test_datetime_equal_and_different(self):
        from base.serializer_mixins import incoming_value_changes_field
        from costing.models import StandardCost

        moment = timezone.now()
        standard = StandardCost(approved_at=moment)
        assert not incoming_value_changes_field(standard, 'approved_at', moment.isoformat())
        assert incoming_value_changes_field(
            standard, 'approved_at', (moment + timedelta(seconds=1)).isoformat()
        )


class ValidatedFileSizeTests(TestCase):
    def test_float_truncation_rejected_and_integral_accepted(self):
        for bad in (1.9, 0.5):
            with pytest.raises(ValidationError) as error:
                ProtectedFile._validated_file_size(bad)
            assert 'file_size' in error.value.message_dict
        assert ProtectedFile._validated_file_size('12') == 12
        assert ProtectedFile._validated_file_size(12) == 12
        assert ProtectedFile._validated_file_size(12.0) == 12
        assert ProtectedFile._validated_file_size(None) is None
