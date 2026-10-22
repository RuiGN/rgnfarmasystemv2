# Identificadores, navegação e reset da homologação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement inline; use fresh independent review for the complete branch. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Entregar a atualização aprovada de codes por ID real, navegação compacta, reset seletivo/catálogos cosméticos e chat funcional de manual.

**Architecture:** Alterar o gerador e o cabeçalho compartilhados. Implementar uma manutenção de treinamento explicitamente acionada, com manifesto fechado de tabelas e transação PostgreSQL, reutilizando catálogos versionados. Atualizar o RAG existente e avaliar o modo realmente configurado antes de liberar a VPS.

**Tech Stack:** Python3.14,Django6,DRF,PostgreSQL,Redis,Celery/RabbitMQ,Docker,Nginx,Bootstrap5/JS; ferramentas já instaladas, sem novas dependências previstas.

**Spec:** `docs/superpowers/specs/2026-10-21-id-code-navigation-training-reset-design.md` — usuário aprovou desenho e execução via clarify em2026-10-21.

## Global Constraints

- CODE_PREFIX-ID sem padding; códigos explícitos/oficiais preservados. PK/FK e modelos somente-ID não serão convertidos.
- Preservar usuários/grupos/permissões gerais e suas identidades; apagar negócio/metadados e ACLs de anexos antigos, sem apagar arquivos físicos/backups.
- CONTINUE IDENTITY: não reutilizar IDs antigos; não prometer sequências sem lacunas ou rollback de avanços.
- Somente auxiliares/catálogos; sem full_demo, transações fictícias ou integrações ativas.
- Corpus apenas manual curado/registry/documentação funcional; nenhum dado privado ou arquivo .env.
- Testes somente no PostgreSQL sintético127.0.0.1:5433; bloquear dotenv antes de imports Django/pytest. Um escritor por banco de testes.
- CI exata aprovada antes da VPS; novo backup depois de parar escritores e ensaio de restore em instância descartável isolada antes do reset.
- Manter override original e dados de outros projetos. Sem flush Redis global, exclusão de volumes ou exposição de credenciais.

## Review Focus

1. PK/alias/force flags e signal com code final: Task1 cobre callbacks e semântica Django.
2. Tabela desconhecida ou FK de preservada para limpa: Task3 cobre recusa sem CASCADE e rollback.
3. Tarefas antigas/referências textuais: Task6 exige parada de escritores, isolamento/filas e sequências preservadas.
4. Fontes antigas/rota obsoleta versus citations apenas decorativas: Task4 cobre reingestão e avaliação de fatos/fontes.
5. Falha após reset e antes de reabrir: Task6 distingue recuperação DB de simples troca de imagem; manter manutenção sem falso PASS.

### Task 1: Código automático por PK

**Files:** modificar `base/sequences.py`; testes `tests/test_codegen.py`, novo `tests/test_code_primary_key.py`; adequar somente expectativas de formato afetadas nos testes/API/manuais.

**Interfaces:** preservar `AutoCodeMixin.save(self, *args, **kwargs)` e geração diária `IdentifierSpec`/`sequence_code`. Produzir `code == f'{CODE_PREFIX}-{pk}'` na criação automática e ao preencher code vazio de registro já existente. Preservar helper público generate_code para os contratos legados independentes, sem usá-lo no mixin.

- [ ] Criar `test_auto_code_uses_real_primary_key_without_padding` com PK deliberadamente diferente do contador e code exato.
- [ ] Executar teste isolado; esperado RED por code sequencial/padded, não por setup/coleta.
- [ ] Implementar reserva da sequência nativa da PK PostgreSQL antes do INSERT, validação de formato/tamanho e alias. Signal created deve ver o code final; nunca publicar code temporário.
- [ ] Executar GREEN; estender em ciclos RED/GREEN para update_fields, códigos explícitos, sem prefixo, force flags, colisão/rollback, exclusão e concorrência de conexões.
- [ ] Executar `tests/test_codegen.py`, `tests/test_code_primary_key.py`, `tests/test_automatic_fields.py`, `tests/test_automatic_fields_additional.py` se esse último existir; inventariar registry real. Esperado todos verdes e sem novos namespaces de code no mixin.
- [ ] Atualizar contratos numéricos fixos das APIs/testes para comparar com PK real, não simplesmente afrouxar asserts. Registrar prova e commit explícito dos arquivos revisados, sem push ainda.

### Task 2: Cabeçalho de navegação sem repetição

**Files:** `templates/includes/page_header.html`, `templates/workspaces/workspace.html`, `base/ui/workspaces.py`; templates compartilhados redundantes em `templates/app/` e `templates/dashboards/hub.html`; `tests/test_compact_page_header.py`, `tests/test_workspace_ui.py`, expectativas focais de `tests/test_app_ui.py`.

**Interfaces:** include com modo compacto explícito, ancestrais/heading atual e ações. Não mudar URLs/workspace builders nem enforcement de permissões.

- [ ] Teste RED de `.page-header` do workflow: Aplicativos > Fluxo de trabalho, uma identificação atual, heading/aria-current e sem Central de workflow no cabeçalho.
- [ ] Implementar uso do include compacto e nome canônico workflow; GREEN.
- [ ] Ciclos para links/ações, ancestral único no módulo, títulos distintos de detalhe/form e permissões/sidebar.
- [ ] Rodar smoke de módulos/listas e suíte focal de headers/workspaces. Esperado todos verdes; preservar workspaces e módulos como destinos distintos.
- [ ] Documentar e registrar commit após verificação.

### Task 3: Manutenção seletiva e catálogo

**Files to create:** `governance/training_reset.py`, `governance/training_reset_manifest.json`, `governance/management/commands/reset_training_data.py`, `tests/test_training_reset.py`.
**Files to modify:** `core/settings/base.py` para flag opt-in de manutenção; loaders existentes somente quando necessário para completar recarga aprovada; documentação operacional de reset.

**Interfaces novas:** `training_reset_plan(*, using='default') -> dict`; `reset_training_data(*, expected_database: str, backup_receipt_sha256: str, using='default') -> dict`. Comando `reset_training_data` com inspeção sem escrita por padrão e execução explícita, banco esperado e recibo de backup obrigatório. A validade real de backup/restore é conferida pelo orquestrador antes de invocar; nunca atribuir à string SHA passada ao comando a prova de backup.

- [ ] Gerar inventário de tabelas/models/M2M em settings herméticos, sem conectar; congelar manifesto explícito do release, preservadas/limpas/recarregadas. Schema/tabela desconhecidos recusados.
- [ ] Teste RED: comando sem execute/opt-in não apaga nada. Implementar plano e guards; GREEN.
- [ ] Teste RED de reset autorizado: limpar Produto/negócio/metadados anexos, preservar valores e PKs de usuários/grupos/permissões/M2Ms/contenttypes/migrations e suas sequências. Implementar transação única, locks/timeouts, TRUNCATE allowlist CONTINUE IDENTITY sem CASCADE; GREEN.
- [ ] Teste RED de falha tardia de carga e tabela/FK desconhecida; provar rollback/recusa sem efeitos externos. Preservação sensível verificada em SQL, sem retornar hashes/senhas/PII.
- [ ] Recarregar por seed_production_reference_data e sync_curated_report_catalog(ReportDefinition); manifestos e full_clean. Provar oficiais/cosméticos/relatórios, repetição sem duplicatas e ausência de transações demo/integrações ativas.
- [ ] Rodar testes de reset, referências e auxiliares; todo reset fica restrito ao banco sintético durante desenvolvimento. Documentar alcance/limites e registrar commit.

### Task 4: Manual atualizado e chat fundamentado

**Files:** `knowledge/step_by_step_manual.py`, `knowledge/manual_catalog.py`, `knowledge/services.py`, `knowledge/eligibility.py`, `knowledge/indexing.py`/`retrieval.py` quando necessário; `docs/architecture/formulations.md`; testes existentes de manual/ingestão/chat/recuperação e novo conjunto versionado de avaliação funcional.

**Interfaces:** manter widget de base.html e POST /api/knowledge/chat/; comandos existentes build_erp_manual_corpus/rebuild_knowledge_index/reconcile_knowledge_alias. Respostas/citations permanecem compatíveis com o cliente atual.

- [ ] RED: manual deve descrever Produtos3abas/Fórmulas2abas, versão explícita, cadastro relacionado separado e filtros dependentes. Atualizar conteúdo gerado/arquitetura; GREEN.
- [ ] RED: reingestão revisada não recupera instrução antiga nem invalida citações históricas. Implementar versão/eligibilidade em ambos os retrievers; GREEN.
- [ ] RED: seções/títulos nos chunks e prompt delimitando fontes como dados, com referências verificáveis e recusa sem suporte. Implementar mínimo mantendo compatibilidade; GREEN.
- [ ] Testar sessão/permissão, escape frontend, local-only sem rede e erros sem divulgar URLs/segredos. Não alterar silenciosamente modo configurado.
- [ ] Criar avaliação PT-BR com fatos obrigatórios/proibidos e fontes para produto/versão/componentes/FK/codes/navegação/permissão/fora do manual/mutação solicitada; testes usam doubles apenas para contratos externos. Execução real é Task6.
- [ ] Rodar suítes focais; documentar e registrar commit.

### Task 5: Integração, revisão e publicação

- [ ] Congelar diff/fonte, rodar Ruff/formato/MyPy/Bandit/auditoria/Node/testes PostgreSQL com cobertura80% e schema/migrations, usando runners herméticos e evidências imutáveis fora do repo. Esperado saídas0; falhas preservadas e corrigidas por causa.
- [ ] Pedir uma revisão fresca da branch completa, destacando reset e Review Focus. Corrigir findings importantes por RED/GREEN e regressão; sem declarar revisão como teste executado.
- [ ] Scanner público/staged/commits com política existente intacta; publicar somente allowlist de arquivos revisados. Excluir .hermes/, documento privado e artefatos operacionais.
- [ ] Push/integração main conforme autorização; reler refs e CI do SHA exato, artefatos e checkout. Não prosseguir com CI pendente/falha.

### Task 6: Implantação e reset autorizados

- [ ] Preflight seguro do projeto exato rgnfarmasystem e configuração/recursos do RAG; construir do Gitarchive fixado, conferir fontes/imagem/configuração antes da parada. Não ler dotenv.
- [ ] Parar escritores/entrada e criar backup novo protegido; releitura independente dos arquivos/recibo/imagem anterior. Validar restore em PostgreSQL descartável isolado, sem portas/dados expostos; se falhar, não resetar.
- [ ] Conferir alvo e manifesto; executar reset/carga uma única vez. Verificar preservadas por igualdade servidor-side e novas contagens por manifesto, negócio antigo ausente e blobs intactos. Limpar somente filas/caches antigos do próprio projeto com propriedade comprovada.
- [ ] Ingerir manual e construir/ativar geração do modo efetivo. Avaliar perguntas reais e fontes sem enviar dados de negócio nem deixar cenários de teste no banco. Se falta dependência/credencial, bloquear honestamente e não declarar IA pronta.
- [ ] Ativar nova imagem com todos os overrides aprovados, atualizar upstream Nginx e retomar serviços após gates. Qualquer falha pós-reset exige manutenção/recuperação de dados explícita, não falsa reversão por imagem.

### Task 7: Releitura e encerramento

- [ ] Reler versão/imagens/serviços/restarts/volumes/migrações/config stat/override e HTTP/estáticos por hash.
- [ ] Confirmar contas/permissões, catálogos/relatórios, negócio antigo limpo, mídias físicas preservadas e anexos antigos fora da UI; verificar codes automáticos por prova reversível/sintética.
- [ ] Conferir corpus/geração/alias ou modo local, respostas e fontes; distinguir recuperação real de mocks.
- [ ] Registrar handoff/manifesto de hashes, atualizar catálogo do projeto, reconciliar checklist e informar URL/resultado/falhas recuperadas/limites de impressão/aceite industrial. Sem alegar monitoramento contínuo, offsite ou aceite industrial.

## Autorrevisão e decisões de execução

Cobertura conferida contra todas as seções da especificação; Review Focus distribuído nos testes/tasks acima. Interfaces novas são definidas na Task3; contratos existentes não serão substituídos silenciosamente. Os comandos de teste serão executados pelo runner hermético desta rodada, com logs/XML por execução; nenhum comando desta lista é evidência de que já foi executado.

Ruling: executar inline em uma branch dedicada no checkout existente, sem criar worktree não solicitado nem copiar dotenv. Preservar arquivos privados/untracked e usar evidências fora do repo. Custo se errado: menor isolamento de filesystem; mitigação: um único implementador, status/diffs e publicação por allowlist.

Ruling: a aprovação explícita do usuário para implementar/testar/publicar/deploy/reset já inclui a execução desta decomposição do desenho; não solicitar nova aprovação de método para cada tarefa. Novas decisões destrutivas fora do escopo exigem confirmação.
