# Dados de treinamento de cosméticos — homologação

## Resultado observado

Carga operacional concluída em `2026-10-20T16:02:38.360897+00:00`; leitura independente em `2026-10-20T16:03:55.873233+00:00`, por conexão PostgreSQL nova e transação somente leitura.

- **1640 novas linhas**, incluindo relacionamentos M2M; **1635 registros novos** passaram `full_clean()` sem exceções de validação.
- Seis carteiras fictícias: hidratante corporal (COR), sérum facial (FAC), xampu (CAP), condicionador (CON), sabonete líquido (HIG) e máscara capilar (MAS).
- Suplemento: 794 inclusões; 0 vínculos omitidos por falta de pré-requisitos.
- **29 áreas com dados**, **162 dos 200 recursos cadastrados com registros**; 38 recursos permanecem vazios (lista completa abaixo).
- Os 6.506 registros canônicos de referência anteriormente carregados foram mantidos; novas linhas de treinamento também ampliam algumas tabelas auxiliares. Esse número não é apresentado como o total atual de todas as tabelas auxiliares.
- 6 arquivos novos criptografados foram lidos, descriptografados e conferidos por hash canônico e tamanho; os downloads canônicos já haviam sido exercitados durante a carga.
- 18 saldos de estoque conciliados com movimentos; consumo real do cenário e genealogia conciliados.
- 7641 linhas preexistentes conferidas nos campos escalares/de relacionamento selecionados. A conferência remota exclui credenciais, configuração arbitrária, conteúdo textual e nomes/conteúdo de arquivos; não é uma comparação byte a byte de todos os campos.
- Os modelos não tiveram regras ou permissões relaxadas. Não foram criadas entregas de e-mail fiscal; documentos fiscais permanecem rascunhos de homologação não enviados. Perfis de IA e conectores novos permanecem inativos.
- As identidades de cenário possuem senha inutilizável; nenhuma senha foi fornecida ou redefinida. Não houve exclusão ou reset de registros operacionais existentes.
- Tempos de criação e auditoria refletem a execução real; datas de planejamento fictício não são confundidas com eventos de auditoria.
- Os nove serviços, imagens, checkout e metadados da configuração permaneceram iguais aos do backup. Não houve reinício, migração, commit, merge ou publicação de UI nesta etapa.

## Escopo e limites

Este ambiente destina-se a treinamento e ajustes de etiquetas, não à produção. Todos os cenários são identificados como simulação sem validade regulatória. Aprovações/ciclos de negócio dos cenários não constituem execução industrial, liberação sanitária, análise laboratorial, capacitação ou certificação real. Valores financeiros são fictícios. Não foram executadas chamadas de IA, embeddings, integrações externas ou transmissão fiscal.

Guardas de rede, SMTP, tarefas e notificações são locais ao processo de carga; não desabilitam outros containers. O armazenamento de mídia não é transacional; falhas após gravação poderiam deixar novos blobs órfãos, sem autorizar cleanup destrutivo. A carga observada terminou e seus seis arquivos foram conferidos.

## Verificação local e recuperação de falhas

- Integração das bibliotecas com os catálogos completos: 24 verificações aprovadas, incluindo segunda execução imutável e leitura após commit.
- Executor transacional do pai: 12 verificações aprovadas, incluindo rollback do core/contas, cópia exata da fixture pública de 6.506 referências, seis carteiras, validação integral dos registros novos, arquivos e segunda carga sem novas linhas nem alterações escalares.
- Dez testes adicionais da seleção segura de campos e proteção de registros/counters passaram. A falha inicial de seleção de uma chave credencial primária foi demonstrada e corrigida antes da execução remota.
- Falhas anteriores foram preservadas: interrupção de migration do teste; uso indevido de PK fixa `id`; classificação de datas planejadas de AuditPlan como auditoria; substituição involuntária de timestamps ao copiar fixtures pelo ORM; comparação sem o prefixo canônico `sha256:` dos arquivos. Nenhuma dessas tentativas aplicou dados na VPS.

## Cobertura por área

| Área | Recursos com dados | Recursos cadastrados |
|---|---:|---:|
| `auxiliary` | 14 | 14 |
| `masters` | 7 | 7 |
| `formulations` | 4 | 4 |
| `production` | 2 | 2 |
| `planning` | 8 | 8 |
| `procurement` | 9 | 9 |
| `inventory` | 4 | 4 |
| `costing` | 2 | 6 |
| `finance` | 4 | 7 |
| `fiscal` | 14 | 16 |
| `crm` | 14 | 14 |
| `quality` | 6 | 6 |
| `qa` | 2 | 7 |
| `documents` | 4 | 6 |
| `deviations` | 6 | 6 |
| `capa` | 5 | 6 |
| `changes` | 6 | 6 |
| `audits` | 8 | 8 |
| `risks` | 5 | 7 |
| `recalls` | 3 | 6 |
| `training` | 9 | 9 |
| `files` | 4 | 4 |
| `reports` | 3 | 6 |
| `workflow` | 4 | 8 |
| `integrations` | 3 | 5 |
| `ai_agents` | 2 | 4 |
| `knowledge` | 5 | 6 |
| `governance` | 3 | 5 |
| `compliance` | 2 | 4 |

## Recursos ainda vazios

A lista não é substituída por logs, execuções, aprovações ou eventos artificiais para produzir cobertura aparente. Alguns recursos dependem de ações posteriores do treinamento ou de escopos que não foram executados.

| Área | Recurso | Modelo |
|---|---|---|
| `costing` | `simulations` | `costing.CostSimulation` |
| `costing` | `production-captures` | `costing.ProductionCostCapture` |
| `costing` | `monthly-closings` | `costing.MonthlyCostClosing` |
| `costing` | `report-snapshots` | `costing.CostReportSnapshot` |
| `finance` | `settlements` | `finance.FinancialSettlement` |
| `finance` | `cash-flow` | `finance.CashFlowEntry` |
| `finance` | `period-closings` | `finance.FinancialPeriodClosing` |
| `fiscal` | `emission-events` | `fiscal.FiscalEmissionEvent` |
| `fiscal` | `email-deliveries` | `fiscal.FiscalEmailDelivery` |
| `qa` | `lot-releases` | `qa.LotRelease` |
| `qa` | `blocks` | `qa.QualityBlock` |
| `qa` | `training-requirements` | `qa.TrainingRequirement` |
| `qa` | `training-records` | `qa.TrainingRecord` |
| `qa` | `critical-activity-rules` | `qa.CriticalActivityRule` |
| `documents` | `distributions` | `documents.DocumentDistribution` |
| `documents` | `audit-trail` | `documents.DocumentAuditTrail` |
| `capa` | `notifications` | `capa.CapaNotification` |
| `risks` | `controls` | `risks.RiskControl` |
| `risks` | `alerts` | `risks.RiskAlert` |
| `recalls` | `impacted-customers` | `recalls.RecallImpactedCustomer` |
| `recalls` | `communications` | `recalls.RecallCommunication` |
| `recalls` | `reports` | `recalls.RecallEffectivenessReport` |
| `reports` | `executions` | `reports.ReportExecution` |
| `reports` | `schedules` | `reports.ReportSchedule` |
| `reports` | `notifications` | `reports.ReportNotification` |
| `workflow` | `delegations` | `workflow.WorkflowDelegation` |
| `workflow` | `comments` | `workflow.WorkflowComment` |
| `workflow` | `attachments` | `workflow.WorkflowAttachment` |
| `workflow` | `async-jobs` | `workflow.AsyncJobStatus` |
| `integrations` | `label-printers` | `integrations.LabelPrinterSettings` |
| `integrations` | `events` | `integrations.IntegrationEvent` |
| `ai_agents` | `suggestions` | `ai_agents.AIInsightSuggestion` |
| `ai_agents` | `prompt-audit` | `ai_agents.AIPromptAuditLog` |
| `knowledge` | `ingestion-logs` | `knowledge.KnowledgeIngestionLog` |
| `governance` | `institution-settings` | `governance.InstitutionSettings` |
| `governance` | `demo-loads` | `governance.DemoScenarioLoad` |
| `compliance` | `status-history` | `compliance.RecordStatusHistory` |
| `compliance` | `critical-actions` | `compliance.CriticalActionExecution` |

## Backup e evidências

- Backup pré-operacional: `/var/backups/rgnfarmasystem/releases/preseed-20261020T145922849764Z-cosmetics`.
- SHA-256 do recibo: `af29a3e8ea650f54bc821299697b38357bfb6590d25a05f774e8ab22c2bc7bc8`.
- Dump custom PostgreSQL e mídia passaram gzip/tar/pg_restore --list e hashes; arquivos 0600/diretório 0700. A leitura do catálogo não é teste de restore; o backup é quente, local ao servidor, sem atomicidade conjunta banco+mídia e sem prova de cópia offsite.
- Evidências e fontes congeladas: `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/cosmetics-training-seed-2026-10-20`.
- Recibos: `operational-applied.json`, `operational-readback.json`, `operational-readback-summary.json`, `post-operational-runtime-backup-readback.json`, `operational-runner-integration-final.json`.
- Fontes usadas (SHA-256):
  - `cos_training_core`: `48df47f55790cfaf6c3c37444f77645f5e8f0424b61554da36af7440315a1da4`.
  - `cos_training_supplement`: `4ffabcc787a65292902c9edba646831a8fa54e5933a159d1b1fd54ecede07dce`.
  - `cosmetics_operational_runner`: `de7c6681f62c49c0258d85325d77dbb001b90e1d8693916a552e11661a49632f`.

## Interface e validações humanas

Cabeçalho compacto e abas expandidas são alterações locais separadas da população. Há 432 testes integrados aprovados; a revisão independente não encontrou perda de campos/permissões, mas exigiu QA das abas no navegador. A publicação da nova UI permanece pendente desse QA e do escopo de publicação aprovado. O candidato em execução continua sendo o anterior.

Não houve alteração de menus/permissões de produção por este carregamento. Os módulos já pertenciam ao menu e as identidades sintéticas não recebem senha. A validação física das etiquetas depende da impressora na indústria; o treinamento dos funcionários e o acesso autenticado do operador não são comprovados por esta carga.
