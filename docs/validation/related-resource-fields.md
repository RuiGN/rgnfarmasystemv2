# Selects relacionados nos recursos HTML

## Contrato de integração

`base.ui.related_fields.configure_related_fields(form)` deve ser chamado **ao final de `__init__`**, depois das restrições da queryset, campos removidos, `disabled` e widgets personalizados. Não adicionar campos a partir do modelo nem trocar querysets autorizadas por `.objects.all()`.

`validate_related_fields(form, cleaned_data)` deve ser chamado no `clean()` depois de `super().clean()`. Acrescenta erros no FK dependente; não salva, não elimina validações do domínio nem substitui permissões de ação/formset. Os builders de recursos, ações e inlines contêm ambos os hooks. A configuração de inline ocorre depois das restrições de campos/imutabilidade/ator. O contexto de pai oculto continua sendo um ponto de integração separado, descrito abaixo.

```python
from base.ui.related_fields import configure_related_fields, validate_related_fields

# __init__, após as regras existentes:
configure_related_fields(self)

# clean:
cleaned = super().clean()
validate_related_fields(self, cleaned)
return cleaned
```

Carregar `static/js/related-fields.js` no shell compartilhado, após o DOM estar disponível ou com `defer`. Sem JavaScript, os selects continuam nativos: combinações incompatíveis são recusadas no POST. Não existem endpoints novos.

### Prefixos e linhas dinâmicas

O JSON `data-related-rules` usa `form.add_prefix()`. A clonagem do `empty_form` deve substituir **todas** as ocorrências de `__prefix__` no HTML (incluindo atributos JSON), não apenas `name`/`id`. Os templates de inline existentes usam `<template>` e `replaceAll`, compatíveis com o contrato. O script observa novos nós, aplica filtros na inicialização e em mudanças, limpa valor incompatível e emite `change` com propagação para cascatas. Não recria opções removidas nem reautoriza opções inicialmente desabilitadas.

O helper é idempotente por instância. Não chamar antes de terminar as restrições de autorização para depois tentar configurar novamente. Widgets ocultos, controles desabilitados e campos ausentes não são restaurados.

## Regras explicitamente sustentadas

- `MasterCategory.kind → parent`: famílias, grupos e categorias podem apontar entre esses três tipos, preservando a hierarquia histórica sem inventar uma ordenação estrita. O teste `test_master_category_composite_identity.py` exige categoria filha de família; o catálogo oficial possui famílias e grupos separados das classificações. Demais tipos aceitam pai do próprio tipo. Pai e tipo históricos incompatíveis podem permanecer **somente no vínculo já existente e no tipo original**, desde que autorizados e sem ciclo. Novos vínculos incompatíveis são recusados.
- Em edição de categoria, excluir o próprio registro e todos os descendentes, mesmo atravessando nós fora da queryset autorizada. O grafo é consultado em uma única query somente para excluir IDs; IDs ocultos não são enviados ao HTML.
- Os quatro FKs de classificação de `Product` usam o `kind` exigido por `Product._validate_category`: categoria, linha, forma e área de aplicação.
- País → estado → cidade usa os campos normalizados do mesmo grupo (`shipping_*`, `delivery_*`, `venue_*`, `event_*`, etc.), além dos nomes nativos `country/state/city` quando esses são ModelChoiceFields dos modelos exatos.
- `site → warehouse → location`, somente com os controladores e modelos explícitos.
- `product → formula`, `product → route` e `formula → route`: roteiro com `formula=None` continua genérico e válido. `copied_from` não recebe essa restrição: sua origem pode ter outro produto; o modelo não proíbe isso.
- `order → order_item`, `receipt.order → order_item` e `receipt → receipt_item` quando os dois selects correspondentes existem. O cruzamento por receipt usa apenas os recebimentos já autorizados.
- `catalog_type → CatalogValue` quando um formulário contém ambos os selects; o próprio cadastro de CatalogValue só possui `catalog_type` e seu valor textual, não precisa de um segundo filtro.
- `payment_term_ref` e `delivery_term_ref` selecionam os `CommercialTerm.term_type` corretos. Textos comerciais, moedas, referências e demais legados continuam visíveis e persistidos como antes.

O helper de dependências usa `field.queryset.model`, inclusive em `forms.Form` das ações. As especializações de `Product` e `MasterCategory` exigem `ModelForm._meta.model`, evitando aplicar uma taxonomia por semelhança de nome em ações de outros domínios. `to_field_name` é respeitado pelas regras de FK.

### Extensão comprovada F2–F6 (revisão dos candidatos de `model.clean`)

`MODEL_DEPENDENCIES` é uma allowlist por **modelo proprietário**, campo, caminho do dependente e caminho do controlador. Não deduz vínculos por nome/alvo coincidente. Os 59 candidatos editáveis deduplicados do parecer estão congelados em `tests/test_proven_related_candidates.py`; cada um exige regra direta ou igualdade inversa explícita. O teste também percorre criação, edição e `empty_form` reais da registry sem permissão de banco, não somente ModelForms sintéticos.

- **Compras:** item do pedido → produto recebido; item da requisição → produto do pedido; sugestão MRP → produto requisitado. A igualdade inversa usa `path='pk'` e `controller_path='product'`, sem ciclos de selects que limpam um ao outro. As unidades permanecem livres para os contratos de conversão do domínio; nenhuma igualdade de UOM foi acrescentada.
- **Produção:** `order.formula → component.formula`, `component.material → material` e `material → stock_lot.product`. O hook pós-injeção troca `order.formula` pelo `formula` do formulário pai real, com prefixo e validação pelo objeto limpo. Também estão comprovados `order.product → ProductionOutput.product`, `order.route → route_step.route` e `order → operation_execution.order` em apontamentos de mão de obra. Para identidade de pai oculto, o hidden serve somente para localizar o controlador no DOM: no servidor a identidade vem de `parent_form.instance`; a validação original do `InlineForeignKeyField` continua rejeitando um ID forjado.
- **QC:** `sample.product → specification.product` e `analysis.sample.product → specification.product`; amostras diferentes do mesmo produto continuam compatíveis. Não se acrescenta `specification` a inlines que não o renderizam. Amostra/especificação, documento/amostra e investigação/análise/resultado também usam suas igualdades explícitas.
- **Lote/produto:** saldo, avaliação de estoque de mudança, reclamação CRM, evento de desvio, especificação/amostra/documento QC, liberação/bloqueio QA, reclamação de mercado, devolução e campanha de recall. Não se filtram genealogia, lote de entrada/saída, cópias ou origem pela simples coincidência de modelos.
- **Fiscal, treinamento, auditoria, CAPA e CRM:** recebimento/pedido fiscal, item/documento fiscal, situação/regra tributária por enum `tax_kind`, turma/requisito, função/cargo, checklist/auditoria, ação/aprovação/eficácia da CAPA, contato/oportunidade/proposta/contrato/pedido por cliente e vínculos comprovados de reclamações/recall. A função com cargo nulo permanece genérica, como exige `clean()`.
- **QA:** documento/lote/produto e revisão/lote usam relações estritas; referências nulas de documento/ordem na revisão QA continuam genéricas. A origem da OP na liberação de lote é **comprovada nesse domínio**, não uma regra global de genealogia: a direção de UX é lote → OP, impedindo que selecionar uma OP opcional torne obrigatório um lote com origem.

`ALLOW_EMPTY_CONTROLLERS` conserva os casos em que `clean()` compara somente se ambos os objetos opcionais existem. O mapa contém `''` nesses casos; `'*'` representa somente a ausência genérica comprovada no objeto dependente. Isso evita transformar filtros em novas obrigatoriedades. Mapas diretos usam subconsulta autorizada na mesma query SQL; mapas inversos/indiretos agrupam somente os controladores autorizados. IDs de controladores fora da queryset não são enviados no JSON. Querysets originais e suas exclusões permanecem intactas; `select_related` cobre os rótulos explicitamente desreferenciados (incluindo componente/fórmula/material), sem N+1.

O protocolo JSON/JavaScript permanece `controller` + `values`, sem endpoints novos. No dicionário privado de regras, `path` continua obrigatório e foi acrescentado `controller_path`; `controller_form` identifica o escopo pai. Regras de identidade do pai possuem também `controller_instance`, nunca serializado para HTML. O inventário deve preservar esses escopos/caminhos ao descrever inversas e controladores indiretos.

As ações atuais não contêm pares novos aplicáveis da allowlist por proprietário: um teste percorre `ActionConfig.fields` e falha se surgir um par sem binding explícito do proprietário. Não se aplica uma regra de ModelForm a uma ação arbitrária somente por conter campos homônimos. Os hooks e as regras comuns de ações existentes continuam exercitados pelas regressões.

**Omissão de registros operacionais corrigida no salvamento HTML:** a integração do pai no inline não substitui revalidar todos os filhos persistidos quando muda o pai. `test_production_parent_omissions.py` reproduziu OP mudando de fórmula com consumos incompatíveis omitidos por `TOTAL_FORMS=0` (302 e readback incompatível). Foram reproduzidos também os casos irmãos: mudança do roteiro deixando operações ligadas ao roteiro anterior e mudança do produto deixando resultados do produto anterior. Após salvar as linhas, `base/ui/views.py` consulta os três conjuntos persistidos, inclusive registros omitidos/não visíveis, ainda na transação e sob o lock da OP compartilhado pelos escritores operacionais. Componente não nulo deve pertencer à fórmula final, etapa não nula ao roteiro final e resultado ao produto final; inconsistência gera erro no controlador correspondente e rollback de pai/filhos/auditoria. O recorte inicial passou com 125 testes; o recorte posterior com os três casos HTTP e regressões de cockpit/stale updates passou com 19 testes. São conjuntos sobrepostos, não somar. A allowlist não altera `models.clean`; o controle HTML não é uma constraint de banco nem um reparo da API/Admin.

## Segurança, desempenho e fronteiras

- Nenhuma regra expande o conjunto de linhas de uma queryset. O POST usa ModelChoiceField mais o mapa calculado pelo servidor; o JSON do cliente nunca é lido para autorização/validação.
- Metadados usam `values_list` com joins e avaliação preguiçosa no primeiro render/validação: uma consulta por dependência, sem consulta por opção. A construção de um formulário novo não avalia as escolhas (o grafo para exclusão de ciclos em edição é a exceção explícita). Os caminhos provados são carregados com `select_related` para evitar N+1 em rótulos como `MasterFormula.__str__`. Não se trata de uma auditoria de desempenho de todos os rótulos do sistema.
- O objeto autorizado incompatível permanece disponível ao `ModelForm._post_clean()` para que modelos que desreferenciam FKs obrigatórias não retornem 500. O erro de campo permanece; `is_valid()` e `save()` recusam o formulário. A validação do modelo continua sendo executada.
- Em linhas marcadas para remoção, a validação adicional não interfere; as permissões e regras de exclusão originais continuam donas da operação.
- As regras são da interface HTML. Não estabelecem uma constraint de banco, não corrigem a API/Admin e não resolvem corrida concorrente ao editar hierarquias. `MasterCategory.clean()` originalmente não impõe a hierarquia; eventual proteção universal precisa de alteração de domínio separada e aprovada.

## Exclusões e lacunas explícitas

1. **Hooks básicos de ações e inlines integrados** em `base/ui/actions/forms.py` e `base/ui/views.py`: uma nova rodada independente executou **19 testes Python**, incluindo as regras relacionais e os hooks reais, sem falhas. Os **6 testes Node** também passaram novamente. O asset está em `templates/base.html`. Isso não encerra o contexto de pai oculto nem substitui a nova rodada browser; não houve prova HTTP de todos os formulários.
2. Pai de inline oculto/injetado pelo Django não é inventado nem tratado como select editável. `RelatedInlineFormSet.add_fields()` agora instala o contexto depois da injeção do Django: `configure_inline_parent_fields()` liga `order_item` ao `order` do formulário pai real, com seu prefixo. O servidor compara com o objeto em `parent_form.cleaned_data`, não com o hidden recebido. A gravação revalida todos os itens persistidos dentro da transação, incluindo linhas omitidas por management form forjado; falhas revertem pai/filhos/auditoria. O FK `receipt` permanece oculto e a sua validação original é preservada. Testes HTTP cobrem mudança do pedido, item incompatível, hidden forjado e omissão de linhas; navegador comprovou limpeza e filtro de novas linhas, com gravação e readback SQL.
3. Nenhum campo textual/regulatório foi deletado/ocultado automaticamente. A presença de `currency_ref`, `payment_term_ref`, `area_ref`, `source_model_ref` etc. não prova sincronização bidirecional nem permite eliminar seu texto legado. O inventário registra os pares individualmente.
4. Mesmo modelo-alvo em dois campos não prova dependência. Origens, substitutos, genealogia, ligações polimórficas, evidências, cópias e hierarquias de outros domínios não recebem filtros inferidos. O inventário inclui candidatos relacionais com a razão da exclusão; isso é inventário de lacunas, não promessa de cobertura funcional dessas regras.
5. A rodada local `browser-integrated-round3` observou Categorias, Produtos, Fórmulas e Recebimentos em 320/768/1024/1440 px, com 57 capturas únicas e hashes conferidos; não é prova HTTP/browser de cada recurso. O ator foi injetado por middleware exclusivo da fixture local, não por login E2E. A fonte foi conferida sem drift no encerramento; os guardas posteriores de dados incompletos de recebimento exigem verificação própria e não tornam essas capturas automaticamente atuais. Node continua sendo DOM sintético, separado dessa evidência.
6. Não há migrations nem alteração de dados históricos, nem endpoints/permissões/menus novos.

## Inventário reproduzível e evidências

`tests/test_related_field_inventory.py` percorre todos os recursos da registry nas variantes criação/edição, todos os `empty_form` de inlines com seus management forms e todas as ações da registry. Grava um JSON por campo, tipo Django/widget/modelo-alvo, status, dependência suportada, candidatos excluídos e pares normalizados redundantes; verifica contagem e unicidade por código. Recursos read-only são inventariados como definição, não apresentados como tela editável observada.

Artefato: `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/related-input-inventory.json`.

Runner isolado: `/Users/rgnsystems/.hermes/cache/scratch/run_related_fields_tests.py`, cópia do runner da tarefa com somente o nome do banco alterado para `cosmos_related_fields_tests`; `environ.Env.read_env` é bloqueado antes dos imports. Nunca aponta ao banco operacional.

```sh
PYTHONPATH=/Users/rgnsystems/.hermes/cache/scratch/release-test-bootstrap \
TMPDIR=/Users/rgnsystems/.hermes/cache/scratch \
.venv/bin/python /Users/rgnsystems/.hermes/cache/scratch/run_related_fields_tests.py \
  tests/test_related_resource_fields.py tests/test_related_field_inventory.py \
  --reuse-db --basetemp=/Users/rgnsystems/.hermes/cache/scratch/related-verification \
  --junitxml=/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/related-verification.xml -q
node --test tests/js/related-fields.test.cjs
```

Os XMLs `related-red-1`, `related-red-2`, `related-red-copy`, `related-red-postclean` e `related-red-nplusone` preservam falhas observadas antes das respectivas correções. O RED de N+1 demonstrou cinco consultas para quatro fórmulas; o GREEN exige uma consulta para seus rótulos. Saídas Node RED também são preservadas junto aos artefatos. O handoff JSON relaciona resultados reais e pendências; passagem local não significa aprovação regulatória, CI, merge ou deploy.

### Verificação integrada após F2–F6 e revalidação dos filhos omitidos

- Execução única de **42 arquivos**: **1.122 testes e 7 subtestes passaram**, sem falhas, erros ou skips (708,37 s). O JUnit declara 1.129 execuções e contém 1.122 nós principais; subtestes não são testes principais adicionais.
- XML: `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/final-integrated-42.xml`. O recibo `final-integrated-test-observation-1792541715084121000.json`, no mesmo diretório, confere contagens, os 42 arquivos e os hashes. Não somar este conjunto às regressões sobrepostas de 881/603/597/125/19 casos.
- Nenhuma divergência de fonte de execução em relação ao checkpoint `378bb1aa01f0bc4df5968c02be8cda4a5c6644918be95a7d0c42971737921e36` capturado durante a rodada. Uma parametrização positiva temporária do teste de omissão foi revertida durante a execução; os bytes finais foram restaurados. Portanto, não se afirma imutabilidade contínua dos arquivos de teste desde o despacho.
- Ruff, formato, `git diff --check`, Mypy de seis fontes e oito testes Node passaram. Node verifica DOM sintético; não substitui o navegador real.
- QA atualizado no navegador foi executado e reconciliado separadamente, conforme seção seguinte. As 57 capturas da rodada 3 permanecem históricas, sem promoção automática à revisão atual. O recorte de 42 arquivos não é a suíte inteira, não mede a cobertura global e não substitui CI ou aprovação de release. Sem novo commit, push ou deploy.

### QA funcional atual no navegador

Evidências em `/Users/rgnsystems/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/browser-integrated-final-20261021T000223004911Z/`; `handoff.json` contém o escopo e `artifact-sha256.json` os hashes. A integração conferiu novamente os **94 hashes**, as **75 capturas com caminhos únicos**, os **176 arquivos de fonte** e as **73 observações**.

- **28 combinações**: sete rotas (Categorias, Produtos, Fórmulas, Recebimentos, OP, Análises QC e Tributos) em 320/768/1024/1440 px. Interações completas em 320/1440; 768/1024 verificam renderização inicial, não todos os fluxos.
- Verificados Tipo → pai (incluindo Categoria → Família), pedido → item → produto distinto, fórmula da OP → componente → material → lote com novas linhas, amostra → especificação e enum tributário → regra. Confirmadas três abas Produto, duas Fórmula e quatro campos do material rápido.
- **53 checks positivos e dois negativos de expectativa excessiva preservados**, não apagados nem reescritos como positivos. Componente opcional vazio pode manter material/lote compatíveis, conforme `MaterialConsumption.clean()` e `test_optional_component_and_requisition_controller_do_not_require_a_selection`. Checks adicionais comprovaram limpeza real ao selecionar componente incompatível.
- POST QC com CSRF real retornou 302; readbacks PostgreSQL e da edição confirmaram uma análise sintética criada com a amostra/especificação escolhidas. A fixture foi encerrada e seus dados são descartáveis; não há promessa de que o registro permaneça no banco após teardown.
- Coletores presentes, sem erros/avisos/falhas de recursos da aplicação nas observações; sem overflow horizontal do documento. Controles fora da área visível foram mantidos na métrica e classificados como sidebar fechada ou tabela responsiva. Acesso horizontal por foco/scroll foi observado; isso não é auditoria completa de acessibilidade. A integração inspecionou também as capturas móveis de Produtos e OP: esta última mantém tabela com rolagem horizontal, não uma página inteiramente sem conteúdo fora da tela.
- Fonte inicial/final coincide com `378bb1aa01f0bc4df5968c02be8cda4a5c6644918be95a7d0c42971737921e36`; servidor/Chrome exclusivos encerrados e portas 61778/61835 conferidas fechadas pelo integrador.

**Limites:** ator sintético injetado localmente, não login real. Seleções usaram valor + eventos DOM contra os assets reais; teclado nativo de selects não foi validado. Tentativas/falhas do harness e cinco avisos de markers desconhecidos na fixture externa foram preservados; não são avisos do console da aplicação. O Chrome registrou diagnóstico GCM em background: navegações/assets da aplicação ficaram em loopback, mas isolamento externo absoluto do processo não foi comprovado. Não se promove esta amostra à matriz completa dos 48 formulários, à suíte global, ao CI ou à aprovação de release.
