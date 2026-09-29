"""Run the actual trading render functions with a small DOM fixture."""
import pathlib
import shutil
import subprocess
import unittest


class TradingUiTests(unittest.TestCase):
    def test_saved_plan_controls_and_followup_render(self):
        source = (pathlib.Path(__file__).parents[1] / "static/app.js").read_text(encoding="utf-8")
        functions = source[source.index("async function loadTradingState()"):source.index("function initTrading()")]
        harness = r"""
const assert = require('node:assert/strict');
const commands = [];
function element(tag, cls, text) {
  return {tag, text, children: [], handlers: {},
    appendChild(child) { this.children.push(child); },
    replaceChildren(...children) { this.children = children; },
    addEventListener(name, fn) { this.handlers[name] = fn; }};
}
const root = {dataset: {}};
const plans = element('div'); const followup = element('div');
function bySelector(selector) { return {'[data-trading-root]':root, '[data-saved-plans]':plans, '[data-followup]':followup}[selector]; }
const emptyState = (text) => element('p', '', text);
const tradingUuid = () => 'request-id';
async function tradingPost(body) { commands.push(body); return {}; }
const assistant = {saved_plans:[{plan_id:'tp_one', position_context:'unheld', plan:{plan_id:'tp_one',market:'US',symbol:'INTC',action:'wait'}}],events:[]};
async function fetch() { return {ok:true,json:async()=>({assistant,followup:{counts:{total:1,ready:0,watching:0,unavailable:0,not_triggered:1},plans:[]}})}; }
"""
        checks = r"""
(async () => {
  await loadTradingState();
  assert.match(followup.children[0].text, /總計畫 1/);
  const card = plans.children[0];
  const position = card.children.flatMap(child => child.children).find(child => child.tag === 'select');
  assert.ok(position, 'held/unheld control missing');
  position.value = 'held'; await position.handlers.change();
  assert.equal(commands[0].action, 'set_position_context');
  assert.equal(commands[0].plan_id, 'tp_one');
  assert.equal(commands[0].position_context, 'held');
  const cancel = card.children.find(child => child.tag === 'button');
  assert.ok(cancel, 'cancel control missing');
  await cancel.handlers.click();
  assert.equal(commands[1].action, 'cancel_plan');
  assert.equal(commands[1].plan_id, 'tp_one');
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([shutil.which("node") or "node", "-"], input=harness + functions + checks,
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
