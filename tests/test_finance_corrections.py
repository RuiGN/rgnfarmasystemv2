"""Financial ledger regressions using real PostgreSQL transactions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient
from django.db import close_old_connections, connection, connections
from django.utils import timezone

from finance.models import (
    CashFlowEntry,
    ChartOfAccount,
    FinancialAccount,
    FinancialCategory,
    FinancialPeriodClosing,
    FinancialSettlement,
    FinancialTitle,
)
from masters.models import BusinessPartner


@pytest.fixture
def ledger():
    partner = BusinessPartner.objects.create(
        code='FIN-COR-PARTNER',
        legal_name='Finance regression partner',
        partner_type=BusinessPartner.PartnerType.SUPPLIER,
    )
    chart = ChartOfAccount.objects.create(
        code='FIN-COR-CHART',
        name='Regression',
        account_type=ChartOfAccount.AccountType.LIABILITY,
    )
    category = FinancialCategory.objects.create(
        code='FIN-COR-CATEGORY',
        name='Regression',
        chart_account=chart,
        category_type=FinancialCategory.CategoryType.BOTH,
    )
    account = FinancialAccount.objects.create(
        code='FIN-COR-ACCOUNT',
        name='Regression',
        account_type=FinancialAccount.AccountType.BANK,
        opening_balance=Decimal('1000'),
        current_balance=Decimal('1000'),
    )

    def title(number='FIN-COR-1', amount='100', title_type=FinancialTitle.TitleType.PAYABLE):
        return FinancialTitle.objects.create(
            title_number=number,
            title_type=title_type,
            partner=partner,
            category=category,
            original_amount=Decimal(amount),
            open_amount=Decimal(amount),
            issue_date=timezone.localdate(),
            due_date=timezone.localdate(),
            status=FinancialTitle.Status.APPROVED,
        )

    return title, account


@pytest.fixture
def finance_client():
    user = get_user_model().objects.create_user(
        username='finance-corrections', email='finance-corrections@example.test'
    )
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='finance'))
    client = APIClient()
    client.force_authenticate(user)
    client.raise_request_exception = False
    return client, user


def settle(title, account, amount='60', **kwargs):
    return title.register_settlement(
        financial_account=account,
        amount=Decimal(amount),
        settlement_date=timezone.localdate(),
        method=FinancialSettlement.Method.PIX,
        **kwargs,
    )


def race(load, operate):
    """Synchronize stale reads BEFORE domain transactions/locks, never after locks."""
    assert connection.vendor == 'postgresql', 'Concurrency acceptance requires PostgreSQL'
    barrier = Barrier(2, timeout=10)

    def worker(index):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
            state = load(index)
            barrier.wait()
            try:
                operate(state)
                return 'ok'
            except ValidationError:
                return 'rejected'
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        return sorted(future.result(timeout=25) for future in futures)


@pytest.mark.django_db(transaction=True)
def test_concurrent_settlements_cannot_exceed_open_title(ledger):
    make_title, account = ledger
    title = make_title()
    outcomes = race(
        lambda _: (
            FinancialTitle.objects.get(pk=title.pk),
            FinancialAccount.objects.get(pk=account.pk),
        ),
        lambda state: settle(*state),
    )
    title.refresh_from_db()
    account.refresh_from_db()
    assert outcomes == ['ok', 'rejected']
    assert FinancialSettlement.objects.count() == 1
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db(transaction=True)
def test_concurrent_reverse_posts_one_compensation_only(ledger):
    make_title, account = ledger
    title = make_title()
    settlement = settle(title, account)
    outcomes = race(
        lambda _: FinancialSettlement.objects.select_related('title', 'financial_account').get(
            pk=settlement.pk
        ),
        lambda entry: entry.reverse(reason='Duplicate correction'),
    )
    title.refresh_from_db()
    account.refresh_from_db()
    settlement.refresh_from_db()
    assert outcomes == ['ok', 'rejected']
    assert settlement.status == FinancialSettlement.Status.REVERSED
    assert title.paid_amount == Decimal('0')
    assert title.open_amount == Decimal('100')
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db(transaction=True)
def test_concurrent_account_movements_do_not_lose_updates(ledger):
    _, account = ledger
    outcomes = race(
        lambda _: FinancialAccount.objects.get(pk=account.pk),
        lambda bank: bank.apply_movement(CashFlowEntry.Direction.OUTFLOW, Decimal('30')),
    )
    account.refresh_from_db()
    assert outcomes == ['ok', 'ok']
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'field,value',
    [
        ('amount', Decimal('20')),
        ('interest_amount', Decimal('2')),
        ('penalty_amount', Decimal('2')),
        ('discount_amount', Decimal('2')),
        ('net_amount', Decimal('2')),
        ('title_id', 'another_title'),
        ('financial_account_id', 'another_account'),
        ('method', FinancialSettlement.Method.CASH),
        ('settlement_date', 'another_date'),
        ('reference', 'changed'),
        ('status', FinancialSettlement.Status.REVERSED),
        ('reversal_reason', 'forged'),
        ('reconciled_at', 'now'),
        ('reversed_at', 'now'),
    ],
)
def test_posted_settlement_model_rejects_ledger_edits(ledger, field, value):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    if value == 'another_title':
        value = make_title(number='FIN-COR-OTHER').pk
    elif value == 'another_account':
        value = FinancialAccount.objects.create(
            code='FIN-COR-OTHER-ACCOUNT',
            name='Other',
            account_type=FinancialAccount.AccountType.BANK,
        ).pk
    elif value == 'another_date':
        value = timezone.localdate() + timedelta(days=1)
    elif value == 'now':
        value = timezone.now()
    setattr(entry, field, value)
    with pytest.raises(ValidationError):
        entry.save()
    entry.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert entry.amount == Decimal('60')
    assert entry.status == FinancialSettlement.Status.ACTIVE
    assert title.paid_amount == Decimal('60')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize('http_method', ['patch', 'put'])
def test_api_rejects_ledger_update_with_400_not_500(ledger, finance_client, http_method):
    make_title, account = ledger
    entry = settle(make_title(), account)
    client, _ = finance_client
    payload = {
        'title': entry.title_id,
        'financial_account': account.pk,
        'settlement_date': str(entry.settlement_date),
        'method': entry.method,
        'amount': '20',
    }
    response = getattr(client, http_method)(
        f'/api/finance/settlements/{entry.pk}/',
        payload,
        format='json',
    )
    assert response.status_code == 400
    assert 'amount' in response.json()
    entry.refresh_from_db()
    assert entry.amount == Decimal('60')


@pytest.mark.django_db
def test_serializer_translates_stale_create_domain_error(ledger):
    from rest_framework.exceptions import ValidationError as ApiValidationError
    from finance.serializers import FinancialSettlementSerializer

    make_title, account = ledger
    title = make_title()
    serializer = FinancialSettlementSerializer(
        data={
            'title': title.pk,
            'financial_account': account.pk,
            'settlement_date': str(timezone.localdate()),
            'method': 'pix',
            'amount': '60',
        }
    )
    assert serializer.is_valid(), serializer.errors
    settle(title, account)
    with pytest.raises(ApiValidationError):
        serializer.save()


@pytest.mark.django_db
@pytest.mark.parametrize('path', ['model', 'queryset', 'api', 'admin'])
@pytest.mark.parametrize('reversed_entry', [False, True])
def test_physical_delete_is_forbidden_even_after_reversal(
    ledger, finance_client, path, reversed_entry
):
    from django.contrib.admin import site
    from django.test import RequestFactory
    from finance.admin import FinancialSettlementAdmin

    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    client, user = finance_client
    if reversed_entry:
        entry.reverse(reason='Correction', user=user)
    if path == 'model':
        with pytest.raises(ValidationError):
            entry.delete()
    elif path == 'queryset':
        with pytest.raises(ValidationError):
            FinancialSettlement.objects.filter(pk=entry.pk).delete()
    elif path == 'api':
        response = client.delete(f'/api/finance/settlements/{entry.pk}/')
        assert response.status_code == 405
        assert 'DELETE' not in response['Allow']
    else:
        request = RequestFactory().get('/admin/')
        request.user = user
        model_admin = FinancialSettlementAdmin(FinancialSettlement, site)
        assert not model_admin.has_delete_permission(request, entry)
        assert 'delete_selected' not in model_admin.get_actions(request)
    assert FinancialSettlement.objects.filter(pk=entry.pk).exists()
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.paid_amount == (Decimal('0') if reversed_entry else Decimal('60'))
    assert account.current_balance == (Decimal('1000') if reversed_entry else Decimal('940'))


@pytest.mark.django_db
@pytest.mark.parametrize('path', ['model', 'admin', 'api'])
def test_all_creation_paths_post_ledger_and_preserve_notes(ledger, finance_client, path):
    from django.contrib.admin import site
    from django.test import RequestFactory
    from finance.admin import FinancialSettlementAdmin

    make_title, account = ledger
    title = make_title()
    client, user = finance_client
    payload = {
        'title': title.pk,
        'financial_account': account.pk,
        'settlement_date': str(timezone.localdate()),
        'method': 'pix',
        'amount': '60',
        'reference': 'Payment ref',
        'notes': 'Legitimate notes',
    }
    if path == 'api':
        response = client.post('/api/finance/settlements/', payload, format='json')
        assert response.status_code == 201, response.content
        entry = FinancialSettlement.objects.get(pk=response.json()['id'])
    else:
        entry = FinancialSettlement(
            title=title,
            financial_account=account,
            amount=Decimal('60'),
            settlement_date=timezone.localdate(),
            method='pix',
            reference=payload['reference'],
            notes=payload['notes'],
        )
        if path == 'admin':
            request = RequestFactory().post('/admin/')
            request.user = user
            FinancialSettlementAdmin(FinancialSettlement, site).save_model(
                request, entry, None, False
            )
        else:
            entry.save()
        entry.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert entry.notes == 'Legitimate notes'
    assert entry.reference == 'Payment ref'
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
def test_admin_ledger_fields_are_readonly_after_posting(ledger, finance_client):
    from django.contrib.admin import site
    from django.test import RequestFactory
    from finance.admin import FinancialSettlementAdmin

    make_title, account = ledger
    entry = settle(make_title(), account)
    _, user = finance_client
    request = RequestFactory().get('/admin/')
    request.user = user
    model_admin = FinancialSettlementAdmin(FinancialSettlement, site)
    form = model_admin.get_form(request, entry)
    assert set(form.base_fields) == {'notes'}


@pytest.mark.django_db
def test_new_instance_cannot_overwrite_existing_ledger_primary_key(ledger):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    impostor = FinancialSettlement(
        pk=entry.pk,
        created_at=entry.created_at,
        title=title,
        financial_account=account,
        amount=Decimal('10'),
        settlement_date=timezone.localdate(),
        method='pix',
    )
    with pytest.raises(ValidationError):
        impostor.save()
    entry.refresh_from_db()
    assert entry.amount == Decimal('60')


@pytest.mark.django_db
@pytest.mark.parametrize('path', ['update', 'bulk_update', 'bulk_create'])
def test_bulk_writes_cannot_bypass_ledger(ledger, path):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    with pytest.raises(ValidationError):
        if path == 'update':
            FinancialSettlement.objects.filter(pk=entry.pk).update(amount=Decimal('10'))
        elif path == 'bulk_update':
            entry.amount = Decimal('10')
            FinancialSettlement.objects.bulk_update([entry], ['amount'])
        else:
            FinancialSettlement.objects.bulk_create(
                [
                    FinancialSettlement(
                        title=title,
                        financial_account=account,
                        amount=Decimal('10'),
                        settlement_date=timezone.localdate(),
                        method='pix',
                    )
                ]
            )
    entry.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert FinancialSettlement.objects.count() == 1
    assert entry.amount == Decimal('60')
    assert title.paid_amount == Decimal('60')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('scenario', ['partial', 'shared_account', 'reverse_distinct', 'mixed'])
def test_ledger_operations_serialize_shared_resources(ledger, scenario):
    make_title, account = ledger
    title = make_title()
    other = (
        title
        if scenario in {'partial', 'reverse_distinct', 'mixed'}
        else make_title(number='FIN-COR-2')
    )
    entries = []
    if scenario == 'reverse_distinct':
        entries = [settle(title, account, '20'), settle(title, account, '30')]
    elif scenario == 'mixed':
        entries = [settle(title, account, '20')]

    def load(index):
        if scenario == 'reverse_distinct' or (scenario == 'mixed' and index == 0):
            return FinancialSettlement.objects.select_related('title', 'financial_account').get(
                pk=entries[index].pk
            )
        target = title if index == 0 else other
        return (
            FinancialTitle.objects.get(pk=target.pk),
            FinancialAccount.objects.get(pk=account.pk),
        )

    def operate(state):
        if isinstance(state, FinancialSettlement):
            state.reverse(reason='Concurrent correction')
        else:
            settle(*state, amount='30')

    assert race(load, operate) == ['ok', 'ok']
    title.refresh_from_db()
    other.refresh_from_db()
    account.refresh_from_db()
    expected_paid = {
        'partial': Decimal('60'),
        'shared_account': Decimal('30'),
        'reverse_distinct': Decimal('0'),
        'mixed': Decimal('30'),
    }[scenario]
    expected_balance = (
        Decimal('940')
        if scenario in {'partial', 'shared_account'}
        else Decimal('1000')
        if scenario == 'reverse_distinct'
        else Decimal('970')
    )
    assert title.paid_amount == expected_paid
    assert title.open_amount == Decimal('100') - expected_paid
    assert account.current_balance == expected_balance
    if scenario == 'shared_account':
        assert other.paid_amount == Decimal('30')
        assert other.open_amount == Decimal('70')
    if entries:
        assert not FinancialSettlement.objects.filter(
            pk__in=[entry.pk for entry in entries], status=FinancialSettlement.Status.ACTIVE
        ).exists()


@pytest.mark.django_db
def test_reconciliation_reads_current_status_instead_of_stale_instance(ledger):
    make_title, account = ledger
    entry = settle(make_title(), account)
    stale = FinancialSettlement.objects.get(pk=entry.pk)
    entry.reverse(reason='Correction')
    with pytest.raises(ValidationError):
        stale.reconcile()
    entry.refresh_from_db()
    assert entry.reconciled_at is None
    assert entry.status == FinancialSettlement.Status.REVERSED


@pytest.mark.django_db
@pytest.mark.parametrize('path', ['api', 'model', 'queryset', 'bulk_update'])
def test_annotations_remain_editable_without_changing_ledger(ledger, finance_client, path):
    make_title, account = ledger
    entry = settle(make_title(), account)
    client, _ = finance_client
    if path == 'api':
        response = client.patch(
            f'/api/finance/settlements/{entry.pk}/', {'notes': 'Annotation'}, format='json'
        )
        assert response.status_code == 200
    elif path == 'queryset':
        FinancialSettlement.objects.filter(pk=entry.pk).update(notes='Annotation')
    elif path == 'bulk_update':
        entry.notes = 'Annotation'
        FinancialSettlement.objects.bulk_update([entry], ['notes'])
    else:
        entry.notes = 'Annotation'
        entry.save(update_fields=['notes', 'updated_at'])
    entry.refresh_from_db()
    account.refresh_from_db()
    assert entry.notes == 'Annotation'
    assert entry.amount == Decimal('60')
    assert entry.status == FinancialSettlement.Status.ACTIVE
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'title_type, balance',
    [
        (FinancialTitle.TitleType.PAYABLE, Decimal('940')),
        (FinancialTitle.TitleType.RECEIVABLE, Decimal('1060')),
    ],
)
def test_api_official_lifecycle_remains_available_with_original_permissions(
    ledger, finance_client, title_type, balance
):
    make_title, account = ledger
    title = make_title(title_type=title_type)
    client, user = finance_client
    response = client.post(
        '/api/finance/settlements/',
        {
            'title': title.pk,
            'financial_account': account.pk,
            'settlement_date': str(timezone.localdate()),
            'method': 'pix',
            'amount': '60',
            'interest_amount': '3',
            'penalty_amount': '2',
            'discount_amount': '5',
        },
        format='json',
    )
    assert response.status_code == 201
    pk = response.json()['id']
    account.refresh_from_db()
    assert account.current_balance == balance
    reconciliation = client.post(f'/api/finance/settlements/{pk}/reconcile/')
    assert reconciliation.status_code == 200
    assert reconciliation.json()['reconciled_by'] == user.pk
    missing_reason = client.post(f'/api/finance/settlements/{pk}/reverse/')
    assert missing_reason.status_code == 400
    reversal = client.post(
        f'/api/finance/settlements/{pk}/reverse/', {'reversal_reason': 'Official correction'}
    )
    assert reversal.status_code == 200
    assert reversal.json()['status'] == FinancialSettlement.Status.REVERSED
    assert reversal.json()['reversed_by'] == user.pk
    assert (
        client.post(
            f'/api/finance/settlements/{pk}/reverse/', {'reversal_reason': 'Again'}
        ).status_code
        == 400
    )
    assert client.post(f'/api/finance/settlements/{pk}/reconcile/').status_code == 400
    account.refresh_from_db()
    title.refresh_from_db()
    assert account.current_balance == Decimal('1000')
    assert title.paid_amount == Decimal('0')
    assert title.open_amount == Decimal('100')


@pytest.mark.django_db
def test_closed_period_reverse_rolls_back_all_ledger_writes(ledger):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    closing = FinancialPeriodClosing.objects.create(
        period_year=entry.settlement_date.year,
        period_month=entry.settlement_date.month,
    )
    closing.validate_period()
    closing.close()
    with pytest.raises(ValidationError) as error:
        entry.reverse(reason='Attempt after closing')
    assert 'settlement_date' in error.value.message_dict
    entry.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert entry.status == FinancialSettlement.Status.ACTIVE
    assert entry.reversed_at is None
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
def test_settlement_decision_uses_fresh_persisted_title_status(ledger):
    make_title, account = ledger
    title = make_title()
    stale = FinancialTitle.objects.get(pk=title.pk)
    title.cancel()
    with pytest.raises(ValidationError):
        settle(stale, account)
    account.refresh_from_db()
    assert not FinancialSettlement.objects.exists()
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db(transaction=True)
def test_concurrent_reconcile_and_reverse_keep_authoritative_state(ledger):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    outcomes = race(
        lambda index: (index, FinancialSettlement.objects.get(pk=entry.pk)),
        lambda state: (
            state[1].reverse(reason='Concurrent correction')
            if state[0] == 0
            else state[1].reconcile()
        ),
    )
    assert outcomes in (['ok', 'ok'], ['ok', 'rejected'])
    entry.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert entry.status == FinancialSettlement.Status.REVERSED
    assert title.paid_amount == Decimal('0')
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
@pytest.mark.parametrize('target', ['title', 'account'])
@pytest.mark.parametrize('path', ['model', 'serializer', 'admin'])
def test_review_stale_metadata_save_preserves_posted_ledger(ledger, target, path):
    from django.contrib.admin import site
    from django.test import RequestFactory
    from finance.serializers import FinancialTitleSerializer, FinancialAccountSerializer

    make_title, account = ledger
    title = make_title()
    model = FinancialTitle if target == 'title' else FinancialAccount
    stale = model.objects.get(pk=title.pk if target == 'title' else account.pk)
    field = 'notes' if target == 'title' else 'name'
    settle(title, account)
    if path == 'serializer':
        serializer_type = (
            FinancialTitleSerializer if target == 'title' else FinancialAccountSerializer
        )
        serializer = serializer_type(stale, data={field: 'Metadata correction'}, partial=True)
        assert serializer.is_valid(), serializer.errors
        serializer.save()
    else:
        setattr(stale, field, 'Metadata correction')
        if path == 'admin':
            site._registry[model].save_model(RequestFactory().post('/admin/'), stale, None, True)
        else:
            stale.save()
    title.refresh_from_db()
    account.refresh_from_db()
    stale.refresh_from_db()
    assert getattr(stale, field) == 'Metadata correction'
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert title.status == FinancialTitle.Status.PARTIALLY_SETTLED
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'field,value',
    [
        ('paid_amount', Decimal('5')),
        ('open_amount', Decimal('90')),
        ('status', FinancialTitle.Status.CANCELLED),
        ('approved_at', timezone.now()),
    ],
)
def test_review_generic_title_save_cannot_write_service_fields(ledger, field, value):
    make_title, _ = ledger
    title = make_title()
    setattr(title, field, value)
    with pytest.raises(ValidationError):
        title.save(update_fields=[field])
    title.refresh_from_db()
    assert title.status == FinancialTitle.Status.APPROVED
    assert title.paid_amount == Decimal('0')
    assert title.open_amount == Decimal('100')


@pytest.mark.django_db
def test_review_generic_account_save_cannot_write_balance(ledger):
    _, account = ledger
    account.current_balance = Decimal('9999')
    with pytest.raises(ValidationError):
        account.save()
    account.refresh_from_db()
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'forged',
    [
        {'status': FinancialTitle.Status.SETTLED},
        {'paid_amount': Decimal('50')},
        {'open_amount': Decimal('50')},
        {'approved_at': timezone.now()},
    ],
)
def test_review_title_creation_cannot_forge_service_state(ledger, forged):
    make_title, _ = ledger
    template = make_title()
    values = dict(
        title_type=template.title_type,
        partner=template.partner,
        category=template.category,
        original_amount=Decimal('100'),
        open_amount=Decimal('100'),
        due_date=timezone.localdate(),
    )
    values.update(forged)
    with pytest.raises(ValidationError):
        FinancialTitle.objects.create(**values)
    assert FinancialTitle.objects.count() == 1


@pytest.mark.django_db
def test_review_account_creation_derives_current_from_opening():
    account = FinancialAccount.objects.create(
        name='New', account_type='bank', opening_balance='125'
    )
    assert account.current_balance == Decimal('125')
    with pytest.raises(ValidationError):
        FinancialAccount.objects.create(
            name='Forged', account_type='bank', opening_balance='125', current_balance='999'
        )


@pytest.mark.django_db
def test_review_api_ignores_user_aggregate_overrides(ledger, finance_client):
    make_title, account = ledger
    title = make_title()
    settle(title, account)
    client, _ = finance_client
    response = client.patch(
        f'/api/finance/titles/{title.pk}/',
        {'notes': 'Allowed', 'open_amount': '100', 'paid_amount': '0', 'status': 'approved'},
        format='json',
    )
    assert response.status_code == 200, response.content
    response = client.patch(
        f'/api/finance/accounts/{account.pk}/',
        {'name': 'Allowed', 'current_balance': '9999'},
        format='json',
    )
    assert response.status_code == 200, response.content
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.open_amount == Decimal('40')
    assert title.paid_amount == Decimal('60')
    assert title.status == FinancialTitle.Status.PARTIALLY_SETTLED
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize(
    'field,value',
    [
        ('title_type', 'receivable'),
        ('original_amount', Decimal('200')),
        ('financial_account_id', 'account'),
        ('due_date', 'tomorrow'),
    ],
)
@pytest.mark.parametrize('path', ['model', 'api'])
@pytest.mark.parametrize('reversed_entry', [False, True])
def test_review_posted_title_freezes_economics(
    ledger, finance_client, field, value, path, reversed_entry
):
    make_title, account = ledger
    title = make_title()
    entry = settle(title, account)
    if reversed_entry:
        entry.reverse('Correction')
    if value == 'account':
        value = account.pk
    elif value == 'tomorrow':
        value = timezone.localdate() + timedelta(days=1)
    client, _ = finance_client
    if path == 'model':
        setattr(title, field, value)
        with pytest.raises(ValidationError):
            title.save()
    else:
        key = 'financial_account' if field.endswith('_id') else field
        response = client.patch(
            f'/api/finance/titles/{title.pk}/', {key: str(value)}, format='json'
        )
        assert response.status_code == 400, response.content
    title.refresh_from_db()
    if not reversed_entry:
        entry.reverse('Direction must remain payable')
    account.refresh_from_db()
    assert title.title_type == FinancialTitle.TitleType.PAYABLE
    assert title.original_amount == Decimal('100')
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
@pytest.mark.parametrize('path', ['model', 'api'])
def test_review_preposting_economic_edit_derives_open_amount(ledger, finance_client, path):
    make_title, account = ledger
    title = make_title()
    if path == 'model':
        title.original_amount = Decimal('80')
        title.title_type = FinancialTitle.TitleType.RECEIVABLE
        title.save()
    else:
        client, _ = finance_client
        response = client.patch(
            f'/api/finance/titles/{title.pk}/',
            {'original_amount': '80', 'title_type': 'receivable'},
            format='json',
        )
        assert response.status_code == 200, response.content
    title.refresh_from_db()
    assert title.open_amount == Decimal('80')
    entry = settle(title, account, '80')
    account.refresh_from_db()
    assert account.current_balance == Decimal('1080')
    entry.reverse('Correction')
    account.refresh_from_db()
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
def test_review_economic_serializer_rechecks_at_save_after_posting(ledger):
    from finance.serializers import FinancialTitleSerializer
    from rest_framework.exceptions import ValidationError as ApiValidationError

    make_title, account = ledger
    title = make_title()
    serializer = FinancialTitleSerializer(title, data={'title_type': 'receivable'}, partial=True)
    assert serializer.is_valid(), serializer.errors
    settle(title, account)
    with pytest.raises(ApiValidationError):
        serializer.save()


@pytest.mark.django_db
def test_review_account_opening_is_frozen_after_posting(ledger):
    make_title, account = ledger
    settle(make_title(), account)
    account.opening_balance = Decimal('2000')
    with pytest.raises(ValidationError):
        account.save()
    account.refresh_from_db()
    assert account.opening_balance == Decimal('1000')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize('transition', ['cancel', 'mark_overdue', 'approve'])
def test_review_title_transitions_use_persisted_state(ledger, transition):
    make_title, account = ledger
    title = make_title()
    title.issue_date = timezone.localdate() - timedelta(days=2)
    title.due_date = timezone.localdate() - timedelta(days=1)
    title.save()
    if transition == 'approve':
        # Load a valid pending caller, then cancel the persisted title.
        title = FinancialTitle.objects.create(
            title_type=title.title_type,
            partner=title.partner,
            category=title.category,
            original_amount='100',
            due_date=timezone.localdate(),
        )
        stale = FinancialTitle.objects.get(pk=title.pk)
        title.cancel()
        with pytest.raises(ValidationError):
            stale.approve()
        title.refresh_from_db()
        assert title.status == FinancialTitle.Status.CANCELLED
    else:
        stale = FinancialTitle.objects.get(pk=title.pk)
        settle(title, account, '100')
        if transition == 'cancel':
            with pytest.raises(ValidationError):
                stale.cancel()
        else:
            stale.mark_overdue()
            assert stale.status == FinancialTitle.Status.SETTLED
        title.refresh_from_db()
        assert title.status == FinancialTitle.Status.SETTLED
        assert title.paid_amount == Decimal('100')
        assert title.open_amount == Decimal('0')
        account.refresh_from_db()
        assert account.current_balance == Decimal('900')


@pytest.mark.django_db(transaction=True)
def test_review_cancel_competes_with_settlement(ledger):
    make_title, account = ledger
    title = make_title()
    outcomes = race(
        lambda index: (
            index,
            FinancialTitle.objects.get(pk=title.pk),
            FinancialAccount.objects.get(pk=account.pk),
        ),
        lambda state: state[1].cancel() if state[0] == 0 else settle(state[1], state[2]),
    )
    assert outcomes == ['ok', 'rejected']
    title.refresh_from_db()
    account.refresh_from_db()
    if title.status == FinancialTitle.Status.CANCELLED:
        assert not title.settlements.exists()
        assert title.paid_amount == Decimal('0')
        assert account.current_balance == Decimal('1000')
    else:
        assert title.status == FinancialTitle.Status.PARTIALLY_SETTLED
        assert title.settlements.count() == 1
        assert title.paid_amount == Decimal('60')
        assert account.current_balance == Decimal('940')


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('target', ['title', 'account'])
def test_review_metadata_save_competes_with_settlement(ledger, target):
    make_title, account = ledger
    title = make_title()

    def load(index):
        return (
            index,
            FinancialTitle.objects.get(pk=title.pk),
            FinancialAccount.objects.get(pk=account.pk),
        )

    def operate(state):
        index, local_title, local_account = state
        if index == 0:
            obj = local_title if target == 'title' else local_account
            setattr(obj, 'notes' if target == 'title' else 'name', 'Concurrent metadata')
            obj.save()
        else:
            settle(local_title, local_account)

    assert race(load, operate) == ['ok', 'ok']
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert title.status == FinancialTitle.Status.PARTIALLY_SETTLED
    assert account.current_balance == Decimal('940')
    assert (title.notes if target == 'title' else account.name) == 'Concurrent metadata'


def admin_settlement_payload(title, account):
    return {
        'title': title.pk,
        'financial_account': account.pk,
        'settlement_date': str(timezone.localdate()),
        'method': 'pix',
        'amount': '60',
        'interest_amount': '0',
        'penalty_amount': '0',
        'discount_amount': '0',
        'reference': 'Admin reference',
        'notes': 'Admin notes',
        '_save': 'Save',
    }


def staff_admin_client(user):
    from django.test import Client

    user.is_staff = True
    user.save(update_fields=['is_staff'])
    client = Client(raise_request_exception=False)
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_review_admin_real_post_pending_title_renders_form_error(ledger, finance_client):
    make_title, account = ledger
    template = make_title()
    title = FinancialTitle.objects.create(
        title_type=template.title_type,
        partner=template.partner,
        category=template.category,
        original_amount='100',
        due_date=timezone.localdate(),
    )
    _, user = finance_client
    response = staff_admin_client(user).post(
        '/admin/finance/financialsettlement/add/', admin_settlement_payload(title, account)
    )
    assert response.status_code == 200, response.content
    assert response.context['adminform'].form.errors
    assert not FinancialSettlement.objects.exists()
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.paid_amount == Decimal('0')
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db(transaction=True)
def test_review_admin_real_post_race_rejection_renders_form_error(
    ledger, finance_client, monkeypatch
):
    from finance.admin import FinancialSettlementAdmin

    make_title, account = ledger
    title = make_title()
    _, user = finance_client
    clients = [staff_admin_client(user), staff_admin_client(user)]
    barrier = Barrier(2, timeout=10)
    original = FinancialSettlementAdmin.save_form

    def synchronized_save_form(self, request, form, change):
        obj = original(self, request, form, change)
        barrier.wait()
        return obj

    monkeypatch.setattr(FinancialSettlementAdmin, 'save_form', synchronized_save_form)

    def worker(index):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
            response = clients[index].post(
                '/admin/finance/financialsettlement/add/', admin_settlement_payload(title, account)
            )
            return response.status_code, response.content.decode()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(worker, index) for index in range(2)]
        results = [future.result(timeout=25) for future in futures]
    assert sorted(status for status, _ in results) == [200, 302], results
    assert 'errorlist' in next(content for status, content in results if status == 200)
    title.refresh_from_db()
    account.refresh_from_db()
    assert FinancialSettlement.objects.count() == 1
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize('permission', ['add', 'change', 'view'])
@pytest.mark.parametrize('operation', ['create', 'reconcile', 'reverse'])
def test_review_api_financial_permissions_are_not_interchangeable(ledger, permission, operation):
    make_title, account = ledger
    title = make_title()
    user = get_user_model().objects.create_user(
        username=f'financial-{permission}', email=f'{permission}@example.test'
    )
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label='finance', codename=f'{permission}_financialsettlement'
        )
    )
    client = APIClient()
    client.force_authenticate(user)
    if operation == 'create':
        response = client.post(
            '/api/finance/settlements/', admin_settlement_payload(title, account), format='json'
        )
        assert response.status_code == (201 if permission == 'add' else 403), response.content
        assert FinancialSettlement.objects.count() == (1 if permission == 'add' else 0)
    else:
        entry = settle(title, account)
        response = client.post(
            f'/api/finance/settlements/{entry.pk}/{operation}/',
            {'reversal_reason': 'Authorized correction'},
            format='json',
        )
        assert response.status_code == (200 if permission == 'change' else 403), response.content
        entry.refresh_from_db()
        assert (entry.reconciled_at is not None) == (
            operation == 'reconcile' and permission == 'change'
        )
        assert (entry.status == FinancialSettlement.Status.REVERSED) == (
            operation == 'reverse' and permission == 'change'
        )


@pytest.mark.django_db
def test_review_admin_real_success_and_invalid_net(ledger, finance_client):
    make_title, account = ledger
    title = make_title()
    _, user = finance_client
    client = staff_admin_client(user)
    payload = admin_settlement_payload(title, account)
    payload['discount_amount'] = '100'
    invalid = client.post('/admin/finance/financialsettlement/add/', payload)
    assert invalid.status_code == 200
    assert invalid.context['adminform'].form.errors
    assert FinancialSettlement.objects.count() == 0
    payload['discount_amount'] = '0'
    response = client.post('/admin/finance/financialsettlement/add/', payload)
    assert response.status_code == 302, response.content
    entry = FinancialSettlement.objects.get()
    assert entry.net_amount == Decimal('60')
    assert entry.notes == 'Admin notes'
    account.refresh_from_db()
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
def test_review_admin_rejection_after_posting_rolls_back_ledger(
    ledger, finance_client, monkeypatch
):
    from finance.admin import FinancialSettlementAdmin

    make_title, account = ledger
    title = make_title()
    _, user = finance_client

    def reject_related(self, request, form, formsets, change):
        raise ValidationError('Transactional rejection')

    monkeypatch.setattr(FinancialSettlementAdmin, 'save_related', reject_related)
    response = staff_admin_client(user).post(
        '/admin/finance/financialsettlement/add/', admin_settlement_payload(title, account)
    )
    assert response.status_code == 200
    assert 'Transactional rejection' in str(response.context['adminform'].form.errors)
    assert FinancialSettlement.objects.count() == 0
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.paid_amount == Decimal('0')
    assert title.open_amount == Decimal('100')
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
def test_review_admin_real_title_creation_derives_open_amount(ledger, finance_client):
    make_title, _ = ledger
    template = make_title()
    _, user = finance_client
    response = staff_admin_client(user).post(
        '/admin/finance/financialtitle/add/',
        {
            'title_type': 'payable',
            'source_type': 'manual',
            'partner': template.partner_id,
            'category': template.category_id,
            'issue_date': str(timezone.localdate()),
            'due_date': str(timezone.localdate()),
            'original_amount': '80',
            'notes': 'New title',
            '_save': 'Save',
        },
    )
    assert response.status_code == 302, response.content
    title = FinancialTitle.objects.get(notes='New title')
    assert title.open_amount == Decimal('80')
    assert title.paid_amount == Decimal('0')
    assert title.status == FinancialTitle.Status.PENDING


@pytest.mark.django_db
@pytest.mark.parametrize('target', ['title', 'account'])
@pytest.mark.parametrize('path', ['update', 'bulk_update', 'bulk_create'])
def test_review_bulk_title_account_writes_cannot_bypass_protocol(ledger, target, path):
    make_title, account = ledger
    title = make_title()
    settle(title, account)
    from copy import copy

    obj = copy(title if target == 'title' else account)
    model = type(obj)
    field = 'open_amount' if target == 'title' else 'current_balance'
    with pytest.raises(ValidationError):
        if path == 'update':
            model.objects.filter(pk=obj.pk).update(**{field: Decimal('999')})
        elif path == 'bulk_update':
            setattr(obj, field, Decimal('999'))
            model.objects.bulk_update([obj], [field])
        else:
            obj.pk = None
            if target == 'title':
                obj.title_number = 'BULK-FORGED-TITLE'
            else:
                obj.code = 'BULK-FORGED-ACCOUNT'
            model.objects.bulk_create([obj])
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize('amount', ['0', '-1'])
def test_review_title_creation_enforces_economic_invariant(ledger, amount):
    make_title, _ = ledger
    template = make_title()
    with pytest.raises(ValidationError):
        FinancialTitle.objects.create(
            title_type='payable',
            partner=template.partner,
            category=template.category,
            original_amount=amount,
            due_date=timezone.localdate(),
        )


@pytest.mark.django_db
def test_review_admin_real_preposting_edit_derives_open(ledger, finance_client):
    make_title, _ = ledger
    title = make_title()
    _, user = finance_client
    response = staff_admin_client(user).post(
        f'/admin/finance/financialtitle/{title.pk}/change/',
        {
            'title_type': 'receivable',
            'source_type': 'manual',
            'partner': title.partner_id,
            'category': title.category_id,
            'issue_date': str(timezone.localdate()),
            'due_date': str(timezone.localdate()),
            'original_amount': '80',
            'notes': 'Edited title',
            '_save': 'Save',
        },
    )
    assert response.status_code == 302, response.content
    title.refresh_from_db()
    assert title.open_amount == Decimal('80')
    assert title.original_amount == Decimal('80')
    assert title.title_type == 'receivable'


@pytest.mark.django_db(transaction=True)
def test_review_direction_edit_competes_with_posting(ledger):
    make_title, account = ledger
    title = make_title()

    def load(index):
        return (
            index,
            FinancialTitle.objects.get(pk=title.pk),
            FinancialAccount.objects.get(pk=account.pk),
        )

    def operate(state):
        if state[0] == 0:
            state[1].title_type = FinancialTitle.TitleType.RECEIVABLE
            state[1].save()
        else:
            settle(state[1], state[2])

    outcomes = race(load, operate)
    assert outcomes in (['ok', 'ok'], ['ok', 'rejected'])
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.settlements.count() == 1
    assert title.paid_amount == Decimal('60')
    assert account.current_balance == (
        Decimal('1060') if title.title_type == 'receivable' else Decimal('940')
    )
    title.settlements.get().reverse('Restore original balance')
    account.refresh_from_db()
    assert account.current_balance == Decimal('1000')


@pytest.mark.django_db
@pytest.mark.parametrize('permission', ['add', 'change', 'view'])
def test_review_admin_creation_requires_add_permission(ledger, permission):
    make_title, account = ledger
    title = make_title()
    user = get_user_model().objects.create_user(
        username=f'admin-{permission}', email=f'admin-{permission}@example.test'
    )
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label='finance', codename=f'{permission}_financialsettlement'
        )
    )
    response = staff_admin_client(user).post(
        '/admin/finance/financialsettlement/add/', admin_settlement_payload(title, account)
    )
    assert response.status_code == (302 if permission == 'add' else 403), response.content
    assert FinancialSettlement.objects.count() == (1 if permission == 'add' else 0)


@pytest.mark.django_db
def test_review_account_preposting_opening_edit_preserves_movements(ledger):
    _, account = ledger
    account.apply_movement(CashFlowEntry.Direction.OUTFLOW, Decimal('30'))
    account.opening_balance = Decimal('1200')
    account.save(update_fields=['opening_balance'])
    account.refresh_from_db()
    assert account.opening_balance == Decimal('1200')
    assert account.current_balance == Decimal('1170')


@pytest.mark.django_db
def test_review_admin_missing_title_amount_renders_form_error(ledger, finance_client):
    make_title, _ = ledger
    title = make_title()
    _, user = finance_client
    response = staff_admin_client(user).post(
        '/admin/finance/financialtitle/add/',
        {
            'title_type': 'payable',
            'source_type': 'manual',
            'partner': title.partner_id,
            'category': title.category_id,
            'issue_date': str(timezone.localdate()),
            'due_date': str(timezone.localdate()),
            '_save': 'Save',
        },
    )
    assert response.status_code == 200
    assert 'original_amount' in response.context['adminform'].form.errors


@pytest.mark.django_db
def test_review_admin_account_opening_rejection_renders_form_error(ledger, finance_client):
    make_title, account = ledger
    settle(make_title(), account)
    _, user = finance_client
    response = staff_admin_client(user).post(
        f'/admin/finance/financialaccount/{account.pk}/change/',
        {
            'name': 'Rejected metadata',
            'account_type': 'bank',
            'opening_balance': '2000',
            'is_active': 'on',
            '_save': 'Save',
        },
    )
    assert response.status_code == 200
    assert 'opening_balance' in response.context['adminform'].form.errors
    account.refresh_from_db()
    assert account.name == 'Regression'
    assert account.opening_balance == Decimal('1000')
    assert account.current_balance == Decimal('940')


@pytest.mark.django_db
@pytest.mark.parametrize('target', ['title', 'account'])
def test_review_deferred_load_does_not_erase_dirty_metadata(ledger, target):
    make_title, account = ledger
    title = make_title()
    model = FinancialTitle if target == 'title' else FinancialAccount
    field = 'notes' if target == 'title' else 'name'
    stale = model.objects.only(field).get(pk=title.pk if target == 'title' else account.pk)
    setattr(stale, field, 'Deferred metadata')
    # Lazy loading another column must not reset the dirty field's baseline.
    assert stale.title_number if target == 'title' else stale.account_type
    settle(title, account)
    stale.save()
    stale.refresh_from_db()
    title.refresh_from_db()
    account.refresh_from_db()
    assert getattr(stale, field) == 'Deferred metadata'
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert account.current_balance == Decimal('940')
