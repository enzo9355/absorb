(() => {
  const panel = document.querySelector('[data-stock-quote]');
  if (!panel) return;
  const price = panel.querySelector('[data-quote-price]');
  const change = panel.querySelector('[data-quote-change]');
  const time = panel.querySelector('[data-quote-time]');
  const status = panel.querySelector('[data-quote-status]');
  const currency = panel.dataset.market === 'TW' ? 'TWD' : 'USD';
  const formatter = new Intl.DateTimeFormat('zh-TW', {
    timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false,
  });
  let timer, controller, nextDue = 0, lastTimestamp = 0;
  let activeStatus = '正在取得報價…';
  const visible = () => !document.hidden && navigator.onLine !== false;
  const schedule = () => {
    clearTimeout(timer);
    if (visible()) timer = setTimeout(refresh, Math.max(0, nextDue - Date.now()));
  };
  async function refresh() {
    if (!visible() || controller) return;
    if (Date.now() < nextDue) { schedule(); return; }
    controller = new AbortController();
    const current = controller;
    const timeout = setTimeout(() => current.abort(), 8000);
    nextDue = Date.now() + 60000;
    try {
      const response = await fetch(panel.dataset.quoteUrl, {
        signal: current.signal, cache: 'no-store', headers: {Accept: 'application/json'},
      });
      if (!response.ok) throw new Error('Quote unavailable');
      const data = await response.json();
      const timestamp = Date.parse(data.quoted_at);
      if (data.status !== 'available' || data.code !== panel.dataset.code ||
          data.currency !== currency || data.source !== 'Yahoo Finance' ||
          !Number.isFinite(data.price) || data.price <= 0 || !Number.isFinite(data.change_pct) ||
          !Number.isFinite(timestamp) || timestamp <= 0 || timestamp > Date.now() + 300000 ||
          timestamp < lastTimestamp) throw new Error('Invalid quote');
      if (!visible() || current.signal.aborted) return;
      price.textContent = data.price.toLocaleString('zh-TW', {minimumFractionDigits: 2, maximumFractionDigits: 2});
      change.textContent = `${data.change_pct > 0 ? '+' : ''}${data.change_pct.toFixed(2)}% · ${currency}`;
      change.classList.toggle('positive', data.change_pct > 0);
      change.classList.toggle('negative', data.change_pct < 0);
      time.textContent = `報價時間 ${formatter.format(new Date(timestamp))}（台北）`;
      lastTimestamp = timestamp;
      const seconds = Number.isFinite(data.refresh_seconds) ? Math.max(60, Math.min(900, data.refresh_seconds)) : 60;
      nextDue = Date.now() + seconds * 1000;
      activeStatus = seconds > 60 ? '非一般交易時段，降低更新頻率' : '觀看時每 60 秒更新';
      status.textContent = activeStatus;
    } catch (_) {
      if (visible()) {
        activeStatus = '更新失敗，5 分鐘後重試；請留意報價時間';
        status.textContent = activeStatus;
        nextDue = Date.now() + 300000;
      }
    } finally {
      clearTimeout(timeout);
      controller = null;
      schedule();
    }
  }
  function resumeOrPause() {
    clearTimeout(timer);
    if (visible()) {
      status.textContent = activeStatus;
      refresh();
    } else {
      if (controller) controller.abort();
      status.textContent = navigator.onLine === false ? '網路離線，暫停更新' : '頁面在背景，暫停更新';
    }
  }
  document.addEventListener('visibilitychange', resumeOrPause);
  window.addEventListener('online', resumeOrPause);
  window.addEventListener('offline', resumeOrPause);
  window.addEventListener('pagehide', () => { clearTimeout(timer); if (controller) controller.abort(); });
  window.addEventListener('pageshow', resumeOrPause);
  resumeOrPause();
})();
