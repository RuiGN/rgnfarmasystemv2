"""Instruções passo-a-passo para o manual do ERP RGN Farma System.

Cada entrada descreve como realizar operações comuns no sistema,
organizadas por módulo. Estas instruções complementam o manual_catalog.py.
"""

STEP_BY_STEP_GUIDES = {
    'formulations': """
## Como criar uma fórmula mestra

1. Acesse **Fórmulas e roteiros > Fórmulas mestras > Novo registro**.
2. O formulário usa duas abas: **Fórmula mestra** e **Componentes**.
   Na primeira, selecione o produto já cadastrado, informe versão, status, tamanho
   do lote, unidade, rendimento e vigência conforme os campos disponíveis.
   O código automático usa CODE_PREFIX-ID, com o ID real, sem preenchimento com zeros.
3. Na aba **Componentes**, adicione material, quantidade, unidade, função, perda
   prevista e conversão. Os filtros dependentes limitam as opções conforme o
   contexto; as validações do servidor continuam obrigatórias.
4. Um material ou categoria criado no cadastro relacionado é salvo separadamente:
   essa ação não salva a fórmula nem os componentes pendentes. Selecione o cadastro
   criado e depois salve o formulário principal.
5. Clique em **Salvar** para gravar a fórmula e seus componentes juntos.
   Erros preservam os valores e abrem a aba correspondente. Sem JavaScript,
   as seções ficam em sequência.
6. Escolha a versão explicitamente; versões anteriores e aprovadas são preservadas.
   Não selecione automaticamente a última versão nem sobrescreva uma aprovada.
   Use o fluxo de reaproveitamento/nova versão quando necessário.
7. A árvore/BOM permite consultar a composição respeitando as permissões.

## Como criar um roteiro de fabricação

1. No menu lateral, clique em **Fórmulas e roteiros**.
2. Clique no recurso **Roteiros**.
3. Clique em **Novo registro**.
4. Preencha:
   - **Código**: identificador do roteiro.
   - **Versão**: versão.
   - **Produto**: produto ao qual o roteiro se aplica.
   - **Fórmula**: fórmula mestra vinculada.
   - **Status**: defina como rascunho ou aprovado.
   - **Vigência**: datas de início e fim.
5. Clique em **Salvar**.
6. Para adicionar etapas do roteiro, use o recurso **Etapas de roteiro**:
   - Informe sequência, descrição da operação, tempo setup, tempo processo e
     área.
""",
    'production': """
## Como criar uma ordem de produção

1. No menu lateral, clique em **Produção**.
2. Clique no recurso **Ordens de produção**.
3. Clique em **Novo registro**.
4. Preencha os campos:
   - **Número**: gerado automaticamente (OP-XXX).
   - **Produto**: produto a ser fabricado.
   - **Fórmula**: fórmula mestra do produto.
   - **Roteiro**: roteiro de fabricação.
   - **Quantidade planejada**: quantidade a produzir.
   - **Unidade**: unidade de medida.
   - **Data prevista de início** e **fim**.
5. Clique em **Salvar**.
6. A ordem passa por transições de status:
   - **Rascunho** → **Aprovada** (ação: Aprovar)
   - **Aprovada** → **Liberada** (ação: Liberar)
   - **Liberada** → **Em andamento** (ação: Iniciar)
   - **Em andamento** → **Pausada** ou **Concluída**
   - Qualquer status ativo → **Cancelada** (com justificativa)
7. Para registrar consumo de matéria-prima, use **Consumo de materiais** no detalhe da ordem.
8. Para registrar resultados de produção, use **Resultados de produção**.
9. Os **Mapas de controle** e **Mapa de resultados** estão disponíveis no detalhe da ordem.

## Como registrar consumo de matéria-prima

1. Abra a ordem de produção no detalhe.
2. Na seção **Consumo de materiais**, clique em adicionar.
3. Selecione o componente da fórmula, a quantidade real consumida e o lote de estoque.
4. Salve. O sistema atualiza o saldo de estoque automaticamente.

## Como receber resultados de produção

1. Abra a ordem de produção no detalhe.
2. Na seção **Resultados de produção**, registre a quantidade produzida, lote gerado e qualidade.
3. Use a ação **Receber resultados** para transformar resultados pendentes em recebidos.
4. O sistema cria automaticamente o movimento de entrada de estoque.
""",
    'crm': """
## Como criar um pedido de venda

1. No menu lateral, clique em **CRM**.
2. Clique no recurso **Pedidos de venda**.
3. Clique em **Novo registro**.
4. Preencha:
   - **Cliente**: selecione o cliente cadastrado.
   - **Representante** (opcional): vendedor responsável.
   - **Data de entrega solicitada**: prazo desejado.
   - **Condição de pagamento**: condições comerciais.
5. Clique em **Salvar** para criar o cabeçalho.
6. Na seção **Itens do pedido** (inline), adicione produtos:
   - **Produto**: selecione do catálogo.
   - **Quantidade** e **Unidade**.
   - **Preço unitário** e **Desconto (%)**.
7. Salve. O sistema calcula o valor total automaticamente.
8. O pedido pode ser **Aprovado**, **Atendido** ou **Cancelado**.

## Como criar uma oportunidade (CRM Kanban)

1. No menu lateral, clique em **CRM**.
2. Clique no recurso **Oportunidades**.
3. Clique em **Novo registro**.
4. Preencha: cliente, título, valor estimado, data prevista de fechamento e estágio.
5. Os estágios são: Lead → Qualificada → Proposta → Negociação → Ganha/Perdida.
6. Use a visão Kanban para arrastar oportunidades entre estágios.
""",
    'finance': """
## Como registrar um título a pagar

1. No menu lateral, clique em **Financeiro**.
2. Clique no recurso **Títulos**.
3. Clique em **Novo registro**.
4. Selecione tipo: **Conta a pagar**.
5. Preencha: parceiro (fornecedor), valor original, data de vencimento, categoria financeira.
6. Salve. O título fica como **Pendente**.
7. Para baixar (pagar), use a ação de baixa no detalhe do título: informe conta financeira, data e valor.
8. O sistema atualiza o saldo da conta e gera o fluxo de caixa.

## Como registrar um título a receber

1. Siga os mesmos passos acima, mas selecione tipo: **Conta a receber**.
2. O parceiro deve ser um cliente.
3. Para baixar (receber), use a ação de baixa no detalhe.

## Como criar uma conta financeira

1. No recurso **Contas financeiras**, clique em **Novo registro**.
2. Preencha: código, nome, tipo (Caixa ou Banco), saldo inicial.
3. Para bancos: informe nome do banco, agência e número da conta.
""",
    'inventory': """
## Como consultar o saldo de estoque

1. Acesse **Estoque > Saldos**. A lista de **Saldos** apresenta produto, lote, almoxarifado,
   localização, status de qualidade, quantidade, quantidade reservada,
   quantidade disponível e unidade. Use a busca por produto, lote, nome do
   almoxarifado ou código da localização para localizar a posição.
2. A quantidade disponível é a quantidade menos a reservada, limitada a zero.
   Disponibilidade numérica não significa liberação: a saída exige saldo aprovado,
   lote não vencido e quantidade disponível suficiente.
3. Para consultar a validade, abra **Lotes**: a lista mostra a validade e o status
   de qualidade do lote. A validade não é uma coluna da lista de Saldos.
4. Quantidades não são editadas diretamente no cadastro de Saldos. Correções
   exigem operações de domínio; as dimensões produto, lote, almoxarifado,
   localização e unidade de um saldo existente são imutáveis.

## Como consultar movimentos de estoque

1. Acesse **Estoque > Movimentos**. O histórico de **Movimentos** é somente leitura,
   sem cadastro genérico de entradas ou edição/exclusão de movimentos.
2. Entradas são registradas pelas operações de domínio dos módulos de origem,
   como lançamento de estoque de recebimentos de compra e recebimento de
   resultados de produção; não por um formulário manual de Movimento.
3. A ação de saída possui permissão própria e exige saldo aprovado, não vencido
   e quantidade suficiente. O chat não executa movimentações nem altera saldos.
""",
    'procurement': """
## Como criar um pedido de compra

1. No menu lateral, clique em **Compras**.
2. Clique no recurso **Pedidos de compra**.
3. Clique em **Novo registro**.
4. Preencha: fornecedor, data de emissão, condição de pagamento.
5. Na seção de itens, adicione produtos, quantidades e preços.
6. Salve. O pedido passa por: Rascunho → Aprovado → Enviado → Parcialmente recebido → Recebido.

## Como registrar recebimento de compra

1. Abra o pedido de compra no detalhe.
2. Use a ação de recebimento: informe quantidade recebida, lote, validade.
3. O sistema cria automaticamente a entrada de estoque e o título a pagar.
""",
    'masters': """
## Como cadastrar um produto

1. Acesse **Cadastros mestres > Produtos > Novo registro**.
2. O editor tem três abas: **Produto**, **Fórmula mestra** e **Componentes**.
   Em **Produto**, preencha descrição, tipo, unidade e demais campos aplicáveis.
   Os códigos automáticos seguem CODE_PREFIX-ID: prefixo do modelo e ID real,
   sem preenchimento com zeros. Códigos descritivos e identificadores oficiais
   existentes são preservados; não invente códigos nem IDs.
3. Em **Fórmula mestra**, faça uma seleção de versão explícita: sem fórmula,
   nova versão ou uma versão existente deste produto. Use **Carregar seleção**
   antes de editar/salvar. A versão carregada deve corresponder à seleção.
   Não é escolhida automaticamente a versão mais recente. Versões anteriores
   e aprovadas são preservadas; uma versão existente mantém seu número.
4. Em **Componentes**, edite os materiais da fórmula carregada. Os filtros
   dependentes respeitam produto, material, unidade e categoria conforme o
   contexto; o servidor valida relacionamentos e permissões.
5. Um material ou categoria criado no cadastro relacionado é salvo separadamente,
   sem salvar produto, fórmula ou componentes pendentes. Depois selecione o
   cadastro criado no componente e salve o formulário principal.
6. Clique em **Salvar** para gravar o conjunto autorizado. As abas não concedem
   novas permissões: consulta, criação e alteração continuam controladas pelo Django.

## Navegação e limites do assistente

O cabeçalho canônico é Aplicativos > Fluxo de trabalho. A sidebar **Central de
workflow** abre indicadores em /app/workspaces/workflow/; os recursos operacionais
ficam em /app/workflow/. Não confunda o painel de indicadores com os recursos.
O chat exige sessão autenticada e a permissão knowledge.view_ragchatsession.
Ele orienta com base no manual e não cria, altera, aprova ou apaga registros.
O chat não executa exclusão de produtos nem confirma operações concluídas:
solicitações de exclusão ou alteração exigem as telas e permissões apropriadas,
nunca uma mutação via chat.
Sem suporte no manual, deve informar a limitação, sem inventar procedimentos.

## Como cadastrar um parceiro (cliente/fornecedor)

1. No recurso **Parceiros**, clique em **Novo registro**.
2. Preencha: código, razão social, nome fantasia, CNPJ/CPF, tipo (cliente, fornecedor, etc.).
3. Informe endereço, contato e dados comerciais.
4. Salve.
""",
    'fiscal': """
## Como emitir uma nota fiscal

1. No menu lateral, clique em **Fiscal**.
2. Clique no recurso **Documentos fiscais**.
3. Clique em **Novo registro**.
4. Preencha: tipo (entrada/saída), operação (compra/venda/devolução), parceiro,
   número, série, data de emissão.
5. Na seção de itens, adicione: produto, CFOP, NCM, quantidade, valor, tributos.
6. Salve. O documento passa por: Rascunho → Em conferência → Conferida → Aprovada → Lançada.
7. Após aprovada, o sistema pode gerar o título financeiro automaticamente.

## Como consultar apuração de impostos

1. Use o recurso **Apurações tributárias**.
2. Clique em **Novo registro** para criar uma apuração de período.
3. Selecione o tributo (ICMS, PIS, COFINS, CBS, IBS) e o período.
4. O sistema calcula débitos, créditos e valor a recolher.
""",
    'quality': """
## Como preparar amostras e especificações

1. Acesse **Controle de qualidade**. Os recursos são **Especificações analíticas**,
   **Amostras de qualidade**, **Análises de qualidade**, **Resultados analíticos**,
   **Investigações laboratoriais** e **Documentos de qualidade**.
2. Em **Especificações analíticas > Novo registro**, informe produto, parâmetro,
   versão, método e critérios/limites aplicáveis. Salve; a ação **Aprovar** é separada.
3. Em **Amostras de qualidade > Novo registro**, informe tipo, produto, quantidade
   e, quando aplicável, lote, especificação, unidade e ponto de coleta. Lote e
   especificação devem pertencer ao produto da amostra.
4. Salve a amostra. As ações **Coletar**, **Receber**, **Iniciar análise** e
   **Revisar** respeitam o estado atual e as permissões; não são consequência
   automática de salvar. **Criar análise** vincula a nova análise à amostra
   e à sua especificação.

## Como registrar uma análise de qualidade

1. Acesse **Controle de qualidade > Análises de qualidade > Novo registro**.
   Selecione a amostra e, quando aplicável, a especificação do mesmo produto.
   Informe método executado, lote do reagente e lote do padrão conforme necessário.
2. Na seção **Resultados Analíticos (LIMS)**, use **Adicionar ensaio** para informar
   parâmetro, tipo e resultado numérico (quantitativo) ou resultado textual
   (qualitativo). Salve a análise com os resultados.
3. Os resultados também podem ser consultados/cadastrados em **Resultados analíticos**,
   vinculados à análise. Use a ação **Avaliar** no resultado para calcular seu
   status conforme tipo, valor e especificação; salvar não equivale a avaliar.
4. Na análise, o fluxo de ações é **Iniciar** (Pendente → Em execução),
   **Concluir** (Em execução → Concluída), **Revisar** (Concluída → Revisada) e
   **Aprovar** (Revisada → Aprovada), respeitando permissões e validações.
   **Rejeitar** exige motivo. Registrar ou avaliar um resultado não aprova automaticamente
   a análise nem substitui a decisão sobre a amostra ou a liberação de estoque.

## Como registrar investigações e documentos de qualidade

1. Em **Investigações laboratoriais > Novo registro**, vincule amostra e, quando
   aplicável, análise/resultado; informe tipo e justificativa. As ações de repetição,
   reteste e reamostragem exigem justificativa; **Concluir** registra causa raiz
   e conclusão, respeitando o fluxo autorizado.
2. Em **Documentos de qualidade > Novo registro**, informe tipo, vínculos aplicáveis,
   resumo e conclusão. Salvar o documento não equivale à ação **Emitir**.
   O chat apenas orienta: não registra resultados, aprova análises ou libera lotes.
""",
    'capa': """
## Como criar uma ação corretiva

1. No menu lateral, clique em **CAPA**.
2. Clique no recurso **Ações corretivas**.
3. Clique em **Novo registro**.
4. Preencha: título, descrição, responsável, prazo, origem (desvio, reclamo, auditoria).
5. O CAPA passa por: Aberta → Em andamento → Implementada → Verificada → Fechada.
""",
    'agenda': """
## Como criar uma tarefa

1. No menu lateral, clique em **Agenda**.
2. Clique no recurso **Tarefas**.
3. Clique em **Novo registro**.
4. Preencha: título, descrição, responsável, data de vencimento, prioridade.
5. A tarefa pode ser visualizada em calendário (visão Calendário).
""",
    'commissions': """
## Como cadastrar uma comissão

1. No menu lateral, clique em **Comissões**.
2. Clique no recurso **Avaliações de comissão**.
3. Clique em **Novo registro**.
4. Preencha: representante, competência (mês/ano), valor base, percentual.
5. Salve. A comissão pode ser aprovada e vinculada a um título a pagar.
""",
}


def get_step_by_step(module_slug):
    """Retorna as instruções passo-a-passo para um módulo, ou string vazia."""
    return STEP_BY_STEP_GUIDES.get(module_slug, '')
