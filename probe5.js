const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  await p.goto('http://127.0.0.1:8311/', { waitUntil: 'domcontentloaded' });
  const r = await p.evaluate(() => {
    const e = document.querySelector('[data-dashboard-error]');
    return { hasHiddenAttr: e.hasAttribute('hidden'), display: getComputedStyle(e).display, h: e.getBoundingClientRect().height };
  });
  console.log(JSON.stringify(r));
  await b.close();
})();
