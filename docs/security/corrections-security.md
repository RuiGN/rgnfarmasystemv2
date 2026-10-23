# Correções de segurança e privacidade S1–S5

## Política e compatibilidade

### S1 — Conectores fiscais

O deployment, não o cadastro editável, autoriza destinos e referências de credenciais.
Configure `FISCAL_PROVIDER_ALLOWED_DESTINATIONS` como JSON: cada chave é uma URL base
HTTPS exata e cada valor é a lista de **nomes** de variáveis fiscais que podem ser
usadas naquele destino. Exemplo apenas sintético para testes:

```json
{"https://fiscal.example.test": ["FAKE_FISCAL_TOKEN"]}
```

- O padrão é `{}` (fail closed). Não há domínio nem referência autorizados implicitamente.
- Configure também `FISCAL_PROVIDER_BASE_URL` e `FISCAL_PROVIDER_SECRET_REFERENCE`
  quando usar o fallback sem conector. O fallback obedece à mesma allowlist.
- Liste a URL base completa, incluindo seu prefixo de caminho, sem barra final;
  não há curingas, sufixos de host nem autorização por substring.
- Referências são vinculadas ao destino, evitando enviar o token de um provedor
  para outro destino autorizado. Somente nomes de variáveis, nunca seus valores,
  pertencem à configuração JSON. Não autorize segredos gerais da aplicação.
- Exigem-se HTTPS, porta 443, ausência de userinfo/query/fragmento e rede pública.
  HTTP, loopback, redes privadas, link-local/metadata, multicast e DNS misto
  público/privado são recusados antes da consulta de credencial/transmissão.
- O IP público validado é fixado na conexão TCP, sem segunda resolução do hostname;
  o hostname original permanece no Host HTTP e TLS/SNI. A verificação TLS continua ativa.
  Redirects e proxies herdados de ambiente são desativados. Não há retry de emissão.
- A adaptação de transporte usa o backend do pool HTTPX/httpcore. O teste com stream
  sintético verifica o IP efetivamente conectado, hostname TLS e ausência de redirect;
  execute-o ao atualizar essas bibliotecas.
- A validação é aplicada no modelo/serializer e novamente no cliente, protegendo
  registros antigos ou gravados sem `full_clean()`.
- A gestão de conectores fiscais na API/UI exige `is_staff` além das permissões
  ordinárias do modelo. `is_staff` sozinho não concede acesso ao endpoint.

Antes de disponibilizar a correção, a operação precisa cadastrar somente os destinos
reais contratados e suas referências fiscais próprias. Conectores preexistentes não
allowlisted passam a falhar de forma fechada. Seeds e homologações sintéticas exigem
settings de teste explícitos ou um cliente mockado; **não** adicionar
`homologacao.example.com` à configuração real para acomodar um demo. Este trabalho
não altera dados, credenciais, produção nem reativa agentes IA aposentados.

### S2 — Arquivos e ACLs

Permissão de modelo para incluir/alterar ACL não concede gestão de arquivo.
Criar, editar ou remover ACL exige `ProtectedFile.user_can_access(user,
permission='manage')` no alvo; retarget exige gestão tanto do arquivo original
quanto do novo. As listagens/detalhes de ACL são restritas à gestão, não à leitura.

UI e Django Admin restringem também escolhas de arquivos. A validação de autorização
permanece no caminho de gravação e não depende apenas da lista de opções. A API
impede alterar os metadados/responsável de arquivo com mera ACL de leitura,
fechando a promoção indireta para proprietário. Proprietário, uploader e regras
`manage` válidas mantêm sua gestão, sempre combinada com as permissões do modelo.

### S3 — Aprovação e delegação

- Ser o `assigned_to` não dispensa papel, módulo, área, criticidade, fila ativa ou
  alçada. Usuário inativo não decide.
- Solicitante não aprova/reprova sua própria tarefa, inclusive quando é superusuário.
  A atribuição ao solicitante também não pode ser usada para delegar essa decisão.
- Delegação temporal válida continua permitindo substituição sem exigir que o
  substituto possua o mesmo grupo. A elegibilidade/alçada é validada no delegante
  original; o substituto deve estar ativo e não pode ser o solicitante.
- Alterações de fila, atribuição, solicitante, valor, área/criticidade e referências
  de origem exigem `workflow.change_approvalqueue`, além de `change_approvaltask`.
  Não é criada permissão nova nem migration de permissões. Reavaliar concessões de
  `change_approvalqueue`, pois ela é autoridade de gestão sensível.
- Delegação só pode ser criada/editada pelo substituído ou gestor com
  `change_approvalqueue`; retarget exige autoridade sobre ambos os delegantes.
- Estado, autor/data/comentários da decisão não são editáveis nos formulários
  genéricos UI/Admin; decisões continuam pelas ações de domínio.

Chamadas ORM internas são código confiável: os serviços internos que alterem
atribuição devem chamar `validate_sensitive_changes()` com seu ator. Estas regras
não substituem o desenho de alçadas e a revisão operacional de permissões.

### S4 — Privacidade na interface

Um seletor compartilhado restringe arquivos por `view`/`manage`, preservando
proprietário/uploader, ACLs ativas por usuário/grupo e o bloqueio de artefatos de
relatório não concluído. Recursos UI de arquivos, ACLs, links e trilhas aplicam o
mesmo escopo usado na API. Pesquisa global, detalhe, exportação e consultas de
recursos consomem esse queryset restrito. Campos relacionados de formulários
seguem o escopo do recurso, com `manage` para o alvo da ACL.

Sessões/mensagens RAG pertencem ao dono da sessão. Superusuário não recebe um
bypass de leitura dessas conversas. O Django Admin aplica o mesmo isolamento a
sessões, mensagens e citações e à gestão de arquivos/ACLs, evitando uma segunda
interface genérica que contorne os controles.

Por solicitação adicional, movimentos de estoque e fluxo de caixa são somente
leitura no catálogo. Saldos preservam criação de metadados com quantidade inicial
zero (`product`, `lot`, `warehouse`, `location`, `unit`), sem campos de quantidade
nem campos editáveis na alteração. Não é necessário proibir esse cadastro vazio.
Baixas financeiras preservam a criação operacional pelos campos econômicos
explicitamente permitidos: o `save()` do modelo corrigido contabiliza título/caixa.
Alteração UI permite apenas `notes`; `allow_delete=False` proíbe exclusão mesmo
com permissão de modelo. POSTs maliciosos de valor/status fora do formulário são
ignorados sem alterar evidência ou saldos; teste HTTP verifica os efeitos reais.

### S5 — RAG local

`RAG_CHAT_LOCAL_ONLY=True` é consultado **antes** da recuperação. O caminho local
usa recuperação PostgreSQL lexical/vetor determinístico local; não consulta Redis
nem gera embeddings/respostas externos. A política continua valendo com índice
Redis ativo e provedor configurado. Ingestão/indexação administrativa externa não
é desligada por essa flag de chat e deve ter política operacional separada.

## Verificação

Os novos cenários ficam em `tests/test_security_corrections.py`. Foram reproduzidos
REDs por fatias verticais antes dos fixes e registrados GREENs no scratch em
`security-corrections-*.log`. Todos os nomes/valores de credenciais HTTP usados nos
testes são sintéticos; não houve emissão, rede de provedor ou consulta de segredos.

Comando isolado de testes:

```sh
python /home/deploy/.hermes/cache/scratch/run_rgn_tests.py --db security tests/test_security_corrections.py --reuse-db -q
```

Além dos testes de ataque, há controles positivos para gestão legítima de ACL,
aprovador elegível e delegação legítima, transporte HTTPX real sobre stream fake,
TLS hostname, redirect e busca/detalhe HTML. Os testes antigos não foram alterados
para aceitar as novas regras. A factory de formulário usa MRO dinâmica por `type()`
com um mixin ModelForm, sem supressão global do MyPy. Mensagens de validação sobre
`secret_reference` são texto, não segredos hardcoded; Bandit permanece habilitado
sem `nosec` nesta implementação.

Os resultados finais e eventuais bloqueios de infraestrutura são informados no
relatório de entrega e nos logs do scratch. O gate integrado após a recuperação do
PostgreSQL passou **320 testes e 7 subtestes**, incluindo os **54 cenários novos**
deste workstream e os módulos UI/arquivos/workflow/conhecimento/fiscal/integrations,
estoque e financeiro. Ruff check/format, MyPy em 15 fontes, Bandit, Django check e
check de migrations dos cinco apps de segurança passaram.

Uma execução subsequente dos 54 cenários próprios retornou **53 passados e uma
falha** após alteração concorrente em `finance/models.py`: a criação de título da
fixture chama `FinancialTitle.approve()`, mas a nova validação de campos de serviço
recusa `status`/`approved_at`. Esse caminho precisa ser corrigido pelo dono do
financeiro e o gate final repetido no snapshot congelado; os testes de segurança
não foram relaxados para acomodá-lo. Logs: `security-corrections-final-green.log`
e `security-corrections-own-final-green.log`.

A aprovação desta alteração não equivale à validação fiscal em homologação nem
à aprovação regulatória/operacional.

## Revisão — autorização das ações S2-01 / S1-01

Correção limitada a `files/views.py`, `integrations/views.py`, ao novo
`tests/test_review_security_action_corrections.py` e a esta seção. Nenhuma mudança
em financeiro, estoque, base/UI, core, settings, dependências, deploy, `.env` ou
produção; nenhum commit.

- **Arquivos:** `delete_secure` e `expire` agora verificam
  `user_can_access(user, permission='manage')` antes do domínio. A inspeção da
  mesma família encontrou o mesmo bypass em `replace` e na revogação de link;
  ambos receberam a mesma exigência. O escopo de leitura continua separando
  `view`/`download`; geração/uso de link e registro de acesso preservam suas
  permissões de consumo. As ações HTML reutilizam os callbacks DRF corrigidos.
- **Conectores fiscais:** `activate`, `suspend`, `test_success` e `test_failure`
  verificam `validate_fiscal_management(user, {})` antes da mutação. A exclusão
  API (`destroy`), encontrada na mesma família, também aplica esse guard.
  Erros de autoridade retornam 403; `test_failure` verifica autoridade mesmo
  quando falta a mensagem. Permissões de modelo continuam obrigatórias;
  conectores não fiscais e chamadas ORM internas confiáveis não ganharam
  restrições novas.
- **Prova HTTP/DB:** os testes usam usuários/permissões/ACLs e modelos reais,
  verificam estados, autores e trilhas/eventos após as chamadas; nenhum handler
  de domínio é mockado. Casos de gestor/staff legítimo retornam 200 na API
  (201 na substituição, 204 na exclusão) e 302 no fluxo HTML. As negativas
  exigem exatamente 403 e ausência de mutação. A fixture fiscal é sintética,
  com sockets Python bloqueados; não há emissão nem chamada de provedor.

TDD vertical reproduzido por família, com RED antes de cada correção:

| Fatia | RED real | GREEN |
| --- | --- | --- |
| Exclusão protegida/expiração API e HTML | 4 falhas, 4 passados | 8 passados |
| Substituição/revogação API e HTML | 4 falhas, 4 passados | 16 passados acumulados |
| Ações fiscais API e HTML | 8 falhas, 16 passados | 40 passados acumulados |
| Exclusão API fiscal | 1 falha, 2 passados | 43 passados acumulados |
| Autorização antes de validar mensagem | 1 falha, 1 passado | 58 passados, incluindo controles de compatibilidade |

Logs no scratch: `security-review-fix-*-red.log`, respectivos GREENs e
`security-review-fix-own-green.log`. O gate dirigido após formatação retornou
**131 passados** (`security-review-fix-targeted-green.log`), incluindo os 58
novos cenários, arquivos, integrações, correções de segurança e ações HTML.
Ruff check/format nos três arquivos Python, MyPy e Bandit nas duas views e
`git diff --check` passaram (`security-review-fix-static-green.log`).

```sh
python /home/deploy/.hermes/cache/scratch/run_rgn_tests.py \
  --db security --image rgnfarmasystem:corrections-clean-tests \
  tests/test_review_security_action_corrections.py -q
```

### Limites encontrados — não declarar aprovação global

1. **Exclusão HTML genérica de conector fiscal ainda contorna staff.**
   `ResourceDeleteView.post()` chama diretamente `obj.delete()`, sem reutilizar
   a view DRF. Probe HTTP com usuário não staff e permissões view/delete retornou
   **302 e exclusão efetiva** em `/app/integrations/connectors/<pk>/delete/`.
   A probe usou PostgreSQL de teste e rollback; evidência em
   `security-review-fix-ui-delete-probe.log`. Corrigir exige o dono de
   `base/ui/views.py` (explicitamente fora deste ownership); este agente não
   alterou essa superfície nem mascarou a pendência com um teste permissivo.
2. O gate ampliado retornou **136 passados, 2 falhas**: descoberta espera 232
   ações, mas há 233, e o catálogo HTML não possui a nova ação
   `('inventory.stockmovement', 'issue', False)`. Evidência em
   `security-review-fix-regression-green.log` e
   `security-review-fix-catalog-diagnostic.log`. Isso está na superfície de
   estoque/catálogo concorrente, fora destas alterações; testes não relaxados.

A revisão fresh do agente pai permanece necessária. Os dois bypasses de ações
DRF reportados foram corrigidos, mas a exclusão HTML genérica encontrada impede
apresentar toda a gestão fiscal UI como autorizada corretamente.

## Revisão complementar — fechamento da exclusão HTML genérica S1

Esta seção fecha a pendência HTML descrita acima; os resultados anteriores são
históricos. A alteração desta fatia é somente o guard de `ResourceDeleteView` em
`base/ui/views.py`, o novo `tests/test_review_ui_fiscal_delete_corrections.py` e
este apêndice. As alterações anteriores no mesmo arquivo foram preservadas.

- `get_object()` aplica `IntegrationConnector.validate_fiscal_management(user, {})`
  tanto no GET de confirmação quanto no POST de exclusão, depois das verificações
  ordinárias de `view` e `delete` do recurso e antes de qualquer exclusão/trilha.
  `ValidationError` de autorização torna-se `PermissionDenied`/HTTP **403**, como
  nas outras entradas UI fiscais. Não se altera a política do modelo nem se cria
  bypass separado para superusuário: superusuário sem staff é recusado.
- Staff com view/delete mantém GET **200** e POST **302**, com exclusão efetiva e
  autoria da trilha `ui.resource.deleted`. Staff sem delete ou sem view recebe
  **403**, sem alteração do registro, eventos ou trilha. Não staff com view/delete
  de conector **não fiscal** continua autorizado; outros modelos não recebem guard
  fiscal nem bloqueio indiscriminado de exclusão.
- A inspeção do catálogo e da descoberta de ações encontrou um único recurso
  `IntegrationConnector` (`integrations/connectors`), nenhum inline com esse
  modelo filho e nenhuma ação de coleção desse modelo. Portanto, não existe
  entrada bulk/inline fiscal para receber guard adicional neste snapshot.
  POSTs reais em `connectors/delete/`, `connectors/actions/delete/` e
  `connectors/actions/bulk-delete/` retornam **404** e preservam o DB.
- Os testes verificam DB real, todos os campos do conector, eventos e trilhas nas
  negativas; não mockam modelo, validação ou handlers. Sockets Python são
  bloqueados após criar a fixture sintética. A exclusão legítima mantém o contrato
  existente de `IntegrationEvent.connector`: **SET_NULL**, não PROTECT; o evento
  permanece com os demais campos intactos. A negativa preserva também esse vínculo
  e não gera evento/trilha de exclusão.

### Evidência RED → GREEN

- `ui-fiscal-delete-review-fix-post-red.log`: **1 falha, 3 passados**; não staff
  com view/delete recebeu 302 em vez de 403.
- `ui-fiscal-delete-review-fix-preview-red.log`: **2 falhas, 3 passados**; a mesma
  exclusão POST e o preview GET (200 em vez de 403) falharam antes do guard.
- `ui-fiscal-delete-review-fix-first-green.log`: **5 passados** após o guard.
- `ui-fiscal-delete-review-fix-own-final-green.log`: **20 passados**, incluindo
  controle de view/delete, preview, superusuário/staff, não fiscal, história e
  ausência de entradas bulk/inline.
- `ui-fiscal-delete-review-fix-targeted-final-green.log`: **266 passados e
  7 subtestes passados**, cobrindo as duas revisões de segurança, correções S1–S5,
  regressões de arquivos/ledgers UI, integrações, UI genérica e
  dispatch/registry/discovery/completude das ações. O problema concorrente de
  catálogo registrado acima não reapareceu nesta execução.
- `ui-fiscal-delete-review-fix-static-final-green.log`: Ruff check/format e MyPy
  nos dois arquivos Python próprios passaram; Bandit na view de produção passou
  sem supressões. A execução exploratória de Bandit sobre o teste reportou somente
  B101 por seus asserts de pytest; os asserts foram preservados, não suprimidos.
  `git diff --check` limitado aos três arquivos próprios passou.

```sh
python /home/deploy/.hermes/cache/scratch/run_rgn_tests.py \
  --db security --image rgnfarmasystem:corrections-clean-tests \
  tests/test_review_ui_fiscal_delete_corrections.py -q
```

Nenhuma alteração em backend fiscal/integrações, arquivos, estoque, financeiro,
core, deploy, dependências ou `.env`; nenhum commit, acesso à produção, emissão
ou comunicação com provedor. As verificações utilizaram somente PostgreSQL e
imagem Docker de testes isolados. A revisão fresh completa de segurança pelo
agente pai continua necessária: este fechamento não é aprovação global nem
homologação fiscal.

## Dependências — Django REST Framework 3.18.3

Os pins direto e resolvido passam de `djangorestframework==3.18.0` para
`3.18.3`. A atualização é limitada ao pacote DRF; as demais versões permanecem
fixadas. Não modifica models, migrations, menus, permissões ou os critérios RAG.

O `pip-audit --strict` identificou três vulnerabilidades altas na versão anterior:

| Aviso | Fronteira afetada | Correção upstream |
| --- | --- | --- |
| [CVE-2026-114138 / GHSA-33wh-fxxf-88vv](https://github.com/advisories/GHSA-33wh-fxxf-88vv) | Negociação de conteúdo com cabeçalhos `Accept` grandes | 3.18.2 |
| [CVE-2026-114136 / GHSA-3547-9m27-7rxg](https://github.com/advisories/GHSA-3547-9m27-7rxg) | Seleção de codecs pelo parser JSON | 3.18.2 |
| [CVE-2026-114137 / GHSA-xw6w-gcfp-cf8m](https://github.com/advisories/GHSA-xw6w-gcfp-cf8m) | Exclusão de tokens por `TokenProxy.delete()` | 3.18.2 |

A 3.18.3 inclui essas correções e reverte uma alteração incompatível acidental
de `order_by_precedence` na 3.18.2, conforme as
[notas oficiais](https://www.django-rest-framework.org/community/release-notes/).
Isso não demonstra que todas as superfícies dos avisos estejam expostas nesta
instância, nem é evidência de exploração ou de incidente.

A validação deve conferir a origem e o hash do wheel oficial, a ausência de
mudanças em outras distribuições, a compatibilidade declarada com Python/Django,
nova auditoria estrita e o gate completo do código exato. A auditoria anterior
negativa é preservada; não se adicionam exclusões de CVEs nem se desabilitam
scanners. Auditorias históricas aprovadas refletem o catálogo de avisos disponível
naquela execução, não uma garantia permanente sobre a versão.

Atualizar pins ou aprovar testes locais não comprova que uma imagem foi construída,
que o CI passou ou que a VPS foi atualizada. Esses resultados devem ser vinculados
separadamente ao commit, à imagem e à execução observados antes de qualquer promoção.
