# Fórmulas e Roteiros

## Arquitetura single-instance

Este módulo opera em escopo global da instalação local. O acesso é controlado
por autenticação Django e permissões nativas `view`, `add`, `change` e
`delete`, administradas no Django Admin por usuário ou grupo.

As APIs e telas operacionais não exigem cabeçalho de escopo, seleção de empresa
ou vínculo de contrato por cliente. Listagens, formulários, detalhes e ações
usam o mesmo conjunto global de dados da instância.

## Regras de implementação

- Preservar as regras de negócio da indústria de cosméticos do módulo.
- Validar relacionamentos pelo contexto funcional do domínio, não por escopo
  SaaS herdado.
- Manter trilha de auditoria, logs e justificativas quando aplicável.
- Expor menus e botões somente conforme permissões Django reais.
- Criar migrations consistentes para qualquer alteração de modelo.
- Cobrir novas regras com testes automatizados.

## APIs e UI

Endpoints REST devem usar `IsAuthenticated` e permissões Django de modelo. A UI
operacional em `/app/` deve usar o shell, cards, tabelas, formulários, badges,
modais, paginação e estados do design system.

## Formulário de fórmula mestra

Criação, edição e reaproveitamento usam o formulário compartilhado com abas:

- **Produto:** seleção de um produto já cadastrado. Não edita o cadastro mestre
  do produto nem concede permissões adicionais sobre ele.
- **Fórmula mestra:** campos da fórmula, incluindo versão, status, tamanho do
  lote, unidade, rendimento e observações, conforme as permissões existentes.
- **Componentes:** cartões de materiais com quantidade, unidade, função, perdas
  e conversão; inclusão e exclusão continuam sujeitas às regras do domínio.

Salvar envia pai e componentes juntos. Erros mantêm os valores submetidos e
abrem a aba correspondente; sem JavaScript, as seções aparecem em sequência.
Não há novos models, migrations, menus ou permissões por aba. Veja o
[contrato de inlines](inline-resources.md#edição-por-abas) e as
[evidências de validação](../validation/resource-form-tabs.md).

## Verificação mínima

```bash
TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py check

TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/pytest -q
```
