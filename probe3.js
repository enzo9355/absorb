const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  await p.goto('http://127.0.0.1:8311/', { waitUntil: 'networkidle' });
  const r = await p.evaluate(() => {
    const out = {};
    const sels = ['.today-brief','.today-brief .state-note','.research-status','.today-copy h1','.research-headline','.today-risk','.research-limit','.today-facts','.update-stream .section-heading','.update-list'];
    sels.forEach(s => { const e=document.querySelector(s); out[s] = e ? {h:Math.round(e.getBoundingClientRect().height), fs:getComputedStyle(e).fontSize} : null; });
    out.factsCols = getComputedStyle(document.querySelector('.today-facts')).gridTemplateColumns;
    return out;
  });
  console.log(JSON.stringify(r, null, 1));
  await b.close();
})();
