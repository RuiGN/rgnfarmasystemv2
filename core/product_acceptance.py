import json
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from django.conf import settings
from django.contrib import admin
from django.core.management import get_commands
from django.urls import NoReverseMatch, Resolver404, resolve, reverse


class ProductAcceptanceCheckStatus(str, Enum):
    PASS = 'pass'  # nosec B105
    FAIL = 'fail'
    WARNING = 'warning'


@dataclass(frozen=True)
class ProductAcceptanceCheck:
    code: str
    title: str
    status: ProductAcceptanceCheckStatus
    evidence: str

    def to_dict(self):
        return {
            'code': self.code,
            'title': self.title,
            'status': self.status.value,
            'evidence': self.evidence,
        }


@dataclass(frozen=True)
class ProductAcceptanceReport:
    checks: tuple[ProductAcceptanceCheck, ...]

    @property
    def passed(self):
        return all(check.status == ProductAcceptanceCheckStatus.PASS for check in self.checks)

    def to_dict(self):
        return {
            'passed': self.passed,
            'checks': [check.to_dict() for check in self.checks],
        }

    def to_json(self):
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def evaluate_product_acceptance(project_root=None):
    root = Path(project_root or settings.BASE_DIR)
    core_urls = _read(root / 'core' / 'urls.py')
    api_v1_urls = _read(root / 'core' / 'api_v1_urls.py')
    sidebar_template = _read(root / 'templates' / 'includes' / 'sidebar.html')
    ui_context_processor = _read(root / 'base' / 'ui' / 'context_processors.py')
    readme = _read(root / 'README.md')
    mkdocs = _read(root / 'mkdocs.yml')
    docs_index = _read(root / 'docs' / 'index.md')
    deployment_docs = _read(root / 'docs' / 'deployment.md')
    compliance_docs = _read(root / 'docs' / 'architecture' / 'compliance.md')
    operational_docs = _read(root / 'docs' / 'architecture' / 'operational-readiness.md')
    backup_restore_docs = _read(root / 'docs' / 'architecture' / 'backup-restore.md')
    product_acceptance_docs = _read(root / 'docs' / 'architecture' / 'product-acceptance.md')
    prd = _read(root / 'PRD.md')

    checks = [
        _core_routes_check(core_urls),
        _single_login_check(),
        _api_v1_modules_check(api_v1_urls),
        _admin_menus_check(
            sidebar_template,
            ui_context_processor,
            core_urls,
        ),
        _commands_check(),
        _docs_check(
            readme,
            mkdocs,
            docs_index,
            deployment_docs,
            compliance_docs,
            operational_docs,
            backup_restore_docs,
            product_acceptance_docs,
        ),
        _prd_check(prd),
        _security_check(
            '\n'.join(
                [
                    readme,
                    deployment_docs,
                    operational_docs,
                    backup_restore_docs,
                    product_acceptance_docs,
                ]
            )
        ),
    ]
    return ProductAcceptanceReport(tuple(checks))


def _read(path):
    try:
        return path.read_text(encoding='utf-8')
    except FileNotFoundError:
        return ''


def _check(code, title, passed, pass_evidence, fail_evidence):
    return ProductAcceptanceCheck(
        code=code,
        title=title,
        status=ProductAcceptanceCheckStatus.PASS if passed else ProductAcceptanceCheckStatus.FAIL,
        evidence=pass_evidence if passed else fail_evidence,
    )


def _core_routes_check(core_urls):
    route_names = ('health', 'home', 'schema', 'swagger-ui', 'admin:index')
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
        "path('admin/'",
    )
    missing_source = [item for item in required_source if item not in core_urls]
    passed = not unresolved and not missing_source
    return _check(
        'routes.core_entrypoints',
        'Rotas principais carregaveis',
        passed,
        'Rotas /health/, /, /api/v1/, /api/schema/, /api/docs/ e admin estao registradas.',
        'Rotas principais ausentes ou nao resolviveis: ' + ', '.join(unresolved + missing_source),
    )


def _single_login_check():
    try:
        shared_login = reverse('accounts:login') == '/accounts/login/'
    except NoReverseMatch:
        shared_login = False
    try:
        admin_login_is_shared = resolve('/admin/login/').func != admin.site.login
    except Resolver404:
        admin_login_is_shared = False
    try:
        resolve('/platform/')
    except Resolver404:
        legacy_platform_removed = True
    else:
        legacy_platform_removed = False
    return _check(
        'auth.single_login',
        'Tela única de login',
        shared_login
        and admin_login_is_shared
        and legacy_platform_removed
        and settings.LOGIN_REDIRECT_URL == '/app/',
        '/accounts/login/ é a única view de autenticação e o destino padrão é /app/.',
        'O login compartilhado, o redirecionamento para /app/ ou a remoção do login paralelo não está vigente.',
    )


def _api_v1_modules_check(api_v1_urls):
    required_modules = (
        'accounts',
        'masters',
        'formulations',
        'production',
        'planning',
        'procurement',
        'inventory',
        'costing',
        'finance',
        'fiscal',
        'crm',
        'quality',
        'qa',
        'documents',
        'deviations',
        'capa',
        'changes',
        'audits',
        'risks',
        'recalls',
        'training',
        'files',
        'reports',
        'workflow',
        'integrations',
        'ai_agents',
        'governance',
        'compliance',
    )
    missing = [module for module in required_modules if module not in api_v1_urls]
    return _check(
        'routes.api_v1_modules',
        'Modulos publicados em API v1',
        not missing,
        'Namespace /api/v1/ inclui os modulos principais sem rota operacional legada.',
        'Modulos ausentes em /api/v1/: ' + ', '.join(missing),
    )


def _admin_menus_check(sidebar_template, ui_context_processor, core_urls):
    standard_admin_is_registered = (
        admin.site.name == 'admin'
        and reverse('admin:index') == '/admin/'
        and "path('admin/', admin.site.urls)" in core_urls
    )
    boundary_isolated = (
        'admin:' not in sidebar_template
        and "'sidebar_admin_links': ()" in ui_context_processor
        and standard_admin_is_registered
    )
    return _check(
        'ui.admin_menus',
        'Fronteira do admin tecnico',
        boundary_isolated,
        'Django Admin padrão está registrado em /admin/ e ausente da sidebar operacional.',
        'O Django Admin padrão ou sua separação da sidebar operacional está incompleto.',
    )


def _commands_check():
    commands = get_commands()
    required_commands = (
        'check_operational_readiness',
        'check_backup_restore_readiness',
        'check_transversal_compliance',
        'check_product_acceptance',
    )
    missing = [command for command in required_commands if command not in commands]
    return _check(
        'commands.operational_gates',
        'Comandos operacionais de aceite',
        not missing,
        'Comandos operacionais de prontidao, backup, compliance e aceite estao registrados.',
        'Comandos operacionais ausentes: ' + ', '.join(missing),
    )


def _docs_check(
    readme,
    mkdocs,
    docs_index,
    deployment_docs,
    compliance_docs,
    operational_docs,
    backup_restore_docs,
    product_acceptance_docs,
):
    requirements = {
        'README.md:check_product_acceptance': 'check_product_acceptance' in readme,
        'mkdocs.yml:product_acceptance': 'architecture/product-acceptance.md' in mkdocs,
        'docs/index.md:aceite': _contains_any(
            docs_index, ('Aceite tecnico', 'aceite tecnico', 'Aceite técnico', 'aceite técnico')
        ),
        'docs/deployment.md:check_product_acceptance': 'check_product_acceptance'
        in deployment_docs,
        'compliance.md:check_transversal_compliance': 'check_transversal_compliance'
        in compliance_docs,
        'operational-readiness.md:check_operational_readiness': 'check_operational_readiness'
        in operational_docs,
        'backup-restore.md:check_backup_restore_readiness': 'check_backup_restore_readiness'
        in backup_restore_docs,
        'product-acceptance.md:canonical': (
            'check_product_acceptance' in product_acceptance_docs
            and _contains_any(
                product_acceptance_docs, ('Criterio de Aceitacao', 'Critério de Aceitação')
            )
        ),
    }
    missing = [name for name, present in requirements.items() if not present]
    return _check(
        'docs.product_acceptance',
        'Documentacao navegavel de aceite',
        not missing,
        'README, MKDocs, deploy e arquitetura documentam check_product_acceptance e os gates relacionados.',
        'Documentacao de aceite incompleta: ' + ', '.join(missing),
    )


def _prd_check(prd):
    passed = all(
        marker in prd
        for marker in (
            '# PRD — RGN Farma System',
            'Status: vigente',
            'single-instance',
            'check_product_acceptance --fail-on-error',
        )
    )
    return _check(
        'prd.sprint_35_recorded',
        'PRD vigente registra o gate de aceite técnico',
        passed,
        'PRD.md vigente registra arquitetura single-instance e check_product_acceptance.',
        'PRD.md vigente não registra arquitetura single-instance e check_product_acceptance.',
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
        'Sem segredos reais em docs de aceite',
        not leaked,
        'Documentacao de aceite e operacao usa variaveis simbolicas, sem tokens reais detectados.',
        'Possivel segredo real detectado por padrao: ' + ', '.join(leaked),
    )


def _contains_any(source, candidates):
    return any(candidate in source for candidate in candidates)
