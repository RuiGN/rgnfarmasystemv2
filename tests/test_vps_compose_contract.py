from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def _vps_compose():
    return yaml.safe_load((ROOT / 'docker-compose.vps.yml').read_text(encoding='utf-8'))


def test_vps_compose_has_healthchecks_and_restart_policy_for_every_service():
    services = _vps_compose()['services']

    assert {
        'app',
        'nginx',
        'celery_worker',
        'celery_beat',
        'db',
        'redis',
        'rabbitmq',
        'backup_scheduler',
        'cloudflared',
    } == set(services)
    for service_name, service in services.items():
        assert service.get('restart') == 'unless-stopped', service_name
        assert service.get('healthcheck'), service_name


def test_backup_service_uses_private_database_and_read_only_media_without_engine_socket():
    compose = _vps_compose()
    service = compose['services']['backup_scheduler']

    assert service['environment']['DB_DEPLOYMENT'] == 'external'
    assert service['environment']['DB_HOST'] == 'db'
    assert 'media:/app/media:ro' in service['volumes']
    assert not any('/var/run/docker.sock' in volume for volume in service['volumes'])
    assert service['depends_on']['app']['condition'] == 'service_healthy'
    assert service['depends_on']['db']['condition'] == 'service_healthy'
    assert service['entrypoint'] == ['/app/scripts/backup_scheduler.sh']
    assert 'secrets' not in service
    assert 'secrets' not in compose


def test_tunnel_readiness_is_exposed_only_on_the_host_loopback():
    services = _vps_compose()['services']
    tunnel = services['cloudflared']

    assert services['nginx']['ports'] == ['127.0.0.1:8081:80']
    assert tunnel['network_mode'] == 'host'
    assert '${CLOUDFLARED_METRICS_ADDRESS:-127.0.0.1:20249}' in tunnel['command']
    assert 'ports' not in tunnel


def test_deploy_script_backs_up_before_update_and_has_automatic_code_rollback():
    source = (ROOT / 'scripts' / 'deploy-vps.sh').read_text(encoding='utf-8')
    main = source[source.index('main()') :]

    assert main.index('create_release_backup') < main.index('promote_revision')
    assert main.index('promote_revision') < main.index('deploy_compose')
    assert 'rollback_release' in source
    assert 'docker compose' in source
    assert (
        'compose up -d --build --remove-orphans --wait'
        in source[source.index('rollback_release()') :]
    )
