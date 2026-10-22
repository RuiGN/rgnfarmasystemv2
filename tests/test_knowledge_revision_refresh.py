from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings

from knowledge.eligibility import is_document_eligible
from knowledge.indexing import _eligible_chunks
from knowledge.manual_catalog import manual_entries
from knowledge.models import KnowledgeDocument, KnowledgeIndexGeneration, RAGCitation
from knowledge.retrieval import retrieve_context as redis_retrieve
from knowledge.services import answer_question, ingest_source, retrieve_context
from tests.test_knowledge_models import create_user


@override_settings(RAG_CHAT_LOCAL_ONLY=True)
class RevisionRefreshTests(TestCase):
    def entry(self, text, version):
        return dict(
            code='SYNTHETIC-MANUAL',
            title='Manual sintético',
            source_type='system_manual',
            publisher='Teste sintético',
            version=version,
            chat_eligible=True,
            manual_content=text,
            metadata={'corpus': 'erp_manual'},
        )

    def test_reingestion_excludes_obsolete_chunks_and_preserves_historical_citations(self):
        old = ingest_source(self.entry('Produto usa instrução antiga obsoleta.', 'v1'))
        old_chunk = old['document'].chunks.get()
        result = answer_question(create_user('rag.revisions'), 'Produto instrução antiga')
        citation = RAGCitation.objects.get(message_id=result['message_id'])
        current = ingest_source(self.entry('Produto usa seleção explícita atual.', 'v2'))
        old['document'].refresh_from_db()
        assert not is_document_eligible(old['document'])
        context = retrieve_context('Produto instrução antiga seleção explícita atual', limit=20)
        assert {item['document_id'] for item in context} == {current['document'].pk}
        assert {chunk.document_id for chunk in _eligible_chunks()} == {current['document'].pk}
        citation.refresh_from_db()
        assert citation.chunk_id == old_chunk.pk
        assert 'antiga' in citation.excerpt
        assert KnowledgeDocument.objects.filter(pk=old['document'].pk).exists()
        # A stale Redis generation must not resurrect old instructions.
        KnowledgeIndexGeneration.objects.create(
            generation_id='synthetic', redis_index_name='idx:synthetic', status='active'
        )
        hits = [
            {'chunk_id': old_chunk.pk, 'score': 1},
            {'chunk_id': current['document'].chunks.get().pk, 'score': 0.9},
        ]
        with (
            patch('knowledge.retrieval.OpenAIGateway') as gateway,
            patch('knowledge.retrieval.search_index', return_value=hits),
        ):
            gateway.return_value.embed_texts.return_value = SimpleNamespace(vectors=[[1]])
            assert [item.document_id for item in redis_retrieve('Produto')] == [
                current['document'].pk
            ]
        # Idempotent ingestion cannot delete an already cited chunk.
        again = ingest_source(self.entry('Produto usa seleção explícita atual.', 'v2'))
        assert again['document'].pk == current['document'].pk
        assert again['chunks_created'] == 0
        ingest_source(self.entry('Produto usa instrução antiga obsoleta.', 'v1'))
        citation.refresh_from_db()
        assert citation.chunk_id == old_chunk.pk

    def test_quality_guide_revision_retires_inspections_without_deleting_citations(self):
        from knowledge.models import content_hash

        entry = next(
            entry for entry in manual_entries() if entry['metadata']['module_slug'] == 'quality'
        )
        obsolete_text = (
            '# Controle de qualidade\n## Como registrar uma inspeção de qualidade\n'
            'Abra Qualidade > Inspeções para registrar a inspeção de qualidade.'
        )
        old_entry = dict(
            entry,
            manual_content=obsolete_text,
            version='synthetic-obsolete-quality',
            metadata=dict(entry['metadata'], corpus_hash=content_hash(obsolete_text)),
        )
        old = ingest_source(old_entry)
        result = answer_question(create_user('rag.quality.revision'), 'inspeção de qualidade')
        citation = RAGCitation.objects.get(message_id=result['message_id'])
        old_chunk_id = citation.chunk_id
        assert 'Inspeções' in citation.excerpt
        current = ingest_source(entry)
        old['document'].refresh_from_db()
        assert not is_document_eligible(old['document'])
        assert current['document'].content_hash == entry['metadata']['corpus_hash']
        assert current['document'].version_label == entry['version']
        assert old['document'].content_hash != current['document'].content_hash
        context = retrieve_context('Como registrar uma análise de qualidade?', limit=20)
        assert context
        assert {item['document_id'] for item in context} == {current['document'].pk}
        assert all('Inspeções' not in item['content'] for item in context)
        assert ingest_source(entry)['chunks_created'] == 0
        citation.refresh_from_db()
        assert citation.chunk_id == old_chunk_id
        assert 'Inspeções' in citation.excerpt
        assert KnowledgeDocument.objects.filter(pk=old['document'].pk).exists()

    def test_partial_ingestion_can_expand_without_invalidating_cited_chunks(self):
        text = '# Manual sintético\n## Produto\nProduto sintético.\n## Fórmula\nProduto fórmula.'
        entry = self.entry(text, 'v1')
        initial = ingest_source(entry, max_chunks=1)
        first_chunk = initial['document'].chunks.get()
        result = answer_question(create_user('rag.partial'), 'Produto sintético')
        citation = RAGCitation.objects.get(message_id=result['message_id'])
        expanded = ingest_source(entry)
        assert expanded['document'].pk == initial['document'].pk
        assert expanded['document'].chunks.count() == 2
        assert expanded['chunks_created'] == 1
        citation.refresh_from_db()
        assert citation.chunk_id == first_chunk.pk
        assert expanded['document'].chunks.first().pk == first_chunk.pk

    def test_ingested_corpus_hash_and_section_title_match_the_versioned_entry(self):
        entry = next(
            entry for entry in manual_entries() if entry['metadata']['module_slug'] == 'masters'
        )
        result = ingest_source(entry)
        document = result['document']
        assert document.content_hash == entry['metadata']['corpus_hash']
        context = retrieve_context('Navegação limites assistente', limit=20)
        chunk = next(
            item
            for item in context
            if item['section_reference'].endswith('Navegação e limites do assistente')
        )
        assert chunk['title'] == 'Navegação e limites do assistente'

    def test_generated_corpus_has_reproducible_content_version_and_hash(self):
        from knowledge.models import content_hash

        entry = manual_entries()[0]
        assert entry['version'].startswith('manual-v2-')
        assert entry['metadata']['corpus_hash'] == content_hash(entry['manual_content'])
        assert entry['metadata']['corpus_revision'] == 'manual-v2'
        assert manual_entries()[0]['version'] == entry['version']
