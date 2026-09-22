# Templates operacionais

A UI operacional usa uma experiência single-instance em `/app/`, sem seleção de
escopo por cliente. O objetivo é oferecer navegação por módulo, CRUD HTML,
permissões Django e testes automatizados sem substituir as APIs REST nem o
Django Admin.

## Página inicial e workspaces

Usuários autenticados que acessam `/` são redirecionados para `/app/`, o
catálogo dinâmico de módulos permitido ao perfil. A home não mantém um catálogo
estático paralelo.

Os cockpits de operação, qualidade e workflow usam configurações imutáveis
`WorkspaceConfig` em `base.ui.workspaces` e uma única apresentação em
`templates/workspaces/workspace.html`. As configurações fornecem textos,
métricas, tons, ícones e URLs já resolvidas. A view filtra módulos, cartões e
atalhos no servidor antes da renderização.

### Contratos do design system operacional

Os componentes compartilhados recebem projeções imutáveis de
`base.ui.presentation`; eles não consultam o banco, não calculam regras de
negócio e não constroem URLs a partir de dados livres.

Todo texto visível deve usar português do Brasil com acentuação correta.

- `ProgressMetric` alimenta o cartão de indicador com `label`, `value`, `icon`,
  `tone`, `badge`, `url`, `target`, `helper` e `required_permission`. A meta só
  deve ser informada quando houver denominador real e autorizado. Sem meta
  positiva, o cartão permanece simples; com meta, o percentual é limitado de
  0% a 100% e exposto por barra e atributos ARIA. A view ou o workspace é dono
  da verificação de `required_permission`. Estado vazio do conjunto: “Nenhum
  indicador disponível”.
- `DeadlineItem` representa um prazo já autorizado com `title`, `description`,
  `due_at`, `tone`, `icon` e `url`. `build_workspace_deadlines` verifica a
  permissão `view` de cada fonte, restringe tarefas e notificações ao usuário e
  aplica ordenação e limite antes da renderização. Estado vazio: “Nenhum prazo
  operacional encontrado.”
- `advanced_filter_fields` é a lista permitida de campos em `ResourceConfig`.
  Somente choices e datas/datas-horas declaradas entram no `QuerySet`; chaves
  livres nunca viram lookups Django. A view é dona da validação e publica os
  parâmetros autorizados para paginação e exportação. Sem configuração, o
  painel avançado não é exibido; uma data inválida permanece visível para
  correção, mas não filtra a consulta.
- `NotificationPreview` projeta `title`, criticidade, origem, tom, ícone,
  `created_at`, estado de leitura e URL de detalhe. O context processor só
  consulta `WorkflowNotification` após confirmar acesso ao workspace e
  `workflow.view_workflownotification`, sempre com
  `recipient=request.user`, ordenação recente e limite de cinco. Estado vazio:
  “Nenhuma notificação recente.”
- `StatusPresentation` mantém o rótulo original e associa `tone` e `icon` por
  `resolve_status`. Cor nunca é a única indicação: o componente apresenta texto
  e ícone semântico. Valores desconhecidos usam apresentação neutra, sem
  inventar um estado de negócio.
- `AuditEntry` normaliza `occurred_at`, ator, ação, detalhes, motivo e
  `StatusPresentation` para leitura. A view só ativa a consulta quando o recurso
  declara `audit_trail`; `base.ui.audit.get_audit_entries` usa fontes
  persistidas, ordena do evento mais recente e limita a 25. Estado vazio:
  “Nenhum evento de auditoria disponível para este registro.”

O mesmo template inclui `deadline_list.html`, alimentado por `DeadlineItem` e
`build_workspace_deadlines`. Cada fonte é consultada somente após a permissão
`view` correspondente: ordens de produção ativas, itens pendentes de checklist
QA e, no workflow, tarefas atribuídas ao usuário e notificações não arquivadas.
Os prazos são ordenados por vencimento antes do limite e apontam para detalhes
reais autorizados.

As rotas nomeadas `app:operations_workspace`, `app:quality_workspace` e
`app:workflow_workspace` permanecem estáveis. Novos workspaces devem ser
registrados no mesmo contrato, com teste de acesso ao módulo, visibilidade dos
itens e escopo das consultas.

### Navegação de workspaces

`WorkspaceConfig` é também a fonte de verdade para o sidebar e os atalhos do
cabeçalho. Todo workspace navegável declara `route_name`, `navigation_label`,
`icon` e `order`. O context processor publica somente configurações autorizadas
em `sidebar_workspaces`; os templates não mantêm listas paralelas nem exibem
links não autorizados.

Ao adicionar um workspace, registre esses metadados, associe um `module_slug`
válido e cubra: URL reversa, ordenação, visibilidade por permissão, estado
`aria-current` e ausência do item para perfis sem acesso.

### Minha área

A rota nomeada `app:personal_area` (`/app/minha-area/`) apresenta somente filas
relacionadas explicitamente ao usuário autenticado. `base.ui.personal_area`
consulta cada fonte depois de confirmar sua permissão `view` e limita os itens
antes da renderização. Aprovações usam `assigned_to`, notificações usam
`recipient`, desvios usam `responsible`, CAPAs usam `owner` e treinamentos usam
`user`.

`templates/app/personal_area.html` recebe apenas `PersonalAreaSection` e
`PersonalAreaItem`; o template não consulta models, não amplia escopos e não
oculta exceções. Se uma seção autorizada não tiver registros, exibe seu estado
vazio específico. Se nenhuma seção estiver autorizada, explica que as
atividades aparecerão conforme permissões e responsabilidades.

### Busca global e paleta de comandos

O endpoint nomeado `app:global_search` pesquisa somente recursos presentes em
`get_visible_modules(user)` e sempre parte de `ResourceConfig.get_queryset`,
preservando escopos por usuário antes de aplicar os campos declarados em
`search_fields`. Consultas exigem ao menos três caracteres, retornam no máximo
vinte itens e limitam cada recurso a cinco resultados.

`static/js/global-search.js` usa debounce, cancela a requisição anterior e
insere textos com `textContent`. A busca permite setas, Enter e Escape, expõe
estados de carregamento, vazio e erro em uma região `aria-live` e não exige
cabeçalho AJAX como controle de acesso.

A paleta `Ctrl+K`/`⌘K` não possui catálogo paralelo. Ela indexa somente links
com `data-command-label` e `data-command-url` já renderizados pelo sidebar
permissionado. Assim, a ausência de um link autorizado implica também ausência
do comando correspondente; as views continuam sendo a fronteira defensiva ao
receber acesso direto.

### Cockpits operacionais especializados

- **Ciclo de Abastecimento da Fórmula (`app:master_formula_cockpit`):**
  Disponível no detalhe de `MasterFormula` (`/app/formulations/formulas/<id>/cockpit/`).
  Consolida a visão operacional do ciclo de vida em quatro abas Duralux:
  1. *Formulação e BOM*: Matérias-primas, quantidades e perdas previstas.
  2. *Orçamentos e Cotações*: RFQs e propostas de fornecedores para os insumos.
  3. *Pedidos de Compra*: Ordens de compra emitidas para atender a fórmula.
  4. *Recebimento e Lotes*: Entradas físicas e fiscais com status de qualidade e lote.
  Cada aba verifica permissões granulares no servidor e mantém o sincronismo de navegação via hash da URL.

## Regras

- Menus usam permissões `view` dos models.
- Botões de criação, edição e exclusão usam `add`, `change` e `delete`.
- Formulários não expõem campos preenchidos pelo sistema, trilhas de auditoria,
  hashes ou timestamps técnicos.
- Listagens preservam filtros, ordenação, paginação e exportação CSV.
- Telas de detalhe exibem badges semânticos para status, criticidade e severidade.
- Relações 1-N prioritárias devem ser editadas no formulário principal com
  transação atômica.

## Como adicionar novos recursos ao CRUD HTML generico

1. Registre o model em `base.ui.registry` com `ResourceConfig`, título, ícone,
   campos de listagem, `form_fields` e permissões esperadas. Quando a edição
   precisar expor um conjunto mais restrito, declare `update_form_fields`; a
   fórmula mestra mantém `copied_from` como rastreabilidade persistida, mas não
   o oferece no formulário de alteração.
2. Garanta que o usuário possua permissões Django `view`, `add`, `change` e
   `delete` conforme a ação desejada.
3. Use validações de model e serializer já existentes; não duplique regra de
   negócio no template.
4. Para relações 1-N, configure inline formsets no recurso pai e salve tudo em
   transação.
5. Adicione testes de listagem, detalhe, criação, edição, exclusão e visibilidade
   dos botões por permissão.

Recursos com reaproveitamento declaram `reuse_route_name` e
`reuse_permissions` no `ResourceConfig`. O template apenas renderiza a rota
autorizada; a view repete as permissões, controla campos de rastreabilidade e
não persiste dados no GET.

Campos derivados, hashes, timestamps técnicos e trilhas de auditoria devem
ficar fora de `form_fields` ou ser marcados como `read_only=True` quando
precisarem aparecer em detalhe/API.

## Como publicar uma nova ação operacional

Uma futura `@action(detail=..., methods=['post'])` deve continuar usando o DRF
como executor único. Para disponibilizá-la na interface:

1. Adicione `(resource_slug, action_name)` a `ACTION_KEYS` do app em
   `base/ui/actions/modules/`.
2. Declare o payload em `FIELD_SPECS`, com tipo, obrigatoriedade, limites,
   choices do model/serializer e queryset de relações autorizado.
3. Se o método restringir o estado de origem, registre o campo e os valores em
   `RESTRICTED_ACTION_STATES`; ações com ciclo de vida sem guard recebem todos
   os valores do `TextChoices`.
4. Adicione o texto visível em `ACTION_LABELS`, sempre em pt-BR e sem fallback
   em inglês. Configure confirmação para operações críticas.
5. Execute `test_html_catalog_exactly_matches_post_actions` e os testes do
   domínio. A igualdade deve permanecer em 258/258 até que uma nova ação seja
   aprovada e altere deliberadamente essa cardinalidade.

Não concatene URL, não replique a regra de negócio no template e não chame o
model diretamente pela view HTML.

## Verificação

```bash
TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test \
DJANGO_SETTINGS_MODULE=core.settings.test \
.venv/bin/pytest tests/test_app_ui.py tests/test_formula_inline_components_ui.py -q
```
