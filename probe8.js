const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  // 浮動面板
  await p.goto('http://127.0.0.1:8344/stocks', { waitUntil: 'networkidle' });
  await p.click('[data-quick-ask-open]');
  await p.waitForTimeout(400);
  const ex = await p.evaluate(() => [...document.querySelectorAll('[data-quick-ask-example]')].map(e=>e.textContent.trim()));
  console.log('stocks examples:', JSON.stringify(ex, null, 0));
  await p.screenshot({ path: '/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_ask_panel.png' });
  // 點範例：只填入不送出
  const before = await p.evaluate(() => document.querySelectorAll('[data-conversation-log] .conversation-message').length);
  await p.click('[data-quick-ask-example]');
  await p.waitForTimeout(300);
  const after = await p.evaluate(() => ({
    inputValue: document.querySelector('.quick-ask-sheet input[name=question]').value,
    messages: document.querySelectorAll('.quick-ask-sheet [data-conversation-log] .conversation-message').length,
    examplesHidden: document.querySelector('.quick-ask-sheet [data-quick-ask-examples]').hidden,
    focused: document.activeElement.name,
  }));
  console.log('before msgs', before, 'after click:', JSON.stringify(after));
  // 完整頁
  await p.goto('http://127.0.0.1:8344/ask', { waitUntil: 'networkidle' });
  const full = await p.evaluate(() => ({
    examples: [...document.querySelectorAll('[data-quick-ask-example]')].map(e=>e.textContent.trim()),
    hasFab: !!document.querySelector('.quick-ask-trigger'),
    footerPad: getComputedStyle(document.querySelector('.site-footer')).paddingBottom,
  }));
  console.log('full page:', JSON.stringify(full, null, 0));
  await p.screenshot({ path: '/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_ask_full.png', fullPage: true });
  await b.close();
})();
