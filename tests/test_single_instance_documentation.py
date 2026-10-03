import hashlib
from pathlib import Path
import re

import yaml

from core.evidence_audit import evaluate_evidence_catalog


ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_ACTION_HASH = 'c5a622328b62e9dc3b2383f8e266d9c6a22a7af4e1eff75e107015b7b4297ea9'
# Recapturado após executar o catálogo corrente; o hash histórico permanece intacto.
CURRENT_ACTION_HASH = '32135d1fda299878281720b9095ca224653f1663694b8abbee27ff170de58388'


def _read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def _level_two_section(source, heading):
    pattern = re.compile(
        rf'^## {re.escape(heading)}\s*$\n(?P<body>.*?)(?=^## |\Z)',
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(source)
    assert match is not None, f'Seção ausente: {heading}'
    return match.group('body')


def _two_column_markdown_rows(section):
    rows = {}
    for line in section.splitlines():
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip('|').split('|')]
        if len(cells) != 2 or set(cells[0]) <= {'-', ':'}:
            continue
        rows[cells[0]] = cells[1]
    return rows


def test_mkdocs_publishes_single_instance_admin_and_domain_actions():
    navigation = _read('mkdocs.yml')

    assert 'Administração single-instance: architecture/admin-single-instance.md' in navigation
    assert 'Ações operacionais: architecture/domain-actions.md' in navigation
    assert 'Administração da plataforma' not in navigation
    assert (ROOT / 'docs/architecture/admin-single-instance.md').is_file()
    assert (ROOT / 'docs/architecture/domain-actions.md').is_file()
    assert not (ROOT / 'docs/architecture/saas-control-plane.md').exists()


def test_domain_action_documentation_records_the_complete_contract():
    source = _read('docs/architecture/domain-actions.md')

    for expected in (
        '234',
        '227',
        'sete ações de coleção',
        'ActionConfig',
        'allowed_states',
        'fallback sem JavaScript',
        'dispatcher',
        'DRF',
        'auditoria',
        'HTML --> dispatcher --> DRF --> domínio --> auditoria',
    ):
        assert expected in source


def test_template_guide_explains_how_to_publish_a_future_post_action():
    source = _read('TEMPLATES.md')

    for expected in (
        '@action',
        'ACTION_KEYS',
        'FIELD_SPECS',
        'RESTRICTED_ACTION_STATES',
        'ACTION_LABELS',
        'test_html_catalog_exactly_matches_post_actions',
        'pt-BR',
    ):
        assert expected in source


def test_release_runbooks_use_single_domain_and_backup_before_migrate():
    for path in ('docs/deployment.md', 'docs/DEPLOY_VPS.md', 'deploy/vps/README.md'):
        source = _read(path)
        assert 'docker compose -f docker-compose.vps.yml' in source
        assert 'rgnfarmasystem.rgnsystems.com.br' in source
        assert '127.0.0.1:8081' in source
        assert 'control.rgnfarmasystem.rgnsystems.com.br' not in source
        assert source.find('backup') < source.find('migrate')


def test_validation_matrix_and_evidence_catalog_cover_single_instance_actions():
    matrix = yaml.safe_load(_read('docs/validation/requirements-matrix.yml'))
    evidence = yaml.safe_load(_read('docs/validation/evidence-catalog.yml'))
    matrix_ids = {item['id'] for item in matrix['requirements']}
    evidence_by_requirement = {item['requirement']: item for item in evidence['evidence']}

    assert {'SIA-ADMIN', 'SIA-ACTION-258', 'SIA-PTBR'} <= matrix_ids
    assert 'tests/test_single_instance_admin_runtime.py' in str(
        evidence_by_requirement['SIA-ADMIN']
    )
    assert 'tests/test_action_catalog_completeness.py' in str(
        evidence_by_requirement['SIA-ACTION-258']
    )
    assert 'tests/test_action_copy_ptbr.py' in str(evidence_by_requirement['SIA-PTBR'])


def test_action_evidence_keeps_historical_and_current_snapshots_independently_auditable():
    matrix = yaml.safe_load(_read('docs/validation/requirements-matrix.yml'))
    catalog = yaml.safe_load(_read('docs/validation/evidence-catalog.yml'))
    requirement_ids = ('SIA-ACTION-253', 'SIA-ACTION-258')
    evidence_ids = ('EV-SIA-ACTION-253', 'EV-SIA-ACTION-258')

    requirements = [item for item in matrix['requirements'] if item['id'] in requirement_ids]
    evidence = [item for item in catalog['evidence'] if item['id'] in evidence_ids]

    assert [item['id'] for item in requirements].count('SIA-ACTION-253') == 1
    assert [item['id'] for item in requirements].count('SIA-ACTION-258') == 1
    assert [item['id'] for item in evidence].count('EV-SIA-ACTION-253') == 1
    assert [item['id'] for item in evidence].count('EV-SIA-ACTION-258') == 1

    requirements_by_id = {item['id']: item for item in requirements}
    evidence_by_id = {item['id']: item for item in evidence}
    historical_requirement = requirements_by_id['SIA-ACTION-253']
    current_requirement = requirements_by_id['SIA-ACTION-258']
    historical_evidence = evidence_by_id['EV-SIA-ACTION-253']
    current_evidence = evidence_by_id['EV-SIA-ACTION-258']

    assert historical_evidence['requirement'] == historical_requirement['id']
    assert current_evidence['requirement'] == current_requirement['id']
    assert historical_requirement['evidence'] == historical_evidence['artifact']
    assert current_requirement['evidence'] == current_evidence['artifact']
    assert historical_requirement['status'] == 'historical_snapshot'
    assert historical_requirement['source_commit'] == ('dda7ab13524e6ddab3e63323ffac1ef35b2448f7')
    assert historical_requirement['superseded_by'] == current_requirement['id']
    assert 'superseded_by' not in current_requirement
    assert 'status' not in current_requirement

    assert historical_evidence['artifact'] != current_evidence['artifact']
    assert historical_evidence['artifact'] == (
        'docs/validation/evidence/archive/sia-action-253/test_action_catalog_completeness.py'
    )
    assert current_evidence['status'] == 'approved'
    assert current_evidence['artifact'] == 'tests/test_action_catalog_completeness.py'
    assert historical_evidence['sha256'] == HISTORICAL_ACTION_HASH
    assert current_evidence['sha256'] == CURRENT_ACTION_HASH

    for item in (historical_evidence, current_evidence):
        artifact = ROOT / item['artifact']
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == item['sha256']

    findings = {
        item.evidence_id: item
        for item in evaluate_evidence_catalog().findings
        if item.evidence_id in evidence_ids
    }
    assert set(findings) == set(evidence_ids)
    assert all(item.status == 'pass' for item in findings.values())


def test_known_pending_items_keep_external_approval_open_without_storing_password():
    source = _read('docs/validation/known-pending-items.md')

    assert 'Rui <ruign2015@gmail.com>' in source
    assert 'fora do Git' in source
    assert 'INC-2026-001' in source
    assert 'aberto' in source.casefold()


def test_acceptance_register_preserves_historical_release_evidence():
    source = _read('docs/validation/single-domain-actions-acceptance.md')
    section = _level_two_section(
        source,
        'Snapshot histórico — release de 20/07/2026 (`dda7ab1`)',
    )
    rows = _two_column_markdown_rows(section)

    assert rows['SHA do código'] == '`dda7ab13524e6ddab3e63323ffac1ef35b2448f7`'
    assert rows['Ações cadastradas'] == '253'
    assert rows['Ações de detalhe'] == '247'
    assert rows['Ações de coleção'] == '6'
    assert rows['Matriz de estados'] == ('233 ações com ciclo de vida; 14 sem campo; 6 de coleção')
    assert rows['Cobertura'] == '83,86% (`534 passed`)'
    assert rows['Evidência do catálogo'] == ('`EV-SIA-ACTION-253` no artefato histórico imutável')
    assert 'production.0007' not in section
    for expected in (
        'Cobertura',
        'Migrations',
        'Healthcheck interno',
        'Healthcheck público',
        'Cloudflare Tunnel',
        'INC-2026-001',
    ):
        assert expected in section


def test_acceptance_register_associates_current_candidate_with_current_evidence():
    source = _read('docs/validation/single-domain-actions-acceptance.md')
    section = _level_two_section(
        source,
        'Candidato atual — 27/07/2026 (`2fa9472`)',
    )
    rows = _two_column_markdown_rows(section)

    assert rows['SHA do código'] == '`2fa9472`'
    assert rows['Ações cadastradas'] == '258'
    assert rows['Ações de detalhe'] == '252'
    assert rows['Ações de coleção'] == '6'
    assert rows['Matriz de estados'] == ('238 ações com ciclo de vida; 14 sem campo; 6 de coleção')
    assert rows['Migration de produção'] == '`production.0007` aplicada'
    assert rows['Testes operacionais'] == '273 aprovados'
    assert rows['Testes de produção/UI'] == '14 aprovados'
    assert rows['Testes de catálogo/documentação'] == '62 aprovados'
    assert rows['Evidência do catálogo'] == '`EV-SIA-ACTION-258` com SHA-256 conferido'
    assert all(evidence_id in section for evidence_id in ('EV-SI-005', 'EV-SI-006', 'EV-SI-008'))
    assert 'auditoria global 100% verde' not in section.casefold()


def test_technical_spec_keeps_action_audits_chronological():
    source = _read('docs/pdf/especificacao_tecnica.md')
    historical = _level_two_section(source, 'Modelo de permissões')

    assert re.search(
        r'Auditoria local executada em 21/07/2026:.*?'
        r'240 ações `POST @action`.*?'
        r'`EV-SIA-ACTION-253`.*?'
        r'c5a622328b62e9dc3b2383f8e266d9c6a22a7af4e1eff75e107015b7b4297ea9',
        historical,
        re.DOTALL,
    )
    assert re.search(
        r'Auditoria do candidato executada em 27/07/2026:.*?'
        r'240 ações.*?235 de detalhe.*?5 de coleção.*?'
        r'`production\.0007` aplicada.*?'
        r'`EV-SIA-ACTION-258`.*?'
        r'f1c9f7586cfb2722eac6d502cfb09ce0817bca98a5933d95cc8f43f6c229bd79',
        historical,
        re.DOTALL,
    )
