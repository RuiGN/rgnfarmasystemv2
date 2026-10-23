# Manual e chat RAG — operação e avaliação

## Contrato funcional

O widget e `POST /api/knowledge/chat/` mantêm as chaves de resposta
`session_id`, `message_id`, `answer` e `citations`. Uma citação continua contendo
`title`, `section_reference`, `url` e `excerpt`. Sessão autenticada, CSRF e
`knowledge.view_ragchatsession` continuam obrigatórios; histórico é isolado por
usuário. O chat é somente leitura e não ganha ferramentas de mutação.

Produtos usam **Produto / Fórmula mestra / Componentes**; o editor próprio de
fórmula usa **Fórmula mestra / Componentes**. A escolha de versão é explícita,
com **Carregar seleção**, e não pressupõe a mais recente. Cadastros relacionados
são salvos separadamente do formulário principal. Filtros dependentes, versões
anteriores/aprovadas e permissões não são substituídos pelo chat.

Estoque usa os recursos **Lotes / Saldos / Movimentos**: o histórico de movimentos
é somente leitura e as quantidades não são editadas diretamente em Saldos.
Validade é consultada em Lotes, não em uma coluna inventada de Saldos.
**Controle de qualidade** usa especificações, amostras, análises com resultados
inline, resultados analíticos, investigações e documentos; não possui recurso
Inspeções. A ação **Avaliar** do resultado é separada de salvar e das ações de
revisão/aprovação da análise. O manual não promete aprovação automática nem
liberação de estoque ao registrar resultados.

## Corpus e revisões

`build_erp_manual_corpus` gera conteúdo a partir do registro de recursos,
instruções funcionais e arquitetura local. Cada entrada tem revisão `manual-v2`,
SHA-256 do conteúdo e versão derivada desse hash. Cada chunk conserva o título e
o caminho de seções Markdown; continuações permanecem na mesma seção.

O guia de Cadastros mestres inclui seções autocontidas de códigos automáticos e
limites do chat. Isso concentra os fatos transversais sem remover os procedimentos
de Produto e Fórmula mestra nem alterar o algoritmo de recuperação. A mudança do
conteúdo produz outro hash e exige ingestão da revisão e publicação controlada de
um novo índice; editar o arquivo não atualiza um índice já ativo. Documentos e
citações históricos permanecem preservados. Não é necessário repetir o reset.

Ingestão bem-sucedida publica `current_content_hash` na fonte, dentro da mesma
transação que prepara os chunks. PostgreSQL, construção do índice e leitura de
hits Redis usam a mesma elegibilidade. Um índice Redis antigo não autoriza
retornar um documento obsoleto: seus hits são revalidados contra o PostgreSQL.
Documentos/chunks antigos não são apagados ao reingerir, e reingestão idempotente
não recria os chunks já ingeridos, preservando citações históricas. Uma ingestão
parcial pode ser expandida sem trocar os IDs já citados; `chunks_created` e o
log contam somente as linhas realmente inseridas, inclusive zero na reingestão
idempotente.

Antes da primeira ingestão versionada, fontes legadas sem esse marcador mantêm
o comportamento de elegibilidade existente. Reingerir o manual é necessário
para estabelecer a revisão corrente. Reingerir exatamente uma revisão antiga é
uma publicação explícita dessa revisão, não uma exclusão do histórico.

Após o reset seletivo, o responsável pela implantação deve gerar o novo corpus
**depois** da transação de reset e então publicar o índice externo. Não incluir
chamadas OpenAI/Redis na transação de reset. Comandos existentes preservados:

```bash
python manage.py build_erp_manual_corpus
python manage.py rebuild_knowledge_index
python manage.py reconcile_knowledge_alias
```

A geração possui manifesto próprio. O alias ativo e os comandos de reconciliação
mantêm o fluxo existente de publicação; as citações antigas não exigem ativar
novamente um índice antigo.

## Fundamentação e indisponibilidade

Prompt desta revisão em `knowledge/prompts/manual-grounded-v4.txt`; v2 e v3
permanecem no repositório para rastreabilidade. O prompt pede contagens documentadas
explícitas, restrições relevantes e passos fundamentados na seção procedimental
aplicável, sem acrescentar citações apenas para cumprir essa preferência. A presença
dessas instruções não prova obediência do modelo nem melhora de recuperação.

A v4 acrescenta um contrato geral de composição: selecionar a evidência principal
pelo conteúdo e escopo da pergunta, redigir a partir dela e conferir cada orientação
e sua citação. Expressões técnicas documentadas permanecem completas; pontuação,
coordenação e Markdown não devem fragmentá-las. Não há seleção de fontes por
pergunta conhecida, posição no ranking ou identificador de caso, nem remapeamento
posterior de citações para satisfazer uma avaliação.

Esta alteração está preparada para validação offline. Testes do texto das instruções
e da estrutura de resposta não executam o modelo nem demonstram que os casos reais
passaram. A mudança isolada de prompt não altera o corpus, a elegibilidade ou o
índice; não justifica reingerir documentos, reconstruir embeddings ou repetir o reset.
Uma nova avaliação externa exige autorização e orçamento próprios, além dos gates
de fonte e implantação. Relatórios anteriores e critérios congelados não são alterados.

Pergunta e fontes são dados JSON separados das instruções; conteúdo recuperado não é uma
instrução executável. A geração retorna JSON validado com texto e números das
fontes efetivamente declaradas como usadas. Referências inexistentes,
duplicadas, sem marcador no texto ou respostas fora da estrutura são rejeitadas.
A resposta pública cita somente o subconjunto usado, na ordem correspondente.
Isso verifica referências, não prova por si só a correção semântica da geração.

Sem contexto, o serviço recusa deterministicamente sem chamar o provedor. Em
`RAG_CHAT_LOCAL_ONLY=True`, não chama OpenAI, HTTP de ingestão nem Redis na
resposta: usa apenas PostgreSQL e mostra até três trechos, citando somente esses
trechos. Não confundir a resposta extrativa local com uma avaliação de IA.

O modo externo mantém o fallback local já existente, explicitamente informado
na resposta. Exceções do provedor não são exibidas ao usuário; o modo configurado
não é reescrito. A avaliação de geração abaixo não aceita fallback: chama o
provedor real diretamente e falha se o modo for local, se o Redis/índice estiver
indisponível ou se a geração violar o contrato.

## Avaliação PT-BR reproduzível

Golden set em `knowledge/evals/pt-br-manual-v2.json`: sondas sintéticas de produto,
versão, componentes, relacionamentos/FK, códigos, navegação, estoque, qualidade,
permissão, pergunta fora do manual e pedido de mutação. Cada caso declara fatos obrigatórios,
proibidos e fontes/seção esperadas. Não contém registros de negócio nem dados
privados. É regressão, não holdout independente; revisão semântica humana segue
necessária. Não se deve ajustar o fixture para esconder falhas.

`retrieval_ok` exige fonte/seção esperadas em algum trecho recuperado (casos sem
fonte esperada são sondas de recusa). No modo geração, os fatos obrigatórios e
proibidos são conferidos na resposta; adicionalmente, cada grupo de fatos
obrigatórios precisa aparecer no conteúdo dos trechos **declarados usados** que
correspondam à fonte e seção esperadas. Trechos recuperados mas não usados, de
outra fonte ou de outra seção não emprestam sustentação. Evidências usadas
compatíveis podem compor os fatos entre si; se o caso não restringe seção, vale
a fonte declarada. A recusa sem suporte não exige fontes, e geração não executada
continua `null` no modo retrieval.

O campo opcional `forbidden_unless_negated` lista termos de `forbidden` cuja
ocorrência pode ser uma advertência negada. Somente o termo listado recebe a
exceção e somente quando imediatamente precedido da palavra `não` e de um ou
mais espaços/tabs, com a mesma normalização de caixa/acentos. Cada ocorrência é
conferida separadamente: uma advertência não libera outra afirmação positiva na
mesma resposta; `não apenas aprova...` não é negação direta. Sem o campo, mantém-se
a proibição literal anterior, inclusive em frases negadas. Atualmente somente
`aprova automaticamente a análise` na sonda qualidade usa a exceção; os demais
termos proibidos continuam literais. Não se trata de um parser de linguagem.

Esse gate usa presença lexical normalizada (caixa/acentos) dos termos versionados;
não prova implicação lógica, tratamento universal de negações/paráfrases ou verdade
semântica de cada afirmação. Não substitui revisão humana nem avaliação do provedor real.
As sondas de estoque/qualidade derivam dos nomes, campos e ações do registry,
formulários e modelos locais. A regressão PostgreSQL ingere o corpus completo e
confere também os fatos e hashes dos trechos dessas sondas.

Após gerar corpus e índice, no ambiente de implantação autorizado:

```bash
python manage.py evaluate_manual_rag --mode retrieval --require-redis --output /caminho/novo-rag-retrieval.json
python manage.py evaluate_manual_rag --mode generation --output /caminho/novo-rag-generation.json
```

Para verificar somente recuperação local, sem rede:

```bash
# Usar uma configuração que já tenha RAG_CHAT_LOCAL_ONLY=True.
python manage.py evaluate_manual_rag --mode retrieval --output /caminho/novo-rag-postgres.json
```

O comando não ingere documentos, não cria usuário/conversa e não altera dados de
negócio; o modo generation transmite apenas perguntas sintéticas e trechos do
manual elegível ao provedor já configurado. Seus arquivos usam criação exclusiva
para não sobrescrever evidências. O processo sai com erro se algum caso reprovar.

O relatório registra cada caso, fontes/chunks/versões/hashes, manifesto do índice,
modelo efetivamente retornado, hash do conjunto e do prompt e latência observada.
Os campos `retrieval_ok` e `generation_ok` separam os vereditos de recuperação e
geração. Tokens e custo ficam `null`, pois o
gateway atual não os fornece para geração. Nenhuma estimativa é apresentada como
medição. Comparar baseline/candidato mantendo o hash do conjunto e registrando os
hashes de corpus e prompt de cada rodada; guardar ambos os relatórios e revisar os
movimentos por caso. Se corpus ou prompt mudar, explicitar essa diferença, sem
reescrever resultados anteriores nem enfraquecer critérios para obter aprovação.

Uma falha de recuperação pula a geração naquele caso; não comprova uma resposta
incorreta do gerador. A sonda de mutação usa a recuperação e geração diretamente,
enquanto o serviço também possui uma guarda local anterior à recuperação. Os dois
caminhos precisam ser verificados separadamente: um não transforma a falha do outro
em aprovação. Testes offline das respostas observadas protegem os critérios, mas
não medem novo recall vetorial nem comprovam a qualidade de uma geração futura.

Testes com doubles na fronteira OpenAI/Redis comprovam o contrato local, **não**
a disponibilidade ou qualidade do modelo/RediSearch na implantação. Uma execução
real de geração e recuperação externa permanece obrigatória antes de declarar
o assistente pronto.
