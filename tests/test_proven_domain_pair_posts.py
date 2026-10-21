"""Real model-form POSTs for the remaining explicitly proved domain pairs."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from tests.test_proven_related_dependencies import metadata, resource_form

pytestmark = pytest.mark.django_db


def assert_pair(model, fields, good, mismatches):
    form = resource_form(model, fields, data=good)
    assert form.is_valid(), form.errors
    for name, value in mismatches.items():
        invalid = resource_form(model, fields, data={**good, name: value})
        assert not invalid.is_valid()
        assert name in invalid.errors
        assert metadata(invalid, name)
        with pytest.raises(ValueError):
            invalid.save()


def test_fiscal_tax_item_document_post_uses_same_map_as_model():
    from fiscal.models import FiscalTax
    from tests.test_fiscal import create_outbound_fiscal_document

    docs = [create_outbound_fiscal_document(f'77{i}') for i in range(2)]
    items = [doc.items.get() for doc in docs]
    before = FiscalTax.objects.count()
    assert_pair(
        FiscalTax,
        ('document', 'item', 'tax_kind', 'base_amount'),
        {'document': docs[0].pk, 'item': items[0].pk, 'tax_kind': 'icms', 'base_amount': '1'},
        {'item': items[1].pk},
    )
    assert FiscalTax.objects.count() == before


def test_training_session_requirement_post_and_generic_job_position():
    from training.models import TrainingEnrollment, TrainingRequirement, TrainingSession

    user = get_user_model().objects.create_user('proven-trainer', 'trainer@example.invalid')
    requirements, sessions = [], []
    for i in range(2):
        requirement = TrainingRequirement.objects.create(
            title=f'Boas práticas {i}',
            training_type=TrainingRequirement.TrainingType.REGULATORY,
            area='Qualidade',
        )
        session = TrainingSession.objects.create(
            requirement=requirement,
            title=f'Turma {i}',
            instructor=user,
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
        )
        requirements.append(requirement)
        sessions.append(session)
        requirement.full_clean()
        session.full_clean()
    assert_pair(
        TrainingEnrollment,
        ('requirement', 'session', 'user'),
        {'requirement': requirements[0].pk, 'session': sessions[0].pk, 'user': user.pk},
        {'session': sessions[1].pk},
    )
    assert not TrainingEnrollment.objects.exists()


@pytest.mark.parametrize(
    'model_label', ('training.TrainingRequirement', 'training.TrainingMatrixRequirement')
)
def test_training_generic_function_keeps_null_job_position_semantics(model_label):
    from django.apps import apps
    from training.models import JobPosition, WorkFunction

    a, b = [JobPosition.objects.create(title=f'Analista {i}', area='Qualidade') for i in range(2)]
    generic = WorkFunction.objects.create(name='Conferência geral', area='Qualidade')
    bound = WorkFunction.objects.create(
        name='Conferência específica', area='Qualidade', job_position=a
    )
    model = apps.get_model(model_label)
    fields = ('job_position', 'function')
    form = resource_form(model, fields, data={'job_position': b.pk, 'function': generic.pk})
    assert form.is_valid(), form.errors
    expected = ['*', ''] if model_label == 'training.TrainingRequirement' else ['*']
    assert metadata(form, 'function')[0]['values'][str(generic.pk)] == expected
    strict = resource_form(model, fields, data={'job_position': a.pk, 'function': bound.pk})
    assert strict.is_valid(), strict.errors
    invalid = resource_form(model, fields, data={'job_position': b.pk, 'function': bound.pk})
    assert not invalid.is_valid()
    assert 'function' in invalid.errors
    with pytest.raises(ValueError):
        invalid.save()


def test_audit_checklist_post_does_not_accept_foreign_audit():
    from audits.models import AuditChecklistItem, AuditFinding, AuditPlan, AuditProgram

    user = get_user_model().objects.create_user('proven-auditor', 'auditor@example.invalid')
    today = timezone.localdate()
    program = AuditProgram.objects.create(
        title='Programa sintético',
        audit_type='internal',
        year=today.year,
        scope='BPF',
        criteria='ISO 22716',
        owner=user,
        starts_on=today,
        ends_on=today + timedelta(days=30),
    )
    plans, items = [], []
    for i in range(2):
        plan = AuditPlan.objects.create(
            program=program,
            title=f'Auditoria {i}',
            audit_type='internal',
            scope='BPF',
            criteria='ISO 22716',
            agenda='Conferência',
            lead_auditor=user,
            auditee_name='Equipe sintética',
            area='Qualidade',
            scheduled_start=timezone.now(),
            scheduled_end=timezone.now() + timedelta(hours=1),
        )
        item = AuditChecklistItem.objects.create(
            audit=plan,
            section='BPF',
            question='Há registro?',
            requirement_reference='ISO 22716',
        )
        plans.append(plan)
        items.append(item)
    assert_pair(
        AuditFinding,
        ('audit', 'checklist_item', 'responsible', 'description'),
        {
            'audit': plans[0].pk,
            'checklist_item': items[0].pk,
            'responsible': user.pk,
            'description': 'Constatação sintética',
        },
        {'checklist_item': items[1].pk},
    )
    assert not AuditFinding.objects.exists()


def test_crm_contact_proposal_contract_posts_remain_customer_scoped():
    from crm.models import CustomerContact, Opportunity, SalesContract, SalesOrder, SalesProposal
    from masters.models import BusinessPartner

    contexts = []
    for i in range(2):
        customer = BusinessPartner.objects.create(
            legal_name=f'Cliente {i}', partner_type='customer'
        )
        contact = CustomerContact.objects.create(customer=customer, name=f'Contato {i}')
        opportunity = Opportunity.objects.create(
            customer=customer, contact=contact, title=f'Creme {i}'
        )
        proposal = SalesProposal.objects.create(
            customer=customer, opportunity=opportunity, valid_until=timezone.localdate()
        )
        contract = SalesContract.objects.create(
            customer=customer,
            proposal=proposal,
            opportunity=opportunity,
            start_date=timezone.localdate(),
        )
        contexts.append(
            dict(
                customer=customer,
                contact=contact,
                opportunity=opportunity,
                proposal=proposal,
                contract=contract,
            )
        )
    a, b = contexts
    assert_pair(
        Opportunity,
        ('customer', 'contact', 'title'),
        {'customer': a['customer'].pk, 'contact': a['contact'].pk, 'title': 'Teste'},
        {'contact': b['contact'].pk},
    )
    assert_pair(
        SalesContract,
        ('customer', 'opportunity', 'proposal', 'start_date'),
        {
            'customer': a['customer'].pk,
            'opportunity': a['opportunity'].pk,
            'proposal': a['proposal'].pk,
            'start_date': str(timezone.localdate()),
        },
        {'opportunity': b['opportunity'].pk, 'proposal': b['proposal'].pk},
    )
    assert_pair(
        SalesOrder,
        ('customer', 'proposal', 'contract'),
        {name: a[name].pk for name in ('customer', 'proposal', 'contract')},
        {name: b[name].pk for name in ('proposal', 'contract')},
    )
    assert not SalesOrder.objects.exists()


def test_capa_notification_action_approval_and_effectiveness_posts():
    from capa.models import (
        CapaAction,
        CapaApproval,
        CapaNotification,
        CapaRecord,
        EffectivenessCheck,
    )

    user = get_user_model().objects.create_user('proven-capa', 'capa@example.invalid')
    contexts = []
    for i in range(2):
        capa = CapaRecord.objects.create(
            source_type='improvement',
            title=f'Melhoria {i}',
            root_cause='Causa sintética',
            action_plan='Plano sintético',
            owner=user,
            due_date=timezone.localdate(),
            source_reference=f'PROVEN-SOURCE-{i}',
            effectiveness_criteria='Sem recorrência na amostra sintética.',
        )
        action = CapaAction.objects.create(
            capa=capa,
            title='Ação',
            action_type='corrective',
            description='Teste',
            responsible=user,
            due_date=timezone.localdate(),
        )
        approval = CapaApproval.objects.create(capa=capa, approver=user, role='qa')
        check = EffectivenessCheck.objects.create(
            capa=capa, criteria='Teste', planned_date=timezone.localdate()
        )
        contexts.append(
            dict(capa=capa, action=action, approval=approval, effectiveness_check=check)
        )
        for source in (capa, action, approval, check):
            source.full_clean()
    a, b = contexts
    fields = ('capa', 'action', 'approval', 'effectiveness_check', 'recipient')
    assert_pair(
        CapaNotification,
        fields,
        {**{key: value.pk for key, value in a.items()}, 'recipient': user.pk},
        {key: b[key].pk for key in ('action', 'approval', 'effectiveness_check')},
    )
    assert not CapaNotification.objects.exists()


def test_qa_release_nullable_review_references_and_strict_lot_origin():
    from inventory.models import StockLot
    from qa.models import LotRelease, QAReview
    from tests.test_qa import create_qa_item, create_qa_production_order, create_quality_document

    unit, product, _unused_lot = create_qa_item('PROVEN-QA')
    order = create_qa_production_order(product, unit, 'PROVEN-QA')
    lot = StockLot.objects.create(
        product=product, lot_number='PROVEN-ORIGIN', source_production_order=order
    )
    other_lot = StockLot.objects.create(product=product, lot_number='PROVEN-NO-ORIGIN')
    document = create_quality_document(product, lot, unit, 'PROVEN-QA')
    generic_review = QAReview.objects.create(
        stock_lot=lot, review_type=QAReview.ReviewType.LOT_RELEASE, title='Revisão sintética'
    )
    generic_review.full_clean()
    fields = ('product', 'stock_lot', 'quality_document', 'qa_review', 'production_order')
    data = dict(
        product=product.pk,
        stock_lot=lot.pk,
        quality_document=document.pk,
        qa_review=generic_review.pk,
        production_order=order.pk,
    )
    form = resource_form(LotRelease, fields, data=data)
    assert form.is_valid(), form.errors
    rules = metadata(form, 'qa_review')
    assert [rule['values'][str(generic_review.pk)] for rule in rules[1:]] == [['*'], ['*']]
    data['stock_lot'] = other_lot.pk
    bad = resource_form(LotRelease, fields, data=data)
    assert not bad.is_valid()
    assert 'production_order' in bad.errors
    assert not LotRelease.objects.exists()
