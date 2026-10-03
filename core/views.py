import json

# Only a fixed interpreter/script is executed; configuration is stdin data.
import subprocess  # nosec B404
import sys

from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from django.shortcuts import redirect, render

from core.celery import app as celery_app


def health_check(request):
    return JsonResponse({'status': 'ok'})


def probe_database():
    _run_readiness_probe({'database': connections['default'].settings_dict})


# A killable process bounds silent socket reads as well as connection attempts.
# Do not use worker threads: timing out a future leaves the blocked probe alive.
READINESS_PROBE_TIMEOUT = 2
_READINESS_PROBE_SCRIPT = """
import json, sys
from django.conf import settings
configuration = json.load(sys.stdin)
if 'database' in configuration:
    settings.configure(DATABASES={'default': configuration['database']})
    from django.db import connections
    try:
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT 1')
            if cursor.fetchone() != (1,):
                raise RuntimeError('Database probe failed.')
    finally:
        connections.close_all()
elif 'broker' in configuration:
    from kombu import Connection
    with Connection(**configuration['broker']) as connection:
        connection.ensure_connection(max_retries=0)
else:
    settings.configure(CACHES={'default': configuration['cache']})
    from django.core.cache import caches
    try:
        caches['default'].get('__rgn_readiness_probe__')
    finally:
        caches.close_all()
"""


def _run_readiness_probe(configuration):
    # Configuration (including credentials) is data on stdin, never code/argv.
    # run() kills AND reaps the child on timeout; driver errors are discarded.
    # The interpreter and script are trusted constants; no shell is involved.
    subprocess.run(  # nosec B603
        [sys.executable, '-c', _READINESS_PROBE_SCRIPT],
        input=json.dumps(configuration),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=READINESS_PROBE_TIMEOUT,
        check=True,
    )


def probe_cache():
    # Read-only, with its own connection/configuration, not the operational pool.
    _run_readiness_probe({'cache': settings.CACHES['default']})


def probe_broker():
    with celery_app.connection_for_read(connect_timeout=READINESS_PROBE_TIMEOUT) as connection:
        _run_readiness_probe({'broker': connection.info()})


def readiness_check(request):
    probes = {'database': probe_database, 'cache': probe_cache, 'broker': probe_broker}
    checks = {}
    for name, probe in probes.items():
        try:
            probe()
        except Exception:
            checks[name] = False
        else:
            checks[name] = True
    ready = all(checks.values())
    response = JsonResponse(
        {'status': 'ok' if ready else 'unavailable', 'checks': checks},
        status=200 if ready else 503,
    )
    response['Cache-Control'] = 'no-store'
    return response


def home(request):
    if not request.user.is_authenticated:
        return redirect('accounts:login')
    return redirect('app:index')


def permission_denied(request, exception=None):
    return render(request, 'app/permission_denied.html', {'exception': exception}, status=403)
