# Código como ID nos modelos do ERP

## Objetivo e decisões aprovadas

Substituir o campo de negócio `code` pela chave primária textual `id` em todos os modelos concretos que hoje declaram ou herdam `code`. Onde o código é globalmente único na tabela, o novo ID é seu valor atual. Onde a unicidade depende de contexto, o ID incorpora esse contexto. Nenhum registro ou vínculo existente deve ser perdido. Templates que exibem `code` passam a exibir `id`; não ocultar o identificador. Não aplicar migrações nem fazer deploy na produção nesta tarefa.

O projeto usa Django 6/PostgreSQL. Inspeção do registro de apps identificou 49 modelos em 18 apps e 259 campos FK/OneToOne declarados apontando para esses modelos (184 aparecem em `_meta.related_objects`; 75 ocultos por `related_name='+'` ou equivalente). A implementação é uma mudança de identidade persistente e de contrato público, não uma simples substituição textual.

## Escopo dos modelos

- `auxiliary`: BusinessArea, BusinessProcess, Department, OrganizationalRole, Currency, CommercialTerm, SystemModule, SystemModel, ImpactLevel, CatalogType, CatalogValue (11, via base abstrata `AuxiliaryCatalog`).
- `masters`: UnitOfMeasure, MasterCategory, Product, BusinessPartner, Site, Warehouse, StorageLocation.
- `formulations`: MasterFormula, ManufacturingRoute.
- `planning`: MasterProductionSchedule, CapacityResource.
- `costing`: CostElement.
- `finance`: ChartOfAccount, FinancialCategory, FinancialAccount.
- `fiscal`: FiscalUnit, FiscalNCM, FiscalOperationCode, TaxSituation.
- `crm`: CustomerGroup, SalesChannel, SalesRepresentative, Campaign.
- `qa`: TrainingRequirement.
- `documents`: ControlledDocument.
- `training`: JobPosition, WorkFunction, Competency, TrainingRequirement.
- `reports`: ReportDefinition, DashboardWorkspace.
- `workflow`: ApprovalQueue.
- `integrations`: IntegrationConnector, ApiClientApplication.
- `ai_agents`: AIAgentProfile.
- `governance`: GovernanceCatalogItem.
- `compliance`: TransversalRequirementPolicy.
- `knowledge`: KnowledgeSource.

Outros campos com `code` como parte do nome (`ibge_code`, `numeric_code`, `activity_code`, `status_code` etc.) e modelos sem `code` ficam fora desta conversão. Não editar migrações históricas. Trabalho não relacionado já presente em `design_system/` permanece intocado.

## Contrato dos IDs

1. Modelos com `UniqueConstraint(code)` recebem `id=code` (valor preservado exatamente, inclusive caixa). Nos modelos com unicidade contextual, todos os IDs, não apenas os atualmente duplicados, seguem a mesma função determinística:
   - MasterCategory: `kind~code`.
   - Warehouse: `site.code~code`.
   - StorageLocation: `warehouse.site.code~warehouse.code~code`.
   - MasterFormula, ManufacturingRoute, ControlledDocument: `code~version`.
   - TaxSituation: `tax_kind~regime_kind~code`.
   - GovernanceCatalogItem: `catalog_type~module~code`.
2. Cada componente da composição é codificado de maneira injetiva e URL-safe: valores ASCII não vazios que só contenham letras, números, `.`, `_` ou `-` permanecem legíveis; os demais recebem `!` seguido de base64url sem padding de seus bytes UTF-8. Componentes são unidos por `~`, que nunca aparece nos componentes codificados. A mesma função é usada no backfill, criação, importação e testes. O comprimento máximo do campo é dimensionado pelos componentes e a expansão possível da codificação; a migração verifica tamanho e colisão antes de alterar PK/FK.
3. IDs são imutáveis após inserção. Para modelos contextuais, também são imutáveis os componentes usados na composição, inclusive o contexto ancestral de Warehouse/StorageLocation. Criar uma nova versão de documento/fórmula/rota significa novo registro/ID, preservando versões anteriores.
4. `AutoCodeMixin` e `automatic_generated_fields` passam a preencher `id` quando há `CODE_PREFIX`; namespaces de sequência antigos são reconciliados com o gerador novo para não repetir valores. Para modelos sem geração automática, criação manual/importação exige ID. `save(update_fields=...)`, `full_clean()`, formulários e admin não podem descartar um ID gerado.
5. Valores de `code` vazios, conflitos da função de composição e IDs que não caibam no schema interrompem a migração com diagnóstico por modelo e PK antiga. Não converter silenciosamente um código inválido em outro, nem sobrescrever registros. A remediação exige dados corrigidos e nova execução em cópia descartável.

## Migração de esquema e dados

1. Inventariar em Django e no banco os 49 modelos, todas as relações de entrada/saída (FK, OneToOne, M2M, autorreferências), constraints, índices e referências de PK fora das relações declaradas. Documentar as dependências entre migrações dos apps.
2. Preflight somente leitura: contar registros, checar valores vazios, unicidade final, comprimentos, referências órfãs e capacidade de resolver eventuais IDs numéricos guardados fora de FK. Nenhuma limpeza automática ou alteração em produção. Fazer backup e ensaio em cópia PostgreSQL descartável representativa antes de aplicar a qualquer banco com dados.
3. Migrações novas e ordenadas criam colunas textuais auxiliares e o mapa estável `(modelo, PK numérica antiga) -> ID novo`; preenchem IDs e FKs em lotes, inclusive relações cíclicas/autorreferentes. O mapa permanece disponível para diagnosticar referências legadas fora de FK. A reversão de uma troca de PK já efetivada exige restauração do backup testado; o mapa sozinho não é um rollback.
4. Verificar cardinalidade, bijeção, constraints e resolução de todas as FKs antes do cutover. Em qualquer banco com dados, a janela de manutenção sem escritores começa **antes** de aplicar a migração de staging e só termina depois do cutover validado; as colunas auxiliares não possuem sincronização automática com gravações posteriores. Trocar PK/FK e tipos com constraints na ordem apropriada para PostgreSQL. Usar operações explícitas de estado Django quando alterações SQL não puderem ser representadas corretamente por `AlterField`; nunca confiar em uma migração gerada automaticamente sem revisar o SQL.
5. Remover os campos `code` e seus índices/constraints obsoletos somente após validação do novo esquema e atualizar índices/ordenação/restrições para `id` ou componentes de contexto quando necessário. Preservar campos de versão e contexto por seu significado de negócio. Uma migração que falha não deve deixar conversão parcial silenciosa.
6. Logs/evidências regulatórias assinadas ou com hash não são regravados cegamente. Referências antigas fora de FK são inventariadas e, quando a semântica permitir, convertidas com o mapa; quando não permitir regravação, o mapa oferece resolução histórica sem invalidar a evidência. Divergências identificadas bloqueiam o aceite.

## Integrações e interface

- Trocar `code` por `id` em serviços, consultas ORM, filtros, searches, seeds/fixtures, importadores, exports, serializers, viewsets, formulários/admin, registro de recursos e templates; ajustar casos que usavam `code+contexto` para localizar um registro. Preservar significado de outros campos que contêm a palavra `code` no nome.
- Rotas com `<int:pk>` são revistas individualmente: só as que endereçam modelos convertidos passam a aceitar PK textual; as demais permanecem numéricas. Para não depender dos caracteres presentes em IDs antigos, registrar um conversor de URL para esses recursos: representa o ID como `~` seguido de base64url sem padding, decodifica para o valor original e o codifica em `reverse()`. O prefixo e o alfabeto não colidem com rotas de IDs numéricos ou `new`/`edit`; IDs mostrados na interface continuam legíveis. Rotas genéricas precisam discriminar recursos convertidos de recursos numéricos pelo registro de modelos, não pela aparência do valor. Testar a ida e volta inclusive com barras, Unicode e componentes contextuais.
- Exibir o novo `id` no lugar do código, evitando sufixar a versão duas vezes se ela já compõe o ID. A representação textual e os campos de pesquisa devem continuar úteis. A mudança de PK/URLs/APIs é incompatível com clientes que enviam IDs numéricos antigos ou o campo `code`; documentar o cutover e a necessidade de atualização desses clientes. Não presumir compatibilidade automática de links antigos.

## Testes e critérios de aceite

- TDD: testes falhando antes de mudar comportamento, cobrindo `code` global, códigos repetidos em escopos distintos, escape da composição, geração automática/manual, imutabilidade de ID/contexto, versões, formulário/admin/API, rotas, templates e registros com dados inválidos.
- Migrações exercitadas em PostgreSQL descartável com dados previamente populados, cobrindo todos os modelos afetados, relações cruzadas, M2M, ciclos, autorreferências, colisões e rollback/recuperação documentados; comparar contagem e resolução de relações antes/depois. Banco novo isolado não comprova preservação de dados.
- Executar `makemigrations --check --dry-run`, `check`, testes relevantes e suíte completa configurada por `pytest.ini` com `TEST_DATABASE_URL` isolado; registrar falhas com seus nomes. Conferir no diff que não restam usos de `code` dos 49 modelos em código ativo/templates, nem rotas numéricas para seus recursos.
- Produção só poderá receber migração posteriormente, mediante backup verificável, ensaio no snapshot, janela sem escritores, revisão independente e aprovação explícita. Esta especificação não autoriza deploy, restart ou migração do banco de produção.
