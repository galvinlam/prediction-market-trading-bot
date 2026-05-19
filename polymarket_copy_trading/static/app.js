const state = {
  overview: {},
  holdings: [],
  closedPositions: [],
  trades: [],
  performance: { wallets: [] },
  performanceHours: 24,
  wallets: [],
  defaultWalletProfile: null,
  settings: {},
  pnl: { pnl: {}, series: [] },
  activePage: "dashboard",
  activeRange: "day",
  activePositionTab: "open",
  activeHoldingIndex: null,
  holdingModalOpen: false,
  holdingSellConfirm: false,
  holdingSellBusy: false,
  holdingSellError: "",
  activeWalletAddress: null,
  walletModalMode: "edit",
  walletModalOpen: false,
  walletDeleteConfirm: false,
  walletModalBusy: false,
  walletModalError: "",
};

const pageMeta = {
  dashboard: ["Dashboard", "Paper copy-trading monitor"],
  trades: ["Trades", "Executed paper ledger"],
  performance: ["Performance", "Wallet PnL by market"],
  wallets: ["Wallets", "Managed copy sources"],
  settings: ["Settings", "Runtime risk controls"],
  research: ["Research", "Wallet discovery workspace"],
};

const MARKET_TYPES = ["crypto", "weather", "sports", "other"];
const WEATHER_PATTERNS = ["exact_or_binary", "range", "above_or_higher", "below_or_lower"];
const SETTINGS_GROUPS = [
  {
    title: "Mode",
    description: "Paper/live mode and source-sell mirroring.",
    keys: ["trading_mode", "mirror_source_sells"],
  },
  {
    title: "Capital & Entry Risk",
    description: "Global paper sizing and executable-price guardrails.",
    keys: [
      "starting_cash_usdc",
      "min_trade_usdc",
      "max_trade_usdc",
      "max_position_usdc",
      "slippage_pct",
      "settlement_slippage_pct",
      "max_entry_price_source_premium",
      "max_entry_price_source_multiple",
    ],
  },
  {
    title: "Markets & Pricing",
    description: "Top-level market universe and quote monitor cadence.",
    keys: [
      "enabled_market_types",
      "price_monitor_enabled",
      "price_monitor_poll_interval_seconds",
      "price_monitor_idle_poll_interval_seconds",
    ],
  },
];
const SETTINGS_KEYS = SETTINGS_GROUPS.flatMap((group) => group.keys);
const PERFORMANCE_WINDOWS = [1, 4, 8, 12, 24];

async function fetchJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} returned ${response.status}`);
  return response.json();
}

async function fetchJsonOr(path, fallback) {
  try {
    return await fetchJson(path);
  } catch (error) {
    console.warn(`Failed to load ${path}`, error);
    return fallback;
  }
}

async function sendJson(path, method, payload) {
  const response = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `${path} returned ${response.status}`);
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function money(value, digits = 2) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function shortAddress(value) {
  const text = String(value || "");
  return text.length > 14 ? `${text.slice(0, 8)}...${text.slice(-6)}` : text;
}

function walletLabel(item) {
  return item.source_wallet_name || shortAddress(item.source_wallet);
}

function marketWithSide(item) {
  const title = String(item.title || item.asset_id || "unknown market");
  const side = String(item.outcome || item.market_outcome || "").trim();
  if (!side) return title;
  return title.toLowerCase().endsWith(` - ${side.toLowerCase()}`) ? title : `${title} - ${side}`;
}

function timeParts(value) {
  if (!value) return "--";
  const text = String(value).trim().replace("T", " ").replace(/\.\d+Z?$/, "");
  const match = text.match(/^(\d{4})-(\d{2})-(\d{2})\s+(\d{2}):(\d{2})(?::\d{2})?(?:\s+(PDT|PD|PST|UTC))?$/);
  if (!match) return null;
  return {
    year: match[1],
    month: match[2],
    day: match[3],
    hour: match[4],
    minute: match[5],
    zone: match[6] === "PD" ? "PDT" : match[6] || "PDT",
  };
}

function formatTradeTime(value, options = {}) {
  if (!value) return "--";
  const parts = timeParts(value);
  if (!parts) return String(value).replace("T", " ").replace(/\.\d+Z?$/, "");
  if (options.compact) return `${parts.month}/${parts.day} ${parts.hour}:${parts.minute} ${parts.zone}`;
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ${parts.zone}`;
}

function marketCloseLabel(item, options = {}) {
  if (item.market_close_time) return formatTradeTime(item.market_close_time, options);
  if (String(item.market_type || "").toLowerCase() === "sports") return "End-of-game";
  return "N/A";
}

function marketTimeName(item) {
  return isEventStartTime(item) ? "Event start" : "Market close";
}

function marketTimePhrase(item, options = {}) {
  const value = marketCloseLabel(item, options);
  if (value === "N/A" || value === "End-of-game") return value;
  return `${marketTimeName(item)} ${value}`;
}

function isEventStartTime(item) {
  const kind = String(item.market_close_time_kind || "").toLowerCase();
  if (kind === "event_start") return true;
  if (kind === "actual_close") return false;
  return String(item.market_type || "").toLowerCase() === "sports"
    && item.market_close_time
    && !Boolean(item.is_closed)
    && item.resolution_price == null;
}

function closeReasonLabel(item) {
  const reason = String(item.close_reason || "").trim();
  if (!reason) return "";
  const labels = {
    source_sell: "Mirrored source sell",
    manual_sell: "Manual dashboard sell",
    market_settlement: "Market settlement",
    stop_loss: "Bot stop loss",
    trailing_stop: "Bot trailing stop",
    price_at_one: "Bot price-at-one close",
    price_near_zero: "Bot near-zero close",
    filter_copy_in_event_stop_loss: "Filter-copy in-event stop loss",
    sports_dead_cut: "Bot sports dead-cut",
    sports_event_lost: "Sports event lost",
    sports_pre_end_lock_profit: "Bot pre-end profit lock",
    winner_recover_stake: "Bot winner stake recovery",
    winner_scale: "Bot winner scale-out",
    winner_high_price: "Bot winner high-price scale-out",
    winner_trailing_stop: "Bot winner trailing stop",
    sports_winner_recover_half_stake: "Bot sports winner half-stake recovery",
    sports_winner_recover_stake: "Bot sports winner stake recovery",
    sports_winner_high_price: "Bot sports winner high-price scale-out",
  };
  return labels[reason] || reason.replaceAll("_", " ");
}

function sourceTradeSideLabel(item) {
  const sourceSide = String(item.source_side || "").toLowerCase();
  if (sourceSide === "sell") return "Source sell";
  if (sourceSide === "buy") return "Source buy";
  return "Source";
}

function paperTradeSideLabel(item) {
  const paperSide = String(item.paper_side || "").toLowerCase();
  if (paperSide === "sell") return "Paper sell";
  if (paperSide === "buy") return "Paper buy";
  return "Paper";
}

function tradeEntryBasis(item) {
  const entryPrice = item.entry_price == null ? null : Number(item.entry_price || 0);
  const entryNotional = item.entry_notional_usdc == null ? null : Number(item.entry_notional_usdc || 0);
  if (entryPrice != null && entryNotional != null) return { price: entryPrice, notional: entryNotional };

  const wallet = String(item.source_wallet || "").toLowerCase();
  const asset = String(item.asset_id || "");
  const buys = state.trades.filter((trade) => {
    const side = String(trade.paper_side || "").toLowerCase();
    return side === "buy"
      && String(trade.asset_id || "") === asset
      && String(trade.source_wallet || "").toLowerCase() === wallet;
  });
  const quantity = buys.reduce((total, trade) => total + Number(trade.paper_quantity || 0), 0);
  const notional = buys.reduce((total, trade) => total + Number(trade.paper_notional_usdc || 0), 0);
  if (!quantity || !notional) return { price: null, notional: null };
  const soldQuantity = Number(item.paper_quantity || 0);
  const average = notional / quantity;
  return { price: average, notional: soldQuantity ? average * soldQuantity : notional };
}

function positionBuyTime(item, options = {}) {
  if (item.buy_time) return formatTradeTime(item.buy_time, options);
  const wallet = String(item.source_wallet || "").toLowerCase();
  const asset = String(item.asset_id || "");
  const matches = state.trades.filter((trade) => {
    const side = String(trade.paper_side || trade.source_side || "").toLowerCase();
    return side === "buy"
      && String(trade.asset_id || "") === asset
      && String(trade.source_wallet || "").toLowerCase() === wallet;
  });
  const earliest = matches[matches.length - 1];
  return earliest ? formatTradeTime(earliest.paper_time || earliest.source_time, options) : "N/A";
}

function exposureUsdc() {
  return state.holdings.reduce((total, item) => {
    return total + Number(item.quantity || 0) * Number(item.avg_entry_price || 0);
  }, 0);
}

async function refresh() {
  const [overview, holdings, closedPositions, trades, performance, wallets, defaultProfile, settings, pnl] = await Promise.all([
    fetchJsonOr("/api/overview", state.overview),
    fetchJsonOr("/api/holdings", { holdings: state.holdings }),
    fetchJsonOr("/api/closed-positions", { closed_positions: state.closedPositions }),
    fetchJsonOr("/api/trades?limit=250", { trades: state.trades }),
    fetchJsonOr(`/api/performance?hours=${state.performanceHours}`, state.performance),
    fetchJsonOr("/api/wallets", { wallets: state.wallets }),
    fetchJsonOr("/api/wallet-profile/default", { default_wallet_profile_json: state.defaultWalletProfile }),
    fetchJsonOr("/api/settings", { settings: state.settings }),
    fetchJsonOr("/api/pnl", state.pnl),
  ]);
  state.overview = overview;
  state.holdings = holdings.holdings || [];
  state.closedPositions = closedPositions.closed_positions || [];
  state.trades = trades.trades || [];
  state.performance = performance || { wallets: [] };
  state.wallets = wallets.wallets || [];
  state.defaultWalletProfile = plainObject(defaultProfile.default_wallet_profile_json)
    ? defaultProfile.default_wallet_profile_json
    : state.defaultWalletProfile;
  state.settings = settings.settings || {};
  state.pnl = pnl || { pnl: {}, series: [] };
  render();
}

function render() {
  renderTopbar();
  renderDashboard();
  renderTrades();
  renderPerformance();
  renderWallets();
  renderSettings();
  renderHoldingModal();
  renderWalletModal();
}

function renderTopbar() {
  const [title, subtitle] = pageMeta[state.activePage] || pageMeta.dashboard;
  document.querySelector("#page-title").textContent = title;
  document.querySelector("#page-subtitle").textContent = subtitle;
  document.querySelector("#watcher-pill").textContent = state.overview.paper_watcher_status || "stopped";
  document.querySelector("#paper-mode").classList.toggle("active", Boolean(state.settings.paper_trading));
  document.querySelector("#real-mode").classList.toggle("active", Boolean(state.settings.live_trading));
}

function renderDashboard() {
  const pnl = state.pnl.pnl || {};
  const portfolio = Number(state.pnl.portfolio_value_usdc || 0);
  const cash = Number(state.pnl.cash_usdc || 0);
  const rangeValue = Number(pnl[state.activeRange] || 0);
  document.querySelector("#portfolio-value").textContent = `$${money(portfolio)}`;
  document.querySelector("#portfolio-delta").textContent = `${signedMoney(rangeValue)} ${rangeLabel(state.activeRange)}`;
  document.querySelector("#portfolio-delta").classList.toggle("bad-text", rangeValue < 0);
  document.querySelector("#cash-available").textContent = `Cash available $${money(cash)}`;
  const chartSeries = state.pnl.series_by_range?.[state.activeRange] || state.pnl.series || [];
  renderChart(chartSeries);
  document.querySelector("#pnl-cards").innerHTML = [
    ["1D", pnl.day || 0, "day"],
    ["1W", pnl.week || 0, "week"],
    ["1M", pnl.month || 0, "month"],
    ["All", pnl.lifetime || 0, "lifetime"],
  ].map(([label, value, range]) => `
    <article class="stat-card pnl-card ${range === state.activeRange ? "active" : ""}" data-range-card="${range}">
      <span class="stat-label">${escapeHtml(label)}</span>
      <strong class="stat-value ${Number(value) < 0 ? "bad-text" : ""}">${signedMoney(value)}</strong>
    </article>
  `).join("");

  renderPositionTabs();
}

function renderPosition(item, holdingIndex) {
  const quantity = Number(item.quantity || 0);
  const avg = Number(item.avg_entry_price || 0);
  const paperNotional = Number(item.cost_basis_usdc || quantity * avg);
  const current = item.current_price == null ? null : Number(item.current_price || 0);
  const currentValue = Number(item.current_value_usdc || quantity * (current ?? avg));
  const pnl = Number(item.unrealized_pnl_usdc || 0);
  const pnlPct = Number(item.unrealized_pnl_pct || 0);
  const title = marketWithSide(item);
  return `
    <article class="position-card card-link holding-card" role="button" tabindex="0" data-holding-index="${holdingIndex}" aria-haspopup="dialog">
      <div class="row-top">
        <div>
          <div class="row-title">${escapeHtml(title)}</div>
          <div class="row-meta compact-line">${escapeHtml(walletLabel(item))}</div>
        </div>
        <span class="badge good">open</span>
      </div>
      <div class="row-grid compact-metrics">
        <span>Paper $${money(paperNotional)}</span>
        <span>Qty ${quantity.toFixed(4)}</span>
        <span>Entry ${avg.toFixed(4)}</span>
        <span>Now ${formatPrice(current)}</span>
        <span>Value $${money(currentValue)}</span>
        <span class="${pnl < 0 ? "bad-text" : "good-text"}">${signedMoney(pnl)} (${signedPct(pnlPct)})</span>
      </div>
      <div class="row-meta compact-line">
        Buy ${escapeHtml(positionBuyTime(item, { compact: true }))} · ${escapeHtml(marketTimePhrase(item, { compact: true }))}
      </div>
    </article>
  `;
}

function renderPositionTabs() {
  document.querySelectorAll("[data-position-tab]").forEach((control) => {
    control.classList.toggle("active", control.dataset.positionTab === state.activePositionTab);
  });
  const books = positionBooksForTab(state.activePositionTab);
  renderList(
    "#positions-list",
    books,
    renderPositionBook,
    state.activePositionTab === "closed" ? "No closed event books yet." : "No open event books."
  );
  bindHoldingCards();
}

function positionBooksForTab(tab) {
  return buildPositionBooks().filter((book) => book.status === (tab === "closed" ? "closed" : "open"));
}

function buildPositionBooks() {
  const groups = new Map();
  state.holdings.forEach((item, holdingIndex) => {
    addPositionBookLeg(groups, item, "open", holdingIndex);
  });
  state.closedPositions.forEach((item) => {
    addPositionBookLeg(groups, item, "closed", null);
  });

  return [...groups.values()].map(finalizePositionBook).sort((left, right) => {
    if (left.status !== right.status) return left.status === "open" ? -1 : 1;
    return sortTimeValue(right.updatedAt) - sortTimeValue(left.updatedAt);
  });
}

function addPositionBookLeg(groups, item, status, holdingIndex) {
  const key = positionBookKey(item);
  if (!groups.has(key)) {
    groups.set(key, {
      key,
      source_wallet: item.source_wallet || "",
      source_wallet_name: item.source_wallet_name || "",
      eventSlug: item.event_slug || "",
      eventTitle: item.event_title || "",
      fallbackTitle: marketWithSide(item),
      marketTimeItem: null,
      openLegs: 0,
      closedLegs: 0,
      costBasisUsdc: 0,
      currentValueUsdc: 0,
      closedNotionalUsdc: 0,
      realizedPnlUsdc: 0,
      unrealizedPnlUsdc: 0,
      buyTime: null,
      closeTime: null,
      updatedAt: null,
      legs: [],
    });
  }
  const book = groups.get(key);
  const metrics = positionBookLegMetrics(item, status);
  const leg = { item, status, holdingIndex, metrics };
  book.legs.push(leg);
  book.openLegs += status === "open" ? 1 : 0;
  book.closedLegs += status === "closed" ? 1 : 0;
  book.costBasisUsdc += metrics.costBasisUsdc;
  if (status === "open") {
    book.currentValueUsdc += metrics.currentValueUsdc;
    book.unrealizedPnlUsdc += metrics.pnlUsdc;
  } else {
    book.closedNotionalUsdc += metrics.closedNotionalUsdc;
    book.realizedPnlUsdc += metrics.pnlUsdc;
  }
  if (!book.eventTitle && item.event_title) book.eventTitle = item.event_title;
  if (!book.eventSlug && item.event_slug) book.eventSlug = item.event_slug;
  if (!book.marketTimeItem && item.market_close_time) book.marketTimeItem = item;
  book.buyTime = earlierTime(book.buyTime, metrics.buyTime);
  book.closeTime = laterTime(book.closeTime, metrics.closeTime);
  book.updatedAt = laterTime(book.updatedAt, metrics.updatedAt || metrics.closeTime || metrics.buyTime);
}

function finalizePositionBook(book) {
  book.status = book.openLegs > 0 ? "open" : "closed";
  book.totalLegs = book.openLegs + book.closedLegs;
  book.pnlUsdc = book.realizedPnlUsdc + book.unrealizedPnlUsdc;
  book.pnlPct = book.costBasisUsdc ? (book.pnlUsdc / book.costBasisUsdc) * 100 : 0;
  book.legs.sort((left, right) => {
    if (left.status !== right.status) return left.status === "open" ? -1 : 1;
    return right.metrics.costBasisUsdc - left.metrics.costBasisUsdc;
  });
  return book;
}

function positionBookKey(item) {
  const wallet = String(item.source_wallet || "").toLowerCase();
  const eventSlug = String(item.event_slug || "").trim().toLowerCase();
  if (eventSlug) return `event:${wallet}:${eventSlug}`;
  const eventTitle = String(item.event_title || "").trim().toLowerCase();
  if (eventTitle) return `event-title:${wallet}:${eventTitle}`;
  const market = String(item.market_slug || item.market_id || item.condition_id || item.title || item.asset_id || "").trim().toLowerCase();
  return `market:${wallet}:${market}`;
}

function positionBookLegMetrics(item, status) {
  if (status === "open") {
    const quantity = Number(item.quantity || 0);
    const entry = Number(item.avg_entry_price || 0);
    const current = item.current_price == null ? null : Number(item.current_price || 0);
    const costBasisUsdc = Number(item.cost_basis_usdc || quantity * entry);
    const currentValueUsdc = Number(item.current_value_usdc || quantity * (current ?? entry));
    const pnlUsdc = Number(item.unrealized_pnl_usdc || currentValueUsdc - costBasisUsdc);
    return {
      quantity,
      entry,
      current,
      costBasisUsdc,
      currentValueUsdc,
      closedNotionalUsdc: 0,
      pnlUsdc,
      pnlPct: Number(item.unrealized_pnl_pct || (costBasisUsdc ? (pnlUsdc / costBasisUsdc) * 100 : 0)),
      buyTime: item.buy_time,
      closeTime: null,
      updatedAt: item.updated_at || item.last_price_at || item.buy_time,
    };
  }
  const quantity = item.closed_quantity == null ? 0 : Number(item.closed_quantity || 0);
  const entry = item.entry_price == null ? null : Number(item.entry_price || 0);
  const exit = item.exit_price == null ? null : Number(item.exit_price || 0);
  const costBasisUsdc = item.entry_notional_usdc == null
    ? (entry == null ? 0 : entry * quantity)
    : Number(item.entry_notional_usdc || 0);
  const closedNotionalUsdc = Number(item.closed_notional_usdc || 0);
  const pnlUsdc = Number(item.realized_pnl_usdc || closedNotionalUsdc - costBasisUsdc);
  return {
    quantity,
    entry,
    exit,
    current: item.current_price == null ? null : Number(item.current_price || 0),
    costBasisUsdc,
    currentValueUsdc: 0,
    closedNotionalUsdc,
    pnlUsdc,
    pnlPct: costBasisUsdc ? (pnlUsdc / costBasisUsdc) * 100 : 0,
    buyTime: item.buy_time,
    closeTime: item.close_time || item.updated_at,
    updatedAt: item.updated_at || item.close_time || item.buy_time,
  };
}

function renderPositionBook(book) {
  const isOpen = book.status === "open";
  const title = eventBookTitle(book);
  const wallet = walletLabel(book);
  const eventMeta = [wallet, book.eventSlug ? book.eventSlug : ""].filter(Boolean).join(" - ");
  const timingBits = [];
  if (book.buyTime) timingBits.push(`First buy ${formatTradeTime(book.buyTime, { compact: true })}`);
  if (isOpen && book.marketTimeItem) timingBits.push(marketTimePhrase(book.marketTimeItem, { compact: true }));
  if (!isOpen && book.closeTime) timingBits.push(`Closed ${formatTradeTime(book.closeTime, { compact: true })}`);
  const valueLabel = isOpen
    ? `Open value $${money(book.currentValueUsdc)}`
    : `Closed $${money(book.closedNotionalUsdc)}`;
  return `
    <article class="position-card event-book-card">
      <div class="row-top">
        <div>
          <div class="row-title">${escapeHtml(title)}</div>
          <div class="row-meta compact-line">${escapeHtml(eventMeta || wallet)}</div>
        </div>
        <span class="badge ${isOpen ? "good" : "disabled"}">${isOpen ? "open" : "closed"}</span>
      </div>
      <div class="row-grid compact-metrics">
        <span>Paper $${money(book.costBasisUsdc)}</span>
        <span>${valueLabel}</span>
        <span>Realized ${signedMoney(book.realizedPnlUsdc)}</span>
        <span>Unrealized ${signedMoney(book.unrealizedPnlUsdc)}</span>
        <span>${book.openLegs} open / ${book.closedLegs} closed</span>
        <span class="${book.pnlUsdc < 0 ? "bad-text" : "good-text"}">Total ${signedMoney(book.pnlUsdc)} (${signedPct(book.pnlPct)})</span>
      </div>
      ${timingBits.length ? `<div class="row-meta compact-line">${timingBits.map(escapeHtml).join(" - ")}</div>` : ""}
      <div class="event-book-leg-list">
        ${book.legs.map(renderPositionBookLeg).join("")}
      </div>
    </article>
  `;
}

function eventBookTitle(book) {
  if (book.eventTitle) return book.eventTitle;
  if (book.totalLegs === 1 && book.legs[0]) return marketWithSide(book.legs[0].item);
  if (book.eventSlug) return book.eventSlug;
  return book.fallbackTitle || "Event book";
}

function renderPositionBookLeg(leg) {
  const item = leg.item;
  const metrics = leg.metrics;
  const isOpen = leg.status === "open";
  const title = marketWithSide(item);
  const closeReason = closeReasonLabel(item);
  const body = isOpen
    ? `
      <div class="event-book-leg-grid">
        <span>Paper $${money(metrics.costBasisUsdc)}</span>
        <span>Qty ${metrics.quantity.toFixed(4)}</span>
        <span>Entry ${formatPrice(metrics.entry)}</span>
        <span>Now ${formatPrice(metrics.current)}</span>
        <span>Value $${money(metrics.currentValueUsdc)}</span>
        <span class="${metrics.pnlUsdc < 0 ? "bad-text" : "good-text"}">${signedMoney(metrics.pnlUsdc)} (${signedPct(metrics.pnlPct)})</span>
      </div>
      <div class="row-meta compact-line">Buy ${escapeHtml(positionBuyTime(item, { compact: true }))}</div>
    `
    : `
      <div class="event-book-leg-grid">
        <span>Paper $${money(metrics.costBasisUsdc)}</span>
        <span>Qty ${metrics.quantity.toFixed(4)}</span>
        <span>Entry ${formatPrice(metrics.entry)}</span>
        <span>Exit ${formatPrice(metrics.exit)}</span>
        <span>Closed $${money(metrics.closedNotionalUsdc)}</span>
        <span class="${metrics.pnlUsdc < 0 ? "bad-text" : "good-text"}">${signedMoney(metrics.pnlUsdc)} (${signedPct(metrics.pnlPct)})</span>
      </div>
      <div class="row-meta compact-line">
        Buy ${escapeHtml(formatTradeTime(metrics.buyTime, { compact: true }))}${metrics.closeTime ? ` - Sell ${escapeHtml(formatTradeTime(metrics.closeTime, { compact: true }))}` : ""}${closeReason ? ` - Exit reason ${escapeHtml(closeReason)}` : ""}
      </div>
    `;
  const header = `
    <div class="event-book-leg-header">
      <div class="event-book-leg-title">${escapeHtml(title)}</div>
      <span class="badge ${isOpen ? "good" : "disabled"}">${isOpen ? "open" : "closed"}</span>
    </div>
    ${body}
  `;
  if (isOpen && leg.holdingIndex != null) {
    return `<div class="event-book-leg event-book-leg-open" role="button" tabindex="0" data-holding-index="${Number(leg.holdingIndex)}" aria-haspopup="dialog">${header}</div>`;
  }
  if (item.market_url) {
    return `<a class="event-book-leg card-link" href="${escapeHtml(item.market_url)}" target="_blank" rel="noopener noreferrer">${header}</a>`;
  }
  return `<div class="event-book-leg">${header}</div>`;
}

function earlierTime(left, right) {
  if (!left) return right || null;
  if (!right) return left;
  return sortTimeValue(right) < sortTimeValue(left) ? right : left;
}

function laterTime(left, right) {
  if (!left) return right || null;
  if (!right) return left;
  return sortTimeValue(right) > sortTimeValue(left) ? right : left;
}

function sortTimeValue(value) {
  if (!value) return 0;
  const parts = timeParts(value);
  if (parts) return Number(`${parts.year}${parts.month}${parts.day}${parts.hour}${parts.minute}`);
  const parsed = Date.parse(String(value).replace(" PDT", " -0700").replace(" PD", " -0700").replace(" PST", " -0800"));
  return Number.isNaN(parsed) ? 0 : parsed;
}

function renderClosedPosition(item) {
  const title = marketWithSide(item);
  const current = item.current_price == null ? null : Number(item.current_price || 0);
  const exit = item.exit_price == null ? null : Number(item.exit_price || 0);
  const entry = item.entry_price == null ? null : Number(item.entry_price || 0);
  const pnl = item.realized_pnl_usdc == null ? null : Number(item.realized_pnl_usdc || 0);
  const quantity = item.closed_quantity == null ? null : Number(item.closed_quantity || 0);
  const paperNotional = item.entry_notional_usdc == null
    ? (entry == null || quantity == null ? null : entry * quantity)
    : Number(item.entry_notional_usdc || 0);
  const link = item.market_url || "";
  const tag = link ? "a" : "article";
  const href = link ? ` href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer"` : "";
  const closeReasonCode = String(item.close_reason || "");
  const closeReason = closeReasonLabel(item);
  const timingLine = closeReasonCode === "market_settlement"
    ? `Buy ${escapeHtml(formatTradeTime(item.buy_time, { compact: true }))} · Settled ${escapeHtml(marketCloseLabel(item, { compact: true }))}`
    : `Buy ${escapeHtml(formatTradeTime(item.buy_time, { compact: true }))} · Sell ${escapeHtml(formatTradeTime(item.close_time || item.updated_at, { compact: true }))} · ${escapeHtml(marketTimePhrase(item, { compact: true }))}`;
  return `
    <${tag} class="position-card closed-position card-link"${href}>
      <div class="row-top">
        <div>
          <div class="row-title">${escapeHtml(title)}</div>
          <div class="row-meta compact-line">${escapeHtml(walletLabel(item))}</div>
        </div>
        <span class="badge disabled">closed</span>
      </div>
      <div class="row-grid compact-metrics">
        <span>Paper ${paperNotional == null ? "--" : `$${money(paperNotional)}`}</span>
        <span>Qty ${quantity == null ? "--" : quantity.toFixed(4)}</span>
        <span>Entry ${formatPrice(entry)}</span>
        <span>Exit ${formatPrice(exit)}</span>
        <span>Closed $${money(item.closed_notional_usdc || 0)}</span>
        <span class="${Number(pnl || 0) < 0 ? "bad-text" : "good-text"}">${pnl == null ? "--" : signedMoney(pnl)}</span>
      </div>
      <div class="row-meta compact-line">
        ${timingLine}${closeReason ? ` · Exit reason ${escapeHtml(closeReason)}` : ""}
      </div>
    </${tag}>
  `;
}

function renderTrades() {
  renderList("#trades-list", state.trades, renderTradeRow, "No copied trades yet.");
}

function renderPerformance() {
  const hours = performanceWindowHours();
  const wallets = state.performance.wallets || [];
  const label = `Last ${hours} ${hours === 1 ? "hour" : "hours"}`;
  const labelElement = document.querySelector("#performance-window-label");
  if (labelElement) labelElement.textContent = label;
  document.querySelectorAll("[data-performance-hours]").forEach((control) => {
    control.classList.toggle("active", Number(control.dataset.performanceHours) === hours);
  });
  renderList("#performance-list", wallets, renderPerformanceWallet, `No wallet performance in the last ${hours} ${hours === 1 ? "hour" : "hours"}.`);
}

function renderPerformanceWallet(wallet) {
  const hours = performanceWindowHours();
  const pnl = Number(wallet.pnl_window_usdc ?? wallet.pnl_24h_usdc ?? 0);
  const markets = wallet.markets || [];
  const trades = Number(wallet.trades_window ?? wallet.trades_24h ?? 0);
  return `
    <article class="performance-wallet-card">
      <div class="row-top">
        <div>
          <div class="row-title">${escapeHtml(wallet.wallet_name || shortAddress(wallet.source_wallet))}</div>
          <div class="row-meta compact-line">${escapeHtml(shortAddress(wallet.source_wallet || ""))} - ${trades} closes in ${hours}h - ${Number(markets.length || 0)} market groups</div>
        </div>
        <strong class="${pnl < 0 ? "bad-text" : "good-text"}">${signedMoney(pnl)}</strong>
      </div>
      <div class="row-grid compact-metrics">
        <span>Realized ${signedMoney(wallet.realized_pnl_window_usdc ?? wallet.realized_pnl_24h_usdc ?? 0)}</span>
        <span>Unrealized ${signedMoney(wallet.unrealized_pnl_window_usdc ?? wallet.unrealized_pnl_24h_usdc ?? 0)}</span>
      </div>
      <div class="performance-market-list">
        ${markets.length ? markets.map(renderPerformanceMarket).join("") : `<div class="empty-inline">No active or closed PnL in this window.</div>`}
      </div>
    </article>
  `;
}

function renderPerformanceMarket(item) {
  const pnl = Number(item.pnl_window_usdc ?? item.pnl_24h_usdc ?? 0);
  return `
    <div class="performance-market-row">
      <div>
        <strong>${escapeHtml(String(item.market || "other").toUpperCase())}</strong>
        <span>${Number(item.open_positions || 0)} open - ${Number(item.trades || 0)} closed</span>
      </div>
      <div class="performance-market-values">
        <span>Open $${money(item.open_cost_usdc || 0)} / Value $${money(item.current_value_usdc || 0)}</span>
        <strong class="${pnl < 0 ? "bad-text" : "good-text"}">${signedMoney(pnl)}</strong>
      </div>
    </div>
  `;
}

function renderTradeRow(item) {
  const side = item.paper_side || item.source_side || "source";
  const sideClass = String(side).toLowerCase() === "sell" ? "sell" : "buy";
  const sourceSideLabel = sourceTradeSideLabel(item);
  const paperSideLabel = paperTradeSideLabel(item);
  const copiedFrom = item.copied_from_wallet_names?.length
    ? item.copied_from_wallet_names
    : (item.copied_from_wallets || []).map(shortAddress);
  const sourceNames = copiedFrom.length ? copiedFrom.join(", ") : walletLabel(item);
  const entry = tradeEntryBasis(item);
  const current = item.current_price == null ? null : Number(item.current_price || 0);
  const realized = item.paper_side === "sell" ? Number(item.realized_pnl_usdc || 0) : null;
  const skipReason = item.skip_reason || "";
  const closeReason = closeReasonLabel(item);
  const title = item.title || item.asset_id || "unknown asset";
  const outcome = item.market_outcome || item.outcome || "";
  const link = item.market_url || "";
  const tag = link ? "a" : "article";
  const href = link ? ` href="${escapeHtml(link)}" target="_blank" rel="noopener noreferrer"` : "";
  return `
    <${tag} class="trade-row card-link"${href}>
      <div class="row-top">
        <div>
          <div class="row-title">${escapeHtml(title)}</div>
          <div class="row-meta compact-line">${outcome ? `${escapeHtml(outcome)} · ` : ""}${escapeHtml(shortAddress(item.asset_id || ""))} · Paper ${escapeHtml(formatTradeTime(item.paper_time || item.source_time, { compact: true }))}${item.source_time ? ` · Source ${escapeHtml(formatTradeTime(item.source_time, { compact: true }))}` : ""}</div>
        </div>
        <span class="badge ${sideClass}">${escapeHtml(side)}</span>
      </div>
      <div class="row-grid trade-metrics">
        <span>Source ${escapeHtml(sourceNames)}</span>
        <span>${sourceSideLabel} $${money(item.source_notional_usdc)} @ ${Number(item.source_price || 0).toFixed(4)}</span>
        <span>${skipReason ? "" : `${paperSideLabel} $${money(item.paper_notional_usdc)} @ ${Number(item.fill_price || 0).toFixed(4)}`}</span>
        <span>Entry ${entry.notional == null || entry.price == null ? "N/A" : `$${money(entry.notional)} @ ${Number(entry.price || 0).toFixed(4)}`}</span>
        <span>Current ${formatPrice(current)}</span>
        ${realized == null ? "" : `<span class="${realized < 0 ? "bad-text" : "good-text"}">Realized ${signedMoney(realized)}</span>`}
        ${closeReason ? `<span>Close ${escapeHtml(closeReason)}</span>` : ""}
      </div>
      ${skipReason ? `<div class="skip-reason">Skipped: ${escapeHtml(skipReason)}</div>` : ""}
    </${tag}>
  `;
}

function renderWallets() {
  document.querySelector("#wallet-count").textContent = String(state.wallets.filter((wallet) => wallet.enabled).length);
  renderList("#wallet-list", state.wallets, (item) => {
    const address = item.address || "";
    const marketTypes = item.allowed_market_types || MARKET_TYPES;
    const strategyLines = walletStrategySummary(item);
    const strategyNotes = String(item.strategy_notes || "").trim();
    return `
    <article class="wallet-card wallet-card-v2 card-link ${item.enabled ? "" : "wallet-card-disabled"}" role="button" tabindex="0" data-wallet-address="${escapeHtml(address)}" aria-haspopup="dialog">
      <div class="wallet-icon wallet-avatar">${escapeHtml(walletInitials(item))}</div>
      <div class="wallet-card-main">
        <div class="wallet-card-titleline">
          <div>
            <div class="wallet-name">${escapeHtml(item.name)}</div>
            <div class="wallet-addr">${escapeHtml(address)}</div>
          </div>
          <span class="wallet-status-pill ${item.enabled ? "enabled" : "disabled"}"><i></i>${item.enabled ? "enabled" : "disabled"}</span>
        </div>
        <div class="wallet-tags">${walletMarketTags(marketTypes)}${walletStrategyTags(item)}</div>
        <div class="wallet-card-summary">
          ${strategyLines.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
        </div>
        ${strategyNotes ? `<div class="wallet-card-notes">${escapeHtml(strategyNotes)}</div>` : ""}
      </div>
      <div class="wallet-actions">
        <button class="row-action" type="button" data-wallet-edit="${escapeHtml(address)}">Edit</button>
        <button class="row-action danger" type="button" data-wallet-delete="${escapeHtml(address)}">Delete</button>
      </div>
    </article>
  `;
  }, "No wallets configured.");
  bindWalletButtons();
}

function renderSettings() {
  document.querySelector("#settings-list").innerHTML = SETTINGS_GROUPS.map((group) => `
    <section class="settings-section">
      <div class="settings-section-heading">
        <h3>${escapeHtml(group.title)}</h3>
        <span>${escapeHtml(group.description)}</span>
      </div>
      ${group.keys.map((key) => settingInput(key, state.settings[key])).join("")}
    </section>
  `).join("");
}

function settingInput(key, value) {
  if (key === "trading_mode") {
    return `
      <article class="settings-row">
        <div>
          <div class="settings-row-title">${settingLabel(key)}</div>
          <div class="settings-row-sub">${settingDescription(key)}</div>
        </div>
        <label class="settings-control">
          <select name="trading_mode">
            <option value="paper" ${value === "paper" ? "selected" : ""}>Paper</option>
            <option value="live" ${value === "live" ? "selected" : ""}>Live</option>
          </select>
        </label>
      </article>
    `;
  }
  if (key === "enabled_market_types") {
    return `
      <article class="settings-row">
        <div>
          <div class="settings-row-title">${settingLabel(key)}</div>
          <div class="settings-row-sub">${settingDescription(key)}</div>
        </div>
        <label class="settings-control market-type-settings">${marketTypeCheckboxes("settings_market_type", value || MARKET_TYPES)}</label>
      </article>
    `;
  }
  const isBool = typeof value === "boolean";
  const input = isBool
    ? `<input name="${escapeHtml(key)}" type="checkbox" ${value ? "checked" : ""}>`
    : `<input name="${escapeHtml(key)}" type="number" step="${numberStep(key)}" value="${escapeHtml(value)}">`;
  return `
    <article class="settings-row">
      <div>
        <div class="settings-row-title">${settingLabel(key)}</div>
        <div class="settings-row-sub">${settingDescription(key)}</div>
      </div>
      <label class="settings-control">${input}</label>
    </article>
  `;
}

function numberStep(key) {
  if (key.includes("minutes")) return "1";
  return "0.01";
}

function settingDescription(key) {
  const descriptions = {
    trading_mode: "Switches the configured runtime between paper and live.",
    mirror_source_sells: "Exit copied positions when the source wallet makes a serious sell.",
    max_trade_usdc: "Hard cap for any single paper buy.",
    max_position_usdc: "Global fallback per-asset cap; wallet profiles may be stricter.",
    min_trade_usdc: "Skip copied trades below this notional.",
    max_entry_price_source_premium: "Max executable-price premium over the source reference price.",
    max_entry_price_source_multiple: "Max executable-price multiple versus source reference price.",
    starting_cash_usdc: "Paper bankroll baseline used for dashboard PnL.",
    slippage_pct: "Adverse fill assumption for normal paper buys and sells.",
    settlement_slippage_pct: "Slippage used only for settlement exits.",
    enabled_market_types: "Global market families the bot may copy.",
    price_monitor_enabled: "Keep open-position quotes and exits updated.",
    price_monitor_poll_interval_seconds: "Fallback REST refresh interval while positions are open.",
    price_monitor_idle_poll_interval_seconds: "Idle refresh interval when there are no open positions.",
  };
  return descriptions[key] || "Runtime setting";
}

function settingLabel(key) {
  const labels = {
    trading_mode: "Trading mode",
    mirror_source_sells: "Mirror source sells",
    starting_cash_usdc: "Paper bankroll",
    min_trade_usdc: "Minimum trade",
    max_trade_usdc: "Max trade",
    max_position_usdc: "Max position",
    slippage_pct: "Paper slippage",
    settlement_slippage_pct: "Settlement slippage",
    max_entry_price_source_premium: "Entry premium guard",
    max_entry_price_source_multiple: "Entry multiple guard",
    enabled_market_types: "Market types",
    price_monitor_enabled: "Price monitor",
    price_monitor_poll_interval_seconds: "Open-position refresh",
    price_monitor_idle_poll_interval_seconds: "Idle refresh",
  };
  return escapeHtml(labels[key] || key);
}

function formatSetting(key, value) {
  if (typeof value === "boolean") return value ? "on" : "off";
  if (Array.isArray(value)) return value.join(" / ");
  if (key.endsWith("_usdc")) return `$${money(value)}`;
  if (key.endsWith("_pct")) return `${money(value)}%`;
  if (key.endsWith("_seconds")) return `${money(value, 0)}s`;
  if (key === "copy_scale") return `${Number(value || 0).toFixed(2)}x`;
  return value ?? "";
}

function marketTypeCheckboxes(prefix, selected) {
  const selectedSet = new Set(selected || MARKET_TYPES);
  return MARKET_TYPES.map((type) => `
    <span><input name="${prefix}_${type}" type="checkbox" value="${type}" ${selectedSet.has(type) ? "checked" : ""}> ${escapeHtml(type)}</span>
  `).join("");
}

function selectedSettingsMarketTypes(form) {
  return MARKET_TYPES.filter((type) => form.elements[`settings_market_type_${type}`]?.checked);
}

function defaultWalletDraft() {
  return {
    name: "",
    address: "",
    enabled: true,
    strategy_notes: "",
    allowed_market_types: [...MARKET_TYPES],
    profile_json: defaultWalletProfile(),
  };
}

function walletInitials(wallet) {
  const text = String(wallet.name || wallet.address || "?").trim();
  const words = text.split(/[\s_-]+/).filter(Boolean);
  if (words.length > 1) return `${words[0][0]}${words[1][0]}`.toUpperCase();
  return text.slice(0, 2).toUpperCase();
}

function walletMarketTags(types) {
  return (types || MARKET_TYPES).map((type) => `
    <span class="wallet-tag wallet-tag-${escapeHtml(type)}">${escapeHtml(type)}</span>
  `).join("");
}

function walletStrategyTags(wallet) {
  const tags = [];
  if (!copyBuysEnabled(wallet)) tags.push(["Copy paused", "muted"]);
  if (profileEnabled(wallet, "weather_bracket", "bracket_strategy_enabled")) tags.push(["Weather bracket", "weather"]);
  if (profileEnabled(wallet, "repeat_buy", "repeat_buy_strategy_enabled")) tags.push(["Repeat-buy", "sports"]);
  if (profileEnabled(wallet, "event_follow", "event_follow_strategy_enabled")) tags.push(["Event-follow", "all"]);
  if (profileEnabled(wallet, "sports_trailing", "sports_trailing_stop_enabled")) tags.push(["Sports trail", "sports"]);
  if (!tags.length) tags.push(["Standard", "muted"]);
  return tags.map(([label, type]) => `<span class="wallet-tag wallet-tag-${type}">${escapeHtml(label)}</span>`).join("");
}

function walletStrategySummary(wallet) {
  const lines = [];
  const weatherBracket = profileSection(wallet, "weather_bracket");
  const repeatBuy = profileSection(wallet, "repeat_buy");
  const eventFollow = profileSection(wallet, "event_follow");
  const sportsTrailing = profileSection(wallet, "sports_trailing");
  if (!copyBuysEnabled(wallet)) {
    lines.push("Copy buys paused");
  }
  if (profileEnabled(wallet, "weather_bracket", "bracket_strategy_enabled")) {
    const buySize = valueFromProfile(weatherBracket, "buy_size_usdc", wallet.bracket_buy_size_usdc);
    const stopLoss = valueFromProfile(weatherBracket, "stop_loss_pct", wallet.bracket_stop_loss_pct);
    const maxOpen = valueFromProfile(weatherBracket, "max_open_events", wallet.bracket_max_open_events);
    lines.push(`Weather bracket $${money(buySize)} / SL ${money(stopLoss)}% / cap ${Number(maxOpen || 0) || "off"}`);
  }
  if (profileEnabled(wallet, "repeat_buy", "repeat_buy_strategy_enabled")) {
    const buySize = valueFromProfile(repeatBuy, "buy_size_usdc", wallet.repeat_buy_size_usdc);
    const minBuys = valueFromProfile(repeatBuy, "min_buy_count", wallet.repeat_buy_min_buy_count);
    const minSource = valueFromProfile(repeatBuy, "min_source_notional_usdc", wallet.repeat_buy_min_source_notional_usdc);
    lines.push(`Repeat-buy $${money(buySize)} / ${Number(minBuys || 2)} buys / source $${money(minSource || 0)}`);
  }
  if (profileEnabled(wallet, "event_follow", "event_follow_strategy_enabled")) {
    const buySize = valueFromProfile(eventFollow, "buy_size_usdc", wallet.event_follow_buy_size_usdc);
    const eventCap = valueFromProfile(eventFollow, "max_event_exposure_usdc", wallet.event_follow_max_event_exposure_usdc);
    const sourceMin = valueFromProfile(eventFollow, "min_source_trade_usdc", wallet.event_follow_min_source_trade_usdc);
    lines.push(`Event-follow $${money(buySize)} / event cap $${money(eventCap)} / source min $${money(sourceMin)}`);
  }
  if (profileEnabled(wallet, "sports_trailing", "sports_trailing_stop_enabled")) {
    const activation = valueFromProfile(sportsTrailing, "activation_pct", wallet.sports_trailing_activation_pct);
    const stop = valueFromProfile(sportsTrailing, "stop_pct", wallet.sports_trailing_stop_pct);
    lines.push(`Sports trail arms +${money(activation)}% / trails ${money(stop)}%`);
  }
  return lines.length ? lines : ["Standard copy sizing"];
}

function profileSection(wallet, key) {
  const profile = wallet.profile_json;
  const section = profile && typeof profile === "object" && !Array.isArray(profile) ? profile[key] : null;
  return section && typeof section === "object" && !Array.isArray(section) ? section : {};
}

function profileEnabled(wallet, sectionKey, normalizedKey) {
  const section = profileSection(wallet, sectionKey);
  if (typeof section.enabled === "boolean") return section.enabled;
  return Boolean(wallet[normalizedKey]);
}

function copyBuysEnabled(wallet) {
  const strategy = profileSection(wallet, "strategy");
  if (typeof strategy.copy_buys_enabled === "boolean") return strategy.copy_buys_enabled;
  return true;
}

function valueFromProfile(section, key, fallback) {
  return section[key] == null ? fallback : section[key];
}

function walletCheckbox(name, label, checked, extraClass = "") {
  return `
    <label class="wallet-check ${extraClass}">
      <input name="${escapeHtml(name)}" type="checkbox" ${checked ? "checked" : ""}>
      <span class="wallet-check-box"></span>
      <span>${escapeHtml(label)}</span>
    </label>
  `;
}

function walletProfileJsonText(wallet) {
  return JSON.stringify(editableWalletProfile(wallet), null, 2);
}

function defaultWalletProfile() {
  if (plainObject(state.defaultWalletProfile)) {
    return cloneJsonValue(state.defaultWalletProfile);
  }
  return { version: 1 };
}

function plainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cloneJsonValue(value) {
  if (plainObject(value) || Array.isArray(value)) return JSON.parse(JSON.stringify(value));
  return value;
}

function mergeProfileObjects(defaults, value) {
  const merged = plainObject(defaults) ? cloneJsonValue(defaults) : {};
  if (!plainObject(value)) return merged;
  Object.entries(value).forEach(([key, override]) => {
    if (plainObject(override) && plainObject(merged[key])) {
      merged[key] = mergeProfileObjects(merged[key], override);
    } else {
      merged[key] = cloneJsonValue(override);
    }
  });
  return merged;
}

function editableWalletProfile(wallet) {
  const profile = normalizedProfileObject(wallet.profile_json);
  profile.version = Number(profile.version || 1);
  profile.market_filters = sectionWith(profile.market_filters, {
    allowed_market_types: Array.isArray(wallet.allowed_market_types) ? wallet.allowed_market_types : [...MARKET_TYPES],
  });
  profile.source_follow = sectionWith(profile.source_follow, {});
  profile.event_book = sectionWith(profile.event_book, {});
  profile.fixed_buy = sectionWith(profile.fixed_buy, {});
  profile.binary_hedge = sectionWith(profile.binary_hedge, {});
  profile.limit_copy = sectionWith(profile.limit_copy, {});
  profile.tier_sizing = sectionWith(profile.tier_sizing, {});
  profile.esports_repeat_buy = sectionWith(profile.esports_repeat_buy, {});
  profile.high_conviction = sectionWith(profile.high_conviction, {});
  profile.strategy = sectionWith(profile.strategy, {});
  profile.weather_bracket = sectionWith(profile.weather_bracket, {
    enabled: Boolean(wallet.bracket_strategy_enabled),
    buy_size_usdc: Number(wallet.bracket_buy_size_usdc || 10),
    stop_loss_pct: Number(wallet.bracket_stop_loss_pct || 0),
    max_open_events: Number(wallet.bracket_max_open_events || 0),
    allowed_patterns: Array.isArray(wallet.bracket_allowed_patterns) ? wallet.bracket_allowed_patterns : [...WEATHER_PATTERNS],
  });
  profile.repeat_buy = sectionWith(profile.repeat_buy, {
    enabled: Boolean(wallet.repeat_buy_strategy_enabled),
    buy_size_usdc: Number(wallet.repeat_buy_size_usdc || 5),
    stop_loss_pct: Number(wallet.repeat_buy_stop_loss_pct || 0),
    min_source_notional_usdc: Number(wallet.repeat_buy_min_source_notional_usdc || 0),
    min_buy_count: Number(wallet.repeat_buy_min_buy_count || 2),
    min_avg_price: Number(wallet.repeat_buy_min_avg_price || 0.01),
    max_avg_price: Number(wallet.repeat_buy_max_avg_price || 1),
    max_total_exposure_usdc: Number(wallet.repeat_buy_max_total_exposure_usdc || 0),
    blocked_title_patterns: Array.isArray(wallet.repeat_buy_blocked_title_patterns) ? wallet.repeat_buy_blocked_title_patterns : [],
    allowed_sports: Array.isArray(wallet.repeat_buy_allowed_sports) ? wallet.repeat_buy_allowed_sports : [],
    allowed_bet_types: Array.isArray(wallet.repeat_buy_allowed_bet_types) ? wallet.repeat_buy_allowed_bet_types : [],
  });
  profile.event_follow = sectionWith(profile.event_follow, {
    enabled: Boolean(wallet.event_follow_strategy_enabled),
    buy_size_usdc: Number(wallet.event_follow_buy_size_usdc || 2),
    max_event_exposure_usdc: Number(wallet.event_follow_max_event_exposure_usdc || 4),
    max_total_exposure_usdc: Number(wallet.event_follow_max_total_exposure_usdc || 50),
    min_source_trade_usdc: Number(wallet.event_follow_min_source_trade_usdc || 20),
    min_event_source_notional_usdc: Number(wallet.event_follow_min_event_source_notional_usdc || 250),
    min_event_buy_count: Number(wallet.event_follow_min_event_buy_count || 3),
    min_avg_price: Number(wallet.event_follow_min_avg_price || 0.2),
    max_avg_price: Number(wallet.event_follow_max_avg_price || 0.8),
  });
  profile.sports_trailing = sectionWith(profile.sports_trailing, {
    enabled: Boolean(wallet.sports_trailing_stop_enabled),
    activation_pct: Number(wallet.sports_trailing_activation_pct || 35),
    stop_pct: Number(wallet.sports_trailing_stop_pct || 25),
    floor_delta: Number(wallet.sports_trailing_floor_delta || 0.03),
  });
  profile.risk = sectionWith(profile.risk, {
    reserved_cash_usdc: Number(wallet.reserved_cash_usdc || 0),
  });
  return profile;
}

function normalizedProfileObject(value) {
  if (typeof value === "string") {
    try {
      value = JSON.parse(value);
    } catch {
      return defaultWalletProfile();
    }
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return defaultWalletProfile();
  return mergeProfileObjects(defaultWalletProfile(), value);
}

function sectionWith(value, defaults) {
  const section = value && typeof value === "object" && !Array.isArray(value) ? value : {};
  return { ...defaults, ...section };
}

function parseWalletProfileJson(value) {
  let parsed;
  try {
    parsed = JSON.parse(String(value || "{}"));
  } catch {
    throw new Error("Profile JSON is not valid JSON.");
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Profile JSON must be a JSON object.");
  }
  return parsed;
}

function setWalletProfileJsonError(form, message) {
  const field = form?.elements?.profile_json;
  const error = form?.querySelector("[data-wallet-profile-json-error]");
  field?.classList.toggle("invalid", Boolean(message));
  if (field) field.setAttribute("aria-invalid", message ? "true" : "false");
  if (error) error.textContent = message || "";
}

function signedMoney(value) {
  const amount = Number(value || 0);
  return `${amount < 0 ? "-" : "+"}$${money(Math.abs(amount))}`;
}

function signedPct(value) {
  const amount = Number(value || 0);
  return `${amount < 0 ? "-" : "+"}${money(Math.abs(amount), 2)}%`;
}

function formatPrice(value) {
  return value == null ? "--" : Number(value || 0).toFixed(4);
}

function formatQuantity(value) {
  return Number(value || 0).toLocaleString(undefined, {
    minimumFractionDigits: 4,
    maximumFractionDigits: 4,
  });
}

function rangeLabel(range) {
  return { day: "today", week: "this week", month: "this month", lifetime: "lifetime" }[range] || "today";
}

function holdingMetrics(item) {
  const quantity = Number(item.quantity || 0);
  const entry = item.entry_price == null ? Number(item.avg_entry_price || 0) : Number(item.entry_price || 0);
  const current = item.current_price == null ? null : Number(item.current_price || 0);
  const value = Number(item.current_value_usdc || quantity * (current ?? entry));
  const cost = Number(item.cost_basis_usdc || quantity * entry);
  const pnl = Number(item.unrealized_pnl_usdc || value - cost);
  const pnlPct = item.unrealized_pnl_pct == null
    ? (cost ? (pnl / cost) * 100 : 0)
    : Number(item.unrealized_pnl_pct || 0);
  return { quantity, entry, current, value, cost, pnl, pnlPct };
}

function activeHolding() {
  if (state.activeHoldingIndex == null) return null;
  return state.holdings[state.activeHoldingIndex] || null;
}

function activeWallet() {
  if (state.walletModalMode === "create") return defaultWalletDraft();
  if (!state.activeWalletAddress) return null;
  return state.wallets.find((item) => item.address === state.activeWalletAddress) || null;
}

function ensureHoldingModal() {
  let element = document.querySelector("#holding-modal-layer");
  if (element) return element;
  element = document.createElement("div");
  element.id = "holding-modal-layer";
  element.className = "holding-modal-layer";
  document.body.appendChild(element);
  element.addEventListener("click", (event) => {
    if (event.target === element) closeHoldingModal();
  });
  return element;
}

function openHoldingModal(index) {
  state.activeHoldingIndex = Number(index);
  state.holdingModalOpen = true;
  state.holdingSellConfirm = false;
  state.holdingSellBusy = false;
  state.holdingSellError = "";
  renderHoldingModal();
}

function closeHoldingModal() {
  state.holdingModalOpen = false;
  state.holdingSellConfirm = false;
  state.holdingSellBusy = false;
  state.holdingSellError = "";
  state.activeHoldingIndex = null;
  renderHoldingModal();
}

function renderHoldingModal() {
  const layer = ensureHoldingModal();
  const item = activeHolding();
  if (!state.holdingModalOpen || !item) {
    layer.classList.remove("active");
    layer.setAttribute("aria-hidden", "true");
    layer.innerHTML = "";
    if (!state.walletModalOpen) document.body.classList.remove("holding-modal-open");
    return;
  }

  const metrics = holdingMetrics(item);
  const title = item.title || item.asset_id || "Open holding";
  const outcome = item.outcome || item.market_outcome || "";
  const marketUrl = item.market_url || "";
  const pnlClass = metrics.pnl < 0 ? "bad-text" : "good-text";
  const sourceWallet = item.source_wallet ? shortAddress(item.source_wallet) : "Unknown source";

  layer.classList.add("active");
  layer.setAttribute("aria-hidden", "false");
  document.body.classList.add("holding-modal-open");
  layer.innerHTML = `
    <section class="holding-modal" role="dialog" aria-modal="true" aria-labelledby="holding-modal-title" tabindex="-1">
      <div class="holding-modal-header">
        <div>
          <p class="eyebrow">Open holding</p>
          <h2 id="holding-modal-title">${escapeHtml(title)}</h2>
          <p class="holding-modal-subtitle">${escapeHtml(item.asset_id || "")}${outcome ? ` / ${escapeHtml(outcome)}` : ""}</p>
        </div>
        <button class="modal-close" type="button" data-holding-modal-close aria-label="Close holding details">x</button>
      </div>

      <div class="holding-metrics">
        <article>
          <span>Entry</span>
          <strong>${formatPrice(metrics.entry)}</strong>
        </article>
        <article>
          <span>Current</span>
          <strong>${formatPrice(metrics.current)}</strong>
        </article>
        <article>
          <span>Qty</span>
          <strong>${formatQuantity(metrics.quantity)}</strong>
        </article>
        <article>
          <span>Value</span>
          <strong>$${money(metrics.value)}</strong>
        </article>
        <article>
          <span>PnL</span>
          <strong class="${pnlClass}">${signedMoney(metrics.pnl)}</strong>
        </article>
        <article>
          <span>PnL %</span>
          <strong class="${pnlClass}">${signedPct(metrics.pnlPct)}</strong>
        </article>
      </div>

      <div class="holding-source">
        <span>Wallet/source</span>
        <strong>${escapeHtml(walletLabel(item))}</strong>
        <small>${escapeHtml(sourceWallet)}</small>
        <small>Buy time: ${escapeHtml(positionBuyTime(item))}</small>
        <small>${escapeHtml(marketTimeName(item))}: ${escapeHtml(marketCloseLabel(item))}</small>
      </div>

      <div class="holding-actions">
        ${marketUrl ? `<a class="btn-secondary" href="${escapeHtml(marketUrl)}" target="_blank" rel="noopener noreferrer">Open Polymarket</a>` : `<span class="btn-secondary disabled">No market link</span>`}
        ${renderHoldingSellAction()}
      </div>
    </section>
  `;
  bindHoldingModalButtons();
}

function renderHoldingSellAction() {
  if (!state.holdingSellConfirm) {
    return `<button class="btn-danger" type="button" data-holding-sell-start>Sell position</button>`;
  }
  return `
    <div class="sell-confirm">
      <p>Confirm sell for this holding?</p>
      <div>
        <button class="btn-danger" type="button" data-holding-sell-confirm ${state.holdingSellBusy ? "disabled" : ""}>${state.holdingSellBusy ? "Selling..." : "Confirm sell"}</button>
        <button class="btn-secondary" type="button" data-holding-sell-cancel ${state.holdingSellBusy ? "disabled" : ""}>Cancel</button>
      </div>
      <span>${state.holdingSellError ? escapeHtml(state.holdingSellError) : "Uses the current marked price and records a manual sell in the paper ledger."}</span>
    </div>
  `;
}

function bindHoldingCards() {
  document.querySelectorAll("[data-holding-index]").forEach((card) => {
    card.addEventListener("click", () => openHoldingModal(card.dataset.holdingIndex));
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openHoldingModal(card.dataset.holdingIndex);
    });
  });
}

function bindHoldingModalButtons() {
  const layer = document.querySelector("#holding-modal-layer");
  layer.querySelector("[data-holding-modal-close]")?.addEventListener("click", closeHoldingModal);
  layer.querySelector("[data-holding-sell-start]")?.addEventListener("click", () => {
    state.holdingSellConfirm = true;
    state.holdingSellError = "";
    renderHoldingModal();
  });
  layer.querySelector("[data-holding-sell-cancel]")?.addEventListener("click", () => {
    state.holdingSellConfirm = false;
    state.holdingSellError = "";
    renderHoldingModal();
  });
  layer.querySelector("[data-holding-sell-confirm]")?.addEventListener("click", async () => {
    const item = activeHolding();
    if (!item) return;
    state.holdingSellBusy = true;
    state.holdingSellError = "";
    renderHoldingModal();
    try {
      await sendJson("/api/holdings/sell", "POST", {
        asset_id: item.asset_id,
        source_wallet: item.source_wallet,
      });
      closeHoldingModal();
      await refresh();
    } catch (error) {
      state.holdingSellBusy = false;
      state.holdingSellError = error.message || "Manual sell failed.";
      renderHoldingModal();
    }
  });
  window.requestAnimationFrame(() => {
    layer.querySelector(".holding-modal")?.focus();
  });
}

function ensureWalletModal() {
  let element = document.querySelector("#wallet-modal-layer");
  if (element) return element;
  element = document.createElement("div");
  element.id = "wallet-modal-layer";
  element.className = "holding-modal-layer wallet-modal-layer";
  document.body.appendChild(element);
  element.addEventListener("click", (event) => {
    if (event.target === element) closeWalletModal();
  });
  return element;
}

function openWalletModal(address, options = {}) {
  state.activeWalletAddress = address;
  state.walletModalMode = "edit";
  state.walletModalOpen = true;
  state.walletDeleteConfirm = Boolean(options.confirmDelete);
  state.walletModalBusy = false;
  state.walletModalError = "";
  renderWalletModal();
}

function openWalletCreateModal() {
  state.activeWalletAddress = null;
  state.walletModalMode = "create";
  state.walletModalOpen = true;
  state.walletDeleteConfirm = false;
  state.walletModalBusy = false;
  state.walletModalError = "";
  renderWalletModal();
}

function closeWalletModal() {
  state.walletModalOpen = false;
  state.walletDeleteConfirm = false;
  state.walletModalBusy = false;
  state.walletModalError = "";
  state.activeWalletAddress = null;
  state.walletModalMode = "edit";
  renderWalletModal();
}

function renderWalletModal() {
  const layer = ensureWalletModal();
  const wallet = activeWallet();
  if (!state.walletModalOpen || !wallet) {
    layer.classList.remove("active");
    layer.setAttribute("aria-hidden", "true");
    layer.innerHTML = "";
    if (!state.holdingModalOpen) document.body.classList.remove("holding-modal-open");
    return;
  }

  const isCreate = state.walletModalMode === "create";
  const title = isCreate ? "Add Wallet" : wallet.name || shortAddress(wallet.address);
  const summaryLines = walletStrategySummary(wallet);
  const strategyNotes = wallet.strategy_notes || "";
  const profileJsonText = walletProfileJsonText(wallet);
  layer.classList.add("active");
  layer.setAttribute("aria-hidden", "false");
  document.body.classList.add("holding-modal-open");
  layer.innerHTML = `
    <section class="holding-modal wallet-modal" role="dialog" aria-modal="true" aria-labelledby="wallet-modal-title" tabindex="-1">
      <div class="wallet-modal-header">
        <div class="wallet-modal-titleblock">
          <div class="wallet-avatar wallet-modal-avatar">${escapeHtml(walletInitials(wallet))}</div>
          <div>
            <p class="eyebrow">Managed wallet</p>
            <h2 id="wallet-modal-title">${escapeHtml(title)}</h2>
            <p class="holding-modal-subtitle">${escapeHtml(isCreate ? "Configure a new copy source" : wallet.address || "")}</p>
          </div>
        </div>
        <button class="modal-close" type="button" data-wallet-modal-close aria-label="Close wallet editor">x</button>
      </div>

      <form class="wallet-modal-form" id="wallet-modal-form">
        <section class="wallet-modal-section wallet-modal-identity">
          <div class="wallet-modal-grid two">
            <label class="wallet-field">
              <span>Name</span>
              <input name="name" autocomplete="off" required placeholder="Wallet name" value="${escapeHtml(wallet.name || "")}">
            </label>
            <div class="wallet-field">
              <span>Status</span>
              ${walletCheckbox("enabled", wallet.enabled ? "Trading enabled" : "Trading disabled", wallet.enabled, "wallet-status-toggle")}
            </div>
          </div>
          <div class="wallet-field">
            <span>Trading address</span>
            ${isCreate
              ? `<input name="address" autocomplete="off" required placeholder="0x trading/proxy address" value="${escapeHtml(wallet.address || "")}">`
              : `<div class="wallet-address-display">${escapeHtml(wallet.address || "")}</div>`}
          </div>
          <label class="wallet-field wallet-notes-field">
            <span>Strategy notes</span>
            <textarea name="strategy_notes" rows="3" placeholder="Per-wallet targeting notes">${escapeHtml(strategyNotes)}</textarea>
          </label>
          <div class="wallet-summary-strip">
            ${summaryLines.map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
          </div>
        </section>

        <section class="wallet-modal-section wallet-profile-json-section">
          <div class="wallet-modal-section-heading">
            <h3>Profile JSON</h3>
            <span>Per-wallet strategy and market gates</span>
          </div>
          <label class="wallet-field wallet-json-field">
            <span>Profile JSON</span>
            <textarea name="profile_json" rows="14" spellcheck="false" autocomplete="off" aria-describedby="wallet-profile-json-error">${escapeHtml(profileJsonText)}</textarea>
          </label>
          <p class="wallet-json-error" id="wallet-profile-json-error" data-wallet-profile-json-error aria-live="polite"></p>
        </section>

        ${state.walletModalError ? `<p class="modal-error">${escapeHtml(state.walletModalError)}</p>` : ""}

        <div class="wallet-modal-actions">
          <button class="btn-primary" type="submit" ${state.walletModalBusy ? "disabled" : ""}>${state.walletModalBusy ? "Saving..." : isCreate ? "Add Wallet" : "Save"}</button>
          <button class="btn-secondary" type="button" data-wallet-modal-close ${state.walletModalBusy ? "disabled" : ""}>Cancel</button>
        </div>
      </form>

      <div class="wallet-delete-panel ${isCreate ? "hidden" : ""}">
        ${renderWalletDeleteAction(wallet)}
      </div>
    </section>
  `;
  bindWalletModalButtons();
}

function walletPayloadFromForm(form) {
  const payload = {
    name: form.elements.name.value,
    enabled: form.elements.enabled.checked,
    strategy_notes: form.elements.strategy_notes.value || "",
    profile_json: parseWalletProfileJson(form.elements.profile_json.value),
  };
  if (form.elements.address) payload.address = form.elements.address.value;
  return payload;
}

function renderWalletDeleteAction(wallet) {
  if (!state.walletDeleteConfirm) {
    return `<button class="btn-danger" type="button" data-wallet-delete-start ${state.walletModalBusy ? "disabled" : ""}>Delete wallet</button>`;
  }
  return `
    <div class="sell-confirm wallet-delete-confirm">
      <p>Delete ${escapeHtml(wallet.name || shortAddress(wallet.address))}?</p>
      <span>This removes the wallet from copy sources. Existing ledger history stays intact.</span>
      <div>
        <button class="btn-danger" type="button" data-wallet-delete-confirm ${state.walletModalBusy ? "disabled" : ""}>${state.walletModalBusy ? "Deleting..." : "Confirm delete"}</button>
        <button class="btn-secondary" type="button" data-wallet-delete-cancel ${state.walletModalBusy ? "disabled" : ""}>Cancel</button>
      </div>
    </div>
  `;
}

function bindWalletModalButtons() {
  const layer = document.querySelector("#wallet-modal-layer");
  const form = layer.querySelector("#wallet-modal-form");
  layer.querySelectorAll("[data-wallet-modal-close]").forEach((button) => {
    button.addEventListener("click", closeWalletModal);
  });
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const wallet = activeWallet();
    if (!wallet) return;
    const isCreate = state.walletModalMode === "create";
    let payload;
    try {
      payload = walletPayloadFromForm(form);
      setWalletProfileJsonError(form, "");
    } catch (error) {
      setWalletProfileJsonError(form, error.message || "Profile JSON is invalid.");
      form.elements.profile_json?.focus();
      return;
    }
    state.walletModalBusy = true;
    state.walletModalError = "";
    renderWalletModal();
    try {
      if (isCreate) {
        await sendJson("/api/wallets", "POST", payload);
      } else {
        await sendJson(`/api/wallets/${encodeURIComponent(wallet.address)}`, "PATCH", payload);
      }
      closeWalletModal();
      await refresh();
    } catch (error) {
      state.walletModalBusy = false;
      state.walletModalError = error.message || "Wallet save failed.";
      renderWalletModal();
    }
  });
  form?.elements.profile_json?.addEventListener("input", () => setWalletProfileJsonError(form, ""));
  layer.querySelector("[data-wallet-delete-start]")?.addEventListener("click", () => {
    state.walletDeleteConfirm = true;
    state.walletModalError = "";
    renderWalletModal();
  });
  layer.querySelector("[data-wallet-delete-cancel]")?.addEventListener("click", () => {
    state.walletDeleteConfirm = false;
    state.walletModalError = "";
    renderWalletModal();
  });
  layer.querySelector("[data-wallet-delete-confirm]")?.addEventListener("click", async () => {
    const wallet = activeWallet();
    if (!wallet) return;
    state.walletModalBusy = true;
    state.walletModalError = "";
    renderWalletModal();
    try {
      await sendJson(`/api/wallets/${encodeURIComponent(wallet.address)}`, "DELETE", {});
      closeWalletModal();
      await refresh();
    } catch (error) {
      state.walletModalBusy = false;
      state.walletModalError = error.message || "Wallet delete failed.";
      renderWalletModal();
    }
  });
  window.requestAnimationFrame(() => {
    layer.querySelector(".wallet-modal")?.focus();
  });
}

function renderChart(points) {
  const svg = document.querySelector("#pnl-chart");
  const values = points.length ? points.map((point) => Number(point.value || 0)) : [0];
  const labels = points.length ? points.map((point) => String(point.label || "")) : [""];
  if (values.length === 1) values.push(values[0]);
  if (labels.length === 1) labels.push(labels[0]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const spread = Math.max(1, max - min);
  const chartPoints = values.map((value, index) => {
    const x = 18 + (index / Math.max(1, values.length - 1)) * 764;
    const y = 184 - ((value - min) / spread) * 150;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  }).join(" ");
  const last = values[values.length - 1] || 0;
  const first = values[0] || 0;
  const midIndex = Math.floor((labels.length - 1) / 2);
  const strokeClass = last < first ? "chart-line negative" : "chart-line";
  svg.innerHTML = `
    ${[0, 1, 2, 3, 4].map((line) => `<line x1="18" x2="782" y1="${34 + line * 36}" y2="${34 + line * 36}" class="chart-grid"></line>`).join("")}
    <polyline points="${chartPoints}" class="${strokeClass}"></polyline>
    <text x="784" y="36" class="chart-axis">$${money(max, 0)}</text>
    <text x="784" y="184" class="chart-axis">$${money(min, 0)}</text>
    <text x="18" y="210" text-anchor="start" class="chart-axis chart-axis-x">${escapeHtml(labels[0] || "")}</text>
    <text x="390" y="210" text-anchor="middle" class="chart-axis chart-axis-x">${escapeHtml(labels[midIndex] || "")}</text>
    <text x="782" y="210" text-anchor="end" class="chart-axis chart-axis-x">${escapeHtml(labels[labels.length - 1] || "")}</text>
  `;
}

function setRange(range) {
  state.activeRange = range;
  document.querySelectorAll("[data-range]").forEach((item) => {
    item.classList.toggle("active", item.dataset.range === state.activeRange);
  });
  renderDashboard();
}

function performanceWindowHours() {
  const hours = Number(state.performanceHours || state.performance.window_hours || 24);
  return PERFORMANCE_WINDOWS.includes(hours) ? hours : 24;
}

async function refreshPerformance() {
  const performance = await fetchJsonOr(`/api/performance?hours=${state.performanceHours}`, state.performance);
  state.performance = performance || { wallets: [] };
  renderPerformance();
}

async function setPerformanceHours(hours) {
  const nextHours = Number(hours);
  state.performanceHours = PERFORMANCE_WINDOWS.includes(nextHours) ? nextHours : 24;
  await refreshPerformance();
}

function setPositionTab(tab) {
  state.activePositionTab = ["open", "closed"].includes(tab) ? tab : "open";
  renderPositionTabs();
}

function renderList(selector, items, template, emptyText) {
  const element = document.querySelector(selector);
  element.innerHTML = items.length ? items.map(template).join("") : `<p class="empty">${escapeHtml(emptyText)}</p>`;
}

function navigateTo(page) {
  state.activePage = page;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.page === page);
  });
  document.querySelectorAll(".page").forEach((item) => {
    item.classList.toggle("active", item.id === `page-${page}`);
  });
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#overlay").classList.remove("active");
  renderTopbar();
}

function bindWalletButtons() {
  document.querySelectorAll("[data-wallet-address]").forEach((card) => {
    card.addEventListener("click", () => openWalletModal(card.dataset.walletAddress));
    card.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openWalletModal(card.dataset.walletAddress);
    });
  });

  document.querySelectorAll("[data-wallet-edit]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openWalletModal(button.dataset.walletEdit);
    });
  });

  document.querySelectorAll("[data-wallet-delete]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      openWalletModal(button.dataset.walletDelete, { confirmDelete: true });
    });
  });
}

document.querySelectorAll(".nav-item").forEach((item) => {
  item.addEventListener("click", () => navigateTo(item.dataset.page));
});

document.querySelectorAll("[data-page-jump]").forEach((item) => {
  item.addEventListener("click", () => navigateTo(item.dataset.pageJump));
});

document.querySelector("#menu-btn").addEventListener("click", () => {
  document.querySelector("#sidebar").classList.add("open");
  document.querySelector("#overlay").classList.add("active");
});

document.querySelector("#sidebar-close").addEventListener("click", () => {
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#overlay").classList.remove("active");
});

document.querySelector("#overlay").addEventListener("click", () => {
  document.querySelector("#sidebar").classList.remove("open");
  document.querySelector("#overlay").classList.remove("active");
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.holdingModalOpen) closeHoldingModal();
  if (event.key === "Escape" && state.walletModalOpen) closeWalletModal();
});

document.querySelector("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const next = root.dataset.theme === "dark" ? "light" : "dark";
  root.dataset.theme = next;
  localStorage.setItem("theme", next);
  document.querySelector("#theme-label").textContent = next === "dark" ? "Dark Mode" : "Light Mode";
});

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#refresh-mobile").addEventListener("click", refresh);
document.querySelector("#refresh-trades").addEventListener("click", refresh);
document.querySelector("#refresh-performance").addEventListener("click", refreshPerformance);
document.querySelectorAll("[data-range]").forEach((control) => {
  control.addEventListener("click", () => setRange(control.dataset.range));
});
document.querySelectorAll("[data-performance-hours]").forEach((control) => {
  control.addEventListener("click", () => setPerformanceHours(control.dataset.performanceHours));
});
document.querySelectorAll("[data-position-tab]").forEach((control) => {
  control.addEventListener("click", () => setPositionTab(control.dataset.positionTab));
});
document.querySelector("#pnl-cards").addEventListener("click", (event) => {
  const card = event.target.closest("[data-range-card]");
  if (card) setRange(card.dataset.rangeCard);
});

document.querySelector("#wallet-add-open")?.addEventListener("click", openWalletCreateModal);

document.querySelector("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = {};
  SETTINGS_KEYS.forEach((key) => {
    const value = state.settings[key];
    if (key === "enabled_market_types") {
      payload[key] = selectedSettingsMarketTypes(form);
      return;
    }
    const field = form.elements[key];
    if (!field) return;
    if (key === "trading_mode") {
      payload[key] = field.value;
    } else {
      payload[key] = typeof value === "boolean" ? field.checked : Number(field.value);
    }
  });
  const result = await sendJson("/api/settings", "PATCH", payload);
  state.settings = result.settings || state.settings;
  document.querySelector("#settings-status").textContent = "Saved. Runtime services refresh config periodically.";
  render();
});

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}

const savedTheme = localStorage.getItem("theme");
if (savedTheme === "light" || savedTheme === "dark") {
  document.documentElement.dataset.theme = savedTheme;
  document.querySelector("#theme-label").textContent = savedTheme === "dark" ? "Dark Mode" : "Light Mode";
}

refresh().catch((error) => {
  document.querySelector("#pnl-cards").innerHTML = `
    <article class="stat-card">
      <span class="stat-label">Error</span>
      <strong class="stat-value">${escapeHtml(error.message)}</strong>
    </article>
  `;
});
