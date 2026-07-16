const bySelector = (selector, root = document) => root.querySelector(selector);

function element(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined && text !== null) item.textContent = String(text);
  return item;
}

function replaceContent(container, items) {
  container.replaceChildren(...items);
}

function emptyState(message) {
  return element("div", "empty-state", message);
}

function stockHref(code, fallback = "/dashboard") {
  const normalized = String(code || "").toUpperCase();
  return /^[A-Z0-9.-]{1,16}$/.test(normalized)
    ? `/stock/${encodeURIComponent(normalized)}`
    : fallback;
}

function card(tag, className, rows, href) {
  const item = element(tag, className);
  if (href) item.setAttribute("href", href);
  rows.forEach(([rowTag, rowClass, value]) => item.append(element(rowTag, rowClass, value)));
  return item;
}

async function loadDashboard() {
  const page = bySelector("[data-dashboard-endpoint]");
  if (!page) return;
  try {
    const response = await fetch(page.dataset.dashboardEndpoint, { headers: { Accept: "application/json" } });
    if (!response.ok) throw new Error("dashboard");
    renderDashboard(await response.json());
  } catch (error) {
    const banner = bySelector("[data-dashboard-error]");
    if (banner) banner.hidden = false;
  }
}

function renderDashboard(data) {
  const presentation = data.presentation || {};
  const outputLabel = presentation.model_output_label || "五日上漲機率";
  const bootstrap = data.baseline_status === "initial_backtest_bootstrap";
  const picksTitle = bySelector("[data-top-picks-title]");
  if (picksTitle) picksTitle.textContent = presentation.top_picks_label || "精選標的";
  const outputDescription = bySelector("[data-model-output-description]");
  if (outputDescription) {
    outputDescription.textContent = bootstrap
      ? "顏色代表模型方向分數，尚未完成機率校準驗證"
      : "顏色代表五日上漲機率，不等同即時漲跌";
  }
  const guideTitle = bySelector("[data-model-output-guide-title]");
  const guide = bySelector("[data-model-output-guide]");
  if (guideTitle) guideTitle.textContent = `${outputLabel}是什麼？`;
  if (guide) {
    guide.textContent = bootstrap
      ? "這是未完成機率校準驗證的模型方向分數，只能作研究觀察，不是真實上漲機率。"
      : "它是五個交易日內方向判斷的已驗證機率，不是保證獲利。";
  }
  const marketData = data.market || {};
  const marketRecommendation = marketData.recommendation || {};
  const hero = bySelector("[data-market-hero]");
  if (hero) {
    const label = element("p", `action-label action-${marketRecommendation.level || "insufficient"}`, marketRecommendation.action || "等待資料");
    const headline = element("h1", "market-headline", marketRecommendation.headline || "市場建議資料暫時不足");
    const reasons = element("ul", "hero-reasons");
    (marketRecommendation.supporting_reasons || []).slice(0, 3).forEach((reason) => reasons.append(element("li", "", reason)));
    if (!reasons.children.length) reasons.append(element("li", "", "等待完整市場資料更新"));
    const risk = element("p", "hero-risk");
    risk.append(element("strong", "", "最大風險："));
    risk.append(document.createTextNode((marketRecommendation.risk_reasons || ["資料品質不足"])[0]));
    const meta = element("p", "muted small", `資料日 ${marketData.as_of || "待更新"} · ${marketRecommendation.confidence || "可信度低"}`);
    replaceContent(hero, [label, headline, reasons, risk, meta]);
  }

  const market = bySelector("[data-market-summary]");
  if (market) {
    replaceContent(market, [
      card("article", "pulse-card", [["span", "", "市場行動"], ["strong", "", marketRecommendation.action || "等待資料"], ["small", "muted", marketRecommendation.headline || "市場建議資料不足"]]),
      card("article", "pulse-card", [["span", "", "優先方向"], ["strong", "", (data.sector_cards || [])[0]?.name || "等待資料"], ["small", "muted", "先看產業，再評估個股"]]),
      card("article", "pulse-card", [["span", "", "最大風險"], ["strong", "", (marketRecommendation.risk_reasons || ["資料品質不足"])[0]], ["small", "muted", `加權指數 ${Number(marketData.price || 0).toFixed(2)}`]]),
    ]);
  }
  const status = bySelector(".status-dot");
  if (status) status.textContent = marketData.as_of ? `資料日 ${marketData.as_of}` : "已更新";

  const watchlist = bySelector("[data-watchlist-strip]");
  if (watchlist) {
    const hint = data.watchlist_hint || { title: "", steps: [] };
    replaceContent(watchlist, (hint.steps || []).map((step, index) =>
      card("article", "watch-chip", [["span", "", `Step ${index + 1}`], ["strong", "", step]])
    ));
  }

  const focus = bySelector("[data-daily-focus]");
  if (focus) {
    const items = data.top_picks || [];
    replaceContent(focus, items.length ? items.slice(0, 2).map((item) =>
      card("a", "focus-card", [["span", "", item.recommendation?.action || "等待確認"], ["strong", "", item.name], ["small", "", item.headline], ["small", "", item.summary]], stockHref(item.code))
    ) : [emptyState("今日焦點等待產業快照更新。")]);
  }

  const heatmap = bySelector("[data-market-heatmap]");
  if (heatmap) {
    const cells = data.heatmap || [];
    if (cells.length > 0 && cells.length < 3) {
      heatmap.style.gridTemplateColumns = `repeat(${cells.length}, minmax(0, 1fr))`;
    } else {
      heatmap.style.gridTemplateColumns = "";
    }
    replaceContent(heatmap, cells.length ? cells.map((item) =>
      card("a", `heatmap-cell ${["hot", "cold", "steady"].includes(item.tone) ? item.tone : "steady"}`, [["span", "", item.name], ["strong", "", `${item.direction_score ?? item.probability}`], ["small", "", `${outputLabel} · ${item.count} 檔觀察`]], item.code ? stockHref(item.code, "#industry-forecast") : "#industry-forecast")
    ) : [emptyState("今日產業樣本尚未完成，暫不提供產業熱力圖。")]);
  }

  const forecasts = bySelector("[data-sector-grid]");
  if (forecasts) {
    const cards = data.sector_cards || [];
    replaceContent(forecasts, cards.length ? cards.map((sector, index) => {
      const recommendation = sector.leader.recommendation || {};
      return card("a", "forecast-card", [
        ["span", "", `第 ${index + 1} 名 · ${sector.name}`],
        ["strong", "", recommendation.action || "等待確認"],
        ["small", "", `${sector.leader.model_output_label || outputLabel} ${sector.leader.direction_score ?? sector.leader.prob} · ${sector.leader.trend}`],
        ["small", "", recommendation.headline || "等待完整資料"],
        ["small", "", `代表股票 ${sector.leader.name || "待更新"} · ${recommendation.confidence || "可信度低"}`],
      ], stockHref(sector.leader.code));
    }) : [emptyState("產業預測快照尚未準備好，請稍後再試。")]);
  }

  const picks = bySelector("[data-top-picks]");
  if (picks) {
    const items = data.top_picks || [];
    const stocks = items.filter(item => !item.is_etf);
    const etfs = items.filter(item => item.is_etf);
    
    const elements = [];
    
    // Stocks Section
    elements.push(element("h3", "sub-section-title", bootstrap ? "量化觀察個股" : "精選個股"));
    const stocksGrid = element("div", `top-picks count-${Math.min(3, stocks.length || 1)}`);
    if (stocks.length) {
      stocks.forEach(item => {
        const rec = item.recommendation || {};
        stocksGrid.append(card("a", "pick-card", [
          ["span", "badge-stock", `[個股] ${item.name} · ${item.code}`],
          ["strong", "", rec.action || "等待確認"],
          ["p", "", item.headline],
          ["p", "", item.summary],
          ["small", "", `主要風險：${(rec.risk_reasons || ["資料不足"])[0]}`],
        ], stockHref(item.code)));
      });
    } else {
      stocksGrid.append(emptyState("目前沒有足夠的精選個股資料。"));
    }
    elements.push(stocksGrid);
    
    // ETFs Section
    elements.push(element("h3", "sub-section-title", "ETF 觀察"));
    const etfsGrid = element("div", `top-picks count-${Math.min(3, etfs.length || 1)}`);
    if (etfs.length) {
      etfs.forEach(item => {
        const rec = item.recommendation || {};
        etfsGrid.append(card("a", "pick-card", [
          ["span", "badge-etf", `[ETF] ${item.name} · ${item.code}`],
          ["strong", "", rec.action || "等待確認"],
          ["p", "", item.headline],
          ["p", "", item.summary],
        ], stockHref(item.code)));
      });
    } else {
      etfsGrid.append(emptyState("目前沒有足夠的 ETF 觀察資料。"));
    }
    elements.push(etfsGrid);
    
    replaceContent(picks, elements);
  }
}

function loginLocation() {
  const returnTo = `${window.location.pathname}${window.location.search}`;
  return `/auth/line/login?return_to=${encodeURIComponent(returnTo)}`;
}

function updateAccountInterface(data) {
  window.absorbAccount = data;
  const account = bySelector("[data-account-nav]");
  if (account) {
    const profile = element("a", "account-profile-link");
    profile.href = "/account";
    if (data.user.picture_url) {
      const picture = element("img", "account-avatar");
      picture.src = data.user.picture_url;
      picture.alt = "";
      picture.referrerPolicy = "no-referrer";
      profile.append(picture);
    }
    const label = element("span", "");
    label.append(element("strong", "", data.user.display_name));
    label.append(element("small", "", "已連結 LINE"));
    profile.append(label);
    const watchlist = element("a", "nav-link", `我的關注（${data.watchlist.length}）`);
    watchlist.href = "/account/watchlist";
    const logout = element("button", "link-button", "登出");
    logout.type = "button";
    logout.dataset.accountLogout = "";
    replaceContent(account, [profile, watchlist, logout]);
  }
  const mobile = bySelector("[data-mobile-account]");
  if (mobile) mobile.textContent = "我的";
  const toggle = bySelector("[data-watchlist-toggle]");
  if (toggle) {
    const watched = data.watchlist.some((item) => item.code === toggle.dataset.code);
    toggle.dataset.authenticated = "true";
    toggle.dataset.watched = String(watched);
    toggle.textContent = watched ? "取消關注" : "加入關注";
    toggle.setAttribute("aria-pressed", String(watched));
  }
}

async function loadAccountState() {
  try {
    const response = await fetch("/api/account/state", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    updateAccountInterface(await response.json());
  } catch (_error) {
    // 公開頁維持未登入狀態；不顯示內部錯誤。
  }
}

function appendConversationMessage(log, role, text) {
  const empty = bySelector(".empty-state", log);
  if (empty) empty.remove();
  const message = element("p", `conversation-message ${role}`, text);
  log.append(message);
  log.scrollTop = log.scrollHeight;
}

function initConversation() {
  const form = bySelector("[data-conversation-form]");
  const panel = bySelector("[data-conversation-endpoint]");
  const log = bySelector("[data-conversation-log]");
  if (!form || !panel || !log) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const input = bySelector("input[name='question']", form);
    const button = bySelector("button", form);
    const question = input.value.trim();
    if (!question) return;
    appendConversationMessage(log, "user", question);
    input.value = "";
    button.disabled = true;
    const headers = { Accept: "application/json", "Content-Type": "application/json" };
    if (window.absorbAccount?.csrf_token) headers["X-CSRF-Token"] = window.absorbAccount.csrf_token;
    try {
      const response = await fetch(panel.dataset.conversationEndpoint, {
        method: "POST",
        headers,
        body: JSON.stringify({ question }),
      });
      const data = await response.json();
      appendConversationMessage(log, "assistant", response.ok ? data.text : "自然語言分析暫時無法使用，請稍後再試。");
    } catch (_error) {
      appendConversationMessage(log, "assistant", "自然語言分析暫時無法使用，固定指令與股票查詢不受影響。");
    } finally {
      button.disabled = false;
      input.focus();
    }
  });
}

async function toggleWatchlist(button) {
  const account = window.absorbAccount;
  if (!account) {
    window.location.assign(loginLocation());
    return;
  }
  button.disabled = true;
  try {
    const response = await fetch("/api/account/watchlist", {
      method: "POST",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
        "X-CSRF-Token": account.csrf_token,
      },
      body: JSON.stringify({
        action: button.dataset.watched === "true" ? "remove" : "add",
        code: button.dataset.code,
      }),
    });
    if (!response.ok) throw new Error("watchlist");
    account.watchlist = (await response.json()).watchlist;
    updateAccountInterface(account);
  } catch (_error) {
    button.textContent = "暫時無法更新，請稍後再試";
  } finally {
    button.disabled = false;
  }
}

function formatNumber(value) {
  return Number.isFinite(value) ? Math.round(value).toLocaleString("zh-TW") : "—";
}

function initReturnCalculator() {
  const panel = bySelector("[data-return-calculator]");
  if (!panel) return;
  const input = bySelector("[data-investment-amount]", panel);
  const price = Number(panel.dataset.price);
  const strategyReturn = Number(panel.dataset.strategyReturn);
  const buyholdReturn = Number(panel.dataset.buyholdReturn);
  const update = () => {
    const amount = Number(input.value);
    const shares = Math.floor(amount / price);
    const deployed = shares * price;
    const valid = Number.isFinite(amount) && amount > 0 && price > 0 && shares > 0;
    bySelector("[data-shares]", panel).textContent = valid ? shares.toLocaleString("zh-TW") : "—";
    bySelector("[data-deployed]", panel).textContent = valid ? formatNumber(deployed) : "—";
    bySelector("[data-strategy-profit]", panel).textContent = valid ? formatNumber((deployed * strategyReturn) / 100) : "—";
    bySelector("[data-buyhold-profit]", panel).textContent = valid ? formatNumber((deployed * buyholdReturn) / 100) : "—";
  };
  input.addEventListener("input", update);
  update();
}

function measureChartHeight(container) {
  return Math.max(320, Math.min(460, Math.round(container.clientWidth * 0.62)));
}

function setChartRange(days) {
  if (!window.stockChart) return;
  const { chart, length } = window.stockChart;
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, length - days), to: length + 5 });
}

function initStockChart() {
  const container = bySelector("#stock-chart");
  const source = bySelector("#stock-chart-data");
  if (!container || !source || !window.LightweightCharts) return;
  const raw = JSON.parse(source.textContent);
  const candles = JSON.parse(raw.candles);
  const height = measureChartHeight(container);
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height,
    layout: { background: { color: "transparent" }, textColor: "#586579" },
    grid: { vertLines: { color: "#d9e0e8" }, horzLines: { color: "#d9e0e8" } },
    timeScale: { borderColor: "#b7c1cf" },
  });
  const candleSeries = chart.addCandlestickSeries({
    upColor: "#d94b63",
    downColor: "#1f9a72",
    borderVisible: false,
    wickUpColor: "#d94b63",
    wickDownColor: "#1f9a72",
  });
  candleSeries.setData(candles);
  chart.addLineSeries({ color: "#2b6cb0", lineWidth: 1, title: "MA20" }).setData(JSON.parse(raw.ma20));
  chart.addLineSeries({ color: "#122643", lineWidth: 2, lineStyle: 2, title: "五日預測" }).setData(JSON.parse(raw.prediction));
  window.stockChart = { chart, length: candles.length };
  setChartRange(90);
  const resize = () => chart.resize(container.clientWidth, measureChartHeight(container));
  if (window.ResizeObserver) new ResizeObserver(resize).observe(container);
  window.addEventListener("resize", resize);
}

document.addEventListener("click", (event) => {
  const watchlist = event.target.closest("[data-watchlist-toggle]");
  if (watchlist) {
    toggleWatchlist(watchlist);
    return;
  }

  const logout = event.target.closest("[data-account-logout]");
  if (logout && window.absorbAccount) {
    fetch("/auth/logout", {
      method: "POST",
      headers: { "X-CSRF-Token": window.absorbAccount.csrf_token },
    }).then((response) => {
      if (response.ok || response.redirected) window.location.assign("/");
    });
    return;
  }

  const preset = event.target.closest("[data-amount-preset]");
  if (preset) {
    const input = bySelector("[data-investment-amount]", preset.closest("[data-return-calculator]"));
    if (input) {
      input.value = preset.dataset.amountPreset;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  const filter = event.target.closest("[data-news-filter]");
  if (filter) {
    const panel = filter.closest(".news-panel");
    const entries = panel.querySelectorAll("[data-news-direction]");
    if (!entries.length) return;
    const direction = filter.dataset.newsFilter;
    let visible = 0;
    panel.querySelectorAll("[data-news-filter]").forEach((item) => {
      const active = item === filter;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", active);
    });
    entries.forEach((item) => {
      item.hidden = direction !== "all" && item.dataset.newsDirection !== direction;
      if (!item.hidden) visible += 1;
    });
    const empty = bySelector("[data-news-filter-empty]", panel);
    if (empty) empty.hidden = visible > 0;
  }

  const range = event.target.closest("[data-chart-range]");
  if (!range) return;
  document.querySelectorAll("[data-chart-range]").forEach((item) => {
    item.classList.toggle("active", item === range);
    item.setAttribute("aria-pressed", item === range);
  });
  setChartRange(Number(range.dataset.chartRange));
});

loadDashboard();
loadAccountState();
initStockChart();
initReturnCalculator();
initConversation();
