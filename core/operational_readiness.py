import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import yaml
from django.conf import settings


class OperationalCheckStatus(str, Enum):
    # Bandit B105: readiness status, not a password.
    PASS = 'pass'  # nosec B105
    FAIL = 'fail'
    WARNING = 'warning'


@dataclass(frozen=True)
class OperationalCheck:
    code: str
    title: str
    status: OperationalCheckStatus
    evidence: str

    def to_dict(self):
        return {
            'code': self.code,
            'title': self.title,
            'status': self.status.value,
            'evidence': self.evidence,
        }


@dataclass(frozen=True)
class OperationalReadinessReport:
    checks: tuple[OperationalCheck, ...]

    @property
    def passed(self):
        return all(check.status == OperationalCheckStatus.PASS for check in self.checks)

    def to_dict(self):
        return {
            'passed': self.passed,
            'checks': [check.to_dict() for check in self.checks],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def evaluate_operational_readiness(project_root=None):
    root = Path(project_root or settings.BASE_DIR)
    vps_compose = _load_yaml(root / 'docker-compose.vps.yml')
    local_compose = _load_yaml(root / 'docker-compose.yml')
    settings_source = _settings_source(root)
    entrypoint_source = _read(root / 'entrypoint.sh')
    worker_entrypoint_source = _read(root / 'worker-entrypoint.sh')
    css_source = _read(root / 'static' / 'css' / 'app.css')
    base_template_source = _read(root / 'templates' / 'base.html')
    deployment_docs = _read(root / 'docs' / 'deployment.md')
    deploy_script = _read(root / 'scripts' / 'deploy-vps.sh')
    backup_script = _read(root / 'scripts' / 'backup.sh')
    restore_script = _read(root / 'scripts' / 'restore.sh')

    checks = [
        _check(
            'settings.allowed_hosts_env_list',
            'ALLOWED_HOSTS por .env',
            'ALLOWED_HOSTS = env.list' in settings_source,
            'core/settings/base.py usa env.list para ALLOWED_HOSTS.',
            'core/settings/base.py nao usa env.list para ALLOWED_HOSTS.',
        ),
        _check(
            'settings.csrf_trusted_origins_env_list',
            'CSRF_TRUSTED_ORIGINS por .env',
            'CSRF_TRUSTED_ORIGINS = env.list' in settings_source,
            'core/settings/base.py usa env.list para CSRF_TRUSTED_ORIGINS.',
            'core/settings/base.py nao usa env.list para CSRF_TRUSTED_ORIGINS.',
        ),
        _check(
            'settings.secure_proxy_ssl_header',
            'Proxy SSL atras do Nginx e Cloudflare Tunnel',
            "SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')" in settings_source
            and 'SECURE_SSL_REDIRECT = env.bool' in settings_source,
            'SECURE_PROXY_SSL_HEADER e SECURE_SSL_REDIRECT estao configurados.',
            'Configuracao de proxy SSL/redirect seguro ausente.',
        ),
        _entrypoint_check(entrypoint_source),
        _worker_entrypoint_check(worker_entrypoint_source),
        _vps_resilience_check(vps_compose, deploy_script),
        _network_isolation_check(vps_compose),
        _tunnel_readiness_check(vps_compose, deploy_script),
        _compose_services_check(local_compose),
        _startup_window_check(vps_compose, local_compose, worker_entrypoint_source),
        _ui_check(css_source, base_template_source),
        _celery_check(settings_source, vps_compose, local_compose, worker_entrypoint_source),
        _filter_performance_check(settings_source),
        _docs_check(deployment_docs, deploy_script, backup_script, restore_script),
    ]
    return OperationalReadinessReport(tuple(checks))


def _check(code, title, passed, pass_evidence, fail_evidence):
    return OperationalCheck(
        code=code,
        title=title,
        status=OperationalCheckStatus.PASS if passed else OperationalCheckStatus.FAIL,
        evidence=pass_evidence if passed else fail_evidence,
    )


def _load_yaml(path):
    return yaml.safe_load(path.read_text(encoding='utf-8'))


def _read(path):
    return path.read_text(encoding='utf-8')


def _settings_source(root):
    settings_root = root / 'core' / 'settings'
    return '\n'.join(_read(settings_root / filename) for filename in ('base.py', 'production.py'))


def _entrypoint_check(source):
    steps = ['wait_for_db', 'migrate_with_lock', 'collectstatic --noinput --clear']
    positions = [source.find(step) for step in steps]
    passed = all(position >= 0 for position in positions) and positions == sorted(positions)
    return _check(
        'entrypoint.app_startup_order',
        'Startup ordenado do app',
        passed,
        'entrypoint.sh executa wait_for_db, migrate_with_lock e collectstatic --noinput --clear.',
        'entrypoint.sh nao comprova wait_for_db, migrate_with_lock e collectstatic --clear em ordem.',
    )


def _worker_entrypoint_check(source):
    steps = ['wait_for_db', 'wait_for_migrations', 'exec "$@"']
    positions = [source.find(step) for step in steps]
    passed = (
        all(position >= 0 for position in positions)
        and positions == sorted(positions)
        and 'migrate_with_lock' not in source
        and 'collectstatic' not in source
    )
    return _check(
        'entrypoint.worker_startup_scope',
        'Startup isolado dos workers',
        passed,
        'worker-entrypoint.sh aguarda banco e migrations aplicadas sem executar migrations nem collectstatic.',
        'worker-entrypoint.sh deve aguardar banco e migrations aplicadas sem executar migrations nem collectstatic.',
    )


def _vps_resilience_check(compose, deploy_script):
    missing = []
    for service_name, service in (compose.get('services') or {}).items():
        if not service.get('healthcheck'):
            missing.append(f'{service_name}:healthcheck')
        if service.get('restart') != 'unless-stopped':
            missing.append(f'{service_name}:restart')
    rollback_is_safe = (
        'rollback_release()' in deploy_script
        and 'git switch --detach "$PREVIOUS_SHA"' in deploy_script
        and 'Banco e midia nao foram restaurados automaticamente.' in deploy_script
        and deploy_script.find('create_release_backup') < deploy_script.find('promote_revision')
    )
    if not rollback_is_safe:
        missing.append('deploy-vps:rollback')
    return _check(
        'docker_compose.vps_resilience',
        'Resiliencia do Compose VPS',
        not missing,
        'Todos os servicos da VPS possuem healthcheck e restart; deploy preserva backup e rollback de codigo.',
        'Pendencias no Compose VPS: ' + ', '.join(missing),
    )


def _network_isolation_check(compose):
    services = compose.get('services') or {}
    networks = compose.get('networks') or {}
    passed = (
        networks.get('backend', {}).get('driver') == 'bridge'
        and all('ports' not in services.get(name, {}) for name in ('db', 'redis', 'rabbitmq'))
        and services.get('nginx', {}).get('ports') == ['127.0.0.1:8081:80']
        and services.get('cloudflared', {}).get('network_mode') == 'host'
        and all(
            services.get(name, {}).get('networks') == ['backend']
            for name in ('app', 'celery_worker', 'celery_beat', 'db', 'redis', 'rabbitmq')
        )
    )
    return _check(
        'docker_compose.vps_network_isolation',
        'Isolamento da rede de producao',
        passed,
        'Banco, filas, cache, app e workers ficam na rede backend; apenas Nginx usa loopback do host.',
        'A topologia da VPS nao isola os servicos internos ou publica portas indevidas.',
    )


def _tunnel_readiness_check(compose, deploy_script):
    tunnel = compose.get('services', {}).get('cloudflared', {})
    command = tunnel.get('command') or []
    address = '${CLOUDFLARED_METRICS_ADDRESS:-127.0.0.1:20249}'
    expected_healthcheck = ['CMD', 'cloudflared', 'tunnel', '--metrics', address, 'ready']
    passed = (
        tunnel.get('network_mode') == 'host'
        and '--metrics' in command
        and command[command.index('--metrics') + 1 : command.index('--metrics') + 2] == [address]
        and tunnel.get('healthcheck', {}).get('test') == expected_healthcheck
        and 'docker inspect --format' in deploy_script
        and '.State.Health.Status' in deploy_script
        and 'configure_tunnel_readiness' in deploy_script
        and 'https://${PUBLIC_HOST}/health/' in deploy_script
    )
    return _check(
        'cloudflare_tunnel.readiness',
        'Prontidao do Cloudflare Tunnel',
        passed,
        'O conector expoe /ready apenas no loopback e o deploy valida origem, conector e dominio publico.',
        'O conector ou o script de deploy nao comprovam prontidao ponta a ponta.',
    )


def _compose_services_check(compose):
    services = compose.get('services') or {}
    required = {'app', 'db', 'redis', 'rabbitmq', 'celery_worker', 'celery_beat'}
    app_depends = services.get('app', {}).get('depends_on') or {}
    passed = required.issubset(services) and all(
        app_depends.get(service, {}).get('condition') == 'service_healthy'
        for service in ('db', 'redis', 'rabbitmq')
    )
    return _check(
        'docker_compose.local_services',
        'Servicos locais minimos',
        passed,
        'docker-compose.yml contem app, db, redis, rabbitmq, celery_worker, celery_beat e depends_on healthy.',
        'docker-compose.yml nao cobre servicos locais minimos ou depends_on healthy.',
    )


def _startup_window_check(vps_compose, local_compose, worker_entrypoint_source):
    vps_services = vps_compose.get('services') or {}
    local_services = local_compose.get('services') or {}
    required_windows = [
        ('local.app', local_services.get('app', {}).get('healthcheck', {}).get('start_period')),
        ('vps.app', vps_services.get('app', {}).get('healthcheck', {}).get('start_period')),
        (
            'vps.celery_worker',
            vps_services.get('celery_worker', {}).get('healthcheck', {}).get('start_period'),
        ),
        (
            'vps.celery_beat',
            vps_services.get('celery_beat', {}).get('healthcheck', {}).get('start_period'),
        ),
    ]
    short = [
        f'{name}:{value}' for name, value in required_windows if _duration_seconds(value) < 600
    ]
    passed = not short and 'MIGRATION_WAIT_TIMEOUT:-900' in worker_entrypoint_source
    return _check(
        'startup.initial_migration_window',
        'Janela de primeira inicializacao',
        passed,
        'App e workers possuem janela minima de 600s para migrations iniciais; workers aguardam ate 900s.',
        'Janela insuficiente para migrations iniciais: ' + ', '.join(short),
    )


def _duration_seconds(value):
    if isinstance(value, int):
        return value
    if not isinstance(value, str):
        return 0
    if value.endswith('s'):
        return int(value[:-1])
    if value.endswith('m'):
        return int(value[:-1]) * 60
    return 0


def _ui_check(css_source, base_template_source):
    has_duralux_shell = (
        'vendor/duralux/css/bootstrap.min.css' in base_template_source
        and 'vendor/duralux/css/vendors.min.css' in base_template_source
        and 'vendor/duralux/css/theme.min.css' in base_template_source
        and 'vendor/duralux/js/vendors.min.js' in base_template_source
        and 'class="nxl-navigation"' in base_template_source
        and 'id="main-content" class="nxl-container app-shell"' in base_template_source
        and 'class="nxl-content"' in base_template_source
        and 'class="main-content"' in base_template_source
    )
    preserves_duralux_main_spacing = (
        '.nxl-content {\n    padding:' not in css_source
        and '.nxl-content {\n        padding:' not in css_source
        and '\n.page-header {' not in css_source
    )
    has_responsive_contract = (
        '@media (max-width: 1024px)' in css_source
        and '.nxl-header {\n        left: 0 !important;\n    }' in css_source
        and '.nxl-container {\n        margin-left: 0;\n    }' in css_source
        and '[data-ui="resource-filters"]' in css_source
    )
    avoids_legacy_mobile_offsets = (
        '@media (max-width: 960px)' not in css_source
        and 'left: 80px !important;' not in css_source
        and 'margin-left: 80px;' not in css_source
        and 'left: 64px !important;' not in css_source
        and 'margin-left: 64px;' not in css_source
    )
    passed = (
        has_duralux_shell
        and preserves_duralux_main_spacing
        and has_responsive_contract
        and avoids_legacy_mobile_offsets
    )
    return _check(
        'ui.responsive_design_system',
        'UI responsiva alinhada ao design system',
        passed,
        'Shell usa assets/classes Duralux e CSS local preserva o espacamento nativo do main responsivo.',
        'Shell ou CSS local nao preservam o contrato responsivo do design system Duralux.',
    )


def _celery_check(settings_source, vps_compose, local_compose, worker_entrypoint_source):
    vps_services = vps_compose.get('services') or {}
    local_services = local_compose.get('services') or {}
    passed = (
        'CELERY_BROKER_URL' in settings_source
        and 'CELERY_RESULT_BACKEND' in settings_source
        and {'celery_worker', 'celery_beat'}.issubset(vps_services)
        and {'celery_worker', 'celery_beat'}.issubset(local_services)
        and 'wait_for_migrations' in worker_entrypoint_source
        and 'migrate_with_lock' not in worker_entrypoint_source
    )
    return _check(
        'async.celery_services',
        'Processamento assincrono',
        passed,
        'Celery configurado com celery_worker e celery_beat nos perfis local e VPS, aguardando migrations sem executa-las.',
        'Celery worker/beat ou escopo dos workers nao estao configurados corretamente.',
    )


def _filter_performance_check(settings_source):
    passed = (
        'django_filters.rest_framework.DjangoFilterBackend' in settings_source
        and "'PAGE_SIZE': 50" in settings_source
        and 'DEFAULT_PAGINATION_CLASS' in settings_source
    )
    return _check(
        'api.filter_pagination_performance',
        'Filtros e paginacao padrao',
        passed,
        'DRF usa DjangoFilterBackend e paginacao padrao para listas empresariais.',
        'Filtros ou paginacao padrao do DRF nao foram encontrados.',
    )


def _docs_check(deployment_docs, deploy_script, backup_script, restore_script):
    passed = (
        'docker compose -f docker-compose.vps.yml' in deployment_docs
        and 'rgnfarmasystem.rgnsystems.com.br' in deployment_docs
        and '127.0.0.1:8081' in deployment_docs
        and 'Cloudflare Tunnel' in deployment_docs
        and deployment_docs.find('backup') < deployment_docs.find('migrate')
        and 'pg_dump' in backup_script
        and 'RETENTION_DAYS' in backup_script
        and 'scripts/backup.sh' in restore_script
        and '--dry-run' in restore_script
    )
    return _check(
        'docs.deployment_and_backup',
        'Documentacao e scripts operacionais',
        passed,
        'Deploy Compose single-domain, Cloudflare Tunnel, backup PostgreSQL/media, rotacao e restore dry-run estao documentados ou scriptados.',
        'Documentacao ou scripts de deploy/backup/restore nao cobrem os requisitos operacionais.',
    )
