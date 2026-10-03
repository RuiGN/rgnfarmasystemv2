import json
from io import StringIO
from pathlib import Path

import yaml
from django.conf import settings
from django.core.management import call_command
from django.test import SimpleTestCase


class OperationalReadinessTests(SimpleTestCase):
    def test_nfr_operational_readiness_report_covers_runtime_deploy_and_ui_requirements(self):
        from core.operational_readiness import (
            OperationalCheckStatus,
            evaluate_operational_readiness,
        )

        report = evaluate_operational_readiness(project_root=settings.BASE_DIR)
        checks = {check.code: check for check in report.checks}

        expected_codes = {
            'settings.allowed_hosts_env_list',
            'settings.csrf_trusted_origins_env_list',
            'settings.secure_proxy_ssl_header',
            'entrypoint.app_startup_order',
            'entrypoint.worker_startup_scope',
            'docker_compose.vps_resilience',
            'docker_compose.vps_network_isolation',
            'cloudflare_tunnel.readiness',
            'docker_compose.local_services',
            'startup.initial_migration_window',
            'ui.responsive_design_system',
            'async.celery_services',
            'docs.deployment_and_backup',
        }

        assert report.passed is True
        assert expected_codes.issubset(checks)
        assert all(check.status == OperationalCheckStatus.PASS for check in checks.values())
        assert '--clear' in checks['entrypoint.app_startup_order'].evidence
        assert 'celery_worker' in checks['async.celery_services'].evidence
        assert 'rede backend' in checks['docker_compose.vps_network_isolation'].evidence

    def test_nfr_command_outputs_json_report_for_operational_readiness(self):
        stdout = StringIO()

        call_command('check_operational_readiness', format='json', stdout=stdout)

        payload = json.loads(stdout.getvalue())
        assert payload['passed'] is True
        assert {item['status'] for item in payload['checks']} == {'pass'}
        assert 'docker_compose.vps_resilience' in {item['code'] for item in payload['checks']}

    def test_nfr_vps_compose_declares_resilience_for_every_service(self):
        compose_path = Path(settings.BASE_DIR) / 'docker-compose.vps.yml'
        compose = yaml.safe_load(compose_path.read_text(encoding='utf-8'))
        services = compose['services']

        for service_name, service in services.items():
            assert service.get('healthcheck'), f'{service_name} sem healthcheck'
            assert service.get('restart') == 'unless-stopped', f'{service_name} sem restart'

        assert services['nginx']['ports'] == ['127.0.0.1:8081:80']
        assert services['cloudflared']['network_mode'] == 'host'
        assert (
            '${CLOUDFLARED_METRICS_ADDRESS:-127.0.0.1:20249}' in services['cloudflared']['command']
        )

    def test_worker_entrypoint_waits_for_migrations_without_running_them(self):
        source = (Path(settings.BASE_DIR) / 'worker-entrypoint.sh').read_text(encoding='utf-8')

        assert 'python manage.py wait_for_db' in source
        assert 'python manage.py wait_for_migrations' in source
        assert 'MIGRATION_WAIT_TIMEOUT:-900' in source
        assert (
            source.find('wait_for_db')
            < source.find('wait_for_migrations')
            < source.find('exec "$@"')
        )
        assert 'migrate_with_lock' not in source
        assert 'collectstatic' not in source

    def test_startup_healthchecks_allow_initial_migration_window(self):
        compose = yaml.safe_load(
            (Path(settings.BASE_DIR) / 'docker-compose.yml').read_text(encoding='utf-8')
        )
        vps_compose = yaml.safe_load(
            (Path(settings.BASE_DIR) / 'docker-compose.vps.yml').read_text(encoding='utf-8')
        )

        assert _duration_seconds(compose['services']['app']['healthcheck']['start_period']) >= 600
        assert (
            _duration_seconds(vps_compose['services']['app']['healthcheck']['start_period']) >= 600
        )
        assert (
            _duration_seconds(
                vps_compose['services']['celery_worker']['healthcheck']['start_period']
            )
            >= 600
        )
        assert (
            _duration_seconds(vps_compose['services']['celery_beat']['healthcheck']['start_period'])
            >= 600
        )

    def test_vps_compose_allows_initial_migration_window(self):
        compose = yaml.safe_load(
            (Path(settings.BASE_DIR) / 'docker-compose.vps.yml').read_text(encoding='utf-8')
        )

        assert _duration_seconds(compose['services']['app']['healthcheck']['start_period']) >= 600


def _duration_seconds(value):
    if isinstance(value, int):
        return value
    if value.endswith('s'):
        return int(value[:-1])
    if value.endswith('m'):
        return int(value[:-1]) * 60
    raise AssertionError(f'Duração não suportada: {value}')
