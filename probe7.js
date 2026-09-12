const { chromium } = require('/opt/node22/lib/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  for (const [port,tag] of [[8322,'baseline'],[8311,'order4']]) {
    const p = await b.newPage({ viewport: { width: 1440, height: 1000 } });
    await p.goto(`http://127.0.0.1:${port}/stocks`, { waitUntil: 'networkidle' });
    const r = await p.evaluate(() => {
      const panel = [...document.querySelectorAll('.picks-panel')][0];
      return { pageH: Math.round(document.querySelector('.page').getBoundingClientRect().height),
               eventPanelH: Math.round(panel.getBoundingClientRect().height),
               groups: document.querySelectorAll('.event-group').length };
    });
    console.log(tag, JSON.stringify(r));
    await p.close();
  }
  await b.close();
})();
