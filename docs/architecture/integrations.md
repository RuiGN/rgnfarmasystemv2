# APIs REST e Integrações

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

## Impressão direta de etiquetas

O servidor Django envia TSPL2 diretamente pela VPN ao host cadastrado em
**Integrações → Impressora de etiquetas**, usando a porta TCP 9100 por padrão.
Somente uma configuração pode estar ativa. A conexão tem timeout de cinco
segundos e não usa fila, agente local ou Celery.

A etiqueta contém Produto, Lote, Validade e a assinatura operacional formada
pelo nome completo do usuário autenticado — com fallback para username — e
pela data/hora do servidor. A assinatura operacional identifica o solicitante,
mas não constitui assinatura eletrônica GxP. O payload não contém código de
barras, data de fabricação ou sublote.

O retorno de sucesso confirma o envio ao socket; não confirma a saída física
da etiqueta. A operação trabalha sem repetição automática. Em caso de timeout
ou resultado incerto, verifique a impressora antes de solicitar outra etiqueta.

### Interface operacional

A ação **Etiqueta** está disponível por linha em **Estoque → Lotes** para
usuários com `inventory.view_stocklot`, além do detalhe e do cockpit de
liberação de lote. A listagem calcula essa disponibilidade somente para
`StockLot`; não há impressão direta a partir de fórmulas ou produtos.
Cada botão possui seu próprio formulário e token CSRF. O controlador compartilhado
registra todos os botões e usa a URL e o token da linha selecionada, mantendo
confirmação explícita, bloqueio do botão durante o envio, feedback textual seguro
e ausência de repetição automática. Sem JavaScript, o botão não envia impressão.

### Endpoints REST

- `GET|POST /api/integrations/label-printers/` mantém as configurações;
- `POST /api/inventory/lots/{id}/print_label/` envia a etiqueta do lote;
- ambas exigem autenticação e permissões Django; chamadas de sessão exigem
  CSRF.

Regressões: `tests/test_direct_label_printing.py` cobre renderização por linha,
permissões e POST com CSRF; `tests/test_local_printing_js.py` executa os cenários
de interação em `tests/js/local-printing.test.cjs` com o runner nativo do Node.js.
Em ambientes sem Node.js, essa última verificação é explicitamente ignorada.

## Verificação mínima

```bash
TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/python manage.py check

TEST_DATABASE_URL=postgresql://rgn_test:rgn_test@127.0.0.1:5433/rgn_test DJANGO_SETTINGS_MODULE=core.settings.test .venv/bin/pytest -q
```
