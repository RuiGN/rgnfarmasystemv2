"""Real HTML/DB regressions for generic fiscal connector deletion authorization."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from governance.models import GovernanceAuditLog
from integrations.models import IntegrationConnector, IntegrationEvent

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


@pytest.fixture
def connector(settings, monkeypatch):
    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {'https://ui-fiscal.example.test': []}
    connector = IntegrationConnector.objects.create(
        code='UI-DELETE-FISCAL',
        name='Synthetic fiscal deletion review',
        provider_type=IntegrationConnector.ProviderType.FISCAL_SYSTEM,
        base_url='https://ui-fiscal.example.test',
    )

    def reject_network(*args, **kwargs):
        raise AssertionError('Provider network is forbidden in this synthetic HTML test.')

    monkeypatch.setattr('socket.create_connection', reject_network)
    monkeypatch.setattr('socket.socket.connect', reject_network)
    return connector


def make_actor(*permissions, staff=False, superuser=False):
    actor = get_user_model().objects.create_user(
        username='ui-fiscal-delete-actor',
        email='ui-fiscal-delete-actor@example.test',
        is_staff=staff,
        is_superuser=superuser,
    )
    for codename in permissions:
        actor.user_permissions.add(
            Permission.objects.get(content_type__app_label='integrations', codename=codename)
        )
    return actor


def delete_url(connector):
    return reverse('app:resource_delete', args=('integrations', 'connectors', connector.pk))


def snapshot(connector):
    return (
        IntegrationConnector.objects.filter(pk=connector.pk).values().get(),
        list(IntegrationEvent.objects.filter(connector=connector).values().order_by('pk')),
        list(
            GovernanceAuditLog.objects.filter(
                target_model='IntegrationConnector', target_record_id=str(connector.pk)
            )
            .values()
            .order_by('pk')
        ),
    )


@pytest.mark.parametrize(
    'authority',
    ['nonstaff_with_view_delete', 'staff_with_view_delete', 'staff_no_delete', 'staff_no_view'],
)
def test_html_fiscal_delete_requires_staff_view_and_delete(client, connector, authority):
    permissions = []
    if authority != 'staff_no_view':
        permissions.append('view_integrationconnector')
    if authority != 'staff_no_delete':
        permissions.append('delete_integrationconnector')
    actor = make_actor(*permissions, staff=authority != 'nonstaff_with_view_delete')
    client.force_login(actor)
    before = snapshot(connector)
    response = client.post(delete_url(connector))
    if authority == 'staff_with_view_delete':
        assert response.status_code == 302
        assert response.url == reverse('app:resource_list', args=('integrations', 'connectors'))
        assert not IntegrationConnector.objects.filter(pk=connector.pk).exists()
        audit = GovernanceAuditLog.objects.get(
            action='ui.resource.deleted',
            target_model='IntegrationConnector',
            target_record_id=str(connector.pk),
        )
        assert audit.user_id == actor.pk
    else:
        assert response.status_code == 403
        assert snapshot(connector) == before


@pytest.mark.parametrize(
    'authority', ['nonstaff_with_delete', 'staff_with_delete', 'staff_no_delete', 'staff_no_view']
)
def test_html_fiscal_delete_preview_authorization(client, connector, authority):
    permissions = []
    if authority != 'staff_no_view':
        permissions.append('view_integrationconnector')
    if authority != 'staff_no_delete':
        permissions.append('delete_integrationconnector')
    actor = make_actor(*permissions, staff=authority != 'nonstaff_with_delete')
    client.force_login(actor)
    before = snapshot(connector)
    response = client.get(delete_url(connector))
    assert response.status_code == (200 if authority == 'staff_with_delete' else 403)
    assert snapshot(connector) == before


@pytest.mark.parametrize('method', ['get', 'post'])
@pytest.mark.parametrize('staff', [False, True])
def test_html_fiscal_delete_does_not_treat_superuser_as_staff(client, connector, method, staff):
    actor = make_actor(staff=staff, superuser=True)
    client.force_login(actor)
    before = snapshot(connector)
    response = getattr(client, method)(delete_url(connector))
    if not staff:
        assert response.status_code == 403
        assert snapshot(connector) == before
    elif method == 'get':
        assert response.status_code == 200
        assert snapshot(connector) == before
    else:
        assert response.status_code == 302
        assert not IntegrationConnector.objects.filter(pk=connector.pk).exists()


@pytest.mark.parametrize('method', ['get', 'post'])
def test_html_nonfiscal_delete_remains_available_to_nonstaff(client, connector, method):
    connector.provider_type = IntegrationConnector.ProviderType.ERP
    connector.save()
    actor = make_actor('view_integrationconnector', 'delete_integrationconnector')
    client.force_login(actor)
    before = snapshot(connector)
    response = getattr(client, method)(delete_url(connector))
    if method == 'get':
        assert response.status_code == 200
        assert snapshot(connector) == before
    else:
        assert response.status_code == 302
        assert not IntegrationConnector.objects.filter(pk=connector.pk).exists()
        assert (
            GovernanceAuditLog.objects.filter(
                action='ui.resource.deleted',
                target_model='IntegrationConnector',
                target_record_id=str(connector.pk),
                user=actor,
            ).count()
            == 1
        )


@pytest.mark.parametrize('staff', [False, True])
def test_html_fiscal_delete_preserves_existing_event_semantics(client, connector, staff):
    actor = make_actor('view_integrationconnector', 'delete_integrationconnector', staff=staff)
    event = connector.record_event(
        IntegrationEvent.EventType.TEST_FAILURE, message='Synthetic history'
    )
    client.force_login(actor)
    before = snapshot(connector)
    event_before = IntegrationEvent.objects.values().get(pk=event.pk)
    response = client.post(delete_url(connector))
    assert response.status_code == (302 if staff else 403)
    if not staff:
        assert snapshot(connector) == before
    else:
        # IntegrationEvent.connector uses SET_NULL, not PROTECT. Preserve its
        # existing history contract rather than imposing new deletion policy.
        assert not IntegrationConnector.objects.filter(pk=connector.pk).exists()
        assert IntegrationEvent.objects.values().get(pk=event.pk) == {
            **event_before,
            'connector_id': None,
        }
        assert IntegrationEvent.objects.count() == 1
        assert response.url == reverse('app:resource_list', args=('integrations', 'connectors'))


def test_connector_has_no_registered_inline_or_bulk_delete_entry():
    from base.ui.actions.discovery import discover_post_actions
    from base.ui.registry import get_modules

    connector_resources = [
        (module.slug, resource.slug)
        for module in get_modules()
        for resource in module.resources
        if resource.model is IntegrationConnector
    ]
    assert connector_resources == [('integrations', 'connectors')]
    assert not any(
        inline.child_model is IntegrationConnector
        for module in get_modules()
        for resource in module.resources
        for inline in resource.inlines
    )
    assert not any(
        action.model is IntegrationConnector and not action.detail
        for action in discover_post_actions()
    )


@pytest.mark.parametrize('path', ['delete/', 'actions/delete/', 'actions/bulk-delete/'])
def test_html_bulk_delete_paths_are_not_available(client, connector, path):
    actor = make_actor('view_integrationconnector', 'delete_integrationconnector')
    client.force_login(actor)
    before = snapshot(connector)
    response = client.post(
        f'/app/integrations/connectors/{path}', {'ids': [connector.pk], 'DELETE': 'on'}
    )
    assert response.status_code == 404
    assert snapshot(connector) == before
