# Seguimento técnico: popup nativo de datetime em 320 px

## Fechamento autorizado — interação responsiva

**Status atual: DONE no recorte funcional/visual de 320 px, com controle de 640 px.** O diagnóstico histórico abaixo permanece preservado, mas sua restrição de não adaptar a interação foi superada pela autorização explícita do usuário. Nenhuma regra ou persistência de domínio foi modificada.

### Interação entregue

- Até `575.98px`, o aprimoramento compartilhado oferece calendário nativo de **data** e editor de **hora `HH:MM:SS`, 24 h**, com frações quando presentes. O calendário não foi ocultado nem substituído por decoração. Há ação “Abrir calendário” utilizável por Tab/Enter e clique; o indicador nativo também permanece disponível.
- A alternativa com dois popups nativos foi rejeitada: resolvia a largura, mas o Chrome completo ainda cortava o popup de **hora** pelo topo. Esse negativo está preservado em `datetime-responsive-20261021T160627128714Z/chromium/320-mobileFalse-parent-time-click-open.png`, dentro do diretório de artefatos do projeto. Não integra o aceite final.
- O campo canônico conserva seu **nome original**, sem nomes adicionais de POST. Após aprimorar, torna-se um input textual oculto e readonly; o clone validador continua `datetime-local` e verifica `min`, `max`, `step` e sua base originais. Valores válidos seguem ISO local, sem `Date`, conversão UTC ou recorte dos segundos. Valores parciais/inválidos não viram vazio opcional válido: por exemplo, `2026-10-22T25:51:18` chega como inválido ao campo Django, que o rejeita.
- `required`, `disabled`, `readonly` inicial, reset, labels, `aria-describedby`, `aria-invalid`, abas de erros e inlines adicionados são cobertos. Alterações de `disabled`, `required`, limites e step no canônico são refletidas. Depois de aprimorado, o editor permanece dividido se a janela for ampliada, para não perder edição parcial; uma página carregada inicialmente em 640 px conserva o controle combinado original.
- Sem JavaScript, o HTML/POST/validação nativos e labels permanecem disponíveis. A edição nativa por teclado, inclusive segundos, foi exercitada. Isso **não** promete corrigir o popup combinado do navegador sem JS; o fallback acessível é a edição nativa por teclado.

### Recibo final imutável

`/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/datetime-responsive-closure-20261021T163449327156Z`

Manifesto: `manifest.json` — SHA-256 `5519f4b324e44c4571e9661540b5a87e61d2f663e5470d977969be3138cbad84`.

O recibo copia evidências focadas, sem sobrescrever originais, e verifica que os hashes de **JS/CSS de produção** nas duas execuções correspondem exatamente aos arquivos atuais. São **38 PNGs**, 19 por navegador; os JSONs distinguem janela nativa, viewport, screen e `mobile` emulado.

- Chrome for Testing `153.0.8010.12` e headless shell `153.0.8010.12`, já instalados; nenhum download.
- 320 desktop emulado e 320 com `mobile=true`, screen emulado e meta viewport, em parent e inline; 640 desktop como controle. A janela headless e o viewport são registrados separadamente. **Não houve ensaio de hardware móvel.**
- Calendários realmente abertos por **Tab → Enter** e **clique** nos botões de produção; seleção de 21 para 22 pelo teclado do calendário. Hora realmente editada com comandos de seleção do editor e `Input.insertText`, sem atribuição `.value` como prova de interação.
- POST observado após interação: `2026-10-22T09:51:18`. Texto inválido `25:51:18` continua visível para correção e o POST correspondente é rejeitável pelo servidor. Os 16 calendários abertos (8 por navegador) foram inspecionados visualmente, incluindo sete colunas, cabeçalho e ações, sem corte em 320 px. Os controles de hora permanecem inteiros inclusive na coluna inline de 173 px.

| Imagem relativa ao recibo | SHA-256 |
| --- | --- |
| `chromium/320-mobileFalse-inline-date-tab-open.png` | `de42bb514799f0e10e510b2bbc33688377cffe80e2d0327dc837a6c1e54883c8` |
| `chromium/320-mobileTrue-inline-keyboard-seconds-edited.png` | `fce0729b042601a664bf48332113f5f97093294e14e2e23ed601971ad52f811e` |
| `shell/320-mobileFalse-inline-date-tab-open.png` | `e1823979caf17780499d06cad0db15a7cee66d5e2baae542f2773daa8b33b0ad` |
| `shell/320-mobileTrue-inline-keyboard-seconds-edited.png` | `3edba7b9fdc3979378a381442e801b5239bac4c1249bfda757df3d911dba3887` |

### TDD e verificações atuais

REDs observados antes das implementações correspondentes: ausência dos editores (`None != '2026-10-21'`); POST sem sincronização; ausência do botão; gap zero; disabled não propagado; editor de hora ainda `time` em vez de `text`; inválido serializado como vazio em vez do valor inválido. Cada camada foi levada a GREEN, sem refatorar o domínio. Os testes de fronteira e servidor complementam essas regressões; não se apresentam testes de caracterização previamente verdes como RED.

Comandos a partir da raiz, todos com `TMPDIR=/Users/rgnsystems/.hermes/cache/scratch`:

```sh
RGN_UI_BROWSER_TESTS=1 RGN_UI_CHROME='/Users/rgnsystems/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-x64/chrome-headless-shell' .venv/bin/python tests/test_datetime_responsive.py
.venv/bin/python tests/test_datetime_contract.py
node --test tests/js/*.test.cjs
node --check static/js/app-form-enhancements.js
.venv/bin/ruff check tests/test_datetime_contract.py tests/test_datetime_responsive.py
.venv/bin/ruff format --check tests/test_datetime_contract.py tests/test_datetime_responsive.py
```

Resultados reais: **15 testes browser PASS**, **4 testes Django sem banco PASS**, **21 testes JavaScript PASS** (3 novos); sintaxe JS e Ruff PASS. Logs completos no recibo. O contrato Django bloqueia `.env` antes de importar settings e proíbe `ensure_connection`; verifica ISO/segundos/fuso `America/Sao_Paulo`, erros, vazio opcional, disabled e metadados comuns de ações/formulários. Não é prova de gravação em banco: nenhuma escrita em banco foi realizada ou necessária para alterar esta interação.

A reprodução visual usa `shell/probe.py` ou `chromium/probe.py` com `PROBE_OUT` novo, `RGN_UI_CHROME` apontando para binário instalado e `TMPDIR` no scratch. Servidor de fixtures é loopback; proxy/DNS e bloqueio CDP são instalados antes da navegação. Isso é contenção **no navegador**, não afirma ausência de egress no SO. Não utiliza perfil pessoal, credenciais ou runner privado.

Houve intermitência de startup/handshake e teardown do Chrome completo no harness compartilhado: uma execução fez 15 assertivas funcionais sem falhas, mas terminou com timeout de SIGTERM. Ela **não é contada como suite PASS**; a prova visual de interação do Chrome completo terminou com código 0 e a suíte focal PASS é a do shell. Logs negativos foram mantidos nos pacotes intermediários, citados no manifesto. Uma tentativa de captura com tooltip nativo de validade também expirou; o recibo final demonstra inválido por validade/POST/texto preservado, sem usar a tooltip como oráculo visual.

Escopo alterado: somente aprimoramento JS compartilhado, 19 linhas CSS de apresentação, testes focais e este seguimento. Não houve mudança em views, modelos, serviços, serializers, regras de negócio, dependências, scanner, CI, evidências originais, notas históricas de QA, commit, push ou deploy. Não foi repetida a matriz histórica de 192 condições.

### Conferência independente do integrador

O integrador reexecutou a suíte focal no shell (**15 PASS**) e os contratos Django
sem banco (**4 PASS**). Conferiu os hashes dos 58 artefatos do manifesto, das
38 capturas e das cinco fontes atuais. As 16 capturas de calendário aberto foram
inspecionadas em folhas derivadas: cabeçalho, sete colunas e ações completos;
o editor de segundos permanece visível. A observação é restrita a esse recorte,
não uma nova pontuação da matriz histórica de192 condições/QA89.

Recibo: `parent-reservation-integration-1792604236365636000.json`, no diretório
de artefatos `product-editor-simplification`. A revisão do backend, os gates
globais e a CI são etapas separadas; impressão física, hardware móvel e aceite
industrial/regulatório não foram certificados por essa conferência.

## Diagnóstico histórico — antes da autorização

## Resultado e limite de fechamento

**Status: blocked — diagnóstico reproduzido; aceite visual do popup em 320 px não fechado.**

O corte é reproduzível no seletor do próprio Chromium com HTML mínimo **sem Bootstrap, tema ou app.css**. O input permanece contido; o popup de calendário + hora ultrapassa a captura/viewport de 320 px. No mesmo navegador, com o mesmo input e valor, 640 px mostram também minutos e segundos (e AM/PM no headless shell). Isso separa o problema do popup da correção anterior do controle fechado.

Não foi demonstrada solução CSS mínima, preservando a semântica nativa, para o popup aberto. Nenhuma nova alteração foi feita em CSS, templates, widgets, tipos ou parâmetros dos inputs. As correções existentes de `min-width: 0` e padding foram preservadas. Não se atribui esse resultado a um dispositivo móvel físico nem se declara que todo navegador móvel terá o mesmo comportamento.

## Identidade e evidências

- Repositório: `/Users/rgnsystems/Documents/rgnfarmasystemv2`.
- Branch observada: `release/2026-10-20-63af02ef`.
- HEAD observado: `d805ae54cf0bb985389d22c3d0c71f355a93cd21`.
- Árvore já modificada antes da investigação; este seguimento acrescenta somente este documento.
- Pacote novo: `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/native-picker-followup-20261021T151517951987Z`.
- Manifesto: `manifest.json`, com 12 condições diagnósticas, 24 capturas fechadas/abertas, dimensões, identidades e SHA-256.
- Script reproduzível: `probe.py`; fixtures `plain.html` e `themed.html` em cada subdiretório de navegador.
- Resultados CDP: `chromium153-v4/results.json` e `shell153-v4/results.json`.
- Saídas reais: `chromium153-v4-command.log`, `shell153-v4-command.log` e `closed-direct.log`.

A evidência original foi somente lida, não sobrescrita:

`/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/browser-temporal-round6-20261021T124056469551Z/qa192/temporal-native/captures/risk-320-native-picker-click--8f0d9086aaf142a180cc95dca5d4b3be.png`

SHA-256 original: `16dba0af20d96a2ff8107f9c34511fe6c01f11bea3efaa222a5f51c37071ba02`.

Fontes preservadas nesta investigação:

| Arquivo | SHA-256 |
| --- | --- |
| `static/css/app.css` | `3cfad6519f5f23d842a81e995bdd2cadf0a99b00201f3ec86832f2dac121a0da` |
| `tests/test_resource_form_temporal_geometry.py` | `826fa80c62b3d0710c5374a6a909bda552f915599e9aa5973f8d62e71ad1c958` |

## Investigação e contraprova

Navegadores já instalados, sem download:

1. Google Chrome for Testing `153.0.8010.12`, modo `--headless=new`, macOS.
2. Chrome headless shell `153.0.8010.12`, macOS.

Uma sondagem preliminar também confirmou a instalação do Chrome `156.0.8078.48`, mas não constitui prova final de popup aberto; não é usada como PASS de compatibilidade.

Ambos os navegadores finais executaram estas condições, sem matriz de rotas:

| Fixture/condição | Observação |
| --- | --- |
| HTML mínimo, viewport 320, desktop emulado | Popup corta após a coluna de horas; minutos/segundos ficam fora da imagem. |
| Mesmo HTML e input, viewport 640 | Popup completo, incluindo minutos/segundos; shell inclui AM/PM. |
| Fixture com Bootstrap + tema + app.css, viewport 320 | Mesmo corte do popup; input continua entre x=47 e x=268. |
| Mesma fixture com tema, viewport 640 | Contraprova de largura, capturada com a mesma configuração de input. |
| HTML mínimo, viewport e screen emulados de 320 | O ajuste de screen não elimina o corte observado no shell. |
| HTML mínimo, `mobile=true`, viewport e screen de 320, meta viewport | O shell continua cortando; continua sendo emulação desktop, não mobile real. |

Capturas focais, relativas ao pacote:

- `shell153-v4/plain-320-mobileFalse-screenFalse-open.png`: reproduz o corte sem CSS do aplicativo, inclusive locale inglês/AM/PM semelhante à evidência original.
- `shell153-v4/plain-640-mobileFalse-screenFalse-open.png`: mesmo controle, popup completo.
- `chromium153-v4/plain-320-mobileFalse-screenFalse-open.png`: corte sem CSS do aplicativo, locale português/24 h.
- `chromium153-v4/plain-640-mobileFalse-screenFalse-open.png`: mesmo controle, popup completo.
- `chromium153-v4/themed-320-mobileFalse-screenFalse-open.png`: o tema não é necessário para provocar o corte.
- `shell153-v4/plain-320-mobileFalse-screenTrue-open.png` e `plain-320-mobileTrue-screenTrue-open.png`: screen/mobile emulados não são prova de resolução.

Metadados CDP distinguem explicitamente as superfícies: janela real headless de 800×1000; viewport de 320×1000; screen padrão de 800×600. Nos casos com override, screen passa a 320×1000; no caso mobile com meta viewport, `innerWidth=320`, escala visual 1. Não se confunde largura da janela com viewport capturado.

O input mínimo mantém `type=datetime-local`, `step=1` e `value=2026-10-21T09:51:17` antes/depois da invocação. Seus limites são x=47, largura=221, direita=268; `document.scrollWidth=320`. A ausência de overflow do documento não comprova contenção do popup do navegador.

### Limite do oráculo de interação

As tentativas iniciais por clique apenas produziram foco nas capturas inspecionadas. A mudança da imagem ou o nome `-open.png` **não** foram aceitos como prova de popup aberto. Esses negativos permanecem no scratch `/Users/rgnsystems/.hermes/cache/scratch/native-picker-followup`.

A rodada final usa coordenadas reais do indicador no shadow DOM, clique CDP e depois `input.showPicker()` com `userGesture=true`, seguido de espera e inspeção visual. Essa chamada abre o seletor nativo e demonstra a geometria; **não substitui** validação de usabilidade por clique/teclado em dispositivo representativo. A captura original por clique continua sendo a evidência negativa original. Não houve alteração do score nem do oráculo para transformar negativo em PASS.

## Verificação focal do controle fechado

O módulo existente foi carregado diretamente por `importlib`, sem carregar `tests/conftest.py`, Django ou banco. O wrapper `verify_closed.py` chama a fixture existente e as seis combinações parent/inline × date/time/datetime-local, sem mudar suas assertivas.

Saída final real:

```json
{"status":"passed","direct_assertion_cases":6,"identities":[["parent","date"],["parent","time"],["parent","datetime-local"],["inline","date"],["inline","time"],["inline","datetime-local"]],"django_loaded":false}
```

No datetime fechado, o conteúdo editável nativo tem client/scroll 191/191 no parent e 171/171 no inline. ISO, segundos e indicador nativo são preservados. Isso verifica apenas o contrato existente do controle fechado, não aprova o popup aberto.

Uma tentativa anterior de pytest com `-c /dev/null --confcutdir=...` ainda importou o conftest do repositório e parou com `ImproperlyConfigured: Requested setting INSTALLED_APPS, but settings are not configured`. Nenhum banco foi acessado. O wrapper direto foi a alternativa isolada; não é relatado como execução da suíte Django.

## Reprodução isolada

A partir da raiz do repositório, usando um diretório de saída **novo**:

```sh
PROBE_OUT=/Users/rgnsystems/.hermes/cache/scratch/native-picker-followup/repro-novo \
PROBE_BROWSER='/Users/rgnsystems/Library/Caches/ms-playwright/chromium_headless_shell-1243/chrome-headless-shell-mac-x64/chrome-headless-shell' \
TMPDIR=/Users/rgnsystems/.hermes/cache/scratch \
.venv/bin/python /Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/native-picker-followup-20261021T151517951987Z/probe.py
```

O script cria perfil descartável dentro da saída; serve somente fixtures e três CSS locais em loopback; antes da navegação bloqueia HTTPS/FTP via CDP e usa proxy fechado + regras DNS para impedir destinos externos. CSP impede scripts/fontes externos. Não usa perfil pessoal, credenciais, `.env`, runner privado, Django ou serviço operacional. Os processos criados são encerrados em `finally`. O pacote não inclui os perfis descartáveis.

## Decisão necessária

Não há base para novo ajuste de CSS de produção nem para declarar a ressalva resolvida. É necessário escolher uma destas saídas, fora da autoridade deste seguimento:

1. Validar o seletor nativo no dispositivo/navegador realmente suportado e decidir, com essa evidência, se a captura desktop emulada representa um defeito do alvo. Preservar o negativo atual e documentar explicitamente eventual aceitação de limitação do navegador.
2. Se o produto exigir popup completamente visível também nesse Chromium desktop a 320 px, autorizar uma revisão do widget/interação e seus requisitos de acessibilidade, validação e persistência. Isso ultrapassa a mudança CSS mínima autorizada e não foi implementado.

Nenhum commit, push, deploy, instalação de pacote ou acesso a banco foi feito. Nenhuma evidência antiga foi alterada.
