# Simplificação dos formulários e revisão dos inputs

## Limites e critério de remoção

A simplificação reduz a digitação e os elementos que não representam uma ação ou
um dado real. Não exclui colunas, registros, controles de permissão, campos de
rastreabilidade, informações fiscais ou decisões de qualidade. Um campo opcional
no banco não é, por isso, desnecessário para a operação.

Não se converte texto em FK apenas por semelhança do nome: é necessário encontrar
o cadastro de destino, a semântica do vínculo e o comportamento dos dados legados.
Texto e referência normalizada coexistentes precisam de um contrato de
sincronização antes de qualquer remoção. A revisão dos selects dependentes tem
inventário e testes próprios; um select estático não comprova uma cascata funcional.

## Inventário inicial de todos os templates

O inventário estático inicial leu **58 templates HTML**, incluindo páginas,
componentes e renderizadores compartilhados. Encontrou controles HTML diretos em
8 templates (19 controles) e renderização dinâmica de formulários em 10 templates.
Esses conjuntos podem se sobrepor. O JSON registra um item por template, o hash,
os identificadores dos controles e a decisão de preservação; não coleta valores,
credenciais ou dados operacionais.

Artefato local: `~/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/template-input-inventory.json`.
Esse inventário é um snapshot anterior ao término do novo editor de produtos;
novos templates serão incluídos na integração final. Não é uma aprovação visual
ou uma alegação de que todas as informações de negócio podem ser removidas.

## Mudanças observadas no recorte compartilhado

- **Identificadores automáticos na criação:** deixaram de ocupar campos visíveis.
  Continuam desabilitados no servidor, ignoram valores forjados e são gerados pelo
  mecanismo existente. Na edição permanecem visíveis e imutáveis. Códigos manuais
  e campos fiscais/qualidade não foram ocultados por essa regra.
- **Relatórios e execução:** reutilizam o renderizador de campos existente,
  preservando labels, ajuda, erros, classes responsivas e controles obrigatórios.
  Campos ocultos são renderizados uma vez, sem label/célula vazia na grade.
- **Leitor documental:** passa a mostrar `ControlledDocument.content`, escapado,
  ou uma mensagem de conteúdo ausente. Foram retirados o POP fictício, a marca
  estática de cópia controlada, a atribuição fictícia de treinamento e botões sem
  implementação de impressão/assinatura/tela cheia. Código, versão, responsável,
  área, publicação e status reais permanecem. Isso não remove o backend de gestão
  documental, de distribuição ou de treinamentos e não implementa assinatura.
- **Preservados:** CSRF, campos de autenticação, confirmações de operações,
  identificadores de linhas, management forms, DELETE, filtros de pesquisa,
  permissões e ações operacionais reais. Não houve alteração de schema/migration.

## Evidências locais deste recorte

- Identificadores: **5 RED / 2 PASS** antes do ajuste; integração posterior com
  as proteções automáticas existentes: **24 PASS**.
- Conteúdo documental real: **1 RED** antes do ajuste; leitor e rotas existentes:
  **3 PASS** após o ajuste.
- Hidden fields nos dois renderizadores: **2 RED** antes do ajuste; integração
  com ações, views adicionais e metadados: **29 PASS** após o ajuste.
- Conjunto ampliado desta etapa: **111 PASS**, com compilação dos templates
  presentes na coleta. Ruff check/formato dos dois novos testes passaram; mypy
  de `base/ui/forms.py` também passou no checkpoint observado.

Os números acima são conjuntos executados separadamente e **não devem ser
somados** como se fossem casos únicos. Evidências JUnit estão no mesmo diretório
do inventário. O código dos fluxos Produto/Fórmula/Componentes e dos filtros FK
segue em desenvolvimento paralelo; esses resultados não aprovam o candidato
integrado, o navegador, o CI ou um deploy. Não houve commit/push/deploy deste
novo pedido. O bloqueio anterior de dependências no CI permanece separado.

## Navegador: baseline preliminar observado

As telas de novo Produto, nova Fórmula mestra, nova Categoria e leitura
documental foram abertas em Chrome 145 a **320 × 1000** e **1440 × 1000**.
Foram preservadas **14 capturas únicas**, com hashes conferidos e fonte congelada
`a7c250e1c015acd354a44c5de904ed30279a4c2fd8f860cbec3280d640f387a1`.
Não houve overflow horizontal do documento/controles nos estados registrados,
nem erros, warnings ou eventos de falha de recurso nos coletores instalados.
Isso não equivale a uma auditoria completa de status HTTP ou acessibilidade.

Foram observadas trocas de abas nos dois tamanhos, a remoção da aba Produto de
Fórmulas e a abertura por teclado do cadastro de categoria na aba Componentes.
Um clique automatizado sofreu timeout de transporte; não foi classificado como
defeito do produto. O texto e os controles ficaram legíveis nos estados capturados.
O assistente flutuante deixou de aparecer sobre formulários (RED/GREEN próprio,
com quatro testes de presença/ausência e permissões aprovados), mas permanece
nas telas de consulta autorizadas.

Parecer deste baseline: **REVISE, 88/100**, não aprovação final. O cadastro rápido
de material ainda exibia campos demais e a fonte congelada ainda não carregava
o novo módulo de selects dependentes. O carregamento foi integrado posteriormente
com RED/GREEN; precisa de nova captura com a fonte resultante, dados tipados e
troca real das opções. O servidor do baseline era GET-only, foi encerrado e não
comprova gravação. Integração, POST/rollback/permissões, tamanhos de tablet e
recaptura final continuam pendentes.

Evidências locais: `browser-baseline-1/{served-source,observations,visual-verdict}.json`
e `browser-baseline-1/captures/`, no diretório de artefatos desta simplificação.

## Relações nos formulários de ações

O mesmo contrato de dependências passou a ser aplicado ao construir os
formulários de ações e ao validar seu envio. A configuração continua lazy:
instanciar um formulário não exige acesso ao banco. Os metadados usam o prefixo
real do formulário e partem dos querysets já autorizados; o mecanismo não amplia
as opções disponíveis. Combinações inconsistentes são rejeitadas no servidor,
inclusive sem JavaScript.

Dois testes novos falharam antes da integração por ausência dos metadados.
Após o ajuste, **15 testes passaram**, incluindo ações existentes, frontend,
querysets restritos e limites de permissão/CSRF na saída de estoque. Ruff check,
formato e mypy do arquivo de ações são verificados separadamente.

O lote de avisos assíncronos preservou dois REDs esperados, uma tentativa sem
coleta por caminho de teste inexistente e uma regressão com **2 falhas / 87 PASS**
por consulta antecipada ao banco. Os dois casos exatos dessa regressão passaram
na reprodução independente atual, sem acrescentar marca de acesso ao banco.
O XML reutilizado pelo executor depois passou a conter **89 PASS**; uma cópia
imutável desse resultado foi preservada separadamente, sem atribuí-la à execução
anterior. Houve também uma tentativa do integrador sem coleta por caminho
inexistente; a repetição usou os nomes reais e produziu os 15 PASS citados acima.

Artefatos: `action-related-red.xml`, `action-related-green-fixed-path.xml`,
`parent-lazy-field-check.xml` e `async-failure-batch-reconciliation.json`.
São verificações parciais: não encerram a integração de inlines, o fluxo completo
de Produto/Fórmula, a revisão no navegador ou os gates de release.

## Auditoria ampliada da registry conferida

O inventário relacional foi relido e suas contagens, unicidade e somas foram
recalculadas: **200 recursos, 234 ações, 696 formulários e 4.825 ocorrências de
campos**. Foram conferidos também os hashes das sete fontes do handoff. São
definições de criação/edição, inlines, management forms e ações; não representam
696 telas autenticadas visitadas no navegador. As **141 ocorrências** de texto
ou choice com referência normalizada foram identificadas e preservadas, não
convertidas por semelhança de nome.

Depois da integração básica dos hooks, uma rodada independente aprovou **19
testes Python** de relações, ações e inlines; **6 testes Node** passaram novamente.
Esses conjuntos se sobrepõem aos anteriores e não são somados. O RED original da
regressão de construção pura também foi localizado em
`related-regression-red.xml`, com 2 falhas; o GREEN separado contém 89 casos sem
falhas. Os dois resultados permanecem distintos.

Lacuna ainda aberta: o Django injeta o FK oculto do pai depois do `__init__` de
um inline. Em recebimentos, filtrar `order_item` exige contexto autoritativo do
pedido do pai, considerando sua alteração no POST. Não se torna `receipt`
editável nem se confia no hidden recebido do cliente para contornar essa lacuna.
Ela foi encaminhada ao responsável por `views.py`, antes de congelar as fontes
para testes HTTP e nova rodada no navegador.

Evidências adicionais: `related-handoff-parent-verification.json`,
`related-input-inventory.json` e `parent-fk-hooks.xml`. A matriz funcional
integrada e o navegador continuam pendentes; o inventário não é aceite de release.

## Integração de recebimentos e rodada local seguinte

A lacuna do pai oculto de recebimento foi reproduzida com HTTP autenticado:
faltavam os metadados e um item de outro pedido era aceito (**2 RED**). A
configuração agora ocorre em `BaseInlineFormSet.add_fields()`, depois da injeção
do Django, e usa o formulário pai real para o controlador `order`, inclusive
prefixos e mudanças no POST. O hidden `receipt` não foi exposto nem confiado.
Uma tentativa de omitir linhas persistidas ao trocar o pedido também foi
reproduzida; uma checagem final, dentro da transação de gravação, recusa e reverte
o conjunto inconsistente.

O recorte integrado ampliado executou **597 testes e 7 subtestes sem falhas**;
isso antecedeu o último endurecimento do `PurchaseReceiptItem.clean()`. Foram
então reproduzidos mais **3 HTTP 500** em envios incompletos (FK/item/produto ou
quantidade ausentes). Comparações e acessos a FKs passaram a considerar ausência
de dados, mantendo os erros obrigatórios e as regras de quantidade/produto. O
novo recorte de recebimentos/compras/relações teve **33 PASS**. Esses conjuntos
não devem ser somados. A checagem mypy também identificou e permitiu corrigir o
tipo da base dinâmica e a composição de views do editor, sem suprimir erros ou
trocar a base real do formulário.

O navegador da rodada `browser-integrated-round3` registrou **57 capturas únicas**
em **320, 768, 1024 e 1440 px**, com hashes e fonte conferidos no encerramento.
Foram observados Tipo→Categoria superior (inclusive limpeza de valor incompatível),
pedido→item do recebimento e novas linhas dinâmicas, as três abas de Produto,
as duas de Fórmula e o cadastro mínimo de material com quatro campos. Houve
gravação de recebimento, categoria e material fictícios com readback SQL; os
dados principais do Produto permaneceram no formulário durante os cadastros
relacionados. Os coletores instalados não registraram erros/warnings/falhas de
recurso; não houve overflow horizontal do documento. A métrica global de
controles fora da tela conserva os botões do menu lateral recolhido e não foi
silenciosamente convertida em aprovação de acessibilidade.

Essa rodada usa ator sintético por middleware local, não comprova login E2E e
antecede os últimos guardas de dados incompletos. O servidor foi encerrado com
teardown e porta fechada conferidos. A revisão das dependências excluídas do
inventário está em andamento; não há aprovação global, novo CI, commit ou deploy.

Evidências: `receipt-parent-red-http.xml`, `receipt-parent-omission-red.xml`,
`receipt-incomplete-{red,green}.xml`, `combined-related-editor.xml` e
`browser-integrated-round3/{interaction-checkpoint,receipt-browser-save-readback,related-browser-create-readback}.json`.

## Legibilidade das ações e nova matriz local — rodada 5

O stylesheet próprio é `static/css/app.css`, carregado depois do Bootstrap e do
tema Duralux em `base.html`. O tema fornecia **Salvar/Cancelar 10 px** e
**Adicionar 9 px**. A correção contém somente `.resource-form .btn { font-size:
12px; }`: não altera vendor, inputs, cores, regras de domínio, permissões ou
estrutura de abas. Os 12 px são um critério local de legibilidade das ações,
**não** um mínimo universal da WCAG.

O novo `tests/test_resource_form_action_typography.py` é opt-in e usa Chromium
real já instalado, os estilos reais e os templates de ações. Antes do ajuste,
as quatro larguras produziram **4 RED**, com as fontes 10/9 px registradas.
Depois houve **4 GREEN**, incluindo preservação dos inputs, checkbox, cores e
botões fora do resource form. A comparação do checkbox foi corrigida para o
controle equivalente externo, em vez de pressupor um tamanho inteiro de 13 px;
o RED da tipografia permanece preservado. A regressão ampliada executou **297
PASS**, e os dois arquivos JavaScript tiveram **8 PASS**. Ruff check e formato
do novo teste passaram. Esses conjuntos se sobrepõem e não devem ser somados.

Nova pasta, sem substituir as rodadas anteriores:
`~/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/browser-readability-round5-20261021T121455560542Z/`.
Os arquivos `red.xml`, `green.xml`, `regression.xml` e `qa192/` conservam a
evidência. A execução opt-in usa `RGN_UI_BROWSER_TESTS=1` e `RGN_UI_CHROME`
apontando para Chromium existente; os comandos exatos estão no handoff. Nenhuma
dependência foi instalada. Os runners bloqueiam `environ.Env.read_env` antes de
importar Django, usam exclusivamente `test_cosmos_related_fields_tests` em
`127.0.0.1:5433` e ator sintético loopback, não login real.

A fonte de runtime foi congelada antes da navegação e permaneceu igual nas
**176 fontes**: `af96eee5d098c31a8d40573b4c9366fd6c455ae61e83e0174558bd16df981cc9`.
Somente `static/css/app.css` difere do manifesto da matriz anterior. Foram
repetidos **48 formulários / 25 módulos / 192 combinações**, nas larguras 320,
768, 1024 e 1440, com **800 cliques de abas e 192 cliques reais de Cancelar**.
As **2.096 amostras de ações** nos 992 estados medidos resultaram em **12 px**.
ARIA, seleção/foco da aba, unicidade e overflow do documento foram observados;
isso não transforma os negativos individuais em uma aprovação de acessibilidade.

Nos dois campos exatos do LIMS320, `id_results-0-text_result` e
`id_results-0-result_status`, houve Tab real desde a aba Resultados. O primeiro
entrou no scrollport pelo comportamento nativo; o segundo precisou de wheel
horizontal real para ficar integralmente visível, mantendo o foco. O testemunho
anterior, com cerca de 4 px do segundo campo recortados, permanece no pacote.
Não se usou `.focus`, `DOM.focus` ou atribuição de `.value` como substituto.
O app não foi alterado para este caso. Os detalhes de Produto também foram
abertos por clique real e percorridos por Tab nas quatro larguras; tentativas
anteriores de oráculo/tecla sem abertura continuam registradas separadamente.

Os checkboxes continuam com cerca de **13,44 × 13,44 px**. Todas as 264
observações têm labels associados; o clique real no label de “Bloqueia compras”
alternou o valor e focou o checkbox nas quatro larguras. Esse label mede cerca
de **105,63 × 19,19 px**: não foi chamado de alvo 24 × 24 nem de conformidade
WCAG 2.5.8. A avaliação de espaçamento/exceções e a auditoria AA completa seguem
fora do que está comprovado. O oráculo geométrico legado conserva seus negativos.

**Parecer novo: REVISE, 89/100, não PASS.** A matriz encontrou outro negativo em
`risks/records`, aba Avaliações de risco, a 320 px: o datetime
`id_assessments-0-assessed_at` tem aproximadamente 249,52 px dentro de uma coluna
de 173 px. Após Tab e wheel vertical reais, ele continua atravessando a borda do
card e termina em x=320,52, além da área útil de 315 px. A captura suplementar
confirma o recorte; o caso não foi descartado nem atribuído historicamente ao
baseline, que usava outro Chrome. Corrigir o tamanho intrínseco desse **input**
exige autorização separada, pois este recorte proibiu mudar inputs. Essa pendência
impede elevar honestamente a rodada a 90 ou aprovar todos os controles.

Os coletores registraram zero erros/warnings JavaScript. As respostas locais
observadas foram HTTP 200 ou 304; o evento bruto de erro no LINK do tema, causado
pelo import de Google Fonts intencionalmente bloqueado, não foi apagado nem
confundido com erro JavaScript. As fixtures scratch emitiram cinco warnings de
marks pytest não registrados; não se alterou configuração para ocultá-los.

O Chromium cacheado usado nesta rodada é **153.0.8010.12**, sem o updater do
Chrome instalado. Proxy externo apontado a loopback sem serviço, DNS negado,
bloqueios CDP e sandbox nativo foram mantidos. A tentativa de sandbox macOS
externo voltou a impedir a inicialização do sandbox filho: foi preservada, sem
`--no-sandbox` ou enfraquecimento do renderer. **Isolamento absoluto de egress no
nível do SO continua não comprovado**, um bloqueador separado se esse nível de
garantia for obrigatório; não é substituído por flags CDP/proxy.

Servidores/navegadores desta rodada foram encerrados, portas verificadas e
teardown sintético conferido, com migrations e metadados de permissão retidos.
Não houve CRUD real, integração externa, commit, push, deploy ou publicação.

## Contenção temporal e revalidação local — rodada 6

O recorte autorizado corrigiu somente CSS e acrescentou o teste opt-in
`tests/test_resource_form_temporal_geometry.py`. O mínimo automático do controle
nativo, como item de grid, fazia `datetime-local` ocupar aproximadamente
250,52 px numa coluna de 173 px. `max-width: 100%` e o `min-width: 0` dos
wrappers não bastavam. A regra existente dos controles recebeu `min-width: 0`.
Isso conteve a caixa, mas **ainda recortava a hora internamente**; esse GREEN
apenas externo não foi aceito como aprovação visual. Em mobile, somente inlines
que contêm `datetime-local` recuperam espaço com padding horizontal zero no corpo
e 0,5 rem nas linhas. A coluna de riscos passa a **221 px**, sem diminuir fonte,
trocar tipo, esconder overflow, remover calendário ou alterar valor.

O teste usa os estilos reais, wrappers pai/inline, precisão de segundos e uma
coluna estreita medida. Além dos retângulos externos, exige localizar de fato o
`-webkit-datetime-edit` nativo e compara seu `scrollWidth` com `clientWidth`.
As primeiras fixtures não reproduziram o defeito porque a CSP rejeitava a largura
inline; essas tentativas foram preservadas e a geometria passou a ser servida
por CSS local. Antes da correção houve **1 RED geométrico** e, depois de apenas
conter a caixa, **1 RED do conteúdo nativo** com os wrappers reais. O replay do
teste final contra o CSS imutável da rodada 5 produziu **2 RED / 4 PASS**; contra
o CSS final, **6 GREEN** (`date`, `time` e `datetime-local`, pai e inline).
O replay é contraprova posterior, não é apresentado como o RED inicial.

A fonte final de runtime foi congelada nas mesmas **176 fontes**:
`fd67ff965061f009950d36f8ff3a6475bda9779ce44ed792e35e1e3f9dd874e1`.
Somente `static/css/app.css` difere da rodada 5. A matriz voltou a executar
**48 formulários / 25 módulos / 192 combinações**, em 320/768/1024/1440 px.
Duas ativações de aba deram timeout no primeiro percurso (Riscos1024/Avaliação e
Relatórios320/Filtros). Os registros originais permanecem intactos; as duas
células exatas foram reexecutadas com ponto nativo de clique estável após scroll,
sem mudar os oráculos de ARIA/foco/seleção/geometria. A composição explícita de
190 células originais e duas rechecadas contém **800 abas, 192 Cancelar, 992
estados e 2.096 amostras de ações, todas com 12 px**. Não se alega que a primeira
passagem terminou sem falhas, nem se atribuem conclusivamente os timeouts ao app.

Em Riscos, o alvo `id_assessments-0-assessed_at` recebeu Tab nativo desde a aba,
seta nativa, clique no indicador e Escape, nas quatro larguras. Caixa, texto com
segundos e indicador cabem; o valor ISO lido e seu atributo permaneceram iguais.
Em 320, o conteúdo nativo tem `clientWidth = scrollWidth = 171 px`. Houve ainda
**78 observações** de temporais reais em pais/inlines de compras, qualidade,
riscos e outros recursos selecionados, em 320/768, sem rejeição do valor HTML ou
recorte nativo detectado; são 48 `date` e 30 `datetime-local`. O irmão `time` foi
exercitado no teste isolado, não é alegado como campo de uma rota real visitada.
O LIMS320 repetiu Tab desde a aba e wheel horizontal real nos dois alvos exatos,
com foco mantido e sem `.focus`, `DOM.focus` ou atribuição de `.value`. Detalhes de
Produto e clique no label do checkbox também foram repetidos nas quatro larguras.

**Parecer visual desta rodada: REVISE, 89/100.** O defeito da caixa e do texto
fechado está corrigido, mas a captura do **popup nativo aberto em Chromium153 a
320 px** mostra a área de seleção de hora excedendo a lateral direita. O ícone e
o calendário abrem; isso não comprova visualização integral de todo o popup.
A evidência negativa foi mantida, sem trocar o widget ou mudar o navegador para
obter PASS. O fechamento visual irrestrito em 90+ continua pendente de resolver
ou adjudicar essa limitação do popup no escopo autorizado. Não se confunde esse
achado com o antigo clipping da caixa, já reparado, nem se certifica WCAG AA.

A revisão própria inspecionou 16 pranchas com as 192 células iniciais e hotspots
em resolução original; não há segundo revisor independente ou inspeção manual de
todos os pixels dos 992 estados. Permanecem os negativos brutos de checkbox
~13,44 px, label ~19,19 px, tabs sem campos e import de Google Fonts bloqueado.
Não houve erros/warnings JavaScript nos estados medidos; respostas HTTP locais
foram 200/304. Isso não transforma os negativos em conformidade geral.

A regressão focada pós-CSS executou **303 PASS**, incluindo os seis novos testes;
**8 Node**, Ruff check/formato e `git diff --check` passaram. Não se repetiu a
suíte global anterior, nem se atribuem a ela os seis novos casos. Esses totais
se sobrepõem. Nenhuma dependência, Python de produção, template, domínio, widget,
valor ou permissão foi alterado por este recorte. Sem commit/push/deploy.

Evidências novas, preservando todas as rodadas anteriores:
`~/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/browser-temporal-round6-20261021T124056469551Z/`.
O handoff referencia XMLs, contraprova baseline, fontes/hashes, matriz bruta e
composição rechecadas, capturas únicas, negativos e cleanup. O Chromium153
cacheado manteve o sandbox nativo; proxy/DNS/bloqueios CDP não são prova de egress
absoluto do SO. As fixtures impediram dotenv operacional antes de importar
Django e usaram somente ator e DB sintéticos em loopback. Encerramento dos
navegadores/servidores, oito portas fechadas e banco sintético sem negócio/ator
foram relidos; migrations e metadados auth/contenttypes permaneceram.

