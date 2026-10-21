# Deploy na Contabo

## Contrato

- Host autorizado: `13.140.139.122`.
- Checkout: `/opt/rgnfarmasystem`.
- Domínio único: `https://rgnfarmasystem.rgnsystems.com.br`.
- Origem do túnel: `http://127.0.0.1:8081`.
- Orquestração: `docker compose -f docker-compose.vps.yml`.

O `.env` remoto é preservado, fica `0600` e nunca deve ser impresso ou carregado
com `source`. PostgreSQL, Redis e RabbitMQ não publicam portas externas.
Defina `CLOUDFLARED_METRICS_ADDRESS=127.0.0.1:20242` no ambiente do Compose para
reservar a porta de prontidão exclusiva deste conector no loopback da VPS.
Esse endereço é autoritativo para Compose e `scripts/deploy-vps.sh`; não basta
definir apenas a variável legada `TUNNEL_METRICS_PORT=20242`. Sem endereço
explícito, o padrão do script é `127.0.0.1:20249`. Os probes deste runbook usam
`20242`, portanto devem acompanhar o endereço efetivamente configurado, sem
carregar o dotenv com `source` nem expor seu conteúdo.
O Compose fixa `DJANGO_SETTINGS_MODULE=core.settings.production` no app e nos
processos Celery. O dotenv de produção deve manter HSTS por um ano, incluindo
subdomínios e a diretiva de preload, conforme `.env.example`.

Na primeira instalação, mantenha um checkout Git completo para permitir
auditoria e rollback por revisão:

```bash
git clone https://github.com/ruign/rgnfarmasystem.git /opt/rgnfarmasystem
cd /opt/rgnfarmasystem
git fetch --tags --prune
git switch --detach <SHA_APROVADO>
```

Nas promoções normais, use o fast-forward descrito abaixo. `git switch
--detach` é reservado à instalação inicial ou ao rollback formal para o SHA já
registrado; nunca substitui a conferência de `git status --short`.

## 1. Registrar estado anterior

```bash
cd /opt/rgnfarmasystem
git status --short
git rev-parse HEAD
docker compose -f docker-compose.vps.yml ps
```

Interrompa se houver alteração versionada inesperada.

## 2. Backup obrigatório

O backup deve terminar e ser validado antes de qualquer `migrate`, build ou
troca de container.

```bash
umask 077
release_dir="backups/release-$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 0700 "$release_dir"
git rev-parse HEAD > "$release_dir/previous-release.gitref"

set -o pipefail
docker compose -f docker-compose.vps.yml exec -T db sh -c \
  'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' \
  | gzip > "$release_dir/postgres.sql.gz"
docker run --rm -v rgnfarmasystem_media:/source:ro \
  -v "$PWD/$release_dir":/backup alpine \
  tar -czf /backup/media.tar.gz -C /source .

gzip -t "$release_dir/postgres.sql.gz"
tar -tzf "$release_dir/media.tar.gz" >/dev/null
sha256sum "$release_dir/postgres.sql.gz" "$release_dir/media.tar.gz" \
  > "$release_dir/SHA256SUMS"
sha256sum -c "$release_dir/SHA256SUMS"
```

## 3. Promover o candidato

O SHA local aprovado deve existir no remoto Git antes do deploy. Na VPS:

```bash
git fetch --prune
git merge --ff-only <SHA_APROVADO>
test "$(git rev-parse HEAD)" = '<SHA_APROVADO>'
docker compose -f docker-compose.vps.yml config --quiet
```

Não use `git reset --hard` e não remova volumes.

## 4. Aplicar o release

```bash
docker compose -f docker-compose.vps.yml up -d --build --remove-orphans
docker compose -f docker-compose.vps.yml ps
docker compose -f docker-compose.vps.yml exec -T app \
  python manage.py showmigrations --plan
docker compose -f docker-compose.vps.yml exec -T app \
  python manage.py check --deploy
```

Aguarde `app` saudável por até 15 minutos. Confirme também `db`, `redis`,
`rabbitmq`, `celery_worker`, `celery_beat`, `nginx` e `cloudflared`.

## 5. Administrador inicial

O usuário é `Rui <ruign2015@gmail.com>`, ativo, staff e superusuário. A senha é
fornecida em arquivo temporário `0600`, fora do checkout, para um processo
one-shot. O processo deve validar `check_password()` e destruir o arquivo sem
exibir o conteúdo. A senha nunca entra no Git, histórico ou log do container.

## 6. Validação interna

```bash
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: rgnfarmasystem.rgnsystems.com.br' http://127.0.0.1:8081/health/
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: rgnfarmasystem.rgnsystems.com.br' http://127.0.0.1:8081/accounts/login/
curl -fsS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: rgnfarmasystem.rgnsystems.com.br' http://127.0.0.1:8081/admin/
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Host: rgnfarmasystem.rgnsystems.com.br' http://127.0.0.1:8081/platform/
curl -fsS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:20242/ready
```

Esperado: `200`, `200`, redirecionamento/`200` no Admin e `404` em
`/platform/`; o conector também deve responder `200` em `/ready`.

## 7. Validação pública

```bash
curl --fail --silent --show-error --max-time 20 --retry 3 \
  -o /dev/null -w '%{http_code} %{ssl_verify_result}\n' \
  https://rgnfarmasystem.rgnsystems.com.br/health/
curl --fail --silent --show-error --max-time 20 \
  -o /dev/null -w '%{http_code}\n' \
  https://rgnfarmasystem.rgnsystems.com.br/accounts/login/
```

Repita na VPS via DNS público. O esperado é `200 0` e `200`. Registre somente
status, timestamps e SHA; não copie token, connector ID ou headers do túnel.

## Rollback

Em falha bloqueante, reimplante o SHA salvo em `previous-release.gitref` por
fast-forward/revisão aprovada e execute novamente o Compose. Restaure banco e
mídia somente se uma migration incompatível tiver sido aplicada, sempre após
`sha256sum -c`. Preserve o diretório de backup e não execute `prune`.

## Compatibilidade: PostgreSQL nativo

O release atual da Contabo usa o serviço `db` privado do Compose. As instruções
desta seção existem somente para recuperar ou migrar instalações anteriores que
usavam PostgreSQL nativo; não alteram a topologia single-domain vigente.

Antes de atribuir ou rotacionar a senha da role legada, force SCRAM e confirme a
configuração:

```bash
sudo -u postgres psql -v ON_ERROR_STOP=1 \
  -c "ALTER SYSTEM SET password_encryption = 'scram-sha-256';"
sudo systemctl reload postgresql
sudo -u postgres psql -Atqc "SHOW password_encryption" | grep -Fx scram-sha-256
sudo -u postgres psql <<'SQL'
SELECT 'CREATE ROLE rgnfarmasystem LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'rgnfarmasystem')\gexec
SELECT 'CREATE DATABASE rgnfarmasystem OWNER rgnfarmasystem'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'rgnfarmasystem')\gexec
\password rgnfarmasystem
SQL
```

Comandos no host usam `HOST_DB_HOST=127.0.0.1`; containers usam
`CONTAINER_DB_HOST=host.docker.internal`. Publique o PostgreSQL apenas nas
interfaces Docker necessárias, nunca na interface pública:

```bash
HOST_DB_HOST=127.0.0.1
CONTAINER_DB_HOST=host.docker.internal
DOCKER0_ADDR=$(ip -4 -o addr show docker0 | awk '{split($4, a, "/"); print a[1]}')
DOCKER_GW_ADDR=$(ip -4 -o addr show docker_gwbridge | awk '{split($4, a, "/"); print a[1]}')
test -n "$DOCKER0_ADDR" && test -n "$DOCKER_GW_ADDR"
printf "listen_addresses = 'localhost,%s,%s'\n" "$DOCKER0_ADDR" "$DOCKER_GW_ADDR"
pg_isready -h "$HOST_DB_HOST" -p 5432
```

Registre a linha gerada em `postgresql.conf`. Em `pg_hba.conf`, permita somente
a subnet Docker real e autenticação `scram-sha-256`:

```bash
DOCKER_GW_SUBNET=$(docker network inspect docker_gwbridge --format '{{(index .IPAM.Config 0).Subnet}}')
printf 'host  rgnfarmasystem  rgnfarmasystem  %s  scram-sha-256\n' "$DOCKER_GW_SUBNET"
```

Para uma operação one-shot contra essa topologia, carregue o dotenv somente
pelo Docker:

```bash
APP_IMAGE=$(docker compose -f docker-compose.vps.yml images -q app)
docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \
  -e DB_DEPLOYMENT=external --entrypoint python "$APP_IMAGE" manage.py check --deploy
```

## Migração do PostgreSQL em container

Esta subseção cobre o corte de uma instalação legada em container para o
PostgreSQL nativo acima. Execute-a apenas em janela aprovada, sem escritas. O
cliente `pg_dump` vem do próprio container legado, e o arquivo temporário só é
publicado após sucesso:

```bash
umask 077
install -d -m 0700 /var/backups/rgnfarmasystem-migration
APP_IMAGE=$(docker compose -f docker-compose.vps.yml images -q app)
CONTAINER_DB_HOST=host.docker.internal
LEGACY_DB_CONTAINER=$(docker ps --filter name=rgnfarmasystem_db --format '{{.ID}}' | head -n1)
test -n "$LEGACY_DB_CONTAINER"
set -o pipefail
POSTGRES_TMP=$(mktemp /var/backups/rgnfarmasystem-migration/.postgres-migration.XXXXXX.sql.gz)
trap 'rm -f "$POSTGRES_TMP"' EXIT
docker exec "$LEGACY_DB_CONTAINER" pg_dump -U rgnfarmasystem rgnfarmasystem \
  --no-owner --no-acl | gzip > "$POSTGRES_TMP"
MIGRATION_DUMP=/var/backups/rgnfarmasystem-migration/postgres-migration.sql.gz
mv "$POSTGRES_TMP" "$MIGRATION_DUMP"
trap - EXIT
gunzip -t "$MIGRATION_DUMP"
sha256sum "$MIGRATION_DUMP" > /var/backups/rgnfarmasystem-migration/migration-dump.sha256
```

Restaure primeiro em um banco isolado. O alvo é passado por `POSTGRES_DB`, que
é a variável consumida por `scripts/restore.sh`:

```bash
sudo -u postgres createdb --owner=rgnfarmasystem rgnfarmasystem_restore_check
docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \
  -e DB_DEPLOYMENT=external -e DB_HOST="$CONTAINER_DB_HOST" \
  -e POSTGRES_DB=rgnfarmasystem_restore_check -e BACKUP_DIR=/backups \
  -v /var/backups/rgnfarmasystem-migration:/backups \
  -v "$PWD:/workspace:ro" --entrypoint bash "$APP_IMAGE" \
  /workspace/scripts/restore.sh --postgres "/backups/$(basename "$MIGRATION_DUMP")" --dry-run
docker run --rm --env-file .env --add-host host.docker.internal:host-gateway \
  -e DB_DEPLOYMENT=external -e DB_HOST="$CONTAINER_DB_HOST" \
  -e POSTGRES_DB=rgnfarmasystem_restore_check -e BACKUP_DIR=/backups \
  -v /var/backups/rgnfarmasystem-migration:/backups \
  -v "$PWD:/workspace:ro" --entrypoint bash "$APP_IMAGE" \
  /workspace/scripts/restore.sh --postgres "/backups/$(basename "$MIGRATION_DUMP")" --yes
```

O arquivo de aprovação somente pode existir quando todas as consultas `psql`
forem bem-sucedidas. A remoção é limitada ao nome exato do banco isolado:

```bash
set -o pipefail
RESTORE_GATE=/var/backups/rgnfarmasystem-migration/restore-check.approved
RESTORE_LOG=/var/backups/rgnfarmasystem-migration/restore-check.log
rm -f "$RESTORE_GATE"
if {
  sudo -u postgres psql -d rgnfarmasystem_restore_check \
    -v ON_ERROR_STOP=1 -Atqc 'SELECT current_database()' | grep -Fx rgnfarmasystem_restore_check &&
  sudo -u postgres psql -d rgnfarmasystem_restore_check \
    -v ON_ERROR_STOP=1 -Atqc 'SELECT count(*) FROM django_migrations' | grep -Eq '^[1-9][0-9]*$' &&
  sudo -u postgres psql -d rgnfarmasystem_restore_check \
    -v ON_ERROR_STOP=1 -Atqc 'SELECT count(*) FROM django_content_type' | grep -Eq '^[1-9][0-9]*$'
} 2>&1 | tee "$RESTORE_LOG"; then
  touch "$RESTORE_GATE"
else
  rm -f "$RESTORE_GATE"
  exit 1
fi
test -s "$RESTORE_LOG"
test -f "$RESTORE_GATE" && sudo -u postgres dropdb rgnfarmasystem_restore_check
```

Somente após esse gate promova o dump validado para o destino formal e registre
hash, operador, horário e resultado. Preserve o dump e o banco/volume anterior
até o aceite e o fim da janela de rollback.
