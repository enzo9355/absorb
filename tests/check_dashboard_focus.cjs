// Run: node tests/check_dashboard_focus.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
let active = false;
let rendered = [];
const focus = {replaceChildren(...items) { rendered = items; }};
const document = {
  body: {dataset: {}},
  querySelector(selector) { return active && selector === '[data-daily-focus]' ? focus : null; },
  querySelectorAll() { return []; }, addEventListener() {},
  createElement() { return {children: [], setAttribute() {}, append(child) { this.children.push(child); }}; },
};
const context = {document, window: {location: {pathname: '/stocks', hash: ''}, addEventListener() {}}, console};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/app.js', 'utf8'), context);
active = true;
context.renderDashboard({product_mode: 'observation', daily_focus: [null, 23, {}, '市場風險狀態：normal']});
assert.equal(rendered.length, 1);
assert.equal(rendered[0].children[1].textContent, '市場風險狀態：一般');
context.renderDashboard({product_mode: 'observation', daily_focus: null});
assert.equal(rendered[0].textContent, '今日焦點資料不足。');
console.log('PASS: actual app.js ignores non-string focus items and handles a null list.');
