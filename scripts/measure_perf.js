// 介面層效能量測（規格書 §12.3）。基準值與回歸門檻見 docs/perf-baseline.md。
// 用法：先啟動本地伺服器，再 `node scripts/measure_perf.js [port]`。
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const rows = [];
  for (const path of ['/','/market','/industries','/stocks','/reports','/learn','/ask']) {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, bypassCSP: false });
    const p = await ctx.newPage();
    let bytes = { html:0, css:0, js:0, font:0, other:0 };
    p.on('response', async (r) => {
      try {
        const url = r.url(); const len = Number(r.headers()['content-length'] || 0);
        const size = len || (await r.body().catch(()=>Buffer.alloc(0))).length;
        const clean = url.split('?')[0];
        if (clean.endsWith('.css')) bytes.css += size;
        else if (clean.endsWith('.js')) bytes.js += size;
        else if (/\.(woff2?|ttf)/.test(clean)) bytes.font += size;
        else if (r.request().resourceType() === 'document') bytes.html += size;
        else bytes.other += size;
      } catch (_e) {}
    });
    await p.goto(`http://127.0.0.1:${process.argv[2] || 8521}${path}`, { waitUntil: 'networkidle' });
    const m = await p.evaluate(() => new Promise((res) => {
      const nav = performance.getEntriesByType('navigation')[0] || {};
      let lcp = 0;
      try { new PerformanceObserver((l) => { for (const e of l.getEntries()) lcp = e.startTime; }).observe({type:'largest-contentful-paint', buffered:true}); } catch(_e){}
      setTimeout(() => {
        const fcp = (performance.getEntriesByName('first-contentful-paint')[0]||{}).startTime || 0;
        res({ fcp: Math.round(fcp), lcp: Math.round(lcp), dcl: Math.round(nav.domContentLoadedEventEnd||0) });
      }, 700);
    }));
    rows.push({ path, ...m, ...bytes });
    await ctx.close();
  }
  const tot = rows.reduce((a,r)=>({css:Math.max(a.css,r.css), js:Math.max(a.js,r.js), font:Math.max(a.font,r.font)}), {css:0,js:0,font:0});
  console.log(JSON.stringify({ rows, worst: tot }, null, 1));
  await b.close();
})();
