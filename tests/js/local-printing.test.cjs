const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../static/js/local-printing.js'), 'utf8');

function setup({ count = 2, confirm = true, fetch, missingToken = -1, missingStatus = false } = {}) {
    const calls = [];
    const confirmations = [];
    const status = { className: 'alert d-none', textContent: '' };
    const forms = Array.from({ length: count }, (_, i) => ({
        querySelector: () => i === missingToken ? null : { value: `csrf-${i}` },
    }));
    const buttons = forms.map((form, i) => ({
        disabled: false,
        dataset: { labelPrintUrl: `/api/inventory/lots/${i + 1}/print_label/` },
        listeners: {},
        closest: () => form,
        addEventListener(name, callback) { this.listeners[name] = callback; },
    }));
    const document = {
        querySelector(selector) {
            if (selector === '[data-label-print-button]') return buttons[0];
            if (selector === '[data-label-print-form]') return forms[0];
            if (selector === '[data-label-print-status]') return missingStatus ? null : status;
            return null;
        },
        querySelectorAll: () => buttons,
    };
    vm.runInNewContext(source, {
        document,
        window: {
            confirm(message) { confirmations.push(message); return confirm; },
        },
        fetch: async (...args) => {
            calls.push(args);
            return fetch ? fetch(...args) : {
                ok: true,
                json: async () => ({ detail: 'Etiqueta enviada à impressora.' }),
            };
        },
    });
    return {
        buttons, calls, confirmations, status,
        click(i) {
            assert.equal(typeof buttons[i].listeners.click, 'function', `listener on row ${i}`);
            return buttons[i].listeners.click();
        },
    };
}

test('each row sends its own URL and CSRF token', async () => {
    const ui = setup();
    await ui.click(1);
    await ui.click(0);
    assert.equal(ui.calls.length, 2);
    assert.equal(ui.calls[0][0], '/api/inventory/lots/2/print_label/');
    assert.equal(ui.calls[0][1].headers['X-CSRFToken'], 'csrf-1');
    assert.equal(ui.calls[1][0], '/api/inventory/lots/1/print_label/');
    assert.equal(ui.calls[1][1].headers['X-CSRFToken'], 'csrf-0');
    for (const [, options] of ui.calls) {
        assert.equal(options.method, 'POST');
        assert.equal(options.credentials, 'same-origin');
        assert.equal(options.headers['X-Requested-With'], 'XMLHttpRequest');
    }
    assert.equal(ui.status.textContent, 'Etiqueta enviada à impressora.');
});

test('single-button detail and cockpit retain their behavior', async () => {
    const ui = setup({ count: 1 });
    await ui.click(0);
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.confirmations.length, 1);
    assert.equal(ui.buttons[0].disabled, false);
});

test('cancelled confirmation sends nothing', async () => {
    const ui = setup({ confirm: false });
    await ui.click(1);
    assert.equal(ui.calls.length, 0);
    assert.equal(ui.buttons[1].disabled, false);
});

test('in-flight row is disabled and duplicate click sends nothing', async () => {
    let finish;
    const pending = new Promise(resolve => { finish = resolve; });
    const ui = setup({ fetch: () => pending });
    const click = ui.click(1);
    assert.equal(ui.buttons[1].disabled, true);
    assert.equal(ui.buttons[0].disabled, false);
    await ui.click(1);
    assert.equal(ui.calls.length, 1);
    finish({ ok: true, json: async () => ({ detail: 'Enviado' }) });
    await click;
    assert.equal(ui.buttons[1].disabled, false);
});

test('HTTP failure shows literal server text without resending', async () => {
    const ui = setup({ fetch: async () => ({
        ok: false,
        json: async () => ({ detail: '<img src=x onerror=alert(1)>' }),
    }) });
    await ui.click(1);
    assert.equal(ui.status.textContent, '<img src=x onerror=alert(1)>');
    assert.equal(ui.status.className, 'alert alert-danger mb-4');
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.buttons[1].disabled, false);
});

test('network failure is not resent automatically', async () => {
    const ui = setup({ fetch: async () => { throw new Error('Conexão indisponível'); } });
    await ui.click(1);
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.status.textContent, 'Conexão indisponível');
    assert.equal(ui.buttons[1].disabled, false);
});

test('non-JSON failure receives safe fallback feedback', async () => {
    const ui = setup({ fetch: async () => ({
        ok: false,
        json: async () => { throw new Error('Invalid JSON'); },
    }) });
    await ui.click(1);
    assert.equal(ui.calls.length, 1);
    assert.equal(ui.status.textContent, 'Não foi possível imprimir a etiqueta.');
    assert.equal(ui.buttons[1].disabled, false);
});

test('missing CSRF in one row does not break other rows', async () => {
    const ui = setup({ missingToken: 0 });
    assert.equal(ui.buttons[0].listeners.click, undefined);
    await ui.click(1);
    assert.equal(ui.calls.length, 1);
});

test('missing feedback container never enables sending', () => {
    const ui = setup({ missingStatus: true });
    assert.ok(ui.buttons.every(button => !button.listeners.click));
    assert.equal(ui.calls.length, 0);
});

test('empty listing initializes without throwing or sending', () => {
    const ui = setup({ count: 0 });
    assert.equal(ui.calls.length, 0);
});
