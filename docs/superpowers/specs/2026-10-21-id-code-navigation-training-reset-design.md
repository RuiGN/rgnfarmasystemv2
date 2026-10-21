# Códigos por ID, navegação simples e reinicialização da homologação

## Estado e base

Desenho e execução aprovados explicitamente pelo usuário via clarify em2026-10-21, incluindo implementação/testes/publicação/deploy, janela de manutenção, backup novo e ensaio isolado antes do reset seletivo. Base inspecionada: main `5707863d080d72719c20ccdfce4fc45d056879a7`. O pedido é desta rodada e se destina à VPS de treinamento/homologação, não à entrada em produção. As escolhas de escopo abaixo foram confirmadas pelo usuário. O builder check não encontrou perguntas importantes adicionais; os achados de descoberta e a decisão posterior sobre anexos foram incorporados pelo responsável. A aprovação do desenho não é revisão de código nem validação de execução.

A especificação histórica `2026-10-13-code-as-contextual-primary-key-design.md` propunha remover code/trocar PKs; ela NÃO é o desenho desta tarefa. Aqui os IDs e as FKs existentes continuam com seus tipos atuais e o campo code permanece separado.

## Objetivos e decisões do usuário

1. Código automático no formato `CODE_PREFIX-ID`, sem padding: ID42 com prefixoCAP resulta em `CAP-42`.
2. Somente geração automática é alterada. Códigos explícitos/descritivos das cargas, códigos oficiais e modelos sem CODE_PREFIX continuam inalterados. Não criar code nos modelos que usam somente ID.
3. Navegação sem duplicação de módulo e central; o caminho do exemplo deve ser `Aplicativos > Fluxo de trabalho`, mantendo recursos, atalhos úteis e permissões.
4. Publicar a versão validada no repositório e atualizar a VPS.
5. Apagar dados de negócio e recarregar cadastros auxiliares em pt-BR, com conteúdo compatível com indústria cosmética; preservar usuários, grupos e permissões. Não apagar mídias/backups. O usuário confirmou que os metadados e as regras de acesso dos anexos antigos também serão limpos; os arquivos físicos ficam guardados, mas não aparecerão nas telas após o reset.
6. Preparar o chat global do base.html para responder perguntas de uso do sistema.

## Não objetivos e limites

- Não converter PK/FK para texto nem aplicar o desenho histórico de troca de identidade.
- Não renumerar códigos explícitos, oficiais ou legados preenchidos.
- Não tornar IDs sem lacunas; sequências PostgreSQL podem ter lacunas após rollback/exclusão.
- Não criar movimentações, OPs, lotes, títulos financeiros, notas fiscais, fórmulas fictícias aprovadas ou evidências GxP para preencher telas.
- Não usar contas, dados de negócio, logs, conversas anteriores, uploads ou dumps como corpus da IA.
- Não fazer fine-tuning; reutilizar o manual/RAG existente.
- Não realizar flush global de Redis, excluir volumes, apagar credenciais ou alterar outros projetos.
- Impressão física, acesso efetivo/perfis reais e aceite industrial/regulatório continuam validações do operador/indústria.

## 1. Identificador automático

A implementação pertence ao gerador compartilhado de `base/sequences.py`/AutoCodeMixin, consumido por formulário, API, Admin e serviços. O mixin atual usa generate_code/IdentifierSequence antes do save; esse contador pode divergir do ID real e deixará de ser a fonte do code automático.

Escolha técnica proposta: usar a própria sequência de PK do PostgreSQL para reservar o ID de criação e formar `prefixo-ID` antes da inserção. Não gravar provisoriamente um code vazio e depois expô-lo a signals/auditoria. O save deverá respeitar o alias de banco, atomicidade, force_insert/force_update e update_fields. Em um registro existente com code vazio, usar a própria PK existente, sem alocar outra. Campos, constraints e FKs permanecem os mesmos.

Manter códigos explícitos exatamente como recebidos, inclusive descritores usados pelos loaders. Não reescrever automaticamente um código conflitante nem alterar a PK de um registro existente. Conflito de unicidade ou formato que não caiba no campo deve falhar de forma clara e atômica. Prefixo/PK não suportados devem falhar fechados, não cair silenciosamente em contador independente.

Identificadores operacionais declarados por AUTOMATIC_IDENTIFIERS/IdentifierSpec e os contratos diários não são CODE_PREFIX e continuam separados. Bulk_create/SQL externos não passam a ter geração automática: não prometer invariantes universais fora dos escritores suportados.

Provas: ID deliberadamente diferente do contador, PK explícita, exclusão/lacunas, concorrência de conexões PostgreSQL, signals observando o code final, criação por API/HTML/Admin, update_fields/alias/rollback, códigos explícitos e Currency sem prefixo preservados. Fazer inventário real do registry além das declarações AST antes de declarar cobertura de todos os modelos.

## 2. Navegação

Resolver a duplicação no renderizador/contexto compartilhado, não esconder texto por CSS nem remover permissões. A inspeção confirmou que workspace.html exibe o breadcrumb e um título adicional, não dois breadcrumbs. Reutilizar includes/page_header.html com um modo compacto explícito: ancestrais navegáveis e página atual em heading semântico/aria-current uma única vez, preservando ações. Alterar somente o include isolado não funciona, pois hoje nenhum template versionado o referencia.

Aplicar o contrato aos workspaces e aos cabeçalhos literalmente redundantes de módulos, listas, dashboards, ações e acesso negado. O workflow usa o nome canônico Fluxo de trabalho. Preservar títulos distintos no detalhe/formulários e a identificação dos objetos. Não fundir os destinos workspace e módulo: /app/workspaces/workflow/ fornece indicadores e /app/workflow/ fornece recursos; ambos e seus atalhos autorizados permanecem acessíveis.

Testar o HTML autenticado, o destino do link e o estado ativo, além da estrutura de contexto. Manter o sino de notificações, recursos e atalhos legítimos acessíveis com suas permissões.

## 3. Reset seletivo e carga

A etapa destrutiva será um comando explícito de manutenção para treinamento, com modo de inspeção sem escrita, opt-in de execução, conferência do banco alvo, backup novo associado à operação e recusa do uso acidental. Não colocar reset no entrypoint normal nem em migrations. Uma reinicialização comum do Compose nunca deve repetir o reset.

Construir um manifesto explícito das tabelas preservadas/limpas/recarregadas, incluindo M2M e tabelas de framework; não usar uma regra aberta de todas menos auth. O usuário real é accounts.User (settings/base.py:150 e accounts/models.py:61). Preservar o usuário ativo, seus M2Ms, Group/Permission/ContentType e histórico de migrations. Validar fechamento das dependências; qualquer relação/tabela não classificada impede executar. Preservar IDs, senhas, flags, vínculos de grupo/permissões e sequências das tabelas mantidas; não exportar esses valores para logs. Verificação de igualdade de dados sensíveis deverá ocorrer dentro do servidor retornando apenas resultado booleano.

Apagar somente as tabelas de negócio aprovadas, incluindo transações/conversas antigas que não devem ser reaproveitadas. Escolha técnica de segurança: manter os avanços de sequências existentes (CONTINUE IDENTITY), pois o usuário pediu apagar dados, não reutilizar IDs. Isso reduz o risco de referências textuais antigas apontarem a outro registro; IDs novos não precisarão começar em1. A operação terá transação, locks de tabela e advisory, com timeouts explícitos. Advisory isolado não exclui escritores não cooperantes. Avaliar TRUNCATE sobre a allowlist inteira, sem CASCADE; RESTRICT deve falhar em dependências não incluídas, jamais expandir silenciosamente o conjunto. A estratégia SQL e a lista exata de tabelas serão exercitadas em PostgreSQL descartável com relações reais antes da VPS. Falha durante reset/carga deve reverter o estágio relacional inteiro; avanços normais de sequências não são prometidos como reversíveis.

Decisão confirmada após a revisão: limpar os metadados e as regras dos anexos antigos junto com o negócio. ProtectedFileAccessRule e os metadados de arquivos entram no conjunto limpo; seus FKs não exigem preservar os antigos catálogos de negócio. Os arquivos físicos e backups não serão removidos, mas deixam de aparecer no sistema. Permissões gerais Django, grupos e usuários permanecem intactos. Não religar arquivos antigos a registros novos nem prometer sua disponibilidade na UI apenas por conservar os blobs.

Reutilizar as cargas e manifestos versionados existentes (reference_data e auxiliary/cosmetics_seed) e classificar explicitamente outros catálogos auxiliares. Nomes/descrições de uso em pt-BR; códigos oficiais, identificadores técnicos e nomenclaturas oficiais não serão traduzidos arbitrariamente. Valores cosméticos serão referências curadas, sem alegação de aprovação regulatória ou formulação produtiva validada. Preservar códigos descritivos para idempotência.

As cargas devem validar dependências, full_clean, contagens por modelo e repetição sem duplicatas. Não somar counters que contam as mesmas linhas. Não consultar sites externos na janela de deploy nem fabricar dados oficiais. Não criar integrações/notificações externas ativas. Não reutilizar full_demo: ele altera contas/grupos, cria transações e ativa integrações.

A carga existente coordenada é load_cosmetics_auxiliary_data --production-catalogs/seed_production_reference_data, não a opção legada de duas cargas separadas. Reutiliza snapshots oficiais (193 países,27 UFs,5571 municípios,178 moedas), auxiliares cosméticos e catálogos entre apps: unidades/categorias, custos, grupos/canais comerciais, contas/categorias financeiras, cargos/funções/competências e unidades/CFOPs fiscais. Suas contagens e manifestos devem ser conferidos no release, incluindo metadados dinâmicos de módulos/modelos. Os15 relatórios curados têm loader próprio sync_curated_report_catalog e devem ser explicitamente recarregados, pois apagar linhas não reexecuta a migration de seed. Configurações específicas da empresa, regras/pareceres fiscais, aprovação, especificações de qualidade e políticas não serão inferidas apenas por serem models cadastrados; registrar por modelo o que é catálogo recarregável e o que depende de dados de negócio.

## 4. Chat de uso do sistema

Reutilizar o widget existente de templates/base.html e a infraestrutura knowledge: manual_catalog, step_by_step_manual, ingestão e indexação. Atualizar o manual para a interface atual, incluindo Produto/Fórmula mestra/Componentes, versões, relacionamentos e cadastros na própria tela, filtros dependentes, navegação e códigos novos.

O corpus terá apenas documentação versionada/revista, registry e procedimentos funcionais. Validar caminhos reais, nomes visíveis, ações e permissões. Não ingerir automaticamente todo docs/, pois contém documentos de desenvolvimento/históricos não destinados ao operador. Corrigir também docs/architecture/formulations.md, hoje ingerível e contraditório com o editor atual, além de step_by_step_manual. A inclusão de docs/ui será por seções operacionais explicitamente curadas, não pelo arquivo completo com relatos de execução.

Manter seções/títulos nos chunks e vincular a versão/hash do corpus. Uma revisão do manual deve tornar documentos antigos inelegíveis tanto na recuperação PostgreSQL quanto Redis sem invalidar citações históricas por exclusão cega. Criar testes de reingestão para não recuperar instruções obsoletas. As respostas devem referenciar fontes efetivamente usadas; a lista atual de todos os trechos recuperados não prova fundamentação. Tratar conteúdo recuperado como dados, exigir citações e avaliar fatos esperados/proibidos, não somente presença de citations.

Ingerir o corpus no PostgreSQL e, no modo vetorial existente, construir/publicar nova geração Redis com embeddings pelo provedor configurado. As operações externas ficam fora da transação de reset/carga. Nenhuma configuração de credencial será adivinhada ou impressa. Se um requisito do modo ativo estiver indisponível, registrar bloqueio real e não declarar a IA pronta. Não mudar silenciosamente para um modo local/diferente só para passar.

Respostas em pt-BR, baseadas em fontes e sem ações de escrita. Fora do manual, deve dizer que não tem informação suficiente. Preservar isolamento entre sessões e permissões do chat. Perguntas de avaliação serão sintéticas sobre funcionalidades, nunca valores reais do banco.

Aceite exige mais que contar chunks: conferir cobertura e hashes do corpus, geração/alias ativo conforme o modo, recuperação real e respostas de perguntas sobre navegação, produtos/abas/componentes, códigos, estoque/qualidade, permissões e um caso sem suporte. Guardar somente resultados/trechos públicos necessários, nunca prompts/dados privados ou credenciais.

## 5. Publicação e janela de implantação

1. Testes RED/GREEN focais em PostgreSQL isolado; não compartilhar DB de testes entre escritores concorrentes de agentes.
2. Revisão independente dos diffs e do reset; Ruff/formato/MyPy/Bandit/auditoria/Node/testes com cobertura mínima80%/schema/migrations e scanner sem afrouxamentos.
3. Commit/push dos arquivos revisados, sem incluir .hermes/ ou documento privado preexistente; CI exata do candidato/main aprovada antes da VPS.
4. Preflight atualizado da VPS por metadados seguros. Construir imagem a partir do SHA fixado e validar fonte/configuração antes de parar serviços. Para esta operação destrutiva, o backup novo será feito após suspender os escritores, e não reutilizado de um deploy anterior.
5. Janela sem escritores: suspender entradas e app/worker/beat/backup_scheduler. Criar backup protegido de DB/mídia e imagem de rollback, com releitura independente. Antes de apagar o negócio, ensaiar o restore do banco em PostgreSQL descartável isolado, no mesmo servidor, sem publicar portas nem dados, e conferir agregados/permissões com saída apenas booleana/numérica. Não restaurar no banco operacional nessa prova. Se a prova falhar, não executar reset e retomar a versão anterior intacta. Impedir processamento de tarefas antigas contra o negócio apagado, mesmo sem reiniciar IDs; limpar somente filas/caches de propriedade confirmada quando necessário, sem atingir outros projetos.
6. Executar comando de reset/carga uma única vez sob os guards e confirmar contas/permissões preservadas, negócio vazio e catálogos completos. Depois, ingerir/indexar o manual e avaliar o chat com requisitos reais do modo ativo.
7. Subir imagem nova com o override original preservado e override de imagem fixada; atualizar upstream do Nginx; retomar escritores apenas depois dos gates aplicáveis.
8. Releitura independente de código/imagem/contas/permissões/catálogos/corpus/codes/menus/migrações/volumes/saúde/HTTPS e assets por hash. Manter comando de operação e evidências com IDs/hashes.

Rollback de código sozinho não recupera dados apagados. Antes do reset, reversão é imagem/configuração antiga. Depois do commit destrutivo, falha exige manter manutenção e usar o plano explícito de recuperação do backup ou corrigir/reexecutar o estágio seguro; nunca chamar uma simples troca de imagem de recuperação de dados. Preservar todas as provas negativas/timeouts.

## Critérios de aceite

- Code automático sempre corresponde ao ID real e ao prefixo no conjunto de escritores suportados; explícitos e oficiais preservados.
- Aplicativos > Fluxo de trabalho sem folha redundante, com recursos/permissões intactos.
- Reset recusado sem guards e restrito ao alvo aprovado; contas/grupos/permissões iguais antes/depois e negócio antigo ausente.
- Catálogos declarados carregados em pt-BR, apropriados ao escopo cosmético e idempotentes; sem transações demo nem integrações externas ativas.
- Manual atual/consultável e avaliação real do chat aprovada com fontes no modo configurado; resultados de mocks não substituem essa prova.
- CI do SHA publicado aprovada, implantação e releitura observadas; artefatos de recuperação preservados e ensaio isolado do banco efetivamente conferido antes do reset. Não alegar restore operacional, teste de recuperação de mídias completo ou offsite que não tenha sido executado.

## Review Focus

1. Save com PK explícita/alias/force flags e receivers vendo code final — responsável: códigos, testes focais antes de implementação.
2. FK de tabela preservada para tabela truncada ou tabela desconhecida — responsável: reset, inventário e testes de recusa sem CASCADE.
3. Tarefa antiga contra negócio apagado ou referência textual reutilizada — responsável: implantação, manter sequências e verificar isolamento/filas antes de retomar workers.
4. Corpus contendo instrução histórica/rota ou aba inexistente, ou índice apenas preparado — responsável: manual/RAG, cobertura e perguntas reais com fonte.
5. Falha após commit do reset mas antes de ativar IA/reabrir HTTP — responsável: implantação, manutenção explícita e plano de recuperação de dados distinto do rollback de imagem.
