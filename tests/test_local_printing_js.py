"""Execute the real printing controller against an isolated DOM/transport harness."""

from pathlib import Path
import shutil
import subprocess

import pytest


def test_local_printing_javascript_behavior():
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required for the printing-controller behavior tests.')
    result = subprocess.run(
        [node, '--test', str(Path(__file__).parent / 'js' / 'local-printing.test.cjs')],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
