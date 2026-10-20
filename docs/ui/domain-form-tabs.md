# Abas por domínio nos formulários extensos

## Escopo e contrato

Inventário do registry em `7d0b9d9b6129755e3750280c34d55dee040f996b`,
contado com Python/JSON: **29 módulos, 200 recursos**, dos quais **42 somente
leitura**. A seleção explícita acrescenta agrupamento do formulário pai a **48
recursos em 25 módulos**, com **172 grupos declarados**. Não é uma regra automática
por quantidade de campos. A tabela abaixo registra também os módulos sem nova divisão.

- `base/ui/form_tab_groups.py` contém tuplas de nomes exatos por recurso.
- `build_resource_form_layout` distribui somente os `BoundField`s visíveis do
  formulário recebido. Não cria campos a partir do modelo nem recupera controles
  excluídos pela autorização; mantém o próprio objeto do campo, seus widgets,
  valores, querysets e o estado `disabled`.
- Campos visíveis novos/não classificados permanecem em **Geral**. Campos ocultos
  continuam no renderer existente, fora da distribuição dos campos visíveis.
- Só entram grupos de pai com campos presentes. Se sobra menos de dois grupos,
  ou não há campos para Geral, conserva-se o fallback anterior: formulário simples
  sem inline, ou Geral mais os inlines existentes. Assim formulários reduzidos,
  inclusive o teste sintético de Compras com `product/version`, não ganham abas vazias.
- Geral é a primeira aba do pai. Erros de campo selecionam sua própria aba;
  erros não associados a campo priorizam Geral. Erros dos filhos e da management
  form continuam abrindo o inline, com a mesma avaliação de erros existente.
- Inlines, inclusive os indisponíveis por permissão, são anexados sem alterar
  disponibilidade, permissões de inclusão/edição/exclusão, prefixes ou instâncias.
  Uma aba não é um mecanismo de autorização.
- Há um formulário e uma transação de gravação, como antes. O agrupamento não
  altera models, serviços, persistência, permissões ou registry. Uma regressão
  identificada na integração foi corrigida no renderer horizontal compartilhado:
  ele também preserva `rgn_layout_class`, sem retirar as colunas Bootstrap.
- Fórmula mestra mantém a divisão especial Produto → Fórmula mestra → Componentes,
  inclusive no reaproveitamento. Nenhum fluxo de reaproveitamento foi inventado
  para Compras: o registry oferece essa ação somente para fórmulas.
- Não há campo novo de auditoria. Observações contém somente campos já existentes;
  datas/atores de auditoria excluídos pelo form builder não são reintroduzidos.
- Financeiro continua recebendo o formulário sem `SERVICE_FIELDS`; status,
  agregados e aprovações do serviço não são restabelecidos pelo layout.

## Compras

- **Pedido**: Geral → Condições comerciais → Entrega e endereço → Observações →
  inline de itens já existente. Datas de entrega e condições de entrega ficam
  junto do endereço; pagamento, moeda, frete e total ficam nas condições comerciais.
- **Recebimento**: Geral → Qualidade e fiscal → Observações → inline de itens.
  XML protegido, chave/hash NF-e e status de qualidade/estoque permanecem exatamente
  os campos autorizados pelo formulário existente.
- **Proposta do fornecedor**: Geral → Condições comerciais → Entrega → Observações.
- **Evento de qualificação do fornecedor**: Geral → Qualificação e bloqueio → Local
  e endereço. O bloqueio continua sendo a regra de domínio existente.
- Requisições e solicitações de cotação são cabeçalhos curtos, mantidos sem nova
  divisão. Também não se fragmentam artificialmente editores individuais de itens.

## Revisão dos módulos

| Módulo | Recursos revisados | Agrupados | Somente leitura | Seleção |
|---|---:|---:|---:|---|
| `auxiliary` | 14 | 0 | 0 | Sem nova divisão de campos |
| `masters` | 7 | 3 | 0 | `products`, `partners`, `sites` |
| `formulations` | 4 | 0 | 0 | Divisão especial de fórmulas e demais editores preservados |
| `production` | 2 | 1 | 0 | `orders` |
| `planning` | 8 | 1 | 1 | `mrp-runs` |
| `procurement` | 9 | 4 | 0 | `supplier-quotations`, `supplier-qualification-events`, `orders`, `receipts` |
| `inventory` | 4 | 1 | 1 | `lots` |
| `costing` | 6 | 3 | 0 | `standard-costs`, `simulations`, `production-captures` |
| `finance` | 7 | 1 | 1 | `titles` |
| `fiscal` | 16 | 3 | 3 | `companies`, `tax-rules`, `documents` |
| `crm` | 14 | 5 | 0 | `customer-profiles`, `opportunities`, `contracts`, `orders`, `complaints` |
| `quality` | 6 | 5 | 0 | `specifications`, `samples`, `analyses`, `investigations`, `documents` |
| `qa` | 7 | 3 | 0 | `reviews`, `blocks`, `training-requirements` |
| `documents` | 6 | 1 | 4 | `controlled-documents` |
| `deviations` | 6 | 1 | 1 | `events` |
| `capa` | 6 | 1 | 1 | `records` |
| `changes` | 6 | 1 | 0 | `controls` |
| `audits` | 8 | 1 | 2 | `plans` |
| `risks` | 7 | 1 | 1 | `records` |
| `recalls` | 6 | 3 | 2 | `complaints`, `returns`, `campaigns` |
| `training` | 9 | 3 | 1 | `requirements`, `sessions`, `enrollments` |
| `files` | 4 | 1 | 3 | `access-rules` |
| `reports` | 6 | 1 | 2 | `definitions` |
| `workflow` | 8 | 1 | 4 | `tasks` |
| `integrations` | 5 | 0 | 2 | Editores curtos/configuração mantidos sem nova divisão |
| `ai_agents` | 4 | 1 | 2 | `profiles` |
| `knowledge` | 6 | 0 | 6 | Somente leitura |
| `governance` | 5 | 1 | 2 | `institution-settings` |
| `compliance` | 4 | 1 | 3 | `policies` |

Os recursos não selecionados conservam seu layout anterior: cadastros auxiliares
curtos, relações/itens, eventos lineares e os inlines genéricos. Recursos somente
leitura, cockpits, kanban, Gantt e boards de execução não recebem novo renderer nem
novo comportamento; a seleção acima diz respeito aos formulários CRUD.

## Modelos e seções selecionados

Abas dos filhos não estão repetidas nesta tabela: continuam sendo anexadas pelo
renderer compartilhado quando configuradas no registry.

| Recurso | Modelo | Abas do formulário pai |
|---|---|---|
| `masters/products` | `Product` | Geral → Classificação → Qualidade e conservação → Fiscal |
| `masters/partners` | `BusinessPartner` | Geral → Qualificação e bloqueio → Contato → Endereço |
| `masters/sites` | `Site` | Geral → Endereço |
| `production/orders` | `ProductionOrder` | Geral → Programação → Observações |
| `planning/mrp-runs` | `MRPRun` | Geral → Parâmetros do cenário → Observações |
| `procurement/supplier-quotations` | `SupplierQuotation` | Geral → Condições comerciais → Entrega → Observações |
| `procurement/supplier-qualification-events` | `SupplierQualificationEvent` | Geral → Qualificação e bloqueio → Local e endereço |
| `procurement/orders` | `PurchaseOrder` | Geral → Condições comerciais → Entrega e endereço → Observações |
| `procurement/receipts` | `PurchaseReceipt` | Geral → Qualidade e fiscal → Observações |
| `inventory/lots` | `StockLot` | Geral → Origem e rastreabilidade → Fabricação e validade → Observações |
| `costing/standard-costs` | `StandardCost` | Geral → Composição de custos → Observações |
| `costing/simulations` | `CostSimulation` | Geral → Custos e capacidade → Premissas |
| `costing/production-captures` | `ProductionCostCapture` | Geral → Custos e desvios → Observações |
| `finance/titles` | `FinancialTitle` | Geral → Vínculos e referências → Valores e vencimento → Observações |
| `fiscal/companies` | `FiscalCompany` | Geral → Endereço |
| `fiscal/tax-rules` | `TaxRule` | Geral → Aplicação fiscal → Alíquotas → Observações |
| `fiscal/documents` | `FiscalDocument` | Geral → Emissão eletrônica → Vínculos → Totais → Observações |
| `crm/customer-profiles` | `CustomerProfile` | Geral → Crédito e condições → Observações |
| `crm/opportunities` | `Opportunity` | Geral → Previsão comercial → Resultado → Observações |
| `crm/contracts` | `SalesContract` | Geral → Condições e vigência → Requisitos regulatórios → Observações |
| `crm/orders` | `SalesOrder` | Geral → Condições comerciais → Entrega e endereço → Observações |
| `crm/complaints` | `CustomerComplaint` | Geral → Rastreabilidade → Resolução → Localidade |
| `quality/specifications` | `AnalyticalSpecification` | Geral → Limites e aceitação → Vigência → Observações |
| `quality/samples` | `QualitySample` | Geral → Origem → Coleta e execução → Observações |
| `quality/analyses` | `QualityAnalysis` | Geral → Método e insumos → Execução e revisão → Observações |
| `quality/investigations` | `LaboratoryInvestigation` | Geral → Investigação e conclusão → Repetição e reamostragem |
| `quality/documents` | `QualityDocument` | Geral → Conteúdo e evidência |
| `qa/reviews` | `QAReview` | Geral → Vínculos e dossiê → Observações e rejeição |
| `qa/blocks` | `QualityBlock` | Geral → Alvos e referências → Desbloqueio |
| `qa/training-requirements` | `TrainingRequirement` | Geral → Público e aplicação → Validade e obrigatoriedade → Observações |
| `documents/controlled-documents` | `ControlledDocument` | Geral → Versão e vigência → Conteúdo e alterações |
| `deviations/events` | `QualityEvent` | Geral → Abrangência e vínculos → Severidade e criticidade → Encerramento |
| `capa/records` | `CapaRecord` | Geral → Origem → Causa e plano → Eficácia → Encerramento |
| `changes/controls` | `ChangeControl` | Geral → Escopo e impacto → Planos e implementação → Encerramento |
| `audits/plans` | `AuditPlan` | Geral → Escopo e equipe → Programação e execução → Local e endereço → Encerramento |
| `risks/records` | `RiskRecord` | Geral → Avaliação → Tratamento e monitoramento → Encerramento |
| `recalls/complaints` | `MarketComplaint` | Geral → Rastreabilidade → Triagem e investigação → Comunicação regulatória → Localidade → Encerramento |
| `recalls/returns` | `ProductReturn` | Geral → Produto e origem → Recebimento e inspeção → Encerramento |
| `recalls/campaigns` | `RecallCampaign` | Geral → Origem e decisão → Responsáveis e prazos → Encerramento |
| `training/requirements` | `TrainingRequirement` | Geral → Público e referências → Avaliação e validade → Observações |
| `training/sessions` | `TrainingSession` | Geral → Programação e instrutor → Local e endereço → Observações |
| `training/enrollments` | `TrainingEnrollment` | Geral → Convocação e avaliação → Certificação e validade → Revogação |
| `files/access-rules` | `ProtectedFileAccessRule` | Geral → Origem e escopo → Observações |
| `reports/definitions` | `ReportDefinition` | Geral → Filtros e execução → Acesso e responsável |
| `workflow/tasks` | `ApprovalTask` | Geral → Origem e escopo → Atribuição e análise |
| `ai_agents/profiles` | `AIAgentProfile` | Geral → Modelo e instruções → Fontes autorizadas |
| `governance/institution-settings` | `InstitutionSettings` | Geral → Contato → Endereço |
| `compliance/policies` | `TransversalRequirementPolicy` | Geral → Controles exigidos |

## Verificação automatizada e reprodução segura

`tests/test_resource_form_domain_tabs.py` cobre:

- Campos reais de criação/edição dos recursos selecionados, sem duplicação/perda.
- GET de criação para cada recurso selecionado, IDs de abas/paineis e controles
  únicos, com management forms preservadas.
- GET de edição dos quatro recursos de Compras; a leitura não altera os registros.
- Campos ausentes/novos/ocultos/desabilitados, fallback de formulários reduzidos,
  erro não associado a campo e erros de todas as seções do pedido.
- POST inválido em Geral/Comercial/Entrega/Itens de pedido e Qualidade/Fiscal de
  recebimento, preservando valores e comprovando que não há gravação parcial.
- Management form ausente, criação/edição válida de pedido e recebimento,
  conservação da identidade dos itens e ausência de lançamento implícito de estoque.
- Permissões mínimas apenas do pai para pedidos e recebimentos: filhos não
  renderizados, payload forjado recusado e registros inalterados.
- Campos financeiros controlados pelo serviço continuam ausentes.

O teste aprovado `tests/test_resource_form_tabs.py` é executado **sem edição de seus
bytes**, junto com as regressões de tipagem, Financeiro, Compras, importação NF-e e
componentes de fórmula. Sua cobertura existente inclui GET de reaproveitamento,
campos bloqueados, filhos indisponíveis, exclusão e POST de fórmula.

**Isolamento:** PostgreSQL de fixture pública em `127.0.0.1:5433`; nome dedicado
na URL `cosmos_tabs_tests`, que o settings de testes transforma em
`test_cosmos_tabs_tests`. Não executar contra o banco operacional nem a porta 5432.
O settings base chama `read_env` incondicionalmente; passar apenas
`TEST_DATABASE_URL` não impede a leitura do `.env`. É necessário bloquear essa
leitura **antes** de importar Django/pytest:

```python
# Bootstrap local de testes, fora do settings operacional.
import os
import environ

environ.Env.read_env = classmethod(lambda cls, *args, **kwargs: None)
os.environ.update({
    'DJANGO_SETTINGS_MODULE': 'core.settings.test',
    'DATABASE_URL': 'postgresql://rgn_test:rgn_test@127.0.0.1:5433/cosmos_tabs_tests',
    'TEST_DATABASE_URL': 'postgresql://rgn_test:rgn_test@127.0.0.1:5433/cosmos_tabs_tests',
    'SECRET_KEY': 'synthetic-domain-tabs-test-bootstrap-only',
    'ALLOWED_HOSTS': 'localhost,127.0.0.1,testserver',
})
import pytest
raise SystemExit(pytest.main([
    'tests/test_resource_form_domain_tabs.py',
    'tests/test_resource_form_tabs.py',
    'tests/test_resource_form_typing_corrections.py',
    'tests/test_review_finance_ui_corrections.py',
    'tests/test_procurement.py',
    'tests/test_procurement_nfe_import.py',
    'tests/test_formula_inline_components_ui.py',
    '-q', '--reuse-db',
]))
```

Os dados/credenciais acima são exclusivamente a fixture pública de
`docker-compose.test.yml`. O bootstrap efetivamente usado na reexecução fica em
`/Users/rgnsystems/.hermes/cache/scratch/run_domain_tabs_tests.py`.
Não se altera `.env`, porta 5432, catálogos aprovados ou snapshots de evidências.

## Resultado observado

- RED da primeira fatia: `test_purchase_order_groups_commercial_and_delivery_fields_once`
  falhou com `[]` no lugar de `general/commercial/delivery/notes` antes da implementação.
- GREEN da primeira fatia e regressões unitárias existentes: **13 passaram**.
- RED da expansão declarativa: **94 falharam, 2 passaram**, pois os demais recursos
  ainda não tinham grupos. Após declarar os grupos: **96 passaram** nessa parametrização.
- A primeira execução HTTP encontrou **48 erros de fixture** por falta do argumento
  obrigatório `email` no novo `create_superuser`; isso foi corrigido somente no
  novo arquivo de testes, sem modificar testes aprovados.
- Reexecução final isolada, com bootstrap bloqueando `.env` antes dos imports:
  **338 passaram em 201,79 s**, sem falhas, erros ou skips. São **184 testes novos**,
  **35 do teste original de abas** e as regressões relacionadas descritas acima.
- Ruff passou nos três arquivos Python da implementação; `git diff --check` passou
  no helper alterado.
- SHA-256 do teste original de abas, igual aos bytes do HEAD:
  `33e08f405479feaa6e381160941074095c304570c41a855faa603ba294223f06`.
- Log/JUnit locais em scratch: `domain-tabs-final-green.log` e
  `domain-tabs-final-green.xml`. Não são catálogos regulatórios aprovados.

## Navegador e fechamento da integração

A rodada 2 usou respostas HTTP reais do Django, congeladas com dados sintéticos,
e assets reais: **192 casos únicos**, cobrindo os 48 formulários nas larguras
320, 768, 1024 e 1440 px, e **402 trocas de abas**. Outros **128 cenários**
cobriram pedidos/recebimentos em criação/edição: validação nativa com campo em
aba inativa, foco, ausência de loader bloqueado, teclado, inclusão/exclusão de
itens, fallback sem JavaScript/Bootstrap, respostas inválidas e permissão restrita.

Não foi um teste de autenticação ou salvamento ponta a ponta no navegador:
o servidor de capturas aceita apenas GET; persistência é verificada pelos testes
HTTP isolados. Não representa validação da VPS ou aceite regulatório.

O agregador preserva uma flag inicialmente negativa na tabela de resultados de
Qualidade em 320 px. A tabela possui rolagem horizontal própria; uma verificação
adicional com foco nativo comprovou acesso aos controles, sem overflow do documento.
Não se declara que todas as métricas brutas de todas as transições passaram.
Também permanece em revisão a sobreposição parcial do chat flutuante com o
rodapé de ações em algumas capturas.

Artefatos: `~/.hermes/artifacts/rgnfarmasystemv2/cosmetics-training-seed-2026-10-20/domain-tabs-browser-round2/`.
Fingerprint histórico da rodada: `ef0f6fc2b31058dcd62994858528a878aaaa57ee74622ba9cda065cc6ddd9f3c`.
**A correção posterior do renderer horizontal mudou a fonte: essa rodada não
aprova automaticamente o candidato atual; a recaptura permanece pendente.**

A primeira execução integral encerrou com 3 falhas, 2.877 testes aprovados, 42 subtestes
aprovados e 4 skips. A falha de classes responsivas foi reproduzida e corrigida
com RED/GREEN: `tests/test_resource_form_field_metadata.py` cobre os dois layouts
e quatro tamanhos, sem editar o teste original de abas. A integração posterior
com abas e widgets temporais aprovou **247 testes**, sem falhas ou skips.
Os limites de readiness e o gate de cobertura de 80% não foram flexibilizados.

A segunda execução integral aprovou o gate de cobertura (**86,45%**), mas não
os testes: **2 falhas, 2.886 aprovados, 42 subtestes aprovados e 4 skips**. Falharam
um checkpoint de sincronização do cancelamento (`Event.wait(10)`) e o carregamento
de uma fixture dotenv. As três falhas da primeira execução não reapareceram.

Sem alterar produção, testes ou deadlines, a reexecução isolada sob coverage,
com diretório temporário explicitamente dentro do scratch, aprovou os **10 testes**
do conjunto de falhas/readiness. A ampliação para todo o módulo de correções de
cancelamento e o wrapper de ambiente aprovou **16 testes**. Isso não substitui um
PASS integral nem prova a origem da falha intermitente de sincronização.

O runner local corrigido fixa `TMPDIR` e um `--basetemp` único sob o scratch,
compatível com o guard que permite somente fixtures pytest e bloqueia dotenv
operacional. Um teste de encaminhamento confirmou recusa do caminho operacional
sem ler seu conteúdo.

A terceira execução integral, com o runner corrigido, encerrou com **1 falha,
2.887 aprovados, 42 subtestes aprovados e 4 skips**; a cobertura permaneceu em
**86,45%**. As falhas da rodada anterior não reapareceram. Falhou o limite de
`future.result(timeout=10)` em
`test_reserve_and_issue_materials_opposite_allocations_do_not_deadlock`.

Três execuções isoladas desse teste, sob coverage e observação limitada ao banco
sintético, passaram sem mudar seus limites. Os corpos instrumentados demoraram
de 1,7074 a 2,5419 segundos; não houve erros SQL ou incremento do contador de
deadlocks nessas amostras. Foram observadas esperas transitórias por transação,
compatíveis com serialização. Isso não prova a causa do timeout ocorrido na suíte
completa, nem exclui um problema dependente da ordem/carga. Não houve alteração
de produção ou das assertions para obter esses resultados.

Evidências: `ui-full-corrected-20261020T185436Z/` e
`lock-diagnostic-{1,2,3}.{json,xml}` no diretório de validação local. A aprovação
integral continua ausente; não foi iniciada uma quarta repetição completa sem
nova hipótese ou definição do ambiente de verificação.

### Integridade de duas imagens históricas

A revisão independente detectou divergência entre dois PNGs de validação nativa
de pedido em 320/768 px e os hashes registrados na rodada 2. A causa foi uma
reexecução que reutilizou nomes de imagens antes de o registro duplicado ser
ignorado. As duas referências foram **invalidadas**, não revalidadas pela simples
troca dos hashes. O manifesto original e os bytes atualmente disponíveis foram
arquivados; `capture-integrity-disposition.json` registra a proveniência e a lacuna.

O helper de captura agora reserva arquivos de forma exclusiva e usa nomes únicos;
dois testes de regressão demonstraram RED e GREEN. A recaptura específica desses
dois casos permanece pendente após falhas de interação nativa com o select no
harness. Não se declara íntegro todo o pacote histórico nem se usam imagens de
uma fonte diferente como recuperação das imagens originais.

### Recaptura focada após a correção do renderer

Empresas fiscais e pedidos de compra foram novamente renderizados por HTTP real
e abertos em Chrome 145, nas dimensões efetivas de 320 × 1000 e 1440 × 1000 px.
Os **4 casos** produziram **26 capturas únicas**, com **14 cliques de abas** na
matriz, quatro verificações de campo obrigatório em aba inativa e quatro de
navegação por seta. Classes de tamanho, IDs e valores temporais foram conferidos;
os campos inválidos receberam foco visível, sem loader. Console e rede ficaram
sem erros no escopo coletado. Não houve requisição de gravação.

Fingerprint: `91f94683eea1fe84b447d62c963c6f3b92ccca3bc43344e8b18cee6e3ab8cfe0`.
Evidências em `domain-tabs-browser-round3-focused/`, ao lado da rodada anterior.
O parecer visual é **REVISE (88/100)**: o chat flutuante ainda se sobrepõe à região
inferior de campos em 320 px. É necessário reservar espaço ou reposicioná-lo e
recapturar os mesmos estados. Este recorte não substitui a matriz completa dos
48 formulários, nem comprova autenticação ou persistência pelo navegador.

Promoção e deploy seguem bloqueados até aprovação integral/cobertura, fechamento
da revisão e recaptura do candidato, além de autorização específica para homologação.
O usuário autorizou somente commit/push do candidato e atualização da PR em
rascunho para executar o CI Linux, sem merge ou deploy. Isso permite a verificação
remota, não aprova a entrega nem encerra as pendências visuais/de proveniência.
Identidade publicada e resultados do CI devem ser vinculados à execução exata,
separadamente dos resultados locais históricos registrados neste documento.
