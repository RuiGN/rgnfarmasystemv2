# Encerramento das ressalvas — rodada posterior ao aceite funcional

## Escopo e autorização

O usuário aprovou funcionalmente o pacote original com ressalvas e depois solicitou seu encerramento técnico. Nesta rodada autorizou separadamente:

- commit e push **somente dos arquivos públicos revisados**, na branch `release/2026-10-20-63af02ef`, atualizando o PR draft nº 1 e executando seu CI;
- exceções de scanner **pontuais e comprovadas**, incluindo quatro ocorrências históricas imutáveis e hashes/trechos públicos específicos, condicionadas a testes negativos reais;
- adaptação da interação temporal em telas estreitas, preservando ISO, segundos, validação no servidor e acessibilidade;
- **nenhum merge, deploy, reescrita de histórico ou dispensa de regras de segurança/qualidade**.

O ZIP original, sua decisão funcional e todas as evidências negativas anteriores permanecem históricos imutáveis. O aceite original não afirma que alterações posteriores já foram verificadas.

## Matriz de encerramento

| Ressalva | Critério para encerrar | Estado nesta preparação |
| --- | --- | --- |
| Popup nativo de data/hora a 320 px | Comprovar interação em320 e controle640, preservando ISO/segundos, POST, servidor e fallback acessível | Fechado no recorte autorizado:15 testes browser e4 Django sem DB reexecutados pelo integrador;58 artefatos/38 capturas e cinco fontes conferidos;16 calendários abertos inspecionados sem corte. Sem reclassificar QA89, hardware móvel ou WCAG formal |
| Diretório público com 120 achados e todas as refs com quatro | Provar proveniência; aplicar somente exceções autorizadas; scanner real em ambos os escopos e canários alterados devem passar/detectar conforme o caso | Fechado no recorte do scanner:25 contratos GREEN; renovação independente do diretório original, todas as refs e candidato da integração com3.671 arquivos:exit0/0. Relatórios/hashes relidos e índice preservado. Fonte final ainda exige rescan; ver secrets-closure.md |
| Concorrência entre escritores de fórmulas/componentes | Matriz real de escritores; testes determinísticos com conexões PostgreSQL separadas; corrigir qualquer violação demonstrada e delimitar API/Admin/bulk/SQL | Implementado;109 testes GREEN e JUnit/hash conferidos. Revisão independente do protocolo e gate integrado pendentes. SQL/update/bulk externos continuam fora da garantia |
| CI remoto da revisão atual | Publicar somente depois dos gates locais e revisão; reler o SHA do PR; todas as verificações obrigatórias do SHA exato concluídas com sucesso | Publicação autorizada, ainda não realizada nesta preparação |
| Cobertura JavaScript no gate | Executar sintaxe de todos os assets próprios e todos os arquivos de testes JS, sem retirar checks anteriores | Três contratos RED→GREEN; sintaxe dos assets e21 testes Node reais renovados, incluindo os três novos da adaptação temporal |
| Auditoria atual de dependências | Resolver advisories sem ignorá-los e exercitar os consumidores afetados | pypdf6.19.0 apresentou quatro CVEs; atualizado para6.20.1 em fonte/lock/ambiente. pip_audit --strict:exit0, zero vulnerabilidades conhecidas. Compatibilidade:20 testes PASS/JUnit conferido, incluindo12 casos PDF de relatórios, ingestão e contratos de versão |

### Resultado das investigações e autorização complementar

O trecho seguinte preserva o diagnóstico anterior à remediação. A matriz acima
e os documentos vinculados distinguem a implementação atual da contraprova histórica.

O agente principal conferiu o JUnit da investigação de escritores: dez testes,
cinco falhas de comportamento e cinco positivos, sem erros de harness. Os quatro
casos concorrentes reproduziram perda de campos não alterados ou aceitação de
componente validado antes de aprovação concorrente; o quinto reproduziu falsa
colisão de identidade no PATCH da fórmula. O estado do problema deixou de ser
apenas ausência de evidência: há regressões reais bloqueando a publicação.
O protocolo comum restrito à tríade está em implementação, não aprovado como
resolvido. Detalhes e casos RED: [Concorrência dos escritores](formula-writer-concurrency.md).

As 24 capturas e suas dimensões/hashes foram conferidas. A contraprova em HTML
mínimo reproduz o corte do popup a 320 px sem o CSS da aplicação; a 640 px o
popup mostra todas as colunas. O usuário autorizou explicitamente **adaptar a
interação em telas estreitas**, preservando ISO, segundos, validação no servidor
e acessibilidade. A adaptação está em implementação. A prova original e o QA89
não foram reclassificados: [Seguimento do seletor nativo](native-picker-followup.md).

## Cobertura JavaScript corrigida

A execução do script de CI com executáveis de gravação isolados demonstrou que o gate não verificava a sintaxe de `static/js/related-fields.js` e executava somente `tests/js/local-printing.test.cjs`, omitindo os dois arquivos de testes de abas/selects.

O script agora verifica a sintaxe do asset relacional e executa `node --test tests/js/*.test.cjs`. Nenhum gate Python, cobertura mínima, prazo de prontidão ou verificação de segurança foi retirado. Dois testes de orquestração exercitam o shell real sem iniciar Django, banco ou serviços; o Node real aprovou seus 18 testes. Uma primeira execução do stub Python excedeu o limite; o harness foi substituído por gravação shell sem novos interpretadores por comando, mantendo o timeout e preservando o erro anterior.

Um terceiro contrato demonstrou que outros assets próprios também ficavam fora
da verificação de sintaxe. O gate passou a iterar `static/js/*.js`, preservando os
checks anteriores e cobrindo automaticamente o asset da nova interação quando
ele existir. A nova contraprova RED e o GREEN de três contratos estão separados
em `ci-javascript-all-assets-{red,green}.log`; os assets próprios existentes
também passaram por `node --check` real. Isso não substitui o CI remoto.

Evidências: `ci-javascript-syntax-red.log`, `ci-javascript-syntax-green.log` (tentativa incompleta), `ci-javascript-syntax-green2.log`, `ci-javascript-all-tests-red.log` e `ci-javascript-all-tests-green.log`, no diretório local de evidências usado pelo pacote original.

## Validações externas: não podem ser fechadas por uma edição de código

Estes itens continuam exigindo evidência própria. Não serão marcados como realizados pelo aceite em chat, testes sintéticos ou CI:

| Item externo | Execução necessária | Evidência mínima para fechamento |
| --- | --- | --- |
| Impressão física de etiquetas | Operador na indústria, com a impressora e os consumíveis reais | Modelo/conexão, tamanho real, alinhamento, texto/código legível, leitura do código, resultado por cenário e responsável/data |
| Login e perfis reais | Usuário autorizado testar em homologação com suas próprias credenciais, sem compartilhá-las no chat | Rotas permitidas/negadas, ações visíveis e recusadas, ausência de alteração indevida, responsável/data |
| Treinamento e aceite operacional | Responsável da indústria executar roteiro de Produto/Fórmula/Componentes e cenários operacionais aplicáveis | Registro dos cenários, resultados, desvios e aceite por responsável |
| Aceite regulatório/CSV | Responsáveis de qualidade e validação aplicarem a avaliação de risco e o protocolo exigido | IQ/OQ/PQ quando aplicáveis, evidências rastreáveis, desvios e aprovação competente; nenhum certificado é gerado por esta rodada |
| Restore/offsite/banco+mídia operacional | Teste de restauração autorizado em ambiente isolado e demonstração da cópia externa e consistência do conjunto | Identidade do backup, hashes, readback dos dados/arquivos, RPO/RTO medidos e responsável; não usar o banco operacional como alvo |
| Auditoria formal de acessibilidade | Avaliação do escopo e fluxos com tecnologias assistivas e critérios definidos | Resultados por critério e ferramenta, problemas corrigidos/retestados; matriz geométrica não equivale a WCAG |
| Isolamento absoluto do navegador no SO | Política de rede verificável em ambiente controlado, abrangendo subprocessos | Configuração e observações de rede; bloqueio CDP da página sozinho não basta |

A ausência de impressora local é conhecida. Preparar esse roteiro resolve a falta de critério de aceite, mas **não comprova execução dos itens externos**. Se exigidos antes da implantação, continuam bloqueantes até sua execução e registro; não são dispensados por classificar seu responsável.

## Estado de publicação e release

A revisão independente `deleg_33abcd6c` retornou `ship`, confiança média e nenhum
achado, restrita ao snapshot do protocolo; não executou banco ou testes. Sua
pergunta residual sobre mais combinações concorrentes de mudança de pai/exclusão
permanece explícita, não uma garantia de cobertura exaustiva.

O gate completo de tipagem encontrou12 diagnósticos nos dois novos adaptadores.
Foram corrigidos reutilizando o contrato de serializer existente, chamadas
`getattr(super(), ...)` conforme o padrão do repositório e uma factory de form
que conserva o `clean` original. Sem ignores nem redução de verificações.
A nova execução passou **MyPy em 404 fontes** e **Bandit**, com dotenv bloqueado
e conexão de banco proibida. O pequeno delta está em revisão própria e em
reexecução dos 109 casos; seus resultados devem ser conferidos antes de publicar.
Os recortes locais não substituem a suíte global/cobertura/build do Quality Gate
na CI do commit exato. Não há dispensa de nenhum check remoto obrigatório.

- Revisão técnica, implementação e evidências finais ainda em integração nesta preparação.
- Nenhum resultado futuro de CI é presumido.
- Merge, deploy e entrada em produção permanecem fora da autorização.
