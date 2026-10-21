# Relações 1-N no template operacional

## Contrato

O CRUD operacional usa `InlineResourceConfig` para declarar recursos filhos no
mesmo formulário do recurso pai. A declaração informa chave estável, model
filho, campo de vínculo, campos editáveis, textos de interface e quantidade
inicial de formulários.

O helper genérico constrói os formsets com prefixos independentes e aplica os
widgets e metadados do design system. O template `app/resource_form.html` é
compartilhado por todos os módulos; não existem templates específicos por
relação.

## Integridade e permissões

- Pai e filhos são persistidos dentro de uma única `transaction.atomic()`.
- Todos os formulários são validados antes da escrita.
- Uma falha ao salvar qualquer filho reverte o pai e os demais filhos.
- Inclusão, alteração e exclusão exigem, respectivamente, as permissões Django
  `add`, `change` e `delete` do model filho.
- Recursos GxP não oferecem exclusão física no CRUD genérico; devem usar
  arquivamento, cancelamento, obsolescência ou expurgo controlado do domínio.
- Criações e alterações da UI geram `GovernanceAuditLog` com ator, alvo,
  campos alterados e contagem de mudanças nos filhos, na mesma transação.
- Campos de decisão, confirmação, conclusão e eficácia não são editáveis nos
  inlines regulados; essas transições usam os métodos e endpoints do domínio.
- Formsets de relações `OneToOneField`, como a avaliação de impacto do desvio,
  respeitam a cardinalidade máxima definida pelo Django.

## Cobertura prioritária

| Recurso pai | Recursos filhos no formulário |
| --- | --- |
| Fórmula mestre | componentes |
| Ordem de produção | consumos de material |
| Pedido de compra | itens |
| Recebimento de compra | itens |
| Documento controlado | anexos, aprovações e distribuições |
| Desvio | investigações, impacto, aprovações e evidências |
| CAPA | ações, evidências, aprovações e verificações de eficácia |
| Plano de auditoria | checklist, achados e evidências |
| Achado de auditoria | ações de acompanhamento |
| Risco | avaliações, controles, mitigações, revisões e alertas |
| Dossiê regulatório | registros, petições, exigências, evidências e compromissos |
| Reclamação de cosmetovigilância | triagem, investigação, comunicação, ações e relatos |
| Campanha de recall | clientes impactados, comunicações e relatório de efetividade |

As ações de auditoria ficam no formulário do achado porque o vínculo de domínio
é `AuditFollowUpAction.finding`; o plano continua acessível pela relação do
achado, sem duplicação de chave estrangeira.

## Edição por abas

`base.ui.form_layouts.build_resource_form_layout` agrupa os `BoundField` e os
formsets já autorizados, sem recriar campos nem consultar permissões. Recursos
genéricos com filhos recebem **Informações gerais** e uma aba por inline.
Fórmulas usam **Produto / Fórmula mestra / Componentes**. Recursos simples
continuam no formulário sem abas; cockpits e fluxos especializados não são
convertidos implicitamente. A cobertura atual está em
[validação das abas](../validation/resource-form-tabs.md).

As abas seguem o cabeçalho e o alinhamento de campos de
`design_system/customers-create.html`. Há um único POST, com CSRF, identificadores,
prefixos e management forms preservados. Os componentes de fórmulas usam cartões
`stacked`; renderizadores tabulares e o editor específico de resultados de QC
continuam disponíveis para os demais recursos.

Erros selecionam a seção correspondente e exibem o texto **Erro** na aba. Um
formset válido com `errors == [{}]` não recebe badge. O controlador revela e
foca campos inválidos em painéis inativos antes de permitir o envio, sem acionar
o overlay de processamento em uma submissão rejeitada.

Excluir um filho mantém `id`, vínculo, `DELETE` e índices; somente os controles
visíveis descartados são desabilitados. Uma linha nova marcada para exclusão
não executa a validação de model que exige valores inexistentes: ela não será
persistida. A autorização de exclusão do formset continua sendo aplicada; o
tratamento não se aplica a linhas persistidas nem dispensa validações dos
filhos mantidos.

A desabilitação dos controles descartados pertence ao listener compartilhado
de exclusão em `resource_form.html`, não ao controlador Bootstrap de abas.
Assim, um campo inválido da linha removida não bloqueia a validação HTML se
Bootstrap Tab estiver indisponível. O listener ignora `DELETE` desabilitado e
preserva identificadores e vínculos ocultos.

Sem JavaScript ou Bootstrap, o cabeçalho de abas fica oculto e todos os painéis
ficam visíveis, com validação HTML nativa. O checkbox rotulado **Remover** permanece
visível até registrar o listener de exclusão; só então `data-inline-ready` troca
o checkbox pelo botão de exclusão. Isso também preserva o comportamento nativo
dos consumidores do partial sem esse listener. A inclusão dinâmica e a ocultação
imediata da linha exigem JavaScript; sem ele, marcar Remover e salvar exclui o
filho autorizado. O CSS de abas é escopado a `.resource-form-tabs`, e o da
exclusão progressiva a atributos próprios de `.resource-inline-formset`.
No celular, os cartões usam uma coluna para que os
gaps da grade de doze colunas não ultrapassem a largura disponível.

## Verificação

O arquivo `tests/test_formula_inline_components_ui.py` valida o inventário do
PRD, renderização e carregamento dos filhos existentes, criação, edição,
exclusão permitida, retenção GxP, rollback transacional e permissões.

`tests/test_resource_form_tabs.py` cobre agrupamento, erros, os recursos
genéricos aplicáveis, criação/edição/reaproveitamento de fórmula e descarte de
linha nova vazia. A inspeção real de teclado, foco, gravação e responsividade
é registrada separadamente em `docs/validation/resource-form-tabs.md`.
