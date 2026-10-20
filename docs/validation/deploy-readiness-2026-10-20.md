# Preparação de deploy — 2026-10-20

## Escopo e limite da decisão

Revalidação local do candidato em `main`, baseada no HEAD
`d8b179c77787806f463d1d637a526bbdf0436d22`, com alterações não commitadas de
integridade P1, abas Duralux, impressão de lotes e correções de prontidão.
Este documento não comprova publicação, CI remoto, deploy ou aprovação regulatória.

**Prontidão de engenharia local: PASS.** A quarta execução integral terminou com
**2613 testes e 42 subtests aprovados**, sem falhas, erros ou skips, e cobertura
**86,40%**, superior ao mínimo de 80%. Build, perfil production sintético, gates
estáticos/estruturais, revisões e integração real isolada também passaram.

**Autorização operacional de produção: HOLD.** Esta conclusão não substitui
checagens da VPS, backup restaurável/rollback, provisionamento seguro e aceites
formais de Segurança/DPO e Qualidade. Impressão física permanece para aceite na
indústria antes de seu uso operacional. Nenhum commit, push ou deploy foi realizado.

O estado acima descreve o encerramento da revalidação local e da pré-checagem.
As autorizações posteriores para branch/PR e backup/preservação de imagem estão
no [registro da etapa de publicação](publication-2026-10-20.md); não concedem merge/deploy.

**Pré-checagem da VPS concluída posteriormente:** [parecer operacional](vps-preflight-2026-10-20.md).
Os9 serviços e endpoints internos/públicos foram observados saudáveis. O dotenv
remoto estava0664 na auditoria; uma autorização posterior específica permitiu
corrigir somente seu modo para0600, confirmado em segunda conexão SSH sem ler
conteúdo ou reiniciar serviços. Naquele recorte, o candidato ainda não estava publicado/promovido.
Backup e rollback foram conferidos por metadados, sem ensaio de restauração.
A decisão operacional permanece HOLD. Recibos da correção de permissão em
`evidence/vps-permission-fix-2026-10-20/`; as evidências originais foram preservadas.

### Candidato corrente e QA renderizado

O candidato corrente congela **999 fontes** em
`source-sha256:63af02efc3d7a640607ff9b2d841a3a80b8f9abfd2cc6c55aab7f13037e17694`.
O manifesto é `evidence/deploy-readiness-2026-10-20/source-snapshot-final.json`.
A terceira suíte integral terminou com **4 falhas, 2609 aprovados e 42 subtests
aprovados**, cobertura **86,40%**. Seus recibos completos estão em `full-attempt-3/`.
Três falhas de deadline não se reproduziram na seleção sem concorrência, mantendo
os testes e os limites originais. A quarta foi reproduzida e isolada no bootstrap
externo: o bloqueio indiscriminado de dotenv impedia ler até a fixture sintética
do teste de `run_with_env.py`, não era defeito desse script de produção.

O bootstrap agora permite somente caminhos explícitos de fixtures pytest sob o
scratch autorizado; leitura implícita, caminhos operacionais, symlinks escapando
da fixture e arquivos fora dessa política continuam bloqueados. Isso foi provado
com loader sentinela sem abrir os arquivos operacionais. A seleção original,
com cobertura ativa, passou com **9 testes**, incluindo todos os seis casos de
readiness e os três do wrapper. Nenhum código de produção, teste de deadline ou
timeout foi alterado para obter esse resultado. Os recibos RED/GREEN e a prova
de isolamento estão preservados.

A **quarta suíte integral passou**, sobre as mesmas 999 fontes, sem workloads
pesados concorrentes e sem alterar os testes de deadline. Foram **2613 casos
principais e 42 subtests aprovados**, cobertura **86,40%** e exit0. O JUnit declara
2655 no agregado porque inclui subtests, mas enumera 2613 elementos `testcase`;
as duas contagens foram reconciliadas por código. O hash do bootstrap e todas as
fontes foram reconferidos após a execução. Os recibos finais comprimidos, resumo,
ambiente e hashes estão em `full-final/`; a trilha anterior não foi sobrescrita.
O ambiente de início está em `verification-environment-attempt-4.json`, o estado
instalado em `environment-final.json`, e os checks em `observed-final-checks.json`.
O rebuild local terminou com sucesso, e o ID foi conferido pela leitura da tag:
`sha256:2b3211d4c19535b92332928d5990470f8d1b6d8bf545330949d334c0bae28cc3`.
As **999 fontes** conferem arquivo por arquivo dentro da imagem imutável; não há
dotenv sensível, `pip check` passou e os **99 pacotes** instalados são idênticos
ao conjunto auditado sem vulnerabilidades na rodada anterior. Isso reutiliza a
auditoria do mesmo conjunto, não afirma nova consulta ao banco de advisories.
O primeiro ensaio nessa imagem **falhou**: os três backends estavam prontos, mas
readiness retornou indisponível. Os probes diagnósticos concluíram com código 0,
levando **3,194 s / 2,226 s / 2,359 s** para banco/cache/broker, acima dos **2 s**
mantidos em produção. A suíte integral estava rodando simultaneamente; concorrência
é hipótese, não causa comprovada. Containers e rede próprios foram removidos e a
ausência foi conferida novamente. O recibo é
`live-integration-candidate-attempt-1.json`. Depois do fim da suíte, a repetição
sem concorrência **passou**, na mesma imagem: liveness200 e três readiness200
consecutivos, com PostgreSQL/Redis/RabbitMQ reais descartáveis, em **3,680 s /
3,624 s / 4,130 s por requisição completa**, mantendo os **2 s por probe** e as
configurações inalteradas. A limpeza foi conferida novamente por leitura dos
alvos exatos. Recibo: `live-integration-candidate-quiet.json`. Isso não comprova
capacidade sob carga nem prontidão da VPS; o resultado negativo anterior permanece.
Não houve push ou deploy.

A inspeção servida usa respostas Django reais renderizadas em transação revertida
no PostgreSQL sintético, depois servidas em loopback com os assets locais reais.
Não existem endpoints POST nesse servidor, nem conexão com impressora. São 12
páginas/estados, com matriz principal de 1440×1000 e 375×900.

Foram encontrados dois defeitos visuais reais: título longo escapando do cartão
em Minha área e sobreposição do resumo operacional com os dados/abas de detalhe.
Ambos receberam regressões RED/GREEN. A correção de altura remove `stretch` e
`stretch-full` também dos cartões de perfil e resumo, não apenas do painel de dados.
A seleção final de UI passou com **162 testes e 16 subtests**. As capturas anteriores
foram preservadas; a rodada final recebe nova captura e prova explícita de que
o coletor de erros JavaScript está instalado, sem interpretar um coletor ausente
como console limpo. A rodada final foi observada: **24 capturas**, cobrindo os
**12 estados nos dois tamanhos**, e **11 observações de interação** com coleta
de console comprovadamente ativa. Não houve overflow horizontal positivo,
controles críticos fora do conteúdo, erros/avisos JavaScript ou assets locais
falhos nas células da matriz. A OP mantém **44 px de separação** entre resumo e
dados no cenário móvel antes sobreposto; as duas abas foram clicadas e observadas.
Foram exercitados ainda menu móvel, foco/Enter até avatar, listagem→detalhe,
módulo→catálogo→formulário, erros/ARIA e Cancelar sem submissão de relatório.

Manifestos e PNGs estão em `evidence/deploy-readiness-2026-10-20/visual-qa/`.
O parecer visual do executor é **PASS, 94/100, confiança média**, restrito à
matriz declarada. As duas revisões independentes de imagens também deram **PASS**,
com notas **94 e 93**, vinculadas exatamente à revisão corrente. O recibo é
`visual-qa/independent-reviews.json`; elas não reproduziram os percursos ao vivo.
Foram preservadas quatro sugestões não bloqueantes: texto neutro no banner de
consulta, ajuda do avatar sem pressupor botão de selfie, folga do botão flutuante
no rodapé e possível ordem cronológica dos campos de período. São melhorias
residuais, não alterações silenciosas na árvore congelada durante a suíte.
Não é auditoria WCAG completa, teste em Safari/dispositivo físico ou validação
de fluxos POST. O coletor HTTP não registrou POST. Rodadas anteriores e o RED
da sobreposição foram preservados. O servidor de fixtures foi encerrado e a
porta loopback 8767 foi verificada fechada.

Ruff global passou (**576 arquivos** formatados); Mypy passou no escopo oficial
do quality gate (**398 fontes**), assim como Bandit, syntax JS/Bash e os **10
testes Node**. A tentativa ampla `mypy .` foi inadequada: encontrou um módulo de
teste duplicado no arquivo histórico em `docs/validation/evidence/archive/`.
Não foi alterada configuração nem removida evidência para ocultá-lo; o comando
correto, com os pacotes declarados no CI, foi executado e passou. Django check,
migrations, OpenAPI e o perfil production sintético também passaram novamente.

## Ambiente isolado

- PostgreSQL sintético em loopback, porta 5433; nenhum banco operacional acessado.
- Leitura de dotenv desabilitada também nos subprocessos de readiness.
- Segredos de teste sintéticos e mídia temporária; valores não registrados aqui.
- `.env` local: somente permissão alterada para `0600`, com autorização expressa;
  conteúdo não lido ou modificado.
- Os testes executáveis do agendador exigem utilitários Linux. Em macOS,
  `SHELL_TEST_IMAGE` seleciona uma imagem Linux local; cada teste usa um container
  efêmero, sem rede, com somente a pasta de fixtures sintéticas montada.
  A imagem de ferramentas não é evidência da imagem de produção do ERP.
- Em Linux os mesmos testes executam Bash diretamente. Não é necessário Docker
  para esses testes no executor Linux da integração contínua.

## Correções e justificativas

### Interface

- Restaurado o link real de alteração de avatar no menu do usuário.
- Minha área recupera título `h1`, texto PT-BR e contexto acessível.
- Seções de Minha área usam `h2` com aparência Duralux preservada. Quando não há
  permissão para filas, a mensagem é neutra: não afirma que todas as tarefas ou
  aprovações estão em dia. Cenários com e sem permissão tiveram RED/GREEN.
- Catálogo e execução de relatórios voltam a comunicar consulta e restrição de
  execução explicitamente, sem modificar as permissões de backend.
- Detalhes e auditoria preservam o comportamento Duralux sem alongar os cartões
  no grid; captions de tabelas usam a utilidade Bootstrap `visually-hidden`.
- Contratos de testes deixam de depender de classes extras e wrappers decorativos;
  continuam verificando valores booleanos traduzidos, ordenação da trilha real,
  captions e identidade dos painéis.
- As 18 falhas de UI históricas selecionadas passaram no replay dirigido.

### Backup e deploy

- Os testes carregavam scripts por descritores de substituição de processo.
  O carregamento foi substituído por arquivos regulares isolados, preservando
  `BASH_SOURCE`; não são executados deploy ou backup reais.
- Encontrado e corrigido defeito real no agendador: uma função executada em
  condição Bash não pode depender de `set -e`. Uma falha do produtor de backup
  após criar os arquivos podia ser registrada como sucesso.
- O ciclo agora verifica explicitamente o retorno do produtor, os artefatos e
  a publicação dos marcadores. Falha de publicação remove a indicação de saúde
  e não registra sucesso; operações intermediárias propagam erro.
- Duas regressões novas observaram RED antes da correção: falha do produtor mesmo
  com artefatos, e falha de publicação da saúde em contexto condicional.
- Seleção de backup/deploy: **33 testes aprovados**, com execução real dos scripts
  contra fixtures. Isso não é um ensaio de restauração de dados operacionais.
- A integração isolada revelou uma corrida adicional: um diagnóstico RabbitMQ
  executado como root antes da inicialização cria o cookie com dono `0:0` e modo
  `0400`; o broker, usuário `100:101`, falha com `eacces`. Foram observados apenas
  metadados, nunca o conteúdo do cookie. Os healthchecks dos dois arquivos Compose
  agora usam `su-exec rabbitmq` antes do diagnóstico. O teste parametrizado dos
  dois arquivos foi RED antes da correção; seleção operacional final: **35 testes
  aprovados**. Não foi aplicado Compose nem alterado volume operacional.

### Higiene, readiness e evidências

- `.gitignore` passa a proteger `.env.local` e `.env.backup*`.
- Removida uma referência documental de infraestrutura descontinuada.
- Higiene e terminologia: **8 testes aprovados** na seleção dirigida.
- Readiness: o caso de invariância de configurações/cache deixa de medir
  incidentalmente a partida fria de um novo interpretador: usa orçamento de
  teste explícito. Os testes de deadline com pares silenciosos mantêm o limite
  real de produção. Nenhum timeout ou controle de produção foi relaxado.
- Readiness: **6 testes aprovados**, incluindo os cenários de deadline.
- EV-SI-010: revalidação de engenharia autorizada expressamente pelo usuário;
  hash anterior preservado em `supersedes_sha256`. O estado do catálogo não
  concede aprovação de release ou regulatória.

### Consolidação do parecer tardio de CI e operação

- A revisão operacional/CI do **candidato corrente**, `deleg_88a95133`, deu
  `ship` com confiança média e sem achados, restrito à inspeção estática. O pai
  conferiu novamente os hashes dos **11 arquivos operacionais/testes** dirigidos
  contra o snapshot63af e os dois pareceres visuais vinculados ao mesmo alvo.
  Recibo: `review-operational-current.json`. A revisão e o registro das pendências
  estão concluídos; a integração sem concorrência passou posteriormente. A nova
  confirmação integral com cobertura passou posteriormente na quarta execução.
- O parecer independente `deleg_89df25f4`, recebido tardiamente, aprovou somente
  esse lote estático, com confiança alta e sem defeitos P0/P1 demonstráveis.
  Seu único achado P3 era a descrição contraditória da execução integral no
  relatório antigo; a leitura atual confirmou que já foi corrigida, distinguindo
  as duas tentativas interrompidas da terceira execução. O recibo foi preservado
  em `review-ci-runbook-personal-late.json`. O parecer não cobre o delta posterior
  de altura dos cartões nem substitui as revisões do candidato corrente.
- Ambos os workflows provisionam Node 24 com `actions/setup-node@v6`, referência
  conferida na documentação oficial; cache de pacotes desnecessário desativado.
- O quality gate exige Node e executa os testes JavaScript explicitamente.
  Um cenário sem Node observou falha, em vez de um skip silencioso.
- O workflow de release instala `requirements-dev.txt` e executa o mesmo quality
  gate completo, incluindo cobertura e auditorias; HSTS sintético foi declarado
  para sua validação production. `release_gate.sh` permanece identificação e
  validação opcional de metadados, não substitui o quality gate.
- O healthcheck RabbitMQ do CI também perde privilégio antes do diagnóstico.
- O runbook da VPS configura `CLOUDFLARED_METRICS_ADDRESS` como autoritativo,
  mantendo a porta reservada 20242 e os probes correspondentes; a variável legada
  isolada não é mais apresentada como suficiente. Nenhum ambiente remoto foi lido.
- Seleção do lote de revisão: **72 testes e 9 subtests aprovados**. Há recibos
  RED/GREEN dos contratos corrigidos; o HTML de falhas com CSRF sintético foi
  omitido na cópia compartilhável, sem alterar estados ou identidades dos testes.

Esse lote exige novo congelamento, rebuild e suíte integral. Os snapshots e
medições anteriores abaixo continuam históricos; não validam automaticamente
as alterações posteriores. A segunda execução integral foi interrompida de forma
controlada, com **583 casos registrados sem falhas/erros**, não como gate aprovado.

## Evidências

Diretório: `docs/validation/evidence/deploy-readiness-2026-10-20/`.

Os recibos dirigidos, resultados globais e manifesto são registrados conforme as
execuções terminam. Um arquivo ausente ou uma etapa pendente não significa PASS.
Os testes dirigidos não substituem a suíte integral com cobertura mínima de 80%.

### Gates anteriores já observados — rodadas históricas

- Replay das **28 falhas históricas: 28 aprovados**.
- Ruff global: lint e formatação aprovados, 575 arquivos no format check final.
- Mypy global: **398 arquivos** sem problemas.
- Django check, detecção de migrations e geração/validação OpenAPI: aprovados.
- Bandit: nenhum achado no escopo dos pacotes de aplicação.
- `pip-audit --strict`: **133 dependências**, nenhuma vulnerabilidade conhecida;
  houve avisos de cache descartado, sem falha da auditoria.
- `pip check`: dependências instaladas consistentes.
- Gates estruturais: operação **14**, backup/restore **15**, aceite do produto
  **8**, release **8** e catálogo de evidências **14** verificações aprovadas.
  São inspeções de código/configuração/documentação, não observação da VPS.
- `core.settings.production` com valores sintéticos: `check --deploy` aprovado
  com falha em nível WARNING. Não é validação do `.env` real do servidor.
- JavaScript: syntax check dos dois controladores aprovado; **10 testes Node**
  de impressão aprovados, sem falhas ou skips.

Primeira execução integral: interrompida de forma controlada após a descoberta
da corrida do healthcheck, para evitar validar uma árvore híbrida. O JUnit parcial
registrou **1948 casos, zero falhas e zero erros**; isso não é uma suíte integral
aprovada. Recibos e motivo da interrupção foram preservados separadamente.
A segunda execução integral também foi interrompida para consolidar correções
tardias de CI/UI; seus resultados parciais são históricos. A execução corrente
é a quarta, identificada no início deste documento; a terceira terminou com
quatro falhas e cobertura86,40%, preservadas separadamente.
Build Docker local: **aprovado**, com autorização expressa, sem push ou deploy.
Imagem local: `rgnfarmasystem:release-check-20261020`, ID
`sha256:299626c308433c66f4895d728b7432bf09deb578afddb84a51d8d04d70bf3b02`.
O ID lido de volta da tag confere com o emitido pelo build.
Rebuild após a correção do Compose: as **998 fontes** congeladas conferem,
arquivo por arquivo, com a cópia dentro da imagem. Os pacotes instalados são
idênticos aos **99 pacotes auditados**, sem vulnerabilidades conhecidas.
Seleção final de operações/readiness/evidências/higiene: **51 testes aprovados**.

Smoke na imagem real, em container efêmero sem rede e com configurações
sintéticas: `check --deploy` aprovado, **1489 arquivos estáticos** coletados,
liveness **200** e readiness **503** com todos os backends indisponíveis,
como esperado. Readiness respondeu em **3,578 s**, mantendo limite de **2 s por
probe** e `Cache-Control: no-store`. Isso comprova falha fechada, não saúde dos
serviços reais. O conteúdo de `.env` e `.env.local` não está na imagem.
Compilação dos pacotes da aplicação por `compileall`: aprovada.

### Integração local com serviços reais descartáveis

Autorizada expressamente pelo usuário, em rede Docker interna, sem portas
publicadas nem volumes de produção. PostgreSQL, Redis e RabbitMQ efetivamente
subiram; a imagem do ERP usou `core.settings.production` e valores sintéticos.
Na imagem final, foram observadas **três respostas readiness 200 consecutivas**,
com os três backends saudáveis, em **3,523 s, 4,133 s e 5,037 s** por requisição completa,
mantendo os **2 s originais por probe**. As configurações normalizadas de banco e
cache permaneceram inalteradas. Todos os containers, rede e volumes anônimos
criados por esse ensaio foram removidos; ausência verificada por leitura posterior.

As tentativas iniciais do harness foram diagnósticas, não PASS: além da corrida
de dono do cookie, aguardar o socket Unix temporário do PostgreSQL e apenas o
ping do nó RabbitMQ não comprovava prontidão de rede dos serviços. A preparação
do ensaio passou a aguardar PostgreSQL por TCP e a aplicação RabbitMQ iniciada.
Nenhum timeout ou regra de produção foi ampliado para obter o resultado.

## Pendências industriais e operacionais

1. Impressão física será testada na indústria, onde o equipamento está disponível.
   A verificação local de formulário, CSRF, seleção da linha e transporte simulado
   não valida equipamento, rede industrial, TSPL ou qualidade da etiqueta.
   Usar `docs/validation/direct-label-printing-acceptance.md` e registrar o aceite.
2. Encerramento formal de INC-2026-001 por Segurança/DPO e Qualidade, conforme
   `docs/validation/known-pending-items.md`; não pode ser simulado por testes.
3. Provisionamento do administrador e validação de credenciais por canal seguro,
   fora do Git e sem valores em logs.
4. Backup/restore, armazenamento, disponibilidade de serviços, rede e rollback no
   ambiente de destino exigem evidência operacional. Checks sintéticos locais não
   comprovam sua execução no servidor.

## Rollback e observação

Antes de executar qualquer deploy, o operador deve identificar a imagem anterior,
confirmar backup restaurável e definir responsáveis pela liberação e recuperação.
Após subir o candidato, verificar liveness/readiness, erros HTTP, filas, banco e
logs de backup. Readiness não saudável ou erro funcional crítico exige interromper
a liberação e aplicar o procedimento de rollback documentado, sem reenvio de
impressão automático. A revalidação local anterior não acessou produção nem
ensaiou seu rollback. A pré-checagem posterior acessou a VPS somente para leitura,
conforme o parecer operacional vinculado no início deste documento; não realizou
deploy nem ensaio de rollback.

## Menus, permissões e migrations

Não foi criado módulo novo. O link de avatar usa a rota existente; relatórios e
impressão continuam sujeitos às permissões de backend. As correções operacionais
não alteram o esquema: `makemigrations --check --dry-run` não detectou mudanças.
