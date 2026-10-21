# Cadastro integrado de produtos, fórmulas e componentes

## Fluxo funcional

- **Cadastros mestres → Produtos → Novo/Editar** oferece três abas: **Produto**, **Fórmula mestra** e **Componentes**. Todos os campos cadastrais atuais do produto continuam disponíveis, inclusive taxonomia, QA e fiscal.
- **Fórmulas e roteiros → Fórmulas mestras** oferece duas abas: **Fórmula mestra** (inclui o seletor de produto existente) e **Componentes**. A aba redundante Produto foi removida; criação, edição e reaproveitamento continuam usando o editor compartilhado.
- Produtos inicia em **Somente produto — não alterar fórmulas**. Nenhuma fórmula é escolhida por ser a mais recente, vigente ou aprovada.
- Para cadastrar uma fórmula, escolha **Nova versão** e use **Carregar seleção**. Informe o número da nova versão e seus componentes. Para editar uma existente, selecione explicitamente o código/versão/status e carregue. Carregar substitui somente os campos da fórmula e seus componentes; os dados digitados do produto permanecem.
- **Salvar** grava produto, fórmula selecionada e componentes na mesma transação. Qualquer erro de validação, conflito de unicidade ou falha de persistência reverte as três entidades e seus eventos de auditoria. Em erro, o formulário mantém os valores enviados e indica a aba correspondente.
- Alterar o seletor sem carregar não redireciona a gravação para outra fórmula: o servidor recusa o salvamento e pede o carregamento explícito. O ID da versão deve pertencer ao produto editado. A identidade produto/versão de uma fórmula existente é preservada neste editor; criar outra versão exige a opção Nova versão.
- Nova versão não modifica, substitui nem apaga versões anteriores. Uma edição expressamente selecionada continua sujeita às regras e permissões existentes; o fluxo não cria uma nova política de aprovação ou uma proibição global de edição das fórmulas aprovadas.

## Cadastros relacionados na aba Componentes

Tanto no editor de Produtos como no de Fórmulas, a aba permite:

1. **Cadastrar categoria de material**: nome, categoria superior e ativo; código automático e tipo fixo `MasterCategory.Kind.CATEGORY`, imposto pelo servidor, não pelo POST.
2. **Cadastrar material / componente**: somente descrição, tipo de item (inicial Matéria-prima), unidade e categoria. O novo `Product` usa os defaults reais do modelo nos demais campos, inclusive status Rascunho e exigência de liberação da qualidade. QA/fiscal e outras classificações permanecem editáveis no cadastro completo Produto; não são eliminados nem aceitos por campos extras forjados do formulário rápido.

Essas ações são **salvamentos separados do formulário principal**, anunciados na tela. Uma categoria/material criado permanece cadastrado mesmo que posteriormente o usuário cancele ou envie uma fórmula inválida. O produto principal, fórmula e linhas não são salvos por essas ações. Os valores atuais permanecem no formulário; os novos registros ficam disponíveis nos seletores, sem substituir silenciosamente o material de uma linha já preenchida.

O HTML contém um único formulário operacional, sem forms aninhados. Prefixos `formula-`, `components-`, `related-material-` e `related-category-` evitam colisões. Os botões relacionados e de carregamento têm `formnovalidate`: os requisitos do cadastro que está sendo salvo continuam validados no servidor, sem exigir o preenchimento prévio do formulário principal.

## Arquitetura e controles

- `masters/ui_views.py`: subclasses especializadas dos editores existentes; composição de forms autorizados e do inline de fórmulas já registrado. Rotas específicas vêm antes das rotas genéricas, mantendo os URLs e links existentes.
- `masters/related_create.py`: construção e gravação dos cadastros relacionados, também reutilizada pelo editor genérico de Fórmulas.
- `base/ui/views.py`: persistência/auditoria originais reaproveitadas; hooks restritos ao recurso Fórmulas para ações relacionadas. Não altera bloqueios operacionais de produção.
- Na edição integrada, `Product` e a fórmula escolhida são relidos com `select_for_update()` antes de validar os forms; a ordem é produto → fórmula. O salvamento genérico permanece dentro de uma transação externa única. Unicidades de versão continuam protegidas pelo modelo/banco, sem `update_or_create` que sobrescreva históricos.
- O campo oculto de identidade do componente é restrito ao queryset da fórmula selecionada. IDs de outras fórmulas são erros, não vínculos aceitos silenciosamente.
- As permissões continuam independentes: view/add/change de Product e MasterFormula; view/add/change/delete de FormulaComponent conforme a operação e a retenção já existente. Gravar somente o produto não exige permissão de fórmula. Cadastro rápido exige view+add do próprio cadastro e acesso às fórmulas/componentes. CSRF usa o middleware e token existentes.
- O builder compartilhado de inlines chama `configure_related_fields()` depois de aplicar read-only/disabled/ator e `validate_related_fields()` no `clean()`. Isso reutiliza o filtro FK dependente também nas linhas, sem ampliar querysets e preservando DELETE. A integração tem testes puros sem permissão de banco em `tests/test_inline_related_hooks.py`.
- `GovernanceAuditLog` mantém usuário, ação, campos alterados e contagens dos inlines por meio do salvamento genérico. Auditoria participa do rollback principal; cadastros relacionados têm seus próprios eventos.
- `ModelForm`/`full_clean()` mantêm regras de lote, rendimento, vigência, disponibilidade de produto/material aprovado e taxonomia. Guardas de valores ausentes em `MasterFormula.clean`, `FormulaComponent.clean` e acesso à unidade em Product impedem HTTP 500 durante validação incompleta, sem relaxar as validações de valor/referência.
- Antes de concluir a gravação de uma fórmula aprovada, o salvamento HTML compartilhado revalida as regras de negócio (`FormulaComponent.clean()`) de **todos os componentes persistidos** na mesma transação, após salvar as linhas. Isso inclui linhas omitidas por um management form forjado ou não exibidas por falta de permissão. Materiais, unidades e categorias são carregados conjuntamente, sem consultas por linha nessa verificação. Uma inconsistência volta como erro geral, sem revelar o componente restrito, e reverte produto/fórmula/linhas/auditoria. O controle cobre Produtos e o cadastro independente de Fórmulas; não constitui constraint de banco nem proteção para SQL direto. A validação completa dos formulários submetidos permanece inalterada.
- Nenhuma migration, coluna, dependência, API, regra de aprovação ou cadastro operacional foi removido.

## Verificação local isolada

A especificação executável está em `tests/test_product_formula_workflow.py`; as assertions de layout explicitamente obsoletas estão atualizadas em `tests/test_resource_form_tabs.py`. O teste Node `tests/js/resource-form-tabs.test.cjs` verifica que `formnovalidate` não é bloqueado pelo listener de abas e que Salvar ainda recusa controles inválidos.

`tests/test_formula_final_component_validation.py` cobre a aprovação com componente persistido omitido, usuário sem visualização dos componentes, edição independente, caso válido e reparo do material na mesma submissão. A reprodução inicial aceitou indevidamente o POST (HTTP 302); após o reparo, o recorte de fórmula/produto/formulações passou com 48 testes. A última execução específica dos cinco cenários passou, incluindo o reparo legítimo. Os conjuntos se sobrepõem; não somar. Evidências `formula-final-child-{red,green,variants,repair}.xml` em `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/`.

Runner sintético externo ao repositório:

```sh
TMPDIR=/Users/rgnsystems/.hermes/cache/scratch \
PYTHONPATH=/Users/rgnsystems/.hermes/cache/scratch/release-test-bootstrap \
.venv/bin/python /Users/rgnsystems/.hermes/cache/scratch/run_product_workflow_tests.py \
 tests/test_product_formula_workflow.py tests/test_resource_form_tabs.py \
 --reuse-db -q \
 --basetemp=/Users/rgnsystems/.hermes/cache/scratch/pytest-product-workflow-validation \
 --junitxml=/Users/rgnsystems/.hermes/cache/scratch/artifacts/product-workflow-validation.xml

node --test tests/js/resource-form-tabs.test.cjs
```

O runner bloqueia dotenv antes de importar Django; banco exclusivo `test_cosmos_product_workflow_tests`, em `127.0.0.1:5433`, dados sintéticos. Não usar o banco do outro agente (`cosmos_tabs_tests`). Evidências RED/GREEN e readback do navegador ficam no scratch, não no repositório.

Testes locais, HTTP e capturas não constituem aprovação regulatória, de release ou de CI. O bloqueio de dependência certifi previamente informado não faz parte desta implementação. A subdivisão opcional dos campos de classificação/QA/fiscal da aba Produto em painéis colapsáveis permanece fora desta alteração: os campos continuam visíveis para não perder erros ou foco.

## Reconfirmação do pedido no código local

Criação e edição de Produtos usam as três abas descritas; Fórmulas mestras não
oferece uma aba Produto separada. O seletor obrigatório do produto permanece
dentro de Fórmula mestra, pois é um vínculo de negócio, não um cadastro duplicado.
O cadastro rápido de material e categoria permanece em Componentes nos dois
editores, com os formulários compartilhados e sem navegar para outra página.

A reconfirmação executou **154 testes Python aprovados**, incluindo criação,
edição, versões, cadastro relacionado, permissões, CSRF, rollback e simplificação.
Todos os **59 templates HTML atuais** compilaram e receberam um inventário
estático novo; o snapshot inicial de 58 templates não foi sobrescrito. Os **oito
testes Node** de abas e selects dependentes também passaram, assim como
`git diff --check`. Os recortes não são somados à suíte global anterior.

Uma primeira tentativa excedeu 300 segundos sem gerar JUnit; foi preservada
como tentativa incompleta. A repetição, sem modificar a implementação, concluiu
os 154 testes. As verificações usaram apenas o banco sintético exclusivo de
workflow, com dotenv operacional bloqueado. Essa confirmação não publicou
alterações. A revisão temporal posterior e a ressalva do popup nativo em
320 px estão descritas em `../validation/local-finalization.md`; o pedido
de aceite está em `../validation/approval-request.md`. A cobertura completa
da matriz não equivale a aprovação visual irrestrita.
