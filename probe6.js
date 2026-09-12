const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const [w,h,tag] of [[1440,1000,'d'],[390,844,'m']]) {
    const p = await b.newPage({ viewport: { width: w, height: h } });
    await p.goto('http://127.0.0.1:8311/stocks', { waitUntil: 'networkidle' });
    const r = await p.evaluate(() => ({
      pageH: document.querySelector('.page').getBoundingClientRect().height,
      groups: document.querySelectorAll('.event-group').length,
      summary: document.querySelectorAll('.event-summary-item').length,
      accent: [...document.querySelectorAll('.event-group')].map(e=>getComputedStyle(e).borderLeftWidth),
      docW: document.documentElement.scrollWidth, winW: window.innerWidth,
    }));
    console.log(tag, JSON.stringify(r));
    await p.screenshot({ path: `/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_stocks_${tag}.png`, fullPage: true });
    await p.close();
  }
  await b.close();
})();
