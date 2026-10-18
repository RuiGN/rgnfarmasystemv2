# IDs contextuais no ERP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Substituir `code` pelo PK textual `id` em 49 modelos de 18 apps, sem perder dados nem vínculos, mostrando o ID nos templates.

**Architecture:** Um codificador determinístico produz IDs simples ou contextuais. Duas migrações físicas PostgreSQL, com preflight e mapa antigo→novo, preenchem colunas auxiliares e convertem PK/FK; migrações de estado nos apps refletem o novo schema Django. Consumidores e rotas passam a usar o contrato textual.

**Tech Stack:** Python 3.14, Django 6, Django REST Framework, PostgreSQL 15, pytest, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-10-13-code-as-contextual-primary-key-design.md`

## Global Constraints

- Não editar migrações históricas nem tocar o trabalho não relacionado em `design_system/`.
- Não executar migração, deploy ou restart de produção. Banco com dados só após ensaio em cópia descartável, backup e aprovação separada. Na aplicação futura, bloquear escritores antes do staging e mantê-los bloqueados até cutover validado; sombras não são dual-write.
- ID global = código atual exatamente; IDs contextuais seguem a composição e o escape do spec; campos de identidade imutáveis.
- Código vazio, colisão, comprimento inválido ou referência não resolvida bloqueiam o cutover sem descarte/merge de registros.
- Não alterar campos diferentes de `code`, como `ibge_code`, `numeric_code`, `activity_code`, `reference_code` ou `status_code`.
- Não fazer commit/push sem pedido explícito do usuário; substituir passos de commit por revisão de diff e checkpoints documentados.
- Para testes com banco, usar APENAS `docker-compose.test.yml` e `TEST_DATABASE_URL` isolado, nunca credenciais de produção. Iniciar com `docker compose -f docker-compose.test.yml up -d postgres_test`; configurar a URL de teste a partir da configuração local sem registrar credenciais no plano nem nos logs. Não remover volume existente sem autorização.

## Review Focus

- Código contendo `~`, `/`, Unicode ou espaços: composição injetiva e URL round-trip sem mudar o ID global; teste `test_identity_components_roundtrip_unsafe_characters` (Task 1) e `test_string_pk_routes_roundtrip_unsafe_values` (Task 8).
- Código vazio/espaços em dados legados: preflight falha sem alterações parciais; teste `test_preflight_rejects_empty_or_whitespace_code_without_writes` (Task 2).
- FK nullable, M2M e autorreferência: cardinalidade e alvo preservados; teste `test_identity_cutover_preserves_nullable_m2m_and_self_fk` (Task 4).
- Atualização direta de campos de identidade (`QuerySet.update`): não pode deixar ID inconsistente; teste `test_persisted_identity_components_cannot_be_changed_with_queryset_update` (Task 5).
- `save(update_fields=...)` e geração antes de `full_clean()` em documentos: ID gerado persiste antes da validação; teste `test_generated_document_id_is_validated_and_persisted` (Task 5).

## Mapa de arquivos e fronteiras

- **Identidade:** criar `base/identity.py` (composição, validação, identificação de modelo), modificar `base/sequences.py` e `base/automatic_fields.py`; somente essas APIs definem IDs novos.
- **Migração física:** criar `base/migrations/support/identity_cutover.py` para preflight/mapa/cutover usando `schema_editor.connection.alias`; novas migrações `base/migrations/0003_identity_stage.py` e `base/migrations/0004_identity_cutover.py`. Registrar dependências das migrações `0003` em todos os *leaf nodes* atuais; `0004` depende de `0003`. Funções usadas por migrações devem ser versionadas/estáveis e independentes dos models atuais.
- **Estado Django:** novos arquivos de migração por app afetado, dependentes de `base.0004_identity_cutover` e da migração anterior do próprio app. Últimos números observados: ai_agents 0003, auxiliary 0005, compliance 0002, costing 0003, crm 0003, documents 0001, finance 0001, fiscal 0001, formulations 0002, governance 0003, integrations 0003, knowledge 0002, masters 0004, planning 0002, qa 0002, reports 0002, training 0002, workflow 0001. Apps adicionais com FK para modelos convertidos também precisam de migração de estado; obter a lista exata por `apps.get_models()` antes de escrever o cutover.
- **Modelos:** modificar `models.py` dos 18 apps acima, declarando `id=CharField(primary_key=True,...)` em cada classe com `code` próprio e na base abstrata `AuxiliaryCatalog` para suas 11 subclasses concretas; retirar `code`/índices/constraints obsoletos. Atualizar chamadas a `code` nos demais models consumidores.
- **Superfícies:** `base/ui/registry.py`, `base/ui/forms.py`, `base/ui/urls.py`, novo `base/ui/converters.py`, `base/admin_mixins.py`, `base/serializer_mixins.py`, views/admin/serializers/services de apps afetados e consumidores; `reference_data/loaders.py`, `auxiliary/cosmetics_seed.py`, `auxiliary/reference_snapshots.py`, `reports/catalog.py` e comandos de seed. Templates afetados concentram-se em `templates/app/*.html`.
- **Testes:** novos `tests/test_business_id.py`, `tests/test_business_id_migrations.py`, `tests/test_business_id_ui.py`; atualizar testes existentes que instanciam `code` (p.ex. `tests/test_codegen.py`, `tests/test_master_category_composite_identity.py`, `tests/test_app_ui.py`). Documentar contrato externo em `docs/` sem modificar histórico de evidência.

## Task 1: Codificador de identidade puro

**Files:** Create `base/identity.py`, `tests/test_business_id.py`; reference `masters/models.py:32-68,373-436`, `documents/models.py:143-155`, `governance/models.py:235-276`.

**Interfaces:** Produce `encode_component(value: str) -> str`, `decode_component(token: str) -> str`, `compose_id(*parts: str) -> str`, `split_id(identifier: str, expected_parts: int) -> tuple[str, ...]`, and `business_id(model_label: str, *, code: str, context: tuple[str, ...] = ()) -> str`. `business_id` uses the eight contextual model labels from the spec; global labels return `code` unchanged. Reject missing/blank components and malformed tokens; preserve case. Numeric versions are converted to their canonical string before calling `business_id`. No Django DB calls.

- [ ] Start the isolated `postgres_test` service and export `TEST_DATABASE_URL` for this shell before invoking pytest; check `core.settings.test` loads without connecting to any production service.
- [ ] Write tests `test_global_id_preserves_code`, `test_contextual_models_include_all_scope_parts`, `test_identity_components_roundtrip_unsafe_characters`, `test_blank_component_is_rejected`; assert e.g. Product `ABC` → `ABC`, MasterCategory `kind=family, code=CAT` → `family~CAT`, and distinct sample tuples yield distinct IDs.
- [ ] Run `.venv/bin/pytest tests/test_business_id.py -q` (pure tests) and record expected missing-interface failure.
- [ ] Implement only the signatures above; token: `[A-Za-z0-9._-]+` as-is, otherwise `!` + unpadded base64url UTF-8; join tokens with `~`. Context order exactly from spec. Do not normalize input.
- [ ] Re-run focused tests; review `git diff` for only identity/test files. Do not commit.

## Task 2: Preflight somente leitura e inventário completo

**Files:** Modify `base/migrations/support/identity_cutover.py` (create), add `tests/test_business_id_migrations.py`; inspect `base/models.py:36-48`, `tests/test_currency_numeric_constraint_migration.py`.

**Interfaces:** Produce `inspect_identity_cutover(apps, schema_editor) -> IdentityReport` (dataclass with `models`, `legacy_counts`, `issues`, `incoming_relations`) and `assert_identity_preconditions(report: IdentityReport) -> None`. Migration code gets historical models via `apps`, never `from masters.models import ...`.

- [ ] Confirm the `TEST_DATABASE_URL` exported in Task 1 targets only the isolated Docker service; never run cleanup commands against an existing volume.
- [ ] Write migration-state tests `test_preflight_inventories_all_49_models_and_incoming_relations`, `test_preflight_rejects_empty_or_whitespace_code_without_writes`, `test_preflight_rejects_composite_collision_or_oversize_id`, and `test_preflight_rejects_orphan_fk`; assert old rows/counts remain identical after each failure.
- [ ] Run `.venv/bin/pytest tests/test_business_id_migrations.py -q` using the exported isolated test URL; confirm missing preflight failure.
- [ ] Implement read-only preflight; enumerate concrete models through historical `apps`, list FK/OneToOne/M2M including auto-through/self, validate uniqueness on the computed ID and max lengths; report model label + old PK, never dump customer fields. Keep a frozen copy of the Task 1 codec in `identity_cutover_support.py` (not a runtime import), and assert matching vectors in tests so future runtime changes cannot alter old migrations. Do not import runtime `business_id` from a migration.
- [ ] Re-run focused tests. Review schema inventory against the spec's 49 entries; halt and correct plan/spec if runtime inventory differs.

## Task 3: Shadow IDs e relações (schema antigo ainda funciona)

**Files:** Create `base/migrations/0003_identity_stage.py`; modify `base/migrations/support/identity_cutover.py`, `tests/test_business_id_migrations.py`.

**Interfaces:** Produce `stage_business_ids(apps, schema_editor) -> None` and immutable lookup table `base_legacyidentitymap(model_label, old_pk, new_id)` with uniqueness on `(model_label, old_pk)` and `(model_label, new_id)`. Stage IDs and FK values in separate text columns; retain all old PK/FK columns and constraints.

- [ ] Write `test_shadow_stage_preserves_old_schema_and_rows` and `test_shadow_stage_populates_every_model_and_fk` using `MigrationExecutor` from historical leaf nodes to `base.0003_identity_stage`; assert sample Product, Unit, category twins, document revisions and links preserve their old numeric PK and obtain distinct new IDs.
- [ ] Run focused migration tests; verify RED at the not-yet-created migration target.
- [ ] Implement explicit dependencies on *all 18 current leaf nodes* for `0003`; preflight before any schema write; stage text columns and map in PostgreSQL inside migration transaction. Verify per-model/relationship counts. `0003` has no runtime model-state changes yet (physical shadow schema only).
- [ ] Re-run focused migration tests; examine `sqlmigrate base 0003` and `git diff --check`. Do not touch production DB.

## Task 4: Physical cutover + estado Django (um único release coerente)

**Execution gates:** 4A implements and tests only the physical cutover function under a rollback transaction on isolated PostgreSQL, without registering `base.0004`; 4B converts model declarations and directly related model methods, without touching Django migration state; 4C registers `base.0004`, all 28 app state migrations and the full integration tests. Review each gate separately. Intermediate gates are not deployable; full-suite verification is required only after 4C.

**Files:** Create `base/migrations/0004_identity_cutover.py`; modify `base/migrations/support/identity_cutover.py`; create state migrations `ai_agents/migrations/0004_business_id_state.py`, `auxiliary/migrations/0006_business_id_state.py`, `compliance/migrations/0003_business_id_state.py`, `costing/migrations/0004_business_id_state.py`, `crm/migrations/0004_business_id_state.py`, `documents/migrations/0002_business_id_state.py`, `finance/migrations/0002_business_id_state.py`, `fiscal/migrations/0002_business_id_state.py`, `formulations/migrations/0003_business_id_state.py`, `governance/migrations/0004_business_id_state.py`, `integrations/migrations/0004_business_id_state.py`, `knowledge/migrations/0003_business_id_state.py`, `masters/migrations/0005_business_id_state.py`, `planning/migrations/0003_business_id_state.py`, `qa/migrations/0003_business_id_state.py`, `reports/migrations/0003_business_id_state.py`, `training/migrations/0003_business_id_state.py`, `workflow/migrations/0002_business_id_state.py`, and state migrations for the ten additional source apps: `audits/migrations/0005_business_id_fk_state.py`, `changes/migrations/0004_business_id_fk_state.py`, `deviations/migrations/0004_business_id_fk_state.py`, `files/migrations/0004_business_id_fk_state.py`, `inventory/migrations/0003_business_id_fk_state.py`, `procurement/migrations/0004_business_id_fk_state.py`, `production/migrations/0004_business_id_fk_state.py`, `quality/migrations/0003_business_id_fk_state.py`, `recalls/migrations/0002_business_id_fk_state.py`, `risks/migrations/0003_business_id_fk_state.py`. Modify `models.py` in all 18 listed apps; add tests in `tests/test_business_id_migrations.py`.

**Interfaces:** Produce `cutover_business_ids(apps, schema_editor) -> None`. All 49 concrete models now expose CharField PK `id`, no `code`; related FK `*_id` values are strings. Leave `base_legacyidentitymap` to resolve historic external IDs. Work from PostgreSQL catalog instead of assuming FK constraint names.

- [ ] Write `test_identity_cutover_preserves_rows_and_all_incoming_fk_definitions`, `test_identity_cutover_preserves_nullable_m2m_and_self_fk`, `test_cutover_rejects_corrupt_shadow_relation`, `test_cutover_rejects_new_row_after_stage`, and `test_identity_migration_state_matches_runtime_models` with populated historical DB and `MigrationExecutor`; assert all 49 model row counts and 259 declared incoming FK/OneToOne definitions (including 75 hidden reverse accessors), then compare every populated old/new target tuple, not just counts.
- [ ] Run focused tests to verify RED (missing cutover/schema or IDs still integer).
- [ ] Implement physical cutover transaction with explicit ordered drop/recreate of dependent constraints/indexes, shadow-column rename and FK type replacement; inspect actual `sqlmigrate` SQL in PostgreSQL. Create app state migrations with `SeparateDatabaseAndState` only where the SQL has already been done, and state-only FK changes even in apps without `code`. Ensure no migration graph cycle and no shadow field in final Django state.
- [ ] Re-run focused tests on disposable PostgreSQL, including fresh empty DB and populated historical DB; run `.venv/bin/python manage.py makemigrations --check --dry-run` with isolated settings. Any inconsistency blocks subsequent tasks.
- [ ] Review every model from spec and FK manifest; inspect `git diff --check`. No commit.

## Task 5: Geração, criação e imutabilidade em todos os modelos

**Files:** Modify `base/sequences.py:65-162`, `base/automatic_fields.py`, `base/models.py`, the 18 `models.py` files above, `base/ui/forms.py:475-536`, `base/admin_mixins.py`, `base/serializer_mixins.py`; create `base/migrations/0005_identity_immutability.py` (depends on the Task 4 state migrations and installs PostgreSQL identity/scope guards); update `tests/test_codegen.py`, `tests/test_business_id.py`.

**Interfaces:** `AutoCodeMixin.save()` fills `id` before validation by generating the former leaf code and composing it with scope via Task 1; `automatic_generated_fields(model)` returns `('id', ...)` only for affected auto models. Manual-ID models accept the full ID on create; `split_id` validates that the contextual prefix matches the supplied scope/version. IDs and scope fields are immutable after insertion, including QuerySet.update (DB-level safeguard).

- [ ] Add failing tests for auto ID, manual ID, `update_fields`, document `full_clean`, same-code different context, parent move rejection and `test_persisted_identity_components_cannot_be_changed_with_queryset_update`; old expectations in `tests/test_codegen.py` become ID assertions, not duplicated `code` data.
- [ ] Run `.venv/bin/pytest tests/test_business_id.py tests/test_codegen.py -q` and verify intended RED.
- [ ] Implement generation against `id` without reusing numeric PK, reconcile old sequence namespace/highest suffix, update form/serializer/admin policy; reject updates of identity and scope at model/service and DB level. Manual IDs appear on create, immutable on update.
- [ ] Re-run focused tests and relevant existing model/form tests; note any red tests explicitly before progressing.

## Task 6: Seeds, importadores e domínio ORM

**Files:** Modify `reference_data/loaders.py`, `auxiliary/cosmetics_seed.py`, `auxiliary/reference_snapshots.py`, `reports/catalog.py`, `knowledge/services.py`, `knowledge/source_catalog.py`, `governance/demo_seeders.py`, `integrations/models.py`, `reports/services.py`, and every active `*.py` hit that resolves to one of the 49 models (`.code`, `code=`, `__code`, `fields=['code']`); leave old migration files untouched. Update `tests/test_master_category_composite_identity.py`, `tests/test_auxiliary_reference_data.py`, `tests/test_report_engine.py`.

**Interfaces:** Queries use `id` for global codes; contextual lookups compute canonical ID from the full existing tuple or search on separate context fields only where their semantics demand it. Seed reruns remain idempotent and do not merge two category kinds or document versions.

- [ ] Write failing rerun and collision tests: legacy category and canonical category with same code survive; same-code formula/doc revisions remain separate; curated report catalog still idempotent.
- [ ] Run targeted suites and verify RED after model cutover.
- [ ] Update callsites app by app, including services, selectors, seed commands, exporters, labels, audit displays and dependent models. Do not replace unrelated `*_code` fields or HTML `<code>` tags. Use repo searches to track remaining references and classify each hit.
- [ ] Re-run targeted suites and review classification manifest of every surviving `code` reference (historical migration or unrelated field only).

## Task 7: REST/admin/resource registry and manual ID creation

**Files:** Modify `base/ui/registry.py:440-1780`, `base/ui/forms.py`, `base/serializer_mixins.py`, all affected `*/admin.py`, `*/views.py`, `*/serializers.py`, and `tests/test_business_id_ui.py`, `tests/test_app_ui.py`.

**Interfaces:** Model fields/filters/searches use `id`; serializer output `id` is text; manual ID models accept ID on create; generated ID models keep it read-only on input and return it after create. `ResourceConfig` search and list fields no longer refer to removed `code`.

- [ ] Write failing tests for manual Currency/FiscalUnit creation with ID, generated Product creation, admin search, API filtering and resource lists; assert error on ID change by PATCH.
- [ ] Run focused UI/API tests and verify RED for missing `code`/missing ID create field.
- [ ] Update registry and per-app endpoint configs explicitly, maintaining other named code fields; fix form defaults that globally exclude `id` in `SYSTEM_FIELD_NAMES` for affected models only.
- [ ] Re-run UI/API tests with `core.settings.test` and review permissions, serializers and inputs.

## Task 8: Rotas e templates

**Files:** Create `base/ui/converters.py`; modify `base/ui/urls.py:41-195` and 14 affected files under `templates/app/` (audit_cockpit, controlled_document_cockpit, lot_release_cockpit, sales_order_cockpit, report_catalog, market_complaint_cockpit, report_run, resource_document_viewer, supplier_cockpit, master_formula_cockpit, quality_event_cockpit, resource_tree, production_order_cockpit, resource_gantt). Modify related URL construction in `base/ui/views.py`, `base/ui/presentation.py`, app `ui_views.py`; add `tests/test_business_id_ui.py` assertions.

**Interfaces:** `BusinessIdConverter.to_url(value: str) -> str` emits `~` + unpadded base64url of UTF-8; `to_python(token: str) -> str` returns original ID. Converted resource paths use this converter; numeric-resource paths retain `<int:pk>`. Namespacing and `reverse()` continue to work for both.

- [ ] Write `test_string_pk_routes_roundtrip_unsafe_values`, `test_numeric_resource_routes_unchanged`, `test_cockpit_routes_accept_text_ids`, `test_templates_render_id_not_code_and_not_duplicate_version`; include slash/Unicode ID, nested location and numeric unchanged.
- [ ] Run focused tests and verify RED because route or template still expects numeric `pk`/`code`.
- [ ] Implement converter and separate named/generic URL routes with model-aware dispatch; update only code-identifier template expressions to `.id`, eliminate duplicated version labels. Ensure reverse-generated links resolve back to the same record.
- [ ] Re-run focused tests, and search `templates/` for remaining `.code` expressions; classify unrelated ones explicitly.

## Task 9: Auditoria histórica, integrações e verificação final

**Files:** Create `base/legacy_identity.py` for read-only non-FK numeric reference resolution against the immutable mapping table; modify `governance/models.py`, `fiscal/models.py` only if related references need stable resolution; update relevant `tests/test_business_id_migrations.py`; create `docs/business-identity-cutover.md` with API/URL contract and backup/restore checklist. Do not edit frozen `base/migrations/support/identity_cutover.py` after Task 4.

**Interfaces:** `resolve_legacy_pk(model_label: str, old_pk: int) -> str | None` reads immutable map; no mutation of signed/hash-protected evidence. Document breaking numeric-link/API change and criteria for later production rollout.

- [ ] Write tests for resolvable legacy audit references and unchanged signed/hash evidence; run and verify RED.
- [ ] Implement only justified mapping/resolution paths; document unresolved historical references as release blockers, not guessed remaps. Re-run tests.
- [ ] Run isolated `manage.py check`, `makemigrations --check --dry-run`, migration tests on populated + fresh databases, full `.venv/bin/pytest` suite, and project lint (`.venv/bin/ruff check .` if installed). Record exact failures rather than claiming success.
- [ ] Compare initial/final row counts, all 259 declared incoming relations (including 75 hidden), no orphaned FK, ID uniqueness, diff and code/template inventory. Review `git status` to confirm pre-existing `design_system/` untouched. No commit/deploy/production migration.

## Handoff and rollback

The physical cutover requires a maintenance window in any database with data; do not treat migration reversibility as automatic. In an isolated dry run, test backup restoration rather than hand-editing data after a failed cutover. Release only after an independent review and a separate explicit production approval from Rui.
