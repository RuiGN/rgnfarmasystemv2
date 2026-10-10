# Conclusão das correções — candidato v3

## Resultado de validação

Candidato aprovado para aplicação das fontes ao projeto, sem autorização ou execução de deploy. Os registros em `corrections-evidence.md` descrevem as etapas históricas; os bloqueios dos candidatos anteriores não representam o estado final do v3.

| Gate | Resultado |
|---|---|
| Suíte completa em PostgreSQL isolado | 2.212 testes + 42 subtestes aprovados; zero falhas, erros e skips |
| Cobertura | 85,78% — 24.580/28.654 linhas; mínimo exigido 80% |
| Ruff e formatação | Aprovados; 528 arquivos formatados |
| MyPy | Sem erros em 385 arquivos de fonte |
| Bandit e diff-check | Aprovados |
| Auditoria de dependências | 98 dependências listadas, zero vulnerabilidades conhecidas |
| Build Docker sem cache / pip check | Aprovados, Python 3.14.7; 98 pins instalados sem divergência |
| Fontes congeladas | 2.074 hashes sem divergência |
| Oito gates Django/migrations/OpenAPI/evidência/prontidão | Aprovados integralmente na repetição |
| Perfil production sintético | Zero issues, zero silenced; não valida configuração real |
| Revisão independente final de fuso | Aprovada; repetição de 118 testes + 12 subtestes |

O primeiro processo dos gates administrativos foi encerrado com código -15 antes de concluir. Não foi aceito como sucesso. A repetição integral concluiu com código 0.

## Correções entregues

- Proteções financeiras: transições públicas, conservação de saldos/ledger, campos econômicos protegidos e tratamento de rejeições nos formulários.
- Estoque/compras/produção: campos controlados protegidos, recebimentos sob lock, seleção explícita de saldo, cancelamento e JSON inválido rejeitado com HTTP 400.
- Autorização e privacidade: ações HTML/API, arquivos e conectores fiscais; testes negativos e controles positivos.
- Demo financeiro: idempotência após baixa/estorno e ordem de locks título→conta em toda a transação externa; concorrência PostgreSQL real.
- Relatórios: fixtures/preparos usam os métodos públicos; 528 assertions e 154 definições de teste preservadas.
- Readiness/deploy e dependências: limites de sondagem, rollback e reprodução do runtime.
- Prazos: timestamp aware convertido ao fuso ativo antes de extrair a data; date/naive e calendário local preservados.

## Identidade e evidências

- Imagem: `rgnfarmasystem:corrections-final-v3`.
- ID: `sha256:9b2e59fe879785834ec98b9f4e6656239b67e6feb49efa7abdbcf0e4487d86c3`.
- Manifest de fontes: `evidence/corrections/v3-source-manifest.json`.
- Reconciliação/testes/imagem: `evidence/corrections/v3-final-verification.json`.
- JUnit: `evidence/corrections/v3-suite-junit.xml` — total declarado 2.254; 2.212 elementos testcase e 42 subtestes.
- Cobertura: `evidence/corrections/v3-coverage.xml`.
- OpenAPI: `evidence/corrections/v3-openapi.yml`.
- Auditoria: `evidence/corrections/v3-pip-audit.json`.
- Aplicação e backup: `evidence/corrections/v3-application-verification.json`, produzido após aplicação.

Saídas posteriores ao congelamento são evidências geradas e têm hashes separados; não se alega identidade byte a byte de toda a árvore ou que o relatório final estivesse na imagem testada. A imagem exclui intencionalmente `.env.development.example` pelas regras existentes do Docker; não houve divergência nos demais arquivos manifestados presentes.

## Limites e pendências operacionais

- Não foram executados commit, push, deploy, migrations em produção ou restart de serviços operacionais.
- Não foram lidos/copied arquivos de ambiente real nem dados de negócio. A configuração production foi somente sintética.
- O PostgreSQL de testes usa dados descartáveis e ajustes de flush exclusivos do harness; os testes comprovam locks/atomicidade, não durabilidade física ou recuperação de energia.
- A auditoria usa `--strict --no-deps --disable-pip` sobre requirements.txt; não equivale a um lock completo com hashes.
- Antes de deploy: validar configuração real, backup/restore real, saúde das dependências e do túnel, disponibilidade da porta de métricas configurada e smoke externo. Esses itens exigem escopo operacional próprio.
- Candidatos anteriores reprovados e seus resultados permanecem preservados.
