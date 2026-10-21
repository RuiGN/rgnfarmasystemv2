"""Ações de coleção distinguem criação de alteração de registros existentes."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse
from rest_framework.test import APIClient

from base.permissions import SingleInstanceDjangoModelPermissions
from base.ui.actions.discovery import discover_post_actions
from compliance.models import ComplianceChecklistItem
from compliance.services import evaluate_module_readiness


@pytest.fixture
def checklist(db):
    owner = get_user_model().objects.create_user(
        username='p1-check-owner', email='p1-check-owner@example.test'
    )
    evaluate_module_readiness(module='production', user=owner)
    return list(
        ComplianceChecklistItem.objects.filter(source_module='production').values(
            'pk', 'status', 'evidence', 'checked_by_id', 'checked_at'
        )
    )


def reviewer(*permissions):
    user = get_user_model().objects.create_user(
        username='p1-check-reviewer', email='p1-check-reviewer@example.test'
    )
    user.user_permissions.add(
        *Permission.objects.filter(content_type__app_label='compliance', codename__in=permissions)
    )
    return user


@pytest.mark.parametrize('prefix', ['/api/', '/api/v1/'])
@pytest.mark.parametrize(
    'permissions', [(), ('add_compliancechecklistitem',), ('change_compliancechecklistitem',)]
)
def test_incomplete_permissions_cannot_overwrite_checks(checklist, prefix, permissions):
    user = reviewer(*permissions)
    api = APIClient()
    api.force_authenticate(user)

    response = api.post(
        f'{prefix}compliance/checklist-items/evaluate_module/',
        {'module': 'production'},
        format='json',
    )

    assert response.status_code == 403
    assert (
        list(
            ComplianceChecklistItem.objects.filter(source_module='production').values(
                'pk', 'status', 'evidence', 'checked_by_id', 'checked_at'
            )
        )
        == checklist
    )


def test_add_and_change_can_evaluate_existing_and_new_checks(checklist):
    user = reviewer('add_compliancechecklistitem', 'change_compliancechecklistitem')
    api = APIClient()
    api.force_authenticate(user)
    for module in ('production', 'inventory'):
        response = api.post(
            '/api/compliance/checklist-items/evaluate_module/', {'module': module}, format='json'
        )
        assert response.status_code == 200, response.data
        assert ComplianceChecklistItem.objects.filter(source_module=module).exists()
        assert (
            not ComplianceChecklistItem.objects.filter(source_module=module)
            .exclude(checked_by=user)
            .exists()
        )


def test_html_action_denies_add_only_reviewer(checklist, client):
    user = reviewer('view_compliancechecklistitem', 'add_compliancechecklistitem')
    client.force_login(user)
    url = reverse(
        'app:collection_action',
        kwargs={
            'module_slug': 'compliance',
            'resource_slug': 'checklist-items',
            'action_name': 'evaluate_module',
        },
    )
    assert client.get(url).status_code == 403
    assert client.post(url, {'module': 'production'}).status_code == 403
    assert (
        list(
            ComplianceChecklistItem.objects.filter(source_module='production').values(
                'pk', 'status', 'evidence', 'checked_by_id', 'checked_at'
            )
        )
        == checklist
    )


def test_unconfigured_collection_write_requires_change_not_add():
    requested = []
    user = SimpleNamespace(
        is_authenticated=True,
        has_perms=lambda permissions: (
            requested.append(permissions)
            or permissions == ['compliance.add_compliancechecklistitem']
        ),
    )
    view = SimpleNamespace(
        action='evaluate', detail=False, queryset=ComplianceChecklistItem.objects.all()
    )
    request = SimpleNamespace(method='POST', user=user)

    assert not SingleInstanceDjangoModelPermissions().has_permission(request, view)
    assert requested == [['compliance.change_compliancechecklistitem']]


def test_discovery_matches_explicit_collection_permission_contracts():
    actions = {
        (action.app_label, action.action_name): action
        for action in discover_post_actions()
        if not action.detail
    }
    assert actions[('compliance', 'evaluate_module')].permissions == (
        'compliance.add_compliancechecklistitem',
        'compliance.change_compliancechecklistitem',
    )
    for key, permission in (
        (('finance', 'from_title'), 'finance.add_cashflowentry'),
        (('finance', 'from_settlement'), 'finance.add_cashflowentry'),
        (('fiscal', 'from_document'), 'fiscal.add_fiscalbookentry'),
        (('procurement', 'import_xml'), 'procurement.add_purchasereceipt'),
        (('risks', 'generate'), 'risks.add_riskalert'),
        (('inventory', 'issue'), 'inventory.add_stockmovement'),
    ):
        action = actions[key]
        assert action.permissions == (permission,)
        assert action.viewset.action_permission_map[action.action_name] == (permission,)
