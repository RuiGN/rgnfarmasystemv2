# Correções financeiras D2/D3 e revisão financeira

## Escopo

As alterações ficam em `finance/`, `tests/test_finance_corrections.py` e neste
registro. Não houve alteração de `base/ui`, settings, dependências, deploy,
ambiente de produção ou commits. Não há novos campos, migrations ou permissões.
Não há reconstituição automática de dados históricos.

Esta revisão acrescenta ao patch D2/D3 a proteção dos CRUDs de título/conta, a
imutabilidade econômica do título após lançamento, transições com estado
persistido bloqueado e tratamento transacional de rejeições no admin.
A aprovação independente posterior e a suíte global continuam com o pai.

## 1. Escrita de título/conta não substitui uma linha desatualizada

`LockedFinanceEditMixin` registra os valores carregados por `from_db()` e após
escritas bem-sucedidas. `save()` de registro existente abre uma transação, relê a
linha com `select_for_update()` e aplica apenas os campos selecionados:

- Com `update_fields`, somente esses campos participam da escrita.
- Sem `update_fields`, somente diferenças em relação aos valores originalmente
  carregados participam da escrita. Uma anotação/nome alterado não traz junto os
  agregados antigos da instância.
- Carregamento lazy/`refresh_from_db(fields=...)` atualiza somente o baseline dos
  campos relidos, sem apagar uma alteração ainda não salva em outro campo.
- A política concreta valida a candidata bloqueada antes da persistência. Após
  sucesso, o chamador recebe o estado gravado; caches das relações vêm da linha
  relida, não da instância antiga.

Os serializers de título/conta também relêem sob lock e usam explicitamente os
campos de `validated_data`. Erros de domínio na gravação viram HTTP 400, inclusive
quando uma baixa ocorreu entre `is_valid()` e `save()`.

`paid_amount`, `open_amount`, `status`, `approved_by` e `approved_at` pertencem ao
serviço de título; `current_balance` pertence ao serviço de conta. Alterações
intencionais pelo save genérico são rejeitadas. Os agregados são somente leitura
na API e no admin; atributos enviados para campos read-only da API são ignorados,
sem afetar os valores persistidos. Valores idênticos não constituem alteração.

O admin do título grava `form.changed_data` explicitamente, para não confundir o
valor em aberto calculado para validação do formulário com uma edição autorizada.

A persistência interna `_save_finance_state()` é privada e é usada pelas operações
de domínio após a leitura bloqueada. Não chama o `save()` público novamente, nem
abre uma permissão genérica para sobrescrever agregados.

### Criação

- Título novo tem valor original positivo, pago zero e aberto igual ao original.
  Estados de baixa/cancelamento e metadados de aprovação forjados são rejeitados.
- API/admin criam título pendente. Por compatibilidade com chamadores model
  existentes, `objects.create(status=APPROVED)` insere inicialmente pendente e
  executa `approve()` na mesma transação; não grava arbitrariamente o estado
  aprovado e não passa recursivamente pelo save público. Falha de aprovação
  desfaz a criação.
- Conta nova deriva o saldo atual do saldo inicial. O default zero ou o mesmo
  saldo inicial são normalizados; um saldo atual divergente informado diretamente
  no model é rejeitado.
- Novas instâncias não podem informar PK para sobrescrever outro título/conta.

`FinanceMetadataQuerySet` permite update/bulk_update apenas de metadados:
`notes` no título e nome/dados bancários/ativo na conta, além de `updated_at`.
Alterações econômicas/agregadas em lote e `bulk_create` são recusadas, pois
contornariam as validações/transições por registro. Editar economia antes da
primeira baixa continua possível por model, API e admin, não por bulk write.

## 2. Economia e direção do título após lançamento

Qualquer baixa existente, inclusive estornada, congela os seguintes campos do
título: tipo/direção, origem, parceiro, categoria, conta, pedido de compra, valor
original, emissão, vencimento e referências fiscal/contratual/comercial.

A comparação ocorre com os valores persistidos sob o mesmo lock usado por
`register_settlement()` e `reverse()`. Reenvio dos mesmos valores e edição de
`notes` continuam legítimos. Uma alteração econômica que se torna inválida entre
validação e gravação é rejeitada sem HTTP 500.

Antes da primeira baixa, editar valor original ou direção continua permitido.
`open_amount` é sempre derivado de `original_amount - paid_amount`, inclusive em
formulário/serializer de edição. O valor não é aceito como parâmetro econômico do
usuário. A direção usada no estorno permanece a do título congelado, portanto
não é necessária uma mudança de schema/snapshot neste patch.

O saldo inicial da conta é imutável após qualquer baixa vinculada. Antes disso,
uma edição legítima do saldo inicial ajusta o saldo atual pela diferença,
preservando movimentos já aplicados pelo serviço. Edição do nome não altera
nenhum dos saldos.

## 3. Transições relêem e validam o estado persistido

`approve()`, `cancel()` e `mark_overdue()` usam `atomic` e `select_for_update()`
no título. Não decidem com base no estado previamente carregado pelo chamador.

- Aprovação aceita apenas o estado persistido pendente/vencido.
- Cancelamento aceita apenas pendente/aprovado/vencido e recusa qualquer baixa
  ativa, mesmo se o status histórico do título estiver inconsistente.
- Marcação de vencimento respeita status e data persistidos. Não recoloca um
  título baixado em vencido; uma operação sem mudança também atualiza o chamador
  para refletir o registro atual.
- Cancelamento e baixa disputando o mesmo título produzem um único vencedor:
  título cancelado sem baixa, ou título baixado com cancelamento rejeitado.

Ordem de lock mantida para operações de baixa/estorno:

1. título;
2. baixa existente, quando aplicável;
3. conta.

Edição de conta/movimentos independentes adquirem somente conta. Edição de
anotação/conciliação adquirem somente baixa, sem adquirir depois título/conta.
A consulta de baixas ativas no cancelamento não toma lock invertido: registro e
estorno já precisam do lock do mesmo título antes de mudar uma baixa.

## 4. Admin: formulário real, validação e rollback

`FinancialSettlementForm` valida elegibilidade do título e calcula o líquido
antes do clean do model. Título pendente aparece como erro de formulário, não
como exceção de `save_model()` enviada ao usuário.

`FinanceDomainErrorAdminMixin` envolve o fluxo de changeform em um savepoint.
Uma `ValidationError` tardia desfaz as gravações e reconstrói o mesmo formulário
bound com os erros anexados; não executa novamente save_model/save_related.
O mixin é aplicado a baixa, título e conta. Erros de campos read-only/ausentes
são apresentados como erros não vinculados a campo, evitando o ValueError de
Django quando a validação do model referencia um campo excluído do formulário.

Esse tratamento não converte erros inesperados de banco/código em sucesso:
cuida exclusivamente de rejeições de domínio `ValidationError`.
As validações de título/baixa toleram campos ausentes durante validação de um
formulário inválido, sem fazer comparação numérica com `None` ou acessar uma
FK ainda não preenchida.

São testes HTTP reais do admin, não apenas chamadas diretas a save_model:

- POST de baixa em título pendente retorna 200 com erros e sem lançamento.
- Dois POSTs concorrentes, ambos inicialmente válidos para baixar 60 de 100,
  retornam 302 para o vencedor e 200 com erros para o perdedor; apenas uma baixa
  existe e os saldos são 40 aberto / 940 na conta.
- POST legítimo retorna 302 e contabiliza; líquido negativo mostra erro.
- Rejeição em save_related após registro reverte baixa, título e saldo.
- Inclusão/edição legítima de título calcula aberto sem oferecer agregados.
- Tentativa de alterar saldo inicial de conta com baixa mostra erro e reverte
  também os metadados enviados no mesmo POST.

O teste concorrente sincroniza em save_form, após validação e antes dos locks de
domínio. Nunca existe barreira depois de select_for_update.
O mixin usa o hook privado `_changeform_view` e o form usa `_update_errors`:
esses pontos precisam continuar cobertos por POST real em upgrades do Django.

## D3 preservado: baixa lançada é histórico

Toda baixa nova é registrada por `FinancialTitle.register_settlement()`, inclusive
criação por model/admin/UI. `FinancialSettlement.save()` delega a esse serviço.
Valor principal, juros, multa, desconto, líquido, título, conta, data, método,
referência, criação, status e metadados de conciliação/estorno são imutáveis no
save genérico; somente `notes` é anotação editável.

`reconcile()`/`reverse()` relêem a baixa bloqueada e são as operações oficiais
para seus metadados. Segundo estorno e conciliação após estorno são recusados.
Falha de validação, inclusive período fechado, reverte todos os efeitos.

Exclusão física continua proibida por model/queryset/admin; DELETE na API retorna
405 e não consta de Allow. Isso não proíbe indiscriminadamente todos os cadastros
financeiros nem altera `base/retention.py`.

Correção econômica de uma baixa: estornar com justificativa e registrar outra.
A proteção do título continua mesmo depois de estorno; não se altera a identidade
econômica de um histórico existente para reutilizá-lo com outra direção.

## Permissões e UI

Sem novas permissões. A matriz API usa usuários com uma única permissão:

| Usuário | Criar baixa | Conciliar | Estornar |
| --- | --- | --- | --- |
| add-only | 201 | 403 | 403 |
| change-only | 403 | 200 | 200 |
| view-only | 403 | 403 | 403 |

No admin, add-only inclui baixa; change-only/view-only recebem 403 na inclusão.
Os testes também verificam ausência de efeitos nos casos negados.
A integração já existente em `base/ui` foi apenas exercitada, não editada:
`test_finance_ui_creation_books_ledger_update_only_notes_and_delete_forbidden`
passa com criação contabilizada, update apenas de notes e exclusão negada.

## Evidências de TDD vertical

Diretório de logs: `/home/deploy/.hermes/cache/scratch/`.
Cada comportamento novo de produção foi precedido por execução RED real e teve
GREEN correspondente, sem implementar todos os testes antes de todas as regras.

| Slice | RED | GREEN |
| --- | --- | --- |
| 1, metadados stale model/API/admin | `finance-review-fix-red-1.log`, 6 falhas | `finance-review-fix-green-1.log`, 6 passaram |
| 2, agregados/criação protegidos | `finance-review-fix-red-2.log`, 11 falhas | `finance-review-fix-green-2.log`, 77 passaram incluindo baseline |
| 3, economia/direção e aberto derivado | `finance-review-fix-red-3.log`, 20 falhas | `finance-review-fix-green-3.log`, 20 passaram |
| 4, transições stale/concorrência | `finance-review-fix-red-4.log`, 4 falhas e 2 passaram | `finance-review-fix-green-4.log`, 6 passaram |
| 5, POST admin pendente/race | `finance-review-fix-red-5.log`, 2 HTTP 500 reproduzidos | `finance-review-fix-green-5b.log`, 2 passaram |
| 6, formulário com campos excluídos/inclusão título | `finance-review-fix-red-6.log` | `finance-review-fix-green-6.log`, 12 passaram |
| 7, bulk bypass/invariante/criação e edição admin | `finance-review-fix-red-7.log` e `red-7b.log` | `finance-review-fix-green-7.log`, 9 passaram |
| 8, título incompleto no admin | `finance-review-fix-red-8.log`, 1 falha e 5 passaram | `finance-review-fix-green-8.log`, 134 passaram incluindo integrações |
| 9, conta rejeitada no admin | `finance-review-fix-red-9.log`, 1 HTTP 500 | `finance-review-fix-green-9.log`, 1 passou |
| 10, baseline de campo deferred | `finance-review-fix-red-10.log`, 2 falhas | `finance-review-fix-green-10.log`, 2 passaram |

Não esconder execuções intermediárias: `green-5.log` ainda falhou por clean com
campos ausentes, antes do GREEN 5b. RED 6 incluiu nove erros de fixture por email
faltante, corrigidos antes do GREEN; esses erros não são prova de defeito de
permissão. As permissões e alguns cenários adicionais já passaram sem mudança de
produção e constituem cobertura positiva/negativa de regressão, não RED alegado.
RED 7 inicial encontrou colisão de identificador no teste de bulk_create; RED 7b
usa identificadores próprios e reproduz as seis ausências de proteção.

### Gate final desta revisão

```sh
python /home/deploy/.hermes/cache/scratch/run_rgn_tests.py \
  --db finance --image rgnfarmasystem:corrections-clean-tests \
  tests/test_finance_corrections.py tests/test_finance.py \
  tests/test_security_corrections.py tests/test_security_file_actions_regressions.py \
  tests/test_security_ui_ledger_regressions.py -v --no-cov
```

`finance-review-fix-green-final-2.log`: **189 passaram em 53,61 s**:
125 financeiros de correções, 10 financeiros existentes, 48 de segurança,
4 regressões de ações de arquivos e 2 regressões de UI/ledger.
O arquivo financeiro tinha 50 casos antes da revisão; agora possui 125.
Nenhum teste financeiro existente em `tests/test_finance.py` foi alterado.

Runtime efetivamente exercitado: Python 3.14.7, Django 6.0.8, PostgreSQL isolado
`test_finance`, imagem limpa indicada acima, sem rede de produção.
`finance-review-fix-concurrency-repeat-1.log` e `repeat-2.log`: **13 passaram por
execução**, respectivamente em 35,58 s e 35,41 s, sem deadlock. O gate final também
exercita esses 13 casos após a correção de deferred fields.

`finance-review-fix-quality.log`: Ruff passou, `git diff --check` passou e
`makemigrations finance --check --dry-run` retornou `No changes detected in app
'finance'`. Formatação Ruff aplicada somente aos arquivos próprios.
Cobertura não foi medida (`--no-cov`).

### Histórico anterior, não substitui a evidência nova

O gate D2/D3 anterior (`finance-corrections-green-final.log`) tinha 60 aprovados,
sendo 50 de correções e 10 existentes. Uma repetição histórica foi interrompida
por DiskFull no PostgreSQL de tmpfs; permanece registrada em
`finance-corrections-concurrency-repeat.log` e não conta como execução aprovada.
O runner e a recuperação do banco foram fornecidos pelo pai antes desta revisão.

## Limites

- Não há trigger de banco: SQL direto, managers internos, save_base e modelos
  históricos de migrations estão fora do contrato público. Nenhuma garantia de
  saneamento de dados já inconsistentes é feita.
- Coordenação concorrente entre fechamento/reabertura de período e registro de
  baixa permanece fora destes quatro bloqueadores. O rollback de estorno em
  período já fechado está coberto.
- Movimentos diretos de conta são operações de serviço existentes; não foram
  transformados em um novo histórico contábil nem em nova autorização pública.
- Gates não são homologação financeira/regulatória nem teste de produção.
- A revisão independente posterior e a suíte global do ERP não foram executadas
  por este workstream. Os resultados acima comprovam os cenários enumerados,
  não uma declaração de resolução de todo risco do sistema.

## Apêndice UI — correção pontual dos dois bloqueadores da fresh review (ciclo 2)

Este apêndice amplia **somente a integração da UI** do registro acima. As
referências anteriores a não alterar `base/ui` descrevem o workstream financeiro
anterior. Nesta etapa foram editados `base/ui/forms.py`, `base/ui/views.py`, criado
`tests/test_review_finance_ui_corrections.py` e acrescentado este apêndice.
`base/ui/registry.py` não precisou de alteração. Não foram editados models,
serializers/admin financeiros, ações, ACL, guards fiscais, estoque, settings,
dependências, deploy, `.env` ou produção. Não houve commit.

### 1. Formulário não autoriza agregados derivados

O provider existente de formulários, para `FinancialTitle` e `FinancialAccount`,
exclui os respectivos `SERVICE_FIELDS`. Assim, `open_amount`, `paid_amount`,
`status`, evidência de aprovação e `current_balance` não são controles de escrita.
POSTs legados/injetados com esses nomes são ignorados. Economia legítima antes da
primeira baixa continua editável, incluindo valor original, direção e saldo
inicial. Campos obrigatórios e metadados dos widgets continuam funcionando.

O `clean()` do título deriva o aberto da candidata antes do `_post_clean()` do
Django, que continua executando `model.full_clean()` normalmente. Essa derivação
é **somente para validação**: a gravação seleciona explicitamente os campos
editáveis de `changed_data` com `resource_save_kwargs()`, tanto no `save()` do
provider quanto no caminho `commit=False` da view. O protocolo financeiro já
existente relê/bloqueia a linha, aplica a política de imutabilidade e deriva o
saldo novamente. Nenhuma alteração enfraquece a validação de campos dirty do
model ou chama a persistência privada de agregados.

Resultado reproduzido por POST HTTP real de usuário comum com permissões de
view/change: título pendente sem baixa passa de original/aberto `100/100` para
`80/80`, HTTP **302**. Aberto injetado negativo/maior que o original, pago e
aprovação injetados não mudam a conservação nem criam evidência de aprovação.
Criação legítima de título sem aberto informado e conta com saldo inicial `100`
também retorna 302 com agregados derivados.

### 2. Rejeição financeira vira formulário bound, depois do rollback

`ResourceUpdateView.post()` mantém os handlers existentes e acrescenta tratamento
de `ValidationError` exclusivamente para recursos do app financeiro. O catch
ocorre **fora** de `save_object_and_inline_formsets()`/`atomic`: modelo,
relacionamentos, efeitos de ledger e eventos já foram revertidos antes de anexar
erros ao mesmo formulário bound e responder HTTP **200**. Não há retry do save,
redirect de sucesso ou captura de `PermissionDenied`/erros inesperados.

Erros tardios usam o helper existente que envia nomes de campos ausentes para
erros não vinculados a campo. O provider financeiro também normaliza esses nomes
no `_update_errors()`, evitando `ValueError` no próprio `_post_clean()` quando,
por exemplo, o valor original informado é menor que o principal já baixado.

Cobertura real contra PostgreSQL:

- alteração de direção/valor com baixa parcial, total ou estornada retorna 200
  com erro e mantém título, conta, baixas, fluxo previsto/realizado e eventos;
- estorno posterior continua usando a direção original e restaura o saldo;
- saldo inicial de conta com baixa ativa ou estornada não muda, nem o nome
  enviado junto ao POST rejeitado;
- payload stale de notes/nome mantém aberto/pago/status/evidência e saldo atual;
- validação de form anterior à baixa e save posterior mantêm o ledger recente,
  tanto com `commit=True` quanto com `commit=False`;
- teste HTTP de rollback oferece **apenas metadados de inline de teste**, sem
  mock de domínio: duas baixas de 60 validam contra título de 100; a segunda
  rejeição após a primeira gravação desfaz também o parent, a primeira baixa,
  movimento de conta e eventos. Não foi criada nova configuração de inline em
  produção.

### Evidências desta etapa

Logs em `/home/deploy/.hermes/cache/scratch/`:

| Slice/gate | Evidência real |
| --- | --- |
| RED 1, edição pendente/injeções | `finance-ui-review-fix-red-1.log`: 3 falhas, incluindo `ValidationError` não tratada na gravação |
| GREEN 1 | `finance-ui-review-fix-green-1.log`: 3 passaram |
| RED 2, rejeições econômicas/conta/campo excluído | `finance-ui-review-fix-red-2.log`: 7 falhas e 3 passaram; reproduziu também `ValueError` para `open_amount` excluído |
| GREEN 2 | `finance-ui-review-fix-green-2b.log`: 10 passaram |
| Comando final solicitado | `finance-ui-review-fix-green-final-2.log`: **32 passaram em 11,95 s** |
| Regressões financeiras/UI/security dirigidas | `finance-ui-review-fix-regression-final-2.log`: **229 passaram e 5 subtests passaram em 53,01 s** |
| Ruff check/format e MyPy próprios | `finance-ui-review-fix-quality-final.log`: passaram; MyPy verificou 3 arquivos |
| Bandit, arquivos de produção próprios | `finance-ui-review-fix-bandit.json`: nenhum achado/erro nos dois arquivos completos, portanto nenhum achado no diff |

```sh
python /home/deploy/.hermes/cache/scratch/run_rgn_tests.py \
  --db security --image rgnfarmasystem:corrections-clean-tests \
  tests/test_review_finance_ui_corrections.py -q --tb=short
```

A execução dirigida adicional incluiu `test_finance.py`,
`test_finance_corrections.py`, `test_security_ui_ledger_regressions.py`,
`test_security_corrections.py` e os grupos `AppUiSprint39ResourceTests` e
`AppUiFormEnhancementTests` de `test_app_ui.py`. `git diff --check` dos arquivos
próprios passou. Banco isolado exclusivo desta etapa: `test_security`, sem rede
de produção.

Falhas intermediárias preservadas: `green-2.log` já corrigia os HTTPs, mas seis
asserções de direção esperavam fluxos que a fixture não criava; o teste passou a
criar os fluxos pelos métodos reais existentes. `green-coverage.log` continha
uma asserção de conjunto exato de changed_data que desconsiderava o hidden initial
de data do Django; foi substituída por verificar a presença do valor original e
a ausência de campos de serviço. Essas correções de teste não adicionaram regras
de produção. A cobertura adicional é regressão positiva/negativa, não outro RED
alegado ou terceira extensão funcional.

**Limites:** não foi executada a suíte global/freeze nesta etapa, nem reivindicada
homologação financeira. A nova revisão independente fresh após fix2 e o gate
final global continuam com o agente pai; o GREEN dirigido não substitui essas
aprovações. O novo catch é de update financeiro, não uma ampliação genérica do
tratamento de erros de outros apps ou de todos os fluxos de criação.
