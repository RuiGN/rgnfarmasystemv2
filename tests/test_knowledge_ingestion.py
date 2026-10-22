from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

import httpx
from django.test import SimpleTestCase, override_settings


class KnowledgeIngestionTests(SimpleTestCase):
    def test_fetch_source_text_tries_alternate_urls(self):
        from knowledge.services import fetch_source_text_candidates

        failed = Mock()
        failed.raise_for_status.side_effect = httpx.HTTPStatusError(
            'blocked',
            request=Mock(),
            response=Mock(status_code=403),
        )
        successful = Mock(
            headers={'content-type': 'text/html'},
            text='<main>Conteúdo oficial da legislação.</main>',
        )
        successful.raise_for_status.return_value = None

        with patch('knowledge.services.httpx.get', side_effect=[failed, successful]) as get:
            fetched, selected_url = fetch_source_text_candidates(
                ['https://primary.invalid', 'https://alternate.example/source']
            )

        assert get.call_count == 2
        assert selected_url == 'https://alternate.example/source'
        assert 'Conteúdo oficial' in fetched['text']

    def test_local_help_source_reads_only_the_declared_project_file(self):
        from knowledge.services import fetch_local_source_text

        with TemporaryDirectory(prefix='rag-local-source-') as directory:
            root = Path(directory)
            help_file = root / 'docs' / 'help.md'
            help_file.parent.mkdir(parents=True, exist_ok=True)
            help_file.write_text(
                '# Impressão local\nConfigure a Argox no painel.', encoding='utf-8'
            )
            with override_settings(BASE_DIR=root):
                fetched = fetch_local_source_text('docs/help.md')

        assert fetched['document_type'] == 'text'
        assert 'Configure a Argox' in fetched['text']

    def test_catalog_contains_internal_erp_help_sources(self):
        from knowledge.source_catalog import SEED_SOURCES

        internal_sources = [
            source for source in SEED_SOURCES if source['code'].startswith('RGN-ERP-HELP-')
        ]

        assert internal_sources
        assert all(source.get('metadata', {}).get('local_path') for source in internal_sources)
