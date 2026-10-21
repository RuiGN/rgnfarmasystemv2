"""Opt-in computed-browser regression for resource action text, not a WCAG audit.

Run with RGN_UI_BROWSER_TESTS=1 and RGN_UI_CHROME pointing to an existing,
updater-free Chromium binary. No browser download, credentials or database used.
"""

import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest
from django.template.loader import render_to_string
from websockets.sync.client import connect


ROOT = Path(__file__).resolve().parents[1]
STYLES = (
    'vendor/duralux/css/bootstrap.min.css',
    'vendor/duralux/css/theme.min.css',
    'css/app.css',
)


@pytest.fixture(scope='module')
def computed_browser(tmp_path_factory):
    if os.environ.get('RGN_UI_BROWSER_TESTS') != '1':
        pytest.skip('Opt-in real-browser typography check: RGN_UI_BROWSER_TESTS=1')
    binary = Path(os.environ['RGN_UI_CHROME'])
    assert binary.is_file(), 'Use an already installed Chromium binary; never download one.'
    actions = render_to_string('includes/form_actions.html', {'cancel_url': '/cancel/'})
    inline = (ROOT / 'templates/app/includes/inline_stacked.html').read_text()
    add = re.search(r'<button\b[^>]*data-inline-formset-add[\s\S]*?</button>', inline)[0]
    add = add.replace('{{ inline.key }}', 'items').replace(
        '{{ inline.add_label }}', 'Adicionar item'
    )
    content = (
        '<!doctype html><html><head><meta charset="utf-8">'
        + ''.join(f'<link rel="stylesheet" href="/static/{p}">' for p in STYLES)
        + '</head><body><form class="resource-form" data-ui="resource-form">'
        + actions
        + add
        + '<input id="inside" class="form-control"><label for="check">Ativo'
        '<input type="checkbox" id="check" class="form-check-input"></label></form>'
        '<button id="outside" class="btn btn-primary">Fora do recurso</button>'
        '<input id="outside-input" class="form-control">'
        '<input id="outside-check" type="checkbox" class="form-check-input"></body></html>'
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            if self.path == '/':
                body, kind = content, 'text/html; charset=utf-8'
            elif self.path in {'/static/' + p for p in STYLES}:
                body = (ROOT / 'static' / self.path.removeprefix('/static/')).read_bytes()
                kind = 'text/css'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'self'")
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    directory = tmp_path_factory.mktemp('action-typography-browser')
    log = (directory / 'browser.log').open('w')
    process = subprocess.Popen(
        [
            str(binary),
            '--headless=new',
            '--remote-debugging-address=127.0.0.1',
            '--remote-debugging-port=0',
            '--user-data-dir=' + str(directory / 'profile'),
            '--no-first-run',
            '--disable-background-networking',
            '--disable-component-update',
            '--disable-sync',
            '--proxy-server=http://127.0.0.1:9',
            '--proxy-bypass-list=127.0.0.1;localhost',
            '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1, EXCLUDE localhost',
            'about:blank',
        ],
        stdout=log,
        stderr=log,
    )
    websocket = None
    try:
        deadline = time.monotonic() + 20
        active = directory / 'profile/DevToolsActivePort'
        while not active.exists() and time.monotonic() < deadline:
            assert process.poll() is None, 'Browser stopped before CDP was ready.'
            time.sleep(0.05)
        port = int(active.read_text().splitlines()[0])
        with urlopen(f'http://127.0.0.1:{port}/json/version', timeout=3) as response:
            endpoint = json.load(response)['webSocketDebuggerUrl']
        websocket = connect(endpoint, open_timeout=3, max_size=8 * 1024 * 1024)
        sequence, session = 0, None

        def call(method, **params):
            nonlocal sequence
            sequence += 1
            message = {'id': sequence, 'method': method, 'params': params}
            if session and not method.startswith(('Target.', 'Browser.')):
                message['sessionId'] = session
            websocket.send(json.dumps(message))
            while True:
                result = json.loads(websocket.recv(timeout=15))
                if result.get('id') == sequence:
                    assert 'error' not in result, result
                    return result.get('result', {})

        target = call('Target.createTarget', url='about:blank')['targetId']
        session = call('Target.attachToTarget', targetId=target, flatten=True)['sessionId']
        call('Network.enable')
        call('Network.setBlockedURLs', urls=['https://*', 'ftp://*'])
        call('Page.enable')
        call('Page.navigate', url=f'http://127.0.0.1:{server.server_port}/')
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            state = call('Runtime.evaluate', expression='document.readyState', returnByValue=True)
            if state['result'].get('value') == 'complete':
                break
            time.sleep(0.05)
        else:
            pytest.fail('Local typography fixture did not load.')
        yield call
    finally:
        if websocket:
            websocket.close()
        process.terminate()
        process.wait(timeout=10)
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        log.close()


@pytest.mark.parametrize('width', [320, 768, 1024, 1440])
def test_resource_action_text_is_at_least_twelve_pixels_without_changing_inputs(
    computed_browser, width
):
    call = computed_browser
    call(
        'Emulation.setDeviceMetricsOverride',
        width=width,
        height=1000,
        deviceScaleFactor=1,
        mobile=False,
    )
    result = call(
        'Runtime.evaluate',
        returnByValue=True,
        expression="""(() => {
        const sample = selector => {
            const e = document.querySelector(selector), s = getComputedStyle(e);
            return {font: parseFloat(s.fontSize), height: e.getBoundingClientRect().height,
                    color: s.color, background: s.backgroundColor, border: s.border};
        };
        return {width: innerWidth, save: sample('form button[type=submit]'),
                add: sample('[data-inline-formset-add]'), cancel: sample('form a.btn'),
                outside: sample('#outside'), input: sample('#inside'),
                outsideInput: sample('#outside-input'), checkbox: sample('#check'),
                outsideCheckbox: sample('#outside-check')};
    })()""",
    )['result']['value']
    print(json.dumps(result, sort_keys=True))
    assert result['width'] == width
    for action in ('save', 'add', 'cancel'):
        assert result[action]['font'] >= 12, (action, result)
    assert result['input'] == result['outsideInput'], 'Action typography must not restyle inputs.'
    assert result['outside']['font'] == 10, (
        'The Duralux action style outside resource forms is preserved.'
    )
    assert result['save']['color'] == result['outside']['color']
    assert result['save']['background'] == result['outside']['background']
    # A native checkbox is not action text; its associated label/target needs a separate assessment.
    assert result['checkbox'] == result['outsideCheckbox']
