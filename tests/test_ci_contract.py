from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml
from django.core.management import call_command


WORKFLOW = Path('.github/workflows/quality.yml')
WORKFLOW_DIRECTORY = Path('.github/workflows')
QUALITY_GATE = Path('scripts/ci/quality-gate.sh')
REQUIREMENTS = Path('requirements.txt')
DEMO_SEEDER = Path('governance/demo_seeders.py')


def test_quality_workflow_declares_required_services_and_evidence():
    assert WORKFLOW.exists()
    source = WORKFLOW.read_text(encoding='utf-8')

    required_markers = (
        'postgres:',
        'redis:',
        'rabbitmq:',
        'gitleaks',
        'scripts/ci/quality-gate.sh',
        'docker build',
        'actions/upload-artifact',
        'coverage.xml',
        'openapi-schema.yml',
        'sbom.cdx.json',
    )
    missing = [marker for marker in required_markers if marker not in source]

    assert missing == []


def test_gitleaks_receives_github_token_for_pull_request_scans():
    source = WORKFLOW.read_text(encoding='utf-8')

    assert 'GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}' in source
    assert 'pull-requests: read' in source


def test_quality_workflow_configures_trusted_csrf_origin():
    source = WORKFLOW.read_text(encoding='utf-8')

    assert 'CSRF_TRUSTED_ORIGINS: https://app.example.invalid' in source


def test_workflows_use_node24_compatible_action_majors():
    required_refs = {
        'actions/checkout': 'v6',
        'actions/setup-python': 'v6',
        'actions/upload-artifact': 'v6',
        'gitleaks/gitleaks-action': 'v3',
    }
    observed_actions = set()
    violations = []

    def collect_uses(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'uses':
                    yield str(item)
                yield from collect_uses(item)
        elif isinstance(value, list):
            for item in value:
                yield from collect_uses(item)

    workflow_paths = sorted(WORKFLOW_DIRECTORY.glob('*.y*ml'))
    for workflow_path in workflow_paths:
        workflow = yaml.safe_load(workflow_path.read_text(encoding='utf-8'))
        for action_ref in collect_uses(workflow):
            action, separator, ref = action_ref.rpartition('@')
            if separator and action in required_refs:
                observed_actions.add(action)
                if ref != required_refs[action]:
                    violations.append(f'{workflow_path}:{action_ref}')

    assert observed_actions == set(required_refs)
    assert violations == []


def test_quality_gate_runs_every_mandatory_check():
    assert QUALITY_GATE.exists()
    source = QUALITY_GATE.read_text(encoding='utf-8')

    required_commands = (
        'manage.py check',
        'manage.py check --deploy',
        'makemigrations --check --dry-run',
        'ruff check',
        'ruff format --check',
        'mypy',
        'bandit',
        'python -m pip_audit',
        'pytest',
        '--cov-fail-under=80',
        'spectacular --file openapi-schema.yml --validate --fail-on-warn',
        'check_operational_readiness --fail-on-error',
        'check_backup_restore_readiness --fail-on-error',
        'check_product_acceptance --fail-on-error',
        'check_release_readiness --fail-on-error',
    )
    missing = [command for command in required_commands if command not in source]

    assert missing == []


def test_runtime_dependencies_use_audited_compatible_versions():
    requirements = set(REQUIREMENTS.read_text(encoding='utf-8').splitlines())
    requirements.update(Path('requirements-dev.txt').read_text(encoding='utf-8').splitlines())

    required_versions = {
        'Django==6.0.8',
        'langchain==1.3.17',
        'langchain-openai==1.6.0',
        'langgraph==1.2.11',
        'langgraph-checkpoint==4.2.0',
        'langgraph-sdk==0.4.4',
        'openai==3.3.1',
        'protobuf==7.36.0',
        'pypdf==6.19.0',
        'pytest==9.1.1',
        'websockets==16.1.1',
    }

    assert required_versions <= requirements
    assert not any(line.startswith('google-generativeai==') for line in requirements)


def test_demo_data_does_not_embed_a_shared_password():
    source = DEMO_SEEDER.read_text(encoding='utf-8')

    assert 'Demo@12345' not in source
    assert 'settings.DEMO_USER_PASSWORD' in source


def test_openapi_schema_is_generated_without_warnings():
    with NamedTemporaryFile(suffix='.yml') as schema_file:
        call_command(
            'spectacular',
            file=schema_file.name,
            validate=True,
            fail_on_warn=True,
        )
