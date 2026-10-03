"""Real PostgreSQL lock-order proofs for the complete full-demo transaction."""

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from io import StringIO
from threading import Event
from time import monotonic, sleep

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import OperationalError, connection, connections, transaction
from django.utils import timezone

from finance.models import CashFlowEntry, FinancialAccount, FinancialSettlement, FinancialTitle
from governance.demo_seeders import DemoSeeder
from governance.models import DemoScenarioLoad

WAIT = 20
pytestmark = pytest.mark.django_db(transaction=True)


def load_full_demo():
    call_command(
        'load_demo_scenario',
        scenario=[DemoScenarioLoad.Scenario.FULL_DEMO],
        stdout=StringIO(),
    )


def backend_pid():
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        return cursor.fetchone()[0]


def bounded_connection():
    connection.ensure_connection()
    with connection.cursor() as cursor:
        cursor.execute("SET lock_timeout = '25s'")
        cursor.execute("SET statement_timeout = '30s'")
    return backend_pid()


def wait_for_title_block(worker_pid, owner_pid, future):
    deadline = monotonic() + WAIT
    while monotonic() < deadline:
        if future.done():
            future.result()
            pytest.fail('Worker completed without waiting for the contested title')
        with connection.cursor() as cursor:
            # B remains in atomic: discard PostgreSQL's cached activity snapshot.
            cursor.execute('SELECT pg_stat_clear_snapshot()')
            cursor.execute(
                'SELECT pg_blocking_pids(pid), query, wait_event_type '
                'FROM pg_stat_activity WHERE pid = %s',
                [worker_pid],
            )
            row = cursor.fetchone()
        if row and owner_pid in row[0]:
            assert row[2] == 'Lock', row
            assert 'finance_financialtitle' in row[1].lower(), row
            assert row[1].startswith('SELECT'), row
            with connection.cursor() as cursor:
                # Activity SQL may be truncated before its FOR UPDATE suffix.
                cursor.execute(
                    'SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid = %s '
                    "AND relation = 'finance_financialtitle'::regclass "
                    "AND mode = 'RowShareLock' AND granted)",
                    [worker_pid],
                )
                assert cursor.fetchone()[0], 'Title SELECT FOR UPDATE table lock absent'
            return
        sleep(0.02)
    pytest.fail('No PostgreSQL title-row blocking proof before bounded deadline')


def snapshot():
    return {
        model.__name__: list(model.objects.order_by('pk').values())
        for model in (FinancialAccount, FinancialTitle, FinancialSettlement, CashFlowEntry)
    }


@pytest.fixture
def demo_ledger():
    assert connection.vendor == 'postgresql', 'These acceptance tests require real PostgreSQL'
    assert not connection.in_atomic_block, 'The full-demo fixture must be committed for workers'
    load_full_demo()
    account = FinancialAccount.objects.get(code='DEMO-BANK')
    title = FinancialTitle.objects.get(title_number='DEMO-CR-0001')
    actor = get_user_model().objects.get(email='demo.finance@example.com')
    assert title.status == FinancialTitle.Status.APPROVED
    assert not connection.in_atomic_block
    return account, title, actor


def pay(title, account, actor):
    settlement = title.register_settlement(
        financial_account=account,
        amount=Decimal('1000.0000'),
        interest_amount=Decimal('10.0000'),
        settlement_date=timezone.localdate(),
        method=FinancialSettlement.Method.PIX,
        reference='Concurrent demo lock-order regression',
    )
    settlement.reconcile(user=actor)
    CashFlowEntry.create_from_settlement(settlement)
    return settlement


def assert_ledger_outcome(before, reverse=False):
    account = FinancialAccount.objects.get(code='DEMO-BANK')
    title = FinancialTitle.objects.get(title_number='DEMO-CR-0001')
    settlement = FinancialSettlement.objects.get()
    flow = CashFlowEntry.objects.get()
    expected_paid = Decimal('0.0000') if reverse else Decimal('1000.0000')
    assert title.original_amount == Decimal('25000.0000')
    assert title.paid_amount == expected_paid
    assert title.open_amount == title.original_amount - expected_paid
    assert title.status == (
        FinancialTitle.Status.APPROVED if reverse else FinancialTitle.Status.PARTIALLY_SETTLED
    )
    assert account.opening_balance == Decimal('100000.0000')
    assert account.current_balance == account.opening_balance + (
        Decimal('0.0000') if reverse else Decimal('1010.0000')
    )
    for model, obj, changed in (
        (FinancialAccount, account, {'current_balance', 'updated_at'}),
        (FinancialTitle, title, {'paid_amount', 'open_amount', 'status', 'updated_at'}),
    ):
        persisted = model.objects.values().get(pk=obj.pk)
        assert {key: value for key, value in persisted.items() if key not in changed} == {
            key: value for key, value in before[model.__name__][0].items() if key not in changed
        }
    assert settlement.amount == Decimal('1000.0000')
    assert settlement.interest_amount == Decimal('10.0000')
    assert settlement.net_amount == Decimal('1010.0000')
    assert settlement.reconciled_by_id == title.approved_by_id
    assert settlement.reconciled_at is not None
    assert settlement.status == (
        FinancialSettlement.Status.REVERSED if reverse else FinancialSettlement.Status.ACTIVE
    )
    if reverse:
        assert list(CashFlowEntry.objects.values()) == before['CashFlowEntry']
        changed_event = {'status', 'reversal_reason', 'reversed_by_id', 'reversed_at', 'updated_at'}
        persisted_event = FinancialSettlement.objects.values().get(pk=settlement.pk)
        assert {
            key: value for key, value in persisted_event.items() if key not in changed_event
        } == {
            key: value
            for key, value in before['FinancialSettlement'][0].items()
            if key not in changed_event
        }
        assert settlement.reversed_by_id == title.approved_by_id
        assert settlement.reversed_at is not None
        assert settlement.reversal_reason == 'Concurrent demo correction'
    else:
        assert settlement.reversed_at is None
    assert flow.settlement_id == settlement.pk
    assert flow.title_id == title.pk
    assert flow.financial_account_id == account.pk
    assert flow.amount == settlement.net_amount
    assert flow.flow_type == CashFlowEntry.FlowType.REALIZED
    assert flow.status == CashFlowEntry.Status.REALIZED
    assert flow.direction == CashFlowEntry.Direction.INFLOW
    assert FinancialAccount.objects.count() == FinancialTitle.objects.count() == 1
    assert FinancialSettlement.objects.count() == CashFlowEntry.objects.count() == 1
    assert (
        DemoScenarioLoad.objects.filter(
            scenario=DemoScenarioLoad.Scenario.FULL_DEMO,
            status=DemoScenarioLoad.Status.SUCCEEDED,
        ).count()
        == 2
    )
    assert not DemoScenarioLoad.objects.filter(status=DemoScenarioLoad.Status.FAILED).exists()


@pytest.mark.parametrize('reverse', [False, True], ids=['settlement', 'reversal'])
def test_rerun_waits_for_title_without_holding_bank(demo_ledger, monkeypatch, reverse):
    account, title, actor = demo_ledger
    settlement = pay(title, account, actor) if reverse else None
    before = snapshot()
    finance_ready, enter_finance = Event(), Event()
    worker_pids = []
    original = DemoSeeder._seed_costing_finance_fiscal

    def coordinated_finance(self):
        # The handshake occurs BEFORE the original takes any financial row lock.
        finance_ready.set()
        assert enter_finance.wait(WAIT), 'Finance entry was not released'
        return original(self)

    monkeypatch.setattr(DemoSeeder, '_seed_costing_finance_fiscal', coordinated_finance)

    def rerun():
        try:
            worker_pids.append(bounded_connection())
            load_full_demo()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(rerun)
        try:
            assert finance_ready.wait(WAIT), 'Full demo did not reach finance'
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '25s'")
                    cursor.execute("SET LOCAL statement_timeout = '30s'")
                locked_title = FinancialTitle.objects.select_for_update().get(pk=title.pk)
                enter_finance.set()
                assert worker_pids[0] != backend_pid(), 'Workers must use separate connections'
                wait_for_title_block(worker_pids[0], backend_pid(), future)
                try:
                    with transaction.atomic():
                        bank = FinancialAccount.objects.select_for_update(nowait=True).get(
                            pk=account.pk
                        )
                except OperationalError as error:
                    raise AssertionError(
                        'Lock inversion: rerun is blocked on title but already holds DEMO-BANK'
                    ) from error
                if reverse:
                    assert settlement is not None
                    settlement.reverse(reason='Concurrent demo correction', user=actor)
                else:
                    pay(locked_title, bank, actor)
                expected = snapshot()
            future.result(timeout=45)
        finally:
            # Even RED releases B's title before joining A; no deadlock harness.
            enter_finance.set()
            future.result(timeout=45)
    assert snapshot() == expected
    assert_ledger_outcome(before, reverse)


@pytest.mark.parametrize('reverse', [False, True], ids=['settlement', 'reversal'])
def test_ledger_waits_for_seeder_first_title_lock(demo_ledger, monkeypatch, reverse):
    account, title, actor = demo_ledger
    settlement = pay(title, account, actor) if reverse else None
    before = snapshot()
    seeder_holds_finance, release_seeder = Event(), Event()
    ledger_ready, enter_ledger = Event(), Event()
    seeder_pids, ledger_pids = [], []
    original = DemoSeeder._seed_crm

    def coordinated_crm(self):
        # Only A waits here; no two-party barrier after acquiring the row locks.
        seeder_holds_finance.set()
        assert release_seeder.wait(WAIT), 'Seeder transaction was not released'
        return original(self)

    monkeypatch.setattr(DemoSeeder, '_seed_crm', coordinated_crm)

    def rerun():
        try:
            seeder_pids.append(bounded_connection())
            load_full_demo()
        finally:
            connections.close_all()

    def ledger():
        try:
            ledger_pids.append(bounded_connection())
            own_title = FinancialTitle.objects.get(pk=title.pk)
            own_account = FinancialAccount.objects.get(pk=account.pk)
            own_actor = get_user_model().objects.get(pk=actor.pk)
            own_settlement = (
                FinancialSettlement.objects.get(pk=settlement.pk) if settlement else None
            )
            # B loads its caller instances and handshakes BEFORE any domain lock.
            ledger_ready.set()
            assert enter_ledger.wait(WAIT), 'Ledger entry was not released'
            if reverse:
                assert own_settlement is not None
                own_settlement.reverse(reason='Concurrent demo correction', user=own_actor)
            else:
                pay(own_title, own_account, own_actor)
            return snapshot()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        seeder_future = executor.submit(rerun)
        ledger_future = None
        try:
            assert seeder_holds_finance.wait(WAIT), 'Seeder never reached its held-lock stage'
            ledger_future = executor.submit(ledger)
            assert ledger_ready.wait(WAIT), 'Ledger worker did not reach its pre-lock handshake'
            assert len({backend_pid(), seeder_pids[0], ledger_pids[0]}) == 3
            enter_ledger.set()
            wait_for_title_block(ledger_pids[0], seeder_pids[0], ledger_future)
            release_seeder.set()
            seeder_future.result(timeout=45)
            expected = ledger_future.result(timeout=45)
        finally:
            release_seeder.set()
            enter_ledger.set()
            seeder_future.result(timeout=45)
            if ledger_future is not None:
                ledger_future.result(timeout=45)
    assert snapshot() == expected
    assert_ledger_outcome(before, reverse)
