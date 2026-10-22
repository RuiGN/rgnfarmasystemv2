import io
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APIClient

from knowledge.services import answer_question
from tests.test_knowledge_api import grant_chat_permission
from tests.test_knowledge_models import create_user


class IndexErrorPrivacyTests(SimpleTestCase):
    def test_rebuild_health_exception_is_reported_without_sensitive_details(self):
        with patch(
            'knowledge.management.commands.rebuild_knowledge_index.knowledge_redis_health',
            side_effect=RuntimeError('redis://secret.invalid/?token=never-disclose'),
        ):
            with self.assertRaises(CommandError) as raised:
                call_command('rebuild_knowledge_index', stdout=io.StringIO())
        assert 'indisponível' in str(raised.exception)
        assert 'never-disclose' not in str(raised.exception)
        assert 'secret.invalid' not in str(raised.exception)

    @override_settings(KNOWLEDGE_REDIS_URL='redis://synthetic:never-disclose@example.invalid/0')
    def test_rebuild_unavailability_never_includes_connection_url(self):
        with patch(
            'knowledge.management.commands.rebuild_knowledge_index.knowledge_redis_health',
            return_value={'available': False},
        ):
            with self.assertRaises(CommandError) as raised:
                call_command('rebuild_knowledge_index', stdout=io.StringIO())
        message = str(raised.exception)
        assert 'indisponível' in message
        assert 'never-disclose' not in message
        assert 'example.invalid' not in message


@override_settings(RAG_CHAT_LOCAL_ONLY=True)
class ChatSessionCsrfTests(TestCase):
    def test_session_authenticated_post_still_requires_csrf(self):
        user = create_user('rag.csrf')
        grant_chat_permission(user)
        client = APIClient(enforce_csrf_checks=True)
        client.force_login(user)
        payload = {'question': 'Pergunta sintética sem suporte'}
        denied = client.post('/api/knowledge/chat/', payload, format='json')
        assert denied.status_code == 403
        token = 'a' * 32
        client.cookies['csrftoken'] = token
        allowed = client.post(
            '/api/knowledge/chat/', payload, format='json', HTTP_X_CSRFTOKEN=token
        )
        assert allowed.status_code == 200
        assert allowed.json()['citations'] == []

    @override_settings(RAG_CHAT_LOCAL_ONLY=False)
    def test_provider_error_does_not_disclose_url_or_token_and_does_not_change_mode(self):
        from django.conf import settings
        from knowledge.services import ingest_source

        ingest_source(
            dict(
                code='SYNTHETIC-ERROR',
                title='Manual sintético',
                source_type='system_manual',
                publisher='Teste',
                chat_eligible=True,
                manual_content='Produto sintético para cadastro.',
            )
        )
        with patch(
            'knowledge.services.invoke_openai',
            side_effect=RuntimeError('https://provider.invalid/?token=never-disclose'),
        ):
            result = answer_question(create_user('rag.errors'), 'Produto sintético')
        assert 'never-disclose' not in str(result)
        assert 'provider.invalid' not in str(result)
        assert 'modo local' in result['answer']
        assert settings.RAG_CHAT_LOCAL_ONLY is False
