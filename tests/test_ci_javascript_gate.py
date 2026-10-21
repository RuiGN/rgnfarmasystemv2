"""Exercise CI JavaScript orchestration without starting Django or services."""

import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / 'scripts/ci/quality-gate.sh'


class TestJavaScriptQualityGate(unittest.TestCase):
    def recorded_commands(self):
        with TemporaryDirectory(prefix='ci-javascript-gate-') as directory:
            directory = Path(directory)
            log = directory / 'commands.jsonl'
            for executable in ('node', 'python'):
                stub = directory / executable
                stub.write_text(
                    '#!/bin/sh\n'
                    'printf \'%s\\0\' "${0##*/}" "$@" >> "$COMMAND_LOG"\n'
                    'printf \'\\0\' >> "$COMMAND_LOG"\n'
                )
                stub.chmod(0o700)
            result = subprocess.run(
                ['bash', str(GATE)],
                cwd=ROOT,
                env={
                    'PATH': str(directory) + os.pathsep + os.defpath,
                    'COMMAND_LOG': str(log),
                    'TEST_DATABASE_URL': 'isolated-contract-no-database-connection',
                },
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return [
                [argument.decode() for argument in record.split(b'\0')]
                for record in log.read_bytes().split(b'\0\0')
                if record
            ]

    def test_checks_related_fields_asset_syntax(self):
        commands = self.recorded_commands()
        self.assertIn(['node', '--check', 'static/js/related-fields.js'], commands)

    def test_checks_every_application_script_syntax(self):
        commands = self.recorded_commands()
        expected = {str(path.relative_to(ROOT)) for path in (ROOT / 'static/js').glob('*.js')}
        self.assertTrue(expected)
        observed = {command[2] for command in commands if command[:2] == ['node', '--check']}
        self.assertEqual(observed, expected)

    def test_runs_every_javascript_test_file(self):
        commands = self.recorded_commands()
        expected = {str(path.relative_to(ROOT)) for path in (ROOT / 'tests/js').glob('*.test.cjs')}
        self.assertTrue(expected)
        observed = {
            argument
            for command in commands
            if command[:2] == ['node', '--test']
            for argument in command[2:]
        }
        self.assertEqual(observed, expected)


if __name__ == '__main__':
    unittest.main()
