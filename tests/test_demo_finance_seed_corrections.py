"""Full-demo finance seeding must use the protected ledger protocol."""

from decimal import Decimal
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.models import Sum
from django.db.models.signals import post_save
from django.utils import timezone

from finance.models import CashFlowEntry, FinancialAccount, FinancialSettlement, FinancialTitle
from governance.models import DemoScenarioLoad


def load_full_demo():
    call_command(
        'load_demo_scenario',
        scenario=[DemoScenarioLoad.Scenario.FULL_DEMO],
        stdout=StringIO(),
    )


@pytest.mark.django_db
def test_full_demo_twice_preserves_finance_creation_and_approval():
    load_full_demo()
    account = FinancialAccount.objects.get(code='DEMO-BANK')
    title = FinancialTitle.objects.get(title_number='DEMO-CR-0001')
    actor = get_user_model().objects.get(email='demo.finance@example.com')
    assert account.opening_balance == Decimal('100000.0000')
    assert account.current_balance == account.opening_balance
    assert title.status == FinancialTitle.Status.APPROVED
    assert title.original_amount == Decimal('25000.0000')
    assert title.open_amount == title.original_amount
    assert title.paid_amount == Decimal('0.0000')
    assert title.approved_by_id == actor.pk
    assert title.approved_at is not None
    first_account = FinancialAccount.objects.values().get(pk=account.pk)
    first_title = FinancialTitle.objects.values().get(pk=title.pk)

    load_full_demo()

    assert FinancialAccount.objects.values().get(pk=account.pk) == first_account
    assert FinancialTitle.objects.values().get(pk=title.pk) == first_title
    assert FinancialAccount.objects.count() == 1
    assert FinancialTitle.objects.count() == 1
    assert FinancialSettlement.objects.count() == 0
    assert CashFlowEntry.objects.count() == 0
    assert (
        DemoScenarioLoad.objects.filter(
            scenario=DemoScenarioLoad.Scenario.FULL_DEMO,
            status=DemoScenarioLoad.Status.SUCCEEDED,
        ).count()
        == 2
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('amount', 'reverse', 'expected_status'),
    [
        (Decimal('1000.0000'), False, FinancialTitle.Status.PARTIALLY_SETTLED),
        (Decimal('25000.0000'), False, FinancialTitle.Status.SETTLED),
        (Decimal('1000.0000'), True, FinancialTitle.Status.APPROVED),
    ],
    ids=['active-partial', 'active-full', 'reversed'],
)
def test_full_demo_rerun_preserves_manual_ledger(amount, reverse, expected_status):
    load_full_demo()
    account = FinancialAccount.objects.get(code='DEMO-BANK')
    title = FinancialTitle.objects.get(title_number='DEMO-CR-0001')
    actor = get_user_model().objects.create_user(
        username='manual-demo-finance', email='manual-demo-finance@example.test'
    )
    settlement = title.register_settlement(
        financial_account=account,
        amount=amount,
        settlement_date=timezone.localdate(),
        method=FinancialSettlement.Method.PIX,
        interest_amount=Decimal('10.0000'),
        reference='Manual integration regression',
    )
    settlement.reconcile(user=actor)
    flow = CashFlowEntry.create_from_settlement(settlement)
    if reverse:
        settlement.reverse(reason='Manual correction with preserved evidence', user=actor)
    account.refresh_from_db()
    title.refresh_from_db()
    assert title.status == expected_status
    assert settlement.reconciled_by_id == actor.pk
    assert settlement.reconciled_at is not None
    if reverse:
        assert settlement.reversed_by_id == actor.pk
        assert settlement.reversed_at is not None
        assert settlement.reversal_reason == 'Manual correction with preserved evidence'
    before_account = FinancialAccount.objects.values().get(pk=account.pk)
    before_title = FinancialTitle.objects.values().get(pk=title.pk)
    before_settlement = FinancialSettlement.objects.values().get(pk=settlement.pk)
    before_flow = CashFlowEntry.objects.values().get(pk=flow.pk)
    title_writes = []

    def record_title_write(sender, instance, **kwargs):
        title_writes.append(instance.pk)

    post_save.connect(record_title_write, sender=FinancialTitle)
    try:
        load_full_demo()
    finally:
        post_save.disconnect(record_title_write, sender=FinancialTitle)

    assert title_writes == []
    assert FinancialAccount.objects.values().get(pk=account.pk) == before_account
    assert FinancialTitle.objects.values().get(pk=title.pk) == before_title
    assert FinancialSettlement.objects.values().get(pk=settlement.pk) == before_settlement
    assert CashFlowEntry.objects.values().get(pk=flow.pk) == before_flow
    assert FinancialAccount.objects.count() == 1
    assert FinancialTitle.objects.count() == 1
    assert FinancialSettlement.objects.count() == 1
    assert CashFlowEntry.objects.count() == 1
    active = title.settlements.filter(status=FinancialSettlement.Status.ACTIVE)
    totals = active.aggregate(principal=Sum('amount'), net=Sum('net_amount'))
    account.refresh_from_db()
    title.refresh_from_db()
    assert title.paid_amount == (totals['principal'] or Decimal('0.0000'))
    assert title.open_amount == title.original_amount - title.paid_amount
    assert account.current_balance == account.opening_balance + (totals['net'] or Decimal('0.0000'))
