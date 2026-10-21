# Pré-checagem operacional da VPS — 2026-10-20

**Recorte deste parecer:** auditoria até10:12UTC e correção autorizada do modo do
dotenv até10:32UTC. As afirmações de ações não executadas abaixo se referem a
esse recorte. Autorizações e execução posteriores de backup/preservação de imagem
e preparação de publicação estão no [registro de publicação](publication-2026-10-20.md).

## Decisão

**Auditoria concluída; correção posterior de permissão confirmada. Deploy: HOLD.**
O runtime foi observado saudável e o dotenv foi corrigido para0600, mas a promoção exige
um candidato imutável/publicado, backup pré-release validado, preservação de
rollback e os aceites operacionais externos. A aprovação de engenharia local
permanece **PASS**; não foi substituída por esta auditoria.

Autorização da auditoria original: resposta **“SIM”** à checagem operacional antes do deploy. Não
abrangeu commit/push, deploy, migrations, criação/restauração de backups,
reinício, alteração de arquivos remotos ou concessão de aceites humanos.

Em nova resposta **“SIM”**, o usuário autorizou exclusivamente corrigir o modo de
`/home/deploy/rgnfarmasystemv2/.env` para0600. A alteração foi executada em
`2026-10-20T10:31:52Z` e confirmada por segunda conexão SSH em
`2026-10-20T10:32:06Z`. Recibos: `evidence/vps-permission-fix-2026-10-20/`.
As demais observações abaixo permanecem datadas da auditoria original.

## Alvo e observações

- SSH existente: `deploy@13.140.139.122`, BatchMode e validação estrita da chave
  de host; nenhuma credencial foi solicitada, lida ou exibida pelo agente.
- Checkout real: **`/home/deploy/rgnfarmasystemv2`**, branch `main`, árvore limpa,
  HEAD `d8b179c77787806f463d1d637a526bbdf0436d22`. `origin/main` local à VPS
  tinha esse mesmo SHA; não houve `fetch` ou consulta ao remoto GitHub.
- O caminho padrão `/opt/rgnfarmasystem` não existe nessa VPS. A primeira
  sondagem composta terminou com exit1 nesse teste de diretório; o SSH estava
  funcionando. A descoberta posterior usou labels Compose e confirmou o caminho.
- Projeto Compose exato: `rgnfarmasystem`, arquivo `docker-compose.vps.yml`.
  Não foram administrados serviços dos outros produtos da máquina compartilhada.
- Janela observada: capturas UTC de `2026-10-20T10:07:26` a
  `2026-10-20T10:12:44` (instantes de início das sondagens, não monitor contínuo).

## Matriz de prontidão

| Área | Resultado | Evidência e limite |
|---|---|---|
| Acesso/identificação | PASS | SSH com chave conhecida, checkout e projeto identificados por metadata |
| Serviços | PASS | 9/9 containers running/healthy; mesmos IDs e zero restarts no início/fim |
| Saúde HTTP/TLS | PASS | `/health/` e `/ready/` internos e públicos: HTTP200; TLS público verificado pelo curl |
| Portas dos backends | PASS | PostgreSQL, Redis e RabbitMQ sem publicação no host; Nginx somente `127.0.0.1:8081` |
| Dotenv | **PASS após correção autorizada** |0664 na auditoria original;0600 confirmado no readback posterior, sem leitura de conteúdo |
| Identidade do candidato | Pendente de promoção | Checkout atual não contém o delta validado localmente; não confundir HEAD-base com snapshot aprovado |
| Recursos | Observação pontual | 4 CPUs, 2,71GiB RAM disponível, 182,83GiB livres, 1,30GiB swap em uso; VM compartilhada com 50 containers |
| Backup | Parcial | Artefatos diários recentes e marcadores existem; integridade e restauração não foram testadas |
| Rollback | Parcial | ID da imagem atual e gitref histórico registrados; imagem não foi retagueada/exportada e rollback não foi exercitado |
| Parâmetros do runbook | HOLD | Caminho `/opt` não corresponde ao checkout real; porta20242 já tem listener no host |
| Segurança/DPO/Qualidade/admin | Não observado | Aceites/provisionamento externos não foram consultados nem simulados |
| Observabilidade/suporte | Parcial | Saúde pontual conferida; alarmes, retenção de logs, responsáveis e janela não foram homologados |

### Serviços conferidos

`app`, `nginx`, `celery_worker`, `celery_beat`, `db`, `redis`, `rabbitmq`,
`backup_scheduler` e `cloudflared`: todos running/healthy, sem reinícios no
contador observado. Não houve alteração dos IDs durante as capturas.

O endpoint local `http://127.0.0.1:20249/ready` retornou200 e existe listener em
loopback nessa porta. O Cloudflared do projeto reporta healthy. Há listeners
compartilhados em20242 e20243: **não aplicar cegamente o exemplo20242 do runbook
nem encerrar outro produto para liberar uma porta**. Não foram lidos os argumentos
com token nem o ambiente dos containers para inspecionar segredos.

Readiness interno: primeira amostra2,555331s, depois2,710618s,2,355026s e2,509526s;
readiness público2,747100s, todos HTTP200. São tempos HTTP totais observados, não
prova de SLA de parede inferior a2s nem medição sob carga. Nenhum deadline foi
alterado. A aprovação dos testes locais de deadline não substitui estes tempos
reais nem um ensaio de capacidade do host.

### Achado de segurança — permissão do `.env`

Na auditoria original, `/home/deploy/rgnfarmasystemv2/.env` tinha modo0664, UID/GID1000, confirmado
em duas capturas. O diretório `/home/deploy` é0750 e limita travessia por outros
usuários, mas isso não satisfaz a política0600. Não foi presumido vazamento a
partir apenas do modo, nem foi lido o conteúdo ou alterada a permissão naquela etapa.

**Correção posterior autorizada e concluída:** somente esse arquivo remoto mudou
de0664 para0600. O readback independente confirmou o mesmo inode, UID/GID, tamanho
e mtime. Não foi aberto para leitura nem teve seu conteúdo editado ou calculado
hash; não houve troca de proprietário ou restart. A autorização anterior de chmod
local não foi reutilizada: houve confirmação específica para a VPS.

### Identidade de código e artefato

Snapshot aprovado local:
`source-sha256:63af02efc3d7a640607ff9b2d841a3a80b8f9abfd2cc6c55aab7f13037e17694`.

Comparação programática das999 fontes com o checkout remoto: **942 iguais,
43 diferentes,14 ausentes**, sem symlinks recusados ou arquivos ilegíveis. É o
delta ainda não promovido, não uma acusação de drift do checkout limpo.
As correções P1, abas, impressão e ajustes de release continuam locais; fazer
apenas pull do HEAD-base não as instala. Publicação/versionamento do candidato
exigem autorização separada.

Imagem atual disponível na VPS:
`sha256:1afda8b358fa7e8f6b839607ef8398c59d293fe4afacf797cee606c2dce9486e`,
com tag `rgnfarmasystem:vps`, sem label OCI de revisão. Capturar a imagem não
prova que seu conteúdo é idêntico ao HEAD do checkout. Não houve comparação
integral de fontes dentro dessa imagem nem preservação nova por tag/export.

A imagem validada localmente é outra:
`sha256:2b3211d4c19535b92332928d5990470f8d1b6d8bf545330949d334c0bae28cc3`.
Esta checagem não a enviou à VPS ou a um registry.

## Backup e recuperação

- Volume do scheduler: `rgnfarmasystem_backups`, montado em
  `/var/backups/rgnfarmasystem`. O scheduler acessa mídia em modo somente leitura.
- Foram inventariados os5 arquivos regulares da raiz desse volume: dois pares
  PostgreSQL/mídia e `last_backup_ok`.
- Par mais recente com mtime `2026-10-20T03:00:01Z`:
  `postgres-20261020-030000.sql.gz` (114699bytes) e
  `media-20261020-030000.tar.gz` (105bytes), ambos0600.
- Marcadores `last_backup_ok` e `backup_scheduler_ready` possuem mtime dessa mesma
  rodada. Marcadores/saúde e tamanho não provam integridade/restaurabilidade.
- A mídia montada contém **zero arquivos regulares**, sem symlinks ou erros de
  travessia. Isso é compatível com um arquivo de mídia pequeno; não foi presumida
  corrupção ou perda a partir apenas dos105bytes. Nenhum upload foi lido.
- Há14 diretórios de releases sob `/var/backups/rgnfarmasystem/releases`; o mais
  recente é `release-20261019T190736Z`. Seus artefatos incluem PostgreSQL/mídia,
  `SHA256SUMS` com duas entradas sintaticamente válidas e `previous-release.gitref`
  com `ef754b804095fa4f643275cf1b02f773209c6500`.
- Os checksums dos arquivos compactados **não foram recalculados** e nenhum
  dump ou arquivo compactado de mídia foi descompactado, lido, transferido ou restaurado.
  Não foi comprovada cópia offsite ou durabilidade fora dessa VPS.

O candidato inclui `scripts/deploy-vps.sh`, cujo rollback automático reimplanta
código anterior, **sem restaurar automaticamente banco ou mídia** (linhas209–216).
Não executar o script durante uma auditoria: ele lê configuração e promove Git,
faz backup/build e altera containers. A presença de `scripts/restore.sh` ou de
seu dry-run não é evidência de um ensaio de restauração.

## Condições antes de promover

1. **Concluído:** autorização específica e modo do dotenv remoto corrigido para0600,
   com readback sem ler conteúdo. O recibo posterior resolve apenas esse achado.
2. Autorizar publicação/versionamento do candidato exato validado, preservando
   alterações locais e vínculo com os hashes de fonte/imagem; sem substituir
   funcionalidades nem usar só o SHA-base como identificação da entrega.
3. Preparar operação com `PROJECT_DIR=/home/deploy/rgnfarmasystemv2`, projeto
   Compose correto e endereço de métricas confirmado, sem disputar portas de
   outros produtos ou mover checkout/volumes sem aprovação.
4. Criar e verificar backup fresco antes da promoção; preservar a imagem atual
   imutavelmente e registrar responsável/critério de recuperação. Demonstrar
   restauração em ambiente isolado ou registrar sua ausência como risco sujeito
   à aprovação aplicável; nunca ensaiar restore no banco operacional.
5. Confirmar janela, monitoramento e responsável de rollback. Critérios preparados:
   os9 serviços saudáveis, health/readiness interno e público200 e ausência de
   regressão de portas. São critérios propostos, não monitor pós-deploy executado.
6. Registrar aceites reais de Segurança/DPO e Qualidade e o provisionamento seguro
   previsto em `known-pending-items.md`. Teste físico de impressão fica para a
   indústria antes de uso operacional, conforme decisão do usuário.

## Evidências e fronteira

A revisão independente `deleg_34c17b04` retornou **REVISE** para dois pontos
documentais, preservados em `review-independent.json`: uma frase do relatório
local negava acesso à produção para toda a sessão, e a descrição da trilha de
comandos excedia suas três sondagens registradas. Os textos foram delimitados
conforme as evidências; o parecer original não foi renomeado PASS nem houve
nova revisão independente após essas correções. A decisão de produção continua
HOLD. Essas correções documentais não alteraram a VPS; o chmod posterior tem
autorização e recibos separados.

Pacote: `evidence/vps-preflight-2026-10-20/`, com resultados JSON sanitizados,
probes concretos, comandos/exit codes, matriz, resumo e `sha256.json`.
`observed-commands.json` vincula as três sondagens principais registradas aos
respectivos programas enviados por stdin. O recibo não cobre os comandos iniciais
de acesso/descoberta, inclusive o teste de diretório com exit1; os resultados da
descoberta estão resumidos em `discovery-sanitized.json`, sem trilha completa desses
comandos. Essa limitação não altera os resultados das três sondagens preservadas.
A comparação com o snapshot e todas as contagens foram verificadas em código.
As999 fontes locais aprovadas continuam sem mudança.

Na auditoria original não houve alteração remota. Posteriormente, somente o chmod
especificamente autorizado foi aplicado ao dotenv, sem editar seu conteúdo.
Nenhum commit, push, deploy, migration, restart ou restore foi realizado.
Não foram lidos conteúdo de dotenv, credenciais, logs,
argv arbitrário, conteúdo de arquivos de mídia ou registros operacionais do banco.
A auditoria não concede aprovação regulatória, homologação industrial ou autorização
para mutações posteriores.
