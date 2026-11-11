const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/stock-quote.js', 'utf8');

async function harness({hidden = false, offline = false} = {}) {
  let now = Date.parse('2026-11-06T02:30:00Z');
  const listeners = {}, timers = new Map(), nodes = {};
  let sequence = 0, calls = 0, fail = false;
  const panel = {
    dataset: {code: '2330', market: 'TW', quoteUrl: '/api/stock/2330/quote'},
    querySelector: (key) => nodes[key] ||= {textContent: '', classList: {toggle() {}}},
  };
  const document = {hidden, querySelector: () => panel, addEventListener: (name, callback) => listeners[name] = callback};
  const navigator = {onLine: !offline};
  const window = {addEventListener: (name, callback) => listeners[name] = callback};
  const payload = {status: 'available', code: '2330', price: 100.5, change_pct: .5,
    currency: 'TWD', quoted_at: '2026-11-06T02:29:30Z', source: 'Yahoo Finance', refresh_seconds: 60};
  class Clock extends Date { static now() { return now; } }
  vm.runInNewContext(source, {document, navigator, window, Date: Clock, Intl, AbortController,
    setTimeout: (callback, delay) => {timers.set(++sequence, {callback, delay}); return sequence;},
    clearTimeout: (id) => timers.delete(id),
    fetch: async () => {calls++; if (fail) throw Error('network'); return {ok: true, json: async () => payload};},
  });
  const flush = async () => {for (let i = 0; i < 8; i++) await Promise.resolve();};
  await flush();
  return {nodes, timers, document, navigator, listeners, payload,
    get calls() {return calls;}, fail() {fail = true;}, flush,
    async tick() {const [id, timer] = [...timers][0]; timers.delete(id); now += timer.delay; timer.callback(); await flush();},
  };
}

(async () => {
  const live = await harness();
  assert.equal(live.calls, 1);
  assert.match(live.nodes['[data-quote-price]'].textContent, /100\.50/);
  assert.match(live.nodes['[data-quote-time]'].textContent, /2026/);
  assert.equal([...live.timers.values()][0].delay, 60000);
  live.document.hidden = true; live.listeners.visibilitychange();
  assert.equal(live.timers.size, 0);
  live.document.hidden = false; live.listeners.visibilitychange(); await live.flush();
  assert.equal(live.calls, 1, 'switching tabs must not bypass the minimum interval');
  assert.match(live.nodes['[data-quote-status]'].textContent, /60 秒更新/, 'resume must restore the scheduled update status');
  await live.tick(); assert.equal(live.calls, 2);
  live.fail(); await live.tick();
  assert.match(live.nodes['[data-quote-price]'].textContent, /100\.50/, 'failure keeps last quote');
  assert.match(live.nodes['[data-quote-status]'].textContent, /失敗/);
  assert.equal([...live.timers.values()][0].delay, 300000);
  live.navigator.onLine = false; live.listeners.offline();
  assert.equal(live.timers.size, 0);
  const hidden = await harness({hidden: true}); assert.equal(hidden.calls, 0);
  const offline = await harness({offline: true}); assert.equal(offline.calls, 0);
  const bad = await harness(); bad.payload.code = 'AAPL'; await bad.tick();
  assert.match(bad.nodes['[data-quote-status]'].textContent, /失敗/);
  const old = await harness(); old.payload.quoted_at = '2026-11-05T02:29:30Z'; await old.tick();
  assert.match(old.nodes['[data-quote-status]'].textContent, /失敗/);
  console.log('Quote frontend: visibility, cadence, offline, failure retention, identity and monotonic time passed');
})().catch(error => {console.error(error); process.exitCode = 1;});
