const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
  await p.goto('http://127.0.0.1:8311/', { waitUntil: 'networkidle' });
  const r = await p.evaluate(() => {
    const g = (sel, prop='fontSize') => [...document.querySelectorAll(sel)].map(e => getComputedStyle(e)[prop]);
    const box = (sel) => { const e=document.querySelector(sel); if(!e) return null; const r=e.getBoundingClientRect(); return {t:Math.round(r.top+window.scrollY), h:Math.round(r.height)}; };
    const cs = (sel, ...props) => { const e=document.querySelector(sel); if(!e) return null; const c=getComputedStyle(e); const o={}; props.forEach(k=>o[k]=c[k]); return o; };
    return {
      metricTitle: g('.command-metrics .metric-title'),
      metricValueUnavail: g('.command-metrics .value-unavailable'),
      termTag: g('.command-metrics .term-tag'),
      researchCommand: cs('.research-command','padding','borderTopWidth','backgroundColor','borderRadius'),
      forecastEmpty: cs('.forecast-panel.is-empty','backgroundColor','color'),
      sections: {
        brief: box('.today-brief'),
        stream: box('.update-stream'),
        why: box('.research-command'),
        limits: box('.data-limits'),
      },
      detailsOpen: document.querySelector('.data-limits')?.open,
      h1: document.querySelectorAll('h1').length,
      docW: document.documentElement.scrollWidth,
      winW: window.innerWidth,
    };
  });
  console.log(JSON.stringify(r, null, 1));
  await p.screenshot({ path: '/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_four_1440.png', fullPage: true });
  await p.setViewportSize({ width: 390, height: 844 });
  await p.waitForTimeout(400);
  const m = await p.evaluate(() => ({ docW: document.documentElement.scrollWidth, winW: window.innerWidth }));
  console.log('mobile', JSON.stringify(m));
  await p.screenshot({ path: '/tmp/claude-0/-home-user-absorb/8c6c509c-c7b3-5626-b120-01362a2e8a9a/scratchpad/o4_four_390.png', fullPage: true });
  await b.close();
})();
