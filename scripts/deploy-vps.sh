#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VPS_IP="${EXPECTED_VPS_IP:-13.140.139.122}"
PROJECT_DIR="${PROJECT_DIR:-/opt/rgnfarmasystem}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.vps.yml}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-rgnfarmasystem}"
TARGET_REF="${TARGET_REF:-origin/main}"
PUBLIC_HOST="${PUBLIC_HOST:-rgnfarmasystem.rgnsystems.com.br}"
ORIGIN_URL="${ORIGIN_URL:-http://127.0.0.1:8081/health/}"
TUNNEL_READY_URL="${TUNNEL_READY_URL:-}"
BACKUP_ROOT="${BACKUP_ROOT:-/var/backups/rgnfarmasystem/releases}"
WAIT_TIMEOUT_SECONDS="${WAIT_TIMEOUT_SECONDS:-900}"

PREVIOUS_SHA=""
RELEASE_BACKUP_DIR=""

log() { printf '[%s] %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }
fail() { log "ERRO: $*" >&2; exit 1; }

compose() {
  VPS_ENV_FILE="$ENV_FILE" COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" "$@"
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Comando obrigatorio ausente: $1"
}

read_env_value() {
  local key="$1"
  awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      sub(/\r$/, "", value)
      matches++
    }
    END {
      if (matches > 1) {
        print "Arquivo de ambiente contem chave duplicada: " key > "/dev/stderr"
        exit 1
      }
      if (matches == 1) print value
    }
  ' "$ENV_FILE"
}

check_vps_ip() {
  if [[ "${SKIP_VPS_IP_CHECK:-false}" == "true" ]]; then
    log "Validacao do IP publico desabilitada explicitamente."
    return
  fi

  local current_ip
  current_ip="$(curl -fsS --max-time 10 https://ipinfo.io/ip)" || \
    fail "Nao foi possivel detectar o IP publico da VPS."
  [[ "$current_ip" == "$EXPECTED_VPS_IP" ]] || \
    fail "IP publico inesperado: ${current_ip}; esperado: ${EXPECTED_VPS_IP}."
}

check_env_file() {
  [[ -f "$ENV_FILE" ]] || fail "Arquivo $ENV_FILE nao encontrado."

  local required_vars=(
    SECRET_KEY
    POSTGRES_DB
    POSTGRES_USER
    POSTGRES_PASSWORD
    RABBITMQ_DEFAULT_USER
    RABBITMQ_DEFAULT_PASS
    TUNNEL_TOKEN
    DATA_ENCRYPTION_KEYS
  )
  local key value
  for key in "${required_vars[@]}"; do
    value="$(read_env_value "$key")"
    [[ -n "$value" && "$value" != "change-me" && "$value" != "change-me-in-production" ]] || \
      fail "Variavel obrigatoria ausente ou insegura: $key."
  done

}

configure_tunnel_readiness() {
  local configured_port configured_address
  # Keep the remote's legacy validation, but the shared Compose address is authoritative.
  configured_port="${TUNNEL_METRICS_PORT:-}"
  if [[ -z "$configured_port" && -f "$ENV_FILE" ]]; then
    configured_port="$(read_env_value TUNNEL_METRICS_PORT)"
  fi
  configured_port="${configured_port:-20249}"
  if [[ ! "$configured_port" =~ ^[0-9]{1,5}$ ]] ||
    (( 10#$configured_port < 1 || 10#$configured_port > 65535 )); then
    fail "TUNNEL_METRICS_PORT invalida."
  fi

  configured_address="${CLOUDFLARED_METRICS_ADDRESS:-}"
  if [[ -z "$configured_address" && -f "$ENV_FILE" ]]; then
    configured_address="$(read_env_value CLOUDFLARED_METRICS_ADDRESS)"
  fi
  configured_address="${configured_address:-127.0.0.1:20249}"
  if [[ ! "$configured_address" =~ ^127\.0\.0\.1:([0-9]{1,5})$ ]]; then
    fail "CLOUDFLARED_METRICS_ADDRESS invalida; use loopback 127.0.0.1."
  fi
  configured_port="${BASH_REMATCH[1]}"
  if (( 10#$configured_port < 1 || 10#$configured_port > 65535 )); then
    fail "CLOUDFLARED_METRICS_ADDRESS invalida."
  fi

  CLOUDFLARED_METRICS_ADDRESS="$configured_address"
  TUNNEL_METRICS_PORT="$configured_port"
  TUNNEL_READY_URL="${TUNNEL_READY_URL:-http://${CLOUDFLARED_METRICS_ADDRESS}/ready}"
  export CLOUDFLARED_METRICS_ADDRESS TUNNEL_METRICS_PORT
}

check_project_state() {
  [[ "$(pwd -P)" == "$(cd "$PROJECT_DIR" && pwd -P)" ]] || \
    fail "Execute o script a partir de $PROJECT_DIR."
  [[ -z "$(git status --porcelain --untracked-files=no)" ]] || \
    fail "O checkout possui alteracoes versionadas; deploy interrompido."
  docker compose version >/dev/null
}

validate_compose() {
  compose config --quiet
}

create_release_backup() {
  PREVIOUS_SHA="$(git rev-parse HEAD)"
  RELEASE_BACKUP_DIR="${BACKUP_ROOT}/release-$(date -u +%Y%m%dT%H%M%SZ)"
  install -d -m 0700 "$RELEASE_BACKUP_DIR"
  printf '%s\n' "$PREVIOUS_SHA" > "$RELEASE_BACKUP_DIR/previous-release.gitref"

  log "Criando backup obrigatorio antes da atualizacao."
  DB_DEPLOYMENT=container \
    MEDIA_DEPLOYMENT=container \
    COMPOSE_PROJECT_NAME="$COMPOSE_PROJECT_NAME" \
    BACKUP_DIR="$RELEASE_BACKUP_DIR" \
    POSTGRES_USER="$(read_env_value POSTGRES_USER)" \
    POSTGRES_DB="$(read_env_value POSTGRES_DB)" \
    RETENTION_DAYS=36500 \
    bash scripts/backup.sh

  local postgres_backup media_backup
  postgres_backup="$(find "$RELEASE_BACKUP_DIR" -maxdepth 1 -type f -name 'postgres-*.sql.gz' -print -quit)"
  media_backup="$(find "$RELEASE_BACKUP_DIR" -maxdepth 1 -type f -name 'media-*.tar.gz' -print -quit)"
  [[ -n "$postgres_backup" && -n "$media_backup" ]] || \
    fail "Backup de banco ou midia nao foi produzido."
  gzip -t -- "$postgres_backup"
  tar -tzf "$media_backup" >/dev/null
  sha256sum "$postgres_backup" "$media_backup" > "$RELEASE_BACKUP_DIR/SHA256SUMS"
  sha256sum -c "$RELEASE_BACKUP_DIR/SHA256SUMS"
}

promote_revision() {
  log "Promovendo revisao $TARGET_REF somente por fast-forward."
  git fetch --prune origin
  git merge --ff-only "$TARGET_REF"
}

deploy_compose() {
  # main calls this in a conditional, where Bash disables implicit errexit.
  validate_compose || { readiness_failure "Configuracao Compose invalida."; return 1; }
  compose up -d --build --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT_SECONDS" || {
    readiness_failure "Falha ao implantar o candidato."; return 1;
  }
}

readiness_failure() { log "ERRO: $*" >&2; return 1; }

verify_readiness() {
  local required_services=(
    app nginx celery_worker celery_beat db redis rabbitmq backup_scheduler cloudflared
  )
  local running service
  running="$(compose ps --status running --services)" || {
    readiness_failure "Nao foi possivel listar os servicos."; return 1;
  }
  for service in "${required_services[@]}"; do
    grep -Fxq "$service" <<<"$running" || {
      readiness_failure "Servico nao esta em execucao: $service"; return 1;
    }
  done

  curl -fsS --max-time 20 -H "Host: $PUBLIC_HOST" "$ORIGIN_URL" >/dev/null || {
    readiness_failure "Origem HTTP indisponivel."; return 1;
  }
  local tunnel_container tunnel_health
  tunnel_container="$(compose ps -q cloudflared)" || {
    readiness_failure "Nao foi possivel consultar o container do tunel."; return 1;
  }
  [[ -n "$tunnel_container" ]] || {
    readiness_failure "Container do tunel nao encontrado."; return 1;
  }
  tunnel_health="$(docker inspect --format '{{.State.Health.Status}}' "$tunnel_container")" || {
    readiness_failure "Nao foi possivel inspecionar a saude do tunel."; return 1;
  }
  [[ "$tunnel_health" == healthy ]] || {
    readiness_failure "Tunel sem conexao saudavel: $tunnel_health"; return 1;
  }
  curl -fsS --max-time 20 --retry 3 "https://${PUBLIC_HOST}/health/" >/dev/null || {
    readiness_failure "Dominio publico indisponivel."; return 1;
  }
  compose exec -T app python manage.py check --deploy || {
    readiness_failure "Validacao Django do candidato falhou."; return 1;
  }
}

rollback_release() {
  log "Falha no candidato; restaurando a revisao anterior ${PREVIOUS_SHA}."
  git switch --detach "$PREVIOUS_SHA"
  validate_compose
  compose up -d --build --remove-orphans --wait --wait-timeout "$WAIT_TIMEOUT_SECONDS"
  curl -fsS --max-time 20 -H "Host: $PUBLIC_HOST" "$ORIGIN_URL" >/dev/null
  log "Codigo anterior reimplantado. Banco e midia nao foram restaurados automaticamente."
  log "Backup preservado em $RELEASE_BACKUP_DIR."
}

main() {
  require_command docker
  require_command git
  require_command curl
  require_command gzip
  require_command tar
  require_command sha256sum

  cd "$PROJECT_DIR"
  check_vps_ip
  check_env_file
  configure_tunnel_readiness
  check_project_state
  validate_compose
  create_release_backup
  promote_revision

  if ! deploy_compose || ! verify_readiness; then
    rollback_release
    exit 1
  fi

  log "Deploy validado: revisao $(git rev-parse HEAD), origem, conector e dominio publico saudaveis."
  log "Backup do release: $RELEASE_BACKUP_DIR"
}

main "$@"
