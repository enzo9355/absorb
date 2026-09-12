const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  await p.goto('http://127.0.0.1:8355/market', { waitUntil: 'networkidle' });
  const r = await p.evaluate(() => ({
    bareUnits: /—\s*%|—／—|>\s*%\s*</.test(document.body.innerHTML),
    legend: document.querySelectorAll('.chart-legend div').length,
    swatchUp: getComputedStyle(document.querySelector('.legend-up')||document.body).backgroundColor,
    swatchMa: getComputedStyle(document.querySelector('.legend-ma')||document.body).backgroundColor,
    caveats: document.querySelectorAll('.chart-caveat').length,
    detailsOpen: document.querySelector('.data-limits')?.open,
    docW: document.documentElement.scrollWidth, winW: window.innerWidth,
  }));
  console.log(JSON.stringify(r));
  await p.screenshot({ path: '/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_market.png', fullPage: true });
  await b.close();
})();
