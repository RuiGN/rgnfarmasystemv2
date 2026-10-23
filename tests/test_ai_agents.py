import pytest
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient


User = get_user_model()


def grant_model_perms(user, *models):
    for model in models:
        content_type = ContentType.objects.get_for_model(model)
        permissions = Permission.objects.filter(
            content_type=content_type,
            codename__in=[
                f'view_{model._meta.model_name}',
                f'add_{model._meta.model_name}',
                f'change_{model._meta.model_name}',
                f'delete_{model._meta.model_name}',
            ],
        )
        user.user_permissions.add(*permissions)
    if hasattr(user, '_perm_cache'):
        del user._perm_cache
    if hasattr(user, '_user_perm_cache'):
        del user._user_perm_cache


def create_user(email):
    return User.objects.create_user(username=email, email=email, password='S3curePass!123')


def create_document(owner, code='POP-IA-001'):
    from documents.models import ControlledDocument

    return ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.SOP,
        code=code,
        title='Procedimento de investigação de desvios',
        area='Garantia da Qualidade',
        effective_from=timezone.localdate(),
        owner=owner,
        content='Investigar causa raiz, impactos em lote, ações corretivas e riscos residuais.',
        change_summary='Emissão inicial para teste de agente.',
    )


def create_agent(owner, code='AI-DOC-SUMMARY'):
    from ai_agents.models import AIAgentProfile

    return AIAgentProfile.objects.create(
        code=code,
        name='Agente de resumo documental',
        agent_type=AIAgentProfile.AgentType.SUMMARY,
        source_module=AIAgentProfile.SourceModule.DOCUMENTS,
        provider=AIAgentProfile.Provider.OPENAI,
        model_name='gpt-5.5-mini',
        system_prompt='Resuma registros regulados e proponha pontos de revisão humana.',
        allowed_source_modules=[
            AIAgentProfile.SourceModule.DOCUMENTS,
            AIAgentProfile.SourceModule.DEVIATIONS,
            AIAgentProfile.SourceModule.CAPA,
            AIAgentProfile.SourceModule.AUDITS,
            AIAgentProfile.SourceModule.COMPLAINTS,
            AIAgentProfile.SourceModule.RISKS,
        ],
        configuration={'force_local': True},
        created_by=owner,
    )


def test_supported_providers_are_limited_to_active_integrations():
    from ai_agents.models import AIAgentProfile

    assert set(AIAgentProfile.Provider.values) == {'openai', 'local'}


@override_settings(OPENAI_MODEL='deployment-configured-model')
def test_default_agent_model_uses_the_configured_openai_model():
    from ai_agents.models import AIAgentProfile

    default = AIAgentProfile._meta.get_field('model_name').default

    assert callable(default)
    assert default() == 'deployment-configured-model'


@override_settings(OPENAI_MODEL='')
def test_default_agent_model_falls_back_when_openai_model_is_blank():
    from ai_agents.models import AIAgentProfile

    assert AIAgentProfile._meta.get_field('model_name').default() == 'gpt-5.5-mini'


@override_settings(OPENAI_API_KEY='synthetic-key')
def test_external_provider_failure_is_not_converted_to_local_success():
    from ai_agents.services import _invoke_model

    state = {
        'provider': 'openai',
        'configuration': {},
        'model_name': 'synthetic-model',
        'system_prompt': 'synthetic system prompt',
        'prompt_text': 'synthetic prompt',
    }
    with pytest.raises(RuntimeError, match='provider unavailable'):
        with patch(
            'ai_agents.services._invoke_external_model',
            side_effect=RuntimeError('provider unavailable'),
        ):
            _invoke_model(state)


class AIAgentModelTests(TestCase):
    def test_rf29_agent_run_uses_langgraph_audits_prompt_and_requires_review(self):
        from ai_agents.models import AIAgentRun, AIPromptAuditLog, AIInsightSuggestion

        owner = create_user('ai.owner@example.com')
        other_user = create_user('ai.other@example.com')
        document = create_document(owner)
        agent = create_agent(owner)

        run = agent.create_run(
            source_module=agent.SourceModule.DOCUMENTS,
            source_model='ControlledDocument',
            source_record_id=str(document.id),
            input_payload={
                'title': document.title,
                'content': document.content,
            },
            requested_by=owner,
        )
        run.execute(user=owner)
        run.refresh_from_db()

        invalid_run = AIAgentRun(
            agent=agent,
            source_module=agent.SourceModule.RISKS,
            source_model='RiskRecord',
            source_record_id='1',
            input_payload={'description': 'Risco fora do módulo permitido'},
            requested_by=owner,
        )
        invalid_reviewer_suggestion = AIInsightSuggestion.objects.filter(run=run).first()

        with pytest.raises(ValidationError) as invalid_run_error:
            invalid_run.full_clean()
        invalid_reviewer_suggestion.approve(
            user=other_user, comments='Sugestão revisada em escopo global.'
        )
        invalid_reviewer_suggestion.refresh_from_db()
        audit = AIPromptAuditLog.objects.get(run=run)

        assert run.status == AIAgentRun.Status.SUCCEEDED
        assert run.graph_engine == 'langgraph'
        assert run.output_text
        assert run.output_payload['summary']
        assert (
            AIInsightSuggestion.objects.filter(
                run=run,
                status=AIInsightSuggestion.Status.PENDING_REVIEW,
            ).count()
            >= 4
        )
        assert invalid_reviewer_suggestion.status == AIInsightSuggestion.Status.APPROVED
        assert invalid_reviewer_suggestion.reviewed_by == other_user
        assert 'prompt_text' in invalid_run_error.value.message_dict
        assert audit.user == owner
        assert audit.model_name == 'gpt-5.5-mini'
        assert audit.status == AIAgentRun.Status.SUCCEEDED
        assert 'Procedimento de investigação' in audit.prompt_text
        assert audit.output_payload['summary']

    def test_rf29_celery_task_executes_queued_agent_run(self):
        from ai_agents.models import AIAgentRun, AIPromptAuditLog
        from ai_agents.tasks import process_ai_agent_run

        owner = create_user('ai.task@example.com')
        document = create_document(owner, code='POP-IA-002')
        agent = create_agent(owner, code='AI-CELERY')
        run = agent.create_run(
            source_module=agent.SourceModule.DOCUMENTS,
            source_model='ControlledDocument',
            source_record_id=str(document.id),
            input_payload={'content': document.content},
            requested_by=owner,
        )

        run.enqueue(dispatch=False)
        run.refresh_from_db()
        task_result = process_ai_agent_run(run.id)
        run.refresh_from_db()

        assert run.status == AIAgentRun.Status.SUCCEEDED
        assert run.celery_task_name == 'ai_agents.tasks.process_ai_agent_run'
        assert run.started_at is not None
        assert run.completed_at is not None
        assert task_result == run.id
        assert AIPromptAuditLog.objects.filter(run=run, status=AIAgentRun.Status.SUCCEEDED).exists()


@pytest.mark.legacy_api_permissions
class AIAgentApiTests(TestCase):
    def test_rf29_api_runs_agent_and_reviews_suggestions_with_global_permissions(self):
        from ai_agents.models import (
            AIAgentProfile,
            AIAgentRun,
            AIInsightSuggestion,
            AIPromptAuditLog,
        )

        user = create_user('ai.api@example.com')
        other_user = create_user('ai.other.api@example.com')
        grant_model_perms(user, AIAgentProfile, AIAgentRun, AIInsightSuggestion, AIPromptAuditLog)
        document = create_document(user, code='POP-IA-003')
        create_agent(other_user, code='AI-OTHER')

        client = APIClient()
        client.force_authenticate(user)

        profile_response = client.post(
            '/api/ai-agents/profiles/',
            {
                'code': 'AI-API-DOC',
                'name': 'Agente API de documentos',
                'agent_type': AIAgentProfile.AgentType.SUMMARY,
                'source_module': AIAgentProfile.SourceModule.DOCUMENTS,
                'provider': AIAgentProfile.Provider.OPENAI,
                'model_name': 'gpt-5.5-mini',
                'system_prompt': 'Resuma e gere sugestões revisáveis.',
                'allowed_source_modules': [AIAgentProfile.SourceModule.DOCUMENTS],
                'configuration': {'force_local': True},
            },
            format='json',
        )
        profile_id = profile_response.json()['id']
        run_response = client.post(
            f'/api/ai-agents/profiles/{profile_id}/run/',
            {
                'source_module': AIAgentProfile.SourceModule.DOCUMENTS,
                'source_model': 'ControlledDocument',
                'source_record_id': str(document.id),
                'input_payload': {
                    'title': document.title,
                    'content': document.content,
                },
                'run_immediately': True,
            },
            format='json',
        )
        invalid_payload_response = client.post(
            f'/api/ai-agents/profiles/{profile_id}/run/',
            {
                'source_module': AIAgentProfile.SourceModule.DOCUMENTS,
                'source_model': 'ControlledDocument',
                'source_record_id': str(document.id),
                'input_payload': {'content': 'Conteúdo sem título para validação local.'},
                'run_immediately': True,
            },
            format='json',
        )
        profiles_list = client.get('/api/ai-agents/profiles/')
        runs_list = client.get('/api/ai-agents/runs/')
        suggestions_list = client.get('/api/ai-agents/suggestions/')
        audit_logs_list = client.get('/api/ai-agents/audit-logs/')
        suggestion = AIInsightSuggestion.objects.filter(run_id=run_response.json()['id']).first()
        approve_response = client.post(
            f'/api/ai-agents/suggestions/{suggestion.id}/approve/',
            {'comments': 'Revisado e aprovado.'},
            format='json',
        )
        queued_run_response = client.post(
            f'/api/ai-agents/profiles/{profile_id}/run/',
            {
                'source_module': AIAgentProfile.SourceModule.DOCUMENTS,
                'source_model': 'ControlledDocument',
                'source_record_id': str(document.id),
                'input_payload': {
                    'title': document.title,
                    'content': document.content,
                },
                'run_immediately': False,
                'dispatch': False,
            },
            format='json',
        )

        assert profile_response.status_code == 201
        assert profile_response.json()['created_by'] == user.id
        assert run_response.status_code == 201
        assert run_response.json()['status'] == AIAgentRun.Status.SUCCEEDED
        assert run_response.json()['graph_engine'] == 'langgraph'
        assert invalid_payload_response.status_code == 201
        assert 'AI-OTHER' in {item['code'] for item in profiles_list.json()['results']}
        assert runs_list.status_code == 200
        assert suggestions_list.status_code == 200
        assert audit_logs_list.status_code == 200
        assert approve_response.status_code == 200
        assert approve_response.json()['status'] == AIInsightSuggestion.Status.APPROVED
        assert queued_run_response.status_code == 201
        assert queued_run_response.json()['status'] == AIAgentRun.Status.QUEUED
        assert (
            queued_run_response.json()['celery_task_name'] == 'ai_agents.tasks.process_ai_agent_run'
        )


class AIWorkflowGateTests(TestCase):
    def test_run_workflow_gate_agent_returns_none_if_no_agent(self):
        from ai_agents.services import run_workflow_gate_agent

        result = run_workflow_gate_agent(
            source_module='capa',
            source_model='CAPARecord',
            record_id='1',
            input_payload={'test': 'data'},
        )
        assert result is None

    def test_run_workflow_gate_agent_returns_correct_result(self):
        from ai_agents.services import run_workflow_gate_agent
        from ai_agents.models import AIAgentProfile

        owner = create_user('wf.owner@example.com')
        AIAgentProfile.objects.create(
            code='WF-AGENT-001',
            name='Workflow Agent',
            agent_type=AIAgentProfile.AgentType.WORKFLOW_GATE,
            source_module=AIAgentProfile.SourceModule.CAPA,
            provider=AIAgentProfile.Provider.LOCAL,
            model_name='local',
            system_prompt='Test prompt',
            allowed_source_modules=[AIAgentProfile.SourceModule.CAPA],
            configuration={'force_local': True, 'approval_threshold': 0.80},
            created_by=owner,
        )

        result = run_workflow_gate_agent(
            source_module=AIAgentProfile.SourceModule.CAPA,
            source_model='CAPARecord',
            record_id='10',
            input_payload={'title': 'CAPA Test', 'content': 'Test desc'},
        )
        assert result is not None
        assert 'approved' in result
        assert 'confidence' in result
        assert 'suggestions' in result
        assert 'summary' in result

    def test_async_workflow_gate_check(self):
        from ai_agents.tasks import async_workflow_gate_check
        from ai_agents.models import AIAgentProfile

        owner = create_user('wf.async@example.com')
        AIAgentProfile.objects.create(
            code='WF-AGENT-ASYNC',
            name='Workflow Agent Async',
            agent_type=AIAgentProfile.AgentType.WORKFLOW_GATE,
            source_module=AIAgentProfile.SourceModule.DEVIATIONS,
            provider=AIAgentProfile.Provider.LOCAL,
            model_name='local',
            system_prompt='Test prompt',
            allowed_source_modules=[AIAgentProfile.SourceModule.DEVIATIONS],
            configuration={'force_local': True},
            created_by=owner,
        )

        result = async_workflow_gate_check(
            source_module=AIAgentProfile.SourceModule.DEVIATIONS,
            source_model='DeviationRecord',
            record_id='20',
            input_payload={'title': 'Dev Test', 'content': 'Test desc'},
        )
        assert result is not None
        assert 'approved' in result

    def test_seed_workflow_agents_command(self):
        from django.core.management import call_command
        from ai_agents.models import AIAgentProfile

        call_command('seed_workflow_agents')

        capa_agent = AIAgentProfile.objects.get(code='WG-CAPA-001')
        assert capa_agent.agent_type == AIAgentProfile.AgentType.WORKFLOW_GATE
        assert capa_agent.source_module == AIAgentProfile.SourceModule.CAPA

        dev_agent = AIAgentProfile.objects.get(code='WG-DEV-001')
        assert dev_agent.source_module == AIAgentProfile.SourceModule.DEVIATIONS

        qa_agent = AIAgentProfile.objects.get(code='WG-QA-001')
        assert qa_agent.source_module == AIAgentProfile.SourceModule.QA
