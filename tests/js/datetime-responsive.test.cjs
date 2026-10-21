// Wiring-only DOM doubles. Native validity/geometry are tested in Chromium by
// tests/test_datetime_responsive.py; no fake validator result counts as that proof.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const test = require('node:test');

function fixture({ narrow = true, disabled = false, readOnly = false } = {}) {
    const elements = [];
    class Element extends EventTarget {
        constructor(tag) {
            super(); this.tagName = tag; this.children = []; this.attrs = new Map();
            this.dataset = {}; this.classList = { add() {} }; this.className = 'form-control';
            this.value = ''; this.min = ''; this.max = ''; this.step = '1';
            this.validity = { valid: true, badInput: false }; this.nodeType = 1;
        }
        hasAttribute(name) { return this.attrs.has(name); }
        getAttribute(name) { return this.attrs.get(name) ?? null; }
        setAttribute(name, value) { this.attrs.set(name, value); }
        removeAttribute(name) { this.attrs.delete(name); }
        appendChild(node) { this.children.push(node); }
        insertAdjacentElement(_where, node) { elements.push(node); }
        querySelectorAll() { return []; }
        cloneNode() { return new Element(this.tagName); }
        setCustomValidity() {}
        matches(selector) { return selector === 'input[type="datetime-local"]' && this.type === 'datetime-local'; }
    }
    const source = new Element('input');
    Object.assign(source, { id: 'id_deadline', type: 'datetime-local', name: 'deadline',
        value: '2026-10-21T09:51:17', disabled, readOnly,
        labels: [{ textContent: 'Prazo', htmlFor: 'id_deadline' }] });
    let ready, observe;
    const media = { matches: narrow, addEventListener(_name, fn) { this.change = fn; } };
    const document = {
        body: {},
        addEventListener(name, fn) { if (name === 'DOMContentLoaded') ready = fn; },
        querySelector() { return null; },
        querySelectorAll(selector) { return selector === 'input[type="datetime-local"]' ? [source] : []; },
        createElement(tag) { const e = new Element(tag); elements.push(e); return e; },
    };
    class MutationObserver { constructor(fn) { observe = fn; } observe() {} }
    vm.runInNewContext(fs.readFileSync('static/js/app-form-enhancements.js', 'utf8'), {
        document, window: { matchMedia() { return media; } }, MutationObserver, Event,
        queueMicrotask, Map, setTimeout,
    });
    ready();
    return { source, media, elements, observe, parts: () => elements.filter(e => e.dataset.datetimePart) };
}

test('narrow editor preserves canonical POST name and ISO, retaining invalid partials for the server', () => {
    const f = fixture();
    const [date, time] = f.parts();
    time.value = '10:22:59'; time.dispatchEvent(new Event('input'));
    assert.equal(f.source.value, '2026-10-21T10:22:59');
    assert.equal(f.source.name, 'deadline');
    assert.equal(f.source.type, 'text');
    assert.equal(date.name, undefined);
    assert.equal(time.name, undefined);
    date.value = ''; date.dispatchEvent(new Event('input'));
    assert.equal(f.source.value, 'T10:22:59');
    assert.equal(date.required, true);
});

test('wide screen remains native; narrowing enhances once and widening does not lose partial edits', () => {
    const f = fixture({ narrow: false });
    assert.equal(f.parts().length, 0);
    f.media.matches = true; f.media.change();
    assert.equal(f.parts().length, 2);
    f.parts()[0].value = '';
    f.media.matches = false; f.media.change();
    f.media.matches = true; f.media.change();
    assert.equal(f.parts().length, 2);
    assert.equal(f.parts()[0].value, '');
});

test('disabled and readonly controls remain untouched and duplicate scan is idempotent', () => {
    assert.equal(fixture({ disabled: true }).parts().length, 0);
    assert.equal(fixture({ readOnly: true }).parts().length, 0);
    const f = fixture();
    f.observe([{ addedNodes: [f.source] }]);
    assert.equal(f.parts().length, 2);
});
