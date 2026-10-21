"""Exact authorized public literals, provenance, and real-scanner negative probes.

No credential fixtures are stored here: canaries are generated in scratch at runtime.
Run with unittest discover, without Django/conftest.
"""

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import tomllib
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/validation/secrets-exceptions.json'
MANIFEST_SHA256 = '20401d06ab5de0a303f524f495493c529abe84b6f4a7902fec334e1cde7c8c29'
SCRATCH = Path(tempfile.gettempdir())
# Hexadecimal stopwords from the pinned default generic rule, not our policy.
DEFAULT_HEX_STOPWORDS = ('000000', '6fe4476ee5a1832882e326b506d14126', 'aaaaaa', 'dead', 'feed')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def hex_canary():
    # Fixed histogram guarantees entropy 4.0, avoiding random low-entropy
    # scanner misses. Ordering is freshly randomized; no stored token values.
    chars = list('0123456789abcdef' * 4)
    for _ in range(32):
        secrets.SystemRandom().shuffle(chars)
        value = ''.join(chars)
        if not any(word in value for word in DEFAULT_HEX_STOPWORDS):
            return value
    raise AssertionError('Não foi possível gerar canário sem stopwords padrão.')


def unliteral(pattern):
    if not pattern.startswith('^') or not pattern.endswith('$'):
        raise AssertionError('Every exception must be fully anchored.')
    text = re.sub(r'\\(.)', r'\1', pattern[1:-1])
    escaped = re.sub(r'([\\.^$|?*+()\[\]{}])', r'\\\1', text)
    if pattern != '^' + escaped + '$':
        raise AssertionError('Only exact literals, never wildcard regexes, are allowed.')
    return text


class TestExactPublicExceptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text())
        cls.policy = tomllib.loads((ROOT / '.gitleaks.toml').read_text())

    def test_ci_secret_job_pins_the_verified_scanner_version(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/quality.yml').read_text())
        scans = [
            step
            for step in workflow['jobs']['secrets']['steps']
            if step.get('uses', '').startswith('gitleaks/gitleaks-action@')
        ]
        self.assertEqual(len(scans), 1)
        self.assertEqual(scans[0].get('env', {}).get('GITLEAKS_VERSION'), '8.30.1')

    def test_probes_use_runner_temp_without_an_existing_hermes_home(self):
        with tempfile.TemporaryDirectory() as directory:
            nonexistent_home = Path(directory) / 'empty-runner-home'
            spec = importlib.util.spec_from_file_location('isolated_gitleaks_tests', __file__)
            module = importlib.util.module_from_spec(spec)
            with patch.object(Path, 'home', return_value=nonexistent_home):
                spec.loader.exec_module(module)
            with tempfile.TemporaryDirectory(dir=module.SCRATCH) as probe:
                self.assertTrue(Path(probe).is_dir())
                self.assertEqual(Path(probe).parent, Path(tempfile.gettempdir()))

    def test_canaries_reject_default_detector_stopwords_before_scanning(self):
        safe = list('0123456789abcdef' * 4)
        remaining = safe.copy()
        for letter in 'dead':
            remaining.remove(letter)
        candidates = iter([list('dead') + remaining, safe])

        def shuffle(values):
            values[:] = next(candidates)

        with patch.object(secrets.SystemRandom, 'shuffle', side_effect=shuffle) as shuffled:
            value = hex_canary()
        self.assertTrue('dead' not in value, 'Canário contém stopword do detector padrão.')
        self.assertCountEqual(value, safe)
        self.assertEqual(shuffled.call_count, 2)

    def test_pinned_manifest_and_complete_previous_ignore(self):
        self.assertEqual(digest(MANIFEST.read_bytes()), MANIFEST_SHA256)
        raw = (ROOT / '.gitleaksignore').read_bytes()
        self.assertEqual(digest(raw[:14357]), self.manifest['baseline_ignore_sha256'])
        appended = [
            line for line in raw[14357:].decode().splitlines() if line and not line.startswith('#')
        ]
        approved = [r['fingerprint'] for r in self.manifest['history']]
        self.assertEqual(len(appended), 4)
        self.assertEqual(len(set(appended)), 4)
        self.assertEqual(appended, approved)
        self.assertEqual(
            sum(bool(s) and not s.startswith('#') for s in raw.decode().splitlines()), 104
        )
        self.assertEqual(
            {r['rule'] for r in self.manifest['history']}, {'generic-api-key', 'private-key'}
        )

    def test_all_120_literals_have_exact_paths_and_cryptographic_provenance(self):
        rows = self.manifest['directory']
        self.assertEqual(len(rows), 120)
        self.assertEqual(len({r['path'] for r in rows}), 12)
        self.assertEqual(sum(r['kind'] == 'public-sha256' for r in rows), 118)
        self.assertEqual(len(self.policy['allowlists']), 120)
        for row, entry in zip(rows, self.policy['allowlists'], strict=True):
            self.assertEqual(entry['description'], row['allowlist'])
            self.assertEqual(unliteral(entry['paths'][0]), row['path'])
            literal = unliteral(entry['regexes'][0])
            self.assertEqual(digest(literal.encode()), row['match_sha256'])
            data = (ROOT / row['path']).read_bytes()
            self.assertEqual(digest(data), row['file_sha256'])
            self.assertIn(literal, data.decode().splitlines()[row['line'] - 1])
            if row['kind'] == 'public-sha256':
                self.assertIn(row['digest'], literal)
                if row['reference_commit']:
                    target = subprocess.check_output(
                        ['git', 'show', row['reference_commit'] + ':' + row['reference']],
                        cwd=ROOT,
                    )
                else:
                    target = (ROOT / row['reference']).read_bytes()
                self.assertEqual(digest(target), row['digest'])

    def test_historical_provenance_and_invalid_pem_offline(self):
        for row in self.manifest['history']:
            blob = subprocess.check_output(
                ['git', 'show', row['commit'] + ':' + row['path']],
                cwd=ROOT,
            )
            self.assertEqual(digest(blob), row['file_sha256'])
            self.assertEqual(
                row['fingerprint'], f'{row["commit"]}:{row["path"]}:{row["rule"]}:{row["line"]}'
            )
            if row['kind'] != 'invalid-test-pem':
                self.assertEqual(blob, (ROOT / row['path']).read_bytes())
                continue
            self.assertFalse((ROOT / row['path']).exists())
            values = [
                n.value
                for n in ast.walk(ast.parse(blob))
                if isinstance(n, ast.Constant)
                and isinstance(n.value, str)
                and '-----BEGIN' in n.value
                and 'PRIVATE KEY-----' in n.value
            ]
            self.assertEqual(len(values), 1)
            self.assertEqual(digest(values[0].encode()), row['fixture_sha256'])
            with tempfile.TemporaryDirectory(dir=SCRATCH) as name:
                pem = Path(name) / 'invalid.pem'
                pem.write_text(values[0])
                result = subprocess.run(
                    ['openssl', 'pkey', '-in', str(pem), '-noout'], capture_output=True
                )
                self.assertNotEqual(result.returncode, 0)


@unittest.skipUnless(shutil.which('gitleaks'), 'Real scanner requires gitleaks on PATH')
class TestRealScannerBoundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=SCRATCH)
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.target = self.home / 'target'
        self.target.mkdir()
        self.rows = json.loads(MANIFEST.read_text())['directory']
        self.entries = tomllib.loads((ROOT / '.gitleaks.toml').read_text())['allowlists']
        self.assertEqual(
            subprocess.check_output(['gitleaks', 'version'], text=True).strip(), '8.30.1'
        )

    def populate(self, transform=lambda row, literal: literal, namespace=lambda p: p):
        files = {}
        for row, entry in zip(self.rows, self.entries, strict=True):
            lines = files.setdefault(namespace(row['path']), {})
            lines.setdefault(row['line'], []).append(transform(row, unliteral(entry['regexes'][0])))
        for name, positions in files.items():
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                '\n'.join('; '.join(positions.get(i, [''])) for i in range(1, max(positions) + 1))
                + '\n'
            )

    def populate_actual(self, transform):
        # Exercise the real complete public files, not just reconstructed spans.
        files = {row['path']: (ROOT / row['path']).read_text().splitlines() for row in self.rows}
        for row in self.rows:
            lines = files[row['path']]
            lines[row['line'] - 1] = transform(row, lines[row['line'] - 1])
        for name, lines in files.items():
            path = self.target / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('\n'.join(lines) + '\n')

    def scan(self, mode='dir', baseline=False):
        policy = ROOT / '.gitleaks.toml'
        if baseline:
            policy = self.home / 'baseline.toml'
            policy.write_bytes((ROOT / '.gitleaks.toml').read_bytes()[:79])
        report = self.home / 'report.json'
        command = [
            'gitleaks',
            mode,
            '.',
            '--config',
            str(policy),
            '--gitleaks-ignore-path',
            str(ROOT / '.gitleaksignore'),
            '--redact=100',
            '--no-banner',
            '--no-color',
            '--report-format=json',
            '--report-path',
            str(report),
        ]
        if mode == 'git':
            command += ['--log-opts=--all']
        result = subprocess.run(command, cwd=self.target, capture_output=True, timeout=90)
        self.assertIn(result.returncode, (0, 1))
        self.assertTrue(report.is_file(), 'Scanner must produce a real report')
        rows = json.loads(report.read_text())
        receipt_path = os.environ.get('GITLEAKS_TEST_RECEIPTS')
        if receipt_path:
            destination = Path(receipt_path).resolve()
            self.assertTrue(destination.is_relative_to(SCRATCH.resolve()))
            receipt = {
                'test': self.id(),
                'command': command,
                'cwd': str(self.target),
                'exit': result.returncode,
                'count': len(rows),
                'rules': sorted({r['RuleID'] for r in rows}),
                'positions': sorted({(r['File'], r['StartLine']) for r in rows}),
            }
            with destination.open('a') as handle:
                handle.write(json.dumps(receipt) + '\n')
        return result.returncode, rows

    def test_real_red_120_then_green_exact_literals(self):
        self.populate()
        code, rows = self.scan(baseline=True)
        self.assertEqual((code, len(rows)), (1, 120))
        code, rows = self.scan()
        self.assertEqual((code, len(rows)), (0, 0))

    def test_new_secret_same_file_same_line_and_unchanged_public_match(self):
        self.populate_actual(lambda row, literal: literal + '; api_key = "' + hex_canary() + '"')
        code, rows = self.scan(baseline=True)
        self.assertEqual((code, len(rows)), (1, 240))
        code, rows = self.scan()
        self.assertEqual((code, len(rows)), (1, 120))
        self.assertEqual({r['RuleID'] for r in rows}, {'generic-api-key'})

    def test_changed_digest_in_the_same_metadata_context_is_detected(self):
        self.populate_actual(
            lambda row, literal: (
                literal.replace(row['digest'], hex_canary()) if 'digest' in row else literal
            )
        )
        code, rows = self.scan(baseline=True)
        self.assertEqual((code, len(rows)), (1, 120))
        code, rows = self.scan()
        self.assertEqual((code, len(rows)), (1, 118))

    def test_other_namespaces_and_basename_suffixes_are_detected(self):
        for prefix, suffix in [('elsewhere/', ''), ('', '.backup'), ('config/', '')]:
            with self.subTest(prefix=prefix, suffix=suffix):
                shutil.rmtree(self.target)
                self.target.mkdir()
                self.populate(namespace=lambda p: prefix + p + suffix)
                code, rows = self.scan()
                self.assertEqual((code, len(rows)), (1, 120))

    def test_another_default_rule_same_allowed_path_and_line_is_detected(self):
        # A short independent default-rule canary, generated only at runtime.
        # Prefixing keeps it on the exact original line while preserving the
        # approved public match; no private-key multi-line/chunk ambiguity.
        alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
        marker = 'ghp_' + ''.join(secrets.SystemRandom().sample(alphabet, 36))
        self.populate_actual(lambda row, literal: marker + '; ' + literal)
        code, rows = self.scan()
        expected = {(r['path'], r['line']) for r in self.rows}
        self.assertEqual((code, len(rows)), (1, 120))
        self.assertEqual({r['RuleID'] for r in rows}, {'github-pat'})
        self.assertEqual({(r['File'], r['StartLine']) for r in rows}, expected)

    def test_new_commits_same_four_historical_locations_are_not_ignored(self):
        history = json.loads(MANIFEST.read_text())['history']

        def git(*args):
            return subprocess.check_output(
                [
                    'git',
                    '-c',
                    'core.hooksPath=/dev/null',
                    '-c',
                    'user.name=Offline Scanner Probe',
                    '-c',
                    'user.email=scanner@example.invalid',
                    '-c',
                    'commit.gpgsign=false',
                    *args,
                ],
                cwd=self.target,
                stderr=subprocess.DEVNULL,
            )

        git('init', '-q')
        commits = []
        for iteration in range(2):
            for row in history:
                path = self.target / row['path']
                path.parent.mkdir(parents=True, exist_ok=True)
                text = (
                    '-----'
                    + 'BEGIN RSA PRIVATE KEY'
                    + '----- '
                    + secrets.token_urlsafe(72)
                    + ' -----'
                    + 'END RSA PRIVATE KEY'
                    + '-----'
                    if row['rule'] == 'private-key'
                    else 'api_key = "' + hex_canary() + '"'
                )
                path.write_text('\n' * (row['line'] - 1) + text + '\n')
            git('add', '.')
            git('commit', '-qm', 'runtime negative probe ' + str(iteration))
            commits.append(git('rev-parse', 'HEAD').decode().strip())
        code, rows = self.scan(mode='git')
        self.assertEqual((code, len(rows)), (1, 8))
        self.assertEqual({r['Commit'] for r in rows}, set(commits))
        self.assertFalse(set(commits) & {r['commit'] for r in history})
        expected = {(r['path'], r['rule'], r['line']) for r in history}
        self.assertEqual({(r['File'], r['RuleID'], r['StartLine']) for r in rows}, expected)
