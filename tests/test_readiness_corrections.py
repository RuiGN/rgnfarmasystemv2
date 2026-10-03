from pathlib import Path
import subprocess

import pytest
import yaml

from core import views


ROOT = Path(__file__).resolve().parents[1]


def test_vps_tunnel_healthchecks_connection_instead_of_binary_version():
    compose = yaml.safe_load((ROOT / 'docker-compose.vps.yml').read_text())
    test = compose['services']['cloudflared']['healthcheck']['test']
    address = '${CLOUDFLARED_METRICS_ADDRESS:-127.0.0.1:20249}'
    assert test == [
        'CMD',
        'cloudflared',
        'tunnel',
        '--metrics',
        address,
        'ready',
    ]
    command = compose['services']['cloudflared']['command']
    assert command[command.index('--metrics') + 1] == address


def test_readiness_endpoint_reports_healthy_dependencies(client, monkeypatch):
    for name in ('probe_database', 'probe_cache', 'probe_broker'):
        monkeypatch.setattr(views, name, lambda: None, raising=False)
    response = client.get('/ready/')
    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok',
        'checks': {'database': True, 'cache': True, 'broker': True},
    }


@pytest.mark.parametrize('failed', ['database', 'cache', 'broker'])
def test_readiness_failure_returns_unavailable_without_sensitive_errors(
    client, monkeypatch, failed
):
    def broken():
        raise RuntimeError('synthetic-secret-that-must-not-leak')

    for name in ('database', 'cache', 'broker'):
        monkeypatch.setattr(
            views, f'probe_{name}', broken if name == failed else lambda: None, raising=False
        )
    response = client.get('/ready/')
    assert response.status_code == 503
    assert response.json()['checks'][failed] is False
    assert b'synthetic-secret' not in response.content


def test_deploy_rejects_unhealthy_tunnel_even_with_working_http():
    source = (ROOT / 'scripts/deploy-vps.sh').read_text()
    function = source[source.index('readiness_failure() {') : source.index('rollback_release() {')]
    mocks = """
set -euo pipefail
PUBLIC_HOST=example.invalid
ORIGIN_URL=http://example.invalid/health/
TUNNEL_READY_URL=http://example.invalid/ready
compose() {
  if [[ "$*" == "ps --status running --services" ]]; then
    printf '%s\\n' app nginx celery_worker celery_beat db redis rabbitmq backup_scheduler cloudflared
  elif [[ "$*" == "ps -q cloudflared" ]]; then
    printf 'synthetic-tunnel-container\\n'
  fi
}
curl() { return 0; }
docker() { printf 'unhealthy\\n'; }
log() { printf '%s\\n' "$*"; }
fail() { printf '%s\\n' "$*"; exit 1; }
"""
    result = subprocess.run(
        ['bash'],
        input=mocks + function + '\nverify_readiness\n',
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert 'Tunel sem conexao saudavel' in result.stdout + result.stderr


def test_lightweight_liveness_contract_is_preserved(client):
    response = client.get('/health/')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}
