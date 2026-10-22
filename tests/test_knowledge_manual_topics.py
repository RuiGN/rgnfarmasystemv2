from django.test import SimpleTestCase

from knowledge.services import chunk_text
from knowledge.step_by_step_manual import get_step_by_step


class FocusedManualTopicsTests(SimpleTestCase):
    def test_identifier_topic_is_self_contained_in_a_dedicated_chunk(self):
        chunks = chunk_text(get_step_by_step('masters'))
        topic = [
            chunk
            for chunk in chunks
            if chunk['title'] == 'Códigos automáticos e identificadores existentes'
        ]
        assert len(topic) == 1
        for fact in (
            'CODE_PREFIX-ID',
            'ID real',
            'sem preenchimento com zeros',
            'descritivos',
            'oficiais',
            'preservados',
        ):
            assert fact in topic[0]['content']
        assert 'Como cadastrar um produto' not in topic[0]['section_reference']

    def test_chat_limits_have_dedicated_evidence_without_navigation_steps(self):
        chunks = chunk_text(get_step_by_step('masters'))
        topic = [
            chunk
            for chunk in chunks
            if chunk['title'] == 'Limites do chat para alteração e exclusão de registros'
        ]
        assert len(topic) == 1
        for fact in (
            'sessão autenticada',
            'knowledge.view_ragchatsession',
            'não cria, altera, aprova ou apaga registros',
            'exclusão de produtos',
            'não confirma',
            'telas e permissões',
        ):
            assert fact in topic[0]['content']
        assert '/app/workspaces/workflow/' not in topic[0]['content']
