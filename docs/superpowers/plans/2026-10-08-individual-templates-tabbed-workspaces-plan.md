# Templates individuais e páginas centrais com abas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar templates centrais individuais com abas para os 22 fluxos da especificação aprovada, permitindo operar pai e itens sem depender dos CRUDs separados.

**Architecture:** Seletor determinístico de templates com fallback, projeções de contexto autorizadas e componentes Bootstrap/Duralux compartilhados. Os 12 agregados atuais preservam formsets e protocolos; os 10 novos recebem configurações explícitas de composição. Consulta, criação e edição de cada agregado usam seu `workspace.html`, preservando rotas e executores de domínio.

**Tech Stack:** Python 3.14, Django 6, Django REST Framework, PostgreSQL, Bootstrap 5, JavaScript, HTML5, CSS3 e Docker. Sem novas dependências de produção.

**Spec:** `docs/superpowers/specs/2026-10-08-individual-templates-tabbed-workspaces-design.md`, aprovada por Rui na revisão interativa desta sessão.

## Global Constraints

- Somente os 22 fluxos declarados na especificação compõem este ciclo.
- Texto e erros em pt-BR; não introduzir ícones decorativos em inputs ou alegações regulatórias novas.
- Preservar permissões, retenção GxP, transações, campos automáticos e locks de produção.
- Não emitir NF-e, baixar estoque, aprovar documentos ou disparar integrações por salvamento genérico.
- Não remover APIs, rotas de CRUD filho ou alterações locais preexistentes.
- Não usar banco, `.env`, cookies ou serviços de produção em testes; não fazer deploy.
- Não inferir composição de qualquer ForeignKey; declarar campos de entrada explicitamente.
- Relações entre filhos novos usam duas gravações na mesma página, sem IDs temporários fictícios.
- Não esconder grupos com JavaScript indisponível; não criar forms aninhados.
- Código antes de teste falhando é proibido; executar ciclos verticais RED → GREEN → REFACTOR.

## Review Focus

- POST de filho pertencente a outro pai: negar sem modificar registros protegidos; teste da Tarefa 2.
- Campo obrigatório em aba inativa: revelar painel e permitir foco/erro, sem travar submit; teste da Tarefa 3.
- Campo/linha adicionado após carregamento: inicializar máscaras uma vez, atualizar formset e contagem correta; teste da Tarefa 3.
- Imposto/evidência referenciando filho novo ou de outro agregado: explicar dependência e negar associação inválida; teste da Tarefa 6.
- Estado terminal ou concorrente em produção: não tornar editável por causa da nova página; regressões da Tarefa 4 e gate da Tarefa 7.

## Estrutura e responsabilidade dos arquivos

| Arquivo | Responsabilidade |
| --- | --- |
| `base/ui/template_selection.py` | Precedência de nomes e mixin para TemplateView |
| `base/ui/resource_workspaces.py` | Projeções de abas/linhas, modo e seleção de erros; sem regra de domínio |
| `base/ui/composites.py` | Lista fechada dos agregados e novas configurações de inlines |
| `base/ui/registry.py` | Campo `workspace_enabled` no fim de ResourceConfig e aplicação das configurações |
| `base/ui/views.py` | Integração com seletor/contexto e proteção dos formsets; preservar persistência existente |
| `base/ui/actions/views.py` | Seleção da página de ação e retorno à central sem duplicar executor |
| `templates/app/resource_workspace.html` | Estrutura central compartilhada nos modos consulta/criação/edição |
| `templates/app/includes/workspace_*.html` | Abas, conteúdo de leitura, resumo de erros e campos |
| `templates/app/<module>/<resource>/workspace.html` | Identidade/introdução/blocos específicos dos 22 fluxos |
| `static/js/resource-workspaces.js` | Aprimoramento de abas, foco e eventos de linhas, sem persistência |
| `static/js/inline-formsets.js` | Adição/exclusão e reinit, extraído dos controladores duplicados |
| `static/js/app-form-enhancements.js` | Inicializador público idempotente dos campos dinâmicos |
| `static/js/resource-actions.js` | Reinit do formulário importado no modal |
| `static/css/app.css` | Abas e barra de ações responsivas com escopo próprio |
| `tests/test_resource_template_selection.py` | Contrato do seletor e fallback |
| `tests/test_resource_workspaces.py` | Contexto, modos, permissões, DOM e matriz dos 22 fluxos |
| `tests/test_composite_workspace_forms.py` | POSTs reais, rollback e vínculos dos novos agregados |
| `tests/test_resource_workspaces_frontend.py` | Contratos do controlador e integração dos assets |
| `tests/workspace_fixtures.py` | Fixtures compartilhadas sem funções `test_*`, evitando coleta duplicada |
| `TEMPLATES.md`, `docs/architecture/templates.md` | Documentação do contrato e limites entregues |

## Tarefa 0: Harness e baseline isolados

**Files:** Artefatos somente em `/home/deploy/.hermes/cache/scratch/rgn-tabbed-workspaces-20261008/`; sem código funcional nesta tarefa.

**Interfaces:** Produz `baseline/` imutável, `candidate/` gravável, `source-manifest.json`, `run-tests.sh` e `evidence/`. O wrapper aceita argumentos de pytest e os encaminha sem alterar filtros. Usa PostgreSQL dedicado, sem porta publicada, e imagem de testes com versões verificadas.

- [ ] Registrar HEAD, status/diff atual e hashes das fontes atuais selecionadas por `git ls-files --cached --others --exclude-standard`; não copiar `.git`, `.env` real, uploads, bancos, caches ou segredos. Preservar exemplos públicos de configuração necessários aos testes. Gerar candidate a partir de baseline, sem modificar baseline. Inicializar um repositório Git separado em candidate e commitar o snapshot de fontes como baseline local; os commits de implementação pertencem somente a esse repositório, nunca incluem alterações de Rui no repositório original.
- [ ] Inspecionar somente mounts dos containers do ERP para confirmar se escrever fonte/estáticos originais alcançaria produção; não promover código não verificado.
- [ ] Verificar pins no runtime. A imagem já consultada `rgnfarmasystem:corrections-clean-tests` contém Django 6.0.8, pytest 9.1.1, pytest-django 4.14.0 e ruff 0.15.21. Comparar também os demais pins realmente usados; diferença bloqueia evidência de release, não deve ser ocultada.
- [ ] Criar rede Docker privada/internal, PostgreSQL `postgres:15-alpine` com armazenamento descartável e credencial efêmera, e container de testes sem Docker socket. Iniciar pela entrypoint Python, nunca pelo entrypoint de produção. Montar candidate somente leitura e evidências como volume gravável. Não herdar variáveis externas ao allowlist.
- [ ] Gerar o wrapper `run-tests.sh` que define banco isolado, configurações `core.settings.test`, cache/arquivos temporários em scratch e encaminha `"$@"`. Manter migrations; `--reuse-db` apenas dentro deste harness, sem substituir o gate final com `--nomigrations`.
- [ ] Executar baseline: `run-tests.sh tests/test_template_language.py tests/test_app_ui.py tests/test_formula_inline_components_ui.py tests/test_action_frontend.py -q`. Guardar exit status e JUnit; distinguir falha preexistente de falha da tarefa. Verificar ausência de `.env` real na cópia e impedir conexão a hosts de produção.

## Tarefa 1: Seleção de templates com fallback

**Files:** Create `base/ui/template_selection.py`; modify `base/ui/registry.py`, `base/ui/views.py`, `base/ui/actions/views.py`; test `tests/test_resource_template_selection.py`.

**Interfaces:**
- `resource_template_names(module_slug: str, resource_slug: str, view_kind: str, generic_template: str, *, workspace_enabled: bool = False, action_name: str = '') -> list[str]`.
- `ResourceTemplateMixin.get_template_names() -> list[str]`, consumindo `get_module()`, `get_resource()`, `template_kind` e `template_name` existentes.
- Acrescentar `workspace_enabled: bool = False` ao fim de `ResourceConfig`, sem alterar os argumentos posicionais atuais.

- [ ] RED: `test_resource_template_precedes_module_and_generic` usa loader real e templates em memória para confirmar recurso > módulo > genérico. `test_workspace_enabled_uses_same_workspace_for_detail_and_form` exige seleção de `app/production/orders/workspace.html` nos dois modos. Executar `run-tests.sh tests/test_resource_template_selection.py -q` e observar falha pelo seletor ausente.
- [ ] GREEN: implementar lista de candidatos controlada pelo servidor. Para workspace em consulta/form, priorizar workspace do recurso, do módulo e compartilhado; em recursos comuns priorizar arquivo do recurso/tipo, módulo/tipo e genérico. Listagem/exclusão não viram workspace. Views validam module/resource antes do seletor.
- [ ] RED/GREEN adicional: `test_invalid_post_keeps_selected_template`, `test_unknown_template_query_parameter_is_ignored`, `test_action_error_uses_same_action_template`; cobrir os três pontos de `render()` da action view e preservar o callback DRF.
- [ ] Rodar testes novos e baseline da Tarefa 0. Registrar diff contra baseline. Não habilitar workspaces antes de sua implementação.
- [ ] Commit local da Tarefa 1: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 2: Contexto central e proteção dos agregados

**Files:** Create `base/ui/resource_workspaces.py`; modify `base/ui/views.py`; test `tests/test_resource_workspaces.py`, fixtures em `tests/workspace_fixtures.py`.

**Interfaces:**
- `build_workspace_context(request, resource, *, obj=None, form=None, inline_formsets=(), mode: str = 'detail', active_tab: str = 'general') -> dict`.
- Projeção `ResourceWorkspaceTab` com `key`, `title`, `tab_id`, `panel_id`, `available`, `count`, `has_errors`, `inline`, `rows`; `rows` são valores autorizados de leitura.
- Chaves de contexto: `workspace_mode`, `workspace_tabs`, `active_workspace_tab`, `workspace_has_errors`; reutilizar `module`, `resource`, `object`, `form` e flags existentes.
- `scope_inline_formset(formset, *, request, resource, inline, parent) -> None` restringe IDs e relações entre irmãos; não altera permissões do usuário.

- [ ] RED: `test_read_workspace_filters_child_rows_and_counts_by_permission`, `test_invalid_form_selects_general_tab`, `test_invalid_inline_selects_its_tab`, `test_untrusted_active_tab_falls_back_to_general`. Executar arquivo específico; falha deve indicar o contexto novo ausente.
- [ ] GREEN: implementar projeções em função sem consultar fontes não autorizadas. Leitura usa campos explicitamente configurados em inline e queryset autorizado, não `object.related_set.all` no template. Contagem exclui linhas extras/deletadas e não cria dados em GET.
- [ ] RED/GREEN: `test_post_rejects_foreign_child_id_without_reassignment` exige snapshots persistidos idênticos; `test_parent_failure_rolls_back_valid_child`; `test_child_without_change_permission_is_rejected`; `test_hidden_or_server_fields_cannot_be_posted_as_editable`. Restringir PK hidden ao queryset do pai e relações entre irmãos ao mesmo pai. Manter auditoria intencional fora de assertions de zero escrita de domínio.
- [ ] Integrar helper a detalhe/criação/edição somente com `workspace_enabled`; preservar ordenação dos locks, validação, ModelForm e transações atuais. Rodar novas proteções e regressões de fórmulas/produção antes de seguir.
- [ ] Commit local da Tarefa 2: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 3: Shell central, abas acessíveis e campos dinâmicos

**Files:** Create `templates/app/resource_workspace.html`, `templates/app/includes/workspace_tabs.html`, `workspace_readonly.html`, `workspace_fields.html`, `workspace_error_summary.html`, `static/js/resource-workspaces.js`, `static/js/inline-formsets.js`; modify templates genéricos e execução, includes de inlines, CSS, form enhancements, resource actions; tests `tests/test_resource_workspaces_frontend.py`.

**Interfaces:**
- `window.RGNForms.initialize(root = document)` liga máscaras/validação/CEP uma vez por campo/form.
- `window.RGNResourceWorkspace.initialize(root = document)` aprimora abas somente após controladores disponíveis.
- Evento `rgn:inline-added` publica o novo contêiner; modal chama os inicializadores após `document.importNode`.
- Atributos `data-resource-workspace`, `data-workspace-tab`, `data-workspace-panel` identificam o controlador. Preservar todos os `data-inline-formset-*` existentes.

- [ ] RED: DOM renderizado exige um form sem nesting, management forms e erros acessíveis em consulta/form. `test_workspace_tabs_have_unique_aria_ids`, `test_qc_grid_renders_row_non_field_errors`, `test_generic_fallback_preserves_existing_controls`; observar falha de markup antes de editar HTML.
- [ ] GREEN: criar shell e includes, abrindo blocos pequenos nos genéricos. Reusar referência Duralux sem copiar CSS de mega-menu. Renderizar Dados gerais + grupos autorizados, toolbar/cancel/ações existentes e avisos de dependência entre filhos.
- [ ] RED/GREEN frontend: controlador mantém painéis visíveis sem JS, ativa erro/aba válida, implementa teclado e revela painel em evento `invalid` capture antes de foco. Inicializador é idempotente, adição é localizada ao formset correto e exclusão marca `DELETE`.
- [ ] Extrair lógica de inlines duplicada somente depois de testes do comportamento; atualizar testes que hoje procuram código dentro do HTML para conferir asset/execução equivalente. Conservar lógica de estados de resultados QC e `block.super`.
- [ ] CSS responsivo: abas em contêiner horizontal, tabelas responsivas e barra de ações sem overflow da página. Nenhuma regra deve esconder conteúdo sem flag de aprimoramento confirmada.
- [ ] Executar as provas de navegador da Tarefa 7 para campo inválido em aba inativa, máscaras em linha nova, clique único sem duplicação, teclado e JS desativado. Não aceitar somente grep em código JS como prova de comportamento.
- [ ] Commit local da Tarefa 3: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 4: Habilitar os 12 fluxos existentes

**Files:** Create `base/ui/composites.py` e os 12 `templates/app/<module>/<resource>/workspace.html` da seção 4.1 da spec; modify registry; tests da matriz central e regressões existentes.

**Interfaces:** `COMPOSITE_WORKSPACE_KEYS: tuple[tuple[str, str], ...]` é a lista fechada dos 22 pares. `configure_composite_resources(modules: tuple) -> tuple` usa `dataclasses.replace` e preserva recursos/flags atuais. Pode usar TYPE_CHECKING e import local de tipos para evitar ciclo com registry.

- [ ] Para cada um dos 12 pares da spec, fazer um ciclo parametrizado RED/GREEN: `test_existing_composite_uses_individual_workspace[module-resource]` exige template individual, contexto e grupos existentes, com apresentação própria de domínio em bloco curto. Não criar 12 cópias do shell.
- [ ] Habilitar os pares existentes e criar os templates com introdução/ordem pertinentes ao domínio. Não alterar os campos de seus inlines ou protocolos de persistência só para adequar o visual.
- [ ] `test_production_new_workspace_does_not_enable_operational_children`, `test_production_terminal_children_remain_disabled`, `test_formula_reuse_preserves_source_and_components`, `test_document_central_save_does_not_approve`; preservar mapas, viewer e executores autorizados.
- [ ] Rodar os 12 casos e suites de fórmula, produção, documentos, desvios, CAPA, riscos, recall, auditorias e qualidade. Manter checklist por par e distinguir bloqueio preexistente de regressão.
- [ ] Commit local da Tarefa 4: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 5: Integrar composições adicionais simples

**Files:** Modify `base/ui/composites.py`; create workspace individual para routes, schedules, requisitions, rfqs, proposals, orders, reviews e dashboards; tests `tests/test_composite_workspace_forms.py` e fixtures.

**Interfaces:** Novos `InlineResourceConfig` têm key única por pai, child model, parent FK, campos de entrada explícitos, labels pt-BR e apresentação tabular/stacked conforme largura. Associações referenciais permanecem seletores, não criação automática de cadastros.

- [ ] Fazer RED/GREEN separado por par: `test_create_<flow>_with_multiple_children_in_one_post` envia pai e dois filhos e exige vínculo correto; `test_update_<flow>_keeps_children_in_central_page` exige modo/template e persistência. Cobrir os oito pares, sem somar casos coletados como testes executados.
- [ ] Configurar relações exatas: routes/steps (`route`), schedules/mps-lines (`schedule`), requisitions/requisition-items (`requisition`), rfqs/supplier-quotations (`rfq`), proposals/proposal-items (`proposal`), crm orders/order-items (`order`), qa reviews/checklist-items (`review`), dashboards/widgets (`dashboard`).
- [ ] Em cada ciclo, conferir campos dos modelos/serializers atuais e escrever allowlist no código; excluir ator, pai, totais derivados, timestamps e estados de decisão. Não construir essa lista automaticamente a partir de todos os fields editáveis.
- [ ] Rodar caso válido, filho inválido com rollback e POST sem permissão para cada par, incluindo estados terminais quando definidos pelo domínio. Preservar estado/transições de RFQ/QA e totais comerciais de serviço.
- [ ] Commit local da Tarefa 5: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 6: Fiscal e mudanças, com dependências e estados controlados

**Files:** Modify composites/context/formset protection; create `templates/app/fiscal/documents/workspace.html`, `templates/app/changes/controls/workspace.html`; tests de POST composto, fiscal e mudanças.

**Interfaces:** Documentos fiscais usam FiscalDocumentItem.document e FiscalTax.document; FiscalTax.item é restrito aos itens persistidos do mesmo documento. Mudanças usam os cinco filhos listados na spec e FK `change`.

- [ ] RED: `test_create_fiscal_document_with_items_does_not_emit_or_post_stock`, `test_tax_cannot_reference_another_document_item`, `test_new_sibling_reference_requires_save_first`. Exigir documento/itens persistidos, ausência de efeitos operacionais e mensagem sobre vínculo após salvar.
- [ ] GREEN: configurar campos de entrada fiscal, itens e impostos; associar dependentes somente a irmãos persistidos. Manter cálculos/validações existentes, sem apresentar totais estimados no frontend como totais oficiais.
- [ ] RED/GREEN para mudanças: `test_create_change_with_owned_children_atomically`, `test_change_assignment_does_not_record_approval_or_complete_action`, `test_invalid_stock_assessment_rolls_back_aggregate`. Criar allowlists de planejamento/avaliação que não exponham decisões executadas por actions.
- [ ] Rodar regressões fiscais/de compras/conferência e changes; executar associação válida na segunda gravação da mesma página. Confirmar que nenhum teste usa provedor fiscal, SMTP, impressora ou ledger real.
- [ ] Commit local da Tarefa 6: no Git de candidate, adicionar somente os arquivos desta tarefa e commitar após GREEN; guardar hash e diff contra o snapshot. Não commitar código funcional no repositório original, cuja árvore contém trabalho preexistente.

## Tarefa 7: Gate integrado, revisão e aplicação segura

**Files:** Documentation e evidências; nenhuma publicação de serviço.

**Interfaces:** `evidence/results.json` registra hashes, comandos, exit codes, contagens JUnit, falhas preexistentes, exclusões e browser checks. A promoção local exige que o original ainda corresponda ao baseline dos arquivos alterados.

- [ ] Verificar matriz dos 22 pares: template individual existe, rotas reversas válidas, grupos e permissões esperados; não considerar wrappers existentes como prova de POST funcional.
- [ ] Rodar `run-tests.sh tests/test_resource_template_selection.py tests/test_resource_workspaces.py tests/test_composite_workspace_forms.py tests/test_resource_workspaces_frontend.py -q`, seguido das suites afetadas e da suite completa viável em harness sem Docker socket. Manter migrations. Se alguma integração real for incompatível com isolamento, identificar teste/exclusão explicitamente, sem afirmar release aprovado.
- [ ] Executar `python manage.py check` e `ruff check` com configuração/versão do projeto. Compilar todos os templates. Comparar pinned dependencies e guardar a distinção entre runtime reutilizado e build limpo.
- [ ] Criar dados/sessão sintéticos no PostgreSQL isolado e executar servidor temporário somente em loopback numa porta livre, sem usar conta real. Usar Chrome headless/CDP ou browser tool, com perfil efêmero em scratch. Verificar fórmula e ao menos um fluxo novo de itens, erro em aba inativa, POST válido/invalid, add/delete, máscara dinâmica, teclado, sem JS, 390px e desktop. Medir scrollWidth e confirmar persistência no banco sintético. Guardar resultados e HTML/screenshot quando úteis; nunca inventar resultados não executados.
- [ ] Congelar candidate e solicitar revisão independente de código/segurança com a spec, o plano e diff contra baseline. Corrigir achados via RED/GREEN e repetir os gates afetados.
- [ ] Atualizar `TEMPLATES.md` e `docs/architecture/templates.md`; reportar explicitamente os dois passos necessários para referência entre filhos e os agregados fora do ciclo.
- [ ] Comparar hashes de arquivos originais com baseline; conflito bloqueia overwrite. Aplicar somente arquivos aprovados da tarefa, mantendo owner/permissões de cada arquivo e sem modificar configurações globais. Não reiniciar/deployar serviços. Não incluir alterações preexistentes em commits da tarefa.
- [ ] Reconciliar contagens/IDs por código, ler exatamente os arquivos/alvos aplicados e confirmar diff final. Remover containers/rede temporários da tarefa e entregar relatório curto do que funciona, testes reais e limites remanescentes.

## Revisão do plano e método

O plano preserva a especificação aprovada: 12 fluxos existentes e 10 adicionais, mesma página central, abas funcionais/acessíveis, segurança e isolamento. Todos os cinco Review Focus têm casos atribuídos às tarefas responsáveis. Interfaces são únicas e o registro não é reestruturado fora do necessário.

Recomendação de execução: **Native**, porque seletor, contexto, formsets e controladores compartilham interfaces estreitas e o repositório contém alterações preexistentes; um implementador central reduz conflitos. Ao congelar o candidato, uma revisão independente cobre o diff integrado. **Subagent-driven** permanece disponível com revisão por tarefa, ao custo de mais contextos e handoffs.

Aguardar revisão deste plano e escolha do método antes de código funcional.
