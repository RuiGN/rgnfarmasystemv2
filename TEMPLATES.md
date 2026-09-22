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

- **Cockpit da Ordem de Produção / e-Batch Record (`app:production_order_cockpit`):**
  Disponível no detalhe de `ProductionOrder` (`/app/production/orders/<id>/cockpit/`).
  Consolida a execução industrial e o prontuário eletrônico da batelada em seis abas Duralux:
  1. *Ficha e planejamento*: Identificação do processo, fórmula, roteiro, linha, cronograma e auditoria do ciclo de vida.
  2. *Materiais e pesagem*: BOM de produção alocado, pesagens reais, perdas e lotes de insumos.
  3. *Fases e mão de obra*: Sequência de operações, centros de trabalho, duração planejada vs. real e apontamento de operadores.
  4. *Controle em processo (IPC)*: Amostras de qualidade colhidas, ensaios laboratoriais e laudos analíticos.
  5. *Desvios e ocorrências*: Eventos de qualidade, severidade, criticidade e status de investigação da batelada.
  6. *Rendimento e custos*: Entradas de produto acabado em quarentena, conciliação teórica vs. real e apropriação de custos de produção.
  Cada aba aplica segregação de deveres (SoD) no servidor, protegendo dados restritos de qualidade e custos contra acessos não autorizados.

- **Cockpit de Liberação de Lote e Dossiê QA (`app:qa_lot_release_cockpit` / `app:stock_lot_dossier`):**
  Disponível no detalhe de `LotRelease` (`/app/qa/lot-releases/<id>/cockpit/`) e no detalhe de `StockLot` (`/app/inventory/lots/<id>/dossier/`).
  Consolida a liberação sanitária e a revisão de batch record em cinco abas Duralux:
  1. *Lote, saldos e genealogia*: Metadados do lote, validade, alertas de expiração, endereçamento físico e saldos detalhados, rastreabilidade montante (insumos consumidos) e jusante (lotes derivados).
  2. *Controle de qualidade e laudos*: Amostras laboratoriais, ensaios físico-químicos e microbiológicos com status de conformidade (OOS/OOT) e Certificados de Análise (CoA) emitidos.
  3. *Revisão do batch record*: Prontuário de revisão QA, percentual de conclusão e checklist normativo de BPF com referências documentais de evidência e conclusão de itens.
  4. *Bloqueios e desvios*: Bloqueios sanitários ativos (Quality Blocks) e eventos de não-conformidade/desvios da batelada com alertas preventivos de risco.
  5. *Decisão e liberação (ALCOA+)*: Matriz de prontidão regulatória sanitária com validação automática de pré-requisitos, parecer técnico registrado com trilha de auditoria e botões diretos de transição de estado (`approve`, `block`, `reject`, `unblock`).
  Cada aba aplica segregação de deveres (SoD) com avisos contextuais para permissões não concedidas.

- **Cockpit de Gestão de Desvio, Investigação e CAPA (`app:quality_event_cockpit`):**
  Disponível no detalhe de `QualityEvent` (`/app/deviations/events/<id>/cockpit/`).
  Consolida a gestão 360° de ocorrências, metodologia de causa raiz e ações corretivas em cinco abas Duralux:
  1. *Notificação e contenção*: Descrição detalhada da ocorrência, severidade, criticidade, quarentena/bloqueio do lote envolvido com link direto para o dossiê do lote, evidências documentais com hash ALCOA+ e vínculos transversais.
  2. *Investigação e causa raiz*: Metodologia técnica Ishikawa e 5 Porquês, apuração de causas imediatas e fundamentais, conclusões de impacto e conclusão técnica com fluxo direto de encerramento de investigação.
  3. *Avaliação de impacto*: Matriz regulatória nos 8 eixos de conformidade sanitária (Qualidade do produto, Segurança sanitária, Eficácia cosmética, Assuntos regulatórios / ANVISA, Consumidor / Paciente, Estoque e quarentena, Custos e perdas, Prazo operacional) e sumário técnico formalizado.
  4. *Planos de ação (CAPA)*: Vínculo unificado com planos `CapaRecord`, resumo executivo de progresso percentual, detalhamento de ações corretivas e preventivas com responsáveis, prazos, exigência de evidência e conclusão direta.
  5. *Aprovações e fechamento*: Workflow de assinaturas multidisciplinares SoD (Garantia da Qualidade, Controle de Qualidade, Produção, Assuntos Regulatórios, Área Responsável), verificações de eficácia dos planos CAPA, checklist regulatório de prontidão (4 gates) e encerramento sanitário formal do evento.
  Cada aba aplica segregação de deveres (SoD) no servidor, protegendo o acesso de acordo com as permissões atribuídas.

- **Cockpit Comercial Order-to-Cash (`app:sales_order_cockpit`):**
  Disponível no detalhe de `SalesOrder` (`/app/crm/orders/<id>/cockpit/`).
  Consolida a jornada comercial completa de ponta a ponta em cinco abas Duralux:
  1. *Pedido e itens comerciais*: Itens do pedido com preços, descontos, subtotais e totais líquidos, dados completos de entrega e logística, propostas, contratos e observações comerciais.
  2. *Análise de crédito e limites*: Limites de crédito aprovados, exposição financeira em aberto, margem disponível antes e após comprometer o pedido, conformidade de travas comerciais e regulatórias (AFE ANVISA/compliance).
  3. *Reserva e estoque (WMS)*: Conferência de atendimento físico por item com saldo aprovado em almoxarifado, detalhamento por lote, armazém e endereço de armazenagem, além do histórico de reservas e movimentações vinculadas.
  4. *Faturamento e NF-e*: Documentos fiscais eletrônicos associados (modelo 55), status de autorização SEFAZ, chave de acesso, protocolo, destaque de tributos e valor total faturado.
  5. *Títulos financeiros e baixas*: Contas a receber geradas pelo pedido, histórico de baixas e liquidações financeiras (PIX, boleto, transferência) e régua de prontidão Order-to-Cash (5 Gates).
  Cada aba aplica segregação de deveres (SoD) no servidor, protegendo o acesso a crédito, estoque, documentos fiscais e finanças conforme as permissões do usuário.

- **Cockpit de Cosmetovigilância, Reclamações de Mercado e Recolhimento (`app:market_complaint_cockpit`):**
  Disponível no detalhe de `MarketComplaint` (`/app/recalls/complaints/<id>/cockpit/`).
  Consolida a segurança pós-mercado, investigação técnica e gestão sanitária de recall em cinco abas Duralux:
  1. *Notificação e triagem clínica*: Identificação da ocorrência, canal/fonte notificante, cliente/consumidor, produto, lote fabril vinculado ao dossiê, pedido de venda e NF-e de origem, relato do evento adverso e protocolos de triagem clínica.
  2. *Amostroteca e investigação analítica*: Amostra de contraprova colhida e retida, ensaios laboratoriais físico-químicos e microbiológicos (CQ), desvios/não-conformidades do lote fabril e parecer técnico da investigação.
  3. *Devoluções e quarentena*: Devoluções pós-mercado e logística reversa com quantidades solicitadas e recebidas, destinação física (quarentena, destruição, retrabalho), notas de inspeção, saldos em estoque e bloqueios de qualidade ativos (Quality Blocks).
  4. *Recolhimento e clientes impactados*: Campanhas de recall formal/voluntário, gatilho, data de decisão e prazo-alvo, mapa de clientes/distribuidores impactados pela batelada (rastreabilidade comercial direta), taxa de recuperação percentual e comunicações aos clientes/autoridades com hash ALCOA+.
  5. *Dossiê regulatório ANVISA e eficácia*: Protocolo de notificação à autoridade sanitária (ANVISA), relatórios de efetividade e rastreabilidade, planos de ação corretiva e preventiva (CAPA) com responsáveis e prazos, além de checklist regulatório sanitário de encerramento.
  Cada aba aplica segregação de deveres (SoD) no servidor, restringindo a visualização de ensaios analíticos, devoluções, recall, clientes impactados e CAPA conforme as permissões atribuídas.

- **Cockpit de Homologação e Qualificação de Fornecedores (`app:supplier_cockpit`):**
  Disponível no detalhe de `BusinessPartner` (`/app/masters/partners/<id>/cockpit/`).
  Consolida a governança do ciclo de vida de fornecedores, conformidade regulatória e desempenho de abastecimento em cinco abas Duralux:
  1. *Dados cadastrais e licenças sanitárias (AFE/VISA)*: Identificação cadastral completa, dados fiscais (CNPJ/IE), endereço normalizado (UF, Cidade e CEP), licenças sanitárias e autorizações de funcionamento vigentes (AFE ANVISA), histórico de bloqueios cautelares da Garantia da Qualidade (QA) e restrições ativas de compras.
  2. *Auditorias de fornecedor BPF*: Programas e planos de auditoria técnica (BPF / ISO 22716), relatórios emitidos com índice percentual de conformidade, apontamentos de auditoria (findings) categorizados por criticidade (crítico, maior, menor), prazos, responsáveis e vínculos de achados.
  3. *Histórico de entregas e OOS no recebimento*: Pedidos de compra e recebimentos físicos de insumos com chave NF-e, laudos do Controle de Qualidade (CQ), amostras analíticas de entrada, taxa de aceitação de lotes (IQF) e investigações laboratoriais de resultados fora de especificação (OOS/OOT).
  4. *Matérias-primas homologadas*: Matérias-primas, embalagens e excipientes associados ao fornecedor com exigência de qualificação sanitária prévia, histórico de quantidades recebidas e aceitas, última entrega, bloqueios por item e propostas comerciais / cotações de fornecedor (RFQs).
  5. *Scorecard e status de qualificação*: Parecer geral regulatório e sanitário (Apto para fornecimento, Qualificação vencida, Fornecimento bloqueado), indicadores consolidados de fornecimento e checklist formal dos 5 Gates de Qualificação Sanitária ANVISA/BPF.
  Cada aba aplica segregação de deveres (SoD) no servidor, restringindo a visualização de auditorias, compras/recebimentos, ensaios de CQ e matérias-primas conforme as permissões de cada perfil.

- **Cockpit de Gestão de Documentos Controlados e Treinamentos (`app:controlled_document_cockpit`):**
  Disponível no detalhe de `ControlledDocument` (`/app/documents/controlled-documents/<id>/cockpit/`).
  Consolida a gestão do ciclo de vida documental, matriz de capacitação e conformidade BPF em cinco abas Duralux:
  1. *Metadados e conteúdo do procedimento (SOP)*: Ficha técnica documental com código, versão, vigência inicial, validade sanitária, responsável, controle de ciclo e assinaturas (elaborador, revisor, aprovador, publicador), histórico e justificativa formal de mudança (ALCOA+), visualização do conteúdo textual do procedimento e anexos documentais com hash criptográfico de integridade.
  2. *Matriz de treinamentos requeridos por cargo*: Mapeamento da matriz de capacitação vinculando o procedimento a cargos, funções operacionais e competências, referências regulatórias (RDC ANVISA 48/2013 e ISO 22716), periodicidade/validade em dias, nota de corte para aprovação, flags de obrigatoriedade, exigência de avaliação e bloqueio operacional automático de atividades sem treinamento prévio.
  3. *Colaboradores treinados e provas de eficácia*: Indicadores executivos de taxa de capacitação (compliance rate), média de notas, relação de colaboradores inscritos com status do treinamento (aprovado, realizado, em andamento, reprovado, vencido), datas de realização, notas obtidas, emissão de certificados com número e referência, validade da qualificação e hash de evidência ALCOA+.
  4. *Histórico de revisões e assinaturas*: Pareceres técnicos e assinaturas eletrônicas formalizadas de revisores e aprovadores com papéis definidos e comentários, linhagem completa de revisões do documento (predecessores e sucessores) e avaliações formais da Garantia da Qualidade (QA Reviews).
  5. *Distribuição controlada, vínculos e trilha de auditoria*: Scorecard com veredito regulatório dos 5 Gates de Prontidão Sanitária DMS (Elaboração e Metadados, Ciclo de Aprovação, Vigência Ativa, Matriz de Capacitação, Eficácia e Bloqueios QA), alertas de bloqueios cautelares QA, distribuição de cópias controladas com confirmação formal de leitura pelo destinatário, relacionamentos documentais (referências, substituições, impactos) e trilha de auditoria documental ALCOA+ com registros congelados e justificativas.
  Cada aba aplica segregação de deveres (SoD) no servidor, protegendo o acesso a dados de treinamento, eficácia, aprovações e governança documental de acordo com os perfis de acesso.

- **Cockpit de Auditorias da Qualidade e Planos de Ação (`app:audit_cockpit`):**
  Disponível no detalhe de `AuditPlan` (`/app/audits/plans/<id>/cockpit/`).
  Consolida a gestão 360° do ciclo completo de auditorias sanitárias, checklists normativos, achados, planos de ação e governança de encerramento em cinco abas Duralux:
  1. *Escopo, cronograma e equipe auditora*: Ficha de planejamento e equipe técnica (auditor líder, auditado, parceiro/fornecedor, área, local e endereço normalizado com logradouro, número, complemento, bairro, município e UF), datas e horários planejados e reais, escopo detalhado de auditoria, critérios normativos e regulatórios aplicáveis (RDC ANVISA nº 48/2013 e ABNT NBR ISO 22716), agenda e roteiro de trabalho.
  2. *Checklist de verificação BPF / ISO 22716*: Indicadores de conformidade global do checklist, status de cada item (conforme, não conforme, não aplicável, não avaliado), referências normativas e regulatórias, respostas e evidências coletadas, auditor responsável pela avaliação e data e hora do preenchimento.
  3. *Constatações, evidências e não-conformidades*: Quadro completo de achados classificados (não conformidade, observação, oportunidade de melhoria, conformidade) e estratificados por criticidade (crítica, maior, menor), prazos, responsáveis, vínculo direto com o item do checklist e galeria de evidências documentais anexadas com hash criptográfico ALCOA+.
  4. *Planos de ação, CAPAs e vínculos transversais*: Ações de follow-up com status, prazos, flags de obrigatoriedade e exigência de evidência, observações de conclusão, referências e hashes de comprovação, além de vínculos transversais rastreados (registros CAPA, desvios e eventos de qualidade, controles de mudança, documentos controlados e fornecedores).
  5. *Relatório final, conclusão e gates de prontidão*: Scorecard de prontidão e governança sanitária com avaliação dos 5 Gates de Auditoria (Gate 1: Planejamento e Escopo; Gate 2: Execução do Checklist; Gate 3: Evidenciação ALCOA+; Gate 4: Planos de Ação e CAPA; Gate 5: Relatório e Conclusão), veredito regulatório formal, sumário executivo e parecer conclusivo do relatório emitido, indicadores consolidados de conformidade e resumo de encerramento formal assinado.
  Cada aba aplica segregação de deveres (SoD) no servidor, protegendo o acesso a checklists, apontamentos, evidências, ações e relatórios conforme as permissões de cada usuário.

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
