# Formulários operacionais com abas — validação

## Escopo e limites

Implementação local sobre `d8b179c77787806f463d1d637a526bbdf0436d22`, conforme
`.hermes/plans/2026-10-19_234634-abas-duralux-formulas-e-formularios.md`.
As alterações P1 anteriores permanecem separadas conceitualmente; a árvore
contém ambos os trabalhos não commitados. Não houve push nem deploy.

O cabeçalho de abas e o alinhamento de campos reutilizam o padrão de
`design_system/customers-create.html`, sem importar seus scripts de demonstração.
A aba Produto seleciona um cadastro existente: não edita `masters.Product`.
Um único formulário envia pai e filhos pelas transações e permissões existentes.
Não houve mudança de schema, cadastro de permissões ou menu.

| Recurso genérico | Organização |
| --- | --- |
| `formulations/formulas` | Produto / Fórmula mestra / Componentes em cartões |
| `production/orders` | Informações gerais / inlines disponíveis |
| `procurement/orders` | Informações gerais / inlines disponíveis |
| `procurement/receipts` | Informações gerais / inlines disponíveis |
| `quality/analyses` | Informações gerais / resultados, preservando editor QC |
| `documents/controlled-documents` | Informações gerais / inlines disponíveis |
| `deviations/events` | Informações gerais / inlines disponíveis |
| `capa/records` | Informações gerais / inlines disponíveis |
| `audits/plans` | Informações gerais / inlines disponíveis |
| `audits/findings` | Informações gerais / inlines disponíveis |
| `risks/records` | Informações gerais / inlines disponíveis |
| `recalls/campaigns` | Informações gerais / inlines disponíveis |

Recursos sem filhos preservam o formulário simples. Cockpits, quadros de execução,
fluxos especializados, páginas de detalhe e Admin não são convertidos por esta
mudança. As verificações HTTP dos doze recursos não representam homologação
visual individual de todos eles.

## Testes automatizados observados

- Baseline limpa de componentes: **30 aprovados** antes da alteração visual.
- Agrupamento: RED antes do helper; GREEN inicial de **7 casos**.
- Templates e superfície HTTP: RED antes da integração; GREEN inicial de **24 casos**.
- Cartões de fórmula: teste alterado para exigir `stacked`, com RED observado.
- Seleção final direcionada: **102 aprovados**, incluindo agrupamento, renderização
  dos doze recursos, criação/edição/reaproveitamento de fórmula, erros, permissões,
  rollback, exclusão e as quatro regressões P1 anteriores. Contagens anteriores
  se sobrepõem e não devem ser somadas.
- Ruff dos arquivos Python da feature, MyPy do helper e das views, sintaxe JS com
  `node --check` e `git diff --check`: aprovados nas verificações locais.

Para reproduzir a seleção no PostgreSQL de testes pelo runner oficial:

```bash
./scripts/test.sh tests/test_resource_form_tabs.py \
  tests/test_formula_inline_components_ui.py tests/test_formulations.py \
  tests/test_p1_collection_permissions.py tests/test_p1_production_stale_updates.py \
  tests/test_p1_stock_balance_retention.py tests/test_p1_stock_lot_identity.py -q
```

Nesta execução, um wrapper externo desabilitou dotenv e usou exclusivamente bases
sintéticas isoladas. Não foram usados dados nem banco operacional.

### Defeitos encontrados na verificação real

1. **Grade no celular:** os gaps de doze colunas excediam o espaço interno do
   cartão a 320 px. A regra mobile agora usa uma coluna, reduz o padding local
   e permite quebra na barra de inclusão. Após estabilizar as transições, todas
   as larguras foram medidas novamente; os controles ficam dentro dos pais.
2. **Linha nova descartada:** adicionar uma linha vazia, excluí-la e enviar
   provocava HTTP 500, pois a validação do model comparava quantidade ausente
   com zero. O teste RED reproduziu `TypeError`; o formulário inline agora pula
   apenas a validação de model de instâncias novas marcadas `DELETE`. O formset
   e a autorização continuam sendo executados. O teste passou e o mesmo fluxo
   foi repetido no servidor reiniciado, incluindo gravação e leitura de volta.
3. **Exclusão sem JavaScript:** a revisão independente identificou que o checkbox
   dos cartões estava sempre oculto. A regressão foi confirmada no template e
   em teste RED. O checkbox rotulado Remover agora aparece no HTML básico;
   somente após registrar o listener de exclusão ele é trocado pelo botão.
   O teste passou e a exclusão foi executada no navegador sem scripts, com
   POST e GET de leitura confirmando zero filhos persistidos.
4. **Bootstrap Tab indisponível:** o caminho estático estava legível, mas excluir
   uma linha com quantidade de precisão inválida deixava o controle oculto ainda
   habilitado e bloqueava a validação HTML. O cenário foi reproduzido no Chromium
   e em teste RED. A desabilitação foi movida para o listener compartilhado de
   exclusão, sem depender de Bootstrap e sem duplicação no controlador de abas.
   DELETE desabilitado é respeitado; campos hidden continuam habilitados. Após
   a correção, o cenário fez POST e a leitura confirmou que a linha descartada
   não foi persistida e o filho original foi mantido.

## Evidência no navegador

Servidor QA em loopback, com sessão e dados sintéticos próprios. A inspeção
foi realizada no Chromium real, não deduzida a partir dos templates.

- As três abas foram medidas em **320, 768, 1024 e 1440 px** de largura,
  com 900 px de altura: nenhum overflow horizontal da página ou de controles
  sobre seu contêiner nas doze combinações finais.
- Capturas de componentes em desktop e celular foram inspecionadas: cartões,
  rótulos, campos e botão de inclusão permanecem legíveis; no celular, as abas
  quebram linha e os campos são empilhados. Textos longos em selects mantêm o
  comportamento nativo de seleção.
- ArrowRight, ArrowLeft, Home e End trocaram seleção, painel ativo e foco.
- Campo obrigatório na aba Fórmula mestra e quantidade com precisão inválida
  na aba Componentes abriram a seção correta e receberam foco; o overlay de
  processamento permaneceu oculto.
- Quantidade zero chegou ao servidor: o retorno manteve o valor e abriu
  Componentes com o erro “A quantidade deve ser maior que zero.”.
- Adicionar e descartar uma linha nova, corrigir a quantidade para 6 e salvar
  redirecionou para o detalhe. Um GET posterior de edição confirmou `6.0000`,
  um único filho persistido e ausência de badges de erro.
- Com execução de JavaScript desativada antes do reload, o cabeçalho ficou
  oculto, os três painéis ficaram visíveis e `noValidate` permaneceu falso;
  a página de 320 px não apresentou overflow horizontal.
- No mesmo modo sem scripts, Remover ficou visível e o botão aprimorado oculto.
  Um clique nativo no checkbox, seguido de Salvar, excluiu o filho; a leitura
  posterior confirmou `INITIAL_FORMS=0`. Com scripts, o botão volta a ser
  exibido e o checkbox fica oculto. A seleção final reúne **25 cenários**
  deduplicados, todos aprovados; as verificações de interação e dimensões
  foram repetidas após esta correção.
- Com JavaScript ativo e `bootstrap.Tab` indisponível antes da inicialização,
  os três painéis ficaram visíveis e a validação HTML permaneceu ativa. Adicionar
  uma linha, informar quantidade inválida e descartá-la manteve a submissão
  válida; o GET posterior confirmou somente o filho original.
- Durante a execução instrumentada de teclado/validação, foram observados
  zero `console.error`, zero `console.warn` e zero erros JS/rejeições não tratados.
  A árvore de acessibilidade apresentou três tabs nomeadas corretamente.

Artefatos em `evidence/resource-form-tabs/`:

- `components-320.png` e `components-1440.png`: capturas finais inspecionadas.
- `no-js-320.png`: fallback renderizado sem execução de scripts.
- `browser-raw.json`: observações históricas, inclusive medições intermediárias;
  não interpretar uma medição anterior às transições como o resultado final.
- `browser-final.json`: observações finais deduplicadas por cenário e dimensão.
- `directed-junit.xml`: seleção direcionada final.
- `empty-delete-red.xml`: regressão antes da correção.
- `native-delete-red.xml`: regressão do fallback antes da correção.
- `bootstrap-delete-red.xml`: regressão da exclusão sem Bootstrap antes da correção.
- `manifest.json`: hashes dos arquivos de código e resultados estruturados.
- `review-followup.json`: rastreabilidade do P2 encontrado e sua correção.
- `review-delta.json`: revisão independente da correção do fallback, sem achados,
  com confiança alta. O revisor conferiu código, hashes e artefatos; não
  reexecutou os cenários funcionais nem avaliou a release geral.
- `review-broad.json`: revisão ampla da feature, sem achados bloqueantes e com
  confiança média, no snapshot anterior aos dois ajustes finais do cliente.
- `review-bootstrap.json`: revisão independente do último ajuste do listener,
  `ship`, confiança alta, sem achados, sobre os hashes da fonte final.
- `full-suite-summary.json`: totais integrais e classificação das falhas.
- `full-suite-junit.xml.gz` e `full-suite-coverage.xml.gz`: artefatos integrais
  comprimidos sem alteração de conteúdo; podem ser abertos com gzip.
- `readiness-replay.xml`: replay da falha ambiental com uma base sintética existente.
- `catalog-impact.json`: comparação do hash aprovado com o teste alterado.
- `ev-si-005-revalidation.json`: autorização explícita e revalidação de engenharia
  do único item atualizado no catálogo; `final-replays.xml` registra três casos verdes.

A inspeção não equivale a certificação WCAG, ensaio em dispositivos físicos,
teste de carga ou validação regulatória IQ/OQ/PQ.

## Gate de fechamento

A suíte completa terminou com **2.565 aprovados, 28 falhas e 42 subtestes
aprovados**, exit code 1. O XML reúne 2.635 casos contando os subtestes. A
cobertura Python de linhas foi **86,39% nessa captura**. A execução integral
precede os dois ajustes finais do cliente; a fonte final passou separadamente
nos 102 testes direcionados e nos 25 cenários do navegador.

Classificação das 28 falhas, por comparação de IDs com o replay P1 anterior:

- **25 já registradas anteriormente**: não foram atribuídas à feature de abas.
  O histórico está em [p1-integrity-corrections.md](p1-integrity-corrections.md).
- **1 ambiental do runner**: o probe saudável usou um nome-base não criado,
  enquanto o pytest trabalhava na base com prefixo `test_`. O replay apontando
  para a base sintética existente passou, sem alterar código ou cache operacional.
- **2 no catálogo de evidências**: ambas decorrem de `EV-SI-005`, cujo artefato
  `tests/test_formula_inline_components_ui.py` foi alterado para o novo contrato
  visual. O hash no HEAD correspondia ao catálogo aprovado; o atual é diferente.
  O catálogo permaneceu intacto até autorização explícita do usuário. Depois
  dessa autorização, somente EV-SI-005 foi revalidado como evidência de engenharia,
  com novo hash, referência ao hash anterior e registros de testes/revisões.
  Os dois testes de auditoria do catálogo e o replay ambiental passaram juntos:
  **3 aprovados**. Isso não equivale a homologação regulatória ou aprovação da release.

O resultado histórico integral continua sendo 28 falhas; não foi reescrito
após os replays. As outras 25 falhas já registradas permanecem fora desta entrega.

Pareceres independentes: revisão ampla `ship`, confiança média, sem achados
bloqueantes (`deleg_4a2b5174`); correção do checkbox nativo `ship`, confiança alta,
sem achados (`deleg_9aa7d503`). O último ajuste, da limpeza de controles sem
Bootstrap Tab, também recebeu `ship`, confiança alta, sem achados, sobre os hashes
da fonte final (`deleg_9328f9b7`). O escopo de implementação e verificação das abas
está concluído; não há aprovação de release geral. Servidores QA e as bases
temporárias das suítes cancelada e
concluída foram encerrados/removidos, com leitura de volta em `cleanup.json`.
