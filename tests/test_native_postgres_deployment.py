from pathlib import Path
import gzip
import io
import subprocess
import sys
import tarfile

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_production_compose_uses_private_containerized_postgres():
    compose = yaml.safe_load((ROOT / 'docker-compose.vps.yml').read_text(encoding='utf-8'))
    services = compose['services']

    assert services['db']['image'].startswith('postgres:')
    assert services['db']['networks'] == ['backend']
    assert 'ports' not in services['db']
    assert 'postgres_data' in compose['volumes']
    assert services['app']['environment']['DB_DEPLOYMENT'] == 'container'
    assert services['app']['environment']['DB_HOST'] == 'db'


def test_production_image_contains_postgres_client():
    dockerfile = (ROOT / 'Dockerfile').read_text(encoding='utf-8')
    assert 'postgresql-client' in dockerfile


def test_example_env_declares_container_database_without_real_secret():
    source = (ROOT / '.env.example').read_text(encoding='utf-8')
    assert 'DB_DEPLOYMENT=container' in source
    assert 'DB_HOST=db' in source
    assert 'MEDIA_DEPLOYMENT=container' in source
    assert 'DB_PORT=5432' in source
    assert '@db:5432/rgnfarmasystem' in source
    assert 'POSTGRES_PASSWORD=change-me' in source
    assert 'TUNNEL_METRICS_PORT=20242' in source


def test_backup_supports_explicit_external_database():
    source = (ROOT / 'scripts' / 'backup.sh').read_text(encoding='utf-8')
    assert 'DB_DEPLOYMENT' in source
    assert 'external)' in source
    assert 'container)' in source
    assert 'mktemp' in source
    assert 'PGPASSWORD=' in source
    assert 'pg_dump' in source


def test_restore_supports_external_database_and_keeps_safety_gates():
    source = (ROOT / 'scripts' / 'restore.sh').read_text(encoding='utf-8')
    assert 'DB_DEPLOYMENT' in source
    assert 'restore_external_postgres' in source
    assert 'PGPASSWORD=' in source
    assert 'psql' in source
    assert '--dry-run' in source
    assert '--yes' in source
    assert 'pre-restore-' in source
    assert 'MEDIA_DEPLOYMENT' in source
    assert 'restore_media.py' in source


def test_scripts_reject_unknown_database_deployment():
    for name in ('backup.sh', 'restore.sh'):
        source = (ROOT / 'scripts' / name).read_text(encoding='utf-8')
        assert 'DB_DEPLOYMENT invalido' in source


def test_external_restore_dry_run_does_not_require_database_container(tmp_path):
    backup = tmp_path / 'postgres.sql.gz'
    with gzip.open(backup, 'wb') as stream:
        stream.write(b'SELECT 1;')

    result = subprocess.run(
        [
            ROOT / 'scripts' / 'restore.sh',
            '--postgres',
            backup,
            '--dry-run',
        ],
        env={'DB_DEPLOYMENT': 'external', 'PATH': '/usr/bin:/bin'},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert 'PGPASSWORD=<redacted> psql' in result.stdout
    assert 'Container do PostgreSQL' not in result.stderr


def test_external_media_restore_rejects_traversal_before_pre_restore_backup(tmp_path):
    backup = tmp_path / 'media.tar.gz'
    with tarfile.open(backup, 'w:gz') as archive:
        info = tarfile.TarInfo('../../outside.txt')
        payload = b'unsafe'
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    result = subprocess.run(
        [ROOT / 'scripts' / 'restore.sh', '--media', backup, '--dry-run'],
        env={
            'DB_DEPLOYMENT': 'external',
            'MEDIA_DEPLOYMENT': 'external',
            'MEDIA_DIR': str(tmp_path / 'media'),
            'PYTHON_BIN': sys.executable,
            'PATH': '/usr/bin:/bin',
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'Caminho inseguro' in result.stderr
    assert 'pre-restore' not in result.stdout
    assert not (tmp_path / 'outside.txt').exists()


def _write_executable(path, source):
    path.write_text(source, encoding='utf-8')
    path.chmod(0o755)


def test_invalid_postgres_gzip_is_rejected_before_external_psql(tmp_path):
    backup = tmp_path / 'invalid.sql.gz'
    backup.write_bytes(b'not-a-gzip')
    media = tmp_path / 'media'
    media.mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    calls = tmp_path / 'calls'
    _write_executable(bin_dir / 'pg_dump', "#!/bin/sh\nprintf 'dump'\n")
    _write_executable(
        bin_dir / 'psql',
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CALLS"\n',
    )

    result = subprocess.run(
        [ROOT / 'scripts' / 'restore.sh', '--postgres', backup, '--yes'],
        env={
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'CALLS': str(calls),
            'DB_DEPLOYMENT': 'external',
            'MEDIA_DIR': str(media),
            'PATH': f'{bin_dir}:/usr/bin:/bin',
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'gzip' in (result.stdout + result.stderr).lower()
    assert not calls.exists(), 'psql must not run for an invalid gzip'


def test_invalid_decrypted_postgres_gzip_is_rejected_before_psql(tmp_path):
    backup = tmp_path / 'invalid.sql.gz.enc'
    backup.write_bytes(b'ciphertext')
    media = tmp_path / 'media'
    media.mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    calls = tmp_path / 'calls'
    _write_executable(bin_dir / 'pg_dump', "#!/bin/sh\nprintf 'dump'\n")
    _write_executable(
        bin_dir / 'psql',
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$CALLS"\n',
    )
    _write_executable(
        bin_dir / 'python',
        """#!/bin/sh
while [ "$#" -gt 0 ]; do
  if [ "$1" = --destination ]; then shift; printf invalid > "$1"; printf 'OK %s\\n' "$1"; exit 0; fi
  shift
done
exit 98
""",
    )

    result = subprocess.run(
        [ROOT / 'scripts' / 'restore.sh', '--postgres', backup, '--yes'],
        env={
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'CALLS': str(calls),
            'DB_DEPLOYMENT': 'external',
            'MEDIA_DIR': str(media),
            'PATH': f'{bin_dir}:/usr/bin:/bin',
            'PROJECT_DIR': str(ROOT),
            'PYTHON_BIN': str(bin_dir / 'python'),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'gzip' in (result.stdout + result.stderr).lower()
    assert not calls.exists(), 'psql must not run for an invalid decrypted gzip'


def test_invalid_postgres_gzip_is_rejected_before_container_exec(tmp_path):
    backup = tmp_path / 'invalid.sql.gz'
    backup.write_bytes(b'not-a-gzip')
    media = tmp_path / 'media'
    media.mkdir()
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    calls = tmp_path / 'docker-calls'
    _write_executable(
        bin_dir / 'docker',
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CALLS"
if [ "$1" = ps ]; then printf 'db-container\\n'; exit 0; fi
if [ "$1 $2 $4" = 'exec db-container pg_dump' ]; then printf 'dump'; exit 0; fi
exit 97
""",
    )

    result = subprocess.run(
        [ROOT / 'scripts' / 'restore.sh', '--postgres', backup, '--yes'],
        env={
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'CALLS': str(calls),
            'DB_DEPLOYMENT': 'container',
            'MEDIA_DIR': str(media),
            'PATH': f'{bin_dir}:/usr/bin:/bin',
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    docker_calls = calls.read_text(encoding='utf-8') if calls.exists() else ''
    assert 'psql' not in docker_calls
    assert 'DROP SCHEMA' not in docker_calls


def test_backup_media_falls_back_to_media_dir_and_publishes_atomically(tmp_path):
    media = tmp_path / 'media'
    media.mkdir()
    (media / 'document.txt').write_text('regulated', encoding='utf-8')
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _write_executable(bin_dir / 'pg_dump', "#!/bin/sh\nprintf 'dump'\n")

    result = subprocess.run(
        [ROOT / 'scripts' / 'backup.sh'],
        env={
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'DB_DEPLOYMENT': 'external',
            'MEDIA_DIR': str(media),
            'PATH': f'{bin_dir}:/usr/bin:/bin',
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    artifacts = list((tmp_path / 'backups').glob('media-*.tar.gz'))
    assert len(artifacts) == 1 and artifacts[0].stat().st_size > 0
    assert not list((tmp_path / 'backups').glob('.media-*'))


def test_backup_fails_when_no_app_container_or_media_directory_exists(tmp_path):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _write_executable(bin_dir / 'pg_dump', "#!/bin/sh\nprintf 'dump'\n")

    result = subprocess.run(
        [ROOT / 'scripts' / 'backup.sh'],
        env={
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'DB_DEPLOYMENT': 'external',
            'MEDIA_DIR': str(tmp_path / 'missing-media'),
            'COMPOSE_PROJECT_NAME': 'rgnfarmasystem-test-no-app',
            'PATH': f'{bin_dir}:/usr/bin:/bin',
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert not list((tmp_path / 'backups').glob('media-*.tar.gz'))


def test_deploy_uses_compose_with_env_file_without_sourcing_secrets():
    source = (ROOT / 'scripts' / 'deploy-vps.sh').read_text(encoding='utf-8')

    assert 'docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE"' in source
    assert 'source "$ENV_FILE"' not in source
    assert 'compose config --quiet' in source
    assert 'compose up -d --build --remove-orphans --wait' in source


def deploy_functions_script(tmp_path):
    source = (ROOT / 'scripts' / 'deploy-vps.sh').read_text(encoding='utf-8')
    assert source.rstrip().endswith('main "$@"')
    script = tmp_path / 'deploy-functions.sh'
    script.write_text(source.rsplit('main "$@"', maxsplit=1)[0], encoding='utf-8')
    return script


def test_deploy_rejects_duplicate_env_keys_without_leaking_values(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text(
        'POSTGRES_PASSWORD=first-secret\nPOSTGRES_PASSWORD=second-secret\n',
        encoding='utf-8',
    )

    result = subprocess.run(
        [
            'bash',
            '-c',
            'source "$1"; read_env_value POSTGRES_PASSWORD',
            'bash',
            deploy_functions_script(tmp_path),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'chave duplicada: POSTGRES_PASSWORD' in result.stderr
    assert 'first-secret' not in result.stdout + result.stderr
    assert 'second-secret' not in result.stdout + result.stderr


def test_deploy_rejects_invalid_tunnel_metrics_port(tmp_path):
    env_file = tmp_path / '.env'
    env_file.write_text('TUNNEL_METRICS_PORT=70000\n', encoding='utf-8')

    result = subprocess.run(
        [
            'bash',
            '-c',
            'source "$1"; ENV_FILE="$2"; configure_tunnel_readiness',
            'bash',
            deploy_functions_script(tmp_path),
            env_file,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert 'TUNNEL_METRICS_PORT invalida' in result.stderr


def test_deploy_validates_backup_before_promoting_revision():
    source = (ROOT / 'scripts' / 'deploy-vps.sh').read_text(encoding='utf-8')
    main = source[source.index('main()') :]

    assert main.index('require_command docker') < main.index('check_env_file')
    assert main.index('validate_compose') < main.index('create_release_backup')
    assert main.index('create_release_backup') < main.index('promote_revision')
    assert main.index('promote_revision') < main.index('deploy_compose')
    assert 'gzip -t -- "$postgres_backup"' in source
    assert 'tar -tzf "$media_backup"' in source
    assert 'sha256sum -c' in source


def test_deploy_rollback_redeploys_code_without_automatic_data_restore():
    source = (ROOT / 'scripts' / 'deploy-vps.sh').read_text(encoding='utf-8')
    rollback = source[source.index('rollback_release()') : source.index('main()')]

    assert 'git switch --detach "$PREVIOUS_SHA"' in rollback
    assert 'compose up -d --build --remove-orphans --wait' in rollback
    assert 'Banco e midia nao foram restaurados automaticamente.' in rollback
    assert 'scripts/restore.sh' not in rollback


def test_vps_docs_cover_native_postgres_security_migration_and_restore():
    sources = '\n'.join(
        (ROOT / path).read_text(encoding='utf-8')
        for path in (
            'docs/DEPLOY_VPS.md',
            'docs/deployment.md',
            'docs/architecture/backup-restore.md',
        )
    )
    for marker in (
        'host.docker.internal',
        'DB_DEPLOYMENT=external',
        'listen_addresses',
        'pg_hba.conf',
        'scram-sha-256',
        'pg_dump',
        'psql',
        'backup_scheduler',
        'rollback',
    ):
        assert marker in sources


def test_vps_runbook_separates_host_and_container_database_endpoints():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')

    assert "listen_addresses = 'localhost,%s,%s'" in source
    assert 'HOST_DB_HOST=127.0.0.1' in source
    assert 'CONTAINER_DB_HOST=host.docker.internal' in source
    assert 'pg_isready -h "$HOST_DB_HOST"' in source


def test_vps_runbook_uses_a_git_checkout_for_revision_rollback():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')

    assert 'git clone' in source
    assert 'git fetch --tags --prune' in source
    assert 'git switch --detach' in source
    assert "rsync -avz --exclude '.venv' --exclude '.git'" not in source


def test_vps_runbook_enables_scram_before_password_assignment():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')

    scram = source.index("ALTER SYSTEM SET password_encryption = 'scram-sha-256'")
    password = source.index('\\password rgnfarmasystem')
    assert scram < password


def test_vps_runbook_loads_env_without_sourcing_or_exposing_secrets():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')

    assert 'docker run --rm --env-file .env' in source
    assert 'set -a && source .env && set +a' not in source
    assert 'POSTGRES_PASSWORD=' not in source


def test_restore_check_has_exact_target_and_a_drop_gate():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')

    assert '-e POSTGRES_DB=rgnfarmasystem_restore_check' in source
    assert '-e DATABASE_URL=' not in source
    assert 'RESTORE_GATE=' in source
    assert 'set -o pipefail' in source
    assert 'test -f "$RESTORE_GATE"' in source
    assert 'dropdb rgnfarmasystem_restore_check' in source


def test_migration_backup_uses_legacy_database_container_client():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')
    migration = source[source.index('## Migração do PostgreSQL em container') :]

    assert 'LEGACY_DB_CONTAINER=$(docker ps' in migration
    assert 'docker exec "$LEGACY_DB_CONTAINER" pg_dump' in migration
    assert 'mktemp' in migration
    assert '-v /var/run/docker.sock:/var/run/docker.sock' not in migration
    assert '-e DB_DEPLOYMENT=container' not in migration


def test_public_docs_use_the_containerized_postgresql_contract():
    for path in ('README.md', 'docs/deployment.md'):
        source = (ROOT / path).read_text(encoding='utf-8')
        assert 'DB_DEPLOYMENT=container' in source
        assert 'COMPOSE_PROJECT_NAME=rgnfarmasystem' in source
        assert 'host.docker.internal:host-gateway' not in source


def test_host_cron_uses_the_private_compose_database():
    source = (ROOT / 'docs/deployment.md').read_text(encoding='utf-8')
    cron = source[source.index('```cron') : source.index('```', source.index('```cron') + 7)]

    assert 'DB_DEPLOYMENT=container' in cron
    assert 'COMPOSE_PROJECT_NAME=rgnfarmasystem' in cron
    assert 'bash scripts/backup.sh' in cron


def test_restore_gate_is_created_only_when_every_validation_succeeds():
    source = (ROOT / 'docs/DEPLOY_VPS.md').read_text(encoding='utf-8')
    restore_gate = source.index('RESTORE_GATE=')
    gate_start = source.rindex('set -o pipefail', 0, restore_gate)
    gate = source[gate_start : source.index('Somente após esse gate')]

    assert 'set -o pipefail' in gate
    assert 'if {' in gate
    assert '} 2>&1 | tee "$RESTORE_LOG"; then' in gate
    assert 'touch "$RESTORE_GATE"' in gate
    assert 'else\n  rm -f "$RESTORE_GATE"\n  exit 1\nfi' in gate
    validation_block = gate[gate.index('if {') : gate.index('} 2>&1 | tee "$RESTORE_LOG"; then')]
    assert validation_block.count('&&') >= 2
