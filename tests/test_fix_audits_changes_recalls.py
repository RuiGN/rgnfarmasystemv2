from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from governance.models import GovernanceAuditLog

from tests.test_audits import create_audit_context
from tests.test_changes import create_change_context
from tests.test_recalls import create_recalls_context


User = get_user_model()


def make_user(name):
    return User.objects.create_user(
        username=f'{name}@example.com', email=f'{name}@example.com', password='S3curePass!123'
    )


def audit_rows(action):
    return GovernanceAuditLog.objects.filter(action=action)


class AuditStateGuardTests(TestCase):
    def _plan(self):
        from audits.models import AuditPlan, AuditProgram

        auditor = make_user('fix.auditor')
        supplier, _document = create_audit_context(auditor, suffix='FIX')
        program = AuditProgram.objects.create(
            audit_type=AuditProgram.AuditType.SUPPLIER,
            title='Programa fix',
            year=timezone.localdate().year,
            scope='Escopo.',
            criteria='Critérios.',
            owner=auditor,
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate() + timedelta(days=365),
        )
        plan = AuditPlan.objects.create(
            program=program,
            audit_type=AuditPlan.AuditType.SUPPLIER,
            supplier=supplier,
            title='Auditoria fix',
            scope='Escopo.',
            criteria='Critérios.',
            agenda='Agenda.',
            lead_auditor=auditor,
            auditee_name='Fornecedor',
            area='Garantia da Qualidade',
            scheduled_start=timezone.now() + timedelta(days=1),
            scheduled_end=timezone.now() + timedelta(days=2),
        )
        return auditor, plan

    def test_report_issue_only_from_draft_and_does_not_overwrite(self):
        from audits.models import AuditReport

        auditor, plan = self._plan()
        report = AuditReport.objects.create(
            audit=plan, executive_summary='Resumo.', conclusion='Conclusão.'
        )
        report.issue(user=auditor)
        report.refresh_from_db()
        first_issued_at = report.issued_at
        assert report.status == AuditReport.Status.ISSUED
        assert audit_rows('audits.report.issued').count() == 1

        with pytest.raises(ValidationError) as reissue:
            report.issue(user=make_user('fix.other'))

        report.refresh_from_db()
        assert 'status' in reissue.value.message_dict
        assert report.issued_at == first_issued_at
        assert report.issued_by == auditor
        assert audit_rows('audits.report.issued').count() == 1

    def test_finding_close_only_from_open_states_and_writes_audit(self):
        from audits.models import AuditFinding

        auditor, plan = self._plan()
        finding = AuditFinding.objects.create(
            audit=plan,
            classification=AuditFinding.Classification.OBSERVATION,
            criticality=AuditFinding.Criticality.MINOR,
            title='Achado',
            description='Descrição.',
            responsible=auditor,
            due_date=timezone.localdate() + timedelta(days=10),
        )
        finding.close(user=auditor)
        finding.refresh_from_db()
        assert finding.status == AuditFinding.Status.CLOSED
        assert audit_rows('audits.finding.closed').count() == 1

        with pytest.raises(ValidationError) as closed_again:
            finding.close(user=auditor)
        assert 'status' in closed_again.value.message_dict

        finding.status = AuditFinding.Status.CANCELLED
        finding.save(update_fields=['status'])
        with pytest.raises(ValidationError) as cancelled:
            finding.close(user=auditor)
        assert 'status' in cancelled.value.message_dict
        assert audit_rows('audits.finding.closed').count() == 1


class ChangeApprovalGuardTests(TestCase):
    def _change(self):
        from changes.models import ChangeApproval, ChangeControl

        owner = make_user('fix.change.owner')
        submitter = make_user('fix.change.submitter')
        approver = make_user('fix.change.approver')
        _unit, product, lot, supplier, document = create_change_context(owner, suffix='FIX')
        change = ChangeControl.objects.create(
            change_type=ChangeControl.ChangeType.PERMANENT,
            title='Mudança fix',
            scope='Escopo.',
            justification='Justificativa.',
            affected_areas='QA',
            system_reference='MES',
            validation_plan='Plano.',
            impact_summary='Impacto.',
            owner=owner,
            due_date=timezone.localdate() + timedelta(days=30),
            requested_by=owner,
        )
        change.submit(user=submitter)
        approval = ChangeApproval.objects.create(
            change=change, approver=approver, role=ChangeApproval.Role.QA, required=True
        )
        return change, approval, submitter, approver

    def test_approve_happy_path_and_double_decision_rejected(self):
        from changes.models import ChangeApproval

        _change, approval, _submitter, approver = self._change()
        approval.approve(user=approver, comments='Ok.')
        approval.refresh_from_db()
        assert approval.decision == ChangeApproval.Decision.APPROVED
        assert approval.decided_by == approver
        assert audit_rows('changes.approval.approved').count() == 1

        with pytest.raises(ValidationError) as again:
            approval.reject(user=approver, comments='Mudei de ideia.')
        with pytest.raises(ValidationError):
            approval.approve(user=approver)
        approval.refresh_from_db()
        assert 'decision' in again.value.message_dict
        assert approval.decision == ChangeApproval.Decision.APPROVED

    def test_reject_happy_path_writes_audit(self):
        from changes.models import ChangeApproval

        _change, approval, _submitter, approver = self._change()
        approval.reject(user=approver, comments='Risco.')
        approval.refresh_from_db()
        assert approval.decision == ChangeApproval.Decision.REJECTED
        assert audit_rows('changes.approval.rejected').count() == 1

    def test_decision_blocked_when_change_already_closed_state(self):
        from changes.models import ChangeControl

        change, approval, _submitter, approver = self._change()
        ChangeControl.objects.filter(pk=change.pk).update(status=ChangeControl.Status.CANCELLED)
        approval.refresh_from_db()
        with pytest.raises(ValidationError) as blocked:
            approval.approve(user=approver)
        assert 'change' in blocked.value.message_dict

    def test_only_designated_approver_can_decide(self):
        _change, approval, _submitter, _approver = self._change()
        intruder = make_user('fix.change.intruder')
        with pytest.raises(ValidationError) as wrong_user:
            approval.approve(user=intruder)
        assert 'decided_by' in wrong_user.value.message_dict

    def test_sod_submitter_cannot_decide_or_approve_for_implementation(self):
        from changes.models import ChangeApproval

        change, approval, submitter, approver = self._change()
        # Aprovador designado é o próprio autor: SoD bloqueia.
        ChangeApproval.objects.filter(pk=approval.pk).update(approver=submitter)
        approval.refresh_from_db()
        with pytest.raises(ValidationError) as sod:
            approval.approve(user=submitter)
        assert 'decided_by' in sod.value.message_dict
        assert audit_rows('changes.approval.approved').count() == 0

        # approve_for_implementation: submitter != approved_by.
        from changes.models import ChangeAssessment

        ChangeApproval.objects.filter(pk=approval.pk).update(
            approver=approver,
            decision=ChangeApproval.Decision.APPROVED,
            decided_by=approver,
            decided_at=timezone.now(),
        )
        assessment = ChangeAssessment.objects.create(
            change=change,
            department=ChangeAssessment.Department.QA,
            assessor=approver,
            impact_description='Pendente.',
        )
        assessment.complete(
            impact_level=ChangeAssessment.ImpactLevel.LOW,
            impact_description='Baixo.',
            required_actions='Nenhuma.',
            user=approver,
        )
        with pytest.raises(ValidationError) as sod_change:
            change.approve_for_implementation(user=submitter)
        assert 'approved_by' in sod_change.value.message_dict

        change.approve_for_implementation(user=approver)
        assert audit_rows('changes.change.approved_for_implementation').count() == 1


class RecallGuardTests(TestCase):
    def _complaint(self, owner, suffix='FIX'):
        from recalls.models import MarketComplaint

        product, lot, customer, sales_order, fiscal_document, crm_complaint, sample, document = (
            create_recalls_context(owner, suffix=suffix)
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
            description='Queixa técnica para validação de máquina de estados.',
        )
        return complaint, product, lot, customer, sales_order, fiscal_document

    def test_market_complaint_close_failure_does_not_persist_pending_state(self):
        from recalls.models import MarketComplaint

        owner = make_user('fix.recall.owner')
        complaint, *_ = self._complaint(owner)
        complaint.start_triage(user=owner)
        complaint.start_investigation(user=owner)

        with pytest.raises(ValidationError) as missing_reference:
            complaint.close(summary='Sem comunicação regulatória.', user=owner)

        complaint.refresh_from_db()
        assert 'regulatory_communication_reference' in missing_reference.value.message_dict
        assert complaint.status == MarketComplaint.Status.INVESTIGATION
        assert audit_rows('recalls.complaint.closed').count() == 0

        complaint.record_regulatory_communication(reference='ANVISA-FIX-1', user=owner)
        complaint.close(summary='Encerrada.', user=owner)
        complaint.refresh_from_db()
        assert complaint.status == MarketComplaint.Status.CLOSED
        assert audit_rows('recalls.complaint.closed').count() == 1

    def _campaign(self, owner):
        from recalls.models import RecallCampaign

        complaint, product, lot, customer, sales_order, fiscal_document = self._complaint(owner)
        campaign = RecallCampaign.objects.create(
            campaign_type=RecallCampaign.CampaignType.RECALL,
            trigger=RecallCampaign.Trigger.TECHNICAL_COMPLAINT,
            product=product,
            stock_lot=lot,
            complaint=complaint,
            criticality=RecallCampaign.Criticality.CRITICAL,
            reason='Risco potencial.',
            decision_date=timezone.localdate(),
            target_completion_date=timezone.localdate() + timedelta(days=30),
            responsible=owner,
        )
        return campaign, customer, sales_order, fiscal_document

    def test_campaign_approve_requires_user(self):
        from recalls.models import RecallCampaign

        owner = make_user('fix.recall.camp.owner')
        campaign, *_ = self._campaign(owner)
        with pytest.raises(ValidationError) as no_user:
            campaign.approve()
        campaign.refresh_from_db()
        assert 'approved_by' in no_user.value.message_dict
        assert campaign.status == RecallCampaign.Status.DRAFT

        approver = make_user('fix.recall.approver')
        campaign.approve(user=approver)
        campaign.refresh_from_db()
        assert campaign.status == RecallCampaign.Status.APPROVED
        assert audit_rows('recalls.campaign.approved').count() == 1

    def test_campaign_cancel_blocked_once_in_execution(self):
        from recalls.models import RecallCampaign, RecallImpactedCustomer

        owner = make_user('fix.recall.cancel.owner')
        campaign, customer, sales_order, fiscal_document = self._campaign(owner)
        campaign.approve(user=make_user('fix.recall.cancel.approver'))
        RecallImpactedCustomer.objects.create(
            campaign=campaign,
            customer=customer,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            quantity_distributed=Decimal('10.0000'),
            quantity_recalled=Decimal('10.0000'),
            contact_name='RT',
            contact_email='rt@example.com',
        )
        campaign.start(user=owner)

        with pytest.raises(ValidationError) as in_execution:
            campaign.cancel(reason='Tarde demais.')
        campaign.refresh_from_db()
        assert 'status' in in_execution.value.message_dict
        assert campaign.status == RecallCampaign.Status.IN_EXECUTION

    def test_campaign_cancel_allowed_from_draft_and_audited(self):
        from recalls.models import RecallCampaign

        owner = make_user('fix.recall.cancel.draft.owner')
        campaign, *_ = self._campaign(owner)
        campaign.cancel(reason='Decisão revertida.')
        campaign.refresh_from_db()
        assert campaign.status == RecallCampaign.Status.CANCELLED
        assert audit_rows('recalls.campaign.cancelled').count() == 1

    def test_communication_send_validates_before_mutating_customer(self):
        from recalls.models import RecallCommunication, RecallImpactedCustomer

        owner = make_user('fix.recall.comm.owner')
        campaign, customer, sales_order, fiscal_document = self._campaign(owner)
        impacted = RecallImpactedCustomer.objects.create(
            campaign=campaign,
            customer=customer,
            sales_order=sales_order,
            fiscal_document=fiscal_document,
            quantity_distributed=Decimal('10.0000'),
            quantity_recalled=Decimal('10.0000'),
            contact_name='RT',
            contact_email='rt@example.com',
        )
        communication = RecallCommunication.objects.create(
            campaign=campaign,
            impacted_customer=impacted,
            channel=RecallCommunication.Channel.EMAIL,
            subject='Comunicado',
            message='Mensagem.',
            content_hash='sha256:fix-comm',
        )
        before = impacted.response_status

        # Sem usuário, full_clean falha (enviada exige sent_by): nada deve ser alterado.
        with pytest.raises(ValidationError):
            communication.send(user=None)

        impacted.refresh_from_db()
        communication.refresh_from_db()
        assert impacted.response_status == before
        assert communication.status == RecallCommunication.Status.DRAFT
        assert audit_rows('recalls.communication.sent').count() == 0

        communication.send(user=owner)
        impacted.refresh_from_db()
        assert impacted.response_status == RecallImpactedCustomer.ResponseStatus.CONTACTED
        assert communication.status == RecallCommunication.Status.SENT
        assert audit_rows('recalls.communication.sent').count() == 1
