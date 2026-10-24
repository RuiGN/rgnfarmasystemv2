from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from capa.models import (
    CapaAction,
    CapaApproval,
    CapaEvidence,
    CapaRecord,
    EffectivenessCheck,
)
from deviations.models import (
    DeviationApproval,
    DeviationImpactAssessment,
    DeviationInvestigation,
    QualityEvent,
)
from governance.models import GovernanceAuditLog
from tests.test_capa import create_deviation_source


User = get_user_model()
PASSWORD = 'S3curePass!123'


def make_user(name):
    return User.objects.create_user(
        username=f'{name}@example.com', email=f'{name}@example.com', password=PASSWORD
    )


def make_capa(owner, suffix='001', **extra):
    event, *_ = create_deviation_source(owner, suffix=suffix)
    return CapaRecord.objects.create(
        source_type=CapaRecord.SourceType.DEVIATION,
        deviation_event=event,
        title='CAPA de teste',
        root_cause='Causa raiz.',
        action_plan='Plano de ação.',
        owner=owner,
        due_date=timezone.localdate() + timedelta(days=30),
        opened_by=owner,
        effectiveness_criteria='Sem recorrência em três lotes.',
        **extra,
    )


def make_ready_capa(owner, approver, suffix='001'):
    """CAPA com ação concluída, evidência e aprovação pendente."""
    capa = make_capa(owner, suffix=suffix)
    action = CapaAction.objects.create(
        capa=capa,
        action_type=CapaAction.ActionType.CORRECTIVE,
        title='Ação',
        description='Descrição.',
        responsible=owner,
        due_date=timezone.localdate() + timedelta(days=5),
        evidence_required=True,
    )
    action.complete(user=owner, completion_notes='Executada.')
    CapaEvidence.objects.create(
        capa=capa,
        action=action,
        title='Evidência',
        file_reference='evidencias/a.pdf',
        content_hash='sha256:abc',
        uploaded_by=owner,
    )
    approval = CapaApproval.objects.create(
        capa=capa, approver=approver, role=CapaApproval.Role.QA, required=True
    )
    return capa, approval


def make_check(capa):
    return EffectivenessCheck.objects.create(
        capa=capa, criteria='Sem recorrência.', planned_date=timezone.localdate()
    )


@pytest.mark.django_db
class TestCapaStateMachine:
    def test_close_requires_latest_effectiveness_check_effective(self):
        owner, approver = make_user('c1.owner'), make_user('c1.appr')
        capa, approval = make_ready_capa(owner, approver)
        first = make_check(capa)
        first.verify(result='ok', effective=True, user=owner, evidence_reference='e/1.pdf')
        second = make_check(capa)
        second.verify(result='recorreu', effective=False, user=owner)
        approval.approve(user=approver)

        with pytest.raises(ValidationError) as error:
            capa.close(summary='Resumo.', user=approver)
        assert 'effectiveness' in error.value.message_dict

        third = make_check(capa)
        third.verify(result='ok agora', effective=True, user=owner, evidence_reference='e/3.pdf')
        capa.close(summary='Resumo.', user=approver)
        capa.refresh_from_db()
        assert capa.status == CapaRecord.Status.CLOSED

    def test_close_blocked_from_closed_and_cancelled(self):
        owner, approver = make_user('c2.owner'), make_user('c2.appr')
        capa, approval = make_ready_capa(owner, approver)
        make_check(capa).verify(result='ok', effective=True, user=owner, evidence_reference='e')
        approval.approve(user=approver)
        capa.close(summary='Resumo.', user=approver)
        with pytest.raises(ValidationError) as closed_error:
            capa.close(summary='De novo.', user=approver)
        assert 'status' in closed_error.value.message_dict

        other = make_capa(owner, suffix='002')
        other.cancel('Motivo.')
        with pytest.raises(ValidationError) as cancelled_error:
            other.close(summary='Resumo.', user=approver)
        assert 'status' in cancelled_error.value.message_dict
        with pytest.raises(ValidationError):
            other.cancel('Outra vez.')

    def test_effectiveness_verdict_cannot_be_overwritten(self):
        owner = make_user('c3.owner')
        check = make_check(make_capa(owner))
        check.verify(result='ruim', effective=False, user=owner)
        with pytest.raises(ValidationError) as error:
            check.verify(result='bom', effective=True, user=owner, evidence_reference='e')
        check.refresh_from_db()
        assert 'status' in error.value.message_dict
        assert check.status == EffectivenessCheck.Status.INEFFECTIVE

    def test_approval_only_when_pending_and_decided_by_actor(self):
        owner, approver = make_user('c4.owner'), make_user('c4.appr')
        _capa, approval = make_ready_capa(owner, approver)
        approval.approve(user=approver, comments='ok')
        approval.refresh_from_db()
        assert approval.decided_by == approver
        with pytest.raises(ValidationError):
            approval.approve(user=approver)
        with pytest.raises(ValidationError):
            approval.reject(user=approver, comments='mudei de ideia')
        approval.refresh_from_db()
        assert approval.decision == CapaApproval.Decision.APPROVED

    def test_approval_requires_acting_user(self):
        owner, approver = make_user('c4b.owner'), make_user('c4b.appr')
        _capa, approval = make_ready_capa(owner, approver)
        with pytest.raises(ValidationError):
            approval.approve()

    def test_approval_segregation_of_duties_owner_and_opener(self):
        owner, approver = make_user('c5.owner'), make_user('c5.appr')
        opener = make_user('c5.opener')
        capa, _approval = make_ready_capa(owner, approver)
        capa.opened_by = opener
        capa.save(update_fields=['opened_by', 'updated_at'])
        for author in (owner, opener):
            own = CapaApproval.objects.create(
                capa=capa, approver=author, role=CapaApproval.Role.OWNER, required=False
            )
            with pytest.raises(ValidationError) as error:
                own.approve(user=author)
            assert 'approver' in error.value.message_dict
            with pytest.raises(ValidationError):
                own.reject(user=author, comments='não')
            own.refresh_from_db()
            assert own.decision == CapaApproval.Decision.PENDING

    def test_transitions_write_audit_rows(self):
        owner, approver = make_user('c6.owner'), make_user('c6.appr')
        capa, approval = make_ready_capa(owner, approver)
        make_check(capa).verify(result='ok', effective=True, user=owner, evidence_reference='e')
        approval.approve(user=approver)
        capa.close(summary='Resumo.', user=approver)
        actions = set(
            GovernanceAuditLog.objects.filter(module='capa').values_list('action', flat=True)
        )
        assert {
            'capa.effectiveness.verified',
            'capa.approval.approved',
            'capa.record.closed',
        } <= actions
        row = GovernanceAuditLog.objects.get(action='capa.record.closed')
        assert row.target_record_id == str(capa.pk)
        assert row.user == approver
        assert row.safe_context['to_status'] == CapaRecord.Status.CLOSED


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestCapaApi:
    def test_approver_immutable_on_put_and_patch(self):
        owner, approver = make_user('a1.owner'), make_user('a1.appr')
        other = make_user('a1.other')
        capa, approval = make_ready_capa(owner, approver)
        client = APIClient()
        client.force_authenticate(owner)
        url = f'/api/capa/approvals/{approval.pk}/'
        patch = client.patch(url, {'approver': other.pk}, format='json')
        put = client.put(
            url,
            {'capa': capa.pk, 'approver': other.pk, 'role': 'qa', 'required': True},
            format='json',
        )
        approval.refresh_from_db()
        assert patch.status_code == 400
        assert put.status_code == 400
        assert approval.approver == approver

    def test_closed_capa_business_fields_rejected(self):
        owner, approver = make_user('a2.owner'), make_user('a2.appr')
        capa, approval = make_ready_capa(owner, approver)
        make_check(capa).verify(result='ok', effective=True, user=owner, evidence_reference='e')
        approval.approve(user=approver)
        capa.close(summary='Resumo.', user=approver)
        client = APIClient()
        client.force_authenticate(owner)
        response = client.patch(
            f'/api/capa/records/{capa.pk}/', {'root_cause': 'Reescrita.'}, format='json'
        )
        capa.refresh_from_db()
        assert response.status_code == 400
        assert 'status' in response.json()
        assert capa.root_cause == 'Causa raiz.'

    def test_open_capa_still_editable(self):
        owner = make_user('a3.owner')
        capa = make_capa(owner)
        client = APIClient()
        client.force_authenticate(owner)
        response = client.patch(
            f'/api/capa/records/{capa.pk}/', {'root_cause': 'Revisada.'}, format='json'
        )
        assert response.status_code == 200, response.content


def make_event(author, suffix='101'):
    event, *_ = create_deviation_source(author, suffix=suffix)
    return event


def make_concluded_event(author, approver, suffix='101'):
    event = make_event(author, suffix=suffix)
    investigation = DeviationInvestigation.objects.create(
        event=event,
        investigator=author,
        immediate_actions='Imediatas.',
        containment_actions='Contenção.',
    )
    investigation.conclude('Causa.', 'Impacto.', 'Conclusão.', user=author)
    DeviationImpactAssessment.objects.create(
        event=event, impacts_quality=True, summary='Impacto.', assessed_by=author
    ).complete(user=author)
    approval = DeviationApproval.objects.create(
        event=event, approver=approver, role=DeviationApproval.Role.QA, required=True
    )
    return event, investigation, approval


@pytest.mark.django_db
class TestDeviationStateMachine:
    def test_close_happy_path_and_blocked_when_final(self):
        author, approver = make_user('d1.author'), make_user('d1.appr')
        event, _inv, approval = make_concluded_event(author, approver)
        approval.approve(user=approver)
        event.close(summary='Resumo.', user=approver)
        event.refresh_from_db()
        assert event.status == QualityEvent.Status.CLOSED
        with pytest.raises(ValidationError) as closed_error:
            event.close(summary='De novo.', user=approver)
        assert 'status' in closed_error.value.message_dict

        cancelled = make_event(author, suffix='102')
        cancelled.cancel('Motivo.')
        with pytest.raises(ValidationError):
            cancelled.close(summary='Resumo.', user=approver)
        with pytest.raises(ValidationError):
            cancelled.cancel('Outra vez.')

    def test_conclude_only_from_open_states(self):
        author, approver = make_user('d2.author'), make_user('d2.appr')
        _event, investigation, _approval = make_concluded_event(author, approver)
        with pytest.raises(ValidationError) as error:
            investigation.conclude('Outra.', 'Outro.', 'Outra.', user=author)
        investigation.refresh_from_db()
        assert 'status' in error.value.message_dict
        assert investigation.root_cause == 'Causa.'

        cancelled = DeviationInvestigation.objects.create(
            event=make_event(author, suffix='103'),
            immediate_actions='x',
            containment_actions='y',
            status=DeviationInvestigation.Status.CANCELLED,
        )
        with pytest.raises(ValidationError):
            cancelled.conclude('C.', 'I.', 'K.', user=author)

    def test_approval_pending_only_and_sod(self):
        author, approver = make_user('d3.author'), make_user('d3.appr')
        event, _inv, approval = make_concluded_event(author, approver)
        own = DeviationApproval.objects.create(
            event=event, approver=author, role=DeviationApproval.Role.QC, required=False
        )
        with pytest.raises(ValidationError) as error:
            own.approve(user=author)
        assert 'approver' in error.value.message_dict
        with pytest.raises(ValidationError):
            own.reject(user=author, comments='não')
        with pytest.raises(ValidationError):
            approval.approve()

        approval.approve(user=approver)
        approval.refresh_from_db()
        assert approval.decided_by == approver
        with pytest.raises(ValidationError):
            approval.reject(user=approver, comments='mudei')
        approval.refresh_from_db()
        assert approval.decision == DeviationApproval.Decision.APPROVED

    def test_transitions_write_audit_rows(self):
        author, approver = make_user('d4.author'), make_user('d4.appr')
        event, _investigation, approval = make_concluded_event(author, approver)
        approval.approve(user=approver)
        event.close(summary='Resumo.', user=approver)
        actions = set(
            GovernanceAuditLog.objects.filter(module='deviations').values_list('action', flat=True)
        )
        assert {
            'deviations.investigation.concluded',
            'deviations.approval.approved',
            'deviations.event.closed',
        } <= actions
        row = GovernanceAuditLog.objects.get(action='deviations.event.closed')
        assert row.target_record_id == str(event.pk)
        assert row.user == approver


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestDeviationApi:
    def test_approver_immutable_on_put_and_patch(self):
        author, approver = make_user('e1.author'), make_user('e1.appr')
        other = make_user('e1.other')
        event, _inv, approval = make_concluded_event(author, approver)
        client = APIClient()
        client.force_authenticate(author)
        url = f'/api/deviations/approvals/{approval.pk}/'
        patch = client.patch(url, {'approver': other.pk}, format='json')
        put = client.put(
            url,
            {'event': event.pk, 'approver': other.pk, 'role': 'qa', 'required': True},
            format='json',
        )
        approval.refresh_from_db()
        assert patch.status_code == 400
        assert put.status_code == 400
        assert approval.approver == approver

    def test_closed_event_edit_rejected(self):
        author, approver = make_user('e2.author'), make_user('e2.appr')
        event, _inv, approval = make_concluded_event(author, approver)
        approval.approve(user=approver)
        event.close(summary='Resumo.', user=approver)
        client = APIClient()
        client.force_authenticate(author)
        response = client.patch(
            f'/api/deviations/events/{event.pk}/', {'description': 'Reescrito.'}, format='json'
        )
        event.refresh_from_db()
        assert response.status_code == 400
        assert 'status' in response.json()
        assert event.description != 'Reescrito.'

    def test_open_event_still_editable(self):
        author = make_user('e3.author')
        event = make_event(author)
        client = APIClient()
        client.force_authenticate(author)
        response = client.patch(
            f'/api/deviations/events/{event.pk}/', {'description': 'Revisado.'}, format='json'
        )
        assert response.status_code == 200, response.content
