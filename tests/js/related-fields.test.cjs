const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function fixture() {
  const listeners = {};
  const form = {elements: {}};
  function select(name, value, rules, options) {
    const node = {
      name, value, form, disabled: false, dataset: {}, options: [],
      addEventListener(type, fn) {this.listener = fn;},
      dispatchEvent(event) {this.events = (this.events || 0) + 1; listeners[event.type]?.({target: this});},
      matches(selector) {return Boolean(this.dataset.relatedRules);},
    };
    node.options = options.map(v => ({value: v, disabled: false, hidden: false}));
    if (rules) node.dataset.relatedRules = JSON.stringify(rules);
    form.elements[name] = node;
    return node;
  }
  const country = select('rows-0-country', 'br', null, ['br', 'pt']);
  const state = select('rows-0-state', 'sp', [{controller:'rows-0-country', values:{sp:['br'], lx:['pt']}}], ['', 'sp', 'lx']);
  const city = select('rows-0-city', 'sao', [{controller:'rows-0-state', values:{sao:['sp'], lis:['lx']}}], ['', 'sao', 'lis']);
  let nodes = [state, city];
  const document = {
    readyState: 'complete',
    querySelectorAll() {return nodes;},
    addEventListener(type, fn) {listeners[type] = fn;},
    documentElement: {},
  };
  const context = {document, Event: class {constructor(type, opts) {this.type=type; this.bubbles=opts?.bubbles;}},
    MutationObserver: class {constructor(fn) {context.mutate=fn;} observe() {}},
    console};
  vm.runInNewContext(fs.readFileSync('static/js/related-fields.js', 'utf8'), context);
  return {country, state, city, context, select, nodes, listeners};
}

test('initialization filters native options without losing compatible selection', () => {
  const {state, city} = fixture();
  assert.equal(state.options[2].disabled, true);
  assert.equal(state.options[1].disabled, false);
  assert.equal(state.value, 'sp');
  assert.equal(city.value, 'sao');
});

test('controller change clears incompatible value and emits cascade', () => {
  const {country, state, city, listeners} = fixture();
  country.value = 'pt';
  listeners.change({target:country});
  assert.equal(state.value, '');
  assert.equal(city.value, '');
  assert.ok(state.events > 0);
  assert.ok(city.events > 0);
  assert.equal(state.options[2].disabled, false);
});

test('new prefixed inline initializes without touching disabled controls', () => {
  const f = fixture();
  const country = f.select('rows-1-country', 'pt', null, ['br','pt']);
  const state = f.select('rows-1-state', 'sp', [{controller:country.name,values:{sp:['br'],lx:['pt']}}], ['', 'sp','lx']);
  f.nodes.push(state);
  f.context.mutate([{addedNodes:[state]}]);
  assert.equal(state.value, '');
  state.disabled = true;
  state.value = 'sp';
  f.listeners.change({target:country});
  assert.equal(state.value, 'sp');
});

test('existing disabled options never become authorized after filtering', () => {
  const f = fixture();
  // Simulate an already-disabled option at initialization on a new inline.
  const state = f.select('rows-2-state', 'lx', [{controller:'rows-0-country',values:{sp:['br'],lx:['pt']}}], ['', 'sp','lx']);
  state.options[1].disabled = true;
  f.nodes.push(state);
  f.context.mutate([{addedNodes:[state]}]);
  assert.equal(state.options[1].disabled, true);
  assert.equal(state.value, '');
});

test('generic route survives formula changes and foreign prefixes stay isolated', () => {
  const f = fixture();
  const formula = f.select('rows-3-formula', 'one', null, ['one', 'two']);
  const route = f.select('rows-3-route', 'generic', [{controller:formula.name,values:{generic:['*'],specific:['two']}}], ['', 'generic','specific']);
  f.nodes.push(route);
  f.context.mutate([{addedNodes:[route]}]);
  assert.equal(route.value, 'generic');
  assert.equal(route.options[2].disabled, true);
  formula.value = 'two';
  f.listeners.change({target:formula});
  assert.equal(route.options[2].disabled, false);
  assert.equal(f.state.value, 'sp');
});

test('incompatible initial choice is cleared on load with a change event', () => {
  const f = fixture();
  const state = f.select('rows-4-state', 'lx', [{controller:'rows-0-country',values:{sp:['br'],lx:['pt']}}], ['', 'sp','lx']);
  f.nodes.push(state);
  f.context.mutate([{addedNodes:[state]}]);
  assert.equal(state.value, '');
  assert.ok(state.events > 0);
});
