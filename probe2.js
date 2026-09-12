const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const w of [390, 768]) {
    const p = await b.newPage({ viewport: { width: w, height: 844 } });
    await p.goto('http://127.0.0.1:8311/', { waitUntil: 'networkidle' });
    const r = await p.evaluate(() => {
      const box = (sel) => { const e=document.querySelector(sel); if(!e) return null; const r=e.getBoundingClientRect(); return {t:Math.round(r.top+window.scrollY), b:Math.round(r.bottom+window.scrollY)}; };
      return { brief: box('.today-brief'), stream: box('.update-stream'), why: box('.research-command'), mainTop: box('#main-content') };
    });
    console.log(w, JSON.stringify(r));
    await p.close();
  }
  await b.close();
})();
