from pathlib import Path

import pytest
import yaml
from django.conf import settings


ROOT = Path(settings.BASE_DIR)
TRACKED_RUNTIME_FILES = (
    '.env.example',
    '.env.development.example',
    '.env.local.example',
    'docker-compose.vps.yml',
    'deploy/nginx/local.conf',
    'deploy/nginx/rgnfarmasystem.conf',
    'deploy/cloudflared/config.yml',
    'docs/deployment.md',
    'docs/DEPLOY_VPS.md',
    'deploy/vps/README.md',
)


@pytest.mark.parametrize('path', TRACKED_RUNTIME_FILES)
def test_runtime_artifacts_do_not_publish_control_domain(path):
    source = (ROOT / path).read_text(encoding='utf-8')

    assert 'control.rgnfarmasystem.rgnsystems.com.br' not in source
    assert 'CONTROL_PLANE_' not in source


def test_vps_nginx_reresolves_app_upstream_between_releases():
    source = (ROOT / 'deploy/nginx/rgnfarmasystem.conf').read_text(encoding='utf-8')

    assert 'upstream ' not in source, 'upstream fixo congela o IP do app na inicializacao'
    assert 'resolver 127.0.0.11' in source
    assert 'proxy_pass http://$upstream_app$request_uri;' in source


def test_vps_tunnel_targets_internal_nginx():
    compose = yaml.safe_load((ROOT / 'docker-compose.vps.yml').read_text(encoding='utf-8'))

    assert compose['services']['cloudflared']['network_mode'] == 'host'
    assert compose['services']['nginx']['ports'] == ['127.0.0.1:8081:80']
    assert _duration_seconds(compose['services']['app']['healthcheck']['start_period']) >= 600


def test_vps_django_services_enforce_production_settings_profile():
    compose = yaml.safe_load((ROOT / 'docker-compose.vps.yml').read_text(encoding='utf-8'))

    for service_name in ('app', 'celery_worker', 'celery_beat'):
        assert compose['services'][service_name]['environment']['DJANGO_SETTINGS_MODULE'] == (
            'core.settings.production'
        )


def test_example_environment_documents_production_hsts_settings():
    source = (ROOT / '.env.example').read_text(encoding='utf-8')

    assert 'SECURE_HSTS_SECONDS=31536000' in source
    assert 'SECURE_HSTS_INCLUDE_SUBDOMAINS=True' in source
    assert 'SECURE_HSTS_PRELOAD=True' in source


def test_managed_tunnel_uses_the_single_public_hostname_and_internal_nginx():
    tunnel = yaml.safe_load((ROOT / 'deploy/cloudflared/config.yml').read_text(encoding='utf-8'))
    ingress = tunnel['ingress']

    assert [item.get('hostname') for item in ingress if item.get('hostname')] == [
        'rgnfarmasystem.rgnsystems.com.br'
    ]
    assert ingress[0]['service'] == 'http://127.0.0.1:8081'


def _duration_seconds(value):
    if isinstance(value, int):
        return value
    unit = value[-1]
    factor = {'s': 1, 'm': 60, 'h': 3600}[unit]
    return int(value[:-1]) * factor
