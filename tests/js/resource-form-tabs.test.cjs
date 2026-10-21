const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function submit(formNoValidate) {
    const handlers = {};
    let checks = 0;
    const form = {
        checkValidity() { checks++; return false; },
        querySelector() { return null; },
        addEventListener(name, callback) { handlers[name] = callback; },
    };
    const button = {};
    const root = {
        dataset: {},
        closest() { return form; },
        querySelectorAll() { return [button]; },
        querySelector(selector) {
            return selector === '[role="tablist"]' ? { addEventListener() {} } : null;
        },
    };
    const document = {
        querySelectorAll() { return [root]; },
        addEventListener(name, callback) { if (name === 'DOMContentLoaded') callback(); },
    };
    vm.runInNewContext(fs.readFileSync('static/js/resource-form-tabs.js', 'utf8'), {
        document, window: { bootstrap: { Tab: { getOrCreateInstance() {} } } }, queueMicrotask,
    });
    const event = {
        submitter: { formNoValidate }, prevented: false,
        preventDefault() { this.prevented = true; }, stopImmediatePropagation() {},
    };
    handlers.submit(event);
    return { checks, prevented: event.prevented };
}

test('related creation and version load bypass unrelated principal validation', () => {
    assert.deepEqual(submit(true), { checks: 0, prevented: false });
});
test('ordinary Save still refuses invalid principal controls', () => {
    assert.deepEqual(submit(false), { checks: 1, prevented: true });
});
