# Reinicialização seletiva do ambiente de treinamento

## Alcance

O comando `reset_training_data` apaga o negócio antigo e recarrega os catálogos de referência da instalação single-instance. Não é um procedimento de produção nem uma rotina de inicialização. Exige a autorização para a operação destrutiva descrita no [desenho aprovado](../superpowers/specs/2026-10-21-id-code-navigation-training-reset-design.md).

O manifesto versionado em `governance/training_reset_manifest.json` classifica cada tabela física, incluindo M2Ms e tabelas do framework. Neste manifesto há 223 tabelas: 9 preservadas e 214 limpas, das quais 27 recebem catálogos novamente. Uma tabela ausente, uma tabela adicional, um schema de aplicação diferente de `public` ou uma FK de tabela preservada para tabela limpa impedem a operação. A lista não se expande automaticamente quando novos models são adicionados.

As tabelas preservadas contêm usuários, grupos, permissões, vínculos M2M, contenttypes, migrations e `IdentifierSequence`. As identidades são comparadas integralmente em SQL antes do commit; valores sensíveis não são retornados ao processo. Os namespaces existentes de `IdentifierSequence` devem continuar presentes e seus valores não podem diminuir. O resultado `preserved_equal=true` representa essas duas verificações, não uma exportação nem um hash de senhas.

As demais tabelas do manifesto são truncadas juntas com `CONTINUE IDENTITY RESTRICT`, sem `CASCADE`. Os IDs não voltam a 1. Avanços de sequências PostgreSQL, inclusive em tentativas revertidas, podem deixar lacunas.

Metadados, regras de acesso e links dos anexos antigos são removidos. O comando não acessa nem exclui os respectivos arquivos físicos. Os blobs conservados não voltam a aparecer nas telas e não devem ser associados a novos registros por semelhança de ID.

## Inspeção e execução

A inspeção é o comportamento padrão e não exige habilitar o reset:

```bash
python manage.py reset_training_data
```

A saída JSON informa o banco conectado, o hash do manifesto e os conjuntos de tabelas. Ela não atesta que um backup existe. O alias suportado é `default`, em PostgreSQL; os loaders reutilizados são single-database.

A execução exige `--execute`, opt-in na configuração do processo, o nome exato do banco conectado e o SHA-256 do recibo de backup previamente validado pelo operador:

```bash
TRAINING_RESET_ENABLED=True python manage.py reset_training_data \
  --execute \
  --expected-database NOME_VALIDADO \
  --backup-receipt-sha256 SHA256_DO_RECIBO_VALIDADO
```

Os valores em maiúsculas são marcadores, não argumentos prontos para uso. A flag é desabilitada por padrão e deve ser ativada somente no processo descartável de manutenção, sem deixá-la habilitada no ambiente habitual. O comando recusa transações externas e cria sua própria transação. O recibo é apenas uma referência: aceitar uma string SHA-256 válida não demonstra a existência, a integridade ou a restauração do backup.

O advisory lock impede dois resets cooperantes. Os locks de todas as tabelas usam `NOWAIT`, com `lock_timeout` de 5 segundos e `statement_timeout` de 120 segundos por instrução. Isso não substitui parar escritores e consumidores. Falha de carga, alteração de identidade preservada, redução de contador, catálogo obrigatório vazio ou criação de dados fora dos catálogos causam rollback relacional. Os arquivos físicos ficam fora dessa transação.

## Conteúdo recarregado

O comando chama `seed_production_reference_data()` e `sync_curated_report_catalog(ReportDefinition)`. São usados somente snapshots e catálogos versionados, sem consultas externas na janela:

- 193 países, 27 UFs, 5571 municípios e 178 moedas;
- áreas, processos, departamentos, papéis, prioridades, criticidades e metadados de módulos/models;
- unidades e categorias, elementos de custo, grupos e canais comerciais;
- contas e categorias financeiras, cargos, funções e competências;
- unidades fiscais e CFOPs selecionados;
- 15 relatórios curados.

Códigos oficiais e descritivos permanecem literais. O padrão `CODE_PREFIX-ID` vale para códigos gerados automaticamente, não para renomear esses códigos de carga. Configurações específicas da empresa, pareceres e regras fiscais, formulações aprovadas, políticas e especificações de qualidade não são inferidos. Não são criados produtos, lotes, ordens de produção, movimentações, títulos, notas ou integrações ativas. Não se usa `full_demo`.

## Janela operacional obrigatória

1. Validar o SHA exato e sua CI; construir a imagem fixada e conferir os overrides efetivos por metadados seguros. Não copiar caminhos ou configurações de outro ambiente.
2. Suspender entradas HTTP e todos os escritores, incluindo app, workers, beat e agendador de backup. Conferir tarefas em curso e filas de propriedade desta instalação, sem apagar caches ou filas de outros projetos.
3. Criar um backup novo de banco e mídia, guardar a imagem anterior e conferir os arquivos com acesso restrito. O backup desta operação deve ser posterior à suspensão dos escritores.
4. Restaurar o banco em PostgreSQL descartável isolado, sem publicar portas e sem restaurar sobre o banco operacional. Conferir agregados e preservação de acessos com saídas numéricas/booleanas. Sem prova de restore, não executar o reset.
5. Inspecionar o manifesto no banco alvo e executar o comando uma única vez com o recibo conferido. Reler o resultado por uma conexão independente e validar os catálogos por modelo, sem somar contadores sobrepostos.
6. Após o commit relacional, reconstruir o corpus/índice RAG e avaliar o chat no modo realmente configurado. Essa etapa não pertence à transação de reset e não treina pesos do modelo.
7. Reabrir a aplicação e retomar consumidores somente depois dos gates aplicáveis. Manter o override aprovado, os volumes e os backups.

Antes do reset, uma falha permite retomar a versão anterior com os dados intactos. Depois do commit destrutivo, trocar apenas a imagem não recupera o negócio apagado. Uma falha posterior exige manter a manutenção e aplicar o plano explícito de recuperação de dados ou corrigir o estágio seguro pendente.

## Verificação e limites

`tests/test_training_reset.py` exercita inspeção, opt-in, alvo, recibo, manifesto, schemas/tabelas/FKs desconhecidos, preservação de acessos/contadores, anexos físicos, concorrência e rollback em PostgreSQL sintético. Os testes de referências e auxiliares conferem os loaders e sua repetição. Resultados locais não provam execução na VPS, restore operacional, offsite, disponibilidade de arquivos antigos na UI ou aceite industrial/regulatório. A impressão física continua dependente do equipamento na indústria.
