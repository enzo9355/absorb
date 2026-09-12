const bySelector = (selector, root = document) => root.querySelector(selector);

function migrateLegacyHashRoute() {
  if (!["/", "/dashboard"].includes(window.location.pathname)) return;
  const target = {
    "#market-pulse": "/market",
    "#daily-focus": "/",
    "#market-heatmap": "/industries",
    "#industry-observations": "/industries",
    "#stock-search": "/stocks",
    "#stock-events": "/stocks",
    "#etf-observations": "/stocks?tab=etf",
    "#learn": "/learn",
  }[window.location.hash];
  if (target) window.location.replace(target);
}

const UNAVAILABLE_TEXT = "尚未驗證";

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
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8000);
  try {
    const response = await fetch(page.dataset.dashboardEndpoint, {
      headers: { Accept: "application/json" },
      signal: controller.signal,
    });
    if (!response.ok) throw new Error("dashboard");
    renderDashboard(await response.json());
  } catch (_error) {
    const banner = bySelector("[data-dashboard-error]");
    if (banner) banner.hidden = false;
  } finally {
    window.clearTimeout(timeout);
  }
}

function displayNumber(value, digits = 2, suffix = "") {
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toFixed(digits)}${suffix}` : UNAVAILABLE_TEXT;
}

// ORDER 4（B-1）：缺值不是數值。前端渲染的路徑原本也把「資料不足」寫進
// <strong>，於是缺值拿到跟真實數值一樣的字級與重量。改為回傳不同的元素，
// 讓它落在內文字級與 muted 色 —— 與伺服器端渲染的 .value-unavailable 一致。
function valueCell(text) {
  return String(text) === UNAVAILABLE_TEXT
    ? ["span", "value-unavailable", UNAVAILABLE_TEXT]
    : ["strong", "", text];
}

function displaySigned(value, digits = 2, suffix = "%") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "資料不足";
  return `${number >= 0 ? "+" : ""}${number.toFixed(digits)}${suffix}`;
}

function observationTrend(value) {
  return {
    above_ma20_ma60: "站上 MA20 與 MA60",
    above_ma20: "站上 MA20",
    below_ma60: "低於 MA60",
    mixed: "均線交錯",
    insufficient: "資料不足",
  }[value] || "資料不足";
}

function renderDashboard(data) {
  if (!data || data.product_mode !== "observation") {
    throw new Error("observation dashboard required");
  }
  const marketData = data.market_observation || {};
  const hero = bySelector("[data-market-hero]");
  if (hero) {
    const riskState = {
      normal: "一般",
      cautious: "謹慎",
      elevated: "升高",
    }[marketData.risk_state] || "資料不足";
    replaceContent(hero, [
      element("p", "action-label action-insufficient", `市場風險狀態：${riskState}`),
      element("h1", "market-headline", `上漲 ${marketData.advancing_count ?? "—"} 檔、下跌 ${marketData.declining_count ?? "—"} 檔`),
      element("p", "hero-risk", `近 5 日市場中位報酬 ${displaySigned(marketData.return_5d_pct)}`),
      element("p", "muted small", `資料日 ${data.observation_as_of || "待更新"} · 覆蓋率 ${displayNumber((data.data_quality?.coverage || 0) * 100, 1, "%")}`),
    ]);
  }

  const market = bySelector("[data-market-summary]");
  if (market) {
    replaceContent(market, [
      card("article", "pulse-card", [["span", "", "單日中位報酬"], valueCell(displaySigned(marketData.return_1d_pct)), ["small", "muted", "全市場有效樣本"]]),
      card("article", "pulse-card", [["span", "", "站上 MA20"], valueCell(displayNumber(marketData.ma20_breadth_pct, 1, "%")), ["small", "muted", "市場均線廣度"]]),
      card("article", "pulse-card", [["span", "", "20 日已實現波動"], valueCell(displayNumber(marketData.realized_volatility_20d_pct, 1, "%")), ["small", "muted", `20 日新高 ${marketData.new_high_20d_count ?? "—"}／新低 ${marketData.new_low_20d_count ?? "—"}`]]),
    ]);
  }
  const status = bySelector(".status-dot");
  if (status) status.textContent = data.observation_as_of ? `資料日 ${data.observation_as_of}` : UNAVAILABLE_TEXT;

  const focus = bySelector("[data-daily-focus]");
  if (focus) {
    const items = Array.isArray(data.daily_focus) ? data.daily_focus : [];
    replaceContent(focus, items.length ? items.map((text, index) =>
      card("article", "focus-card", [["span", "", `焦點 ${index + 1}`], ["strong", "", text]])
    ) : [emptyState("今日焦點資料不足。")]);
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
      card("a", `heatmap-cell ${["hot", "cold", "steady"].includes(item.tone) ? item.tone : "steady"}`, [
        ["span", "", item.name],
        valueCell(displaySigned(item.metric_value_pct)),
        ["small", "", `${item.available_count ?? "—"} 檔 · 覆蓋 ${displayNumber((item.coverage || 0) * 100, 1, "%")}`],
      ], "/industries")
    ) : [emptyState("產業相對報酬資料不足。")]);
  }

  const industries = bySelector("[data-industry-observations]");
  if (industries) {
    const items = Array.isArray(data.industry_observations) ? data.industry_observations : [];
    replaceContent(industries, items.length ? items.map((item) =>
      card("article", "forecast-card", [
        ["span", "", item.name],
        ["strong", "", `相對大盤 ${displaySigned(item.relative_return_5d_pct)}`],
        ["small", "", `單日 ${displaySigned(item.return_1d_pct)} · 5 日 ${displaySigned(item.return_5d_pct)}`],
        ["small", "", `上漲家數 ${displayNumber(item.advancing_ratio_pct, 1, "%")} · 站上 MA20 ${displayNumber(item.ma20_breadth_pct, 1, "%")}`],
        ["small", "", `量比中位數 ${displayNumber(item.median_volume_ratio)} · 可用 ${item.available_count ?? "—"}/${item.component_count ?? "—"} 檔`],
      ])
    ) : [emptyState("產業觀察資料不足。")]);
  }

  const events = bySelector("[data-stock-events]");
  if (events) {
    const items = Array.isArray(data.stock_events) ? data.stock_events : [];
    const official = (Array.isArray(data.trading_status_observations) ? data.trading_status_observations : []).map((item) => ({
      ...item, observation: item.label, as_of: item.observation_as_of, severity: "high", official: true,
    }));
    const groups = [
      ["up", "異常上漲", items.filter((item) => item.event_type === "price_move" && Number(item.metric_value) > 0)],
      ["down", "異常下跌", items.filter((item) => item.event_type === "price_move" && Number(item.metric_value) <= 0)],
      ["volume", "量能異常", items.filter((item) => ["volume_surge", "volume_dry_up"].includes(item.event_type))],
      ["institution", "法人動向", items.filter((item) => item.event_type === "institution_flow")],
      ["technical", "技術面", items.filter((item) => ["rsi_overbought", "rsi_oversold", "new_high_20d", "new_low_20d"].includes(item.event_type))],
      ["official", "官方事件", official],
      ["data", "資料警示", items.filter((item) => item.event_type === "data_warning")],
    ];
    replaceContent(events, groups.map(([key, title, groupItems]) => {
      const section = element("section", `event-group event-${key}`);
      section.dataset.eventGroup = key;
      const heading = element("div", "event-group-heading");
      heading.append(element("h3", "", title), element("span", "", `${groupItems.length} 檔`));
      const list = element("div", "top-picks");
      replaceContent(list, groupItems.length ? groupItems.map((item) => {
        const severity = item.official ? "官方" : ({ high: "極端", medium: "顯著", low: "注意" }[item.severity] || "注意");
        const unit = ({ pct: "%", ratio: "倍", index: "", price: "", flag: "" })[item.unit] ?? item.unit ?? "";
        return card("a", `pick-card event-card severity-${item.severity || "low"}`, [
          ["span", "badge-stock", `${item.name} · ${item.symbol}`],
          ["strong", "", item.observation],
          ["p", Number(item.metric_value) > 0 ? "positive" : Number(item.metric_value) < 0 ? "negative" : "", `${item.metric_value ?? "—"}${unit}`],
          ["b", "event-severity", severity],
          ["small", "", `${item.official ? "驗證日" : "資料日"} ${item.as_of || data.observation_as_of}`],
        ], stockHref(item.symbol));
      }
      ) : [emptyState(`目前沒有${title}事件。`)]);
      section.append(heading, list);
      return section;
    }));
  }

  const etfs = bySelector("[data-etf-observations]");
  if (etfs) {
    const items = Array.isArray(data.etf_observations) ? data.etf_observations : [];
    replaceContent(etfs, items.length ? items.map((item) =>
      card("a", "pick-card", [
        ["span", "badge-etf", `${item.name} · ${item.symbol}`],
        ["strong", "", `收盤 ${displayNumber(item.price)}`],
        ["p", "", `單日 ${displaySigned(item.return_1d_pct)} · 5 日 ${displaySigned(item.return_5d_pct)}`],
        ["small", "", `${observationTrend(item.trend_observation)} · 量比 ${displayNumber(item.volume_ratio)}`],
      ], stockHref(item.symbol))
    ) : [emptyState("ETF 觀察資料不足。")]);
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
  if (document.body.dataset.accountSession !== "present") return;
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

// ORDER 4（A-8）：問題範例只填入輸入框，不自動送出。自動送出會替使用者
// 做決定，而且送出的問題不見得是他想問的 —— 範例的用途是示範「這裡能問
// 什麼」，不是代替他發問。對話一開始就把範例收起來，避免長期佔位。
function initAskExamples() {
  document.querySelectorAll("[data-conversation-endpoint]").forEach((panel) => {
    const examples = bySelector("[data-quick-ask-examples]", panel);
    const input = bySelector("input[name='question']", panel);
    if (!examples || !input) return;
    examples.querySelectorAll("[data-quick-ask-example]").forEach((button) => {
      button.addEventListener("click", () => {
        input.value = button.textContent.trim();
        input.focus();
      });
    });
  });
}

function initConversations() {
  document.querySelectorAll("[data-conversation-form]").forEach((form) => {
    const panel = form.closest("[data-conversation-endpoint]");
    const log = panel && bySelector("[data-conversation-log]", panel);
    if (!panel || !log) return;
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const input = bySelector("input[name='question']", form);
      const button = bySelector("button", form);
      const question = input.value.trim();
      if (!question) return;
      appendConversationMessage(log, "user", question);
      const examples = bySelector("[data-quick-ask-examples]", panel);
      if (examples) examples.hidden = true;
      input.value = "";
      button.disabled = true;
      const headers = { Accept: "application/json", "Content-Type": "application/json" };
      if (window.absorbAccount?.csrf_token) headers["X-CSRF-Token"] = window.absorbAccount.csrf_token;
      try {
        const payload = {
          question,
          market: panel.dataset.marketContext,
          page: panel.dataset.pageContext,
        };
        if (panel.dataset.symbolContext) {
          payload.symbol = panel.dataset.symbolContext;
        }
        const response = await fetch(panel.dataset.conversationEndpoint, {
          method: "POST",
          headers,
          body: JSON.stringify(payload),
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
  });
}

function initQuickAsk() {
  const dialog = bySelector("[data-quick-ask-dialog]");
  const dataQuickAskOpen = document.querySelectorAll("[data-quick-ask-open]");
  if (!dialog || !dataQuickAskOpen.length) return;
  const closeButton = bySelector("[data-quick-ask-close]", dialog);
  const input = bySelector("input[name='question']", dialog);
  let lastFocus = null;

  const open = (instant = false) => {
    if (!dialog.hidden) {
      input.focus({ preventScroll: true });
      return;
    }
    lastFocus = document.activeElement;
    dialog.hidden = false;
    dataQuickAskOpen.forEach((button) => button.setAttribute("aria-expanded", "true"));
    const reveal = () => {
      dialog.classList.add("is-open");
      input.focus({ preventScroll: true });
    };
    if (instant) reveal();
    else window.requestAnimationFrame(reveal);
  };

  const close = () => {
    dialog.classList.remove("is-open");
    dataQuickAskOpen.forEach((button) => button.setAttribute("aria-expanded", "false"));
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    window.setTimeout(() => {
      dialog.hidden = true;
      if (lastFocus instanceof HTMLElement) lastFocus.focus({ preventScroll: true });
    }, reduceMotion ? 0 : 180);
  };

  dataQuickAskOpen.forEach((button) => button.addEventListener("click", () => open(false)));
  closeButton.addEventListener("click", close);
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !dialog.hidden) close();
    if (event.key === "Tab" && !dialog.hidden) {
      const focusable = [...dialog.querySelectorAll(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      )];
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) {
        event.preventDefault();
      } else if (event.shiftKey && (document.activeElement === first || !dialog.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
      event.preventDefault();
      open(true);
    }
  });
}

function initSidebar() {
  const toggle = bySelector("[data-sidebar-toggle]");
  const sidebar = bySelector("#dashboard-sidebar");
  if (!toggle || !sidebar) return;
  const setCollapsed = (collapsed) => {
    document.body.classList.toggle("sidebar-collapsed", collapsed);
    toggle.setAttribute("aria-expanded", String(!collapsed));
    toggle.setAttribute("aria-label", collapsed ? "展開 Dashboard 導覽" : "收合 Dashboard 導覽");
  };
  toggle.addEventListener("click", () => setCollapsed(!document.body.classList.contains("sidebar-collapsed")));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.body.classList.contains("sidebar-collapsed")) setCollapsed(false);
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

function parseChartPoints(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || !value.trim()) return [];
  const parsed = JSON.parse(value);
  return Array.isArray(parsed) ? parsed : [];
}

function createPriceChart(container, raw, { predictionMarker = false, compact = false } = {}) {
  const candles = parseChartPoints(raw.candles);
  if (!candles.length) return null;
  const height = compact
    ? Math.max(250, Math.min(350, Math.round(container.clientWidth * 0.46)))
    : measureChartHeight(container);
  const chart = LightweightCharts.createChart(container, {
    width: container.clientWidth,
    height,
    layout: { background: { color: "transparent" }, textColor: "#536575" },
    grid: { vertLines: { color: "#cbd8de" }, horzLines: { color: "#cbd8de" } },
    rightPriceScale: { borderColor: "#aebfc8" },
    timeScale: { borderColor: "#aebfc8", rightOffset: predictionMarker ? 6 : 1 },
  });
  const directionStyle = getComputedStyle(document.body);
  const priceUp = directionStyle.getPropertyValue("--price-up").trim();
  const priceDown = directionStyle.getPropertyValue("--price-down").trim();
  const candleSeries = chart.addCandlestickSeries({
    upColor: priceUp,
    downColor: priceDown,
    borderVisible: false,
    wickUpColor: priceUp,
    wickDownColor: priceDown,
  });
  candleSeries.setData(candles);
  const ma20 = parseChartPoints(raw.ma20);
  if (ma20.length) {
    // ORDER 4（M-4）：均價線顏色改讀 token，圖例色塊與線條同源。
    const maColor = directionStyle.getPropertyValue("--chart-ma").trim();
    chart.addLineSeries({ color: maColor, lineWidth: 2, title: "MA20" }).setData(ma20);
  }
  const prediction = parseChartPoints(raw.prediction);
  if (predictionMarker && prediction.length > 1) {
    const infoColor = directionStyle.getPropertyValue("--absorb-info").trim();
    const predictionSeries = chart.addLineSeries({
      color: infoColor,
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      title: "AI 研究情境",
      lastValueVisible: true,
      priceLineVisible: false,
    });
    predictionSeries.setData(prediction);
    predictionSeries.setMarkers([{
      time: prediction[prediction.length - 1].time,
      position: "aboveBar",
      color: infoColor,
      shape: "circle",
      text: "AI 5日",
    }]);
  }
  const resize = () => {
    const nextHeight = compact
      ? Math.max(250, Math.min(350, Math.round(container.clientWidth * 0.46)))
      : measureChartHeight(container);
    chart.resize(container.clientWidth, nextHeight);
  };
  if (window.ResizeObserver) new ResizeObserver(resize).observe(container);
  window.addEventListener("resize", resize);
  return { chart, length: candles.length };
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
  window.stockChart = createPriceChart(container, raw, { predictionMarker: true });
  if (!window.stockChart) return;
  setChartRange(90);
}

// ORDER 5（§6.2）：一份報告三種讀法。
// 三個分頁在 HTML 裡預設全部可見，這裡才收起兩個 —— JS 失效時退化成
// 原本的線性長頁，不會把已發布的內容藏起來。
// 章節錨點跨分頁時（例如索引指向 #quantitative-research，而使用者正在
// 30 秒大局觀），先切到目標所在的分頁再捲過去，否則連結會靜靜失效。
function initReportTracks() {
  const tablist = bySelector("[data-report-tracks]");
  if (!tablist) return;
  const tabs = [...tablist.querySelectorAll("[data-report-track]")];
  const panels = new Map(
    [...document.querySelectorAll("[data-report-track-panel]")].map((panel) => [
      panel.dataset.reportTrackPanel,
      panel,
    ])
  );
  if (!tabs.length || !panels.size) return;

  const activate = (key, { focusTab = false } = {}) => {
    if (!panels.has(key)) return;
    tabs.forEach((tab) => {
      const active = tab.dataset.reportTrack === key;
      tab.setAttribute("aria-selected", String(active));
      tab.classList.toggle("is-active", active);
      tab.tabIndex = active ? 0 : -1;
      if (active && focusTab) tab.focus();
    });
    panels.forEach((panel, panelKey) => {
      panel.hidden = panelKey !== key;
    });
  };

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => activate(tab.dataset.reportTrack));
    tab.addEventListener("keydown", (event) => {
      const index = tabs.indexOf(tab);
      let next = null;
      if (event.key === "ArrowRight") next = tabs[(index + 1) % tabs.length];
      if (event.key === "ArrowLeft") next = tabs[(index - 1 + tabs.length) % tabs.length];
      if (event.key === "Home") next = tabs[0];
      if (event.key === "End") next = tabs[tabs.length - 1];
      if (!next) return;
      event.preventDefault();
      activate(next.dataset.reportTrack, { focusTab: true });
    });
  });

  const trackOf = (element) => {
    const panel = element && element.closest("[data-report-track-panel]");
    return panel ? panel.dataset.reportTrackPanel : null;
  };

  const revealHash = (hash) => {
    if (!hash || hash.length < 2) return false;
    let target = null;
    try {
      target = document.querySelector(hash);
    } catch (_error) {
      return false;
    }
    const key = trackOf(target);
    if (!key) return false;
    activate(key);
    target.scrollIntoView();
    return true;
  };

  document.addEventListener("click", (event) => {
    const link = event.target.closest('a[href^="#"]');
    if (!link) return;
    const hash = link.getAttribute("href");
    if (hash === "#" || !revealHash(hash)) return;
    event.preventDefault();
    if (window.history.replaceState) window.history.replaceState(null, "", hash);
  });
  window.addEventListener("hashchange", () => revealHash(window.location.hash));

  activate(tabs[0].dataset.reportTrack);
  revealHash(window.location.hash);
}

// ORDER 5（§6.2）：異常個股資料表。純前端、零相依。
// 搜尋與篩選只改 row.hidden，不重建 DOM —— 重建會丟掉使用者的捲動位置，
// 而且在幾百列時比切換 hidden 慢得多。排序是穩定排序（同鍵維持原順序），
// 否則反覆點同一個欄位時列的相對位置會亂跳。
function initAnomalyTable() {
  const table = bySelector("[data-anomaly-table]");
  if (!table) return;
  const body = table.tBodies[0];
  const rows = [...body.rows];
  const query = bySelector("[data-anomaly-query]");
  const filter = bySelector("[data-anomaly-filter]");
  const count = bySelector("[data-anomaly-count]");
  const empty = bySelector("[data-anomaly-empty]");
  const copy = bySelector("[data-anomaly-copy]");

  const cellText = (row, index) => (row.cells[index]?.textContent || "").trim();
  const keyOf = {
    name: (row) => cellText(row, 0),
    symbol: (row) => cellText(row, 1),
    type: (row) => cellText(row, 2),
    // 缺值回傳 null，不是 0 也不是 -Infinity。Number("") 是 0，
    // 直接轉數字會讓「尚未驗證」排到 0 的位置，等於把缺值當成 0（F-7）。
    value: (row) => {
      const raw = row.dataset.value;
      if (raw === undefined || raw.trim() === "") return null;
      const parsed = Number(raw);
      return Number.isFinite(parsed) ? parsed : null;
    },
    severity: (row) => Number(row.dataset.severityRank || 0),
    as_of: (row) => cellText(row, 6),
  };

  const apply = () => {
    const needle = (query?.value || "").trim().toLowerCase();
    const type = filter?.value || "";
    let visible = 0;
    rows.forEach((row) => {
      const matchesType = !type || row.dataset.type === type;
      const matchesText =
        !needle || (row.textContent || "").toLowerCase().includes(needle);
      const show = matchesType && matchesText;
      row.hidden = !show;
      if (show) visible += 1;
    });
    if (count) count.textContent = `${visible} 筆`;
    if (empty) empty.hidden = visible !== 0;
  };

  let sortKey = null;
  let ascending = true;
  table.querySelectorAll("[data-anomaly-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.anomalySort;
      ascending = key === sortKey ? !ascending : true;
      sortKey = key;
      const get = keyOf[key];
      const decorated = rows.map((row, index) => ({ row, index }));
      decorated.sort((a, b) => {
        const left = get(a.row);
        const right = get(b.row);
        // 缺值永遠墊底，不隨升冪／降冪翻面 —— 缺值不是「最小」，是「沒有」，
        // 把它排進數線上的某個位置就等於宣稱它有值。
        if (left === null || right === null) {
          if (left === right) return a.index - b.index;
          return left === null ? 1 : -1;
        }
        let result;
        if (typeof left === "number" && typeof right === "number") {
          result = left - right;
        } else {
          result = String(left).localeCompare(String(right), "zh-Hant");
        }
        if (result === 0) return a.index - b.index; // 穩定排序
        return ascending ? result : -result;
      });
      decorated.forEach(({ row }) => body.append(row));
      table.querySelectorAll("[data-anomaly-sort]").forEach((other) => {
        const active = other === button;
        other.closest("th").setAttribute(
          "aria-sort",
          active ? (ascending ? "ascending" : "descending") : "none"
        );
        other.classList.toggle("is-sorted", active);
      });
    });
  });

  query?.addEventListener("input", apply);
  filter?.addEventListener("change", apply);

  copy?.addEventListener("click", async () => {
    const header = [...table.tHead.rows[0].cells].map((cell) =>
      cell.textContent.trim()
    );
    const lines = [header.join("\t")];
    rows.forEach((row) => {
      if (row.hidden) return;
      lines.push([...row.cells].map((cell) => cell.textContent.trim()).join("\t"));
    });
    const text = lines.join("\n");
    try {
      await navigator.clipboard.writeText(text);
      copy.textContent = `已複製 ${lines.length - 1} 筆`;
    } catch (_error) {
      // 剪貼簿被拒（權限、非安全來源）時不能假裝成功
      copy.textContent = "複製失敗，請手動選取表格";
    }
    window.setTimeout(() => {
      copy.textContent = "複製為 TSV";
    }, 2400);
  });

  apply();
}

// ORDER 5（A-7）：章節索引的「當前章節」標示。
// 章節索引原本沒有任何位置回饋 —— 在一份十章、超過 700 行的報告裡捲動，
// 讀者無從判斷自己在哪一章。用 IntersectionObserver 而非 scroll 事件，
// 避免每次捲動都做版面量測。手機下索引預設收合，收合時把當前章節名稱
// 顯示在 summary 上，收起來也看得到位置。
function initReportChapterNav() {
  const wrap = bySelector("[data-chapter-nav]");
  if (!wrap) return;
  const links = [...wrap.querySelectorAll("nav a")];
  if (!links.length) return;
  const current = bySelector("[data-chapter-current]", wrap);
  const sections = links
    .map((link) => ({ link, section: document.querySelector(link.getAttribute("href")) }))
    .filter((entry) => entry.section);
  if (!sections.length) return;

  const mark = (activeSection) => {
    sections.forEach(({ link, section }) => {
      const active = section === activeSection;
      link.classList.toggle("is-current", active);
      if (active) {
        link.setAttribute("aria-current", "true");
        if (current) current.textContent = link.textContent.trim();
      } else {
        link.removeAttribute("aria-current");
      }
    });
  };

  const visible = new Set();
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) visible.add(entry.target);
        else visible.delete(entry.target);
      });
      const first = sections.find(({ section }) => visible.has(section));
      if (first) mark(first.section);
    },
    { rootMargin: "-20% 0px -70% 0px", threshold: 0 }
  );
  sections.forEach(({ section }) => observer.observe(section));
  mark(sections[0].section);

  // 手機預設收合：索引本身佔掉第一屏的話反而擋住內容
  const narrow = window.matchMedia("(max-width: 760px)");
  const applyWidth = () => { wrap.open = !narrow.matches; };
  applyWidth();
  narrow.addEventListener("change", applyWidth);
  wrap.querySelectorAll("nav a").forEach((link) => {
    link.addEventListener("click", () => { if (narrow.matches) wrap.open = false; });
  });
}

function initMarketIndexChart() {
  const container = bySelector("#market-index-chart");
  const source = bySelector("#market-index-chart-data");
  if (!container || !source || !window.LightweightCharts) return;
  const marketChart = createPriceChart(container, JSON.parse(source.textContent), { compact: true, predictionMarker: true });
  if (marketChart) marketChart.chart.timeScale().fitContent();
}

function initUsIndexChart() {
  const container = bySelector("#us-index-chart");
  const source = bySelector("#us-index-chart-data");
  const tabs = document.querySelectorAll("[data-us-index-tab]");
  if (!source || !tabs.length) return;
  const items = JSON.parse(source.textContent);
  let activeChart = null;
  const select = (symbol) => {
    const item = items.find((value) => value.symbol === symbol);
    if (!item) return;
    tabs.forEach((tab) => {
      const active = tab.dataset.usIndexTab === symbol;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-us-index-panel]").forEach((panel) => {
      panel.hidden = panel.dataset.usIndexPanel !== symbol;
    });
    if (!container || !window.LightweightCharts) return;
    if (activeChart) activeChart.chart.remove();
    container.replaceChildren();
    activeChart = createPriceChart(container, {
      candles: item.candles,
      prediction: item.line,
    }, { compact: true, predictionMarker: true });
    if (activeChart) activeChart.chart.timeScale().fitContent();
  };
  tabs.forEach((tab) => tab.addEventListener("click", () => select(tab.dataset.usIndexTab)));
  select(tabs[0].dataset.usIndexTab);
}

document.addEventListener("click", (event) => {
  const reportRetry = event.target.closest("[data-report-retry]");
  if (reportRetry) {
    window.location.reload();
    return;
  }

  const reportFilter = event.target.closest("[data-report-filter]");
  if (reportFilter) {
    const controls = reportFilter.closest("[data-report-filters]");
    const selectedType = reportFilter.dataset.reportFilter;
    controls.querySelectorAll("[data-report-filter]").forEach((item) => {
      const active = item === reportFilter;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-report-type]").forEach((lane) => {
      lane.hidden = selectedType !== "all" && lane.dataset.reportType !== selectedType;
    });
    return;
  }

  // ORDER 5（A-5）：第一層是讀者，不是報告類型。
  // 三個門一直都在卡片上，切換只改「哪一個是主要按鈕」——
  // 不把同一份報告在清單裡列兩次，也不把另外兩個入口藏起來。
  const reportReader = event.target.closest("[data-report-reader]");
  if (reportReader) {
    const controls = reportReader.closest("[data-report-readers]");
    const reader = reportReader.dataset.reportReader;
    controls.querySelectorAll("[data-report-reader]").forEach((item) => {
      const active = item === reportReader;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-report-doors]").forEach((doors) => {
      const links = [...doors.querySelectorAll("[data-report-door]")];
      // 回退到 overview 這個固定的門，不是「目前排在最前面的那一個」——
      // 後者會隨上一次切換而漂移（盤前報告沒有異常資料表，
      // 選「查異常標的」時它會停在上一輪被提前的門上）。
      const primary =
        links.find((link) => link.dataset.reportDoor === reader) ||
        links.find((link) => link.dataset.reportDoor === "overview") ||
        links[0];
      links.forEach((link) => {
        const isPrimary = link === primary;
        link.classList.toggle("button-secondary", !isPrimary);
        link.classList.toggle("is-primary-door", isPrimary);
      });
      // 主要入口排到最前面，讀者不用在三顆一樣的按鈕裡找
      if (primary) doors.prepend(primary);
    });
    return;
  }

  // 時間軸：依交易日篩選。沒有報告的日期本來就不會出現在時間軸上，
  // 所以任何一個按鈕都至少有一筆結果，不會點出空畫面。
  const reportDay = event.target.closest("[data-report-day]");
  if (reportDay && reportDay.closest("[data-report-timeline]")) {
    const controls = reportDay.closest("[data-report-timeline]");
    const day = reportDay.dataset.reportDay;
    controls.querySelectorAll("[data-report-day]").forEach((item) => {
      const active = item === reportDay;
      item.classList.toggle("active", active);
      item.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll(".report-card[data-report-day]").forEach((card) => {
      card.hidden = day !== "all" && card.dataset.reportDay !== day;
    });
    return;
  }

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

migrateLegacyHashRoute();
loadDashboard();
loadAccountState();
initStockChart();
initMarketIndexChart();
initUsIndexChart();
initReturnCalculator();
initConversations();
initQuickAsk();
initAskExamples();
initReportTracks();
initReportChapterNav();
initAnomalyTable();
initSidebar();
