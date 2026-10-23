# PRD — RGN Farma System

- Versão: 3.0
- Status: vigente
- Atualização: 31/08/2026
- Arquitetura: ERP para a indústria de cosméticos, single-instance

## 1. Fontes de verdade

Este documento define o produto vigente. As decisões de
implementação estão em `docs/architecture/single-instance.md` e
`docs/architecture/auth-single-instance.md`.

Em caso de conflito, prevalecem, nesta ordem: `AGENTS.md`, este PRD e a
documentação de arquitetura vigente. Planos e specs
em `docs/superpowers/` são registros históricos e não constituem contrato de
runtime.

## 2. Visão do produto

O RGN Farma System é um ERP para uma indústria de cosméticos, cobrindo os
processos industriais, logísticos, financeiros, fiscais, comerciais,
regulatórios e da qualidade em uma única instância. O produto deve preservar
integridade de dados, rastreabilidade, segregação de funções e evidências
compatíveis com BPF de cosméticos, ALCOA+, GAMP 5, ISO 22716, CSV,
cosmetovigilância e requisitos da ANVISA quando aplicáveis.

## 3. Stack obrigatória

- Python 3.14, Django 6 e Django REST Framework.
- PostgreSQL como único banco relacional suportado.
- Redis, Celery e RabbitMQ para cache e processamento assíncrono.
- Bootstrap 5, JavaScript, HTML5 e CSS3 na interface.
- Docker e Nginx para execução e publicação; PostgreSQL sempre em container.
- MkDocs e Mermaid para documentação técnica e funcional.

## 4. Arquitetura e acesso

- A instalação possui um único escopo global de dados.
- Não existe cadastro, seleção, header, middleware ou filtro obrigatório de
  escopo por cliente.
- O login usa `username` único e senha; e-mail é contato obrigatório.
- Usuários, grupos e permissões são administrados pelo Django Admin.
- UI e APIs usam permissões Django `view`, `add`, `change` e `delete`.
- Ações REST adicionais de escrita exigem `change` no model correspondente.
- Arquivos protegidos nunca são publicados diretamente e exigem autenticação,
  autorização e vínculo funcional.
- Operações com pai e filhos ou múltiplos registros são transacionais.

## 5. Requisitos funcionais

| ID | Domínio | Resultado esperado |
| --- | --- | --- |
| RF-01 | Identidade e acesso | Login único, Django Admin, grupos, permissões e auditoria de ações críticas. |
| RF-02 | Cadastros mestres | Produtos, unidades, parceiros, plantas, armazéns e estruturas operacionais validados. |
| RF-03 | Fórmulas e roteiros | Fórmulas versionadas, componentes, rendimentos, roteiros e vigências controlados. |
| RF-04 | Produção | Ordens, consumos, perdas, lotes, estados e desvios rastreáveis. |
| RF-05 | PCP/MPS/MRP | Demanda, necessidade líquida, capacidade, sugestões e alertas de planejamento. |
| RF-06 | Compras | Requisições, cotações, pedidos, recebimentos e qualificação de fornecedores. |
| RF-07 | Estoque | Saldos por item/lote/local/status, movimentações, reservas e genealogia. |
| RF-08 | Custos | Custos padrão, médio e real, simulações, variações e fechamento mensal. |
| RF-09 | Financeiro | Contas, títulos, liquidações, caixa, conciliação e fechamento. |
| RF-10 | Fiscal | Cadastros tributários, documentos, impostos, livros, emissão e obrigações. |
| RF-11 | CRM | Clientes, oportunidades, propostas, pedidos, contratos, campanhas e reclamações. |
| RF-12 | Controle de Qualidade | Amostras, especificações, análises, resultados e investigações laboratoriais. |
| RF-13 | Garantia da Qualidade | Revisões, liberação de lotes, bloqueios, treinamentos e registros de lote. |
| RF-14 | Gestão documental | Documentos controlados, versões, anexos, aprovações, distribuição e trilha. |
| RF-15 | Desvios | Eventos, contenção, investigação, causa raiz, impacto, evidências e aprovações. |
| RF-16 | CAPA | Ações corretivas/preventivas, evidências, aprovações e verificação de eficácia. |
| RF-17 | Mudanças | Avaliações de impacto, ações, aprovações, estoque afetado e implantação. |
| RF-18 | Auditorias | Programas, planos, checklist, achados, evidências, ações e relatórios. |
| RF-19 | Riscos | Avaliações, controles, mitigação, revisões, alertas e risco residual. |
| RF-21 | Cosmetovigilância | Reclamações, eventos adversos, investigação, comunicação regulatória e tendências. |
| RF-22 | Recall | Reclamações, devoluções, campanhas, clientes, comunicações e efetividade. |
| RF-24 | Treinamentos | Cargos, competências, matriz, turmas, avaliações e autorização de atividades críticas. |
| RF-25 | Arquivos protegidos | Criptografia, hash, regras de acesso, links temporários e trilha de acesso. |
| RF-26 | Relatórios e BI | Dashboards, definições, execuções, agendas, exportações e notificações. |
| RF-27 | Workflow | Filas, tarefas, delegações, comentários, anexos, notificações e jobs. |
| RF-28 | Integrações | Conectores, clientes de API, rotação de segredo, eventos e logs. |
| RF-29 | IA | Agentes, revisão humana e auditoria de prompts. |
| RF-30 | Governança | Parâmetros, catálogos, logs, cenários de demonstração e administração interna. |
| RF-31 | Compliance transversal | Permissão, auditoria, status, transação, mensagens, documentação, menu, testes e API. |

## 6. Interface operacional

- Um shell responsivo e um template genérico atendem listagem, detalhe,
  adição, edição e confirmação de exclusão.
- Sidebar, módulos, recursos e botões respeitam permissões reais.
- Relações prioritárias 1-N são editadas no formulário principal por formsets
  genéricos, com rollback integral em falha e permissão por ação do filho.
- As 258 ações `POST` de domínio possuem representação na UI operacional; ações
  de detalhe respeitam permissões e ciclo de vida antes de exibir o botão, e o
  endpoint DRF revalida todas as regras no envio.
- Textos exibidos ao usuário são em português brasileiro.

## 7. Dados e integridade

- Models operacionais herdam de base single-instance equivalente a
  `TimeStampedModel` e não possuem campo de escopo por cliente.
- Constraints são globais ou compostas pelo contexto funcional do domínio.
- Foreign keys, regras de estado e validações de relacionamento devem impedir
  referências incompatíveis.
- Registros críticos exigem autoria, timestamps, motivo, evidência e trilha de
  auditoria conforme risco regulatório.
- Migrations devem ser revisáveis, reversíveis quando possível e executáveis
  no PostgreSQL containerizado.

## 8. Segurança e compliance

- Segredos reais ficam fora do Git e devem ser fornecidos por ambiente ou
  mecanismo de secrets do orquestrador.
- Conteúdo sensível usa AES-256-GCM e hash SHA-256 quando aplicável.
- CSRF, cookies, hosts, TLS, rate limits e logs devem ser configurados por
  perfil de ambiente.
- Exclusão física de registros GxP somente é permitida quando houver política
  explícita de retenção e auditoria.
- Alterações críticas devem ser transacionais e registrar usuário, instante,
  motivo e resultado.

## 9. Operação local e continuidade

- Desenvolvimento e testes usam PostgreSQL em Docker Compose.
- Redis e RabbitMQ em containers suportam cache e Celery.
- Backup inclui PostgreSQL e mídia, possui retenção e pode ser criptografado
  para cópia off-site.
- Restore exige artefato explícito, confirmação, validação gzip e backup
  pré-restauração; `--dry-run` não altera dados.
- O plano de rollback está em `docs/deployment.md` (seção Rollback).

## 10. Critérios de aceite

- `manage.py check`, migrations, lint e suíte automatizada passam.
- PostgreSQL containerizado é comprovado nos perfis local, teste e VPS.
- Models e schema não contêm artefatos funcionais de escopo por cliente.
- Login por nome de usuário e controle de acesso pelo Django Admin funcionam.
- UI, APIs, CRUD e relações prioritárias respeitam permissões.
- O catálogo HTML e as ações `POST` DRF possuem exatamente as mesmas 258 chaves,
  sem ações órfãs, duplicadas ou expostas em estado incompatível.
- IA, backup, arquivos e criptografia funcionam no escopo global.
- Documentação, matriz de requisitos e catálogo de evidências estão atualizados.
- Pendências externas ou regulatórias são explicitadas e bloqueiam a declaração
  de encerramento formal quando aplicável.

## 11. Gates de aceite e release

```bash
.venv/bin/python manage.py check_product_acceptance --fail-on-error
.venv/bin/python manage.py check_release_readiness --fail-on-error
```

Esses gates validam rotas, documentação, controles operacionais, backup,
OpenAPI e runbook de release contra este contrato vigente.
