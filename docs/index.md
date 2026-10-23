# RGN Farma System

O RGN Farma System é um ERP single-instance para a indústria de cosméticos. A documentação deve
ser atualizada sempre que funcionalidades, modelos, permissões, menus,
integrações ou processos operacionais forem alterados.

## Fundação atual

- Python 3.14 e Django 6 com PostgreSQL em Docker Compose.
- Autenticação por nome de usuário em `/accounts/login/`; e-mail é contato.
- Acesso operacional por usuários, grupos e permissões nativas do Django Admin.
- Runtime operacional em `/app/` sem seleção de escopo por cliente.
- APIs REST com autenticação e permissões Django de modelo.
- Cadastros mestres, produção, PCP/MRP, compras, estoque, custos, financeiro,
  fiscal, CRM, qualidade, QA, documentos, desvios, CAPA, mudanças, auditorias,
  riscos, cosmetovigilância, recalls e treinamentos.
- Arquivos protegidos, criptografia AES-256-GCM, auditoria, workflow, relatórios,
  integrações, IA, RAG, backup e restauração.
- UI operacional baseada no design system, com shell responsivo, sidebar,
  listagens, detalhes, formulários, confirmação de exclusão, badges, filtros,
  paginação, estados vazios e relações 1-N transacionais no formulário pai.
- Catálogo HTML das 258 ações DRF, com permissões, formulários, confirmações e
  visibilidade compatível com o estado atual do registro.

## Documentos principais

- `PRD.md`
- `docs/architecture/single-instance.md`
- `docs/architecture/auth-single-instance.md`
- `docs/architecture/admin-single-instance.md`
- `docs/architecture/domain-actions.md`
- `docs/architecture/inline-resources.md`
- `docs/validation/known-pending-items.md`
- `docs/validation/single-domain-actions-acceptance.md`
- `docs/deployment.md`
- `docs/validation/evidence-catalog.yml`

## Gates operacionais

- Aceite técnico de produto: `check_product_acceptance --fail-on-error`.
- Prontidão de release: `check_release_readiness --fail-on-error`.
- Prontidão operacional: `check_operational_readiness --fail-on-error`.
- Backup e restauração: `check_backup_restore_readiness --fail-on-error`.
