"""HTTP regressions with real DB/domain mutations and synthetic local records."""

import hashlib
import json
import tempfile

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APIClient

from files.models import ProtectedFile, ProtectedFileAccessRule, ProtectedFileAuditTrail
from integrations.models import IntegrationConnector, IntegrationEvent

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def make_actor(name, *permissions, staff=False):
    actor = get_user_model().objects.create_user(
        username=name, email=f'{name}@example.test', is_staff=staff
    )
    for permission in permissions:
        app, codename = permission.split('.')
        actor.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=codename)
        )
    return actor


def make_file(owner):
    return ProtectedFile.objects.create(
        source_module='administrative',
        source_model='ReviewSynthetic',
        source_record_id='1',
        file_type='other',
        origin='upload',
        criticality='low',
        confidentiality='restricted',
        title='Synthetic review file',
        file_name='fake.txt',
        file_reference='review-synthetic/fake.txt',
        content_hash='synthetic-review-hash',
        responsible=owner,
        uploaded_by=owner,
    )


def grant_file_access(protected_file, actor, permission):
    ProtectedFileAccessRule.objects.create(
        protected_file=protected_file, rule_type='user', user=actor, permission=permission
    )


def post_action(client, actor, channel, module, resource, obj, action, payload):
    with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
        return _post_action(client, actor, channel, module, resource, obj, action, payload)


def _post_action(client, actor, channel, module, resource, obj, action, payload):
    if channel == 'api':
        api = APIClient()
        api.force_authenticate(actor)
        multipart = any(hasattr(value, 'read') for value in payload.values())
        return api.post(
            f'/api/{module}/{resource}/{obj.pk}/{action}/',
            payload,
            format='multipart' if multipart else 'json',
        )
    client.force_login(actor)
    url = reverse('app:resource_action', args=(module, resource, obj.pk, action))
    html_payload = {
        key: json.dumps(value) if isinstance(value, dict) else value
        for key, value in payload.items()
    }
    return client.post(url, {**html_payload, 'confirmation_acknowledged': True})


@pytest.mark.parametrize('channel', ['api', 'ui'])
@pytest.mark.parametrize('action', ['delete_secure', 'expire'])
@pytest.mark.parametrize('grant', ['view', 'manage'])
def test_file_lifecycle_requires_manage_even_with_model_change(client, channel, action, grant):
    owner = make_actor('file-owner')
    actor = make_actor('file-actor', 'files.view_protectedfile', 'files.change_protectedfile')
    protected_file = make_file(owner)
    grant_file_access(protected_file, actor, grant)
    response = post_action(
        client,
        actor,
        channel,
        'files',
        'protected-files',
        protected_file,
        action,
        {'reason': 'Synthetic lifecycle correction'},
    )
    protected_file.refresh_from_db()
    if grant == 'view':
        assert response.status_code == 403
        assert protected_file.status == ProtectedFile.Status.ACTIVE
        assert protected_file.deleted_by_id is None
        assert not protected_file.audit_trail.exists()
    else:
        assert response.status_code == (200 if channel == 'api' else 302)
        expected_status = (
            ProtectedFile.Status.DELETED
            if action == 'delete_secure'
            else ProtectedFile.Status.EXPIRED
        )
        expected_audit = (
            ProtectedFileAuditTrail.Action.DELETE
            if action == 'delete_secure'
            else ProtectedFileAuditTrail.Action.EXPIRE
        )
        assert protected_file.status == expected_status
        assert protected_file.audit_trail.filter(action=expected_audit, actor=actor).count() == 1
        if action == 'delete_secure':
            assert protected_file.deleted_by_id == actor.pk
            assert protected_file.deletion_reason == 'Synthetic lifecycle correction'


@pytest.mark.parametrize('channel', ['api', 'ui'])
@pytest.mark.parametrize('action', ['replace', 'revoke'])
@pytest.mark.parametrize('grant', ['view', 'manage'])
def test_other_file_management_actions_require_manage(client, channel, action, grant):
    owner = make_actor('other-file-owner')
    actor = make_actor(
        'other-file-actor',
        'files.view_protectedfile',
        'files.change_protectedfile',
        'files.add_protectedfile',
        'files.view_securefilelink',
        'files.change_securefilelink',
    )
    protected_file = make_file(owner)
    grant_file_access(protected_file, actor, grant)
    if action == 'replace':
        target = protected_file
        resource = 'protected-files'
        replacement_content = b'synthetic body'
        payload = {
            'file': SimpleUploadedFile('replacement.txt', replacement_content),
            'new_file_name': 'replacement.txt',
            'content_hash': f'sha256:{hashlib.sha256(replacement_content).hexdigest()}',
            'reason': 'Synthetic replacement',
            'file_size': len(replacement_content),
            'mime_type': 'text/plain',
        }
    else:
        target = protected_file.generate_secure_link(owner)
        resource = 'secure-links'
        payload = {'reason': 'Synthetic revocation'}
    audit_count = protected_file.audit_trail.count()
    file_count = ProtectedFile.objects.count()
    response = post_action(client, actor, channel, 'files', resource, target, action, payload)
    protected_file.refresh_from_db()
    target.refresh_from_db()
    if grant == 'view':
        assert response.status_code == 403
        assert protected_file.status == ProtectedFile.Status.ACTIVE
        assert protected_file.replaced_by_id is None
        assert protected_file.audit_trail.count() == audit_count
        assert ProtectedFile.objects.count() == file_count
        if action == 'revoke':
            assert not target.is_revoked
    else:
        expected_response = (201 if action == 'replace' else 200) if channel == 'api' else 302
        assert response.status_code == expected_response
        if action == 'replace':
            assert protected_file.status == ProtectedFile.Status.SUPERSEDED
            replacement = protected_file.replaced_by
            assert replacement.supersedes_id == protected_file.pk
            assert replacement.uploaded_by_id == actor.pk
            assert replacement.file_name == 'replacement.txt'
            expected_audit = ProtectedFileAuditTrail.Action.REPLACE
        else:
            assert target.is_revoked
            assert target.revoked_by_id == actor.pk
            expected_audit = ProtectedFileAuditTrail.Action.LINK_REVOKED
        assert protected_file.audit_trail.filter(action=expected_audit, actor=actor).count() == 1


@pytest.fixture
def fiscal_connector(settings, monkeypatch):
    def reject_network(*args, **kwargs):
        raise AssertionError('Provider network is forbidden in this synthetic HTTP test.')

    monkeypatch.setattr('socket.create_connection', reject_network)
    monkeypatch.setattr('socket.socket.connect', reject_network)
    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {'https://review-fiscal.example.test': []}
    return IntegrationConnector.objects.create(
        code='REVIEW-FISCAL-SYNTHETIC',
        name='Synthetic fiscal connector',
        provider_type=IntegrationConnector.ProviderType.FISCAL_SYSTEM,
        base_url='https://review-fiscal.example.test',
    )


@pytest.mark.parametrize('channel', ['api', 'ui'])
@pytest.mark.parametrize('action', ['activate', 'suspend', 'test_success', 'test_failure'])
@pytest.mark.parametrize(
    'authority', ['nonstaff_with_change', 'staff_with_change', 'staff_no_change']
)
def test_fiscal_connector_actions_require_staff_and_model_permission(
    client,
    fiscal_connector,
    channel,
    action,
    authority,
):
    permissions = ['integrations.view_integrationconnector']
    if authority != 'staff_no_change':
        permissions.append('integrations.change_integrationconnector')
    actor = make_actor(
        'fiscal-action-actor', *permissions, staff=authority != 'nonstaff_with_change'
    )
    payload = {
        'reason': 'Synthetic suspension',
        'error_message': 'Synthetic failure',
        'details': {'synthetic': True},
    }
    before = (
        fiscal_connector.status,
        fiscal_connector.is_active,
        fiscal_connector.last_error,
        fiscal_connector.last_tested_at,
        fiscal_connector.updated_at,
    )
    response = post_action(
        client,
        actor,
        channel,
        'integrations',
        'connectors',
        fiscal_connector,
        action,
        payload,
    )
    fiscal_connector.refresh_from_db()
    if authority != 'staff_with_change':
        assert response.status_code == 403
        assert (
            fiscal_connector.status,
            fiscal_connector.is_active,
            fiscal_connector.last_error,
            fiscal_connector.last_tested_at,
            fiscal_connector.updated_at,
        ) == before
        assert not fiscal_connector.events.exists()
    else:
        assert response.status_code == (200 if channel == 'api' else 302)
        expected_status, expected_event = {
            'activate': (IntegrationConnector.Status.ACTIVE, IntegrationEvent.EventType.ACTIVATED),
            'suspend': (
                IntegrationConnector.Status.SUSPENDED,
                IntegrationEvent.EventType.SUSPENDED,
            ),
            'test_success': (
                IntegrationConnector.Status.ACTIVE,
                IntegrationEvent.EventType.TEST_SUCCESS,
            ),
            'test_failure': (
                IntegrationConnector.Status.ERROR,
                IntegrationEvent.EventType.TEST_FAILURE,
            ),
        }[action]
        assert fiscal_connector.status == expected_status
        assert fiscal_connector.events.filter(event_type=expected_event).count() == 1
        if action in {'test_success', 'test_failure'}:
            assert fiscal_connector.last_tested_at is not None
        if action == 'suspend':
            assert not fiscal_connector.is_active
            assert fiscal_connector.last_error == 'Synthetic suspension'
        if action == 'test_failure':
            assert fiscal_connector.last_error == 'Synthetic failure'


@pytest.mark.parametrize(
    'authority', ['nonstaff_with_delete', 'staff_with_delete', 'staff_no_delete']
)
def test_fiscal_connector_api_delete_requires_staff_and_model_permission(
    fiscal_connector, authority
):
    permissions = (
        [] if authority == 'staff_no_delete' else ['integrations.delete_integrationconnector']
    )
    actor = make_actor(
        'connector-delete-actor', *permissions, staff=authority != 'nonstaff_with_delete'
    )
    api = APIClient()
    api.force_authenticate(actor)
    pk = fiscal_connector.pk
    response = api.delete(f'/api/integrations/connectors/{pk}/')
    if authority == 'staff_with_delete':
        assert response.status_code == 204
        assert not IntegrationConnector.objects.filter(pk=pk).exists()
    else:
        assert response.status_code == 403
        assert IntegrationConnector.objects.filter(pk=pk).exists()


@pytest.mark.parametrize('staff', [False, True])
def test_fiscal_test_failure_checks_authority_before_payload_validation(
    client, fiscal_connector, staff
):
    actor = make_actor(
        'invalid-fiscal-test-actor', 'integrations.change_integrationconnector', staff=staff
    )
    response = post_action(
        client,
        actor,
        'api',
        'integrations',
        'connectors',
        fiscal_connector,
        'test_failure',
        {},
    )
    assert response.status_code == (400 if staff else 403)
    assert not fiscal_connector.events.exists()


@pytest.mark.parametrize('action', ['activate', 'suspend', 'test_success', 'test_failure'])
def test_nonfiscal_connector_actions_remain_available_to_nonstaff_with_change(client, action):
    actor = make_actor('erp-actor', 'integrations.change_integrationconnector')
    connector = IntegrationConnector.objects.create(
        code='REVIEW-ERP',
        name='Synthetic nonfiscal connector',
        provider_type=IntegrationConnector.ProviderType.ERP,
        base_url='https://erp.example.test',
    )
    response = post_action(
        client,
        actor,
        'api',
        'integrations',
        'connectors',
        connector,
        action,
        {'reason': 'Synthetic suspension', 'error_message': 'Synthetic failure'},
    )
    assert response.status_code == 200
    assert connector.events.count() == 1


def test_fiscal_trusted_internal_domain_calls_remain_available(fiscal_connector):
    actor = make_actor('trusted-internal-nonstaff')
    fiscal_connector.activate(user=actor)
    fiscal_connector.suspend(reason='Synthetic internal suspension', user=actor)
    fiscal_connector.record_test_success({'synthetic': True})
    fiscal_connector.record_test_failure('Synthetic internal failure')
    fiscal_connector.refresh_from_db()
    assert fiscal_connector.status == IntegrationConnector.Status.ERROR
    assert fiscal_connector.events.count() == 4


@pytest.mark.parametrize('action', ['delete_secure', 'expire', 'replace', 'revoke'])
def test_file_manage_does_not_replace_model_permissions(client, action):
    actor = make_actor('manager-without-model-permission')
    protected_file = make_file(actor)
    if action == 'revoke':
        target = protected_file.generate_secure_link(actor)
        resource = 'secure-links'
    else:
        target = protected_file
        resource = 'protected-files'
    audit_count = protected_file.audit_trail.count()
    response = post_action(
        client,
        actor,
        'api',
        'files',
        resource,
        target,
        action,
        {'reason': 'Synthetic denied operation'},
    )
    assert response.status_code == 403
    protected_file.refresh_from_db()
    assert protected_file.status == ProtectedFile.Status.ACTIVE
    assert protected_file.audit_trail.count() == audit_count


@pytest.mark.parametrize('ownership', ['responsible', 'uploaded_by'])
@pytest.mark.parametrize('action', ['delete_secure', 'expire'])
def test_existing_file_owner_and_uploader_management_remains_valid(client, action, ownership):
    owner = make_actor('original-owner')
    actor = make_actor('legitimate-file-actor', 'files.change_protectedfile')
    protected_file = make_file(owner)
    setattr(protected_file, ownership, actor)
    protected_file.save(update_fields=[ownership])
    response = post_action(
        client,
        actor,
        'api',
        'files',
        'protected-files',
        protected_file,
        action,
        {'reason': 'Synthetic legitimate management'},
    )
    assert response.status_code == 200
    protected_file.refresh_from_db()
    assert protected_file.status == (
        ProtectedFile.Status.DELETED if action == 'delete_secure' else ProtectedFile.Status.EXPIRED
    )
