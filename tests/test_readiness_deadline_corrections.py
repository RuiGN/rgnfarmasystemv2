"""Exercise real silent sockets, not mocked driver timeout configuration."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, contextmanager

import pytest
from django.conf import settings


@contextmanager
def silent_dependency(protocol='cache'):
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(0.1)
    stop = threading.Event()
    reached = threading.Event()
    peers = []

    def serve():
        while not stop.is_set():
            try:
                peer, _ = listener.accept()
            except socket.timeout:
                continue
            peer.settimeout(0.1)
            peers.append(peer)
            if protocol == 'database-query':
                # SSL is disabled by the test. Complete startup, then never
                # answer the query: a connect-only timeout cannot fix this.
                while not stop.is_set():
                    try:
                        if peer.recv(8192):
                            break
                    except socket.timeout:
                        continue
                peer.sendall(b'R\x00\x00\x00\x08\x00\x00\x00\x00')
                for key, value in ((b'server_version', b'16.4'), (b'client_encoding', b'UTF8')):
                    payload = key + b'\0' + value + b'\0'
                    peer.sendall(b'S' + (len(payload) + 4).to_bytes(4, 'big') + payload)
                peer.sendall(b'Z\x00\x00\x00\x05I')
            while not stop.is_set():
                try:
                    packet = peer.recv(8192)
                    if packet and (protocol != 'database-query' or packet[:1] in (b'Q', b'P')):
                        reached.set()
                        break
                except socket.timeout:
                    continue
            stop.wait()

    thread = threading.Thread(target=serve)
    thread.start()
    try:
        yield listener.getsockname()[1], reached
    finally:
        stop.set()
        thread.join(timeout=2)
        listener.close()
        for peer in peers:
            peer.close()
        assert not thread.is_alive()


REQUEST = """
import json, os, time
import django
django.setup()
from django.conf import settings
from django.test import RequestFactory, override_settings
from core import views
configuration = json.loads(os.environ['PROBE_TEST_CONFIGURATION'])
with override_settings(**{key: value for key, value in configuration.items() if key == 'CACHES'}):
    active = configuration.pop('ACTIVE_PROBES', ['cache'])
    if 'database' in active:
        from django.db import connections
        connections['default'].close()
        connections['default'].settings_dict = configuration['DATABASES']['default']
    else:
        views.probe_database = lambda: None
    if 'cache' not in active:
        views.probe_cache = lambda: None
    if 'broker' in active:
        from kombu import Connection
        broker_url = configuration['BROKER_TEST_URL']
        views.celery_app.connection_for_read = lambda **kwargs: Connection(broker_url, **kwargs)
    else:
        views.probe_broker = lambda: None
    import subprocess
    children = []
    original_popen = subprocess.Popen
    def track_child(*args, **kwargs):
        child = original_popen(*args, **kwargs)
        children.append(child)
        return child
    subprocess.Popen = track_child
    start = time.monotonic()
    response = views.readiness_check(RequestFactory().get('/ready/'))
    print(json.dumps({'code': response.status_code, 'body': json.loads(response.content),
                      'cache_control': response['Cache-Control'],
                      'children': [child.poll() for child in children],
                      'elapsed': time.monotonic() - start}))
"""


def test_silent_cache_read_returns_503_before_healthcheck_deadline():
    with silent_dependency() as (port, reached):
        configuration = {
            'CACHES': {
                'default': {
                    'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                    'LOCATION': f'redis://127.0.0.1:{port}/0',
                }
            }
        }
        env = dict(os.environ, PROBE_TEST_CONFIGURATION=json.dumps(configuration))
        try:
            result = subprocess.run(
                [sys.executable, '-c', REQUEST], env=env, capture_output=True, text=True, timeout=9
            )
        except subprocess.TimeoutExpired:
            assert False, 'Readiness blocked on a silent cache beyond the 9s supervisor deadline'
        assert reached.is_set(), 'The probe must actually reach the silent dependency'
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['code'] == 503
        assert report['body'] == {
            'status': 'unavailable',
            'checks': {
                'database': True,
                'cache': False,
                'broker': True,
            },
        }
        assert report['cache_control'] == 'no-store'
        assert report['elapsed'] < 3


@pytest.mark.parametrize('protocol', ['database-connect', 'database-query'])
def test_silent_database_returns_503_before_healthcheck_deadline(protocol):
    with silent_dependency(protocol) as (port, reached):
        database = dict(settings.DATABASES['default'])
        database.update(
            HOST='127.0.0.1',
            PORT=str(port),
            NAME='synthetic',
            USER='synthetic',
            PASSWORD='',
            OPTIONS={'sslmode': 'disable'},
            CONN_MAX_AGE=0,
            CONN_HEALTH_CHECKS=False,
        )
        env = dict(
            os.environ,
            PROBE_TEST_CONFIGURATION=json.dumps(
                {
                    'ACTIVE_PROBES': ['database'],
                    'DATABASES': {'default': database},
                }
            ),
        )
        try:
            result = subprocess.run(
                [sys.executable, '-c', REQUEST], env=env, capture_output=True, text=True, timeout=9
            )
        except subprocess.TimeoutExpired:
            assert False, 'Readiness blocked on a silent database beyond the 9s supervisor deadline'
        assert reached.is_set(), 'The database startup/query must reach the silent peer'
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['code'] == 503
        assert report['body']['checks'] == {'database': False, 'cache': True, 'broker': True}
        assert report['elapsed'] < 3


def test_silent_broker_handshake_is_bounded_including_network_reads():
    with silent_dependency('broker') as (port, reached):
        env = dict(
            os.environ,
            PROBE_TEST_CONFIGURATION=json.dumps(
                {
                    'ACTIVE_PROBES': ['broker'],
                    'BROKER_TEST_URL': f'amqp://synthetic:synthetic@127.0.0.1:{port}//',
                }
            ),
        )
        result = subprocess.run(
            [sys.executable, '-c', REQUEST], env=env, capture_output=True, text=True, timeout=9
        )
        assert reached.is_set(), 'The AMQP handshake must reach the silent peer'
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['code'] == 503
        assert report['body']['checks'] == {'database': True, 'cache': True, 'broker': False}
        assert report['elapsed'] < 2.7


def test_all_silent_dependencies_fit_total_budget_and_children_are_reaped():
    with ExitStack() as stack:
        db_port, db_reached = stack.enter_context(silent_dependency('database-query'))
        cache_port, cache_reached = stack.enter_context(silent_dependency())
        broker_port, broker_reached = stack.enter_context(silent_dependency('broker'))
        database = dict(settings.DATABASES['default'])
        database.update(
            HOST='127.0.0.1',
            PORT=str(db_port),
            NAME='synthetic',
            USER='synthetic',
            PASSWORD='',
            OPTIONS={'sslmode': 'disable'},
            CONN_MAX_AGE=0,
            CONN_HEALTH_CHECKS=False,
        )
        env = dict(
            os.environ,
            PROBE_TEST_CONFIGURATION=json.dumps(
                {
                    'ACTIVE_PROBES': ['database', 'cache', 'broker'],
                    'DATABASES': {'default': database},
                    'CACHES': {
                        'default': {
                            'BACKEND': 'django.core.cache.backends.redis.RedisCache',
                            'LOCATION': f'redis://127.0.0.1:{cache_port}/0',
                        }
                    },
                    'BROKER_TEST_URL': f'amqp://synthetic:synthetic@127.0.0.1:{broker_port}//',
                }
            ),
        )
        # django.setup() in this separate test supervisor is not request time.
        result = subprocess.run(
            [sys.executable, '-c', REQUEST], env=env, capture_output=True, text=True, timeout=12
        )
        assert all(event.is_set() for event in (db_reached, cache_reached, broker_reached))
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout)
        assert report['code'] == 503
        assert report['body']['checks'] == {'database': False, 'cache': False, 'broker': False}
        assert report['elapsed'] < 8
        assert report['children'] == [-9, -9, -9]
        print(
            f'silent dependencies elapsed={report["elapsed"]:.3f}s; children={report["children"]}'
        )


def test_real_healthy_probes_do_not_change_operational_settings_or_write_cache(tmp_path):
    from copy import deepcopy
    from django.test import RequestFactory, override_settings
    from kombu import Connection
    from core import views
    from unittest.mock import patch

    cache_config = {
        'default': {
            'BACKEND': 'django.core.cache.backends.filebased.FileBasedCache',
            'LOCATION': str(tmp_path),
        }
    }
    before = deepcopy(settings.DATABASES)
    with (
        override_settings(CACHES=cache_config),
        # This case verifies read-only behavior, not cold interpreter startup.
        # Silent-peer tests above retain the real production deadline.
        patch.object(views, 'READINESS_PROBE_TIMEOUT', 8),
        patch.object(
            views.celery_app,
            'connection_for_read',
            side_effect=lambda **kwargs: Connection('memory://localhost/', **kwargs),
        ),
    ):
        start = time.monotonic()
        response = views.readiness_check(RequestFactory().get('/ready/'))
        elapsed = time.monotonic() - start
        print(f'healthy isolated probes elapsed={elapsed:.3f}s')
        assert response.status_code == 200, response.content
        assert json.loads(response.content)['checks'] == {
            'database': True,
            'cache': True,
            'broker': True,
        }
        assert settings.CACHES == cache_config
    assert settings.DATABASES == before
    assert not list(tmp_path.iterdir()), 'Readiness must not create operational cache entries'
