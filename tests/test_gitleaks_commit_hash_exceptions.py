"""Contract for immutable Git findings; real scanner probes live in private evidence.

A fingerprint is an exact (commit, file, rule, line) identity, not a file
exclusion or a statement that arbitrary SHA-shaped values are harmless.
Directory findings have no commit and must not match these exceptions.
"""

import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
COMMIT = '43b1c1aed42017018acec43769244854d9f49c45'
PREFIX_LENGTH = 198
PREFIX_SHA256 = '619f5024d2898db6193c8a98b0c1d2d0d42e9624bba103089df5263db7974962'
POLICY_SHA256 = 'fa35bc5f1fd24cefca9898c1e23394a88dc319f2a1065834f6fca9d8a7a03bd5'
BASE = 'docs/validation/evidence/corrections/'
KNOWN_FINDINGS = (
    (COMMIT, BASE + 'current-main-v2-reconciliation.json', 'generic-api-key', 32),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 99),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 204),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 871),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 934),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 1023),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 1042),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 1319),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 2062),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 2119),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 2124),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 2133),
    (COMMIT, BASE + 'current-main-v3-source-manifest.json', 'generic-api-key', 2135),
    (COMMIT, BASE + 'current-main-v3-suite-reconciliation.json', 'generic-api-key', 19),
    (
        COMMIT,
        BASE + 'first-frozen-source-artifact-reconciliation.json',
        'generic-api-key',
        10,
    ),
)
PUBLICATION_COMMIT = '36a5cd694de9c39876057f96e3220f26d9c97daa'
LEGACY_IGNORE_LENGTH = 2398
LEGACY_IGNORE_SHA256 = 'ca195c1632aafea2fbebfa1a41e6309e205840e6a19e758941edfec1240f2652'
PUBLICATION_MANIFEST = (
    ROOT / 'docs/validation/evidence/ci-secrets-2026-10-20/approved-commit-fingerprints.json'
)
PUBLICATION_MANIFEST_SHA256 = 'b5469b9f2423f09a1d361b60fb6b6d1afcca0caaa4dd6a553b9b8aa1938220fe'
PUBLICATION_FINDINGS = tuple(
    (commit, path, rule, int(line))
    for commit, path, rule, line in (
        fingerprint.split(':') for fingerprint in json.loads(PUBLICATION_MANIFEST.read_text())
    )
)
EXPECTED_FINDINGS = KNOWN_FINDINGS + PUBLICATION_FINDINGS


def added_findings():
    """Parse only the appended entries, leaving the historical prefix intact."""
    raw = (ROOT / '.gitleaksignore').read_bytes()
    findings = []
    # The original 99-entry contract is immutable; new approved entries have
    # their own exact manifest and independent assertions below.
    for line in raw[PREFIX_LENGTH:14357].decode('utf-8').splitlines():
        if not line or line.startswith('#'):
            continue
        commit, path, rule, position = line.split(':')
        if not position.isascii() or not position.isdecimal():
            raise ValueError('A finding position must be an exact positive integer.')
        findings.append((commit, path, rule, int(position)))
    return findings


class TestImmutableCommitHashExceptions(unittest.TestCase):
    def test_historical_prefix_remains_byte_identical(self):
        raw = (ROOT / '.gitleaksignore').read_bytes()
        self.assertEqual(hashlib.sha256(raw[:PREFIX_LENGTH]).hexdigest(), PREFIX_SHA256)
        self.assertEqual(raw[PREFIX_LENGTH - 1 : PREFIX_LENGTH], b'\n')

    def test_only_exact_reviewed_findings_are_appended(self):
        findings = added_findings()
        self.assertEqual(len(KNOWN_FINDINGS), 15)
        self.assertEqual(len(findings), 99)
        self.assertEqual(len(set(findings)), 99)
        self.assertEqual(set(findings), set(EXPECTED_FINDINGS))

    def test_entries_have_no_patterns_or_directory_exemptions(self):
        findings = added_findings()
        self.assertEqual(set(findings), set(EXPECTED_FINDINGS))
        for commit, path, rule, line in findings:
            self.assertIn(commit, {COMMIT, PUBLICATION_COMMIT})
            self.assertEqual(len(commit), 40)
            self.assertTrue(all(char in '0123456789abcdef' for char in commit))
            self.assertFalse(PurePosixPath(path).is_absolute())
            self.assertNotIn('..', PurePosixPath(path).parts)
            self.assertFalse(any(char in path for char in '*?[]{}()^$\\'))
            if commit == COMMIT:
                self.assertTrue(path.startswith(BASE))
                self.assertTrue(path.endswith('.json'))
            else:
                self.assertIn(path, {finding[1] for finding in PUBLICATION_FINDINGS})
            self.assertEqual(rule, 'generic-api-key')
            self.assertGreater(line, 0)

    def test_changing_any_identity_field_does_not_match(self):
        actual = set(added_findings())
        for finding in KNOWN_FINDINGS:
            self.assertIn(finding, actual)
            commit, path, rule, line = finding
            for different in (
                ('0' * 40, path, rule, line),
                (commit, 'config/' + path, rule, line),
                (commit, path, 'private-key', line),
                (commit, path, rule, line + 1),
            ):
                self.assertNotIn(different, actual)

    def test_commitless_directory_findings_are_not_exempt(self):
        actual = set(added_findings())
        self.assertEqual(actual, set(EXPECTED_FINDINGS))
        for _, path, rule, line in EXPECTED_FINDINGS:
            self.assertNotIn(('', path, rule, line), actual)

    def test_same_location_in_another_commit_is_not_exempt(self):
        actual = set(added_findings())
        self.assertEqual(actual, set(EXPECTED_FINDINGS))
        # Changed bytes necessarily belong to a different immutable Git commit.
        for _, path, rule, line in EXPECTED_FINDINGS:
            self.assertNotIn(('f' * 40, path, rule, line), actual)

    def test_other_path_namespaces_and_basename_suffixes_are_not_exempt(self):
        actual = set(added_findings())
        self.assertEqual(actual, set(EXPECTED_FINDINGS))
        for commit, path, rule, line in EXPECTED_FINDINGS:
            for other_path in (
                path + '.backup',
                'config/' + PurePosixPath(path).name,
                'elsewhere/' + path,
                './' + path,
            ):
                self.assertNotIn((commit, other_path, rule, line), actual)

    def test_complete_previous_ignore_file_remains_byte_identical(self):
        raw = (ROOT / '.gitleaksignore').read_bytes()
        self.assertEqual(
            hashlib.sha256(raw[:LEGACY_IGNORE_LENGTH]).hexdigest(), LEGACY_IGNORE_SHA256
        )

    def test_publication_manifest_is_pinned_and_exact(self):
        self.assertEqual(
            hashlib.sha256(PUBLICATION_MANIFEST.read_bytes()).hexdigest(),
            PUBLICATION_MANIFEST_SHA256,
        )
        self.assertEqual(len(PUBLICATION_FINDINGS), 84)
        self.assertEqual(len(set(PUBLICATION_FINDINGS)), 84)
        self.assertEqual(len({finding[1] for finding in PUBLICATION_FINDINGS}), 6)
        self.assertEqual({finding[0] for finding in PUBLICATION_FINDINGS}, {PUBLICATION_COMMIT})
        self.assertEqual({finding[2] for finding in PUBLICATION_FINDINGS}, {'generic-api-key'})

    def test_publication_exceptions_reject_changed_identity_fields(self):
        actual = set(added_findings())
        for finding in PUBLICATION_FINDINGS:
            self.assertIn(finding, actual)
            commit, path, rule, line = finding
            unknown_line = max(f[3] for f in PUBLICATION_FINDINGS if f[1] == path) + 1
            for other in (
                (COMMIT, path, rule, line),
                (commit, path, 'private-key', line),
                (commit, path, rule, unknown_line),
                (commit, path + '.backup', rule, line),
            ):
                self.assertNotIn(other, actual)

    def test_reviewed_publication_lines_have_file_hash_provenance(self):
        snapshot = ROOT / (
            'docs/validation/evidence/deploy-readiness-2026-10-20/source-snapshot-final.json'
        )
        for _, name, _, position in PUBLICATION_FINDINGS:
            path = ROOT / name
            line = path.read_text().splitlines()[position - 1].strip()
            if name.endswith('/probe-recovery.stdin.txt'):
                self.assertTrue(line.startswith('EXPECTED_SOURCES='))
                self.assertEqual(
                    ast.literal_eval(line.partition('=')[2]),
                    json.loads(snapshot.read_text())['sources'],
                )
                continue
            record = json.loads('{' + line.rstrip(',') + '}')
            self.assertEqual(len(record), 1)
            key, digest = next(iter(record.items()))
            self.assertFalse(PurePosixPath(key).name.startswith('.env'))
            self.assertTrue(
                any(
                    candidate.resolve().is_relative_to(ROOT)
                    and not candidate.is_symlink()
                    and candidate.is_file()
                    and hashlib.sha256(candidate.read_bytes()).hexdigest() == digest
                    for candidate in (ROOT / key, path.parent / key)
                ),
                name,
            )

    def test_only_unsafe_historical_allowlist_is_removed(self):
        raw = (ROOT / '.gitleaks.toml').read_bytes()
        # Preserve the complete previous 100-entry ignore, not just its older
        # 2398-byte prefix. The four new tuples are tested separately.
        raw_ignore = (ROOT / '.gitleaksignore').read_bytes()
        self.assertEqual(
            hashlib.sha256(raw_ignore[:14357]).hexdigest(),
            '27c9cf8c77766e2d30c59482db18e427c3813314a84dcdec04598893b37795cc',
        )
        self.assertEqual(hashlib.sha256(raw[:79]).hexdigest(), POLICY_SHA256)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            'bde45e822b6777c244ddc5938e8b0829e0b87e14fdd77fb20810ce527153ab15',
        )
        policy = tomllib.loads(raw.decode('utf-8'))
        self.assertEqual(policy['extend'], {'useDefault': True})
        self.assertNotIn('allowlist', policy)
        self.assertEqual(set(policy), {'title', 'extend', 'allowlists'})
        self.assertEqual(len(policy['allowlists']), 120)
        self.assertEqual(policy['title'], 'RGN Farma System secret detection policy')
        for entry in policy['allowlists']:
            self.assertEqual(
                set(entry),
                {'description', 'condition', 'targetRules', 'regexTarget', 'paths', 'regexes'},
            )
            self.assertEqual(entry['condition'], 'AND')
            self.assertEqual(entry['targetRules'], ['generic-api-key'])
            self.assertEqual(entry['regexTarget'], 'match')
            self.assertEqual(len(entry['paths']), 1)
            self.assertEqual(len(entry['regexes']), 1)
        self.assertNotIn('rules', policy)

    def test_known_locations_are_metadata_hash_values_not_secret_assertions(self):
        for _, path, _, line in KNOWN_FINDINGS:
            text = (ROOT / path).read_text(encoding='utf-8').splitlines()[line - 1]
            value = text.strip().rstrip(',').rsplit(': ', 1)[1].strip('"')
            self.assertEqual(len(value), 64)
            self.assertTrue(all(char in '0123456789abcdef' for char in value))
            # Digest provenance is verified against actual referenced bytes by the
            # separate scanner probes, not inferred from this shape check.
