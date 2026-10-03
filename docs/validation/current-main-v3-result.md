# Resultado do candidato integrado v3

## Identidade e escopo

Candidato integrado sobre `bee2e6a5fae8f9b6a7753110f95e526579811c61`, preservando os 49 commits posteriores à base antiga das correções. As 2.164 fontes congeladas, a cópia de trabalho e todos os respectivos blobs do índice foram conferidos por SHA-256 antes da publicação. O documento `current-main-release.md` conserva o histórico das reprovações e das etapas anteriores; este registro apresenta a conclusão do v3.

Manifesto de fontes: `034ab77508d9b1d9e01f8aaad2498d613fa0257bca63d486d10faaa960400a22`.

## Resultados executados

| Verificação | Resultado |
| --- | --- |
| Suíte completa PostgreSQL isolado | 2.521 testes e 42 subtestes aprovados; zero falhas, erros ou skips; 1.004 segundos |
| Reconciliação JUnit | 2.563 declarados = 2.521 casos serializados + 42 subtestes |
| Cobertura | 26.482 / 30.679 linhas: 86,32%; limite de 80% atendido |
| Ruff | Aprovado; 566 arquivos formatados |
| MyPy | 397 fontes, zero erros |
| Bandit e diff checks | Aprovados |
| Auditoria dos 98 pins de produção | Sem vulnerabilidades conhecidas; não substitui lock transitivo com hashes |
| Auditoria integral do runtime de validação instalado | Sem vulnerabilidades conhecidas |
| Build sem cache e pip check | Aprovados |
| Conteúdo da imagem | 2.163 fontes conferidas; apenas `.env.development.example` excluído intencionalmente; 98 versões de pacotes correspondentes |
| Oito gates administrativos | check, migrations, schema, evidências, prontidão operacional, backup/restore, aceite e release aprovados |
| Perfil production sintético | check --deploy --fail-level WARNING, zero issues; não testa ambiente real |
| Revisão funcional independente | Sem bloqueadores no escopo; 189 testes dirigidos reportados e sondas sintéticas de locks/retry/múltiplos itens |
| Revisão de segurança/runtime | 108 e 205 testes aprovados nos transcripts reais; parecer restrito reconciliado com listas de segurança/lógica vazias |

Imagem de build validada: `rgnfarmasystem:current-main-candidate-v3`, identidade `sha256:8a69a7a1c1f0ab77b2f47265721b7ab9178cffc21a062a948759270c4064b953`.

## Limites preservados

- A compatibilidade de fabricação NULL no retry exige os vínculos NF-e/XML/hash e origem específicos. Esses dados não distinguem omissão histórica de apagamento posterior. Datas conhecidas permanecem estritas; o retry não faz backfill nem escrita de domínio. Não há certificação de imutabilidade ou proteção contra adulteração da data ausente.
- O antigo probe manual, sem proveniência NF-e, permanece fora dessa exceção. Não foi declarado aprovado.
- O teste HTTP exige zero escrita inesperada e exatamente um INSERT legítimo de auditoria, com quantidade, usuário, método, rota, status e resultado conferidos. Os snapshots completos de sete modelos permanecem intactos; seis casos negativos cobrem DML proibido.
- Gitleaks não foi declarado globalmente limpo: diff rastreado do snapshot teve zero achados/exit 0; diff ampliado teve dois/exit 1; diretório relativo teve dois/exit 1; diretório absoluto teve três/exit 1; histórico teve três/exit 1. Hashes de schemas foram comparados aos arquivos reais, prosa NF-e foi conferida nos blobs e as duas fixtures PEM históricas foram rejeitadas por OpenSSL. Não houve ampliação de allowlists nessa revisão. Escopos distintos não têm totais intercambiáveis.
- O payload final acrescenta dez arquivos de evidência/relatório gerados após a validação. Seu scan stdin completo retornou 15 achados/exit 1: todos foram mapeados às linhas exatas e comprovados como hashes dos arquivos/schema reais. Isso inclui os hashes de nomes relacionados a API, autenticação e criptografia no manifesto; não são credenciais. Esse resultado não equivale ao scan anterior do snapshot, e nenhuma exceção de scanner foi acrescentada.
- O JUnit bruto da reprodução RED HTTP mantém um trecho de traceback com whitespace final. O `git diff --check` do payload aponta exclusivamente esse artefato; todos os demais caminhos passaram. O arquivo foi preservado byte a byte, sem reescrever a evidência nem modificar `.gitattributes` para ocultar esse resultado.
- Fontes imutáveis e saídas geradas são registradas separadamente. Os artefatos v3 anexados após a validação e este relatório não alteram as fontes executadas. Snapshots reprovados e evidências anteriores foram preservados.

## Publicação e produção

A aprovação acima cobre as fontes exatas e o empacotamento verificados. Não declara push, CI remoto, backup real restaurável, migração, deploy, conector ou domínio público aprovados. Essas operações exigem confirmação posterior do commit remoto, do CI, do backup e da versão efetivamente servida; o rollback não deve restaurar banco/mídia automaticamente.
