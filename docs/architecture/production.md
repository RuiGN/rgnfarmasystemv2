# Produção e Execução de Ordens

## Arquitetura single-instance

Este módulo opera em escopo global da instalação local. O acesso é controlado
por autenticação Django e permissões nativas `view`, `add`, `change` e
`delete`, administradas no Django Admin por usuário ou grupo.

As APIs e telas operacionais não exigem cabeçalho de escopo, seleção de empresa
ou vínculo de contrato por cliente. Listagens, formulários, detalhes e ações
usam o mesmo conjunto global de dados da instância.

## Regras de implementação

- Preservar as regras de negócio da indústria de cosméticos do módulo.
- Validar relacionamentos pelo contexto funcional do domínio, não por escopo
  SaaS herdado.
- Manter trilha de auditoria, logs e justificativas quando aplicável.
- Expor menus e botões somente conforme permissões Django reais.
- Criar migrations consistentes para qualquer alteração de modelo.
- Cobrir novas regras com testes automatizados.

## APIs e UI

Endpoints REST devem usar `IsAuthenticated` e permissões Django de modelo. A UI
operacional em `/app/` deve usar o shell, cards, tabelas, formulários, badges,
modais, paginação e estados do design system.

As transições públicas da ordem (`approve`, `release`, `start`, `pause`,
`resume`, `complete` e `cancel`) exigem um usuário autenticado e já persistido.
O ator é validado antes do lock, da mudança de estado e da auditoria; não existe
fallback para evento anônimo. O cancelamento é permitido somente em `draft`,
`approved`, `released`, `in_progress` ou `paused`. Uma ordem já cancelada é
terminal para essa ação, portanto uma repetição é rejeitada sem substituir
justificativa, data, ator ou evento original.

Atualizações genéricas da própria OP pela API recarregam a linha atual com
`select_for_update()` em transação, reaplicam apenas os campos enviados,
revalidam as referências atuais e salvam esses campos com `updated_at`.
Assim, um `PATCH` validado antes de `complete`, `pause` ou `cancel` não restaura
estado, rendimento, autoria ou timestamps antigos. A resposta utiliza a
instância atualizada, não a leitura obsoleta. Metadados não enviados também
são preservados. A UI já reaplica alterações sobre a ordem bloqueada; o Admin
bloqueia a ordem antes de construir o formulário de gravação.

Regressão: `tests/test_p1_production_stale_updates.py`, incluindo intercalação
HTTP determinística, revalidação de fórmula e conexões PostgreSQL separadas.
O teste de concorrência não substitui avaliação de carga em produção.

Os mapas de controle e resultados exigem conjuntamente
`production.view_productionorder` e a permissão funcional dedicada
`production.view_production_maps`. Os links só são publicados no detalhe da
ordem quando ambas estão presentes. Dentro do mapa, materiais, produtos
acabados, processos, mão de obra, movimentos, genealogia, custos e eventos
continuam protegidos por suas oito permissões de consulta independentes; uma
seção não autorizada não é consultada nem enviada ao template.

Os recursos REST `outputs`, `operations` e `labor-entries` são não destrutivos:
oferecem listagem, detalhe, criação e atualização, mas não expõem `DELETE`.
Criações e atualizações geram uma única entrada funcional em
`GovernanceAuditLog`, na mesma transação, com ator, alvo e snapshots mínimos
antes/depois sem observações ou outros dados potencialmente sensíveis.
Cada escrita bloqueia primeiro a `ProductionOrder` e depois o recurso
operacional, recarrega a instância e repete a validação dentro da mesma
transação. Essa ordem de locks é compartilhada com `receive_outputs`, evitando
que uma atualização baseada em leitura obsoleta sobrescreva evidência de
recebimento ou um estado terminal. A ordem vinculada ao recurso é imutável.

Resultados de produção recebidos são imutáveis; a evidência de recebimento é
criada exclusivamente pela action `receive_outputs`. Resultados pendentes só
podem ser criados ou alterados em ordens `draft`, `approved`, `released`,
`in_progress` ou `paused`. Um resultado pendente histórico sem alteração pode
ser lido para que `receive_outputs` o transforme em `received` na ordem
`completed`; resultados recebidos persistidos permanecem validáveis para
auditoria. Apontamentos de mão de obra só podem ser criados ou alterados em
ordens `released`, `in_progress` ou `paused`; registros persistidos sem
alteração continuam validáveis depois de a ordem se tornar terminal.

Execuções de operação seguem a máquina de estados:

- `pending`: sem timestamps e duração real zero;
- `in_progress`: exige início, proíbe fim e mantém duração real zero;
- `completed`: exige início, fim e ator; a duração é sempre derivada;
- `skipped`: sem timestamps, duração zero, ator e justificativa obrigatórios.

São permitidas as transições `pending` para `in_progress`, `completed` ou
`skipped`, e `in_progress` para `completed`. Estados `completed` e `skipped`
são terminais. A API aceita criação retrospectiva coerente em `completed`,
sempre associando `recorded_by` ao usuário autenticado e auditando o registro.

As regras sequenciais também são verificadas por `full_clean()` nos models para
proteger serviços e demais caminhos internos. `QuerySet.update()`,
`bulk_create()`, `bulk_update()` e SQL direto não executam `full_clean()`:
esses caminhos são uma fronteira deliberadamente restrita a migrations e
rotinas administrativas revisadas. As `CheckConstraint` protegem a coerência
local dos estados no banco, mas uma `CheckConstraint` não consegue impor uma
regra que depende do status da `ProductionOrder` em outra tabela. Essa defesa
cross-table depende de locks e serviços transacionais; `full_clean()` é o
contrato para os caminhos internos.

A migration `0006` não corrige evidência legada automaticamente. Antes de criar
as constraints, um preflight lista categorias e IDs incompatíveis e interrompe
a aplicação para saneamento explícito, documentado e auditável.

## Sequência operacional e segregação de qualidade

O fluxo operacional de referência é:

```mermaid
flowchart LR
    A[Aprovar ordem] --> B[Separar e reservar materiais]
    B --> C[Liberar ordem]
    C --> D[Iniciar execução]
    D --> E[Baixar materiais]
    E --> F[Concluir ordem]
    F --> G[Receber produto acabado em quarentena]
    G --> H[Liberação do lote pelo fluxo de QA]
```

Essa sequência separa execução produtiva de decisão de qualidade:

- `approve` leva a ordem de `draft` para `approved`;
- `reserve_materials` reserva os lotes aprovados alocados às linhas de
  consumo. O serviço aceita a ordem `approved` ou `released`, embora o
  procedimento recomendado faça a separação antes da liberação;
- `release` exige produto operacionalmente disponível e fórmula e roteiro
  aprovados e vigentes;
- `start` leva a ordem liberada para `in_progress`;
- `issue_materials` só opera em `in_progress` e exige que consumo real, perda
  e devolução reconciliem exatamente a quantidade reservada;
- `complete` registra o rendimento real e encerra a execução produtiva;
- `receive_outputs` só opera na ordem concluída, exige componentes ativos da
  fórmula efetivamente baixados, cria a genealogia e recebe cada lote acabado
  com status de qualidade `quarantine`;
- somente o módulo de QA pode decidir a liberação de qualidade posterior.

**Produção nunca aprova a qualidade do lote acabado.** O serviço de recebimento
valida que o lote continua em quarentena e rejeita evidência que indique outro
status.

### Disposição de qualidade do lote e dos saldos

A fronteira genérica de Estoque não decide disposição de qualidade:

- a API REST de `StockLot` declara `quality_status` somente leitura e devolve
  `400` quando o campo é enviado em `POST`, `PUT` ou `PATCH`;
- a API REST de `StockBalance` aplica a mesma rejeição explícita a
  `quality_status`, `quantity` e `reserved_quantity`, pois são derivados das
  ações de qualidade, movimentos e reservas;
- depois da criação, `product`, `lot`, `warehouse`, `location` e `unit`
  formam a identidade imutável do saldo. `PUT` e `PATCH` devolvem `400` mesmo
  quando recebem o valor atual; formulário de edição, Admin e `save()` do
  modelo também impedem que um saldo seja relabelado sem movimento;
- os formulários genéricos de `/app/` não renderizam esses campos, e o Django
  Admin os mantém somente leitura;
- os demais campos não controlados continuam sujeitos às permissões e
  validações de seu recurso.

As actions de `LotRelease`, protegidas por `qa.change_lotrelease`, recebem
sempre `request.user` e exigem ator autenticado, ativo e persistido. O ator é
relido e bloqueado no banco, evitando aceitar uma instância obsoleta cujo
usuário tenha sido desativado. A matriz permitida é:

| Ação | Origem | Destino | Disposição do lote e saldos |
|---|---|---|---|
| Aprovar | `under_review` | `released` | `approved` |
| Bloquear | `under_review` | `blocked` | `blocked` |
| Desbloquear | `blocked` | `under_review` | `quarantine` |
| Rejeitar | `under_review` ou `blocked` | `rejected` | `rejected` |

`released` e `rejected` são terminais. Cada ação usa uma única transação e a
ordem de locks `LotRelease` → `StockLot` → `StockBalance` por PK → evidências
QA/documentais/ordem → ator. A revisão, o documento e a ordem são relidos sob
lock e devem apontar para o mesmo produto e lote, fechando a janela TOCTOU.
Uma divergência legada entre lote e saldo interrompe a operação sem
normalização automática: o dado deve ser reconciliado por procedimento
controlado antes de uma nova tentativa.

Depois das validações, a action atualiza a liberação, o lote e todos os seus
saldos por atualização em lote e registra exatamente um evento
`qa.lot_release.approved|blocked|unblocked|rejected` no
`GovernanceAuditLog`. Estado, saldos e auditoria compartilham a mesma
transação; falha em qualquer etapa reverte o conjunto. Uma repetição inválida
é rejeitada e não duplica a auditoria. Produto, lote, revisão, documento e
ordem formam o alvo imutável da liberação após sua criação; evidências de
estados terminais também não podem ser reescritas. Recebimentos de
compra também bloqueiam o lote e recusam criar saldo com status incompatível,
impedindo que uma nova entrada reintroduza quarentena depois da liberação.

Mutações internas continuam restritas aos serviços de domínio de
Estoque/Qualidade/QA e a rotinas administrativas revisadas. Como em outras
áreas do sistema, `QuerySet.update()`, operações em massa e SQL executado fora
desses serviços não passam por serializers ou formulários e permanecem uma
fronteira operacional controlada.

Pausa e retomada formam o caminho opcional `in_progress` → `paused` →
`in_progress`. O cancelamento exige justificativa e é permitido em `draft`,
`approved`, `released`, `in_progress` e `paused`; não é permitido em
`completed`, `cancelled` ou `closed`.

## Workspace de execução

A tela de execução apresenta quatro abas, exatamente nesta ordem:

1. **Matérias-primas**: componente, material, quantidades planejada e real,
   perda, devolução, unidade, lote, almoxarifado, localização, qualidade,
   validade e observações.
2. **Produtos acabados**: lote e sublote, quantidades, destino, fabricação,
   validade e observações. A aba registra resultados pendentes; o recebimento
   em quarentena ocorre somente pela action segura.
3. **Processos**: etapa do roteiro, sequência, operação, centro de trabalho,
   tempos, custo-hora de máquina, estado e observações.
4. **Colaboradores**: processo, pessoa, função, intervalo, custo-hora e
   observações.

Cada aba exige a permissão `view` de seu próprio model. `add`, `change` e
`delete` são avaliadas separadamente; como `production` faz parte da retenção
GxP, a UI não oferece exclusão e o workspace rejeita qualquer tentativa de
apagar um registro operacional. As quatro abas permanecem visíveis para
preservar a orientação da workspace. Uma aba sem `view` mostra um aviso de
permissão, não consulta, não renderiza nem processa seu formset, e o envio
forjado de seu management form retorna `403`.

Quando uma validação falha, a aba com erro se torna ativa; caso contrário, a
primeira aba autorizada fica ativa. O salvamento bloqueia primeiro a ordem e,
em seguida, os registros filhos existentes com `select_for_update()`, repete
`full_clean()` sob o lock e grava tudo em uma única transação. Falha de
revalidação não persiste alteração parcial.

Os estados e travas funcionais são específicos por registro:

- resultados pendentes podem ser criados ou alterados de `draft` até
  `paused`; depois de recebidos, são imutáveis e carregam lote, movimento,
  ator e horário de recebimento;
- processos permitem `pending` → `in_progress`, `completed` ou `skipped` e
  `in_progress` → `completed`. `completed` e `skipped` são terminais;
  `skipped` exige ator e justificativa;
- apontamentos de colaboradores só podem mudar com a ordem `released`,
  `in_progress` ou `paused`; a duração é derivada do intervalo;
- alocações de matérias-primas preservam os vínculos com os movimentos de
  reserva, baixa, perda e liberação de reserva.

Cada salvamento da workspace cria um `GovernanceAuditLog` para a ordem, com
ator, campos alterados e contagem de mudanças por aba. As actions de ciclo de
vida e as ações compostas de estoque/custo geram eventos funcionais próprios.

## Permissões

A abertura da workspace **Executar** exige
`production.view_productionorder` e `production.change_productionorder`. Cada
aba ainda requer:

| Área | Consulta | Escrita |
|---|---|---|
| Matérias-primas | `production.view_materialconsumption` | `production.add_materialconsumption` / `production.change_materialconsumption` |
| Produtos acabados | `production.view_productionoutput` | `production.add_productionoutput` / `production.change_productionoutput` |
| Processos | `production.view_productionoperationexecution` | `production.add_productionoperationexecution` / `production.change_productionoperationexecution` |
| Colaboradores | `production.view_productionlaborentry` | `production.add_productionlaborentry` / `production.change_productionlaborentry` |

As actions `approve`, `release`, `start`, `pause`, `resume`, `complete` e
`cancel` exigem `production.change_productionorder` e um estado compatível. As
ações compostas usam a seguinte matriz cumulativa:

| Ação | Permissões obrigatórias |
|---|---|
| Separar/reservar materiais | `production.change_productionorder`, `production.change_materialconsumption`, `inventory.add_stockmovement` |
| Baixar materiais | `production.change_productionorder`, `production.change_materialconsumption`, `inventory.add_stockmovement` |
| Receber produtos acabados | `production.receive_productionoutput`, `inventory.add_stockmovement` |
| Calcular custo | `production.change_productionorder`, `costing.add_productioncostcapture` |

## Idempotência, transações e compensação

`reserve_materials`, `issue_materials`, `receive_outputs` e `calculate_cost`
são atômicos e idempotentes. Uma repetição coerente devolve os mesmos
movimentos, resultados ou captura de custo já vinculados, sem duplicar saldos,
genealogia ou eventos. Se a evidência persistida divergir da solicitação
recalculada, o serviço rejeita a ação em vez de reescrever o histórico.

As transições de ciclo de vida não são genericamente idempotentes: repetição
fora do estado de origem é rejeitada. Em especial, repetir `cancel` em uma
ordem cancelada não substitui a justificativa, o ator, a data ou o evento
originais.

Movimentos de estoque postados devem ser tratados como evidência: **não
excluir nem reescrever**. A devolução informada durante a baixa é implementada
como um novo movimento `RELEASE_RESERVATION`, vinculado ao consumo e auditado
pela ação composta. Para correções posteriores, a política é criar um
movimento inverso/ajuste novo, com justificativa e ator, preservando o
movimento original.

Lacuna conhecida: ainda não existe no módulo de Produção uma action dedicada
que compense automaticamente reserva, baixa, perda ou recebimento já postado e
registre o vínculo de reversão na trilha da ordem. `cancel` muda apenas o ciclo
de vida da ordem. O estoque possui o primitivo `adjust_stock`, que cria um novo
ajuste com justificativa, mas não implementa sozinho o fluxo regulado de
compensação da ordem. Além disso, a API REST genérica de `StockMovement` ainda
expõe atualização e exclusão para quem possuir as respectivas permissões de
modelo; portanto a imutabilidade de movimento postado ainda não está
integralmente imposta nessa fronteira. Até essas lacunas serem corrigidas, uma
divergência pós-postagem deve ser bloqueada para edição direta, tratada por
procedimento controlado e reconciliada por usuário autorizado, sem apagar o
histórico.

## Mapas de controle e resultados

Os mapas são páginas somente leitura e imprimíveis, acessíveis a partir do
detalhe da ordem. Ambos exigem simultaneamente:

- `production.view_productionorder`;
- `production.view_production_maps`.

O cabeçalho apresenta ordem, produto, lote, fórmula, roteiro, quantidade,
prioridade, responsável, linha, datas previstas e reais, estado e observações.
O mapa de resultados acrescenta:

- rendimento percentual, com zero seguro quando a quantidade planejada é
  zero;
- perda real e retrabalho;
- quantidades planejada, real, devolvida e variação de materiais;
- tempo real de processos e de colaboradores;
- custo planejado, real e variação `real - planejado`.

As tabelas detalham materiais, produtos acabados e sua situação de qualidade,
processos, colaboradores, movimentos, genealogia, capturas de custo e eventos
operacionais. Eventos são filtrados estritamente por `module='production'`,
`target_model='ProductionOrder'` e pelo identificador da ordem.

Além das duas permissões de entrada, cada uma das oito seções é protegida de
forma independente. Se faltar a permissão, a consulta daquela seção não é
executada e o template exibe um aviso:

| Seção | Permissão |
|---|---|
| Materiais | `production.view_materialconsumption` |
| Produtos acabados | `production.view_productionoutput` |
| Processos | `production.view_productionoperationexecution` |
| Colaboradores | `production.view_productionlaborentry` |
| Movimentos | `inventory.view_stockmovement` |
| Genealogia | `inventory.view_stocklotgenealogy` |
| Custos | `costing.view_productioncostcapture` |
| Eventos | `governance.view_governanceauditlog` |

Os totais derivados também respeitam essa segregação: sem acesso a materiais,
processos, colaboradores ou custos, a métrica dependente não é calculada nem
exposta. O botão **Imprimir mapa** usa a impressão do navegador e uma folha de
estilo específica que remove a navegação e preserva a legibilidade das
tabelas.

## Verificação mínima

```bash
TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py check

TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/pytest -q
```
