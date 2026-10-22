from django.test import SimpleTestCase

from knowledge.services import chunk_text


class SectionChunkTests(SimpleTestCase):
    def test_each_chunk_keeps_its_markdown_title_and_section_path(self):
        text = '# Manual sintético\n## Produto\n' + ('produto unidade ' * 14)
        text += '\n## Fórmula\n### Componentes\n' + ('material perda ' * 14)
        chunks = chunk_text(text, max_words=10, overlap=2)
        assert len(chunks) > 4
        for chunk in chunks:
            assert chunk['title'] in {'Produto', 'Componentes'}
            assert chunk['section_reference'].startswith('Manual sintético > ')
            assert chunk['title'] in chunk['content']
            if chunk['title'] == 'Produto':
                assert 'material' not in chunk['content']
            else:
                assert chunk['section_reference'] == 'Manual sintético > Fórmula > Componentes'
                assert 'unidade' not in chunk['content']
        assert chunk_text('  ') == []
        assert chunk_text('texto sem título')[0]['section_reference'] == 'chunk 1'
