const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const p = await b.newPage({ viewport: { width: 390, height: 844 } });
  await p.goto('http://127.0.0.1:8311/', { waitUntil: 'networkidle' });
  const r = await p.evaluate(() => {
    document.querySelector('[data-dashboard-error]').hidden = true;
    const box = (s)=>{const e=document.querySelector(s);const r=e.getBoundingClientRect();return {t:Math.round(r.top+scrollY),b:Math.round(r.bottom+scrollY)};};
    return { brief: box('.today-brief'), streamHeading: box('.update-stream .section-heading'), firstItem: box('.update-item') };
  });
  console.log('verified-case', JSON.stringify(r));
  await b.close();
})();
