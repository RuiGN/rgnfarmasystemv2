# Publicação do candidato — 2026-10-20

## Autorizações e limites

O usuário autorizou separadamente:

1. Criar commits, publicar `release/2026-10-20-63af02ef` em
   `RuiGN/rgnfarmasystemv2` e abrir PR para `main`, **sem merge, tag de release
   ou deploy**. O repositório foi observado público. Dotenv, dumps, uploads reais
   e estado privado `.hermes/` não integram a seleção de publicação.
2. Criar backup fresco de PostgreSQL/mídia na VPS e preservar a imagem atual por
   tag e exportação, com arquivos protegidos, sem restore, restart ou edição de
   configuração.

A preparação vinculou os blobs do índice Git às999 fontes do snapshot aprovado
`source-sha256:63af02efc3d7a640607ff9b2d841a3a80b8f9abfd2cc6c55aab7f13037e17694`.
Essa identidade não é uma nova execução da suíte nem aprovação de CI remoto.
O baseline local/remoto consultado era
`d8b179c77787806f463d1d637a526bbdf0436d22`.

## Verificação de publicação

O Gitleaks8.30.1 foi executado sobre uma cópia explícita dos327 arquivos elegíveis,
sem dotenv/estado de agente, com redação e profundidade de arquivos compactados2.
O resultado bruto foi **exit1,103 achados generic-api-key em6 arquivos**.

A classificação programática identificou:

- 83 registros JSON com valores SHA256 iguais aos arquivos de fonte/PNG indicados;
- 20 achados na linha do mapa `EXPECTED_SOURCES` do probe, cujo dicionário é
  exatamente o snapshot de999 fontes conferido;
- nenhum achado não classificado nessa varredura.

Isso não transforma o scanner em verde nem valida todo o histórico Git. A
revisão independente `deleg_41865217` confirmou **PUBLICATION_SAFE**, restrito à
allowlist examinada:103/103 valores comprovados,23 arquivos referenciados e zero
desconhecidos. Não é aprovação de CI/merge; o recibo está em
`evidence/publication-2026-10-20/security-triage-review.json`. Os recibos de backup
adicionados depois desse recorte passaram em varredura direta separada.
`.gitleaks.toml`, `.gitleaksignore` e os testes de suas exceções históricas não
foram relaxados. O resultado de CI/merge-readiness deve ser lido no PR efetivo,
não inferido da classificação local ou de testes antigos.

O primeiro `git diff --cached --check` registrou4 problemas de whitespace somente
em3 JUnits RED brutos. Seguindo o padrão existente, `.gitattributes` passou a
tratar como binários apenas `ci-rabbitmq-identity-red.xml`,
`last-four-replay-red.xml` e `rabbitmq-identity-red.xml` dessa rodada. Os bytes
foram preservados, os arquivos foram examinados na varredura direta e fontes
Python continuam com diff normal. O gate de whitespace passou depois disso;
Ruff e formato também passaram. Não se trata de esconder whitespace em fontes.

## Backup e preservação de rollback executados

Diretório remoto protegido:
`/var/backups/rgnfarmasystem/releases/prepublish-20261020T104215904590Z-63af02ef`.

Recibo: `receipt.json`; manifesto: `SHA256SUMS`. O hash do recibo conferido pelo
pai é `4041038ba43ea31f461cc1e8edee510201f8a5b069b06aee2d0923ce461c9f12`.

| Artefato | Bytes | Verificação |
|---|---:|---|
| `postgresql.dump.gz` |233270| gzip e catálogo pg_restore, sem conectar a banco para listar |
| `media.tar.gz` |105| gzip/tar; volume de mídia observado vazio |
| `rollback-image.tar.gz` |540412566| gzip/tar, hashes; worker também validou identidade e grafo OCI |

Tag preservada:
`rgnfarmasystem:rollback-20261020t104215904590z-1afda8b358fa`.

Imagem:
`sha256:1afda8b358fa7e8f6b839607ef8398c59d293fe4afacf797cee606c2dce9486e`.

Após a execução pelo worker, o pai realizou nova conexão SSH em
`2026-10-20T10:52:02Z` e reconferiu os5 hashes do manifesto, os7 arquivos em0600,
diretório0700, gzip/tar, catálogo PostgreSQL e tag/imagem. Os9 containers mantiveram
IDs/imagens e estavam running/healthy, com zero restarts; o dotenv continuou0600.
O primeiro validador do worker confundiu digest de configuração com índice OCI;
a validação foi corrigida e o mesmo export foi validado, sem recriar a imagem.
A ocorrência permanece no recibo remoto, sem declarar a tentativa inicial verde.

**Formato importante:** o dump é custom `pg_dump` comprimido, não SQL plano.
Uma restauração requer `pg_restore` e procedimento autorizado adequado; não
passar esse arquivo diretamente ao caminho SQL de `scripts/restore.sh`.

Limites: backup quente, sem atomicidade conjunta banco+mídia, sem restauração
isolada e sem cópia offsite. Não se promete RPO futuro: reconfirmar a validade do
backup imediatamente antes de uma eventual promoção e repetir se a janela exigir.
Os dados/export ficaram na VPS; somente recibos sanitizados e probes sem segredos
foram preservados localmente em `evidence/publication-2026-10-20/`.

## Estado de liberação

**Produção permanece HOLD.** Publicação de branch/PR e suas verificações não
concedem merge/deploy ou aceites formais. A imagem de rollback não foi carregada
ou executada, o banco não foi restaurado e nenhum serviço foi reiniciado.
Encerramento de Segurança/DPO/Qualidade, provisionamento seguro e aceite físico
da impressão na indústria mantêm seus próprios registros e limites.
