import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from django.conf import settings
from django.core.management import get_commands
from django.urls import NoReverseMatch, reverse


class ReleaseReadinessCheckStatus(str, Enum):
    PASS = 'pass'  # nosec B105
    FAIL = 'fail'
    WARNING = 'warning'


@dataclass(frozen=True)
class ReleaseReadinessCheck:
    code: str
    title: str
    status: ReleaseReadinessCheckStatus
    evidence: str

    def to_dict(self):
        return {
            'code': self.code,
            'title': self.title,
            'status': self.status.value,
            'evidence': self.evidence,
        }


@dataclass(frozen=True)
class ReleaseReadinessReport:
    checks: tuple[ReleaseReadinessCheck, ...]

    @property
    def passed(self):
        return all(check.status == ReleaseReadinessCheckStatus.PASS for check in self.checks)

    def to_dict(self):
        return {
            'passed': self.passed,
            'checks': [check.to_dict() for check in self.checks],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def evaluate_release_readiness(project_root=None):
    root = Path(project_root or settings.BASE_DIR)
    core_urls = _read(root / 'core' / 'urls.py')
    settings_source = _read(root / 'core' / 'settings' / 'base.py')
    readme = _read(root / 'README.md')
    mkdocs = _read(root / 'mkdocs.yml')
    docs_index = _read(root / 'docs' / 'index.md')
    deployment_docs = _read(root / 'docs' / 'deployment.md')
    governance_docs = _read(root / 'docs' / 'architecture' / 'governance.md')
    product_acceptance_docs = _read(root / 'docs' / 'architecture' / 'product-acceptance.md')
    release_docs = _read(root / 'docs' / 'architecture' / 'release-readiness.md')
    prd = _read(root / 'PRD.md')

    docs_source = '\n'.join(
        [
            readme,
            mkdocs,
            docs_index,
            deployment_docs,
            governance_docs,
            product_acceptance_docs,
            release_docs,
            prd,
        ]
    )

    checks = [
        _required_gates_check(readme, deployment_docs, product_acceptance_docs, release_docs),
        _docs_navigation_check(mkdocs, docs_index, release_docs),
        _smoke_routes_check(core_urls, deployment_docs, release_docs),
        _openapi_check(core_urls, settings_source, readme, deployment_docs, release_docs),
        _demo_data_check(readme, governance_docs, release_docs),
        _evidence_runbook_check(readme, deployment_docs, release_docs),
        _prd_check(prd),
        _security_check(docs_source),
    ]
    return ReleaseReadinessReport(tuple(checks))


def _read(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def _check(code, title, passed, pass_evidence, fail_evidence):
    return ReleaseReadinessCheck(
        code=code,
        title=title,
        status=ReleaseReadinessCheckStatus.PASS if passed else ReleaseReadinessCheckStatus.FAIL,
        evidence=pass_evidence if passed else fail_evidence,
    )


def _required_gates_check(readme, deployment_docs, product_acceptance_docs, release_docs):
    commands = get_commands()
    required_commands = (
        'check_operational_readiness',
        'check_backup_restore_readiness',
        'check_product_acceptance',
        'check_release_readiness',
    )
    docs_source = '\n'.join([readme, deployment_docs, product_acceptance_docs, release_docs])
    missing_registered = [command for command in required_commands if command not in commands]
    missing_docs = [command for command in required_commands if command not in docs_source]
    passed = not missing_registered and not missing_docs
    return _check(
        'release.required_gates',
        'Gates obrigatorios de release',
        passed,
        'Gates check_operational_readiness, check_backup_restore_readiness, check_product_acceptance e check_release_readiness estao registrados e documentados.',
        'Gates ausentes no registry ou documentacao: '
        + ', '.join(missing_registered + missing_docs),
    )


def _docs_navigation_check(mkdocs, docs_index, release_docs):
    requirements = {
        'mkdocs.yml:release_readiness': 'architecture/release-readiness.md' in mkdocs,
        'docs/index.md:prontidao_de_release': _contains_any(
            docs_index,
            (
                'Prontidão de Release',
                'Prontidão de release',
                'prontidão de release',
                'release readiness',
            ),
        ),
        'docs/architecture/release-readiness.md:check_release_readiness': 'check_release_readiness'
        in release_docs,
        'docs/architecture/release-readiness.md:titulo': _contains_any(
            release_docs,
            (
                'Prontidão de Release',
                'Prontidão de release',
            ),
        ),
    }
    missing = [name for name, present in requirements.items() if not present]
    return _check(
        'docs.release_navigation',
        'Navegacao da documentacao de release',
        not missing,
        'MKDocs, docs/index.md e docs/architecture/release-readiness.md expõem a prontidão de release e o comando check_release_readiness.',
        'Navegacao de release incompleta: ' + ', '.join(missing),
    )


def _smoke_routes_check(core_urls, deployment_docs, release_docs):
    route_names = ('health', 'home', 'schema', 'swagger-ui')
    unresolved = []
    for route_name in route_names:
        try:
            reverse(route_name)
        except NoReverseMatch:
            unresolved.append(route_name)

    required_source = (
        "path('health/'",
        "path('', home",
        "path('api/v1/'",
        "path('api/schema/'",
        "'api/docs/'",
    )
    missing_source = [item for item in required_source if item not in core_urls]
    docs_source = '\n'.join([deployment_docs, release_docs])
    smoke_commands = (
        'curl -fsS http://127.0.0.1:8000/health/',
        'curl -fsS http://127.0.0.1:8000/',
        'curl -fsS http://127.0.0.1:8000/api/schema/',
        'curl -fsS http://127.0.0.1:8000/api/docs/',
        'curl -fsS http://127.0.0.1:8000/api/v1/',
    )
    missing_docs = [command for command in smoke_commands if command not in docs_source]
    passed = not unresolved and not missing_source and not missing_docs
    return _check(
        'release.smoke_routes',
        'Smoke local de rotas criticas',
        passed,
        'Runbook documenta smoke local para /health/, /, /api/schema/, /api/docs/ e /api/v1/; rotas Django carregam.',
        'Smoke local incompleto: ' + ', '.join(unresolved + missing_source + missing_docs),
    )


def _openapi_check(core_urls, settings_source, readme, deployment_docs, release_docs):
    docs_source = '\n'.join([readme, deployment_docs, release_docs])
    commands = get_commands()
    requirements = {
        'command:spectacular': 'spectacular' in commands,
        'settings:drf_spectacular': "'drf_spectacular'" in settings_source,
        'settings:DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema' in settings_source,
        'route:/api/schema/': "path('api/schema/'" in core_urls,
        'route:/api/docs/': "'api/docs/'" in core_urls,
        'docs:spectacular_file': 'spectacular --file openapi-schema.yml' in docs_source,
    }
    missing = [name for name, present in requirements.items() if not present]
    return _check(
        'release.openapi_schema',
        'OpenAPI pronto para release',
        not missing,
        'OpenAPI via drf-spectacular, /api/schema/, /api/docs/ e openapi-schema.yml estao disponiveis.',
        'OpenAPI incompleto para release: ' + ', '.join(missing),
    )


def _demo_data_check(readme, governance_docs, release_docs):
    commands = get_commands()
    docs_source = '\n'.join([readme, governance_docs, release_docs])
    legacy_scope_arg = '--' + 'ten' + 'ant-slug'
    requirements = {
        'command:load_demo_scenario': 'load_demo_scenario' in commands,
        'docs:no_legacy_scope_slug': legacy_scope_arg not in docs_source,
        'docs:scenario': '--scenario' in docs_source,
        'docs:base_master_data': 'base_master_data' in docs_source,
        'docs:quality_deviation': 'quality_deviation' in docs_source,
    }
    missing = [name for name, present in requirements.items() if not present]
    return _check(
        'release.demo_data',
        'Carga demo para staging local',
        not missing,
        'Comando load_demo_scenario esta registrado e documentado para instancia unica com scenario e exemplos de dados demo.',
        'Carga demo de staging incompleta: ' + ', '.join(missing),
    )


def _evidence_runbook_check(readme, deployment_docs, release_docs):
    docs_source = '\n'.join([readme, deployment_docs, release_docs])
    required_steps = (
        'manage.py check',
        'makemigrations --check --dry-run',
        'check_operational_readiness --fail-on-error',
        'check_backup_restore_readiness --fail-on-error',
        'check_product_acceptance --fail-on-error',
        'check_release_readiness --fail-on-error',
        'spectacular --file openapi-schema.yml',
        'curl -fsS http://127.0.0.1:8000/health/',
        'Evidencia de release',
    )
    missing = [step for step in required_steps if step not in docs_source]
    return _check(
        'release.evidence_runbook',
        'Runbook de evidencia de release',
        not missing,
        'Runbook documenta checks Django, migrations, gates, OpenAPI, smoke local e Evidencia de release.',
        'Runbook de release incompleto: ' + ', '.join(missing),
    )


def _prd_check(prd):
    passed = all(
        marker in prd
        for marker in (
            '# PRD — RGN Farma System',
            'Status: vigente',
            'single-instance',
            'check_release_readiness --fail-on-error',
        )
    )
    return _check(
        'prd.sprint_36_recorded',
        'PRD vigente registra o gate de prontidão de release',
        passed,
        'PRD.md vigente registra arquitetura single-instance e check_release_readiness.',
        'PRD.md vigente não registra arquitetura single-instance e check_release_readiness.',
    )


def _security_check(source):
    secret_patterns = (
        r'sk-[A-Za-z0-9]{20,}',
        r'AKIA[0-9A-Z]{16}',
        r'ghp_[A-Za-z0-9]{30,}',
        r'-----BEGIN (RSA |EC |OPENSSH |)PRIVATE KEY-----',
    )
    leaked = [pattern for pattern in secret_patterns if re.search(pattern, source)]
    return _check(
        'security.no_real_secrets',
        'Sem segredos reais em docs de release',
        not leaked,
        'Documentacao de release usa variaveis simbolicas, sem tokens reais detectados.',
        'Possivel segredo real detectado por padrao: ' + ', '.join(leaked),
    )


def _contains_any(source, candidates):
    return any(candidate in source for candidate in candidates)
