"""Contract for immutable Git findings; real scanner probes live in private evidence.

A fingerprint is an exact (commit, file, rule, line) identity, not a file
exclusion or a statement that arbitrary SHA-shaped values are harmless.
Directory findings have no commit and must not match these exceptions.
"""

import hashlib
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


def added_findings():
    """Parse only the appended entries, leaving the historical prefix intact."""
    raw = (ROOT / '.gitleaksignore').read_bytes()
    findings = []
    for line in raw[PREFIX_LENGTH:].decode('utf-8').splitlines():
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

    def test_only_fifteen_confirmed_findings_are_appended(self):
        findings = added_findings()
        self.assertEqual(len(findings), 15)
        self.assertEqual(len(set(findings)), 15)
        self.assertEqual(set(findings), set(KNOWN_FINDINGS))

    def test_entries_have_no_patterns_or_directory_exemptions(self):
        findings = added_findings()
        self.assertEqual(set(findings), set(KNOWN_FINDINGS))
        for commit, path, rule, line in findings:
            self.assertEqual(commit, COMMIT)
            self.assertEqual(len(commit), 40)
            self.assertTrue(all(char in '0123456789abcdef' for char in commit))
            self.assertFalse(PurePosixPath(path).is_absolute())
            self.assertNotIn('..', PurePosixPath(path).parts)
            self.assertFalse(any(char in path for char in '*?[]{}()^$\\'))
            self.assertTrue(path.startswith(BASE))
            self.assertTrue(path.endswith('.json'))
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
        self.assertEqual(actual, set(KNOWN_FINDINGS))
        for _, path, rule, line in KNOWN_FINDINGS:
            self.assertNotIn(('', path, rule, line), actual)

    def test_same_location_in_another_commit_is_not_exempt(self):
        actual = set(added_findings())
        self.assertEqual(actual, set(KNOWN_FINDINGS))
        # Changed bytes necessarily belong to a different immutable Git commit.
        for _, path, rule, line in KNOWN_FINDINGS:
            self.assertNotIn(('f' * 40, path, rule, line), actual)

    def test_other_path_namespaces_and_basename_suffixes_are_not_exempt(self):
        actual = set(added_findings())
        self.assertEqual(actual, set(KNOWN_FINDINGS))
        for commit, path, rule, line in KNOWN_FINDINGS:
            for other_path in (
                path + '.backup',
                'config/' + PurePosixPath(path).name,
                'elsewhere/' + path,
                './' + path,
            ):
                self.assertNotIn((commit, other_path, rule, line), actual)

    def test_only_unsafe_historical_allowlist_is_removed(self):
        raw = (ROOT / '.gitleaks.toml').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), POLICY_SHA256)
        policy = tomllib.loads(raw.decode('utf-8'))
        self.assertEqual(policy['extend'], {'useDefault': True})
        self.assertNotIn('allowlists', policy)
        self.assertNotIn('allowlist', policy)
        self.assertEqual(
            policy,
            {
                'title': 'RGN Farma System secret detection policy',
                'extend': {'useDefault': True},
            },
        )
        self.assertNotIn('rules', policy)

    def test_known_locations_are_metadata_hash_values_not_secret_assertions(self):
        for _, path, _, line in KNOWN_FINDINGS:
            text = (ROOT / path).read_text(encoding='utf-8').splitlines()[line - 1]
            value = text.strip().rstrip(',').rsplit(': ', 1)[1].strip('"')
            self.assertEqual(len(value), 64)
            self.assertTrue(all(char in '0123456789abcdef' for char in value))
            # Digest provenance is verified against actual referenced bytes by the
            # separate scanner probes, not inferred from this shape check.
