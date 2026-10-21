from pathlib import Path
import shlex

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    'filename', ['docker-compose.yml', 'docker-compose.vps.yml', '.github/workflows/quality.yml']
)
def test_rabbitmq_healthcheck_uses_broker_identity_before_startup(filename):
    compose = yaml.safe_load((ROOT / filename).read_text(encoding='utf-8'))
    if filename.startswith('.github/'):
        options = shlex.split(compose['jobs']['quality']['services']['rabbitmq']['options'])
        command = options[options.index('--health-cmd') + 1]
    else:
        command = compose['services']['rabbitmq']['healthcheck']['test']
    if isinstance(command, str):
        command = shlex.split(command)
    elif command[0] == 'CMD-SHELL':
        command = shlex.split(command[1])
    elif command[0] == 'CMD':
        command = command[1:]

    # A root diagnostic can create a root-owned cookie before broker startup.
    # Dropping privilege prevents that race without reading or weakening the cookie.
    assert command == ['su-exec', 'rabbitmq', 'rabbitmq-diagnostics', '-q', 'ping']
