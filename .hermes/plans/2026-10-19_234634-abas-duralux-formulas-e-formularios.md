# Plano — abas Duralux em fórmulas e formulários com registros filhos

**Estado:** proposta para aprovação; implementação não iniciada.  
**Workspace:** `/Users/rgnsystems/Documents/rgnfarmasystemv2`.  
**Referência visual:** `design_system/customers-create.html:2303–2385`, sobretudo o card, o cabeçalho de abas e as linhas label/controle.  
**Regra deste turno:** somente este Markdown foi criado; os comandos abaixo são para execução futura.

## Goal

Reorganizar criação, edição e reaproveitamento de fórmulas em **Produto / Fórmula mestra / Componentes**, adotando o padrão Duralux fornecido e estendendo a navegação por abas aos formulários genéricos que já possuem registros filhos, sem mudar permissões ou persistência.

## Contexto atual e premissas

### O que foi confirmado no código

- `formulations/` não possui template próprio de cadastro. As telas usam `templates/app/resource_form.html`, por `ResourceCreateView` e `ResourceUpdateView`, em `base/ui/views.py:1649–2041`.
- `MasterFormulaReuseView`, em `formulations/ui_views.py:24–77`, herda esse fluxo. O reaproveitamento deve receber a mesma apresentação, sem perder código automático, rascunho, nova versão e rastreabilidade.
- A fórmula e seu inline estão configurados em `base/ui/registry.py:680–733`. O inline `components` é atualmente **tabular**, com nove campos editáveis espremidos em uma tabela.
- `resource_form.html:58–96` apresenta todos os campos e depois todos os filhos, verticalmente. Seus scripts de adicionar/remover linhas estão no próprio template.
- `templates/app/includes/inline_stacked.html` já fornece cartões e uma `form-grid` responsiva; usá-lo, em vez de construir outro editor de componentes.
- `base/ui/forms.py:473–583` gera os ModelForms e seus metadados. As abas devem usar os **BoundFields do formulário efetivamente autorizado**, nunca reconstruir campos a partir do model.
- `ResourceCreateView.get_inline_formsets()` já entrega disponibilidade, permissões, formset e estilo de cada filho. O agrupamento não deve recriar formsets ou acessar filhos sem autorização.
- `save_object_and_inline_formsets()` já implementa transação, auditoria, atribuição de atores e proteções operacionais. **Não alterar esse método.**
- Bootstrap e Duralux já são locais e carregados por `templates/base.html`. O bundle expõe `window.bootstrap` e `Tab.getOrCreateInstance`. Não instalar Select2, framework SPA ou uma segunda cópia do Bootstrap.
- `resource_detail.html` e os cockpits já possuem abas com outras finalidades. Este plano reorganiza **formulários**; não mistura cadastro com cockpit de abastecimento, detalhe, árvore BOM ou quadro de execução.
- A árvore Git está suja com as correções P1 anteriores. Não apagar, reformatar em massa, sobrescrever nem incluir essas mudanças em commits deste trabalho.
- A validação anterior deixou falhas globais conhecidas, registradas em `docs/validation/p1-integrity-corrections.md`. Um teste global já reprovado não pode ser atribuído automaticamente a esta mudança, nem removido para produzir verde.

### Interpretação funcional explícita

**Produto** significa selecionar o produto já cadastrado, usando o campo `product` existente; o texto do select já apresenta código e descrição (`masters/models.py:206–207`). Não significa editar `masters.Product` junto com a fórmula. Texto auxiliar: “Selecione um produto cadastrado. Os dados cadastrais do produto são mantidos no módulo Cadastros.” Sem endpoint novo ou consulta Ajax de resumo neste escopo.

**Fórmula mestra** recebe todos os demais campos visíveis que o formulário atual autoriza: versão, status, lote padrão, unidade, rendimento, vigência, observações e identificador quando presente. Não restaurar campos excluídos pelo fluxo; não tornar editáveis identificadores automáticos, status bloqueado no reaproveitamento ou campos de autoria.

**Componentes** recebe o mesmo formset `components`, seus management fields, IDs, erros e ações existentes. Trocar apenas seu estilo de apresentação para cartões `stacked`.

### Escopo fechado de propagação

Levantamento estático do registry: **12 recursos em 10 apps** já têm inlines. Aplicar automaticamente o mesmo componente de navegação a seus formulários genéricos:

| Recurso | Abas depois de “Informações gerais” |
|---|---|
| `formulations/formulas` | Exceção: Produto / Fórmula mestra / Componentes |
| `production/orders` | Matérias-primas; Produtos acabados; Processos; Colaboradores |
| `procurement/orders` | Itens do pedido |
| `procurement/receipts` | Itens do recebimento |
| `quality/analyses` | Resultados Analíticos (LIMS), preservando `qc_grid` |
| `documents/controlled-documents` | Anexos documentais; Aprovações documentais; Distribuições documentais |
| `deviations/events` | Investigações de desvio; Avaliações de impacto; Aprovações de desvio; Evidências de desvio |
| `capa/records` | Ações CAPA; Evidências CAPA; Aprovações CAPA; Verificações de eficácia |
| `audits/plans` | Checklist de auditoria; Achados de auditoria; Evidências de auditoria |
| `audits/findings` | Ações de auditoria |
| `risks/records` | Avaliações de risco; Controles de risco; Ações de mitigação; Revisões de risco; Alertas de risco |
| `recalls/campaigns` | Clientes impactados; Comunicações de recall; Relatório de efetividade |

Recursos sem inlines continuam no formulário simples atual. `formulations/routes` não possui inline de etapas hoje: **não criar essa relação de edição apenas para justificar abas**. Cockpits e `resource_execution_board.html` permanecem intactos.

## Arquitetura / abordagem proposta

Adicionar um pequeno apresentador puro em `base/ui/form_layouts.py`, que agrupa BoundFields e os dicionários de inlines já construídos pela view, sem consultar ou gravar dados. Renderizar esse contexto em um partial compartilhado com o card e as abas Duralux, mantendo um único formulário, um único POST e as ações Salvar/Cancelar fora dos painéis. Um JavaScript externo cuida da validação de campos em abas ocultas e do teclado; CSS com escopo local mantém o conteúdo utilizável quando JavaScript ou Bootstrap não carregam.

### Contrato visual — não deixar ao gosto do implementador

1. Preservar o shell, breadcrumbs e fontes de `base.html`; não copiar menu, notificações, customizador ou scripts de demo do HTML de referência.
2. Um card `card border-top-0 resource-form-tabs`; cabeçalho `card-header p-0`; navegação `nav nav-tabs flex-wrap w-100 text-center customers-nav-tabs`; itens `nav-item flex-fill border-top`.
3. Usar **buttons `type="button"`**, não links `javascript:void(0)`. ARIA completo: tablist, tab, tabpanel, `aria-controls`, `aria-labelledby`, `aria-selected` e IDs estáveis.
4. Nas abas de campos do pai, usar linhas `row mb-4 align-items-start`: label `col-lg-4`, controle `col-lg-8`. Em telas menores, label acima do controle. Preservar widgets, required, help_text e IDs de erro existentes.
5. Componentes em cartões empilhados com `form-grid`, não tabela de nove colunas. Não introduzir accordion: todos os campos do cartão ficam visíveis dentro da aba.
6. Abas podem quebrar linha no celular como a referência. Não criar rolagem horizontal da página; tabelas LIMS e de outras apps continuam com seu scroll local.
7. Salvar e Cancelar aparecem **uma vez**, fora de `.tab-content`, dentro do `<form>`. Não criar salvamento por aba, “próximo passo” ou “salvar rascunho” fictício.
8. Aba com erro recebe badge textual “Erro”, não apenas cor. POST inválido abre a primeira aba com erro; erro não vinculado a campo do pai abre Fórmula mestra/Informações gerais.
9. Sem JS/Bootstrap, esconder a navegação e exibir todos os painéis em sequência. Nunca deixar controles obrigatórios inacessíveis.
10. Sem gradientes, novos avatares, cartões de métricas ou selos de conformidade adicionais. Não alterar CSS global de `.card`, `.nav-tabs` ou `.form-grid`.

## Arquivos envolvidos

**Novos:**
- `base/ui/form_layouts.py`
- `templates/app/includes/resource_form_tabs.html`
- `templates/app/includes/resource_form_field.html`
- `templates/app/includes/resource_inline_formset.html`
- `static/js/resource-form-tabs.js`
- `tests/test_resource_form_tabs.py`
- `docs/architecture/resource-form-tabs.md`

**Alterações localizadas:**
- `base/ui/views.py`: import e atualização de contexto em `ResourceCreateView.get_context_data()` apenas.
- `base/ui/registry.py`: somente `inline_style` dos componentes da fórmula, de `tabular` para `stacked`.
- `templates/app/resource_form.html`: ramo tabulado, renderização única de hidden fields, includes e carregamento do novo JS; manter scripts de adicionar/excluir.
- `templates/app/includes/inline_stacked.html`: reutilizar renderer de campo e dar à exclusão o botão acessível existente no estilo tabular.
- `static/css/app.css`: acrescentar regras exclusivamente sob `.resource-form-tabs`.
- `tests/test_formula_inline_components_ui.py`: atualizar apenas o teste que pressupõe tabela na fórmula; manter as regressões de negócio e do tabular.

**Não alterar:** models, serializers, APIs, migrations, contratos de permissão, menu, arquivos vendor, `.env`, arquivos de assinatura, configurações operacionais e correções P1 já presentes.

## Preparação de verificação para o implementador

Os comandos desta seção **não foram executados no modo plano**. Executar a partir da raiz após autorização de implementação.

```bash
pwd
git status --short
git diff --check
.venv/bin/python -m pytest --version
```

Esperado: raiz acima; mudanças preexistentes identificadas; diff sem erro de whitespace. O ambiente desta sessão havia precisado de um runner externo para pytest; **não depender desse arquivo temporário para entregar a feature**. Se pytest/dependências faltarem, pedir autorização para preparar `requirements-dev.txt` antes de continuar; não instalar nem improvisar outro ambiente silenciosamente.

Com ambiente de dev preparado, o comando oficial de testes é:

```bash
bash scripts/test.sh tests/test_formula_inline_components_ui.py -q --tb=short
```

Ele inicia o PostgreSQL de testes pela configuração `docker-compose.test.yml`. Não apontar `TEST_DATABASE_URL` para banco operacional e não usar SQLite. Guardar baseline e novos resultados em evidência local, sem afirmar que todos os testes antigos estão verdes.

## Tarefas passo a passo

Cada item abaixo é uma unidade de 2–5 minutos de edição focada, excluindo tempo de execução do banco. Dependências são sequenciais até o primeiro checkpoint. **TDD significa observar a falha especificada, aplicar a mudança indicada e observar aprovação; não marcar execução apenas por ler este plano.**

### 1. Registrar o baseline, sem misturar o patch P1 — 3 min

- Ler `AGENTS.md`, este plano, `docs/validation/p1-integrity-corrections.md` e `git diff -- base/ui/registry.py`.
- Rodar a preparação acima e o arquivo de testes de fórmula. Registrar falhas preexistentes por nodeid e mensagem.
- Se autorizado a trabalhar em branch nova: `git switch -c feat/ui-resource-form-tabs`. Não criar branch nem commit neste turno de planejamento.
- Critério: mudanças P1 conhecidas e preservadas; dependências e banco de testes confirmados. Se faltar ambiente, bloquear a execução com o motivo, não trocar o escopo.

### 2. RED do agrupamento puro — 4 min

- Criar `tests/test_resource_form_tabs.py` com o código do **Apêndice A**.
- Executar:

```bash
bash scripts/test.sh tests/test_resource_form_tabs.py -q --tb=short
```

- RED esperado: falta `base.ui.form_layouts`/helper; depois de criado, falhas devem ser assertivas do contrato, não erro de configuração do banco.
- Não criar view nem template ainda.

### 3. GREEN do agrupamento — 5 min

- Criar `base/ui/form_layouts.py` com o **Apêndice B**.
- Repetir o comando da tarefa 2. Esperado: todos os casos do apêndice aprovados.
- Verificar que não há acesso a model manager, URL ou `save()` nesse módulo.
- Checkpoint/commit, somente após autorização para implementar e com o diff revisado:

```bash
git add base/ui/form_layouts.py tests/test_resource_form_tabs.py
git diff --cached --check
git commit -m "feat(ui): define agrupamento de formulários em abas"
```

### 4. RED de integração das três abas — 5 min

- Acrescentar os testes do **Apêndice C** em `tests/test_resource_form_tabs.py`.
- Executar:

```bash
bash scripts/test.sh tests/test_resource_form_tabs.py -k 'formula_page or every_inline_resource or simple_resource' -q --tb=short
```

- RED esperado: contexto `form_tabs` inexistente e ausência de `data-ui="resource-form-tabs"`. O teste de recurso simples funciona como controle negativo.

### 5. Conectar o contexto sem tocar no POST — 3 min

- Em `base/ui/views.py`, importar `build_resource_form_layout` de `base.ui.form_layouts`.
- No fim de `ResourceCreateView.get_context_data()`, **depois** de construir `inline_formsets` e antes do `return context`, acrescentar exatamente:

```python
context.update(build_resource_form_layout(self.get_resource(), form, inline_formsets))
```

- `ResourceUpdateView` e `MasterFormulaReuseView` herdam esse contexto. Não duplicar o cálculo nas subclasses. Não usar `context['form_mode']` para decidir grupos: na chamada do pai ele ainda pode ser `create`.
- Repetir a seleção da tarefa 4. Esperado neste ponto: assertivas do contexto aprovam; assertivas de HTML ainda falham. Essa falha parcial é esperada até a tarefa 8.

### 6. Extrair renderização de campo — 4 min

- Criar `templates/app/includes/resource_form_field.html` com o **Apêndice D**.
- No ramo simples de `resource_form.html`, substituir apenas o corpo repetido de cada campo por esse include, sem `horizontal=True`.
- Usar `form.visible_fields` nesse loop e renderizar `form.hidden_fields` uma vez no início do `<form>`, depois de CSRF; não repetir campos ocultos nos painéis.
- Em `tests/test_resource_form_tabs.py`, acrescentar o teste pequeno do Apêndice D antes da extração e observar RED. Executar `bash scripts/test.sh tests/test_resource_form_tabs.py -k field_renderer -q` até GREEN.
- Não modificar IDs de help/error produzidos por `_annotate_form_accessibility()`.

### 7. Extrair o dispatcher de inline — 3 min

- Criar `templates/app/includes/resource_inline_formset.html` com o **Apêndice E**; é a mesma decisão que já existe em `resource_form.html:77–94`.
- Substituir o dispatcher antigo pelo include, mantendo a variável `inline` e os handlers JS intactos.
- Verificar por teste existente:

```bash
bash scripts/test.sh tests/test_formula_inline_components_ui.py -k 'renders_inline_component_section or priority_parent_forms_render_registered_inline_sections' -q --tb=short
```

- Esperado: aprovação sem alteração de management fields nem marcadores `data-inline-*`.

### 8. GREEN do card tabulado — 5 min

- Criar `templates/app/includes/resource_form_tabs.html` com o **Apêndice F**.
- Em `resource_form.html`, manter um único `<form method="post" class="resource-form" data-ui="resource-form">`, CSRF, `enctype` condicional e erros globais.
- Quando `form_tabs` não estiver vazio, renderizar o novo include **no lugar** do cabeçalho “Campos do Registro”, da grade e dos inlines antigos. Não manter uma cópia fora das abas.
- Quando estiver vazio, manter a apresentação simples, com o renderer da tarefa 6. Tirar o card externo comum do caminho tabulado: o partial F já é o card e seu `card-header p-0` precisa ficar rente às bordas, não dentro de outro `card-body p-4`.
- Incluir `includes/form_actions.html` uma vez após o corpo selecionado, ainda dentro do `<form>`. Preservar título/breadcrumbs “Novo registro/Editar registro - {{ resource.label }}”.
- Repetir a seleção da tarefa 4. Esperado: GREEN; cada campo do pai e cada management form aparece uma única vez.
- Checkpoint: formulário novo e edição usam a mesma infraestrutura; sem alteração em `post()`, transações, audit ou autorização.

### 9. RED/GREEN dos componentes legíveis — 5 min

- Em `tests/test_formula_inline_components_ui.py`, substituir o teste `test_tabular_inline_delete_control_is_icon_action` por `test_stacked_formula_delete_control_is_icon_action`: mesma requisição da fórmula, mas exigir `.resource-inline-formset__form`, `data-inline-formset-delete`, `aria-label="Excluir item"`, `feather-trash-2` e ausência de tabela no editor de componentes.
- Preservar a cobertura tabular com o teste do **Apêndice G**; não simplesmente apagar as assertivas antigas.
- RED: a fórmula ainda contém tabela e o stacked não oferece o botão.
- Em `base/ui/registry.py:723`, trocar **somente** `inline_style='tabular'` do inline `components` para `inline_style='stacked'`.
- Em `inline_stacked.html`, nos dois loops (`forms` e `empty_form`), trocar apenas o ramo `field.name == 'DELETE'` por:

```django
<div class="form-field form-field-inline">
    <span class="d-none">{{ field }}</span>
    <button type="button" class="btn btn-icon btn-outline-danger"
            data-inline-formset-delete aria-label="Excluir item" title="Excluir item">
        <i class="feather-trash-2" aria-hidden="true"></i>
        <span class="visually-hidden">Excluir item</span>
    </button>
    {% if field.errors %}
        <span class="invalid-feedback d-block field-error"
              id="{{ field.id_for_label }}_errors" role="alert">{{ field.errors }}</span>
    {% endif %}
</div>
```

- Para campos diferentes de DELETE, reutilizar o renderer D sem horizontal, preservando hidden fields e non-field errors no cartão.
- Rodar `bash scripts/test.sh tests/test_formula_inline_components_ui.py tests/test_resource_form_tabs.py -q --tb=short`. Esperado: novas assertivas e regressões de criação/edição/exclusão/reaproveitamento/rollback/permissão aprovadas, ressalvado apenas baseline comprovado e documentado.

### 10. RED/GREEN de abertura da aba com erro — 5 min

- Acrescentar na classe `FormulaInlineComponentsUiTests` um teste usando seus helpers existentes `_formula_payload()` e `_component_payload()`:
  1. POST de criação com produto válido, um componente e `components-0-quantity='0'`.
  2. Exigir HTTP 200, `active_form_tab == 'inline-components'`, `form_tabs[-1]['has_errors'] is True` e nenhum `MasterFormula` persistido.
  3. Em outro teste, usar `batch_size='0'` e componente válido; exigir `active_form_tab == 'formula'`.
  4. Em outro, `product=''`; exigir `active_form_tab == 'product'`.
- A primeira formulação exata do payload é:

```python
payload = {
    **self._formula_payload('IGNORED-AUTO-CODE'),
    'components-TOTAL_FORMS': '1',
    'components-INITIAL_FORMS': '0',
    'components-MIN_NUM_FORMS': '0',
    'components-MAX_NUM_FORMS': '1000',
    **self._component_payload(0, 10, self.materials[0], FormulaComponent.Role.ACTIVE),
    'components-0-quantity': '0',
}
response = self.client.post(
    reverse('app:resource_create', kwargs={
        'module_slug': 'formulations', 'resource_slug': 'formulas',
    }),
    payload,
)
assert response.status_code == 200
assert response.context['active_form_tab'] == 'inline-components'
assert response.context['form_tabs'][-1]['has_errors'] is True
assert MasterFormula.objects.count() == 0
```

- Executar esses três nodeids individualmente; esperado GREEN com o helper B. Se falhar, corrigir somente agrupamento/seleção, nunca flexibilizar validações do model.
- Testar management form ausente e duas linhas com mesma `line_number`: erro deve abrir Componentes, sem persistência. Ambos são casos de `non_form_errors()`.

### 11. TDD de CSS e fallback sem JavaScript — 4 min

- Criar em `tests/test_resource_form_tabs.py` um teste `test_styles_are_scoped_and_have_no_script_fallback`: ler `static/css/app.css` e exigir os seletores e propriedades do **Apêndice H**.
- Rodar `bash scripts/test.sh tests/test_resource_form_tabs.py -k styles_are_scoped -q`; RED antes do CSS.
- Acrescentar H no fim de `static/css/app.css`. Repetir; esperado GREEN.
- A assertiva textual apenas protege o contrato de escopo; não substitui o navegador da tarefa 15.

### 12. TDD de navegação e campos obrigatórios ocultos — 5 min de edição

- Criar `static/js/resource-form-tabs.js` com o **Apêndice I**.
- Acrescentar `{% load static %}` em `resource_form.html` e, no bloco scripts, carregar esse arquivo com `defer` **somente quando `form_tabs` existir**. Os scripts existentes de adicionar/excluir permanecem presentes.
- Antes de carregar o script, executar o cenário de validação cliente da tarefa 15: controle obrigatório em aba inativa não pode ser focado corretamente pelo fluxo atual. Registrar o RED real de comportamento; não usar somente busca de string como prova.
- Depois, repetir: clicar Salvar com unidade do lote vazia deve abrir Fórmula mestra, focar o controle e não mostrar overlay nem enviar POST. Esperado GREEN.
- O handler captura submit antes do listener de `app-form-enhancements.js`, evitando overlay e botão travado em erro. Não retirar `required` de todos os campos nem desativar validação no backend.

### 13. TDD de exclusão de uma linha nova e vazia — 4 min

- Cenário RED de navegador: Adicionar componente; deixar material/quantidade vazios; excluir esse cartão; salvar um conjunto restante válido. A linha excluída não pode bloquear a validação HTML5.
- O handler de exclusão do Apêndice I desabilita controles visíveis da linha, mas mantém habilitados `id`, FK oculta e DELETE; o handler antigo continua marcando DELETE e escondendo a linha.
- Acrescentar teste backend de exclusão enviando ID, FK e DELETE de um componente existente, sem os demais campos dessa linha. Exigir que ele seja removido e que outro componente não seja alterado.
- Executar `bash scripts/test.sh tests/test_formula_inline_components_ui.py -k 'updates_and_deletes or deleted_component' -q --tb=short`. Esperado GREEN.
- Não decrementar TOTAL_FORMS e não renumerar índices: isso corromperia a associação com IDs existentes.

### 14. TDD de permissões e reaproveitamento — 5 min

- Nos testes novos, criar usuário com `view_masterformula`, `add_masterformula` e `change_masterformula`, **sem** `view_formulacomponent`. GET da fórmula deve mostrar a aba com mensagem de acesso negado, sem `components-TOTAL_FORMS`, sem material, sem adicionar/excluir. Não usar o marker `legacy_api_permissions`.
- POST forjado com campos `components-*` continua sendo rejeitado pelo fluxo existente. Usar uma versão válida, nova, para que o teste alcance a checagem de permissão, em vez de falhar antes por duplicidade.
- Acrescentar ao teste de reaproveitamento existente assertivas de keys `['product', 'formula', 'inline-components']` e HTML único; manter as verificações de rascunho, código gerado, `copied_from` e versão.
- Repetir o arquivo completo de fórmulas. Se houver regressão, restaurar a lógica original de autorização/formset; o apresentador não pode substituí-la.
- Checkpoint/commit: revisar `git diff`; usar `git add -p` nos arquivos já sujos, aprovando **somente** hunks de abas. Nunca `git add .`. Mensagem: `feat(ui): aplica abas Duralux a formulários com inlines`.

### 15. Verificação visual e de comportamento — unidades de 3–5 min por cenário

Usar **ambiente QA local isolado e autenticado**, nunca dados operacionais. Reutilizar o runtime de navegador do executor; não adicionar dependências de browser ao app só para realizar esta inspeção. Se não houver servidor QA/sessão sintética disponível, registrar essa dependência e bloquear o aceite visual; não chamar testes Django de aprovação visual.

Rotas confirmadas para um servidor QA em `http://127.0.0.1:8000`:
- criar: `/app/formulations/formulas/new/`;
- editar: `/app/formulations/formulas/<pk>/edit/`;
- reaproveitar: `/app/formulations/formulas/<pk>/reuse/`.

Obter `<pk>` de uma fórmula sintética existente no QA; não adivinhar. Confirmar o endpoint de criação em `base/ui/urls.py` antes da navegação. Autenticação por mecanismo seguro do executor; nunca pedir senha em chat.

**Cenário A — referência e responsividade:** capturar em 320, 768, 1024 e 1440 px. Comparar card/abas/label 4–controle 8 com o miolo do HTML de referência, não com sua navegação de demo. No console do navegador executar:

```javascript
console.assert(document.documentElement.scrollWidth <= innerWidth + 1, 'overflow da página');
console.assert(document.querySelectorAll('[data-ui="resource-form-tabs"]').length === 1);
console.assert(document.querySelectorAll('[data-ui="resource-form-tabs"] [role="tab"]').length === 3);
console.assert(document.querySelectorAll('[data-ui="resource-form-tabs"] .tab-pane.active').length === 1);
console.assert(document.querySelectorAll('[name="components-TOTAL_FORMS"]').length === 1);
```

Esperado: nenhuma assertiva no console; componentes sem tabela comprimida; nenhum label truncado para caber artificialmente.

**Cenário B — teclado:** foco em Produto; ArrowRight abre Fórmula mestra; End abre Componentes; Home volta a Produto. `aria-selected` deve acompanhar o painel, e Tab deve alcançar seus controles. Repetir no desktop e a 320 px.

**Cenário C — validação:** preencher um conjunto sintético válido; limpar unidade do lote; abrir Produto e clicar Salvar. Esperado: aba Fórmula mestra aberta, foco em `#id_batch_unit`, nenhum request POST e overlay ainda oculto. Restaurar, invalidar quantidade do primeiro componente e repetir a partir de Produto; esperado Componentes aberto. Para erro do servidor, mandar quantidade zero e confirmar dados preservados e badge Erro.

**Cenário D — adicionar/excluir:** adicionar duas linhas; conferir incremento de TOTAL_FORMS e IDs distintos. Excluir uma linha vazia: DELETE marcado, ID preservado quando existente, controles visíveis desabilitados, nenhum índice renumerado. Salvar restante válido, reabrir edição e confirmar persistência/auditoria nos testes backend.

**Cenário E — fallback:** recarregar com JavaScript desativado e depois simulando falha de carregamento do bundle Bootstrap. Esperado: navegação escondida, todos os painéis legíveis e controles acessíveis. Nenhum dado pode desaparecer por CSS.

**Cenário F — outras apps:** abrir `production/orders`, `quality/analyses`, `documents/controlled-documents` e `risks/records` em criação/edição. Conferir tabs, permissões, grade LIMS e múltiplos inlines; no QA sem permissão, nenhuma informação protegida. Recursos simples como `/app/masters/units/new/` continuam sem tabs.

Guardar screenshots e recibos fora de arquivos versionados com dados sensíveis, por exemplo em `.hermes/qa/resource-form-tabs/`. Não anexar cookies, tokens ou dados reais. Parar/limpar runtime QA criado exclusivamente para a verificação.

### 16. Documentar e executar os gates — 5 min de edição

- Criar `docs/architecture/resource-form-tabs.md`: referência visual, regra de agrupamento, tabela dos 12 recursos, responsabilidades do helper, POST único, tratamento de erros, fallback e limites de permissão.
- Registrar revisão de menu/permissões: sem módulo ou permissão nova; não alterar navegação nem conceder acessos.
- Rodar os comandos abaixo no ambiente de testes preparado:

```bash
bash scripts/test.sh tests/test_resource_form_tabs.py tests/test_formula_inline_components_ui.py tests/test_formulations.py tests/test_p1_collection_permissions.py tests/test_p1_production_stale_updates.py tests/test_p1_stock_balance_retention.py tests/test_p1_stock_lot_identity.py -q --tb=short
.venv/bin/python -m ruff check base/ui/form_layouts.py base/ui/views.py base/ui/registry.py tests/test_resource_form_tabs.py tests/test_formula_inline_components_ui.py
.venv/bin/python -m ruff format --check base/ui/form_layouts.py base/ui/views.py base/ui/registry.py tests/test_resource_form_tabs.py tests/test_formula_inline_components_ui.py
.venv/bin/python -m mypy base/ui/form_layouts.py
node --check static/js/resource-form-tabs.js
git diff --check
```

Esperado: seleção focada aprovada; `All checks passed!`; arquivos já formatados; MyPy sem erros; Node e diff sem saída e exit 0. Não declarar esses resultados sem executar.

- No mesmo ambiente com `TEST_DATABASE_URL` isolado, executar `manage.py check --settings=core.settings.test` e `manage.py makemigrations --check --dry-run --settings=core.settings.test`; esperado nenhum problema e `No changes detected`. Não apontar esses comandos para settings de produção.
- Rodar também `bash scripts/test.sh tests/test_app_ui.py tests/test_responsive_layout_css.py tests/test_production_operations.py -q --tb=short`; comparar falhas com baseline, sem “corrigir” requisitos fora do escopo ou apagar testes.
- Rodar a suíte completa pelo gate oficial quando o ambiente estiver pronto; qualquer falha nova causada por esta feature bloqueia entrega. Falhas anteriores devem ficar separadas e não permitem anunciar release geral verde.
- Commit pequeno de documentação/testes, só de arquivos/hunks desta feature: `docs(ui): documenta formulários em abas e validação acessível`.

## Apêndices — código proposto, não aplicado

### A. Testes puros iniciais — `tests/test_resource_form_tabs.py`

```python
from types import SimpleNamespace

from django import forms
from django.forms import formset_factory


def resource(app='formulations', slug='formulas'):
    return SimpleNamespace(app_label=app, slug=slug)


def parent_form(data=None):
    class Parent(forms.Form):
        product = forms.CharField()
        version = forms.IntegerField(min_value=1)
        token = forms.CharField(widget=forms.HiddenInput, required=False)

    return Parent(data)


def inline(data=None):
    class Row(forms.Form):
        quantity = forms.DecimalField(min_value=1)

    factory = formset_factory(Row, extra=1)
    return {
        'key': 'components',
        'title': 'Componentes da fórmula',
        'available': True,
        'formset': factory(data, prefix='components'),
    }


def test_formula_groups_visible_fields_once():
    from base.ui.form_layouts import build_resource_form_layout

    form = parent_form()
    layout = build_resource_form_layout(resource(), form, [inline()])
    tabs = layout['form_tabs']
    assert [tab['key'] for tab in tabs] == ['product', 'formula', 'inline-components']
    assert [field.name for field in tabs[0]['fields']] == ['product']
    assert [field.name for field in tabs[1]['fields']] == ['version']
    assert sum(len(tab['fields']) for tab in tabs) == len(form.visible_fields())
    assert layout['active_form_tab'] == 'product'
    assert not form.is_bound


def test_generic_inlines_get_general_then_child_tabs():
    from base.ui.form_layouts import build_resource_form_layout

    layout = build_resource_form_layout(resource('procurement', 'orders'), parent_form(), [inline()])
    assert [tab['key'] for tab in layout['form_tabs']] == ['general', 'inline-components']


def test_simple_resource_has_no_tabs():
    from base.ui.form_layouts import build_resource_form_layout

    assert build_resource_form_layout(resource('masters', 'units'), parent_form(), []) == {
        'form_tabs': [], 'active_form_tab': '',
    }


def test_child_errors_activate_child_panel():
    from base.ui.form_layouts import build_resource_form_layout

    child = inline({
        'components-TOTAL_FORMS': '1', 'components-INITIAL_FORMS': '0',
        'components-MIN_NUM_FORMS': '0', 'components-MAX_NUM_FORMS': '1000',
        'components-0-quantity': '0',
    })
    layout = build_resource_form_layout(
        resource(), parent_form({'product': '1', 'version': '1'}), [child],
    )
    assert layout['active_form_tab'] == 'inline-components'
    assert layout['form_tabs'][-1]['has_errors'] is True


def test_unavailable_inline_is_not_dereferenced():
    from base.ui.form_layouts import build_resource_form_layout

    child = {'key': 'components', 'title': 'Componentes', 'available': False, 'formset': None}
    layout = build_resource_form_layout(resource(), parent_form(), [child])
    assert layout['form_tabs'][-1]['inline'] is child
    assert layout['form_tabs'][-1]['has_errors'] is False


def test_valid_bound_child_does_not_get_an_error_badge():
    from base.ui.form_layouts import build_resource_form_layout

    child = inline({
        'components-TOTAL_FORMS': '1', 'components-INITIAL_FORMS': '0',
        'components-MIN_NUM_FORMS': '0', 'components-MAX_NUM_FORMS': '1000',
        'components-0-quantity': '1',
    })
    layout = build_resource_form_layout(
        resource(), parent_form({'product': '1', 'version': '1'}), [child],
    )
    assert layout['form_tabs'][-1]['has_errors'] is False
    assert layout['active_form_tab'] == 'product'


def test_non_field_parent_error_activates_formula():
    from base.ui.form_layouts import build_resource_form_layout

    form = parent_form({'product': '1', 'version': '1'})
    form.is_valid()
    form.add_error(None, 'Conflito de versão.')
    layout = build_resource_form_layout(resource(), form, [inline()])
    assert layout['active_form_tab'] == 'formula'
    assert layout['form_tabs'][1]['has_errors'] is True
```

### B. Apresentador — `base/ui/form_layouts.py`

```python
"""Agrupamento visual; não cria campos, formsets ou permissões."""


def build_resource_form_layout(resource, form, inline_formsets):
    is_formula = (resource.app_label, resource.slug) == ('formulations', 'formulas')
    if not is_formula and not inline_formsets:
        return {'form_tabs': [], 'active_form_tab': ''}

    fields = list(form.visible_fields())
    if is_formula:
        tabs = [
            {'key': 'product', 'label': 'Produto',
             'fields': [field for field in fields if field.name == 'product'], 'inline': None},
            {'key': 'formula', 'label': 'Fórmula mestra',
             'fields': [field for field in fields if field.name != 'product'], 'inline': None},
        ]
        main_key = 'formula'
    else:
        tabs = [{'key': 'general', 'label': 'Informações gerais', 'fields': fields, 'inline': None}]
        main_key = 'general'

    for item in inline_formsets:
        tabs.append({
            'key': f'inline-{item["key"]}',
            'label': 'Componentes' if is_formula and item['key'] == 'components' else item['title'],
            'fields': [], 'inline': item,
        })

    for tab in tabs:
        tab['has_errors'] = any(bool(field.errors) for field in tab['fields'])
        item = tab['inline']
        if item is not None and item['available'] and item['formset'] is not None:
            formset = item['formset']
            tab['has_errors'] = bool(any(formset.errors) or formset.non_form_errors())

    if form.non_field_errors():
        active_key = main_key
        next(tab for tab in tabs if tab['key'] == main_key)['has_errors'] = True
    else:
        active_key = next((tab['key'] for tab in tabs if tab['has_errors']), tabs[0]['key'])
    for tab in tabs:
        tab['active'] = tab['key'] == active_key
    return {'form_tabs': tabs, 'active_form_tab': active_key}
```

Aplicar o formatter do projeto antes de considerar GREEN; não expandir esse helper para um framework de layouts.

### C. Integração HTTP — acrescentar ao mesmo arquivo

```python
import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse


INLINE_RESOURCES = [
    ('formulations', 'formulas'), ('production', 'orders'),
    ('procurement', 'orders'), ('procurement', 'receipts'), ('quality', 'analyses'),
    ('documents', 'controlled-documents'), ('deviations', 'events'), ('capa', 'records'),
    ('audits', 'plans'), ('audits', 'findings'), ('risks', 'records'), ('recalls', 'campaigns'),
]


@pytest.fixture
def tab_admin(db, client):
    user = get_user_model().objects.create_superuser(
        username='tabs-admin', email='tabs-admin@example.com', password=None,
    )
    client.force_login(user)
    return client


def create_url(module, slug):
    return reverse('app:resource_create', kwargs={'module_slug': module, 'resource_slug': slug})


def test_formula_page_renders_three_unique_panels(tab_admin):
    response = tab_admin.get(create_url('formulations', 'formulas'))
    assert response.status_code == 200
    tabs = response.context['form_tabs']
    assert [tab['key'] for tab in tabs] == ['product', 'formula', 'inline-components']
    html = response.content.decode()
    assert 'data-ui="resource-form-tabs"' in html
    for tab in tabs:
        assert html.count(f'id="resource-tab-{tab["key"]}"') == 1
        assert html.count(f'id="resource-pane-{tab["key"]}"') == 1
    for field in response.context['form'].visible_fields():
        assert html.count(f'name="{field.html_name}"') == 1
    assert html.count('name="components-TOTAL_FORMS"') == 1


@pytest.mark.parametrize(('module', 'slug'), INLINE_RESOURCES)
def test_every_inline_resource_uses_the_shared_tabs(tab_admin, module, slug):
    response = tab_admin.get(create_url(module, slug))
    assert response.status_code == 200
    tabs = response.context['form_tabs']
    expected = {'inline-' + item['key'] for item in response.context['inline_formsets']}
    assert {tab['key'] for tab in tabs if tab['inline'] is not None} == expected
    assert 'data-ui="resource-form-tabs"' in response.content.decode()


def test_simple_resource_keeps_plain_form(tab_admin):
    response = tab_admin.get(create_url('masters', 'units'))
    assert response.status_code == 200
    assert response.context['form_tabs'] == []
    assert 'data-ui="resource-form-tabs"' not in response.content.decode()
```

Mover imports para o topo do arquivo ao consolidar A e C. Não duplicar fixture nem criar outra classe que herde todos os testes antigos e os execute em dobro.

### D. Renderer de campo — `templates/app/includes/resource_form_field.html`

```django
{% if horizontal %}
<div class="row mb-4 align-items-start resource-form-field">
    <div class="col-lg-4">
{% else %}
<div class="form-field {{ field.field.rgn_layout_class }}{% if field.field.widget.input_type == 'checkbox' %} form-field-inline{% endif %}">
{% endif %}
    <label for="{{ field.id_for_label }}" class="form-label fw-semibold text-dark">
        {{ field.label }}
        {% if field.field.required %}<span class="text-danger ms-1" aria-hidden="true">*</span>{% endif %}
    </label>
{% if horizontal %}</div><div class="col-lg-8">{% endif %}
    {{ field }}
    {% if field.help_text %}
        <span class="form-text fs-11 text-muted" id="{{ field.id_for_label }}_help">{{ field.help_text }}</span>
    {% endif %}
    {% if field.errors %}
        <span class="invalid-feedback d-block field-error" id="{{ field.id_for_label }}_errors" role="alert">{{ field.errors }}</span>
    {% endif %}
{% if horizontal %}</div>{% endif %}
</div>
```

Teste de contrato para inserir antes do arquivo existir:

```python
def test_field_renderer_preserves_ids_and_errors():
    from django.template.loader import render_to_string

    form = parent_form({'product': '', 'version': '1'})
    form.is_valid()
    html = render_to_string('app/includes/resource_form_field.html', {
        'field': form['product'], 'horizontal': True,
    })
    assert 'col-lg-4' in html and 'col-lg-8' in html
    assert 'for="id_product"' in html
    assert 'id="id_product_errors"' in html
    assert 'name="product"' in html
```

### E. Dispatcher — `templates/app/includes/resource_inline_formset.html`

```django
{% if not inline.available %}
<section class="card border border-gray-2 mt-4 resource-inline-formset" data-inline-formset="{{ inline.key }}">
    <div class="card-header bg-light p-3 border-bottom"><h2 class="h6 fw-bold mb-0">{{ inline.title }}</h2></div>
    <div class="card-body p-4">
        <div class="alert alert-secondary mb-0" role="status">
            <i class="feather-lock me-2" aria-hidden="true"></i>Você não possui permissão para visualizar estes registros.
        </div>
    </div>
</section>
{% elif inline.inline_style == 'tabular' %}
    {% include 'app/includes/inline_tabular.html' %}
{% elif inline.inline_style == 'qc_grid' %}
    {% include 'app/includes/inline_qc_grid.html' %}
{% else %}
    {% include 'app/includes/inline_stacked.html' %}
{% endif %}
```

### F. Card com abas — `templates/app/includes/resource_form_tabs.html`

```django
<div class="card border-top-0 resource-form-tabs" data-ui="resource-form-tabs">
    <div class="card-header p-0">
        <ul class="nav nav-tabs flex-wrap w-100 text-center customers-nav-tabs" role="tablist" aria-label="Seções do formulário">
            {% for tab in form_tabs %}
            <li class="nav-item flex-fill border-top" role="presentation">
                <button class="nav-link w-100{% if tab.active %} active{% endif %}"
                        id="resource-tab-{{ tab.key }}" type="button" role="tab"
                        data-bs-toggle="tab" data-bs-target="#resource-pane-{{ tab.key }}"
                        aria-controls="resource-pane-{{ tab.key }}"
                        aria-selected="{% if tab.active %}true{% else %}false{% endif %}">
                    {{ tab.label }}
                    {% if tab.has_errors %}<span class="badge bg-danger ms-2">Erro</span>{% endif %}
                </button>
            </li>
            {% endfor %}
        </ul>
    </div>
    <div class="tab-content">
        {% for tab in form_tabs %}
        <section class="tab-pane fade{% if tab.active %} show active{% endif %}"
                 id="resource-pane-{{ tab.key }}" role="tabpanel"
                 aria-labelledby="resource-tab-{{ tab.key }}" tabindex="0">
            <div class="card-body p-4">
                <h2 class="h6 fw-bold mb-4">{{ tab.label }}</h2>
                {% if tab.key == 'product' %}
                    <p class="text-muted fs-12">Selecione um produto cadastrado. Os dados cadastrais do produto são mantidos no módulo Cadastros.</p>
                {% endif %}
                {% for field in tab.fields %}
                    {% include 'app/includes/resource_form_field.html' with horizontal=True %}
                {% endfor %}
                {% if tab.inline %}
                    {% include 'app/includes/resource_inline_formset.html' with inline=tab.inline %}
                {% endif %}
            </div>
        </section>
        {% endfor %}
    </div>
</div>
```

Não envolver cada painel em `<form>`. A variável `horizontal` não deve vazar para o dispatcher de inline: passar `horizontal=False` explicitamente quando incluir o renderer nos cartões stacked.

### G. Manter contrato tabular sem depender da fórmula

```python
def test_tabular_delete_control_keeps_accessible_icon():
    from django.template.loader import render_to_string

    class Row(forms.Form):
        quantity = forms.DecimalField()

    factory = formset_factory(Row, extra=1, can_delete=True)
    html = render_to_string('app/includes/inline_tabular.html', {
        'inline': {
            'key': 'items', 'title': 'Itens', 'description': '',
            'can_add': True, 'add_label': 'Adicionar item', 'formset': factory(prefix='items'),
        },
    })
    assert '>Ações</th>' in html
    assert '>Excluir</th>' not in html
    assert 'data-inline-formset-delete' in html
    assert 'aria-label="Excluir item"' in html
```

### H. CSS estritamente local — acrescentar em `static/css/app.css`

```css
.resource-form-tabs:not([data-tabs-ready]) > .card-header {
    display: none;
}

.resource-form-tabs:not([data-tabs-ready]) > .tab-content > .tab-pane {
    display: block;
    opacity: 1;
}

.resource-form-tabs .nav-link {
    white-space: normal;
}

.resource-form-tabs .nav-link:focus-visible {
    outline: 2px solid var(--bs-primary);
    outline-offset: -2px;
}

.resource-form-tabs .resource-form-field,
.resource-form-tabs .resource-inline-formset,
.resource-form-tabs .form-field {
    min-width: 0;
}

.resource-form-tabs .resource-form-field .form-control,
.resource-form-tabs .resource-form-field .form-select,
.resource-form-tabs .resource-inline-formset .form-control,
.resource-form-tabs .resource-inline-formset .form-select {
    max-width: 100%;
}

.resource-form-tabs .resource-inline-formset {
    margin-top: 0 !important;
    margin-bottom: 0;
}

@media (max-width: 767.98px) {
    .resource-form-tabs .resource-inline-formset .form-field {
        grid-column: 1 / -1;
    }
}
```

O `!important` é restrito à substituição do `mt-4` utilitário nos cards de inline já existentes, dentro da aba; não acrescentar overrides globais. Se algum controle causar overflow a 320 px, corrigir o controle dentro desse escopo, não encolher a fonte do app inteiro.

### I. Navegação / validação — `static/js/resource-form-tabs.js`

```javascript
(function () {
    document.addEventListener('DOMContentLoaded', function () {
        const Tab = window.bootstrap && window.bootstrap.Tab;
        if (!Tab) return;

        document.querySelectorAll('[data-ui="resource-form-tabs"]').forEach(function (root) {
            const form = root.closest('form');
            const buttons = Array.from(root.querySelectorAll('[role="tab"]'));
            if (!form || !buttons.length) return;
            buttons.forEach(function (button) { Tab.getOrCreateInstance(button); });
            root.dataset.tabsReady = 'true';
            form.noValidate = true;
            let invalidBatch = false;

            function reveal(control, report) {
                const pane = control.closest('[role="tabpanel"]');
                if (!pane || !root.contains(pane)) return;
                const button = buttons.find(function (item) {
                    return item.getAttribute('aria-controls') === pane.id;
                });
                if (!button) return;
                function focus() {
                    if (!pane.classList.contains('active')) return;
                    control.focus();
                    if (report) control.reportValidity();
                }
                if (pane.classList.contains('active')) {
                    focus();
                } else {
                    button.addEventListener('shown.bs.tab', focus, { once: true });
                    Tab.getOrCreateInstance(button).show();
                }
            }

            root.querySelector('[role="tablist"]').addEventListener('keydown', function (event) {
                const index = buttons.indexOf(event.target);
                if (index < 0) return;
                let target;
                if (event.key === 'Home') target = 0;
                else if (event.key === 'End') target = buttons.length - 1;
                else if (event.key === 'ArrowRight') target = (index + 1) % buttons.length;
                else if (event.key === 'ArrowLeft') target = (index + buttons.length - 1) % buttons.length;
                else return;
                event.preventDefault();
                event.stopPropagation();
                Tab.getOrCreateInstance(buttons[target]).show();
                buttons[target].focus();
            });

            form.addEventListener('invalid', function (event) {
                if (invalidBatch) return;
                invalidBatch = true;
                reveal(event.target, false);
                queueMicrotask(function () { invalidBatch = false; });
            }, true);

            form.addEventListener('submit', function (event) {
                if (form.checkValidity()) return;
                event.preventDefault();
                event.stopImmediatePropagation();
                const control = form.querySelector('input:invalid, select:invalid, textarea:invalid');
                if (control) reveal(control, true);
            }, true);

            form.addEventListener('click', function (event) {
                const button = event.target.closest('[data-inline-formset-delete]');
                if (!button) return;
                const row = button.closest('[data-inline-formset-form]');
                if (!row) return;
                const deletion = row.querySelector('input[type="checkbox"][name$="-DELETE"]');
                if (!deletion || deletion.disabled) return;
                row.querySelectorAll('input, select, textarea').forEach(function (control) {
                    if (control !== deletion && control.type !== 'hidden') control.disabled = true;
                });
            }, true);

            const firstError = root.querySelector('.tab-pane.active [aria-invalid="true"]:not([disabled])');
            if (firstError) firstError.focus();
        });
    });
}());
```

Este código é a proposta mínima a exercitar em navegador. Não inferir que `node --check` comprova foco, eventos Bootstrap, ausência de POST ou interação com o overlay. Essas evidências pertencem às tarefas 12, 13 e 15.

## Tests / validação e critérios de aceite

- [ ] Criação, edição e reaproveitamento de fórmula têm exatamente Produto / Fórmula mestra / Componentes.
- [ ] Componentes não ficam fora do painel nem continuam comprimidos em tabela de nove colunas.
- [ ] Cada campo autorizado e management form aparece uma vez; nenhum campo antes excluído retorna.
- [ ] Os 12 recursos inventariados usam o componente compartilhado; recursos simples e quadros de execução preservam seu comportamento.
- [ ] Erros de produto, fórmula, componente e management form abrem o painel correto; dados digitados permanecem na resposta.
- [ ] Exclusão não renumera índices; incluir/excluir componente vazio não bloqueia envio válido; transação e auditoria permanecem aprovadas.
- [ ] Sem permissão não há dados de filhos; esconder uma aba nunca substitui autorização no servidor.
- [ ] Teclado, foco, required em aba oculta, overlay, fallback sem JS e quatro larguras têm evidência de navegador.
- [ ] Sem migration ou novas dependências de runtime; lint, sintaxe, testes relevantes e revisão de diff aprovados.
- [ ] Documento técnico atualizado; baseline global separado; nenhuma alegação de release geral verde por causa desta feature.

## Riscos, tradeoffs e perguntas abertas

| Risco / decisão | Tratamento |
|---|---|
| Esconder required quebra validação nativa e pode travar o loader | Captura de submit antes do listener global, abertura do painel e teste real de navegador |
| Renderizar campos duas vezes duplica POST/IDs | Usar uma lista de BoundFields por aba; hidden fields únicos; testes de contagem |
| Formulário de produção tem locks e restrições especiais | Não tocar em POST, `uses_operational_inline_locks` ou no quadro de execução; reexecutar regressões P1 |
| LIMS possui renderer especializado | Manter `qc_grid`; apenas mover o contêiner para uma aba |
| Estilo stacked ocupa mais altura para muitas linhas | Tradeoff deliberado por legibilidade; não adicionar virtualização/paginação de formsets neste trabalho |
| Muitas abas em Riscos | Flex-wrap, rótulos reais e teclado; não converter para wizard |
| Produtos já cadastrados poderiam ser editados sem permissão se embutidos aqui | Aba Produto seleciona a relação; edição do cadastro mestre continua em sua própria tela |
| Alterações anteriores não commitadas | Inspeção de diff e staging por hunk; não juntar commits P1 com apresentação |
| Ambiente de testes/browser pode não estar preparado | Pré-requisito explícito; pedir autorização de setup e não declarar verificação inexistente |

**Pergunta não bloqueante de extensão futura:** se a intenção for editar simultaneamente o cadastro mestre de Produto, ou redesenhar também os cockpits/detalhes, isso precisa de um segundo escopo com autorização, controle de acesso e persistência próprios. Não é requisito implícito deste plano.

## Review Focus

1. **Reenvio inválido e hierarquia de erros** — tarefas 2, 10 e 12: formset non-form error, campos em abas diferentes e erro global do pai devem ativar o painel previsto sem apagar valores.
2. **Herança do contexto** — tarefas 5 e 14: edição e reaproveitamento recebem o mesmo agrupamento, sem reabilitar campos bloqueados.
3. **DELETE de linhas vazias/sem corpo** — tarefas 9 e 13: hidden ID e DELETE preservados; nenhuma operação sobre a linha errada ou mudança de TOTAL_FORMS.
4. **Permissões mínimas de filhos** — tarefa 14: sem dados e sem management form quando indisponível; POST forjado continua proibido.
5. **Falha de JS e overlay** — tarefas 11, 12 e 15: fallback legível, nenhuma mensagem de campo não focável ou overlay travado. Sem evidência de browser, esse item continua aberto.

## Handoff e limite de execução

Plano ainda não aprovado para execução. Após aprovação, manter um único responsável por `resource_form.html`, `inline_stacked.html` e `resource-form-tabs.js`; testes/documentação podem ser delegados em paralelo depois de congelado o contrato de contexto. Commits pequenos somente após GREEN e staging dos hunks desta feature; nenhum push, merge ou deploy implícito.
