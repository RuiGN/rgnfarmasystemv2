"""UI integration keeps safe operational writes, not generic ledger changes."""

from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from base.ui.registry import get_resource
from base.ui.views import ResourceCreateView, ResourceUpdateView
from finance.models import FinancialSettlement
from tests.test_finance_corrections import ledger as ledger
from tests.test_security_corrections import make_user

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def test_stock_balance_zero_metadata_form_remains_available_without_quantity_fields():
    user = make_user('balance-ui', 'inventory.add_stockbalance')
    resource = get_resource('inventory', 'balances')
    assert resource.can_add(user)
    create = ResourceCreateView()
    create.resource = resource
    form = create.get_form_class()(request=SimpleNamespace(user=user))
    assert set(form.fields) == {'product', 'lot', 'warehouse', 'location', 'unit'}
    update = ResourceUpdateView()
    update.resource = resource
    assert not update.get_form_class()(request=SimpleNamespace(user=user)).fields


def test_finance_ui_creation_books_ledger_update_only_notes_and_delete_forbidden(ledger):
    title_factory, account = ledger
    title = title_factory()
    user = make_user(
        'finance-ui',
        'finance.add_financialsettlement',
        'finance.view_financialsettlement',
        'finance.change_financialsettlement',
        'finance.delete_financialsettlement',
    )
    client = Client()
    client.force_login(user)
    resource = get_resource('finance', 'settlements')
    response = client.post(
        reverse('app:resource_create', args=('finance', 'settlements')),
        {
            'title': title.pk,
            'financial_account': account.pk,
            'settlement_date': timezone.localdate().isoformat(),
            'method': 'pix',
            'amount': '60.00',
            'interest_amount': '0.00',
            'penalty_amount': '0.00',
            'discount_amount': '0.00',
            'reference': 'SYNTHETIC-UI',
            'notes': 'Initial',
            'status': 'reversed',
            'net_amount': '999.00',
        },
    )
    assert response.status_code == 302
    settlement = FinancialSettlement.objects.get(title=title)
    title.refresh_from_db()
    account.refresh_from_db()
    assert title.open_amount == Decimal('40.00')
    assert account.current_balance == Decimal('940.00')
    assert settlement.status == FinancialSettlement.Status.ACTIVE
    assert settlement.amount == Decimal('60.00')
    response = client.post(
        reverse('app:resource_edit', args=('finance', 'settlements', settlement.pk)),
        {'notes': 'Amended', 'amount': '99.00', 'status': 'reversed'},
    )
    assert response.status_code == 302
    settlement.refresh_from_db()
    assert settlement.notes == 'Amended'
    assert settlement.amount == Decimal('60.00')
    assert settlement.status == FinancialSettlement.Status.ACTIVE
    assert not resource.can_delete(user)
    response = client.post(
        reverse('app:resource_delete', args=('finance', 'settlements', settlement.pk))
    )
    assert response.status_code == 403
    assert FinancialSettlement.objects.filter(pk=settlement.pk).exists()
