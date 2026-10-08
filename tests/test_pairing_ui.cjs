'use strict';

// Exercise the real browser script without a browser or third-party packages.
// GitHub CI runs these tests; configuration, QR images and API results are fake.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase();
    this.listeners = new Map();
    this.children = [];
    this.attributes = new Map();
    this.dataset = {};
    this.value = '';
    this.textContent = '';
    this.disabled = false;
    this.hidden = false;
    this.open = false;
    this.classList = { add() {}, remove() {}, toggle() {} };
  }

  addEventListener(type, listener) {
    const listeners = this.listeners.get(type) || [];
    listeners.push(listener);
    this.listeners.set(type, listeners);
  }

  emit(type) {
    return Promise.all((this.listeners.get(type) || []).map(listener => listener({ target: this })));
  }

  appendChild(child) {
    this.children.push(child);
    if (this.tagName === 'SELECT' && !this.value) this.value = child.value;
    return child;
  }

  append(...children) { children.forEach(child => this.appendChild(child)); }
  replaceChildren() { this.children = []; if (this.tagName === 'SELECT') this.value = ''; }
  querySelectorAll() { return []; }
  removeAttribute(name) { this.attributes.delete(name); }
  getAttribute(name) { return this.attributes.has(name) ? this.attributes.get(name) : null; }
  set src(value) { this.attributes.set('src', value); }
  get src() { return this.getAttribute('src'); }
  showModal() { assert.equal(this.open, false); this.open = true; }
  close() { this.open = false; return this.emit('close'); }
}

function page(overrides) {
  const elements = new Map();
  const element = id => {
    if (!elements.has(id)) elements.set(id, new Element(id === 'pair-address' ? 'select' : id === 'pair-dialog' ? 'dialog' : 'div'));
    return elements.get(id);
  };
  const document = {
    createElement: tag => new Element(tag),
    getElementById: element,
    querySelectorAll: () => [],
    addEventListener() {},
    documentElement: {},
    body: new Element('body'),
  };
  let timerId = 0;
  const timers = new Map();
  const context = vm.createContext({
    document,
    window: { addEventListener() {} },
    // Keep init() at its first await so unrelated application flows stay idle.
    fetch: () => new Promise(() => {}),
    setTimeout: callback => { const id = ++timerId; timers.set(id, callback); return id; },
    setInterval: callback => { const id = ++timerId; timers.set(id, callback); return id; },
    clearInterval: id => timers.delete(id),
    overrides,
  });
  const script = fs.readFileSync(path.join(__dirname, '..', 'gui', 'app.js'), 'utf8');
  vm.runInContext(script, context, { filename: 'gui/app.js' });
  vm.runInContext('Object.assign(api, overrides)', context);
  return {
    element,
    click: id => element(id).emit('click'),
    close: () => element('pair-dialog').close(),
    drainMutations: () => vm.runInContext('pairingMutations', context),
  };
}

function ready(id, firewall = {}) {
  return {
    ok: true,
    address: '192.168.1.13',
    qr_svg: `data:image/svg+xml;base64,dummy-qr-${id}`,
    expires_at: Date.now() / 1000 + 120,
    firewall,
  };
}

function networks() {
  return Promise.resolve({ ok: true, addresses: [{ address: '192.168.1.13', label: 'Wi-Fi', network_category: 'public' }] });
}

function assertControlsDisabled(ui, expected) {
  for (const id of ['pair-address', 'pair-renew-btn', 'pair-allow-btn']) {
    assert.equal(ui.element(id).disabled, expected, `${id} disabled state`);
  }
}

test('closing and reopening during QR renewal never lets an old response cancel the new session', { timeout: 5000 }, async () => {
  const oldResponse = deferred(), oldStarted = deferred();
  const newResponse = deferred(), newStarted = deferred();
  const events = [];
  let active = null, starts = 0;
  const ui = page({
    pairNetwork: networks,
    pairCancel: async () => { events.push(`cancel:${active}`); active = null; return { ok: true }; },
    pairStart: async () => {
      active = ++starts; events.push(`start:${active}`);
      if (starts === 2) { oldStarted.resolve(); return oldResponse.promise; }
      if (starts === 3) { newStarted.resolve(); return newResponse.promise; }
      return ready(starts);
    },
  });
  await ui.click('pair-start-btn');
  const renewal = ui.click('pair-renew-btn');
  await oldStarted.promise;
  const closing = ui.close();
  const reopening = ui.click('pair-start-btn');
  oldResponse.resolve(ready(2));
  await newStarted.promise;
  await renewal;
  assert.equal(ui.element('pair-dialog').open, true);
  assertControlsDisabled(ui, true);
  assert.equal(ui.element('pair-qr').hidden, true, 'stale QR must remain hidden');
  newResponse.resolve(ready(3));
  await Promise.all([closing, reopening]);
  await ui.drainMutations();
  assert.equal(active, 3);
  assert.equal(ui.element('pair-qr').src, ready(3).qr_svg);
  assert.equal(ui.element('pair-qr').hidden, false);
  assertControlsDisabled(ui, false);
  assert.deepEqual(events, ['cancel:null', 'start:1', 'cancel:1', 'start:2', 'cancel:2', 'cancel:null', 'start:3']);
});

test('a failed QR regeneration closes the old access and removes its image', { timeout: 5000 }, async () => {
  let active = false, starts = 0;
  const events = [];
  const ui = page({
    pairNetwork: networks,
    pairCancel: async () => { active = false; events.push('cancel'); return { ok: true }; },
    pairStart: async () => {
      starts++; events.push('start');
      if (starts > 1) return { ok: false, error: 'invalid_config' };
      active = true; return ready(1);
    },
  });
  await ui.click('pair-start-btn');
  assert.equal(active, true);
  await ui.click('pair-renew-btn');
  await ui.drainMutations();
  assert.equal(active, false);
  assert.equal(ui.element('pair-qr').src, null);
  assert.equal(ui.element('pair-qr').hidden, true);
  assert.equal(ui.element('pair-status').textContent, 'config_invalid');
  assertControlsDisabled(ui, false);
  assert.deepEqual(events, ['cancel', 'start', 'cancel', 'start']);
});

for (const outcome of ['allowed', 'rejected']) {
  test(`an old UAC ${outcome} result cannot alter a reopened pairing dialog`, { timeout: 5000 }, async () => {
    const allowResponse = deferred(), allowStarted = deferred();
    const freshResponse = deferred(), freshStarted = deferred();
    let starts = 0;
    const ui = page({
      pairNetwork: networks,
      pairCancel: async () => ({ ok: true }),
      pairAllow: async () => { allowStarted.resolve(); return allowResponse.promise; },
      pairStart: async () => {
        starts++;
        if (starts === 2) { freshStarted.resolve(); return freshResponse.promise; }
        return ready(starts, { supported: true, can_configure: true, state: 'unknown' });
      },
    });
    await ui.click('pair-start-btn');
    assert.equal(ui.element('pair-allow-btn').hidden, false);
    const permission = ui.click('pair-allow-btn');
    await allowStarted.promise;
    const closing = ui.close();
    const reopening = ui.click('pair-start-btn');
    await freshStarted.promise;
    const statusBefore = ui.element('pair-firewall-status').textContent;
    assertControlsDisabled(ui, true);
    if (outcome === 'allowed') allowResponse.resolve({ ok: true });
    else allowResponse.reject(new Error('dummy UAC failure'));
    await permission;
    assert.equal(starts, 2, 'old permission must not regenerate the current QR');
    assert.equal(ui.element('pair-firewall-status').textContent, statusBefore);
    assertControlsDisabled(ui, true);
    assert.equal(ui.element('pair-qr').src, null);
    freshResponse.resolve(ready(2, { supported: true, can_configure: true, state: 'blocked' }));
    await Promise.all([closing, reopening]);
    assert.equal(ui.element('pair-qr').src, ready(2).qr_svg);
    assert.equal(ui.element('pair-firewall-status').textContent, 'pair_firewall_detected');
    assertControlsDisabled(ui, false);
  });
}
