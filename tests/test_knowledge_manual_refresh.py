from django.test import SimpleTestCase

from knowledge.manual_catalog import manual_entries


class ManualRefreshTests(SimpleTestCase):
    def test_quality_guide_matches_real_resources_and_result_workflow(self):
        from base.ui.registry import get_module, get_resource
        from knowledge.step_by_step_manual import get_step_by_step

        guide = get_step_by_step('quality')
        published = next(
            entry['manual_content']
            for entry in manual_entries()
            if entry['metadata']['module_slug'] == 'quality'
        )
        for text in (guide, published):
            assert '**Inspeções**' not in text
            assert 'Como registrar uma inspeção de qualidade' not in text
            assert 'O sistema classifica como' not in text
        module = get_module('quality')
        assert module.label == 'Controle de qualidade'
        assert module.label in guide
        for resource in module.resources:
            assert f'**{resource.label}**' in guide
        analyses = get_resource('quality', 'analyses')
        assert analyses.inlines[0].title == 'Resultados Analíticos (LIMS)'
        for fact in (
            'Como registrar uma análise de qualidade',
            'amostra',
            'especificação',
            'Resultados Analíticos (LIMS)',
            'Adicionar ensaio',
            'resultado numérico',
            'resultado textual',
            '**Avaliar**',
            '**Revisar**',
            '**Aprovar**',
            'não aprova automaticamente',
        ):
            assert fact in guide

    def test_inventory_guide_matches_read_only_ledger_and_balance_dimensions(self):
        from base.ui.registry import get_resource
        from knowledge.step_by_step_manual import get_step_by_step

        guide = get_step_by_step('inventory')
        for slug in ('lots', 'balances', 'movements'):
            resource = get_resource('inventory', slug)
            assert f'**{resource.label}**' in guide
        assert get_resource('inventory', 'movements').read_only is True
        assert get_resource('inventory', 'balances').update_form_fields == ()
        for fact in (
            'quantidade reservada',
            'quantidade disponível',
            'almoxarifado',
            'localização',
            'somente leitura',
            'operações de domínio',
            'validade',
        ):
            assert fact in guide
        for obsolete in (
            '**Movimentações de estoque**',
            '**Saldos de estoque**',
            '**Lotes de estoque**',
            'Para entradas manuais',
            'quantidade, reservado, disponível, validade',
        ):
            assert obsolete not in guide

    def test_manual_describes_current_product_and_formula_workflow(self):
        entries = {entry['metadata']['module_slug']: entry for entry in manual_entries()}
        masters = entries['masters']['manual_content']
        formulas = entries['formulations']['manual_content']
        for fact in (
            'três abas',
            '**Produto**',
            '**Componentes**',
            'Fórmula mestra',
            'versão explícita',
            'salvo separadamente',
            'sem preenchimento com zeros',
            'CODE_PREFIX-ID',
        ):
            assert fact in masters
        for fact in (
            'duas abas',
            'Fórmula mestra',
            'Componentes',
            'versões anteriores',
            'aprovadas',
            'filtros dependentes',
            'salvo separadamente',
        ):
            assert fact in formulas
        assert 'FM-001' not in formulas
        assert '**Produto:** seleção' not in formulas
        content = '\n'.join(entry['manual_content'] for entry in entries.values())
        assert 'Aplicativos > Fluxo de trabalho' in content
        assert '/app/workspaces/workflow/' in content
        assert '/app/workflow/' in content
