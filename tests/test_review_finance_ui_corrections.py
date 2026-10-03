"""Real HTTP regressions for the financial resource form integration."""

from dataclasses import replace
from decimal import Decimal

from base.ui.forms import build_resource_form
from base.ui.registry import InlineResourceConfig, get_resource
from base.ui.views import ResourceCreateView, ResourceUpdateView

import pytest
from django.test import Client
from django.urls import reverse

from finance.models import CashFlowEntry, FinancialSettlement, FinancialTitle
from governance.models import GovernanceAuditLog
from tests.test_finance_corrections import ledger as ledger
from tests.test_finance_corrections import settle
from tests.test_security_corrections import make_user

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def title_payload(title, **changes):
    payload = {
        'title_type': title.title_type,
        'source_type': title.source_type,
        'partner': title.partner_id,
        'category': title.category_id,
        'financial_account': title.financial_account_id or '',
        'issue_date': title.issue_date.isoformat(),
        'due_date': title.due_date.isoformat(),
        'original_amount': str(title.original_amount),
        'open_amount': str(title.open_amount),
        'paid_amount': str(title.paid_amount),
        'status': title.status,
        'notes': title.notes,
    }
    return payload | changes


def ui_client(*permissions):
    user = make_user('financial-form-review', *permissions)
    assert not user.is_superuser
    client = Client()
    client.force_login(user)
    return client


def pending_title(factory):
    approved = factory()
    approved.delete()
    return FinancialTitle.objects.create(
        title_type=approved.title_type,
        partner=approved.partner,
        category=approved.category,
        original_amount=Decimal('100'),
        open_amount=Decimal('100'),
        issue_date=approved.issue_date,
        due_date=approved.due_date,
    )


@pytest.mark.parametrize('injected_open', [None, '80', '-1', '999'])
def test_pending_title_lower_amount_derives_open_ignoring_injected_aggregates(
    ledger, injected_open
):
    factory, _account = ledger
    title = pending_title(factory)
    client = ui_client('finance.view_financialtitle', 'finance.change_financialtitle')
    payload = title_payload(title, original_amount='80', open_amount='80')
    if injected_open is not None:
        payload.update(
            open_amount=injected_open,
            paid_amount='999',
            status='approved',
            approved_by=client.session['_auth_user_id'],
            approved_at='2026-01-01T00:00:00Z',
        )
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'titles', title.pk)), payload
    )
    assert response.status_code == 302
    title.refresh_from_db()
    assert title.original_amount == title.open_amount == Decimal('80')
    assert title.paid_amount == 0
    assert title.status == FinancialTitle.Status.PENDING
    assert title.approved_at is None
    assert title.approved_by_id is None


def test_pending_title_direction_remains_editable_before_first_launch(ledger):
    factory, _account = ledger
    title = pending_title(factory)
    client = ui_client('finance.view_financialtitle', 'finance.change_financialtitle')
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'titles', title.pk)),
        title_payload(title, title_type='receivable', notes='Legitimate prelaunch edit'),
    )
    assert response.status_code == 302
    title.refresh_from_db()
    assert title.title_type == FinancialTitle.TitleType.RECEIVABLE
    assert title.original_amount == title.open_amount == Decimal('100')
    assert title.status == FinancialTitle.Status.PENDING


def ledger_snapshot(title, account):
    return {
        'title': FinancialTitle.objects.filter(pk=title.pk).values().get(),
        'account': type(account).objects.filter(pk=account.pk).values().get(),
        'settlements': list(FinancialSettlement.objects.filter(title=title).values()),
        'cash_flow': list(CashFlowEntry.objects.filter(title=title).order_by('pk').values()),
        'audit': list(GovernanceAuditLog.objects.order_by('pk').values()),
    }


@pytest.mark.parametrize('settled_amount', ['60', '100'])
@pytest.mark.parametrize('reversed_entry', [False, True])
@pytest.mark.parametrize(
    'changes',
    [{'title_type': 'receivable'}, {'original_amount': '80'}, {'original_amount': '30'}],
)
def test_posted_economic_edit_renders_bound_errors_without_any_write(
    ledger, reversed_entry, changes, settled_amount
):
    factory, account = ledger
    title = factory()
    CashFlowEntry.create_from_title(title)
    entry = settle(title, account, amount=settled_amount)
    CashFlowEntry.create_from_settlement(entry)
    if reversed_entry:
        entry.reverse('Review reversal')
    title.refresh_from_db()
    client = ui_client('finance.view_financialtitle', 'finance.change_financialtitle')
    before = ledger_snapshot(title, account)
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'titles', title.pk)),
        title_payload(title, notes='Must roll back too', **changes),
    )
    assert response.status_code == 200
    assert response.context['form'].is_bound
    assert response.context['form'].errors
    if not reversed_entry and Decimal(changes.get('original_amount', '100')) < Decimal(
        settled_amount
    ):
        assert response.context['form'].non_field_errors()
    assert ledger_snapshot(title, account) == before
    entry.refresh_from_db()
    if not reversed_entry:
        entry.reverse('Direction remains payable')
    account.refresh_from_db()
    assert account.current_balance == account.opening_balance == Decimal('1000')
    assert set(CashFlowEntry.objects.filter(title=title).values_list('direction', flat=True)) == {
        CashFlowEntry.Direction.OUTFLOW
    }


def account_payload(account, **changes):
    return {
        'name': account.name,
        'account_type': account.account_type,
        'opening_balance': str(account.opening_balance),
        'current_balance': str(account.current_balance),
        'is_active': 'on',
    } | changes


@pytest.mark.parametrize('reversed_entry', [False, True])
def test_posted_account_opening_edit_renders_error_and_rolls_back_name_and_events(
    ledger, reversed_entry
):
    factory, account = ledger
    title = factory()
    entry = settle(title, account)
    if reversed_entry:
        entry.reverse('Review reversal')
    account.refresh_from_db()
    client = ui_client('finance.view_financialaccount', 'finance.change_financialaccount')
    before = ledger_snapshot(title, account)
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'accounts', account.pk)),
        account_payload(account, name='Must roll back', opening_balance='100'),
    )
    assert response.status_code == 200
    assert 'opening_balance' in response.context['form'].errors
    assert ledger_snapshot(title, account) == before


@pytest.mark.parametrize('injected_open', [None, '-1', '999'])
def test_title_creation_omits_aggregates_and_derives_open_before_model_validation(
    ledger, injected_open
):
    factory, _account = ledger
    exemplar = factory()
    client = ui_client('finance.view_financialtitle', 'finance.add_financialtitle')
    url = reverse('app:resource_create', args=('finance', 'titles'))
    get_response = client.get(url)
    fields = get_response.context['form'].fields
    assert not FinancialTitle.SERVICE_FIELDS.intersection(fields)
    assert fields['original_amount'].required
    assert fields['partner'].required
    assert fields['due_date'].widget.input_type == 'date'
    assert fields['notes'].widget.attrs['data-field-size'] == 'full'
    payload = title_payload(
        exemplar, notes='New pending title', status='settled', paid_amount='999'
    )
    payload.pop('open_amount')
    if injected_open is not None:
        payload['open_amount'] = injected_open
    response = client.post(url, payload)
    assert response.status_code == 302
    title = FinancialTitle.objects.exclude(pk=exemplar.pk).get()
    assert title.title_number
    assert title.original_amount == title.open_amount == Decimal('100')
    assert title.paid_amount == 0
    assert title.status == FinancialTitle.Status.PENDING
    assert title.approved_at is None
    assert title.notes == 'New pending title'


@pytest.mark.parametrize('missing', ['original_amount', 'partner', 'category', 'due_date'])
def test_title_creation_required_fields_still_render_errors(ledger, missing):
    factory, _account = ledger
    exemplar = factory()
    client = ui_client('finance.view_financialtitle', 'finance.add_financialtitle')
    before = FinancialTitle.objects.count()
    payload = title_payload(exemplar)
    payload.pop(missing)
    response = client.post(reverse('app:resource_create', args=('finance', 'titles')), payload)
    assert response.status_code == 200
    assert missing in response.context['form'].errors
    assert FinancialTitle.objects.count() == before


def test_account_creation_and_prelaunch_opening_edit_derive_current_balance(ledger):
    _factory, exemplar = ledger
    client = ui_client(
        'finance.view_financialaccount',
        'finance.add_financialaccount',
        'finance.change_financialaccount',
    )
    url = reverse('app:resource_create', args=('finance', 'accounts'))
    fields = client.get(url).context['form'].fields
    assert 'current_balance' not in fields
    response = client.post(
        url,
        account_payload(exemplar, name='New account', opening_balance='100', current_balance='999'),
    )
    assert response.status_code == 302
    account = type(exemplar).objects.exclude(pk=exemplar.pk).get()
    assert account.opening_balance == account.current_balance == Decimal('100')
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'accounts', account.pk)),
        account_payload(account, opening_balance='80', current_balance='-999'),
    )
    assert response.status_code == 302
    account.refresh_from_db()
    assert account.opening_balance == account.current_balance == Decimal('80')


def test_stale_http_notes_and_name_payloads_do_not_overwrite_new_ledger_aggregates(ledger):
    factory, account = ledger
    title = factory()
    title_data = title_payload(title, notes='Safe stale note')
    account_data = account_payload(account, name='Safe stale name')
    approved_at = title.approved_at
    settle(title, account)
    client = ui_client(
        'finance.view_financialtitle',
        'finance.change_financialtitle',
        'finance.view_financialaccount',
        'finance.change_financialaccount',
    )
    assert (
        client.post(
            reverse('app:resource_edit', args=('finance', 'titles', title.pk)), title_data
        ).status_code
        == 302
    )
    assert (
        client.post(
            reverse('app:resource_edit', args=('finance', 'accounts', account.pk)), account_data
        ).status_code
        == 302
    )
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.notes == 'Safe stale note'
    assert account.name == 'Safe stale name'
    assert title.paid_amount == Decimal('60')
    assert title.open_amount == Decimal('40')
    assert title.status == FinancialTitle.Status.PARTIALLY_SETTLED
    assert title.approved_at == approved_at
    assert account.current_balance == Decimal('940')


@pytest.mark.parametrize('commit', [False, True])
def test_provider_save_after_validation_preserves_concurrent_settlement_state(ledger, commit):
    factory, account = ledger
    title = factory()
    view = ResourceUpdateView()
    view.resource = get_resource('finance', 'titles')
    form = view.get_form_class()(
        title_payload(title, notes='Validated before booking'), instance=title
    )
    assert form.is_valid(), form.errors
    settle(FinancialTitle.objects.get(pk=title.pk), account)
    obj = form.save(commit=commit)
    if not commit:
        obj.save(**form.resource_save_kwargs())
        form.save_m2m()
    obj.refresh_from_db()
    assert obj.notes == 'Validated before booking'
    assert obj.paid_amount == Decimal('60')
    assert obj.open_amount == Decimal('40')
    assert obj.status == FinancialTitle.Status.PARTIALLY_SETTLED


def test_direct_provider_save_derives_lower_open_without_authorizing_aggregate_edit(ledger):
    factory, _account = ledger
    title = pending_title(factory)
    form = build_resource_form(get_resource('finance', 'titles'), update=True)(
        title_payload(title, original_amount='80', open_amount='999'), instance=title
    )
    assert form.is_valid(), form.errors
    assert form.instance.open_amount == Decimal('80')
    selected = form.resource_save_kwargs()['update_fields']
    assert 'original_amount' in selected
    assert not FinancialTitle.SERVICE_FIELDS.intersection(selected)
    obj = form.save()
    obj.refresh_from_db()
    assert obj.original_amount == obj.open_amount == Decimal('80')


def test_late_inline_financial_rejection_rolls_back_parent_first_booking_and_events(
    ledger, monkeypatch
):
    factory, account = ledger
    title = factory()
    resource = replace(
        get_resource('finance', 'titles'),
        inlines=(
            InlineResourceConfig(
                'review_settlements',
                'Review settlements',
                FinancialSettlement,
                'title',
                ('financial_account', 'settlement_date', 'method', 'amount'),
            ),
        ),
    )
    # Only UI metadata is supplied for this rollback probe; all domain methods,
    # row locks and ledger writes execute unchanged against PostgreSQL.
    original_get_resource = ResourceCreateView.get_resource

    def get_review_resource(view):
        if view.kwargs.get('resource_slug') == 'titles':
            return resource
        return original_get_resource(view)

    monkeypatch.setattr(ResourceCreateView, 'get_resource', get_review_resource)
    client = ui_client(
        'finance.view_financialtitle',
        'finance.change_financialtitle',
        'finance.view_financialsettlement',
        'finance.add_financialsettlement',
    )
    payload = title_payload(title, notes='Rollback parent too') | {
        'review_settlements-TOTAL_FORMS': '2',
        'review_settlements-INITIAL_FORMS': '0',
        'review_settlements-MIN_NUM_FORMS': '0',
        'review_settlements-MAX_NUM_FORMS': '1000',
    }
    for index in range(2):
        payload.update(
            {
                f'review_settlements-{index}-financial_account': account.pk,
                f'review_settlements-{index}-settlement_date': title.issue_date.isoformat(),
                f'review_settlements-{index}-method': 'pix',
                f'review_settlements-{index}-amount': '60',
            }
        )
    before = ledger_snapshot(title, account)
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'titles', title.pk)), payload
    )
    assert response.status_code == 200
    assert response.context['form'].non_field_errors()
    assert 'saldo em aberto' in str(response.context['form'].non_field_errors())
    assert not response.context['inline_formsets'][0]['formset'].errors[0]
    assert ledger_snapshot(title, account) == before
