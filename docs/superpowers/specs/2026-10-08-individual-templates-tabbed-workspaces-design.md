# Templates individuais e páginas centrais com abas

**Status:** proposta para revisão de Rui. Código funcional ainda não alterado.

## 1. Intenção e entrega

Rui autorizou iniciar a evolução dos templates individuais e pediu centralizar as funcionalidades cujos itens são cadastrados separadamente, usando abas do `design_system/`.

Interpretação proposta: haverá um template central por funcionalidade composta, não uma página única com todos os recursos do ERP. Listagens continuam como entrada. Consulta, criação e edição do agregado reutilizam a estrutura central, com componentes compartilhados. O usuário deve consultar o contexto, adicionar/alterar itens permitidos e corrigir erros sem abrir o CRUD de cada filho.

A entrega é código local no repositório, documentação e evidências de testes isolados. Não inclui deploy, reinício de produção ou mutação de dados reais. Aprovações, emissões, movimentações e transições controladas continuam usando os executores existentes.

## 2. Contexto confirmado

- Django Templates e descoberta por app: `core/settings/base.py:125-139`.
- Registro com 29 módulos e 200 recursos; 12 pais já declaram 31 conjuntos de inlines.
- Views de listagem, detalhe e formulário usam nomes genéricos fixos; `ResourceConfig` não declara seleção de templates.
- Criação/edição já validam formsets e salvam pai/filhos em transação. Produção tem locks e proteções adicionais que não podem ser removidos.
- Shell compartilhado: `templates/base.html`.
- Referência de abas: `design_system/refs/duralux/index.html:1173-1209`, com `nav-tabs`, `data-bs-toggle="tab"`, `tab-content` e `tab-pane`.
- Exemplo operacional: `templates/app/resource_execution_board.html:59-108`.
- Formsets dependem de management forms, prefixos, hidden fields e `data-inline-formset-*`.
- Máscaras são inicializadas em `DOMContentLoaded`; campos inseridos posteriormente precisam de inicialização explícita.
- Há alterações locais preexistentes de Rui que não pertencem a esta tarefa.

## 3. Alternativas

1. Apenas colocar abas no formulário genérico: menor mudança, mas não integra os fluxos que ainda têm filhos separados. Insuficiente.
2. **Recomendado:** páginas centrais especializáveis, com abas, seletor de templates e contratos compartilhados. Reutiliza Django, forms e APIs.
3. Reescrever como SPA ou duplicar um CRUD por módulo: escopo desnecessário e duplicação de validação/autorização. Excluído.

## 4. Escopo fechado do primeiro ciclo

O ciclo abrange os 22 fluxos abaixo. Não será apresentado como centralização de todo relacionamento existente no ERP.

### 4.1. Os 12 fluxos com inlines existentes

| Fluxo | Grupos |
| --- | --- |
| `formulations/formulas` | Componentes |
| `production/orders` | Matérias-primas, produtos acabados, processos, colaboradores |
| `procurement/orders` | Itens do pedido de compra |
| `procurement/receipts` | Itens do recebimento |
| `quality/analyses` | Resultados analíticos |
| `documents/controlled-documents` | Anexos, responsáveis por aprovação, distribuições |
| `deviations/events` | Investigações, impacto, responsáveis por aprovação, evidências |
| `capa/records` | Ações, evidências, responsáveis por aprovação, planejamento de eficácia |
| `audits/plans` | Checklist, achados, evidências |
| `audits/findings` | Ações de acompanhamento |
| `risks/records` | Avaliações, controles, ações, revisões, alertas permitidos |
| `recalls/campaigns` | Clientes impactados, comunicações, relatórios permitidos |

### 4.2. Os 10 fluxos adicionais atualmente separados

| Fluxo | Composição a integrar |
| --- | --- |
| `formulations/routes` | Etapas |
| `planning/schedules` | Linhas MPS |
| `procurement/requisitions` | Itens de requisição |
| `procurement/rfqs` | Cotações de fornecedores da RFQ |
| `fiscal/documents` | Itens e impostos |
| `crm/proposals` | Itens da proposta |
| `crm/orders` | Itens do pedido de venda |
| `qa/reviews` | Checklist de batch record |
| `changes/controls` | Itens afetados, avaliações, ações, responsáveis por aprovação, avaliações de estoque |
| `reports/dashboards` | Widgets |

Os grupos novos terão listas explícitas de campos de entrada. IDs automáticos, timestamps, atores do servidor, totais derivados e resultados de ações controladas não serão editáveis. Não inferir inlines a partir de qualquer ForeignKey: produto, unidade, cliente e outros cadastros de referência não são filhos editáveis do agregado.

Matrículas de treinamento, tarefas de filas de aprovação e outros agregados não listados ficam para etapa posterior, preservando seus próprios protocolos de estado e autorização. Não serão declarados concluídos neste ciclo.

## 5. Arquitetura

### Seleção e apresentação

Introduzir seletor com caminhos controlados no servidor e slugs validados no registro. Para telas comuns: template do recurso/tipo, template do módulo/tipo, genérico atual.

Os fluxos compostos usarão `app/<module>/<resource>/workspace.html` para consulta, criação e edição, com modo explícito. Esse template poderá estender `app/resource_workspace.html`. Listagens poderão ter `list.html` próprio. Recursos fora do escopo manterão fallback genérico.

Não aceitar caminho de template em parâmetros livres. O seletor não substitui autorização. `ResourceActionView`, que chama `render()` diretamente, terá integração própria para GET, POST inválido e retorno à página central, sem substituir o executor DRF.

Separar componentes para campos, abas, painéis, inlines, resumo de erros e ações. Abrir blocos internos nos genéricos para evitar cópias completas. O contexto será construído no servidor: modo, seções permitidas, URLs, aba ativa, edição e erros. Templates não consultarão modelos para ampliar escopo nem calcularão regras de negócio.

No detalhe, consultar filhos somente após permissão `view` e aplicar escopos específicos. Contadores serão derivados de registros reais autorizados, sem consultas por linha.

### Página central

- Cabeçalho com identificação, status e ações autorizadas.
- Aba “Dados gerais” e uma aba por grupo autorizado.
- Quantidade de registros persistidos e sinalização de erros por aba.
- Resumo/auditoria onde já suportados e autorizados.
- Barra de salvar/cancelar acessível sem entrar em outro CRUD.

Na consulta, grupos são somente leitura; “Editar” abre o modo de edição do mesmo template central. Na criação/edição, pai e formsets compatíveis compõem um formulário e um POST transacional. Ações operacionais usam comandos/formulários próprios na página central. Não haverá forms aninhados. Trocar abas não salva nem executa ações; botões de aba são `type="button"`.

### Erros e estado

- Preservar todos os valores no POST inválido e indicar abas com erros.
- Abrir a primeira seção inválida; erro do pai prioriza “Dados gerais”.
- Mostrar erros de campos, erros gerais do pai, do formset e de cada linha.
- Revelar a aba do campo inválido antes do foco da validação nativa.
- Sem erros, aceitar aba solicitada somente se válida e autorizada; valor adulterado volta a “Dados gerais”.
- Exclusão inline marca `DELETE`, sem retirar a linha do protocolo enviado.
- Inicializar novos campos e formulários de modal por função idempotente.

### Acessibilidade e layout

Usar Bootstrap/Duralux com roles de tablist/tab/tabpanel, IDs únicos, atributos ARIA, estado selecionado e teclado. Aplicar CSS de escopo próprio, não estilos exclusivos do mega-menu.

No celular, abas podem rolar horizontalmente sem aumentar a largura da página; tabelas usam contêiner responsivo. Sem JavaScript, todos os grupos permanecem visíveis e o POST funciona. Esconder painéis somente após confirmação do aprimoramento.

Texto e erros em pt-BR, sem ícones decorativos em inputs nem novas alegações de conformidade regulatória. Preservar scripts herdados com `block.super` quando necessários.

## 6. Persistência e segurança

- Reusar transação existente: erro de pai/filho impede persistência parcial dos dados de domínio.
- Validar permissões reais do pai e de cada filho no servidor, inclusive POST falsificado.
- IDs de filhos devem pertencer ao agregado acessível. Rejeitar reassociação e referências a outro pai.
- Preservar retenção GxP, campos controlados e locks de produção. Estados hoje proibidos continuam proibidos.
- Preservar rotas atuais de API/CRUD filho por compatibilidade; a página central será o caminho recomendado.
- Revalidar relações dentro da transação quando houver protocolo concorrente existente.

Associações entre filhos, como imposto → item fiscal ou evidência → ação, não aceitarão filho de outro pai. No primeiro ciclo, vincular um filho novo ainda não persistido exige duas gravações na mesma página: salvar os filhos, retornar ao template central e vincular o dependente. A UI deve explicar a dependência sem enviar para outro CRUD. Não criar IDs fictícios nem um protocolo novo de IDs temporários.

Criar documento fiscal não emite NF-e; salvar itens não baixa estoque; editar responsáveis não aprova documento/CAPA; editar linha não conclui ação operacional.

## 7. Verificação

Implementar em ciclos verticais RED → GREEN → REFACTOR.

1. Precedência/fallback do seletor, incluindo consistência de GET e POST inválido.
2. Matriz programática com os 22 fluxos: seleção e apresentação central.
3. Criação/edição reais de pai e filhos em PostgreSQL isolado, persistência, rollback, campos automáticos e associações incorretas.
4. Perfis sem permissão, adulteração de POST e acesso direto às rotas preservadas.
5. Regressões de fórmulas, compras, recebimentos, produção, fiscal, CRM e domínios GxP afetados.
6. Navegador: abas, foco/teclado, erros em aba inativa, adição/exclusão, máscaras, sem JavaScript e largura móvel.
7. Checks/lint nas versões declaradas, logs e exit codes em scratch, contagens reconciliadas por código.
8. Atualizar `TEMPLATES.md` e documentação de arquitetura com o alcance realmente entregue.

Usar fonte isolada sem `.env` real, PostgreSQL dedicado e integrações externas desativadas. Não testar em produção. Compilar templates não homologa fluxos. Imagem existente serve para diagnóstico; evidência de release exige verificar dependências do candidato atual.

## 8. Limites e handoff

Não reescrever APIs/regras de negócio, remover rotas, normalizar o restante do repositório, reverter correções de Rui ou fazer deploy. A reorganização visual não exige migrations por si; qualquer mudança de modelo requer necessidade demonstrada no escopo.

Antes de implementar, capturar baseline imutável das fontes e resultados relevantes fora do projeto. Revisar diffs contra esse baseline, não somente contra HEAD, porque há alterações preexistentes.

Rui deve revisar esta especificação antes de código funcional. Após aprovação, elaborar o plano com entregas, arquivos, infraestrutura, comandos de verificação e critérios por fluxo. A conclusão de uma etapa não será apresentada como conclusão das 22 funcionalidades.
