# Correções de integridade de estoque — D1, D4, D5 e revisão

## Escopo

Mantido o monólito e os serviços existentes, sem modelos novos ou migrations.
Execução exclusivamente na cópia scratch e PostgreSQL isolado `inventory`, pela imagem
`rgnfarmasystem:corrections-clean-tests`. Não houve acesso a produção, rede de produção,
dados reais, segredos, alterações de dependências/configuração/deploy ou commit.

## Contratos originais preservados

- Ledger não é CRUD: movimentos genéricos POST/PUT/PATCH retornam 405; retenção nega DELETE.
  Admin de movimentos não permite inclusão/edição/exclusão; serializer rejeita escrita genérica.
- `POST /api/inventory/movements/issue/` executa saída real, exige permissão e ator,
  valida saldo disponível, unidade, endereço e vencimento; debita e audita atomicamente.
- `POST /api/procurement/receipts/{id}/post_stock/` exige `warehouse` e `location` explícitos.
  Qualidade aprovada, endereço ativo, pedido/produto/unidade, reconciliação, lote e validade
  são validados antes de lançar. Somente depois dos efeitos o recebimento fica `stock_posted`/`posted`.
- Cancelamento bloqueia ordem → alocações → saldos, libera apenas reserva não consumida e
  cria compensação `release_reservation` vinculada à reserva original, ordem, consumo e ator.
  Retry pelo mesmo ator não duplica compensação/auditoria; outro ator é recusado.
- Históricos marcados sem movimentos não são silenciosamente reparados. Reconciliação de
  dados históricos exige análise e remediação auditada, fora deste patch.

## Seis bloqueadores da revisão

### 1. Ordem dos locks de saldo e sequência

Recebimento agora incrementa/bloqueia saldo **antes** da sequência de identificadores de
movimento, como a saída. Callers em lote de compras e produção preparam todos os lotes
em ordem estável e bloqueiam **todos** os saldos existentes por PK; saldos novos são
criados em ordem estável de dimensões, antes de gerar qualquer movimento do lote.
Não basta inverter duas linhas no helper: o primeiro movimento manteria a sequência
bloqueada enquanto o caller tenta obter o saldo do segundo item.

Locks dos lotes usam PostgreSQL `NO KEY UPDATE`, pois a identidade não muda. Isso mantém
serialização entre recebedores sem impedir o `KEY SHARE` da FK de uma saída concorrente.
A revisão reproduziu também esse segundo deadlock quando apenas a ordem saldo/seq foi corrigida.
Retries com movimento já existente não preparam novo lote/saldo: não reaplicam quantidade,
não restauram disposição de qualidade e não recriam saldo histórico ausente.

Evidência: duas conexões reais reproduziram `deadlock detected` no RED; GREEN concluiu
recebimento+saída com saldo 142.0000 e três movimentos. Outro teste observa em
`pg_stat_activity` a saída bloqueada no saldo do segundo item, não na sequência.
Produção verifica com NOWAIT de outra conexão que o segundo saldo já está bloqueado
quando o primeiro identificador é solicitado; executa o fluxo legítimo completo até recebimento.

### 2. PATCH de consumo após cancelamento

API agora usa protocolo atômico ordem → alocação, relendo o objeto bloqueado e validando
antes do save. O serializer persiste apenas os campos enviados. O model também bloqueia
ordem antes da alocação, preserva valores atuais não alterados e usa snapshot `from_db`
para distinguir mudanças intencionais de uma instância desatualizada sem `update_fields`.
Alteração de ordem é negada. Ordens `cancelled`, `completed`, `closed` não aceitam criação
ou edição de alocações; leitura/validação sem mudança de evidência continua possível.
Erros de domínio durante save viram DRF 400.

Admin de consumo e inline negam edição terminal; POST administrativo obtém lock da ordem
antes de construir/validar formulário/alocação. Admin de ordem também bloqueia a ordem
antes de ler os inlines. Testes incluem PATCH carregado antes do cancelamento, save direto
stale e POST Admin real nos três estados terminais, preservando quantidade/vínculo de devolução.

### 3. Admin e transições genéricas com efeitos de estoque

Estados e metadados de ciclo de vida são readonly em `PurchaseReceiptAdmin` e
`ProductionOrderAdmin` (atores e datas também). `PurchaseReceipt.save()` recusa a promoção
genérica para `stock_posted`/`posted`; somente `post_stock` autoriza sua persistência depois
dos efeitos. `ProductionOrder.save()` recusa cancelamento genérico e reescrita da evidência
de cancelamento; `cancel` autoriza o save depois de liberar reservas. Outros helpers
preexistentes de ciclo de vida permanecem intactos.

POSTs Admin reais com estados forjados concluem com 302 e salvam observações legítimas,
mas deixam estados, reservas e ledger intactos. Não se confundiu formulário inválido
com uma negativa de segurança.

### 4. Django ValidationError durante CRUD de recebimento

`PurchaseReceiptViewSet.perform_create/perform_update` traduzem erros de save para DRF 400.
Reconstrução de model para validação de serializer preserva `_state.adding=False` e DB:
sem isso o teste parecia passar por um erro de unicidade não relacionado, escondendo o 500
real. O teste exige a chave de erro `receipt`, além do HTTP 400, e documento fiscal intacto.

### 5. Quantidade aceita acumulada por item do pedido

`post_stock` bloqueia todos os `PurchaseOrderItem` envolvidos por PK, com `NO KEY UPDATE`.
Sob esses locks soma entradas `receipt` já contabilizadas no ledger por item do pedido e
as quantidades aceitas do recebimento atual, incluindo itens repetidos no mesmo recebimento.
O helper de entrada direta adquire o mesmo lock e aplica o mesmo teto; entradas diretas
contam no cumprimento físico mesmo antes de a flag de recebimento ser concluída.
Retries não duplicam contagem. Um excesso reverte o recebimento inteiro.

**Política explícita:** quantidade rejeitada não cumpre o pedido nem entra no saldo aprovado.
Reposição de rejeitados é permitida enquanto `accepted_cumulative <= ordered_quantity`.
Exemplo testado: pedido 50, primeira aceitação 48/rejeição 2, reposição aceita 2 permitida;
uma aceitação adicional 1 é recusada. Dois recebimentos concorrentes de 48 para o mesmo
item de 50 produzem exatamente um sucesso 200 e uma recusa 400, não 96 em estoque.
Mantém-se também o teto preexistente de quantidade recebida em cada item individual.

### 6. HTML post_stock e origem do catálogo

`base/ui/actions/modules/procurement.py` contém somente `ACTION_KEYS`; a fonte dos campos
é `base/ui/actions/inventory.py`, consumida por `factory.action_config`/`fields_for`.
Não foram criadas duas fontes. Para `post_stock` foi adicionada a entrada
`warehouse:r,location:r`, rótulos e factories das relações correspondentes. A integração
adicional de saída abaixo usa a mesma origem de campos, sem duplicá-la.

O framework existente gera `ModelChoiceField` e serializa as seleções como IDs. Querysets
exigem a permissão `masters.view_warehouse`/`masters.view_storagelocation` e filtram unidade,
almoxarifado e localização ativos. GET com `warehouse` e POST filtram localizações pelo
almoxarifado selecionado; GET inicial permite escolher entre endereços ativos autorizados.
POST com endereço incompatível apresenta erro no campo e não produz efeitos. A API
continua validando o endereço independentemente do HTML. Testes reais de GET/POST da ação
verificam formulário, redirect, saldo 48, movimento vinculado e recusa de mismatch/inativos.
Não foram editados `base/ui/registry.py` nem `base/ui/views.py` nesta revisão.

## Integração adicional — saída no catálogo HTML

Criado `base/ui/actions/modules/inventory.py` com a chave `movements/issue` e incluído
no agregador de módulos. Campos em `actions/inventory.py`: `stock_balance` (relação),
`quantity` (mínimo 0.0001), `reference` (opcional, até 120), `notes` (opcional, até 4000).
A ação exige confirmação e somente `inventory.add_stockmovement`. As opções de saldo
são aprovadas, não vencidas, com disponibilidade e endereço ativo/coerente.

`StockIssueSerializer` aceita o contrato novo baseado em saldo sem remover o contrato
anterior de produto/lote/unidade/endereço/motivo. Não aceita sobrescrever dimensões quando
um saldo é selecionado. Deriva as dimensões, usa o mesmo helper que relê/bloqueia saldo,
registra referência e observações no movimento e determina o ator pela sessão.
Excesso retorna API 400; HTML exibe o erro de quantidade sem novos efeitos.

`base/ui/actions/views.py` mantém CSRF e autenticação e aplica a permissão da ação
especificamente à saída de coleção, sem exigir permissão genérica de consulta do ledger.
Os demais recursos mantêm seu gate original. Operador add-only retorna ao formulário
autorizado depois do sucesso, não a uma listagem proibida. Testes verificam sucesso
add-only real, ator/referência, excesso, tampering, 403 sem permissão/CSRF e login obrigatório.
Não foram alterados `base/ui/views.py` nem `base/ui/registry.py`.

Validação em Python: conjuntos de descoberta e catálogo **idênticos**, 233 ações,
227 de detalhe e 6 de coleção. Só as constantes dessas cardinalidades foram atualizadas
em `tests/test_action_discovery.py` e `tests/test_action_catalog_completeness.py`.
O endpoint não foi ocultado por whitelist e não houve deselection no gate final.

## Ajustes de setup legado, sem enfraquecer asserções

A primeira regressão completa teve 332 passes/12 falhas por fixtures que criavam/editavam
alocações após concluir a ordem, ou cancelavam por save genérico. Após exigir gate completo,
foram ajustados apenas os setups correspondentes em `tests/test_production_operations.py`:
preparação de materiais/evidências antes da conclusão; cenários de crescimento e construção
do segundo snapshot em estado operacional; fixtures canceladas via helper explícito.
As asserções de genealogia, rollback, custo, idempotência, concorrência, status terminal e
quantidade de queries foram preservadas. Não se abriu exceção no domínio para esses testes.
As duas negativas Admin também comprovam 302 e observações legítimas salvas, evitando falso
verde por formulário inválido. A proteção de saldos HTML zero/metadados do agente de
segurança permaneceu intacta.

## Evidência e resultados finais

Logs RED/GREEN: `/home/deploy/.hermes/cache/scratch/stock-review-fix*.log`.
Casos em `tests/test_inventory_corrections.py`, `tests/test_purchase_posting_corrections.py`
e `tests/test_production_cancellation_corrections.py`.

- Correções isoladas finais: **47 passed**, em `stock-review-fix-final-new-green.log`.
- Gate domínio + discovery/catalog, sem exclusões: **354 passed**, em
  `stock-review-fix-final-domain-actions-green.log` (antes do teste adicional de CSRF).
- Gate ações/segurança/saída HTML: **114 passed**, em
  `stock-review-fix-issue-actions-security-green.log`.
- Gate final combinado domínio completo + todas as suítes `test_action*.py` + segurança
  corrections/UI-ledger/file-actions: **454 passed**, sem falhas, skips ou deselections,
  em `stock-review-fix-final-integrated-green.log`.
- Ruff check/format e `git diff --check` passaram; `makemigrations --check --dry-run`
  de inventory/procurement/production retornou `No changes detected`.

Os logs intermediários de falha/exclusão foram mantidos como histórico RED, não como
resultado final. Não há pendência conhecida nos gates executados deste escopo. O gate
mais amplo do responsável pelo freeze e a reconciliação de eventuais dados históricos
continuam fora desta validação isolada; não houve autorização para ações em produção.

## Apêndice final — seams da API e integridade do item de compra (ciclo 2)

Correções limitadas aos dois bloqueadores da segunda revisão e à sugestão de integridade
já reportada; não foi adicionada imutabilidade global de quantidade nem alterado o domínio
financeiro, os guards dos models de produção ou o framework HTML.

### PATCH da ordem cancelada

`ProductionOrderSerializer.update` converte `DjangoValidationError` do guard de save em
DRF HTTP 400. PATCH de `cancel_reason` após cancelamento legítimo mantém justificativa,
status, ator e data originais, sem repetir/liberar novamente reservas. `status`,
`cancelled_by` e `cancelled_at` continuam readonly e sua presença na escrita genérica é
explicitamente recusada, não silenciosamente descartada. Uma edição validada antes do
cancelamento também é recusada no save pelo guard terminal existente, que relê sob lock.

### Identidade do saldo selecionado na saída

O serializer recusa seleção bloqueada e preserva `stock_balance_id` até `issue_stock`.
O parâmetro novo é keyword-only e opcional: callers legados sem ID continuam resolvendo
as dimensões como antes. Com ID, o helper bloqueia/reconsulta **aquele PK**, confronta
produto, lote, almoxarifado, localização e disposição de qualidade, revalida unidade,
endereço, vencimento e disponibilidade e somente então debita. Não troca um saldo
bloqueado por outro aprovado de dimensões iguais, inclusive quando o bloqueio ocorre
após `is_valid`. A ordem de locks permanece saldo → sequência de movimento; o caminho
novo não adquire outro saldo depois da sequência. O dispatcher HTML existente já envia
o ID à API; não foi necessário modificar módulos de ações, views, forms ou registry.
Permissões add-only e CSRF permanecem nos gates existentes.

### Quantidade do item do pedido vs aceitação contabilizada

`PurchaseOrderItem.clean` recusa quantidade inferior à soma de entradas `receipt` reais
vinculadas ao item. `save` adquire o mesmo lock PostgreSQL `NO KEY UPDATE` usado pelo
posting e relê o total do ledger **depois** de obtê-lo, dentro da transação. Não adquire
locks de recebimento/saldo/sequência e evita inversão com o posting. O serializer traduz
a negativa de save concorrente em HTTP 400. Um PATCH de 50 para 1 após aceitação de 48
é recusado sem mutação; 48, 49 e 60 continuam permitidos. Os 2 rejeitados do recebimento
50 não contam como cumprimento. Sem aceitação contabilizada, reduzir para 1 continua
permitido mesmo com recebimento pendente. Escrita direta de model aplica a mesma regra.
Os testes concorrentes observam `pg_blocking_pids` para provar espera no lock compartilhado:
posting vencedor recusa edição para 1; edição vencedora recusa posting de 48. Outro teste
HTTP sincroniza duas conexões para posting entre validação e save da edição.

### Evidência do ciclo 2

- RED→GREEN vertical em `/home/deploy/.hermes/cache/scratch/stock-api-review-fix-*.log`:
  500→400 no PATCH; 200→400 para metadados readonly; 201→400 para seleção bloqueada e
  corrida após validação; 200→400 para quantidade insuficiente; save direto/concorrente.
- `tests/test_review_stock_api_corrections.py`: **21 passed**, runner e imagem solicitados,
  em `stock-api-review-fix-final-new-green.log`.
- Gate dirigido de estoque/compras/produção existentes, correções, todas as suítes
  `test_action*.py` e segurança UI-ledger: **424 passed**, sem skips, deselections,
  exclusões novas ou relaxamento de asserções, em
  `stock-api-review-fix-final-directed-green.log`. Não foi executada a suíte global.
- Ruff check + format, MyPy dos 7 arquivos Python modificados, Bandit dos 6 arquivos de
  produção e `git diff --check` passaram. `makemigrations inventory procurement production
  --check --dry-run` retornou `No changes detected`; zero migrations, em
  `stock-api-review-fix-quality-gates.log`.

Execução no PostgreSQL sintético isolado `inventory`, sem produção ou dados reais.
Os ajustes de fsync do harness são somente de teste e não evidência de durabilidade.
Fresh review independente e freeze global permanecem sob responsabilidade do agente pai.
