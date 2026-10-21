# Correções P1 — integridade e autorização

## Escopo

Correções locais sobre `d8b179c77787806f463d1d637a526bbdf0436d22`, sem commit,
push ou deploy. O escopo autorizado compreende quatro P1: exclusão genérica de
saldos, gravação obsoleta de ordens de produção, troca do produto de um lote e
permissão inadequada para ações de coleção. Não inclui os demais P2 da análise.

## Proteções implementadas

1. **Retenção de saldo:** `inventory.stockbalance` integra a política central
   por model. API legada/v1, recurso HTML e seus inlines e Django Admin negam
   DELETE genérico, inclusive para superusuários. Não muda o acesso a todos os
   demais models do app nem impede rotinas internas revisadas de usar o ORM.
2. **PATCH de OP:** o serializer recarrega a ordem sob lock na transação,
   reaplica campos enviados, revalida e salva apenas esses campos e o timestamp.
   Preserva estado, rendimento e autoria de transições realizadas após a leitura
   inicial, além dos metadados não enviados. A resposta usa a instância atual.
3. **Identidade de lote:** o produto é imutável após a criação, antes mesmo do
   primeiro movimento, evitando uma política dependente de uma consulta de uso
   sujeita a corrida. API, formulário, Admin, clean e save protegem esse campo.
   Nenhum saneamento de dados históricos ou trigger de banco foi adicionado.
4. **Ações de coleção:** actions adicionais usam change por padrão. As ações
   exclusivamente criadoras têm mapa explícito de add, compartilhado pela
   descoberta HTML. A avaliação de compliance exige add e change porque faz
   update_or_create. Não há concessão automática de permissões a grupos.

Sem alteração de schema; `makemigrations --check --dry-run` não detectou mudanças.
O comando local emitiu aviso de histórico porque o nome-base sintético do runner
não existe; as execuções PostgreSQL usaram seu banco de teste dedicado.

## Testes e revisão

- Testes novos em `tests/test_p1_stock_balance_retention.py`,
  `tests/test_p1_production_stale_updates.py`,
  `tests/test_p1_stock_lot_identity.py` e
  `tests/test_p1_collection_permissions.py`.
- RED observado antes da implementação de cada P1: exclusão 4 falhas,
  produção 6 falhas, lote 7 falhas e permissões 5 falhas. Os controles positivos
  existentes no lote/permissões permaneceram verdes.
- GREEN: **30 novos casos aprovados**, incluindo duas conexões PostgreSQL reais
  para PATCH/conclusão, API legada/v1, UI, Admin e permissões mínimas.
- Seleção final dos quatro arquivos novos mais `tests/test_master_data.py`:
  **40 aprovados**. O teste legado de criação de fluxo de caixa foi ajustado
  para utilizar o mapa real do CashFlowEntryViewSet, sem restabelecer o padrão
  inseguro de add para qualquer action de coleção.
- Regressões de integração de permissões e módulos relacionados: **88 aprovados**
  na execução direcionada anterior. Essa contagem se sobrepõe a outros grupos;
  não deve ser somada aos totais acima.
- Django check, OpenAPI e Ruff dos arquivos alterados: aprovados.
- MyPy dos módulos envolvidos: 145 fontes, sem erros, apontando
  `--python-executable .venv/bin/python`. A tentativa de escopo global encontrou
  três erros de stubs PyYAML ausentes no ambiente local; não foi declarada verde.
- Revisão auxiliar somente leitura: sem achados, confiança média. Não executou
  os testes independentemente. A concorrência de edições dos próprios cadastros
  relacionados, especialmente relações enviadas no PATCH, continua fora da
  cobertura demonstrada por esse parecer; não houve teste de carga ou deploy.

## Resultado da suíte completa e comparação de base

A suíte completa terminou, antes do ajuste do teste legado, com:

- **2.534 testes aprovados e 26 falhas**, zero erros e zero skips;
- **42 subtestes aprovados**;
- 2.560 casos serializados no JUnit, mais 42 subtestes, reconciliando os 2.602
  declarados no atributo tests;
- cobertura bruta reportada de **57,92%**, abaixo da meta de 80%.

A execução utilizou um runner local que inicializa Django antes do início da
medição do pytest-cov. Isso limita a interpretação da cobertura, particularmente
para código importado nessa inicialização; o número não é certificação do gate
oficial. Ferramentas locais reaproveitadas também diferem dos pins de dev.

As falhas foram reproduzidas seletivamente em uma worktree detached intacta do
commit-base, sem copiar credenciais locais: 24 falharam também na base e o teste
legado de permissão passou. A worktree foi removida após a comparação.

Depois do ajuste do teste legado, a repetição dos 26 casos inicialmente
reprovados terminou com **25 falhas e 1 aprovação**:

- 24 falhas reproduzidas no commit-base: contratos da UI/layout, scripts de
  backup/deploy, referência documental antiga e expectativas de ignore;
- 1 falha ambiental: o teste de higiene aponta `.env` local com modo `0644`.
  O conteúdo não foi lido nem alterado. A verificação dessa condição não foi
  repetida na worktree-base porque ela intencionalmente não possui credenciais
  locais. Corrigir permissões do arquivo exige uma ação operacional separada.

Não se declarou uma nova execução completa verde após a alteração de fixture.
Nenhuma falha remanescente do replay corresponde aos quatro P1 corrigidos.

## Limites e aceite

**Aceite técnico restrito aos quatro P1:** implementados, regressões relevantes
aprovadas e revisão estática sem bloqueadores. As interfaces foram exercitadas
por clientes HTTP de teste; não foi feita inspeção visual em navegador.

**Release geral: não aprovada.** Persistem as falhas da base/ambiente, cobertura
não validada no ambiente pinado, itens P2 fora deste escopo e aprovações
operacionais/regulatórias externas. Os resultados não equivalem a CI remoto,
homologação GxP, saneamento histórico ou implantação.

Os testes utilizaram apenas PostgreSQL isolado na porta de testes e mídia
sintética temporária. A mídia foi limpa pelo runner. O banco dedicado de
pytest foi mantido por `--reuse-db` para permitir repetição local; não é banco
operacional nem contém cópia de dados reais.

## Reprodução

No ambiente de desenvolvimento com dependências de `requirements-dev.txt`:

```bash
bash scripts/test.sh tests/test_p1_stock_balance_retention.py tests/test_p1_production_stale_updates.py tests/test_p1_stock_lot_identity.py tests/test_p1_collection_permissions.py tests/test_master_data.py -q
```

Evidências locais desta execução estão em
`/Users/rgnsystems/.hermes/cache/scratch/`: `p1-regressions-green.xml`,
`p1-final-directed.xml`, `p1-full-suite.xml`, `p1-baseline-failures.xml`,
`p1-postfix-failures.xml`, `p1-coverage.xml`, `p1-independent-review.json` e
`p1-verification-manifest.json`. São arquivos temporários sujeitos a limpeza;
para release formal, recapturar no ambiente pinado e guardar junto ao SHA e à
imagem efetivamente candidatos.
