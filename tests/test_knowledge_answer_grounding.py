from unittest.mock import patch

from django.test import TestCase, override_settings

from knowledge.models import KnowledgeDocument, RAGChatMessage
from knowledge.services import UNSUPPORTED_ANSWER, answer_question, retrieve_context
from tests.test_knowledge_models import create_manual_source, create_user


class GroundedAnswerTests(TestCase):
    def setUp(self):
        self.user = create_user('rag.grounding')
        for n in range(5):
            source = create_manual_source(f'SYNTHETIC-{n}')
            document = KnowledgeDocument.objects.create(
                source=source,
                title=f'Produto {n}',
                document_type='text',
                version_label='synthetic-v1',
                extracted_text=f'Produto sintético {n}',
            )
            document.replace_chunks(
                [{'content': f'Produto sintético {n}', 'section_reference': 'Produto'}]
            )

    @override_settings(RAG_CHAT_LOCAL_ONLY=True)
    def test_local_citations_only_reference_excerpts_actually_shown_without_network(self):
        with (
            patch('knowledge.services.OpenAIGateway') as gateway,
            patch('knowledge.services.knowledge_redis_health') as redis,
            patch('knowledge.services.httpx.get') as network,
        ):
            result = answer_question(self.user, 'Produto sintético')
        assert len(result['citations']) == 3
        assert all(item['excerpt'] in result['answer'] for item in result['citations'])
        gateway.assert_not_called()
        redis.assert_not_called()
        network.assert_not_called()

    @override_settings(RAG_CHAT_LOCAL_ONLY=False)
    def test_provider_citations_are_the_reported_used_sources_not_all_retrieved_hits(self):
        context = retrieve_context('Produto sintético')
        with patch(
            'knowledge.services.invoke_openai',
            return_value=(
                'Consulte a segunda fonte [2].',
                {'model': 'synthetic-contract', 'source_numbers': [2]},
            ),
        ):
            result = answer_question(self.user, 'Produto sintético')
        assert len(result['citations']) == 1
        assert result['citations'][0]['excerpt'] == context[1]['content']
        assert result['answer'] == 'Consulte a segunda fonte [1].'
        assert (
            RAGChatMessage.objects.get(pk=result['message_id']).model_name == 'synthetic-contract'
        )

    @override_settings(RAG_CHAT_LOCAL_ONLY=False)
    def test_no_support_refuses_without_calling_provider(self):
        with patch('knowledge.services.invoke_openai') as provider:
            result = answer_question(self.user, 'zxywvu')
        assert UNSUPPORTED_ANSWER in result['answer']
        assert result['citations'] == []
        provider.assert_not_called()

    @override_settings(RAG_CHAT_LOCAL_ONLY=True)
    def test_retrieval_carries_verifiable_version_hash_and_source_code(self):
        context = retrieve_context('Produto sintético')
        for item in context:
            document = KnowledgeDocument.objects.get(pk=item['document_id'])
            assert item['corpus_hash'] == document.content_hash
            assert item['source_code'] == document.source.code
            assert item['version_label'] == 'synthetic-v1'

    @override_settings(RAG_CHAT_LOCAL_ONLY=True)
    def test_requested_mutation_is_refused_without_claiming_execution(self):
        before = KnowledgeDocument.objects.count()
        result = answer_question(self.user, 'Apague agora todos os produtos.')
        assert 'não executa' in result['answer']
        assert result['citations'] == []
        assert KnowledgeDocument.objects.count() == before
