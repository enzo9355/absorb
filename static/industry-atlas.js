/* Progressive enhancement: GET search and evidence remain usable without JavaScript. */
(() => {
  const root = document.getElementById('industry-atlas');
  const form = document.getElementById('atlas-search-form');
  if (!root || !form) return;
  const graph = document.getElementById('atlas-graph');
  const svg = graph.querySelector('.atlas-wires');
  const edges = JSON.parse(document.getElementById('atlas-edges').textContent);
  const ns = 'http://www.w3.org/2000/svg';
  function draw() {
    svg.replaceChildren();
    if (root.classList.contains('is-list') || getComputedStyle(svg).display === 'none') return;
    const box = graph.getBoundingClientRect();
    if (!box.width) return;
    svg.setAttribute('viewBox', `0 0 ${box.width} ${box.height}`);
    const nodes = new Map([...graph.querySelectorAll('[data-company-key]')].map(node => [node.dataset.companyKey, node.getBoundingClientRect()]));
    const defs = document.createElementNS(ns, 'defs');
    const marker = document.createElementNS(ns, 'marker');
    for (const [key, value] of Object.entries({id:'atlas-arrow',viewBox:'0 0 8 8',refX:7,refY:4,markerWidth:5,markerHeight:5,orient:'auto'})) marker.setAttribute(key, value);
    const tip = document.createElementNS(ns, 'path');
    tip.setAttribute('d', 'M0 0 L8 4 L0 8 Z');
    tip.setAttribute('fill', 'context-stroke');
    marker.append(tip); defs.append(marker); svg.append(defs);
    for (const edge of edges) {
      const a = nodes.get(edge.from.key), b = nodes.get(edge.to.key);
      if (!a || !b) continue;
      const sameLane = Math.abs(a.left - b.left) < 2;
      const forward = a.left < b.left;
      const x1 = (sameLane || forward ? a.right : a.left) - box.left;
      const x2 = (sameLane || !forward ? b.right : b.left) - box.left;
      const y1 = a.top + a.height / 2 - box.top, y2 = b.top + b.height / 2 - box.top;
      const bend = sameLane ? Math.min(box.width - 2, x1 + 14) : (x1 + x2) / 2;
      const path = document.createElementNS(ns, 'path');
      path.setAttribute('d', `M${x1} ${y1} C${bend} ${y1},${bend} ${y2},${x2} ${y2}`);
      path.setAttribute('fill', 'none'); path.setAttribute('stroke', 'var(--atlas-accent)');
      path.setAttribute('stroke-width', '1.5'); path.setAttribute('opacity', '.7');
      if (edge.directed) path.setAttribute('marker-end', 'url(#atlas-arrow)');
      else path.setAttribute('stroke-dasharray', '5 4');
      svg.append(path);
    }
  }
  root.querySelector('.atlas-view-switch').hidden = false;
  root.querySelectorAll('[data-atlas-view]').forEach(button => button.addEventListener('click', () => {
    root.classList.toggle('is-list', button.dataset.atlasView === 'list');
    root.querySelectorAll('[data-atlas-view]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
    requestAnimationFrame(draw);
  }));
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => requestAnimationFrame(draw)).observe(graph);
  requestAnimationFrame(draw);

  const input = document.getElementById('atlas-query');
  const market = document.getElementById('atlas-market');
  const results = document.getElementById('atlas-search-results');
  const list = document.getElementById('atlas-results');
  const status = document.getElementById('atlas-search-status');
  let timer, controller, generation = 0;
  input.addEventListener('input', () => {
    clearTimeout(timer); controller?.abort();
    const version = ++generation;
    if (!input.value.trim()) { results.hidden = true; list.replaceChildren(); return; }
    timer = setTimeout(async () => {
      controller = new AbortController();
      const params = new URLSearchParams(new FormData(form));
      results.hidden = false;
      list.replaceChildren();
      status.textContent = '正在搜尋已收錄公司…';
      try {
        const response = await fetch(`${form.dataset.searchApi}?${params}`, {signal:controller.signal, headers:{Accept:'application/json'}});
        if (!response.ok) throw new Error('search unavailable');
        const data = await response.json();
        if (version !== generation) return;
        const fragment = document.createDocumentFragment();
        for (const company of data.search_results) {
          const article = document.createElement('article'); article.className = 'atlas-result';
          const name = document.createElement('strong'); name.textContent = company.name;
          const code = document.createElement('span'); code.textContent = `${company.market} · ${company.symbol}`;
          const links = document.createElement('div');
          for (const membership of company.industries) {
            const link = document.createElement('a');
            const target = new URL(form.action);
            target.search = new URLSearchParams({industry:membership.id,focus:company.key,market:market.value});
            link.href = target.href; link.textContent = `${membership.topic} →`; links.append(link);
          }
          article.append(name, code, links); fragment.append(article);
        }
        list.replaceChildren(fragment);
        status.textContent = data.search_results.length ? `找到 ${data.search_results.length} 家公司` : '尚未收錄符合條件的公司；未收錄不代表沒有產業關係。';
      } catch (error) {
        if (version !== generation || error.name === 'AbortError') return;
        status.textContent = '即時搜尋暫時無法使用，請按「搜尋」重新查詢。';
      }
    }, 180);
  });
  market.addEventListener('change', () => form.requestSubmit());
})();
