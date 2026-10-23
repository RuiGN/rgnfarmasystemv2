# RGN Farma System

ERP single-instance para a indústria de cosméticos, executado com Python 3.14,
Django 6, Django REST Framework, PostgreSQL em Docker, Redis, Celery e RabbitMQ.

O sistema suporta impressão direta de etiquetas TSPL2 pela VPN para uma
impressora ativa, com porta TCP 9100 por padrão. A etiqueta de lote contém
Produto, Lote, Validade e assinatura operacional do usuário. O envio ocorre
sem repetição automática e não confirma a saída física da etiqueta.

Campos gerados automaticamente pelo servidor são desabilitados nos formulários
operacionais e protegidos como somente leitura na API e no Django Admin.

## Ambiente local

O ambiente suportado é autocontido em Docker Compose, inclusive o PostgreSQL.
Somente o Nginx é publicado no host; banco, aplicação, Redis e RabbitMQ ficam na
rede interna do Compose.

```bash
cp .env.local.example .env.local
docker compose --env-file .env.local -f docker-compose.local.yml up -d --build
docker compose --env-file .env.local -f docker-compose.local.yml ps
```

Aplicação local: `http://erp.localhost:4127/`. O perfil de testes também inicia
um PostgreSQL isolado em Docker, por padrão na porta `5433`.

Para diagnóstico excepcional com `runserver`, conecte-o ao PostgreSQL do
Compose e mantenha no ambiente local:

Para executar com `runserver` em HTTP local, mantenha no `.env`:

```dotenv
SECURE_SSL_REDIRECT=False
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False
```

Healthcheck:

```bash
curl http://127.0.0.1:8000/health/
```

Login web:

```text
http://127.0.0.1:8000/accounts/login/
```

O acesso usa o nome de usuário único cadastrado no Django Admin. O e-mail é
obrigatório para contato, mas não autentica.

Painel administrativo interno:

```text
http://erp.localhost:4127/admin/
```

Crie o primeiro administrador pelo comando nativo do Django dentro do container:

```bash
docker compose --env-file .env.local -f docker-compose.local.yml exec app python manage.py createsuperuser
```

Usuários, grupos e permissões são administrados pelo Django Admin. O runtime
operacional usa `/accounts/login/` e `/app/` sem seleção de escopo por cliente.
Consulte `docs/architecture/single-instance.md` para a arquitetura atual.

APIs iniciais:

- `GET /api/accounts/me/` retorna o usuário autenticado sem exigir escopo por cliente.
- `GET|POST /api/masters/products/` mantém produtos e materiais em escopo global.
- `GET|POST /api/masters/partners/` mantém parceiros, fornecedores, clientes e laboratórios.
- `GET|POST /api/masters/units/`, `/api/masters/categories/`, `/api/masters/sites/`, `/api/masters/warehouses/` e `/api/masters/locations/` mantêm estruturas de apoio.
- `GET|POST /api/formulations/formulas/` mantém fórmulas mestras versionadas.
- `GET|POST /api/formulations/components/` mantém componentes e perdas previstas da fórmula.
- `GET|POST /api/formulations/routes/` e `/api/formulations/steps/` mantêm roteiros e etapas de fabricação.
- `GET|POST /api/production/orders/` mantém ordens de produção em escopo global.
- `POST /api/production/orders/{id}/approve/`, `/release/`, `/start/`, `/pause/`, `/resume/`, `/complete/` e `/cancel/` executam o workflow da ordem.
- `GET|POST /api/production/consumptions/` mantém apontamentos de consumo real, perdas e devoluções.
- `GET|POST /api/planning/policies/` mantém políticas de planejamento, estoque de segurança, lote mínimo, múltiplo e lead time.
- `GET|POST /api/planning/schedules/` e `/api/planning/mps-lines/` mantêm o plano mestre de produção e suas demandas.
- `GET|POST /api/planning/inventory/` mantém a posição de estoque usada no MRP.
- `GET|POST /api/planning/mrp-runs/` cria execuções e `POST /api/planning/mrp-runs/{id}/calculate/` calcula necessidades líquidas e sugestões.
- `GET /api/planning/suggestions/` lista sugestões de compra, produção, transferência e terceirização.
- `GET|POST /api/planning/capacity-resources/` e `/api/planning/capacity-loads/` mantêm recursos e gargalos de capacidade.
- `GET|POST /api/procurement/requisitions/` e `/api/procurement/requisition-items/` mantêm requisições manuais, de MRP e demais origens.
- `POST /api/procurement/requisitions/{id}/submit/`, `/approve/`, `/reject/` e `/cancel/` executam o workflow da requisição.
- `GET|POST /api/procurement/rfqs/` e `/api/procurement/supplier-quotations/` mantêm cotações e propostas comparáveis por preço, prazo, qualificação e desempenho.
- `GET|POST /api/procurement/supplier-qualification-events/` mantém documentos, auditorias, ocorrências e restrições de fornecedores.
- `GET|POST /api/procurement/orders/` e `/api/procurement/order-items/` mantêm pedidos de compra e bloqueiam fornecedores inválidos quando o item exige fornecedor aprovado.
- `GET|POST /api/procurement/receipts/` e `/api/procurement/receipt-items/` mantêm recebimento fiscal, físico, qualidade e entrada em estoque.
- `GET|POST /api/inventory/lots/` mantém lotes, sublotes, status de qualidade, fornecedor, origem, fabricação e validade.
- `POST /api/inventory/lots/{id}/print_label/` envia uma etiqueta TSPL2 do lote à impressora ativa pela VPN.
- `GET|POST /api/inventory/balances/` mantém saldos por produto, lote, almoxarifado, localização e status de qualidade.
- `GET|POST /api/inventory/movements/` mantém entradas, saídas, transferências, ajustes, inventários, reservas, devoluções, perdas, segregações, descartes e expedições.
- `GET|POST /api/inventory/genealogy/` mantém genealogia entre lotes consumidos e lotes gerados; a migration da chave única interrompe com chave e IDs acionáveis se detectar duplicatas históricas, sem apagar evidências.
- `GET|POST /api/costing/cost-elements/` mantém elementos de custo.
- `GET|POST /api/costing/standard-costs/` mantém custo padrão; `POST /api/costing/standard-costs/{id}/approve/` executa `draft -> approved` com recálculo e auditoria, e `POST /api/costing/standard-costs/{id}/obsolete/` executa `approved -> obsolete` preservando a evidência de aprovação. Um trigger PostgreSQL bloqueia inserções fora de rascunho, transições inválidas e adulteração de `approved_by`/`approved_at`.
- `GET|POST /api/costing/simulations/` cria simulações e `POST /api/costing/simulations/{id}/calculate/` calcula custo total e unitário.
- `GET|POST /api/costing/production-captures/` mantém custo real por ordem e `POST /api/costing/production-captures/{id}/calculate/` calcula total e variação.
- `GET|POST /api/costing/monthly-closings/` controla fechamento mensal com validação, fechamento e reabertura.
- `GET|POST /api/costing/report-snapshots/` mantém snapshots de margem, custo por lote/produto, não qualidade, desvios e retrabalho.
- `GET|POST /api/finance/chart-accounts/`, `/api/finance/categories/` e `/api/finance/accounts/` mantêm plano de contas, categorias e contas caixa/banco.
- `GET|POST /api/finance/titles/` mantém contas a pagar/receber e `POST /api/finance/titles/{id}/approve/` aprova pagamentos e despesas.
- `GET|POST /api/finance/settlements/` registra baixas com juros, multas, descontos, estornos e conciliação.
- `GET|POST /api/finance/cash-flow/` mantém fluxo de caixa previsto e realizado.
- `GET|POST /api/finance/period-closings/` controla fechamento financeiro mensal com validação, fechamento e reabertura.
- `GET|POST /api/fiscal/companies/`, `/api/fiscal/ncms/`, `/api/fiscal/cfops/`, `/api/fiscal/tax-situations/` e `/api/fiscal/tax-rules/` mantêm cadastros e parâmetros fiscais em escopo global.
- `GET|POST /api/fiscal/documents/`, `/api/fiscal/document-items/` e `/api/fiscal/taxes/` mantêm notas fiscais, itens e impostos de entrada/saída.
- `POST /api/fiscal/documents/{id}/review/`, `/approve/` e `/post_entry/` executam conferência, aprovação e lançamento fiscal.
- `POST /api/fiscal/documents/{id}/issue/`, `/check_status/`, `/cancel/` e `/send_email/` executam emissão NF-e via provedor fiscal, consulta, cancelamento e envio agendado por e-mail.
- `GET /api/fiscal/documents/{id}/xml/`, `/danfe/`, `/api/fiscal/emission-events/` e `/api/fiscal/email-deliveries/` expõem artefatos protegidos e eventos de emissão/envio.
- `GET|POST /api/fiscal/assessments/`, `/api/fiscal/book-entries/`, `/api/fiscal/obligations/` e `/api/fiscal/audit-trail/` mantêm apurações, livros, obrigações e auditoria.
- `GET|POST /api/crm/customer-groups/`, `/api/crm/channels/`, `/api/crm/representatives/`, `/api/crm/customer-profiles/` e `/api/crm/contacts/` mantêm a base comercial de clientes.
- `GET|POST /api/crm/campaigns/`, `/api/crm/opportunities/`, `/api/crm/proposals/`, `/api/crm/proposal-items/` e `/api/crm/contracts/` mantêm campanhas, funil, propostas, itens e contratos.
- `GET|POST /api/crm/orders/` e `/api/crm/order-items/` mantêm pedidos de venda com validação de crédito, estoque, prazo, preço e bloqueios regulatórios.
- `POST /api/crm/orders/{id}/approve/` aprova ou bloqueia pedidos de venda com registro do motivo de bloqueio.
- `GET|POST /api/crm/interactions/` e `/api/crm/complaints/` registram histórico de atendimento e reclamações vinculadas a produto, lote, pedido, nota fiscal, qualidade e CAPA.
- `GET|POST /api/quality/specifications/` mantém especificações analíticas por produto, lote, versão, método, parâmetro, unidade, limites e critérios.
- `GET|POST /api/quality/samples/` mantém amostras de recebimento, produção, estabilidade, validação, reclamação, investigação e monitoramento ambiental.
- `POST /api/quality/samples/{id}/collect/`, `/receive/`, `/start_analysis/`, `/review/`, `/approve/` e `/reject/` executam o workflow da amostra.
- `GET|POST /api/quality/analyses/` e `/api/quality/results/` registram análises, reagentes, padrões, anexos e resultados com flags OOS, OOT, alerta e ação.
- `GET|POST /api/quality/investigations/` controla investigação laboratorial, repetição, reteste, reamostragem e conclusão.
- `GET|POST /api/quality/documents/` emite certificados de análise, laudos, etiquetas e relatórios de liberação.
- `GET|POST /api/qa/reviews/` mantém revisões e aprovações QA de lotes, ordens, registros de embalagem, laudos, desvios, CAPAs, mudanças e documentos.
- `GET|POST /api/qa/checklist-items/` controla checklist de batch record com pendências, responsáveis, prazos, comentários e evidências.
- `GET|POST /api/qa/lot-releases/` controla liberação, rejeição, bloqueio e desbloqueio de lotes com reflexo no status de qualidade do estoque.
- `GET|POST /api/qa/blocks/` bloqueia e desbloqueia lotes, itens, fornecedores, documentos e processos.
- `GET|POST /api/qa/training-requirements/`, `/api/qa/training-records/` e `/api/qa/critical-activity-rules/` mantêm treinamentos obrigatórios e impedem atividades críticas por usuário sem treinamento válido.
- `GET|POST /api/documents/controlled-documents/` mantém documentos controlados com revisão, aprovação, publicação, obsolescência, cancelamento, arquivamento e nova revisão.
- `GET|POST /api/documents/attachments/` e `/api/documents/relationships/` registram anexos com hash ALCOA+ e relacionamentos documentais.
- `GET|POST /api/documents/distributions/` distribui documentos publicados e `POST /api/documents/distributions/{id}/confirm_read/` registra confirmação de leitura.
- `GET /api/documents/audit-trail/` consulta trilha de auditoria documental em escopo global.
- `GET|POST /api/deviations/events/` mantém desvios e não conformidades com origem, área, produto, lote, documento, fornecedor, cliente, severidade e criticidade.
- `GET|POST /api/deviations/evidences/`, `/api/deviations/investigations/`, `/api/deviations/impact-assessments/` e `/api/deviations/approvals/` controlam evidências, investigação, impacto e aprovações obrigatórias.
- `POST /api/deviations/events/{id}/start_investigation/` inicia investigação e `POST /api/deviations/events/{id}/close/` encerra somente com investigação, impacto e aprovações concluídas.
- `GET|POST /api/deviations/links/` vincula desvios a CAPAs, mudanças, auditorias, reclamações, OOS/OOT, lotes, documentos e riscos.
- `GET|POST /api/capa/records/` mantém CAPAs originadas de desvios, auditorias, reclamações, riscos, OOS/OOT, mudanças ou melhorias.
- `GET|POST /api/capa/actions/`, `/api/capa/evidences/`, `/api/capa/effectiveness-checks/` e `/api/capa/approvals/` controlam ações, evidências, avaliação de eficácia e aprovações.
- `POST /api/capa/records/{id}/submit/`, `/start/`, `/close/`, `/cancel/` e `/generate_notifications/` executam workflow, encerramento controlado e geração de alertas.
- `POST /api/capa/actions/{id}/complete/`, `/api/capa/effectiveness-checks/{id}/verify/` e `/api/capa/approvals/{id}/approve/` registram conclusão, eficácia e aprovação.
- `GET|POST /api/capa/notifications/` acompanha vencimentos, atrasos, aprovações pendentes e verificações de eficácia.
- `GET|POST /api/changes/controls/` mantém controles de mudança com escopo, justificativa, áreas afetadas, sistemas, validação, treinamento, regulatório e estoque.
- `GET|POST /api/changes/affected-items/`, `/api/changes/assessments/`, `/api/changes/actions/`, `/api/changes/approvals/` e `/api/changes/stock-assessments/` controlam itens afetados, análises, plano de ações, aprovações e avaliação de estoque.
- `POST /api/changes/controls/{id}/submit/`, `/approve_for_implementation/`, `/start_implementation/`, `/close/` e `/cancel/` executam o workflow de mudança.
- `POST /api/changes/assessments/{id}/complete/`, `/api/changes/actions/{id}/complete/`, `/api/changes/approvals/{id}/approve/` e `/api/changes/stock-assessments/{id}/complete/` registram análise, ação, aprovação e decisão de estoque.
- `GET|POST /api/audits/programs/` mantém programas anuais por tipo de auditoria, escopo, critérios e responsável.
- `GET|POST /api/audits/plans/` controla planos de auditoria e `POST /api/audits/plans/{id}/submit/`, `/start/`, `/complete_execution/`, `/close/` e `/cancel/` executam o workflow.
- `GET|POST /api/audits/checklist-items/`, `/findings/`, `/evidences/`, `/actions/`, `/finding-links/` e `/reports/` controlam checklists, achados, evidências ALCOA+, ações de follow-up, vínculos regulatórios e relatórios.
- `POST /api/audits/checklist-items/{id}/answer/`, `/api/audits/actions/{id}/complete/` e `/api/audits/reports/{id}/issue/` registram avaliação, conclusão de ação e emissão do relatório.
- `GET|POST /api/risks/records/` mantém riscos por categoria, área, responsável, prazos, score inicial e score residual.
- `GET|POST /api/risks/assessments/`, `/api/risks/controls/`, `/api/risks/actions/`, `/api/risks/links/` e `/api/risks/reviews/` controlam matriz/FMEA, controles existentes, ações de mitigação, vínculos e revisões.
- `POST /api/risks/records/{id}/start_treatment/`, `/start_monitoring/`, `/close/`, `/cancel/` e `/generate_alerts/` executam workflow e geração de alertas.
- `POST /api/risks/actions/{id}/complete/`, `/api/risks/reviews/{id}/complete/` e `/api/risks/alerts/{id}/acknowledge/` registram conclusão de ações, revisões e reconhecimento de alertas.
- `GET|POST /api/recalls/complaints/`, `/returns/`, `/campaigns/`, `/impacted-customers/`, `/communications/` e `/reports/` mantêm reclamações pós-mercado, devoluções, campanhas de recall/recolhimento, clientes impactados, comunicações e relatórios.
- `POST /api/recalls/complaints/{id}/start_triage/`, `/start_investigation/`, `/record_regulatory_communication/`, `/close/` e `/cancel/` controlam triagem, investigação, comunicação regulatória e encerramento de reclamações.
- `POST /api/recalls/returns/{id}/authorize/`, `/receive/`, `/inspect/` e `/close/` controlam autorização, recebimento, inspeção e encerramento de devoluções.
- `POST /api/recalls/campaigns/{id}/approve/`, `/start/` e `/close/`, `/api/recalls/impacted-customers/{id}/record_response/`, `/record_return/`, `/api/recalls/communications/{id}/send/` e `/api/recalls/reports/{id}/generate/` executam recall com comunicação, respostas, retorno e efetividade.
- `GET|POST /api/training/job-positions/`, `/functions/`, `/competencies/`, `/requirements/`, `/matrix/`, `/sessions/`, `/enrollments/`, `/critical-activities/` e `/reports/` mantêm cargos, funções, competências, matriz, requisitos, turmas, convocações, registros, atividades críticas e indicadores.
- `POST /api/training/sessions/{id}/convocate/`, `/api/training/enrollments/{id}/start/`, `/complete/`, `/approve/`, `/fail/`, `/revoke/`, `/api/training/critical-activities/{id}/authorize/` e `/api/training/reports/{id}/generate/` controlam convocação, realização, avaliação, aprovação, certificado, bloqueios/alertas e aderência.
- `GET|POST /api/files/protected-files/`, `/access-rules/`, `/secure-links/` e `/audit-trail/` mantêm anexos protegidos em escopo global, origem, sigilo, criticidade, validade, hash e responsável.
- `POST /api/files/protected-files/{id}/generate_link/`, `/replace/`, `/delete_secure/`, `/expire/` e `/record_view/`, além de `POST /api/files/secure-links/{id}/use/` e `/revoke/`, controlam links temporários, acesso, substituição, exclusão, expiração e auditoria.
- `GET|POST /api/reports/dashboards/`, `/dashboard-widgets/`, `/definitions/`, `/executions/`, `/schedules/` e `GET /api/reports/notifications/` mantêm dashboards, widgets, relatórios, execuções, agendamentos e notificações em escopo global.
- `POST /api/reports/definitions/{id}/run/`, `/api/reports/executions/{id}/run/`, `/cancel/` e `/api/reports/schedules/{id}/trigger_now/` geram exportações PDF/XLSX/CSV, executam relatórios e notificam conclusão.
- `GET|POST /api/workflow/notifications/`, `/approval-queues/`, `/approval-tasks/`, `/delegations/`, `/comments/`, `/attachments/`, `/async-jobs/` e `GET /api/workflow/history/` mantêm central de notificações, aprovações, delegações, anexos, jobs assíncronos e histórico.
- `POST /api/workflow/notifications/{id}/send/`, `/mark_read/`, `/archive/`, `/api/workflow/approval-tasks/{id}/approve/`, `/reject/`, `/cancel/` e `/api/workflow/async-jobs/{id}/start/`, `/update_progress/`, `/complete/`, `/fail/` executam o fluxo operacional.
- `GET|POST /api/integrations/connectors/` mantém conectores para ERPs, fiscal, laboratório, email, OpenAI e BI.
- `GET|POST /api/integrations/label-printers/` mantém a configuração da impressora de etiquetas; somente uma pode estar ativa.
- `POST /api/integrations/connectors/{id}/activate/`, `/suspend/`, `/test_success/` e `/test_failure/` controlam o ciclo técnico do conector.
- `GET|POST /api/integrations/api-clients/` mantém clientes de API e `POST /api/integrations/api-clients/{id}/rotate_secret/` rotaciona segredo com hash.
- `GET /api/integrations/api-call-logs/` e `/api/integrations/events/` consultam chamadas, erros e eventos com contexto seguro em escopo global.
- As rotas dos principais módulos também estão expostas em `/api/v1/*`, reutilizando autenticação e permissões Django nativas dos endpoints legados.
- `GET|POST /api/ai-agents/profiles/` mantém agentes de IA por módulo, tipo, provedor, modelo, prompt e módulos permitidos.
- `POST /api/ai-agents/profiles/{id}/run/` cria execução síncrona ou assíncrona; execuções assíncronas usam metadados de task Celery.
- `GET /api/ai-agents/runs/`, `/api/ai-agents/suggestions/` e `/api/ai-agents/audit-logs/` acompanham execução LangGraph, sugestões revisáveis e auditoria de prompt/modelo/entrada/saída.
- `POST /api/ai-agents/suggestions/{id}/approve/`, `/reject/` e `/apply/` registram revisão humana obrigatória para sugestões de IA.
- `GET|POST /api/governance/parameters/` mantém parâmetros de retenção, prazos, alertas, alçadas, bloqueios, lotes, estoque e workflows.
- `GET|POST /api/governance/catalog-items/` mantém tipos de documento, tipos de desvio, categorias de CAPA, status, criticidades e fluxos.
- `GET /api/governance/audit-logs/` consulta logs técnicos e funcionais com contexto seguro em escopo global.
- `GET|POST /api/governance/demo-loads/` e `POST /api/governance/demo-loads/{id}/run/` executam cargas fake/demonstração auditadas.
- `GET|POST /api/compliance/policies/` mantém políticas transversais RF-31 em escopo global e módulo.
- `GET|POST /api/compliance/status-history/` mantém histórico genérico de transições de status com usuário, motivo e contexto seguro.
- `GET /api/compliance/critical-actions/` consulta execuções de ações críticas transacionais e auditadas.
- `GET /api/compliance/checklist-items/` consulta checks transversais e `POST /api/compliance/checklist-items/evaluate_module/` avalia permissões, auditoria, status, transação, mensagens, docs, menu, testes e API de um módulo.
- APIs exigem autenticação e permissões Django nativas; o header de escopo por cliente não é usado no runtime single-instance.

## Assistente RAG do manual

O endpoint `POST /api/knowledge/chat/` e o assistente global exigem a permissão
`knowledge.view_ragchatsession`. O botão flutuante abre o chat em um painel
lateral pela direita; o módulo técnico **Conhecimento RAG** não aparece no menu
nem na grade de aplicativos. As conversas têm isolamento por usuário e o
assistente opera em modo **somente leitura**: consulta o corpus elegível do
manual, devolve citações e não executa SQL, workflows ou mutações no ERP.

Preparação básica:

```bash
.venv/bin/python manage.py migrate
.venv/bin/python manage.py build_erp_manual_corpus
.venv/bin/python manage.py rebuild_knowledge_index
.venv/bin/python manage.py reconcile_knowledge_alias
```

Redis acelera a recuperação vetorial; quando ele está indisponível, existe
fallback PostgreSQL lexical. Para operação, segurança, rollout e rollback,
consulte [docs/architecture/knowledge.md](docs/architecture/knowledge.md).

Carga demo por comando Django:

```bash
.venv/bin/python manage.py load_demo_scenario --scenario base_master_data quality_deviation
.venv/bin/python manage.py load_demo_scenario --scenario full_demo
```

O cenário `full_demo` cria uma massa ampla e idempotente com prefixo `DEMO-*`
para cadastros, produção, MRP, compras, estoque, custos, financeiro, fiscal,
CRM, qualidade, QA, documentos, desvios, CAPA, riscos, auditorias,
cosmetovigilância, recalls, treinamentos, workflow, relatórios, integrações e IA.
Usuários demo usam a senha definida em `DEMO_USER_PASSWORD` (sem valor padrão).

Criptografia AES-256-GCM para arquivos protegidos:

```bash
.venv/bin/python manage.py generate_data_encryption_key --key-id primary
```

Use a saída em `DATA_ENCRYPTION_KEYS` e mantenha `DATA_ENCRYPTION_KEY_ID` com o
identificador da chave ativa. O conteúdo gravado por `ProtectedFile.store_encrypted_content()`
fica criptografado em repouso e vinculado ao registro por dados associados.

Check transversal RF-31:

```bash
.venv/bin/python manage.py check_transversal_compliance --module governance
```

Check de requisitos não funcionais e prontidão operacional:

```bash
.venv/bin/python manage.py check_operational_readiness --format json
```

No Docker Compose, o app executa migrations com advisory lock. Celery
worker e Celery beat aguardam banco e migrations aplicadas, sem executar
migrations nem collectstatic.

Check de backup e restauração:

```bash
.venv/bin/python manage.py check_backup_restore_readiness --format json
```

Aceite técnico de produto:

```bash
.venv/bin/python manage.py check_product_acceptance
.venv/bin/python manage.py check_product_acceptance --format json
.venv/bin/python manage.py check_product_acceptance --fail-on-error
```

Prontidão de release e staging local:

```bash
.venv/bin/python manage.py check_release_readiness
.venv/bin/python manage.py check_release_readiness --format json
.venv/bin/python manage.py check_release_readiness --fail-on-error
.venv/bin/python manage.py spectacular --file openapi-schema.yml
curl -fsS http://127.0.0.1:8000/health/
curl -fsS http://127.0.0.1:8000/
curl -fsS http://127.0.0.1:8000/api/schema/
curl -fsS http://127.0.0.1:8000/api/docs/
curl -fsS http://127.0.0.1:8000/api/v1/
```

Evidencia de release: registre commit, resultados de `manage.py check`,
`makemigrations --check --dry-run`, gates operacionais, schema OpenAPI e smoke
local antes de promover a versão.

Backup e restore operacional:

```bash
DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem BACKUP_DIR=/var/backups/rgnfarmasystem bash scripts/backup.sh
DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem BACKUP_DIR=/var/backups/rgnfarmasystem bash scripts/restore.sh --postgres /var/backups/rgnfarmasystem/postgres-20260831-020000.sql.gz --dry-run
# Após validar hash, janela e backup pré-restore:
DB_DEPLOYMENT=container COMPOSE_PROJECT_NAME=rgnfarmasystem BACKUP_DIR=/var/backups/rgnfarmasystem bash scripts/restore.sh --postgres /var/backups/rgnfarmasystem/postgres-20260831-020000.sql.gz --yes
```

Na VPS, a produção usa o serviço privado `db` do Docker Compose. Siga o [runbook de provisionamento, migração e
rollback](docs/DEPLOY_VPS.md) e o
[contrato canônico de backup e restauração](docs/architecture/backup-restore.md).

Backup automático diário local:

- O serviço `backup_scheduler` executa `scripts/backup.sh` na janela configurada.
- PostgreSQL e mídia são obrigatórios; artefatos ausentes ou vazios mantêm o
  serviço sem marcador de saúde.
- `flock` impede ciclos concorrentes e `BACKUP_RETENTION_DAYS` controla a
  retenção no volume local.
- Para operação e restauração, siga `docs/deployment.md`.

## Testes automatizados

A suíte usa um PostgreSQL 15 isolado em `127.0.0.1:5433`. Docker, Docker
Compose v2 e a virtualenv `.venv` devem estar disponíveis.

```bash
bash scripts/test.sh
```

Para executar somente parte da suíte, passe os argumentos diretamente ao
pytest:

```bash
bash scripts/test.sh tests/test_foundation.py -q
```

Se a porta `5433` estiver ocupada, escolha outra porta:

```bash
TEST_POSTGRES_PORT=55433 bash scripts/test.sh
```

O banco permanece ativo para acelerar execuções posteriores com `--reuse-db`.
Para removê-lo, incluindo o volume isolado:

```bash
docker compose -f docker-compose.test.yml down -v
```

## Documentação

```bash
.venv/bin/mkdocs serve
```
