from pathlib import Path
import os
import shutil
import subprocess

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ('filename', 'job'), [('quality.yml', 'quality'), ('release.yml', 'gates')]
)
def test_ci_provisions_node_before_the_quality_gate(filename, job):
    workflow = yaml.safe_load((ROOT / '.github/workflows' / filename).read_text())
    steps = workflow['jobs'][job]['steps']
    node_indexes = [
        index
        for index, step in enumerate(steps)
        if step.get('uses') == 'actions/setup-node@v6'
        and str(step.get('with', {}).get('node-version')) == '24'
    ]
    gate_indexes = [
        index
        for index, step in enumerate(steps)
        if 'bash scripts/ci/quality-gate.sh' in step.get('run', '')
        or step.get('run', '').startswith('pytest ')
    ]
    assert node_indexes and gate_indexes
    assert node_indexes[0] < gate_indexes[0]


def test_release_installs_dev_tools_and_runs_the_complete_gate():
    workflow = yaml.safe_load((ROOT / '.github/workflows/release.yml').read_text())
    steps = workflow['jobs']['gates']['steps']
    commands = [step.get('run', '') for step in steps]
    dependencies = [
        index for index, command in enumerate(commands) if 'requirements-dev.txt' in command
    ]
    gates = [
        index
        for index, command in enumerate(commands)
        if 'bash scripts/ci/quality-gate.sh' in command
    ]
    assert dependencies and gates
    assert dependencies[0] < gates[0]
    assert not any(command.strip() == 'pytest -q' for command in commands)
    environment = workflow['jobs']['gates']['env']
    assert environment['SECURE_HSTS_SECONDS'] == '31536000'
    assert environment['SECURE_HSTS_INCLUDE_SUBDOMAINS'] == 'True'
    assert environment['SECURE_HSTS_PRELOAD'] == 'True'


def test_quality_gate_fails_when_node_is_absent_instead_of_skipping(tmp_path):
    bash = shutil.which('bash')
    assert bash is not None
    result = subprocess.run(
        [bash, str(ROOT / 'scripts/ci/quality-gate.sh')],
        cwd=ROOT,
        env={**os.environ, 'PATH': str(tmp_path), 'TEST_DATABASE_URL': 'synthetic-not-connected'},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode != 0
    assert 'node' in result.stderr
    source = (ROOT / 'scripts/ci/quality-gate.sh').read_text()
    assert 'node --test tests/js/local-printing.test.cjs' in source


def test_tunnel_runbook_sets_the_authoritative_address_for_its_probe():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text()
    assert 'CLOUDFLARED_METRICS_ADDRESS=127.0.0.1:20242' in source
    assert 'http://127.0.0.1:20242/ready' in source
