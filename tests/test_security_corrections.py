from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model

from knowledge.services import answer_question

pytestmark = [pytest.mark.django_db, pytest.mark.permission_strict]


def test_local_chat_never_recovers_external_embeddings(settings, monkeypatch):
    settings.RAG_CHAT_LOCAL_ONLY = True
    user = get_user_model().objects.create_user(
        username='local-security', email='local-security@example.test', password='fake-password'
    )
    external_retrieval = Mock(return_value=[])
    monkeypatch.setattr('knowledge.services._redis_retrieve_context', external_retrieval)
    gateway = Mock()
    monkeypatch.setattr('knowledge.openai_gateway.OpenAIGateway', gateway)
    result = answer_question(user, 'Como consultar arquivos?')
    assert result['answer']
    external_retrieval.assert_not_called()
    gateway.assert_not_called()


def test_local_chat_ignores_active_redis_index_and_both_external_gateways(settings, monkeypatch):
    from knowledge.models import KnowledgeIndexGeneration, KnowledgeSource, KnowledgeDocument

    settings.RAG_CHAT_LOCAL_ONLY = True
    source = KnowledgeSource.objects.create(
        code='SECURITY-MANUAL',
        title='Manual',
        source_type='system_manual',
        publisher='Synthetic',
        is_active=True,
        chat_eligible=True,
    )
    document = KnowledgeDocument.objects.create(
        source=source,
        title='Manual de arquivos',
        document_type='text',
        extracted_text='Consultar arquivos protegidos.',
    )
    document.replace_chunks(
        [{'content': 'Para consultar arquivos protegidos, abra o módulo Arquivos.'}]
    )
    KnowledgeIndexGeneration.objects.create(
        generation_id='security-active', redis_index_name='idx:security-active', status='active'
    )
    redis_gateway = Mock(side_effect=AssertionError('External embedding prohibited'))
    chat_gateway = Mock(side_effect=AssertionError('External answer prohibited'))
    monkeypatch.setattr('knowledge.retrieval.OpenAIGateway', redis_gateway)
    monkeypatch.setattr('knowledge.services.OpenAIGateway', chat_gateway)
    monkeypatch.setattr(
        'knowledge.services.knowledge_redis_health', Mock(return_value={'available': True})
    )
    user = make_user('local-active-index')
    result = answer_question(user, 'Como consultar arquivos protegidos?')
    assert result['citations']
    redis_gateway.assert_not_called()
    chat_gateway.assert_not_called()


def make_user(name, *permissions):
    from django.contrib.auth.models import Permission

    user = get_user_model().objects.create_user(
        username=name, email=f'{name}@example.test', password='fake-password'
    )
    for permission in permissions:
        app, codename = permission.split('.')
        user.user_permissions.add(
            Permission.objects.get(content_type__app_label=app, codename=codename)
        )
    return user


def make_file(owner, title='Private file'):
    from files.models import ProtectedFile

    return ProtectedFile.objects.create(
        source_module='administrative',
        source_model='SecurityTest',
        source_record_id='1',
        file_type='other',
        origin='upload',
        criticality='low',
        confidentiality='restricted',
        title=title,
        file_name='fake.txt',
        file_reference=f'fake/{owner.pk}-{title}.txt',
        content_hash=f'fake-hash-{owner.pk}-{title}',
        responsible=owner,
        uploaded_by=owner,
    )


def test_acl_create_requires_manage_not_model_add_permission():
    from files.models import ProtectedFileAccessRule
    from rest_framework.test import APIClient

    owner = make_user('acl-owner')
    attacker = make_user('acl-attacker', 'files.add_protectedfileaccessrule')
    protected_file = make_file(owner)
    client = APIClient()
    client.force_authenticate(attacker)
    response = client.post(
        '/api/files/access-rules/',
        {
            'protected_file': protected_file.pk,
            'rule_type': 'user',
            'user': attacker.pk,
            'permission': 'manage',
        },
        format='json',
    )
    assert response.status_code == 403, response.data
    assert not ProtectedFileAccessRule.objects.filter(protected_file=protected_file).exists()


@pytest.mark.parametrize('operation', ['list', 'edit', 'retarget'])
def test_acl_read_and_change_require_manage_on_both_targets(operation):
    from files.models import ProtectedFileAccessRule
    from rest_framework.test import APIClient

    owner = make_user('acl-owner')
    reader = make_user(
        'acl-reader', 'files.view_protectedfileaccessrule', 'files.change_protectedfileaccessrule'
    )
    protected_file = make_file(owner)
    rule = ProtectedFileAccessRule.objects.create(
        protected_file=protected_file, rule_type='user', user=reader, permission='view'
    )
    own_file = make_file(reader, 'Own file')
    own_rule = ProtectedFileAccessRule.objects.create(
        protected_file=own_file, rule_type='user', user=owner, permission='view'
    )
    client = APIClient()
    client.force_authenticate(reader)
    if operation == 'list':
        response = client.get('/api/files/access-rules/')
        assert response.status_code == 200
        rows = (
            response.data.get('results', []) if isinstance(response.data, dict) else response.data
        )
        assert rule.pk not in {row['id'] for row in rows}
        assert own_rule.pk in {row['id'] for row in rows}
    elif operation == 'edit':
        response = client.patch(
            f'/api/files/access-rules/{rule.pk}/', {'permission': 'manage'}, format='json'
        )
        assert response.status_code in {403, 404}
        rule.refresh_from_db()
        assert rule.permission == 'view'
    else:
        response = client.patch(
            f'/api/files/access-rules/{own_rule.pk}/',
            {'protected_file': protected_file.pk},
            format='json',
        )
        assert response.status_code in {403, 404}
        own_rule.refresh_from_db()
        assert own_rule.protected_file_id == own_file.pk


def make_task(requester, assignee=None, amount='10.00'):
    from workflow.models import ApprovalQueue, ApprovalTask

    queue = ApprovalQueue.objects.create(
        name='Security queue', module='quality', profile_role='quality', approval_limit='100.00'
    )
    return ApprovalTask.objects.create(
        queue=queue,
        title='Security task',
        source_module='quality',
        source_model='SecurityTest',
        source_record_id='1',
        requested_by=requester,
        assigned_to=assignee,
        amount=amount,
    )


@pytest.mark.parametrize('scenario', ['wrong_role', 'over_limit', 'requester', 'inactive'])
def test_assigned_approver_must_meet_queue_and_segregation(scenario):
    from django.contrib.auth.models import Group

    requester = make_user('task-requester')
    actor = requester if scenario == 'requester' else make_user('task-actor')
    if scenario != 'wrong_role':
        actor.groups.add(Group.objects.get_or_create(name='quality')[0])
    task = make_task(requester, actor)
    if scenario == 'over_limit':
        task.queue.approval_limit = 1
    if scenario == 'inactive':
        actor.is_active = False
    assert not task.can_approve(actor)


def test_task_editor_cannot_change_assignment_or_lower_approval_amount():
    from rest_framework.test import APIClient

    requester = make_user('task-requester')
    editor = make_user('task-editor', 'workflow.change_approvaltask')
    task = make_task(requester)
    client = APIClient()
    client.force_authenticate(editor)
    response = client.patch(
        f'/api/workflow/approval-tasks/{task.pk}/',
        {'assigned_to': editor.pk, 'amount': '0.00'},
        format='json',
    )
    assert response.status_code == 403, response.data
    task.refresh_from_db()
    assert task.assigned_to_id is None
    assert str(task.amount) == '10.00'


@pytest.mark.parametrize(
    ('url', 'reference'),
    [
        ('http://fiscal.example.test', 'FAKE_FISCAL_TOKEN'),
        ('https://attacker.example.test', 'FAKE_FISCAL_TOKEN'),
        ('https://127.0.0.1', 'FAKE_FISCAL_TOKEN'),
        ('https://fiscal.example.test', 'FAKE_UNRELATED_SECRET'),
        ('https://user:pass@fiscal.example.test', 'FAKE_FISCAL_TOKEN'),
        ('https://fiscal.example.test?next=https://attacker.example.test', 'FAKE_FISCAL_TOKEN'),
    ],
)
def test_fiscal_client_blocks_untrusted_destination_and_secret(
    settings, monkeypatch, url, reference
):
    from django.core.exceptions import ValidationError
    from fiscal.services import FiscalProviderClient

    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {
        'https://fiscal.example.test': ['FAKE_FISCAL_TOKEN']
    }
    monkeypatch.setenv('FAKE_FISCAL_TOKEN', 'synthetic-token')
    monkeypatch.setenv('FAKE_UNRELATED_SECRET', 'synthetic-unrelated')
    # Public DNS and a client guard ensure rejection is due to policy, not DNS failure.
    import socket

    monkeypatch.setattr(
        socket,
        'getaddrinfo',
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))
        ],
    )
    network = Mock(side_effect=AssertionError('Unexpected fiscal network request'))
    monkeypatch.setattr('fiscal.services.httpx.Client', network)
    with pytest.raises(ValidationError):
        FiscalProviderClient().check_status(
            {}, connector=SimpleNamespace(base_url=url, secret_reference=reference)
        )
    network.assert_not_called()


def test_fiscal_connector_model_rejects_untrusted_destinations(settings):
    from django.core.exceptions import ValidationError
    from integrations.models import IntegrationConnector

    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {}
    connector = IntegrationConnector(
        code='FAKE-FISCAL',
        name='Fake fiscal',
        provider_type='fiscal_system',
        base_url='https://attacker.example.test',
    )
    with pytest.raises(ValidationError):
        connector.full_clean()


@pytest.mark.parametrize(
    'address',
    ['127.0.0.1', '10.0.0.1', '169.254.169.254', '::1', '::ffff:192.168.1.1', '224.0.0.1'],
)
def test_fiscal_dns_resolution_cannot_reach_internal_addresses(settings, monkeypatch, address):
    import socket
    from django.core.exceptions import ValidationError
    from fiscal.services import FiscalProviderClient

    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {'https://fiscal.example.test': []}
    monkeypatch.setattr(
        socket,
        'getaddrinfo',
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 443))],
    )
    network = Mock(side_effect=AssertionError('Unexpected fiscal network request'))
    monkeypatch.setattr('fiscal.services.httpx.Client', network)
    with pytest.raises(ValidationError):
        FiscalProviderClient().check_status(
            {},
            connector=SimpleNamespace(base_url='https://fiscal.example.test', secret_reference=''),
        )
    network.assert_not_called()


@pytest.mark.parametrize(
    'resource_slug', ['protected-files', 'access-rules', 'secure-links', 'audit-trail']
)
def test_file_ui_resources_scope_by_api_object_permission(resource_slug):
    from base.ui.registry import get_resource
    from files.models import ProtectedFileAccessRule, ProtectedFileAuditTrail, SecureFileLink

    owner = make_user('ui-file-owner')
    stranger = make_user('ui-file-stranger')
    private = make_file(owner)
    own = make_file(stranger, 'Own file')
    for protected_file in (private, own):
        ProtectedFileAccessRule.objects.create(
            protected_file=protected_file, rule_type='user', user=owner, permission='view'
        )
        ProtectedFileAuditTrail.objects.create(
            protected_file=protected_file, action='view', actor=owner
        )
        protected_file.generate_secure_link(
            user=protected_file.responsible, purpose=SecureFileLink.Purpose.VIEW
        )
    resource = get_resource('files', resource_slug)
    queryset = resource.get_queryset(SimpleNamespace(user=stranger))
    if resource_slug == 'protected-files':
        assert list(queryset.values_list('pk', flat=True)) == [own.pk]
    else:
        assert set(queryset.values_list('protected_file_id', flat=True)) == {own.pk}


@pytest.mark.parametrize('resource_slug', ['sessions', 'messages'])
def test_chat_ui_scopes_by_session_owner_even_for_superuser(resource_slug):
    from base.ui.registry import get_resource
    from knowledge.models import RAGChatSession

    owner = make_user('chat-owner')
    stranger = make_user('chat-stranger')
    stranger.is_superuser = True
    private = RAGChatSession.objects.create(created_by=owner, title='Secret conversation')
    private.add_user_message('Secret contents')
    own = RAGChatSession.objects.create(created_by=stranger, title='Own conversation')
    message = own.add_user_message('Own contents')
    queryset = get_resource('knowledge', resource_slug).get_queryset(SimpleNamespace(user=stranger))
    assert list(queryset.values_list('pk', flat=True)) == [
        own.pk if resource_slug == 'sessions' else message.pk
    ]


def test_acl_ui_choices_exclude_files_without_manage():
    from base.ui.registry import get_resource
    from base.ui.views import ResourceCreateView
    from files.models import ProtectedFileAccessRule

    owner = make_user('ui-owner')
    reader = make_user('ui-reader')
    private = make_file(owner)
    own = make_file(reader, 'Own file')
    ProtectedFileAccessRule.objects.create(
        protected_file=private, rule_type='user', user=reader, permission='view'
    )
    view = ResourceCreateView()
    view.resource = get_resource('files', 'access-rules')
    form = view.get_form_class()(request=SimpleNamespace(user=reader))
    assert set(form.fields['protected_file'].queryset.values_list('pk', flat=True)) == {own.pk}


def test_ui_task_editor_cannot_reassign_or_write_decision_state():
    from base.ui.registry import get_resource
    from base.ui.views import ResourceUpdateView

    requester = make_user('ui-requester')
    editor = make_user('ui-editor', 'workflow.change_approvaltask')
    task = make_task(requester)
    view = ResourceUpdateView()
    view.resource = get_resource('workflow', 'tasks')
    form = view.get_form_class()(instance=task, request=SimpleNamespace(user=editor))
    assert 'status' not in form.fields
    assert 'decision_comments' not in form.fields
    form.cleaned_data = {'assigned_to': editor, 'amount': task.amount}
    from django.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        form.clean()


def test_file_reader_cannot_promote_self_to_owner():
    from files.models import ProtectedFileAccessRule
    from rest_framework.test import APIClient

    owner = make_user('file-owner')
    reader = make_user('file-reader', 'files.change_protectedfile')
    private = make_file(owner)
    ProtectedFileAccessRule.objects.create(
        protected_file=private, rule_type='user', user=reader, permission='view'
    )
    client = APIClient()
    client.force_authenticate(reader)
    response = client.patch(
        f'/api/files/protected-files/{private.pk}/', {'responsible': reader.pk}, format='json'
    )
    assert response.status_code == 403, response.data
    private.refresh_from_db()
    assert private.responsible_id == owner.pk


def test_delegation_cannot_be_forged_on_behalf_of_another_approver():
    from datetime import timedelta
    from django.utils import timezone
    from rest_framework.test import APIClient

    actor = make_user('delegation-attacker', 'workflow.add_workflowdelegation')
    approver = make_user('delegation-approver')
    client = APIClient()
    client.force_authenticate(actor)
    response = client.post(
        '/api/workflow/delegations/',
        {
            'from_user': approver.pk,
            'to_user': actor.pk,
            'reason': 'Fake delegation',
            'starts_at': timezone.now().isoformat(),
            'ends_at': (timezone.now() + timedelta(days=1)).isoformat(),
        },
        format='json',
    )
    assert response.status_code == 403, response.data


@pytest.mark.parametrize(
    ('module', 'slug'),
    [('inventory', 'movements'), ('finance', 'cash-flow')],
)
def test_accounted_ledgers_do_not_expose_generic_ui_mutations(module, slug):
    from base.ui.registry import get_resource

    resource = get_resource(module, slug)
    admin = make_user('ledger-admin')
    admin.is_superuser = True
    assert resource.read_only
    assert not resource.can_add(admin)
    assert not resource.can_change(admin)
    assert not resource.can_delete(admin)


def test_nonstaff_connector_editor_cannot_change_fiscal_configuration(settings):
    from integrations.models import IntegrationConnector
    from integrations.serializers import IntegrationConnectorSerializer
    from rest_framework.exceptions import PermissionDenied

    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {
        'https://fiscal.example.test': ['FAKE_FISCAL_TOKEN']
    }
    connector = IntegrationConnector.objects.create(
        code='FAKE-FISCAL',
        name='Fake fiscal',
        provider_type='fiscal_system',
        base_url='https://fiscal.example.test',
    )
    editor = make_user('connector-editor', 'integrations.change_integrationconnector')
    serializer = IntegrationConnectorSerializer(
        instance=connector,
        data={'secret_reference': 'FAKE_FISCAL_TOKEN'},
        partial=True,
        context={'request': SimpleNamespace(user=editor)},
    )
    with pytest.raises(PermissionDenied):
        serializer.is_valid(raise_exception=True)


@pytest.mark.parametrize('status_code', [200, 302])
def test_fiscal_http_pins_public_ip_keeps_tls_hostname_and_never_redirects(
    settings, monkeypatch, status_code
):
    import socket
    import httpx
    from fiscal.services import FiscalProviderClient
    import fiscal.services as services

    settings.FISCAL_PROVIDER_ALLOWED_DESTINATIONS = {
        'https://fiscal.example.test': ['FAKE_FISCAL_TOKEN']
    }
    monkeypatch.setenv('FAKE_FISCAL_TOKEN', 'synthetic-token')
    dns = Mock(side_effect=[[(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]])
    monkeypatch.setattr(socket, 'getaddrinfo', dns)
    requests = []
    tls_names = []
    body = b'{"status":"processing"}'
    response_bytes = (
        f'HTTP/1.1 {status_code} Test\r\nContent-Length: {len(body)}\r\nLocation: https://attacker.example.test/\r\n\r\n'.encode()
        + body
    )

    class SyntheticStream:
        def read(self, max_bytes, timeout=None):
            result = self.response
            self.response = b''
            return result

        def write(self, buffer, timeout=None):
            requests.append(bytes(buffer))

        def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            tls_names.append(server_hostname)
            return self

        def get_extra_info(self, info):
            return None

        def close(self):
            pass

    stream = SyntheticStream()
    stream.response = response_bytes
    backend = Mock()
    backend.connect_tcp.return_value = stream
    original_transport = httpx.HTTPTransport

    def transport_factory(**kwargs):
        transport = original_transport(**kwargs)
        transport._pool._network_backend = backend
        return transport

    monkeypatch.setattr(services.httpx, 'HTTPTransport', transport_factory)
    connector = SimpleNamespace(
        base_url='https://fiscal.example.test', secret_reference='FAKE_FISCAL_TOKEN'
    )
    if status_code == 302:
        with pytest.raises(httpx.HTTPStatusError):
            FiscalProviderClient().check_status({'number': 'FAKE'}, connector=connector)
    else:
        result = FiscalProviderClient().check_status({'number': 'FAKE'}, connector=connector)
        assert result.status == 'processing'
    dns.assert_called_once()
    assert backend.connect_tcp.call_count == 1
    assert backend.connect_tcp.call_args.args == ('93.184.216.34', 443)
    assert tls_names == ['fiscal.example.test']
    sent = b''.join(requests)
    assert b'Host: fiscal.example.test' in sent
    assert b'Authorization: Bearer synthetic-token' in sent
    assert b'attacker.example.test' not in sent


def test_legitimate_acl_manager_and_eligible_approvers_continue_to_work():
    from django.contrib.auth.models import Group
    from files.models import ProtectedFileAccessRule
    from workflow.models import WorkflowDelegation
    from datetime import timedelta
    from django.utils import timezone
    from rest_framework.test import APIClient

    requester = make_user('legit-requester')
    approver = make_user('legit-approver', 'files.add_protectedfileaccessrule')
    substitute = make_user('legit-substitute')
    approver.groups.add(Group.objects.get_or_create(name='quality')[0])
    task = make_task(requester, approver)
    assert task.can_approve(approver)
    WorkflowDelegation.objects.create(
        from_user=approver,
        to_user=substitute,
        starts_at=timezone.now() - timedelta(hours=1),
        ends_at=timezone.now() + timedelta(days=1),
        reason='Synthetic legitimate leave',
    )
    assert task.can_approve(substitute)
    protected_file = make_file(requester)
    ProtectedFileAccessRule.objects.create(
        protected_file=protected_file, rule_type='user', user=approver, permission='manage'
    )
    client = APIClient()
    client.force_authenticate(approver)
    response = client.post(
        '/api/files/access-rules/',
        {
            'protected_file': protected_file.pk,
            'rule_type': 'user',
            'user': substitute.pk,
            'permission': 'view',
        },
        format='json',
    )
    assert response.status_code == 201, response.data
    assert protected_file.user_can_access(substitute)


def test_global_search_and_html_detail_do_not_expose_foreign_files():
    from django.test import Client
    from django.urls import reverse
    from base.ui.search import search_visible_resources
    from files.models import ProtectedFileAccessRule

    owner = make_user('search-owner')
    reader = make_user(
        'search-reader', 'files.view_protectedfile', 'files.view_protectedfileaccessrule'
    )
    private = make_file(owner, 'Synthetic secret needle')
    ProtectedFileAccessRule.objects.create(
        protected_file=private, rule_type='user', user=owner, permission='view'
    )
    assert search_visible_resources(SimpleNamespace(user=reader), 'needle') == ()
    client = Client()
    client.force_login(reader)
    response = client.get(
        reverse('app:resource_detail', args=('files', 'protected-files', private.pk))
    )
    assert response.status_code == 404


@pytest.mark.parametrize('model_name', ['file', 'acl', 'trail', 'link', 'session', 'message'])
def test_django_admin_preserves_file_acl_and_chat_owner_scope(model_name):
    from django.contrib import admin
    from files.models import (
        ProtectedFile,
        ProtectedFileAccessRule,
        ProtectedFileAuditTrail,
        SecureFileLink,
    )
    from knowledge.models import RAGChatSession, RAGChatMessage

    owner = make_user('admin-owner')
    reader = make_user('admin-reader')
    reader.is_staff = True
    private = make_file(owner)
    rule = ProtectedFileAccessRule.objects.create(
        protected_file=private, rule_type='user', user=reader, permission='view'
    )
    trail = ProtectedFileAuditTrail.objects.create(
        protected_file=private, action='view', actor=owner
    )
    link = private.generate_secure_link(user=owner, purpose='view')
    session = RAGChatSession.objects.create(created_by=owner, title='Private session')
    message = session.add_user_message('Private message')
    model, target = {
        'file': (ProtectedFile, private),
        'acl': (ProtectedFileAccessRule, rule),
        'trail': (ProtectedFileAuditTrail, trail),
        'link': (SecureFileLink, link),
        'session': (RAGChatSession, session),
        'message': (RAGChatMessage, message),
    }[model_name]
    queryset = admin.site._registry[model].get_queryset(SimpleNamespace(user=reader))
    if model_name in {'file', 'trail', 'link'}:
        assert queryset.filter(pk=target.pk).exists()
    else:
        assert not queryset.filter(pk=target.pk).exists()


def test_django_admin_cannot_bypass_task_sensitive_change_authorization():
    from django.contrib import admin
    from django.core.exceptions import PermissionDenied
    from workflow.models import ApprovalTask

    requester = make_user('admin-task-requester')
    editor = make_user('admin-task-editor', 'workflow.change_approvaltask')
    editor.is_staff = True
    task = make_task(requester)
    task.assigned_to = editor
    with pytest.raises(PermissionDenied):
        admin.site._registry[ApprovalTask].save_model(
            SimpleNamespace(user=editor), task, SimpleNamespace(changed_data=['assigned_to']), True
        )
