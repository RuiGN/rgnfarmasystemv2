# Correção do gate de segredos — 2026-10-20

## Escopo e diagnóstico observado

Autorização: investigar e corrigir o CI sem enfraquecer a política de segurança.
Não abrange merge, tag de release, deploy, restart, migrations ou restore.

O job `secrets` da execução [39411771630](https://github.com/RuiGN/rgnfarmasystemv2/actions/runs/39411771630)
falhou no candidato `36a5cd694de9c39876057f96e3220f26d9c97daa`.
O SARIF obtido do artefato `12259915519` contém 103 achados, reproduzidos
localmente com igualdade de arquivo, regra e linhas, inclusive multiplicidades.
São os 83 hashes de arquivos/PNG e os 20 valores do mapa `EXPECTED_SOURCES`
já classificados independentemente como públicos no
[recibo de triagem](evidence/publication-2026-10-20/security-triage-review.json).
A causa remota não foi inferida apenas do scan local de diretório.

Origem `introduced`: os achados apontam para linhas de evidência acrescentadas
no commit candidato; isso é inferência pelo diff, não execução no merge-base.
O campo de versão do driver no SARIF não comprova a versão do binário remoto.
A reprodução usa Gitleaks 8.30.1.

## Correção e fronteiras de segurança

- `.gitleaks.toml` permanece byte a byte igual, com regras padrão habilitadas.
- Os 2398 bytes anteriores de `.gitleaksignore`, incluindo suas 15 exceções
  históricas acrescentadas, permanecem idênticos.
- Foram acrescentados somente 84 fingerprints do commit imutável acima,
  vinculados a arquivo, regra e linha. Não há regex ou exceção de diretório,
  basename, extensão ou formato genérico de hash.
- São 84 identidades para 103 achados: os 20 valores do mapa estão na mesma
  linha do mesmo blob e, portanto, compartilham um fingerprint. A identidade
  do commit fixa os bytes da linha inteira, não apenas um valor dela.
- A lista exata está em
  [approved-commit-fingerprints.json](evidence/ci-secrets-2026-10-20/approved-commit-fingerprints.json).
  Seu conteúdo e o prefixo anterior do ignore têm digests fixados nos testes.
- Os testes anteriores não foram removidos. O conjunto aceito foi estendido
  explicitamente de 15 para 99 registros acrescentados, com checagens de
  preservação do bloco anterior, igualdade do conjunto completo e rejeição
  de identidades alteradas. A entrada que já estava no prefixo histórico
  continua fora dessa contagem de registros acrescentados.

Não foram alteradas fontes funcionais, permissões da aplicação, menus,
workflows, limites de cobertura ou deadlines. O único módulo Python modificado
é o teste das exceções. A aprovação local anterior continua vinculada ao
snapshot anterior; ela não é rebatizada como execução integral deste head.

## Verificações executadas

1. Reprodução Git anterior à correção: exit 1, 103 achados iguais aos remotos.
2. Contratos antes da alteração do ignore: 13 testes, 6 falhas esperadas, sem
   erros de importação. Após a alteração: 13 testes aprovados.
3. Scanner real, mesmo intervalo Git: exit 0, nenhum achado restante.
4. Scanner real em diretório sintético, mesmo arquivo e valores públicos:
   exit 1, 20 achados. Não existe isenção commitless/de diretório.
5. Scanner real em outro commit, mesmo caminho e conteúdo: exit 1, 20 achados.
6. Valor sintético alterado na mesma posição do arquivo: exit 1, 1 achado.
7. Outra regra, com canário não emitido por serviço algum: exit 1,
   1 achado `github-pat`. Nenhuma credencial foi usada ou consultada.
8. Ruff, formato e `git diff --check`: aprovados na árvore examinada.

Os exits 1 dos casos negativos são o resultado esperado e comprovam recusa,
não falhas ignoradas. Os fixtures e relatórios brutos ficam em scratch;
somente metadados sem valores sensíveis são publicados. Um fixture inicial
de chave deliberadamente inválida não acionou o detector e foi substituído
por um canário reconhecido; essa tentativa não foi contada como aprovação.

Evidência dos cinco cenários com o scanner real:
[scanner-regressions.json](evidence/ci-secrets-2026-10-20/scanner-regressions.json).
O programa de reprodução não consulta dotenv, credenciais ou banco operacional.

## Revisão independente

O parecer `deleg_8a21d997` foi **ship**, confiança alta, sem achados,
restrito aos sete arquivos preparados originalmente. O revisor conferiu os
blobs imutáveis, a política, os bytes anteriores do ignore e executou os
13 testes, inclusive reproduzindo o RED em memória. Não reexecutou o acesso
remoto ao SARIF nem os cinco cenários do scanner real.
O [recibo](evidence/ci-secrets-2026-10-20/review-independent.json)
preserva esses limites; este link e o próprio recibo foram acrescentados depois
do parecer e não são apresentados como nova revisão independente.

## Estado e limites

**Correção local verificada; CI do novo head ainda pendente neste registro.**
O job `quality` do head anterior concluiu com sucesso, incluindo quality gate,
build da imagem e SBOM, mas a execução anterior permaneceu failure devido a
`secrets`. A nova revisão e o CI devem ser vinculados ao head efetivamente
publicado, não extrapolados desse resultado anterior.

O estado remoto atualizado é consultável no [PR draft #1](https://github.com/RuiGN/rgnfarmasystemv2/pull/1).
Este registro não concede merge/deploy nem substitui restore isolado,
aceites Segurança/DPO/Qualidade ou impressão física na indústria.
