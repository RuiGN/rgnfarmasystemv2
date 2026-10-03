"""Execute the real main control flow; never run Docker, Git or a deployment."""

from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run_main(scenario):
    source = (ROOT / 'scripts/deploy-vps.sh').read_text()
    definitions = source.rsplit('\nmain "$@"', 1)[0]
    mocks = r"""
PROJECT_DIR="$PWD"
PUBLIC_HOST=example.invalid
ORIGIN_URL=http://example.invalid/health/
WAIT_TIMEOUT_SECONDS=1
require_command() { :; }
check_vps_ip() { :; }
check_env_file() { :; }
check_project_state() { :; }
create_release_backup() { PREVIOUS_SHA=synthetic-previous; RELEASE_BACKUP_DIR=synthetic-backup; }
promote_revision() { :; }
validate_calls=0
validate_compose() {
  validate_calls=$((validate_calls + 1))
  if [[ "$SCENARIO" == config-fail && "$validate_calls" == 2 ]]; then return 1; fi
}
rollback_release() { printf 'ROLLBACK:%s\n' "$PREVIOUS_SHA"; }
git() { printf 'synthetic-candidate\n'; }
compose() {
  case "$*" in
    'ps --status running --services')
      [[ "$SCENARIO" != ps-fail ]] || return 1
      printf '%s\n' app nginx celery_worker celery_beat db redis rabbitmq backup_scheduler
      [[ "$SCENARIO" != missing-service ]] || return 0
      printf 'cloudflared\n';;
    'ps -q cloudflared')
      [[ "$SCENARIO" != tunnel-ps-fail ]] || return 1
      [[ "$SCENARIO" != missing-container ]] || return 0
      printf 'synthetic-tunnel\n';;
    'exec -T app python manage.py check --deploy')
      [[ "$SCENARIO" != check-fail ]] || return 1;;
    up*)
      printf 'CANDIDATE_UP\n'
      [[ "$SCENARIO" != up-fail ]] || return 1;;
    *) return 99;;
  esac
  return 0
}
curl() {
  if [[ "$SCENARIO" == origin-curl-fail && "$*" == *http://example.invalid/* ]]; then return 1; fi
  if [[ "$SCENARIO" == public-curl-fail && "$*" == *https://example.invalid/* ]]; then return 1; fi
  return 0
}
docker() {
  [[ "$SCENARIO" != inspect-fail ]] || return 1
  if [[ "$SCENARIO" == unhealthy ]]; then printf 'unhealthy\n'; else printf 'healthy\n'; fi
}
main
"""
    return subprocess.run(
        ['bash'],
        input=definitions + '\nSCENARIO=' + scenario + '\n' + mocks,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=5,
    )


def test_main_rolls_back_unhealthy_tunnel_instead_of_exiting_inside_verification():
    result = run_main('unhealthy')
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'ROLLBACK:synthetic-previous' in result.stdout


@pytest.mark.parametrize(
    'scenario',
    [
        'missing-service',
        'missing-container',
        'ps-fail',
        'tunnel-ps-fail',
        'origin-curl-fail',
        'public-curl-fail',
        'check-fail',
        'inspect-fail',
        'config-fail',
        'up-fail',
    ],
)
def test_main_propagates_candidate_failure_and_rolls_back(scenario):
    result = run_main(scenario)
    assert result.returncode == 1, result.stdout + result.stderr
    assert 'ROLLBACK:synthetic-previous' in result.stdout
    assert 'Deploy validado:' not in result.stdout
    if scenario == 'config-fail':
        assert 'CANDIDATE_UP' not in result.stdout


def test_main_accepts_healthy_candidate_without_rollback():
    result = run_main('healthy')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'ROLLBACK:' not in result.stdout
    assert 'Deploy validado:' in result.stdout
