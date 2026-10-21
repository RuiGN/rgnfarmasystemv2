# Catálogo de Templates

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

Ações de domínio usam os componentes `resource_actions.html` e
`resource_action_form.html`. O primeiro apresenta somente ações autorizadas e
compatíveis com o estado; o segundo fornece confirmação, CSRF, erros por campo
e fallback navegável sem JavaScript. O modal nunca é a única forma de concluir
uma ação.

Campos de formulário são renderizados sem ícones decorativos prefixados. Ícones
permanecem permitidos em botões, menus, alertas, indicadores e controles
interativos quando comunicam uma ação ou um estado. A configuração central de
widgets não publica `data-icon` nem metadados equivalentes de apresentação.

## Componentes operacionais reutilizáveis

`base.ui.presentation` define projeções imutáveis, e os includes sob
`templates/includes/components/` apenas apresentam essas projeções. Consultas,
permissões, normalização de estados e URLs pertencem às views, aos context
processors e aos construtores em `base.ui`; não devem migrar para Django
Templates.

| Contrato/configuração | Finalidade e entrada | Dono da autorização | Estado vazio ou fallback |
| --- | --- | --- | --- |
| `ProgressMetric` | Indicador simples ou com meta real, valor, tom, ícone, URL e texto auxiliar | View/workspace filtra por `required_permission` | “Nenhum indicador disponível” |
| `DeadlineItem` | Prazo real com descrição, data/hora, tom, ícone e URL | `build_workspace_deadlines` verifica a permissão da fonte e o escopo do usuário | “Nenhum prazo operacional encontrado.” |
| `advanced_filter_fields` | Lista permitida de choices e datas/datas-horas de um `ResourceConfig` | `ResourceListView` valida nomes, valores e parâmetros preservados | Painel omitido quando não há configuração; entrada inválida é preservada sem filtrar |
| `NotificationPreview` | Até cinco notificações recentes com criticidade, origem, momento e estado de leitura | `sidebar_menu` exige acesso ao workflow, permissão de visualização e `recipient=request.user` | “Nenhuma notificação recente.” |
| `StatusPresentation` | Rótulo original, tom e ícone produzidos por `resolve_status` | Consumidor fornece apenas valores que já pode exibir | Tom e ícone neutros para valor sem classificação |
| `AuditEntry` | Evento persistido com data/hora, ator, ação, detalhes, motivo e estado | `ResourceDetailView` consulta somente recursos com `audit_trail` declarado | “Nenhum evento de auditoria disponível para este registro.” |

Todo texto visível deve estar em português do Brasil com acentuação correta.
Cor deve vir acompanhada de texto e ícone ou descrição acessível. Exemplos
aprovados incluem “Ver detalhes”, “Filtros avançados”, “Vence hoje” e “Não há
dados suficientes para exibir este gráfico.”

O layout lateral de detalhe usa oito colunas para os dados e quatro para o
resumo somente quando `build_detail_summary` retorna identificação,
responsável, data ou estado real. Sem resumo, o conteúdo ocupa as doze colunas.
Dashboards publicam a hora real em `generated_at` e oferecem tabela textual
equivalente ao gráfico.

## Formulários genéricos com abas

`app/resource_form.html` mantém um formulário único e delega a apresentação a
`resource_form_tabs.html`, `resource_form_field.html` e
`resource_inline_formset.html`, sob `app/includes/`. A seleção de grupos vem
de `base.ui.form_layouts`, não de lógica de domínio no template.

`resource-form-tabs.js` usa o Bootstrap já carregado pelo shell; não importa
scripts de demonstração do Duralux. Somente após inicializar as abas aplica
`data-tabs-ready` e substitui a validação HTML automática por validação que
revela a seção do primeiro campo inválido. Setas, Home e End navegam entre
abas. Sem inicialização, o CSS escopado mostra todos os painéis.

O recurso sem inlines mantém o formulário simples. O padrão não converte
cockpits, quadros operacionais, páginas de detalhe ou Django Admin. Detalhes de
persistência e permissões estão no [contrato de inlines](inline-resources.md).

## Verificação mínima

```bash
TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py check

TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/pytest -q
```
