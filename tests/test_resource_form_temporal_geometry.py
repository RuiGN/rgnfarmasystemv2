"""Opt-in real Chromium geometry for native temporal parent/inline controls.

Existing local browser only; loopback HTTP, no DB, no credentials/downloads.
Run RGN_UI_BROWSER_TESTS=1 RGN_UI_CHROME=/existing/chromium pytest this_file.
"""

import json
import os
from pathlib import Path
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

import pytest
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
    temporal = [
        ('date', '2026-10-21'),
        ('time', '12:34:56'),
        ('datetime-local', '2026-10-21T12:34:56'),
    ]

    def fields(scope):
        return ''.join(
            f'<div class="form-field"><label for="{scope}-{kind}">{kind}</label>'
            f'<input id="{scope}-{kind}" class="control-size--md form-control" '
            f'type="{kind}" step="1" value="{value}"></div>'
            for kind, value in temporal
        )

    content = (
        '<!doctype html><html><head><meta charset="utf-8">'
        + ''.join(f'<link rel="stylesheet" href="/static/{p}">' for p in STYLES)
        + '<link rel="stylesheet" href="/fixture.css"></head><body>'
        '<form class="resource-form resource-form-tabs">'
        '<section class="fixture-column resource-form-field">'
        + fields('parent')
        + '</section><section class="fixture-column card resource-inline-formset">'
        '<div class="card-body p-4"><div class="border rounded-2 p-3" data-inline-formset-form>'
        '<div class="form-grid">'
        + fields('inline')
        + '</div></div></div></section></form></body></html>'
    ).encode()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def do_GET(self):
            if self.path == '/':
                body, kind = content, 'text/html; charset=utf-8'
            elif self.path == '/fixture.css':
                body = b'.fixture-column{width:241px;margin-left:37px}'
                kind = 'text/css'
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


@pytest.mark.parametrize('scope', ['parent', 'inline'])
@pytest.mark.parametrize(
    'kind, expected',
    [
        ('date', '2026-10-21'),
        ('time', '12:34:56'),
        ('datetime-local', '2026-10-21T12:34:56'),
    ],
)
def test_native_temporal_control_fits_its_column(computed_browser, scope, kind, expected):
    call = computed_browser
    call(
        'Emulation.setDeviceMetricsOverride',
        width=320,
        height=1000,
        deviceScaleFactor=1,
        mobile=False,
    )
    selector = f'#{scope}-{kind}'
    state = call(
        'Runtime.evaluate',
        returnByValue=True,
        expression="""(() => {
      const e=document.querySelector(SELECTOR), p=e.parentElement;
      const r=e.getBoundingClientRect(), q=p.getBoundingClientRect();
      const s=getComputedStyle(e), picker=getComputedStyle(e,'::-webkit-calendar-picker-indicator');
      return {type:e.type,value:e.value,attribute:e.getAttribute('value'),
        x:r.x,right:r.right,width:r.width,parentX:q.x,parentRight:q.right,
        parentWidth:q.width,parentClient:p.clientWidth,parentScroll:p.scrollWidth,
        minWidth:s.minWidth,maxWidth:s.maxWidth,overflow:s.overflowX,
        appearance:s.appearance,pickerDisplay:picker.display,viewport:innerWidth};
    })()""".replace('SELECTOR', json.dumps(selector)),
    )['result']['value']
    print(json.dumps({'id': selector, **state}, sort_keys=True))
    assert state['viewport'] == 320
    assert 173 <= state['parentWidth'] <= 241, 'The narrow fixture column must actually apply.'
    assert state['type'] == kind
    assert state['value'] == state['attribute'] == expected
    assert state['pickerDisplay'] != 'none', 'Native picker must not be removed.'
    assert state['x'] >= state['parentX'] - 1
    assert state['right'] <= state['parentRight'] + 1, state
    assert state['parentScroll'] <= state['parentClient'] + 1, state

    # Native shadow content can still clip even when the outer input fits.
    document = call('DOM.getDocument', depth=-1, pierce=True)

    def descendants(node):
        yield node
        for child in node.get('children', []) + node.get('shadowRoots', []):
            yield from descendants(child)

    native_edits = []
    for node in descendants(document['root']):
        attrs = dict(zip(node.get('attributes', [])[::2], node.get('attributes', [])[1::2]))
        if attrs.get('id') != f'{scope}-{kind}':
            continue
        for shadow in descendants(node):
            attributes = dict(
                zip(shadow.get('attributes', [])[::2], shadow.get('attributes', [])[1::2])
            )
            if attributes.get('pseudo') == '-webkit-datetime-edit':
                obj = call('DOM.resolveNode', backendNodeId=shadow['backendNodeId'])['object'][
                    'objectId'
                ]
                geometry = call(
                    'Runtime.callFunctionOn',
                    objectId=obj,
                    returnByValue=True,
                    functionDeclaration='function(){return {client:this.clientWidth,scroll:this.scrollWidth}}',
                )['result']['value']
                native_edits.append(geometry)
                print(json.dumps({'nativeEdit': selector, **geometry}))
                assert geometry['scroll'] <= geometry['client'] + 1, geometry
    assert len(native_edits) == 1, 'Native editable shadow content must actually be inspected.'
