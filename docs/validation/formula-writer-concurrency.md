# Produto / Fórmula / Componentes — concorrência entre escritores

## Remediação aplicada — verificação local focada

A decisão de integração autorizou um dono comum **somente para a tríade**. A
implementação usa `formulations/writers.py`: transação e advisory lock PostgreSQL
transacional compartilhado; descoberta de pais estabilizada pelo gate; locks de
linhas Produto(s) → Fórmula(s) → Componente(s), ordenados por PK. Mudanças de pai
incluem os pais atual e pretendido. O gate é deliberadamente conservador: serializa
as gravações de manutenção desta tríade, não leituras nem os demais módulos.
É uma escolha de correção simples, com custo de paralelismo documentado; não é
constraint de banco nem garantia contra escritores que ignorem o protocolo.

Depois do lock, a instância é recarregada; somente `validated_data` REST ou
`changed_data` dos formulários é reaplicado. FKs são reaplicadas por identidade e
seus caches descartados, para validar relações atuais. O objeto retornado também
é atual. Os mixins de serializer de masters/formulations usam a pequena cópia
compartilhada `instance_for_clean`, preservando `_state.adding` e `_state.db`;
nenhuma validação/constraint foi desativada. Os clones de outros módulos não
receberam uma refatoração transversal fora do escopo autorizado.

### Superfícies adaptadas

- REST Produto/Fórmula/Componente: create/update/PATCH via dono; destroy via
  mesmo protocolo. FK protegida retorna 400, não 500. Os aliases v1 compartilham
  as mesmas classes e têm provas HTTP específicas.
- UI integrada: gate **antes** do lock já existente de Produto/Fórmula; conserva
  permissões, CSRF, atribuição e auditoria. Standalone e reutilização passam pelo
  mesmo ramo restrito em `ResourceCreateView`, sem alterar o rebase de
  `ProductionOrder`. Inlines fazem rebase dos campos alterados e exclusão pelo dono.
- Admin da tríade: `save_model` faz rebase; `save_related` verifica o conjunto
  final depois dos reparos/inlines. Falha tardia faz rollback e reexibe formulário
  inválido, sem repetir persistência nem responder 500. Os recibos de mudanças de
  formset usados por `LogEntry` permanecem preenchidos. Exclusão individual e
  `delete_selected` englobam coleta/permissão/auditoria/gravação no gate/transação,
  não somente a chamada final de delete.
- DemoSeeder: `_upsert` dos três modelos passa pelo dono, sem `update/save_base`;
  `run_full_demo` compartilha o gate durante sua transação. Nenhuma carga demo foi
  aplicada operacionalmente; testes de carga usam somente o banco sintético.
- A verificação de componentes persistidos continua **depois** dos reparos,
  inclui linhas omitidas ou não visualizáveis e não impõe imutabilidade geral à
  fórmula aprovada. As cinco contraprovas positivas originais continuam exigidas.

### Evidência de implementação

Primeira correção: `formula-writer-green1.xml/log`, 9 passed / 1 failed; o erro era
recibo `new_objects` ausente no adaptador Admin, corrigido sem relaxar o teste.
Segunda rodada: `formula-writer-green2.xml/log`, **60 passed**, zero failures,
errors ou skips (353.431 s). Os cinco REDs originais e os cinco positivos de
validação final passaram; também houve inversão da corrida e espera real
observada com `pg_blocking_pids`, PIDs distintos e limites temporais de sessão.
Arquivos de evidência ficam em `/Users/rgnsystems/.hermes/cache/scratch/`.

Rodada ampliada final: **109 passed em 407.873 s (JUnit)**, zero failures, errors ou
skips. Evidência: `formula-writer-green4.xml` e `formula-writer-green4.log` em
`/Users/rgnsystems/.hermes/cache/scratch/`. SHA-256 do XML:
`74d9a83a61ffcf15b4631993b1dc95c8691011012fc35110e7c20aa411b731db`.
O XML RED original continua intacto, SHA-256
`e5e1878b213302a0cf0033ad42abc16535f217020ffdb2ab28b1788d5260d6eb`.

```sh
TMPDIR=/Users/rgnsystems/.hermes/cache/scratch .venv/bin/python \
  /Users/rgnsystems/.hermes/cache/scratch/run_product_workflow_tests.py \
  tests/test_product_formula_writer_concurrency.py \
  tests/test_formula_writer_protocol.py \
  tests/test_formula_final_component_validation.py \
  tests/test_product_formula_workflow.py \
  tests/test_formula_inline_components_ui.py tests/test_formulations.py \
  tests/test_demo_finance_seed_corrections.py tests/test_production_parent_omissions.py \
  --reuse-db \
  --basetemp=/Users/rgnsystems/.hermes/cache/scratch/formula-writer-green4-tmp \
  --junitxml=/Users/rgnsystems/.hermes/cache/scratch/formula-writer-green4.xml -q
```

Composição programaticamente conferida no JUnit: cinco regressões originais;
15 provas do protocolo (incluindo aliases, negativa de permissão, corrida inversa,
espera de lock observável, criação HTML concorrente standalone/Admin, mudança de
pai inválida, aprovação com reparo Admin, auditoria, bulk delete e seeder); cinco
positivos originais de validação final; 40 do workflow integrado; 30 de componentes
inline/reutilização; sete de models/API formulations; quatro de seeder financeiro
com repetição; três de omissões de ProductionOrder. O teste adicional de DELETE
protegido também teve RED real preservado em `formula-writer-delete-red.xml/log`
antes de receber tratamento 400.

`ruff check` dos 14 arquivos Python tocados: passou; `git diff --check`: passou.
As verificações específicas de endpoint foram retiradas dos testes portáveis e
colocadas no runner local, que fixa e confere engine/host/porta/nome sintético,
sem imprimir credenciais; os testes mantêm exigência PostgreSQL e PIDs distintos.
As sessões dos testes concorrentes usam lock_timeout de 4 s; nenhuma barreira
foi colocada depois da aquisição de lock enquanto se aguardava um competidor síncrono.

Isto encerra as cinco falhas no escopo aplicativo autorizado, não constitui
suíte completa, revisão independente ou aprovação de release. Permanecem fora
da garantia os escritores SQL/update/bulk que deliberadamente não passam pelo
protocolo, além do custo de serialização conservadora já descrito.
Nenhum commit/push/deploy/build foi executado.

## Diagnóstico original preservado: BLOCKED antes da correção

Base examinada: `release/2026-10-20-63af02ef`, HEAD
`d805ae54cf0bb985389d22c3d0c71f355a93cd21`, incluindo o working tree
funcionalmente aprovado. Nenhum arquivo de produção foi alterado nesta investigação.
Não houve commit, push, deploy, build nem suíte completa.

A ressalva **não pode ser encerrada** por uma alegação de que os locks do editor
integrado protegem os demais escritores. Quatro regressões concorrentes falharam
por perda de atualização ou uso de validação obsoleta; uma quinta detectou um
bloqueio sequencial do PATCH de fórmula. Os cinco testes existentes de validação
final de componentes passaram. RED não é GREEN nem aprovação de release.

## Matriz dos escritores existentes pertinentes

| Origem | Entidades / operação | Protocolo observado e limite |
| --- | --- | --- |
| `masters/ui_views.py:ProductWorkflowMixin.post` | Produto + fórmula selecionada + componentes; inclusão/alteração/exclusão de inline | Transação externa; Produto existente com `select_for_update`, depois fórmula selecionada com `select_for_update`; construção/validação posterior; gravação e auditoria atômicas. Não há token otimista para detectar dois POSTs humanos do mesmo campo. |
| `masters/related_create.py:save_related` | Cria Product/material, ou categoria; não salva o principal | Validação e transação próprias; usa salvamento genérico. Não altera fórmula/componente existentes. IDs automáticos não representam lock do agregado. |
| `base/ui/views.py:ResourceCreateView/ResourceUpdateView` + registro `formulations.formulas` | Fórmula standalone e componentes inline | Valida antes da transação de persistência; salva instâncias completas previamente carregadas. Verifica componentes finais ao aprovar, inclusive omitidos. **Não** adquire o lock comum de Produto/Fórmula antes de carregar/reaplicar mudanças. Perda de nota reproduzida. |
| Mesmo recurso genérico, `formulations.components` | CRUD standalone de componente | `ModelForm` + `save`; não compartilha lock explícito do agregado nem recarrega/revalida o pai na persistência. Exclusão usa `ResourceDeleteView`, transação e auditoria, sem protocolo de lock do agregado. |
| `formulations/ui_views.py:MasterFormulaReuseView` | Nova fórmula e novos componentes a partir de valores apresentados na UI | `prepare_object_for_save` trava o Produto destino; status forçado rascunho. Origem/valores já carregados não constituem snapshot bloqueado. `next_formula_version` é sugestão via MAX, não reserva; unicidade no banco arbitra conflito. |
| `masters/views.py:ProductViewSet` + `ProductSerializer` | REST create/update/PATCH/destroy | DRF padrão; PATCH modifica a instância antiga e faz save completo, sem reload sob lock. Perda de descrição não submetida reproduzida. DELETE não tem protocolo de agregado próprio. |
| `formulations/views.py:MasterFormulaViewSet` + serializer | REST create/update/PATCH/destroy | DRF padrão; full_clean ocorre em cópia para validação, não no estado recarregado sob lock. PATCH válido atualmente recebe 400 por falsa colisão da própria identidade. Não há validação final dos componentes equivalente à UI no save REST. |
| `formulations/views.py:FormulaComponentViewSet` + serializer | REST create/update/PATCH/destroy | Validação anterior ao save; pai pode mudar entre ambos. Inserção de material bloqueado após aprovação concorrente reproduzida. |
| `masters/admin.py:ProductAdmin` | Admin individual e ação padrão `delete_selected` | ModelAdmin padrão, sem reload/rebase/lock do agregado acrescentado. Transação do changeform não elimina instância obsoleta. |
| `formulations/admin.py:MasterFormulaAdmin` e `FormulaComponentInline` | Admin fórmula e componentes inline; exclusão individual/em massa | Transação do Admin, sem protocolo comum pré-leitura; save do formulário completo. Perda de nota não alterada reproduzida via HTTP Admin. |
| `formulations/admin.py:FormulaComponentAdmin` | Admin componente individual/em massa | ModelAdmin padrão; sem lock/revalidação final comum. |
| `governance/demo_seeders.py:DemoSeeder` | Product, MasterFormula, FormulaComponent | `run_full_demo` é atômico, mas `_upsert` usa **`QuerySet.update`** para existentes e **`save_base(force_insert=True)`** para novos. Bypassa overrides de save/clean. Este é um escritor real existente, não apenas hipótese de SQL externo. |
| ORM, bulk, fixtures e SQL externo | Qualquer uma das três entidades | `SingleInstanceModel.save` não chama full_clean; `AutoCodeMixin` apenas gera código. Não há manager que intercepte update/bulk nesta tríade. FK e constraints UNIQUE continuam vigentes; **não** impõem disponibilidade do material, vínculo temporal da aprovação ou ausência de lost update. |

As duas famílias REST são publicadas tanto em `/api/<módulo>/` quanto em
`/api/v1/<módulo>/`; usam os mesmos ViewSets/serializers. As reproduções HTTP
executaram a primeira família; o alias v1 não foi executado separadamente.
O registro e os módulos de ações foram inspecionados: não há ação dedicada de
aprovação/gravação desta tríade que substitua esses caminhos. Os demais módulos
com referências a Product/Fórmula/Componentes os consomem por FK/leitura;
nenhum serviço operacional de gravação desta tríade foi localizado nessa busca.
`reference_data/loaders.py` cataloga UoM/categorias, não as três entidades alvo.

## Provas executadas

Arquivo novo: `tests/test_product_formula_writer_concurrency.py`.

As quatro intercalações usam conexão PostgreSQL própria na thread, conferem PIDs
distintos, eventos **antes da persistência/da eventual aquisição de lock** e
fecham conexões da thread. O escritor real valida o payload; é pausado antes de
save; o segundo escritor executa o POST autenticado integrado e confirma a
mudança; só então o primeiro prossegue. Não há sleeps, respostas ORM inventadas
nem mock substituindo a persistência. Isso demonstra estado previamente carregado
obsoleto, não prova de espera/bloqueio de um protocolo que ainda inexiste.

| Teste de segurança | Observado |
| --- | --- |
| `test_product_api_patch_preserves_fields_committed_by_integrated_editor` | PATCH fiscal retorna 200 e grava NCM, mas restaura `Produto existente`, apagando descrição já confirmada no POST integrado. **RED real**. |
| `test_component_api_create_rechecks_approval_committed_by_integrated_editor` | Componente validado em fórmula rascunho retorna 201 depois do POST integrado aprovar fórmula; material permanece bloqueado. **RED real**. |
| `test_formula_form_preserves_unmodified_fields_committed_by_integrated_editor[standalone]` | POST standalone retorna 302 e grava batch_size 333, mas restaura `Nota anterior`. **RED real**. |
| Mesmo teste `[admin]` | HTTP Admin reproduz a mesma perda de campo não alterado. **RED real**. |
| `test_formula_api_patch_accepts_existing_identity` | Sem concorrência: PATCH retorna 400 por colisões Produto/Versão e Código/Versão da própria fórmula. `_instance_for_clean` atribui pk à cópia, mas deixa `_state.adding=True`. **RED real sequencial**, não evidência de concorrência. |
| `tests/test_formula_final_component_validation.py` | **5 passed**: omissão de linhas, falta de permissão, standalone, componente disponível e reparo na mesma submissão. Protegem contratos existentes, não são RED. |

Limites temporais: eventos 60/90 s; future 40 s; PostgreSQL lock_timeout 4 s e
statement_timeout 30 s. Timeouts de sessão são resetados antes do flush do Django.
A versão de diagnóstico atual está vinculada ao banco sintético dedicado; antes
de promover os testes para CI geral, mover os asserts de host/nome para o runner
de segurança (não confundir essa adaptação do harness com correção do produto).

### Comando final e evidência preservada

CWD: `/Users/rgnsystems/Documents/rgnfarmasystemv2`.

```sh
TMPDIR=/Users/rgnsystems/.hermes/cache/scratch .venv/bin/python \
  /Users/rgnsystems/.hermes/cache/scratch/run_product_workflow_tests.py \
  tests/test_product_formula_writer_concurrency.py \
  tests/test_formula_final_component_validation.py \
  --reuse-db \
  --basetemp=/Users/rgnsystems/.hermes/cache/scratch/formula-writer-red6-tmp \
  --junitxml=/Users/rgnsystems/.hermes/cache/scratch/formula-writer-red6.xml -q
```

Resultado observado: **5 failed, 5 passed, 242.37 s**, exit 1.
Log: `/Users/rgnsystems/.hermes/cache/scratch/formula-writer-red6.log`.
JUnit: `/Users/rgnsystems/.hermes/cache/scratch/formula-writer-red6.xml`.
Primeira reprodução válida de API Product/componente: `formula-writer-red5.log`
e `.xml`, **2 failed, 41.63 s**. Ambos fora do repositório.

O runner foi validado por AST sem emitir valores privados: destino sintético
exclusivo PostgreSQL `127.0.0.1:5433`, banco de teste
`test_cosmos_product_workflow_tests`, dotenv bloqueado antes dos imports da app.
Nenhum `.env`, credencial operacional ou banco operacional foi lido.
As primeiras tentativas `red1`, `red2`, `red3` e `harness4` são diagnóstico do
harness, **não** RED de concorrência: timeout curto contaminou flush; nova rodada
limpou o banco; PATCH de fórmula impediu atingir a barreira; a causa foi isolada.
Logs/XML dessas tentativas foram preservados, não sobrescritos.

## Remediação delimitada proposta ao integrador

Não colocar apenas `select_for_update` dentro de `save`: a instância já validada
continua obsoleta e sobrescreve campos. Não corrigir só o editor integrado, que
já usa locks; os quatro REDs sobreviveriam. Tampouco impor imutabilidade geral ou
reformular dezenas de módulos para encerrar esta ressalva.

1. Criar um dono de escrita restrito a Product/MasterFormula/FormulaComponent:
   transação, ordem única Produto(s) → Fórmula(s) → Componente(s), reload sob lock,
   aplicação somente dos campos intencionais (attrs REST / changed_data de forms),
   revalidação e retorno da instância atual. Definir mudança de pai e aquisição
   ordenada de ambos os agregados antes de autorizar esse caso.
2. Fazer standalone, REST e Admin (incluindo inlines/exclusões/bulk delete)
   consumirem esse dono; manter permissão, auditoria, rollback e criação relacionada.
   Corrigir a cópia de validação do serializer da fórmula com teste próprio.
3. Revalidar o conjunto persistido **depois** das alterações de componentes, sob
   o mesmo lock. Preservar o contrato positivo já comprovado de reparar material e
   aprovar no mesmo POST; validação prematura em MasterFormula.save quebraria isso.
4. Resolver explicitamente o DemoSeeder: migrar os três modelos para o dono ou
   exigir janela de manutenção verificável. Override de model.save sozinho não
   cobre `save_base`/`QuerySet.update` desse escritor existente.
5. Não chamar isso de constraint de banco. SQL externo/update/bulk irrestritos
   continuam fora de qualquer protocolo apenas aplicativo; se forem exigidos como
   escritores concorrentes suportados, a decisão é arquitetural e requer desenho
   próprio de constraints/triggers/permissões, não um patch cosmético de UI.
6. Reexecutar estes REDs como GREEN, acrescentar inversão da corrida (componente
   confirma antes da aprovação) e bloqueio observado enquanto lock está ativo,
   então os testes focados já existentes. Só declarar encerramento após todos os
   escritores suportados cumprirem o contrato escolhido.

**Decisão pendente:** escopo de retrofitting do protocolo comum entre interfaces e
política explícita do escritor de demo/bypass. Esta investigação entrega REDs e
matriz para essa decisão; não apresenta remediação parcial como ressalva fechada.
