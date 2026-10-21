from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import sys

import pytest

from django.conf import settings
from django.test import SimpleTestCase


class BackupSchedulerScriptTests(SimpleTestCase):
    def setUp(self):
        self.path = Path(settings.BASE_DIR) / 'scripts' / 'backup_scheduler.sh'

    def run_scheduler(self, tmp_path, fake_backup, *, conditional=False, extra_env=None):
        # Regular files preserve BASH_SOURCE and avoid process-substitution FDs.
        source = self.path.read_text(encoding='utf-8').replace(
            'BACKUP_SCRIPT="$ROOT_DIR/scripts/backup.sh"', 'BACKUP_SCRIPT="$FAKE_BACKUP"'
        )
        if conditional:
            source = source.rsplit('main "$@"', maxsplit=1)[0]
            source += 'if ! run_backup_cycle; then exit 1; fi\n'
        script = tmp_path / 'scheduler-test.sh'
        script.write_text(source, encoding='utf-8')
        environment = {
            'BACKUP_DIR': str(tmp_path / 'backups'),
            'FAKE_BACKUP': str(fake_backup),
            'HEALTH_FILE': str(tmp_path / 'health'),
            'LAST_RUN_FILE': str(tmp_path / 'last-run'),
            'LOCK_FILE': str(tmp_path / 'lock'),
            'LOG_DIR': str(tmp_path / 'logs'),
            'RUN_ONCE': 'true',
        }
        environment.update(extra_env or {})
        if sys.platform == 'linux':
            command = ['bash', str(script)]
        else:
            image = os.environ.get('SHELL_TEST_IMAGE')
            if not image:
                pytest.skip('Linux scheduler requires SHELL_TEST_IMAGE on non-Linux hosts.')
            docker = shutil.which('docker')
            assert docker is not None, 'SHELL_TEST_IMAGE requires Docker.'
            command = [
                docker,
                'run',
                '--rm',
                '--network',
                'none',
                '--mount',
                f'type=bind,src={tmp_path},dst={tmp_path}',
                '--workdir',
                str(tmp_path),
            ]
            for key, value in environment.items():
                command.extend(('--env', f'{key}={value}'))
            command.extend(('--entrypoint', 'bash', image, str(script)))
        return subprocess.run(
            command,
            env={**os.environ, **environment},
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

    def test_scheduler_contract_is_local_only(self):
        source = self.path.read_text(encoding='utf-8')

        assert source.startswith('#!/usr/bin/env bash')
        assert 'set -euo pipefail' in source
        assert 'scripts/backup.sh' in source
        assert 'RUN_ONCE' in source
        assert 'flock' in source
        assert 'seconds_until_next_run' in source
        assert 'backup_scheduler_ready' in source
        assert 'last_backup_ok' in source
        assert 'manage.py' not in source

    def test_successful_local_cycle_writes_health_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            fake_backup = tmp_path / 'backup.sh'
            fake_backup.write_text(
                '#!/bin/sh\n'
                'mkdir -p "$BACKUP_DIR"\n'
                'printf dump > "$BACKUP_DIR/postgres-test.sql.gz"\n'
                'printf media > "$BACKUP_DIR/media-test.tar.gz"\n',
                encoding='utf-8',
            )
            fake_backup.chmod(0o755)
            health = tmp_path / 'health'
            last_run = tmp_path / 'last-run'

            result = self.run_scheduler(tmp_path, fake_backup)

            assert result.returncode == 0, result.stderr
            assert health.exists()
            assert last_run.exists()

    def test_cycle_without_artifacts_fails_without_health_markers(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            fake_backup = tmp_path / 'backup.sh'
            fake_backup.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
            fake_backup.chmod(0o755)
            health = tmp_path / 'health'
            last_run = tmp_path / 'last-run'

            result = self.run_scheduler(tmp_path, fake_backup)

            assert result.returncode != 0
            assert 'artefato' in result.stderr.lower()
            assert not health.exists()
            assert not last_run.exists()

    def test_failed_backup_in_conditional_does_not_publish_health_even_with_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            fake_backup = tmp_path / 'backup.sh'
            fake_backup.write_text(
                '#!/bin/sh\n'
                'mkdir -p "$BACKUP_DIR"\n'
                'printf dump > "$BACKUP_DIR/postgres-failed.sql.gz"\n'
                'printf media > "$BACKUP_DIR/media-failed.tar.gz"\n'
                'exit 1\n',
                encoding='utf-8',
            )
            health = tmp_path / 'health'
            health.write_text('stale success', encoding='utf-8')

            result = self.run_scheduler(tmp_path, fake_backup, conditional=True)

            assert result.returncode != 0
            assert not health.exists()
            assert not (tmp_path / 'last-run').exists()

    def test_failed_health_publish_in_conditional_fails_the_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            tmp_path = Path(temporary)
            fake_backup = tmp_path / 'backup.sh'
            fake_backup.write_text(
                '#!/bin/sh\n'
                'mkdir -p "$BACKUP_DIR"\n'
                'printf dump > "$BACKUP_DIR/postgres-test.sql.gz"\n'
                'printf media > "$BACKUP_DIR/media-test.tar.gz"\n',
                encoding='utf-8',
            )
            bin_dir = tmp_path / 'bin'
            bin_dir.mkdir()
            fake_mv = bin_dir / 'mv'
            fake_mv.write_text(
                '#!/bin/sh\ncase "$*" in *"$HEALTH_FILE") exit 1;; esac\nexec /bin/mv "$@"\n',
                encoding='utf-8',
            )
            fake_mv.chmod(0o755)

            result = self.run_scheduler(
                tmp_path,
                fake_backup,
                conditional=True,
                extra_env={'PATH': f'{bin_dir}:/usr/bin:/bin'},
            )

            assert result.returncode != 0
            assert not (tmp_path / 'health').exists()
            assert not (tmp_path / 'last-run').exists()
