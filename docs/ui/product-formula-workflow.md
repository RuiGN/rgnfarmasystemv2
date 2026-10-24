# Cadastro de produtos e de fórmulas mestras

Produto e fórmula mestra são cadastros distintos. O produto pertence a
**Cadastros mestres**; a fórmula e seus componentes pertencem a **Fórmulas e
roteiros**. A fórmula referencia o produto por chave estrangeira — esse vínculo
de negócio não torna o produto parte do módulo de formulação.

## Fluxo funcional

- **Cadastros mestres → Produtos → Novo/Editar** é o formulário genérico de
  recurso, com as abas de domínio declaradas em `base/ui/form_tab_groups.py`:
  **Geral**, **Classificação**, **Qualidade e conservação** e **Fiscal**. Ele não
  cria, carrega nem altera fórmulas.
- **Fórmulas e roteiros → Fórmulas mestras → Novo/Editar** oferece duas abas:
  **Fórmula mestra** (inclui o seletor do produto existente) e **Componentes**.
  Criação, edição e reaproveitamento usam o editor compartilhado de recursos.
- Versões são explícitas: nenhuma fórmula é escolhida por ser a mais recente,
  vigente ou aprovada. Nova versão não modifica, substitui nem apaga versões
  anteriores; use `app:master_formula_reuse` para partir de uma existente.
- **Salvar** grava a fórmula e seus componentes na mesma transação. Qualquer erro
  de validação, conflito de unicidade ou falha de persistência reverte a fórmula,
  as linhas e seus eventos de auditoria, mantendo os valores enviados e abrindo a
  aba correspondente.

## Cadastros relacionados na aba Componentes

No editor de Fórmulas, a aba Componentes permite:

1. **Cadastrar categoria de material**: nome, categoria superior e ativo; código
   automático e tipo fixo `MasterCategory.Kind.CATEGORY`, imposto pelo servidor,
   não pelo POST.
2. **Cadastrar material / componente**: somente descrição, tipo de item (inicial
   Matéria-prima), unidade e categoria. O novo `Product` usa os defaults reais do
   modelo nos demais campos, inclusive status Rascunho e exigência de liberação da
   qualidade. QA/fiscal e outras classificações permanecem editáveis no cadastro
   completo de Produto.

Essas ações são **salvamentos separados do formulário principal**, anunciados na
tela. Uma categoria/material criado permanece cadastrado mesmo que o usuário
depois cancele ou envie uma fórmula inválida. A fórmula e as linhas não são salvas
por essas ações; os valores atuais permanecem no formulário e os novos registros
ficam disponíveis nos seletores, sem substituir o material de uma linha já
preenchida.

O HTML contém um único formulário operacional, sem forms aninhados. Os prefixos
`components-`, `related-material-` e `related-category-` evitam colisões. Os
botões relacionados têm `formnovalidate`: os requisitos do cadastro que está
sendo salvo continuam validados no servidor.

## Arquitetura e controles

- `base/aggregate_writes.py`: protocolo de escrita compartilhado por
  `masters.Product`, `formulations.MasterFormula` e
  `formulations.FormulaComponent`. Vive em `base` porque o agregado cruza duas
  apps e nenhuma delas é dona da outra — `masters` não importa `formulations`.
- `masters/related_create.py`: construção e gravação dos cadastros relacionados
  (material e categoria), consumidos pelo editor genérico de Fórmulas.
- `base/ui/views.py`: persistência e auditoria genéricas; os hooks de cadastro
  relacionado são restritos ao recurso `formulations/formulas`.
- O gate `write_gate()` serializa a manutenção do agregado com
  `pg_advisory_xact_lock`; depois dele as linhas são travadas na ordem
  Product → MasterFormula → FormulaComponent, por chave primária. SQL cru,
  `queryset.update` e escritores ORM de terceiros não são cobertos.
- O campo oculto de identidade do componente é restrito ao queryset da fórmula
  editada. IDs de outras fórmulas são erros, não vínculos aceitos silenciosamente.
- Permissões continuam independentes: view/add/change de Product e MasterFormula;
  view/add/change/delete de FormulaComponent conforme a operação. Editar um
  produto não exige permissão de fórmula, e vice-versa.
- `GovernanceAuditLog` mantém usuário, ação, campos alterados e contagens dos
  inlines por meio do salvamento genérico, participando do rollback principal.
- Antes de concluir a gravação de uma fórmula aprovada, o salvamento HTML
  compartilhado revalida `FormulaComponent.clean()` de **todos os componentes
  persistidos** na mesma transação, inclusive linhas omitidas por um management
  form forjado ou não exibidas por falta de permissão. Uma inconsistência volta
  como erro geral, sem revelar o componente restrito, e reverte fórmula, linhas e
  auditoria. Não constitui constraint de banco nem proteção para SQL direto.

## Cobertura

- `tests/formula_editor_cases.py`: fixtures HTTP compartilhadas do editor de
  fórmulas (`case`, `existing_case`, `url`, `product_url`).
- `tests/test_formula_final_component_validation.py`: aprovação com componente
  persistido omitido, usuário sem visualização dos componentes, caso válido,
  reparo do material na mesma submissão e a prova de que o editor de Produto não
  alcança linhas de fórmula.
- `tests/test_formula_writer_protocol.py` e
  `tests/test_product_formula_writer_concurrency.py`: contrato do escritor
  compartilhado e as corridas entre API, admin e formulário HTML.
- `tests/test_resource_form_domain_tabs.py`: `masters/products` segue o contrato
  genérico de abas de domínio, sem exceção.
- `tests/js/resource-form-tabs.test.cjs`: `formnovalidate` não é bloqueado pelo
  listener de abas e Salvar continua recusando controles inválidos.

Testes locais, HTTP e capturas não constituem aprovação regulatória, de release
ou de CI.
