# Fechamento pontual dos diagnósticos Gitleaks

## Autorização e limite

Exceções pontuais autorizadas expressamente com provas e testes negativos.
Referência: HEAD `d805ae54cf0bb985389d22c3d0c71f355a93cd21`, Gitleaks **8.30.1**.
Não há reescrita de história, baseline de achados, remoção de evidências,
exclusão de arquivos/diretórios, desativação ou substituição de regras padrão.
Este fechamento local não é execução de CI, merge, deploy ou rotação de credenciais.

## Política restrita

- Os **14.357 bytes anteriores** de `.gitleaksignore` permanecem idênticos
  (SHA-256 `27c9cf8c77766e2d30c59482db18e427c3813314a84dcdec04598893b37795cc`).
  Mantêm-se os 100 fingerprints anteriores, inclusive o contrato das 99 adições
  após a primeira exceção. Somente quatro tuplas completas e imutáveis
  `commit:arquivo:regra:linha` foram acrescentadas: total **104**.
- `.gitleaks.toml` mantém integralmente seus 79 bytes iniciais e
  `[extend] useDefault = true`. Sem `disabledRules`, sobrescritas `rules`,
  stopwords, exceções por commit inteiro ou padrões genéricos de hashes.
- As **120 allowlists** são individuais: `condition = "AND"`,
  `targetRules = ["generic-api-key"]`, `regexTarget = "match"`, caminho
  relativo completo ancorado e um único match público literal ancorado.
  Nunca `regexTarget = "line"`: adicionar um segredo ao lado do match permitido
  na mesma linha continua produzindo achado.
- Não se reconhece “qualquer SHA-256”. Cada digest/contexto é literal e tem
  comprovação criptográfica de bytes públicos. Prefixos, sufixos, namespaces,
  outra regra e alteração do valor ficam fora das exceções.

**Convenção obrigatória para diretório:** entrar na raiz da cópia pública
explicitamente permitida e usar `gitleaks dir .`. Os caminhos são relativos e
exatos. Fornecer um alvo absoluto ou prefixar caminhos não amplia a política:
produz achados não suprimidos. Não substituir as âncoras por padrões de basename
ou prefixos arbitrários para adaptar a execução.

A sintaxe foi conferida na documentação oficial da versão:
<https://github.com/gitleaks/gitleaks/blob/v8.30.1/README.md#configuration>.

## Proveniência pública

[`secrets-exceptions.json`](secrets-exceptions.json), SHA-256
`20401d06ab5de0a303f524f495493c529abe84b6f4a7902fec334e1cde7c8c29`,
registra as 120 identidades de diretório, hashes dos arquivos e matches,
referências dos 118 digests e as quatro identidades históricas completas.
Não contém valores de canários, conteúdo PEM nem campos `Secret`/`Match`.

- **118** ocorrências são digests públicos em dez arquivos de metadados.
  Os bytes referenciados foram novamente hasheados; não se inferiu inocuidade
  pelo formato hexadecimal. Os 12 arquivos contenedores coincidem com HEAD.
- Uma referência histórica declara `corrections/final-openapi.yml`, mas os bytes
  correspondentes estão preservados em `corrections/v2-openapi.yml`.
  O manifesto conserva ambos os nomes e comprova igualdade de bytes pelo digest;
  **não afirma** que o caminho histórico declarado contém esses bytes hoje.
  Nenhum documento histórico foi corrigido retroativamente.
- **1** ocorrência Quill é atribuição JavaScript pública; **1** é prosa no plano
  NF-e. Os blobs nos commits de introdução foram comparados com HEAD.
- **2** ocorrências históricas `private-key` são fixtures PEM inválidos em testes
  ausentes de HEAD. Foram extraídas dos blobs Git exatos, identificadas por
  hashes e rejeitadas novamente por `openssl pkey -noout`, offline, exit 1.
  Isso não é alegação de revogação/rotação de uma chave operacional.

## Verificação observada

Os relatórios originais foram preservados. Reexecuções com a política anterior
produziram **RED: exit 1 / 120** na mesma cópia pública original e
**RED: exit 1 / 4** em `git --all`. Com a política nova, os mesmos escopos
produziram **GREEN: exit 0 / 0**. A contagem não foi filtrada após a execução.

```sh
# CWD: raiz da cópia pública explicitamente permitida, não o checkout bruto.
gitleaks dir . --config "$REPO/.gitleaks.toml" \
  --gitleaks-ignore-path "$REPO/.gitleaksignore" --redact=100 \
  --no-banner --no-color --report-format=json --report-path "$SCRATCH/report.json"

# CWD: checkout; leitura do histórico Git, não dos arquivos operacionais.
gitleaks git . --log-opts=--all --config .gitleaks.toml \
  --gitleaks-ignore-path .gitleaksignore --redact=100 \
  --no-banner --no-color --report-format=json --report-path "$SCRATCH/history.json"

# Sem conftest/Django. Temporários e canários ficam em scratch.
TMPDIR="$HOME/.hermes/cache/scratch" PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -p 'test_gitleaks*exceptions.py' -v
```

**22 testes aprovados**, incluindo scanner real e estes controles:

| Controle negativo | Exit / achados esperados e observados |
|---|---:|
| Segredo novo ao lado do literal aprovado, mesmos arquivos completos e linhas | 1 / 120 |
| Digest novo no mesmo contexto de metadado, arquivos completos e linhas | 1 / 118 |
| Outra regra padrão (`github-pat`), mesmos arquivos completos e linhas | 1 / 120 |
| Mesmos literals em `elsewhere/` | 1 / 120 |
| Mesmos literals com sufixo `.backup` | 1 / 120 |
| Mesmos literals sob prefixo `config/` | 1 / 120 |
| Dois commits novos, nos quatro caminhos/regras/linhas históricos exatos | 1 / 8 |
| Literals públicos isolados: política anterior / política nova | 1 / 120; 0 / 0 |

Canários são gerados em runtime e nunca impressos ou versionados. Canários
hexadecimais têm histograma de entropia constante, evitando falsos negativos
aleatórios do próprio detector por baixa entropia. Os testes mantêm asserts
exatos de contagem e identidade, sem relaxá-los para obter aprovação.

Os recibos privados de execução, relatórios redigidos e logs ficam em
`$HOME/.hermes/cache/scratch/gitleaks-closure-1792595435462291000/`.
O índice real foi mantido byte a byte. Os scans abrangem somente as cópias
públicas explicitamente enumeradas e as refs Git locais; não leem `.env`
operacionais, `.hermes/` do checkout ou mídia não enumerada. Novas alterações,
novas refs ou outro executável exigem nova execução; não há promessa de
aprovação de versões futuras do scanner.

## Integração e reprodutibilidade

A integração executou **25 testes aprovados**, incluindo os testes reais do
scanner, sem Django ou banco. Além dos 22 contratos iniciais, há regressões
para temporários portáveis sem uma home Hermes existente, admissão dos canários
e versão do scanner no job `secrets`. O workflow fixa `GITLEAKS_VERSION=8.30.1`,
parâmetro documentado pelo próprio `gitleaks-action`.

Foi preservada uma tentativa intermediária com 23 testes e uma falha: o controle
de digest novo encontrou 117 em vez de 118 ocorrências. Não se reduziu o assert.
Um controle independente demonstrou que um canário com entropia 4,0 e uma
stopword hexadecimal da configuração **padrão anterior** também é ignorado por
essa política anterior. Histograma fixo, isoladamente, não comprova admissão
pelo detector. O gerador agora rejeita as stopwords hexadecimais do detector
padrão fixado, com limite explícito de tentativas; nenhuma stopword foi
acrescentada à política do projeto. Uma regressão determinística reproduziu
RED antes dessa correção.

Antes de aplicar as exceções, os próprios controles de arquivos completos
exigem também **240 achados** na política anterior para segredo adjacente e
**120** para digest substituído. Só depois verificam os resultados novos
**120** e **118**, respectivamente. Assim, uma falha do canário no detector
original não se confunde com uma exceção excessiva. Valores de canários não
são impressos nos recibos.

Logs de integração, incluindo REDs e a execução final de 25 testes, ficam em
`$HOME/.hermes/artifacts/rgnfarmasystemv2/product-editor-simplification/`.
Uma reexecução independente do diretório amplo atingiu o limite externo de
180 segundos; não foi classificada como GREEN e não substitui os resultados
anteriores. A renovação independente posterior concluiu os **três escopos com
exit 0 / zero achados**: diretório público original, todas as refs locais e
snapshot público da integração do scanner com **3.671 arquivos enumerados**.
O índice real permaneceu inalterado. O recibo
`gitleaks-parent-renewal-1792599711762563000.json` tem SHA-256
`ac0693d5d9bd162184c67c73eaad33b0e9b2c0eb96bbdcb17b48255e0bbd314d`;
os três relatórios JSON foram relidos e seus hashes conferidos pelo integrador.
As alterações concorrentes de domínio e interface continuam exigindo
um snapshot final congelado antes da publicação; estes contratos não certificam
um candidato que ainda esteja mudando nem a CI remota.
