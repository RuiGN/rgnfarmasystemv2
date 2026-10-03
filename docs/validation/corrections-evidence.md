# Recaptura automatizada de evidências

## Escopo

Os hashes de `EV-SI-006` e `EV-SI-010` estavam divergentes no baseline. Não foram
reaprovados apenas recalculando hashes: os testes de ambos os artefatos foram
executados em PostgreSQL isolado, sem acesso à rede ou ao banco de produção.

- Artefatos: `tests/test_ai_agents.py`, `tests/test_native_postgres_deployment.py`.
- Resultado JUnit: 37 testes, zero falhas, zero erros e zero skips.
- Runner: Python 3.14, Django 6, PostgreSQL 15; runtime vigente usado somente
  nesta recaptura. O candidato final também precisa passar em build limpo.
- A avaliação é de `automated-quality-gate`, não de aprovação regulatória humana
  ou validação GxP em produção.

A montagem temporária precisa permitir execução dos scripts sintéticos de
backup/restore. A primeira execução usou `noexec` implicitamente, gerando duas
falhas do harness; a repetição com `exec,nosuid` passou nos 27 testes de deploy.
Nenhum backup real de produção foi criado ou restaurado nessa execução.

## Contrato de demonstração

O teste de demo completo exigia `AIAgentProfile`, embora o contrato vigente
proíba o seeder de criar profiles/runs/suggestions legados. O teste foi alinhado
com o contrato existente: exige clientes/conectores ativos e comprova que não
cria profiles legados. A regra de idempotência continua obrigatória.

## Harness e execução integrada

A primeira execução integrada não é aceite: começou antes do congelamento dos
arquivos e encontrou importação incompleta em compras. Depois o PostgreSQL
isolado de 512 MB em tmpfs sofreu PANIC por falta de espaço no WAL, causando
falhas de setup/teardown em cascata. Os artefatos dessa tentativa foram retirados
do candidato e preservados no scratch com o identificador `invalid-run`.

O banco foi recriado em volume Docker exclusivo do harness, na mesma rede interna,
sem portas publicadas. Os dados são sintéticos e descartáveis. `fsync`,
`synchronous_commit` e `full_page_writes` foram desativados somente nesse banco
para acelerar flushes da suíte; locks e atomicidade PostgreSQL permanecem ativos.
Isso não testa durabilidade física nem recuperação de falha de energia, e esses
ajustes não podem ser propagados para produção.

A aprovação integrada requer snapshot sem edições concorrentes, suíte completa,
review independente e gates; aprovação de testes selecionados não a substitui.

## Readiness real

O endpoint `/ready/` foi exercitado com PostgreSQL, Redis e RabbitMQ reais em
rede Docker interna dedicada:

- Dependências disponíveis: HTTP 200, três checks verdadeiros.
- Broker isolado desligado: HTTP 503, check de broker falso; banco/cache verdadeiros.
- Resposta `Cache-Control: no-store`, sem detalhes de exceções.

Essas verificações não comprovam saúde do túnel de produção nem autorização de
deploy. As portas de métricas 20241 e 20243 estavam ocupadas na inspeção do host;
o candidato usa endereço configurável, padrão 127.0.0.1:20249, que deve ser
verificado novamente antes da promoção.

## Gates dirigidos após a revisão independente

Estes resultados são parciais e **não substituem** a suíte completa congelada:

- Exclusão HTML de conectores fiscais: 20 cenários próprios passaram; o gate
  dirigido passou 266 testes e 7 subtestes. Há negativos GET/POST para não staff,
  controles positivos para staff autorizado e exclusão não fiscal preservada.
- Readiness/deploy: o pai repetiu os testes e obteve 62 aprovados. O JUnit está em
  `evidence/corrections/readiness-deploy-review-junit.xml`. Incluem dependências
  silenciosas e execução do rollback ao rejeitar o candidato.
- As três sondagens silenciosas retornaram indisponibilidade em 6,021 segundos
  no harness dirigido; os subprocessos foram encerrados e coletados. Cada probe
  tem limite de 2 segundos, sem reutilizar o pool operacional nem criar dados.
- O endpoint atualizado foi repetido com PostgreSQL, Redis e RabbitMQ reais na
  rede interna: HTTP 200 com os três checks verdadeiros; ao parar somente o broker,
  HTTP 503 com banco/cache verdadeiros e broker falso. A resposta manteve
  `Cache-Control: no-store`. O broker de teste foi iniciado novamente depois.
- A imagem `rgnfarmasystem:corrections-clean-tests` usa Python 3.14.7 e corresponde
  aos 98 pins atuais do runtime, sem divergências. Não confundir com a imagem
  inicial `correction-tests`, baseada no runtime antigo.

Ruff, formatação e Bandit do caminho readiness foram exercitados. As exceções
Bandit B404/B603 são locais e documentadas: o executável e o script são fixos,
sem shell; configurações são dados enviados por stdin, nunca código/argv.
O gate de tipagem global identificou 21 erros novos nos mixins/factory financeiros.
A correção restrita a tipagem/MRO passou em 385 arquivos e em 135 testes financeiros;
o pai repetiu o MyPy global com sucesso. Não houve migration financeira nova.
A revisão financeira funcional confirmou locks, conservação e imutabilidade, mas
identificou duas integrações HTML com HTTP 500 (edição econômica legítima antes da
primeira baixa e apresentação de rejeições após lançamento). O ajuste de formulário
passou 32 cenários novos e um gate dirigido de 229 testes + 5 subtestes; não alterou
o domínio financeiro. A revisão fresh dessa integração foi aprovada e repetiu
34 testes com sucesso. A suíte congelada segue pendente, assim como a conclusão
dos últimos ajustes/revisão de estoque. O patch atual do original permanece idêntico ao patch inicial preservado
(SHA256 `2dd51a80b21c1dffe31a810190a2ecfa1087ffa3b76324b62b12e1714f8939ea`); nenhuma
correção foi aplicada ao original nesta etapa.
Uma suíte ampla iniciada pelo agente de readiness acabou interrompida, sem resumo
final; ela não é aceita como evidência integrada.

## Primeira suíte completa em snapshot congelado

A execução posterior no snapshot `rgnfamarsystemv2-final-candidate` terminou de
forma completa: **2.064 aprovados, 4 falhas, 46 erros e 42 subtestes aprovados**,
sem skips. A cobertura foi **85,52%** (24.480/28.626 linhas). O snapshot e a imagem
mantêm os hashes de origem, mas o candidato **não foi aprovado**.

Os rastros identificam três causas, sem afrouxar as proteções financeiras:

1. Uma falha de idempotência do demo: `_upsert()` usava `QuerySet.update()` com
   campos econômicos/agregados financeiros controlados pelo serviço.
2. Os 46 erros compartilham a mesma fixture de relatório: criação direta de
   título vencido, agora protegida por transição explícita. O preparo precisa usar
   o domínio; valores esperados/assertions de relatório devem permanecer intactos.
3. Três falhas de evidência: hash corrente do teste do catálogo ficou antigo após
   incluir a saída segura no conjunto de 233 ações. Foi recapturado **executando
   7 testes**, preservando identificadores e hash histórico. A repetição de
   catálogo/documentação/auditoria passou **19 testes**; o pin corrente foi
   atualizado, não removido nem substituído por uma verificação permissiva.

JUnit, cobertura e resumo dessa tentativa ficam em
`evidence/corrections/first-frozen-suite-junit.xml`,
`evidence/corrections/first-frozen-coverage.xml` e
`evidence/corrections/first-frozen-suite-summary.json`. O snapshot reprovado não é
editado. A correção do demo/fixture exige novo congelamento e nova suíte completa
antes da aplicação ao original. Nenhum erro foi ocultado por skip/deselection.

### Reconciliação de fontes e artefatos gerados

Os **2.055 arquivos manifestados** foram relidos e seus hashes permaneceram
idênticos. Fora do manifest, excluindo `.git` e caches de ferramentas, existem
somente quatro saídas produzidas depois do congelamento: `.coverage`, JUnit,
cobertura XML e `final-openapi.yml`. Seus hashes estão registrados separadamente
em `evidence/corrections/first-frozen-source-artifact-reconciliation.json`.
Isso comprova identidade das **fontes manifestadas**, não identidade byte a byte
da árvore inteira, que recebeu essas saídas durante a validação. A checagem do
patch original foi repetida e continua igual ao baseline preservado.

### Revisão final de estoque e terceiro ciclo autorizado

A revisão independente repetiu **68 testes aprovados**, confirmando os ajustes de
campos protegidos/cancelamento, saldo explicitamente selecionado e teto da
quantidade de compras sob lock. Entretanto, reprovou o guard de
`ProductionOrderSerializer.to_internal_value`: a interseção de campos protegidos
ocorre antes de o DRF rejeitar JSON inteiro/lista, podendo lançar `TypeError` e
resultar em HTTP 500. A aprovação de estoque permanece bloqueada.

Após o limite de dois ciclos, o usuário autorizou explicitamente um terceiro
ajuste restrito ao guard de formato e testes HTTP, mantendo as proteções e a
exigência de suíte completa antes da aplicação. Não é autorização de deploy nem
para refatorações adicionais. A correção, revisão fresh e novo congelamento
continuam pendentes; nenhum resultado futuro é tratado como aprovado.

### Build limpo do primeiro candidato

O build `--no-cache` do **primeiro candidato, ainda reprovado nos testes**, terminou
com sucesso. A imagem `rgnfarmasystem:corrections-final` foi relida pelo Docker,
executada sem rede e confirmou Python **3.14.7**, `pip check` sem conflitos e
**98 pins de runtime verificados, zero divergências**. O ID exato e a comparação
de arquivos estão em `evidence/corrections/first-frozen-clean-image.json`.

Não houve divergência de conteúdo em arquivos presentes na imagem. O único
arquivo manifestado ausente foi `.env.development.example`, excluído pelas regras
vigentes de `.dockerignore` para `.env*`; apenas os exemplos explicitamente
reincluídos são copiados. Não foi acessado nenhum arquivo de ambiente real.
Esse gate comprova instalação/empacotamento daquele snapshot; não aprova o
release nem contém os ajustes posteriores de demo/fixture/JSON. O novo candidato
precisa de seu próprio build e validação completa.

### Integração do demo e preparo dos relatórios

O demo financeiro deixou de usar atualização em massa de campos protegidos:
criação e transições usam o protocolo público, e repetição preserva economia e
ledger, atualizando apenas metadata permitida. O pai repetiu os casos de carga
idempotente, baixa parcial/integral e estorno: **5 aprovados**, com JUnit em
`evidence/corrections/demo-finance-directed-junit.xml`. A revisão independente
continua pendente, inclusive quanto à ordem dos locks na transação completa.

O agente comprovou **167 testes financeiros/domain/UI aprovados**. Na execução
integral de demo/relatórios/governance, obteve **563 aprovados e 2 falhas, zero
erros**. A shared fixture foi reparada sem mudar suas assertions; a comparação
AST registrou **154 definições de teste e 528 assertions preservadas**.

As duas falhas restantes são preparos inline antes ocultos pela shared fixture:
criação direta de título liquidado/pago e títulos com status/paid/open
incompatíveis com nova criação. O ownership foi ampliado somente aos blocos de
preparo dessas duas funções, para usar transições e baixas públicas sem alterar
assertions esperadas, executores, models, regras ou esconder casos. A nova
execução integral permanece obrigatória antes de novo congelamento.

### Terceiro guard JSON: execução dirigida

O serializer de produção agora encaminha dados não-`Mapping` para a validação
padrão do DRF antes de inspecionar os campos protegidos. Não muda o domínio nem
os guards para objetos. A reprodução HTTP pré-fix registrou quatro falhas com
500/`TypeError` (POST/PATCH, inteiro/lista); a execução do implementador após o
ajuste passou **46 testes**. O log preserva também uma tentativa intermediária
com assertion incorreta sobre o formato textual do erro do teste novo.

O pai repetiu um gate ampliado de JSON, API de estoque, movimentos, recebimentos
e cancelamento: **93 aprovados**, zero falhas/erros/skips. O JUnit está em
`evidence/corrections/stock-json-third-directed-junit.xml`. Há controles de
objetos válidos, rejeição explícita de metadata protegida, validação econômica e
snapshots de identidades/eventos/consumos/saldos inalterados nos negativos.
A revisão independente fresh desse terceiro ajuste foi **aprovada**, sem
preocupações de segurança ou erros lógicos; repetiu **46 testes** no banco
`inventory`. A comparação contra o snapshot anterior confirmou somente import e
guard de `Mapping`, com os outros métodos e testes de estoque intactos. Isso
fecha o escopo dirigido de estoque, mas não substitui a suíte global do próximo
snapshot nem aprova aplicação/release.

### Relatórios verdes; bloqueio de concorrência do demo

Os dois preparos inline foram corrigidos pelo protocolo público. O gate integral
do agente passou **565 testes**. O pai releu os preparos, repetiu o verificador
AST e executou **todo `test_report_engine.py`: 560 aprovados**, sem deselection.
As 528 assertions e 154 nomes/assinaturas/decorators permanecem preservados.
O JUnit do pai está em `evidence/corrections/report-prep-directed-junit.xml`.

A revisão independente do demo foi **reprovada por ordem de locks**, apesar dos
cinco testes sequenciais verdes: a transação externa do cenário conserva o lock
da conta e depois pede o título; baixa/estorno pedem título antes de conta.
Isso forma ciclo de deadlock com duas conexões. O PostgreSQL reverte uma vítima;
não é evidência de corrupção ou duplicação de saldos. A ordem implícita também
existia no baseline e continua incompatível com o protocolo de ledger atual.

Um fix agent fresh recebeu somente esse bloqueador: alinhar a descoberta/locks
dos títulos existentes antes da conta, mantendo o cenário atômico, os guards e
os dados financeiros. Exige reprodução transacional determinística com conexões
reais, prova do bloqueio/ordem e concorrência com baixa e estorno. A criação
concorrente inicial continua sujeita às constraints únicas e rollback, sem
prometer sucesso das duas cargas. Fix, revisão e suíte congelada ainda pendem.

### Correção da ordem de locks do demo

O fix do demo acrescentou apenas o prelock público do título existente antes do
primeiro lock da conta, mantendo o helper, allowlist, economia e fronteiras
atômicas. Quatro testes concorrentes reais cobrem baixa/estorno com ledger
primeiro e seeder primeiro; usam conexões independentes, `pg_blocking_pids`,
`pg_locks` e `NOWAIT`, sem aceitar timeout/deadlock como sucesso.

A ausência do prelock reproduziu **2 falhas e 7 aprovados** com erro de inversão.
O gate com a correção passou **9 testes**, repetido com o mesmo resultado.
O gate financeiro/domain/UI passou **169 testes em duas execuções**. Ruff,
formatação, MyPy, Bandit e diff-check do ownership passaram. Os logs permanecem
no scratch em `demo-finance-lock-order-{red,green,quality}.log`.

A revisão final fresh será feita sobre novo snapshot imutável, em paralelo com
os gates globais. Isso não é aprovação antecipada; o primeiro candidato e suas
falhas permanecem preservados, e a aplicação exige revisão e suíte aprovadas.

### Resultado integrado do segundo candidato

O snapshot `rgnfamarsystemv2-final-candidate-v2` preservou os hashes dos **2.068
arquivos manifestados**. A revisão final do demo foi aprovada, repetindo **9
testes**. O build limpo passou e foi relido pelo ID
`sha256:f236fb148d6b2f36c331083cd08363375e12c843c1a7adbb5577909d66035299`;
`pip check` não encontrou conflitos. Os oito gates Django/migrations/OpenAPI/
evidência/prontidão passaram. O perfil production foi exercitado apenas com
configuração e chaves sintéticas: zero issues, zero silenced; não comprova
configuração real de produção.

A suíte completa terminou com **2.145 aprovados, 2 falhas, 42 subtestes aprovados,
zero erros e zero skips**, cobertura **85,78%** (24.573/28.648 linhas). O JUnit
contabiliza 2.189 no atributo total, mas serializa 2.147 elementos `testcase`:
a diferença de 42 corresponde aos subtestes informados pelo pytest. O resumo
preserva ambas as contagens em `evidence/corrections/v2-frozen-summary.json`.

As duas falhas são de prazo, em fonte que não havia sido alterada: datetime UTC
usa `.date()` diretamente e compara com `timezone.localdate()`. Após 21h no fuso
UTC-03, ontem local pode ser classificado como hoje. O pai reproduziu exatamente
as duas falhas e limitou a correção à conversão de datetimes aware ao fuso ativo,
com testes determinísticos; valores date/naive e assertions existentes devem
continuar preservados. O candidato v2 não é editado nem aprovado.

Ruff check passou; a formatação global detectou um arquivo de teste demo novo
não formatado. Foi corrigido somente no workspace, com AST idêntico antes/depois.
Os gates restantes foram executados separadamente: **MyPy sem erros em 385
arquivos**, Bandit aprovado e auditoria dos **98 pins diretos** sem vulnerabilidade
conhecida. O audit usou `--no-deps --disable-pip`; não equivale a lock completo
transitivo com hashes. A formatação e o ajuste de fuso exigem novo congelamento,
revisão dirigida e suíte/gates completos antes da aplicação.

### Normalização de prazo no calendário ativo

`DeadlineItem.temporal_label` e `_deadline_tone` agora compartilham um helper
mínimo: datetime aware é convertido ao fuso ativo antes de extrair a data;
`date` e datetime naive preservam o calendário local. Sorting, autorização,
modelos, configurações e assertions existentes não foram alterados.

O RED determinístico fixou `2026-10-03T01:00Z` em Recife e registrou **4 falhas,
51 aprovados e 12 subtestes**: dois casos novos e os dois failures da suíte v2.
O GREEN passou **118 testes e 12 subtestes**, cobrindo offsets de origem, fusos
positivos/negativos, fronteiras UTC/local, datas/naive e concordância label/tone.
Ruff, formatação, MyPy dos dois arquivos, Bandit e diff-check do escopo passaram.
Os logs estão no scratch em `deadline-timezone-{red,green,quality}.log`.

O próximo snapshot inclui essa correção e a formatação puramente textual do
teste demo, sem modificar v2. A revisão independente e o aceite global ainda
precisam concluir; nenhum resultado dirigido aprova o release antecipadamente.
