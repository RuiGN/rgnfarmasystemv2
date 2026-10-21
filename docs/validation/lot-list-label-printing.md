# Correção da impressão de etiquetas na listagem de lotes

## Escopo entregue

Em **Estoque → Lotes**, cada registro autorizado apresenta **Etiqueta** na coluna
**Ações**. A disponibilidade é calculada na listagem apenas para `StockLot` e
usuários com `inventory.view_stocklot`. Não foram criadas permissões, menus,
migrations, impressão em massa ou impressão a partir de fórmulas mestras.

Cada linha contém um formulário próprio com CSRF. O controlador compartilhado
registra todos os botões, encontra o formulário da linha selecionada e usa sua
URL e token. Preserva confirmação explícita, bloqueio do botão durante o envio,
feedback com `textContent` e ausência de reenvio automático. O detalhe do lote e
o cockpit de liberação continuam consumindo o mesmo controlador.

As alterações locais anteriores de integridade P1 e abas foram preservadas.
`base/ui/views.py` é compartilhado com essa entrega anterior; seus manifestos
registram snapshots históricos e não foram reescritos para ocultar a nova mudança.
Não houve commit, push ou deploy.

## Testes observados

- **RED HTTP:** o novo teste encontrou zero formulários de impressão em duas
  linhas autorizadas, em vez dos dois esperados (`list-red.xml`).
- **RED JavaScript:** o controlador anterior falhou ao acionar a segunda linha:
  sete cenários falharam por ausência de listener; três passaram.
- **Seleção final: 71 testes pytest aprovados**, sem falhas ou skips. Inclui
  impressão direta, CSRF, permissões, ausência da ação em outros recursos,
  cockpit de liberação, fórmulas, descoberta de ações e retenção de saldos.
- Dentro dessa seleção, um teste pytest executa **10 cenários Node.js**, todos
  aprovados. Essas contagens se sobrepõem e não devem ser somadas.
- Ruff, verificação de formatação dos testes, MyPy de `base/ui/views.py`, sintaxe
  JavaScript e `git diff --check`: aprovados.

### Checagem adicional da listagem genérica

O recorte de `tests/test_app_ui.py` com `-k 'resource_list and not all_modules'`
registrou **5 aprovados e 3 falhas**. Os três IDs já constam no XML integral da
entrega anterior (`resource-form-tabs/full-suite-junit.xml.gz`):

1. `test_resource_list_boolean_values_are_displayed_in_portuguese`;
2. `test_read_only_resource_lists_have_clear_state_and_accessible_tables`;
3. `test_resource_list_uses_design_system_table_and_filter_components`.

São expectativas antigas de marcação HTML da listagem; não foram alteradas nem
incluídas silenciosamente nesta correção. A suíte global não foi reexecutada e
não há aprovação geral de release.

## Chromium: nove verificações aprovadas

A inspeção usou HTML realmente renderizado pelo Django com dois lotes sintéticos,
e o arquivo real `static/js/local-printing.js`. Os registros e a sessão de QA
foram criados em transação na base PostgreSQL sintética de loopback e revertidos
antes da inspeção. O servidor temporário serviu apenas as capturas HTML e assets
públicos; foi encerrado e a porta 8766 foi conferida fechada.

**O transporte `fetch` e a confirmação foram instrumentados nas capturas de QA.**
As respostas de sucesso/erro eram explicitamente simuladas e nenhuma chamada
alcançou a API operacional, VPN ou impressora. Separadamente, o teste HTTP
exerceu a API Django real com autenticação de sessão e CSRF, substituindo apenas
o serviço de envio físico.

Verificações em `evidence/lot-list-label-printing/browser-checks.json`:

- dois botões com formulário próprio, nome acessível e feedback `aria-live`;
- cancelamento sem envio;
- desabilitação somente do botão selecionado;
- segunda linha com URL correta, CSRF e sem duplicidade em clique repetido;
- erro HTTP com feedback e sem reenvio;
- falha de rede simulada com botão reabilitado, sem reenvio ou erro JS não tratado;
- compatibilidade do botão único no detalhe;
- renderização em 1440 px e em 320 px, com rolagem horizontal da tabela e sem
  overflow horizontal do documento.

A primeira observação com espera fixa foi inconclusiva porque o navegador ainda
aguardava o timer da simulação. O recorte final foi repetido com a aba ativa e
espera limitada pelo estado do botão; não houve alteração de produção para isso.

## Rechecagem da superfície servida

Após solicitação explícita do gate visual, a captura renderizada foi novamente
servida em loopback e aberta no Chromium em **1440 × 1000** e **320 × 1000**.
O texto **Etiqueta** ficou integralmente visível nos dois botões após rolar a
tabela até as ações; cada controle mediu aproximadamente 105 px de largura.
Em mobile, os filtros empilham e o cabeçalho quebra linhas. A rolagem horizontal
fica contida na tabela: o documento mediu 315 px no viewport de 320 px.

O cancelamento da segunda linha gerou zero solicitações. A confirmação produziu
uma única solicitação simulada para a URL da segunda linha, com CSRF, desabilitou
somente seu botão durante a espera e o reabilitou após a resposta, sem erros JS
não tratados. As **quatro rechecagens** estão em `served-surface-checks.json`;
são reafirmações de cenários anteriores, não novos casos para somar aos nove.
Capturas: `served-1440.png` e `served-320.png`. O transporte continuou
explicitamente simulado, sem impressão física.

## Reprodução

```bash
./scripts/test.sh tests/test_direct_label_printing.py tests/test_local_printing_js.py \
  tests/test_lot_release_cockpit_ui.py tests/test_formula_inline_components_ui.py \
  tests/test_action_discovery.py tests/test_p1_stock_balance_retention.py -q
node --test tests/js/local-printing.test.cjs
```

Nesta execução foi usado um wrapper externo com dotenv desabilitado e PostgreSQL
sintético isolado. A execução Node.js ocorreu de fato; em ambientes sem Node.js,
o teste correspondente informa skip explicitamente.

## Revisão independente e fechamento

A revisão somente leitura `deleg_725be29a` foi concluída sem achados concretos
no delta de impressão. Foram inspecionados disponibilidade por modelo/permissão,
CSRF por linha, associação de todos os botões, confirmação, bloqueio durante o
envio, ausência de reenvio automático e compatibilidade estrutural do detalhe e
cockpit. O retorno textual está resumido em `evidence/lot-list-label-printing/review.json`;
não foi convertido em um parecer formal `ship` que o revisor não emitiu.

O revisor não executou testes, navegador, banco ou impressão; as verificações
de execução descritas acima pertencem ao executor. A correção local e sua revisão
estão concluídas, sem aprovação geral de release. Permanecem somente os limites
de aceite físico e as falhas genéricas preexistentes já documentadas.

## Limites operacionais

O aceite com equipamento físico permanece pendente conforme
[direct-label-printing-acceptance.md](direct-label-printing-acceptance.md).
É necessária uma impressora ativa e alcançável pelo servidor através da VPN.
O sucesso do envio ao socket **não confirma a saída física** da etiqueta.
Não houve envio físico nesta verificação.
