import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings


class RagEvaluationCommandTests(SimpleTestCase):
    def test_result_uses_explicit_verdict_keys_without_password_like_names(self):
        from knowledge.evaluation import evaluate_case, load_cases

        with patch('knowledge.evaluation.retrieve_context', return_value=[]):
            result = evaluate_case(load_cases()['cases'][0], mode='retrieval')
        assert 'retrieval_ok' in result
        assert result['generation_ok'] is None
        assert 'retrieval_pass' not in result
        assert 'generation_pass' not in result

    @override_settings(RAG_CHAT_LOCAL_ONLY=True)
    def test_real_generation_evaluation_refuses_local_configuration(self):
        with self.assertRaisesMessage(CommandError, 'modo local'):
            call_command('evaluate_manual_rag', mode='generation', stdout=io.StringIO())

    def test_versioned_cases_have_sources_required_and_forbidden_facts(self):
        from knowledge.evaluation import load_cases

        suite = load_cases()
        assert suite['version'] == 'pt-br-manual-v2'
        cases = suite['cases']
        assert len({case['id'] for case in cases}) == len(cases)
        for topic in (
            'produto',
            'versao',
            'componentes',
            'fk',
            'codes',
            'navegacao',
            'permissao',
            'fora-manual',
            'mutacao',
        ):
            case = next(case for case in cases if case['id'] == topic)
            assert case['question']
            assert case['required_any']
            assert case['forbidden']
            assert 'expected_sources' in case

    def test_versioned_cases_cover_stock_and_quality_workflows(self):
        from knowledge.evaluation import load_cases

        cases = {case['id']: case for case in load_cases()['cases']}
        for topic, source, section, required, forbidden in (
            (
                'estoque',
                'RGN-ERP-MODULE-INVENTORY',
                'Como consultar o saldo de estoque',
                ['Saldos', 'quantidade reservada', 'quantidade disponível', 'Lotes', 'validade'],
                ['edite diretamente a quantidade', 'Saldos de estoque'],
            ),
            (
                'qualidade',
                'RGN-ERP-MODULE-QUALITY',
                'Como registrar uma análise de qualidade',
                [
                    'Análises de qualidade',
                    'amostra',
                    'especificação',
                    'Adicionar ensaio',
                    'Avaliar',
                ],
                ['Qualidade > Inspeções', 'aprova automaticamente a análise'],
            ),
        ):
            with self.subTest(topic=topic):
                assert topic in cases
                case = cases[topic]
                assert case['expected_sources'] == [source]
                assert case['section'] == section
                assert case['question']
                assert all([fact] in case['required_any'] for fact in required)
                assert set(forbidden) <= set(case['forbidden'])

    def _evaluate_quality_answer(self, suffix, *, legacy_contract=False):
        from knowledge.evaluation import evaluate_case, load_cases
        from knowledge.step_by_step_manual import get_step_by_step

        case = next(case for case in load_cases()['cases'] if case['id'] == 'qualidade')
        if legacy_contract:
            case = dict(case)
            case.pop('forbidden_unless_negated', None)
        section = get_step_by_step('quality').split(f'## {case["section"]}\n', 1)[1]
        section = section.split('\n## ', 1)[0]
        context = [
            dict(
                source_code='RGN-ERP-MODULE-QUALITY',
                section_reference='Como registrar uma análise de qualidade',
                content=section,
            )
        ]
        answer = (
            'Acesse Controle de qualidade > Análises de qualidade, selecione a amostra '
            'e a especificação. Em Resultados Analíticos (LIMS), use Adicionar ensaio '
            'para informar resultado numérico ou resultado textual. Salve; depois use '
            'Avaliar no resultado e as ações Revisar e Aprovar na análise, '
            'respeitando o fluxo e as permissões [1]. '
        ) + suffix
        with (
            patch('knowledge.evaluation.retrieve_context', return_value=context),
            patch(
                'knowledge.evaluation.invoke_openai',
                return_value=(answer, dict(model='synthetic-contract', source_numbers=[1])),
            ),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['error'] is None
        assert result['retrieval_ok'] is True
        assert result['used_source_numbers'] == [1]
        assert result['sources'][0]['source_code'] == case['expected_sources'][0]
        assert result['sources'][0]['section_reference'] == case['section']
        return result

    def test_quality_generation_accepts_supported_negated_approval_warning(self):
        for suffix in (
            '',
            'Registrar ou avaliar um resultado não aprova automaticamente a análise [1].',
            'Registrar ou avaliar um resultado NÃO aprova automaticamente a análise [1].',
            'Não aprova automaticamente a análise; não aprova automaticamente a análise [1].',
        ):
            with self.subTest(suffix=suffix):
                result = self._evaluate_quality_answer(suffix)
                assert result['generation_ok'] is True

    def test_quality_generation_rejects_affirmed_approval_even_with_warning(self):
        warning = 'Registrar ou avaliar um resultado não aprova automaticamente a análise'
        affirmation = 'Registrar ou avaliar um resultado aprova automaticamente a análise'
        for suffix in (
            affirmation + ' [1].',
            warning + ' [1]. ' + affirmation + ' [1].',
            affirmation + ' [1]. ' + warning + ' [1].',
            warning + ', mas salvar aprova automaticamente a análise [1].',
            'Registrar um resultado não apenas aprova automaticamente a análise [1].',
            'Não ignore permissões. ' + affirmation + ' [1].',
            'Senão aprova automaticamente a análise [1].',
            warning + ' [1]. Use Qualidade > Inspeções [1].',
            warning + ' [1]. Salvar classifica automaticamente [1].',
        ):
            with self.subTest(suffix=suffix):
                result = self._evaluate_quality_answer(suffix)
                assert result['generation_ok'] is False

    def test_quality_negation_does_not_waive_legacy_forbidden_contract(self):
        result = self._evaluate_quality_answer(
            'Registrar ou avaliar um resultado não aprova automaticamente a análise [1].',
            legacy_contract=True,
        )
        assert result['generation_ok'] is False

    def test_generation_rejects_used_evidence_from_wrong_section_of_same_source(self):
        from knowledge.evaluation import evaluate_case, load_cases

        case = next(case for case in load_cases()['cases'] if case['id'] == 'produto')
        context = [
            dict(
                source_code='RGN-ERP-MODULE-MASTERS',
                section_reference='Como cadastrar um produto',
                content='O editor tem três abas: Produto, Fórmula mestra e Componentes.',
            ),
            dict(
                source_code='RGN-ERP-MODULE-MASTERS',
                section_reference='Navegação e limites do assistente',
                content='O chat exige sessão autenticada e knowledge.view_ragchatsession.',
            ),
        ]
        with (
            patch('knowledge.evaluation.retrieve_context', return_value=context),
            patch(
                'knowledge.evaluation.invoke_openai',
                return_value=(
                    'Use três abas: Produto, Fórmula mestra e Componentes [2].',
                    dict(model='synthetic-contract', source_numbers=[2]),
                ),
            ),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['error'] is None
        assert result['retrieval_ok'] is True
        assert result['generation_ok'] is False

    def test_generation_requires_facts_in_used_matching_evidence(self):
        from knowledge.evaluation import evaluate_case, load_cases

        case = next(case for case in load_cases()['cases'] if case['id'] == 'produto')
        correct = dict(
            source_code='RGN-ERP-MODULE-MASTERS',
            section_reference='Como cadastrar um produto',
            content='O editor tem três abas: Produto, Fórmula mestra e Componentes.',
        )
        unsupported = dict(correct, content='Selecione o produto e salve o cadastro.')
        other_section = dict(correct, section_reference='Navegação e limites do assistente')
        other_source = dict(correct, source_code='OUTRA-FONTE')
        for context, used in (
            ([correct, unsupported], [2]),
            ([unsupported, other_section], [1, 2]),
            ([unsupported, other_source], [1, 2]),
        ):
            with (
                self.subTest(context=context, used=used),
                patch('knowledge.evaluation.retrieve_context', return_value=context),
                patch(
                    'knowledge.evaluation.invoke_openai',
                    return_value=(
                        'Use três abas: Produto, Fórmula mestra e Componentes '
                        + ''.join(f'[{number}]' for number in used)
                        + '.',
                        dict(model='synthetic-contract', source_numbers=used),
                    ),
                ),
            ):
                result = evaluate_case(case, mode='generation')
                assert result['error'] is None
                assert result['retrieval_ok'] is True
                assert result['generation_ok'] is False

    def test_generation_accepts_facts_composed_only_from_used_matching_evidence(self):
        from knowledge.evaluation import evaluate_case, load_cases

        case = next(case for case in load_cases()['cases'] if case['id'] == 'produto')
        context = [
            dict(
                source_code='RGN-ERP-MODULE-MASTERS',
                section_reference='Como cadastrar um produto',
                content=content,
            )
            for content in ('O editor tem três abas: Produto,', 'Fórmula mestra e Componentes.')
        ]
        with (
            patch('knowledge.evaluation.retrieve_context', return_value=context),
            patch(
                'knowledge.evaluation.invoke_openai',
                return_value=(
                    'Use três abas: Produto, Fórmula mestra e Componentes [1][2].',
                    dict(model='synthetic-contract', source_numbers=[1, 2]),
                ),
            ),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['error'] is None
        assert result['retrieval_ok'] is True
        assert result['generation_ok'] is True

    def test_generation_preserves_unsupported_question_refusal(self):
        from knowledge.evaluation import evaluate_case, load_cases

        case = next(case for case in load_cases()['cases'] if case['id'] == 'fora-manual')
        with (
            patch('knowledge.evaluation.retrieve_context', return_value=[]),
            patch(
                'knowledge.evaluation.invoke_openai',
                return_value=(
                    'Não encontrei uma instrução validada no manual.',
                    dict(model='synthetic-contract', source_numbers=[]),
                ),
            ),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['error'] is None
        assert result['retrieval_ok'] is True
        assert result['generation_ok'] is True
        assert result['used_source_numbers'] == []

    def test_retrieval_only_marks_generation_as_unobserved(self):
        from knowledge.evaluation import evaluate_case

        case = dict(
            id='synthetic',
            question='Sonda',
            expected_sources=[],
            required_any=[['recusa']],
            forbidden=['invenção'],
            section='',
        )
        with patch('knowledge.evaluation.retrieve_context', return_value=[]):
            result = evaluate_case(case, mode='retrieval')
        assert result['retrieval_ok'] is True
        assert result['generation_ok'] is None
        assert result['model'] is None

    def test_evaluation_scores_real_results_and_fails_closed_on_errors(self):
        from knowledge.evaluation import evaluate_case

        case = dict(
            id='synthetic',
            question='Pergunta sintética',
            expected_sources=['SYNTHETIC'],
            required_any=[['três abas']],
            forbidden=['FM-001'],
            section='Produto',
        )
        context = [
            dict(
                chunk_id=1,
                document_id=2,
                source_id=3,
                source_code='SYNTHETIC',
                section_reference='Produto',
                content='três abas',
            )
        ]
        with (
            patch('knowledge.evaluation.retrieve_context', return_value=context),
            patch(
                'knowledge.evaluation.invoke_openai',
                return_value=(
                    'Use três abas [1].',
                    dict(model='synthetic-contract', source_numbers=[1]),
                ),
            ),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['retrieval_ok'] is True
        assert result['generation_ok'] is True
        assert result['model'] == 'synthetic-contract'
        with patch(
            'knowledge.evaluation.retrieve_context',
            side_effect=RuntimeError('https://secret.invalid/?token=synthetic-secret'),
        ):
            result = evaluate_case(case, mode='generation')
        assert result['retrieval_ok'] is False
        assert result['generation_ok'] is False
        assert 'secret' not in json.dumps(result)


@override_settings(RAG_CHAT_LOCAL_ONLY=True)
class RagRetrievalRegressionTests(TestCase):
    def test_versioned_cases_retrieve_current_generated_manual_from_postgres(self):
        from knowledge.evaluation import _normalized, load_cases
        from knowledge.manual_catalog import manual_entries
        from knowledge.models import KnowledgeChunk
        from knowledge.services import ingest_source

        for entry in manual_entries():
            ingest_source(entry)
        output = io.StringIO()
        try:
            call_command('evaluate_manual_rag', mode='retrieval', stdout=output)
        except CommandError:
            print(output.getvalue())
            raise
        report = json.loads(output.getvalue())
        assert report['passed'] is True
        assert report['case_count'] == len(report['results'])
        assert all(row['retrieval_ok'] for row in report['results'])
        assert report['mode'] == 'retrieval'
        assert all(row['model'] is None for row in report['results'])
        assert report['tokens'] is None
        assert report['cost'] is None
        by_id = {row['id']: row for row in report['results']}
        for case in load_cases()['cases']:
            if case['id'] not in {'estoque', 'qualidade'}:
                continue
            matching = [
                item
                for item in by_id[case['id']]['sources']
                if item['source_code'] in case['expected_sources']
                and case['section'] in item['section_reference']
            ]
            assert matching
            chunks = KnowledgeChunk.objects.filter(pk__in=[item['chunk_id'] for item in matching])
            evidence = _normalized('\n'.join(chunk.content for chunk in chunks))
            assert all(
                any(_normalized(term) in evidence for term in alternatives)
                for alternatives in case['required_any']
            ), case['id']
            for item in matching:
                chunk = chunks.get(pk=item['chunk_id'])
                assert item['corpus_hash'] == chunk.document.content_hash
                assert item['version_label'] == chunk.document.version_label
