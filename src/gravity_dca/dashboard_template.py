from __future__ import annotations

HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#002b36">
  <title>Gravity Bot Dashboard</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #002b36;
      --bg-elevated: #073642;
      --panel: rgba(12, 54, 66, 0.92);
      --panel-strong: rgba(16, 64, 78, 0.98);
      --ink: #fdf6e3;
      --muted: #93a1a1;
      --border: rgba(147, 161, 161, 0.18);
      --accent: #2aa198;
      --accent-soft: rgba(42, 161, 152, 0.18);
      --warn: #b58900;
      --warn-soft: rgba(181, 137, 0, 0.18);
      --danger: #dc322f;
      --danger-soft: rgba(220, 50, 47, 0.18);
      --ok: #859900;
      --ok-soft: rgba(133, 153, 0, 0.18);
      --focus: #cb4b16;
      --shadow: 0 24px 60px rgba(0, 18, 24, 0.42);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Iowan Old Style", "Palatino Linotype", Georgia, serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(42, 161, 152, 0.22), transparent 24rem),
        radial-gradient(circle at top right, rgba(203, 75, 22, 0.14), transparent 22rem),
        linear-gradient(180deg, #001f27 0%, var(--bg) 38%, #001820 100%);
      min-height: 100vh;
      overflow-x: hidden;
      -webkit-tap-highlight-color: rgba(42, 161, 152, 0.2);
    }
    a, button, input { font: inherit; }
    .skip-link {
      position: absolute;
      left: 1rem;
      top: -3rem;
      padding: 0.7rem 0.95rem;
      border-radius: 0.8rem;
      background: var(--panel-strong);
      color: var(--ink);
      border: 1px solid var(--border);
      z-index: 30;
      text-decoration: none;
      transition: top .18s ease;
    }
    .skip-link:focus-visible {
      top: 1rem;
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .shell {
      width: min(1240px, calc(100vw - 2rem));
      margin: 0 auto;
      padding: max(2rem, env(safe-area-inset-top)) 0 max(3rem, env(safe-area-inset-bottom));
    }
    .hero {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: end;
      margin-bottom: 1.5rem;
    }
    h1 {
      margin: 0;
      font-size: clamp(2rem, 4vw, 3.4rem);
      font-weight: 700;
      letter-spacing: -0.03em;
      text-wrap: balance;
    }
    .sub {
      color: var(--muted);
      max-width: 40rem;
      line-height: 1.45;
      max-width: 44rem;
    }
    .meta {
      text-align: right;
      color: var(--muted);
      font-size: 0.95rem;
      font-variant-numeric: tabular-nums;
    }
    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 0.9rem;
      margin-bottom: 1.25rem;
    }
    .toolbar {
      display: flex;
      justify-content: flex-end;
      margin-bottom: 1rem;
    }
    .view-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.35rem;
      padding: 0.35rem;
      border-radius: 999px;
      border: 1px solid var(--border);
      background: rgba(7, 54, 66, 0.72);
      box-shadow: var(--shadow);
    }
    .view-toggle-label {
      color: var(--muted);
      font-size: 0.82rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      padding: 0 0.45rem 0 0.3rem;
    }
    .view-toggle button {
      border: 0;
      background: transparent;
      color: var(--muted);
      border-radius: 999px;
      padding: 0.45rem 0.8rem;
      cursor: pointer;
      transition: background-color .18s ease, color .18s ease;
    }
    .view-toggle button[aria-pressed="true"] {
      background: var(--accent-soft);
      color: #d8fff9;
    }
    .view-toggle button:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 2px;
    }
    .banner {
      display: none;
      margin-bottom: 1rem;
      padding: 0.9rem 1rem;
      background: var(--danger-soft);
      border: 1px solid rgba(220, 50, 47, 0.28);
      color: var(--danger);
      border-radius: 1rem;
      box-shadow: var(--shadow);
    }
    .banner.visible {
      display: block;
    }
    .summary-card, .card, .drawer-panel {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 1.1rem;
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }
    .summary-card {
      padding: 1rem 1.1rem;
      background:
        linear-gradient(180deg, rgba(42, 161, 152, 0.08), transparent 70%),
        var(--panel);
    }
    .summary-label {
      color: var(--muted);
      font-size: 0.84rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }
    .summary-value {
      margin-top: 0.35rem;
      font-size: 1.5rem;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 1rem;
    }
    .card {
      padding: 1.05rem 1.1rem 1rem;
      position: relative;
      overflow: hidden;
      cursor: pointer;
      text-align: left;
      width: 100%;
      color: inherit;
      appearance: none;
      border: 1px solid var(--border);
      background:
        linear-gradient(180deg, rgba(131, 148, 150, 0.06), transparent 35%),
        var(--panel);
      transition: transform .18s ease, box-shadow .18s ease, border-color .18s ease;
      touch-action: manipulation;
    }
    .card-button {
      display: block;
      width: 100%;
      padding: 0;
      margin: 0;
      border: 0;
      background: transparent;
      text-align: left;
      color: inherit;
      font: inherit;
      cursor: pointer;
    }
    .card:hover {
      transform: translateY(-2px);
      box-shadow: 0 28px 56px rgba(0, 18, 24, 0.52);
      border-color: rgba(42, 161, 152, 0.42);
    }
    .card:focus-within {
      border-color: rgba(42, 161, 152, 0.56);
      box-shadow: 0 0 0 1px rgba(42, 161, 152, 0.26), 0 28px 56px rgba(0, 18, 24, 0.52);
    }
    .card-button:focus-visible, .drawer-close:focus-visible, .logs-toggle input:focus-visible {
      outline: 2px solid var(--focus);
      outline-offset: 3px;
    }
    .card::before {
      content: "";
      position: absolute;
      inset: 0 0 auto;
      height: 0.35rem;
      background: linear-gradient(90deg, rgba(42, 161, 152, 0.92), rgba(181, 137, 0, 0.74), rgba(203, 75, 22, 0.85));
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      gap: 1rem;
      align-items: start;
      margin-bottom: 0.8rem;
      padding-top: 0.25rem;
    }
    .card-layout {
      display: block;
    }
    .card-primary, .card-secondary {
      min-width: 0;
    }
    .title {
      font-size: 1.35rem;
      font-weight: 700;
      line-height: 1.1;
      margin: 0;
      text-wrap: balance;
    }
    .subtitle {
      color: var(--muted);
      margin-top: 0.25rem;
      font-size: 0.95rem;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 0.35rem;
      justify-content: end;
    }
    .badge {
      border-radius: 999px;
      padding: 0.3rem 0.6rem;
      font-size: 0.76rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      border: 1px solid transparent;
      font-family: "SFMono-Regular", "Menlo", monospace;
    }
    .badge.ok { background: var(--ok-soft); color: #b7c66d; border-color: rgba(133,153,0,.28); }
    .badge.warn { background: var(--warn-soft); color: #e6d58b; border-color: rgba(181,137,0,.28); }
    .badge.danger { background: var(--danger-soft); color: #ff918b; border-color: rgba(220,50,47,.28); }
    .badge.info { background: var(--accent-soft); color: #7bd6cf; border-color: rgba(42,161,152,.28); }
    dl {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 0.45rem 0.8rem;
      margin: 0;
      font-size: 0.95rem;
    }
    dt { color: var(--muted); }
    dd { margin: 0; min-width: 0; text-align: right; font-family: "SFMono-Regular", "Menlo", monospace; font-size: 0.88rem; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .section {
      border-top: 1px solid var(--border);
      margin-top: 0.85rem;
      padding-top: 0.75rem;
    }
    .section h2 {
      margin: 0 0 0.55rem;
      font-size: 0.95rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }
    .empty {
      padding: 2rem;
      text-align: center;
      color: var(--muted);
    }
    .grid[data-view="horizontal"] {
      grid-template-columns: 1fr;
    }
    .grid[data-view="horizontal"] .card-layout {
      display: grid;
      grid-template-columns: minmax(0, 1.25fr) minmax(280px, 0.95fr);
      gap: 1rem 1.25rem;
      align-items: start;
    }
    .grid[data-view="horizontal"] .card-secondary .section:first-child,
    .grid[data-view="horizontal"] .card-secondary:empty {
      margin-top: 0;
      padding-top: 0;
      border-top: 0;
    }
    .grid[data-view="horizontal"] .card-secondary {
      display: flex;
      flex-direction: column;
      gap: 0.85rem;
    }
    .grid[data-view="horizontal"] .card-secondary .section {
      margin-top: 0;
    }
    .drawer {
      position: fixed;
      inset: 0;
      display: none;
      background: rgba(0, 18, 24, 0.58);
      backdrop-filter: blur(8px);
      padding:
        max(1rem, env(safe-area-inset-top))
        max(1rem, env(safe-area-inset-right))
        max(1rem, env(safe-area-inset-bottom))
        max(1rem, env(safe-area-inset-left));
      z-index: 20;
      overscroll-behavior: contain;
    }
    .drawer.open {
      display: flex;
      align-items: stretch;
      justify-content: end;
    }
    .drawer-panel {
      width: min(920px, 100%);
      height: 100%;
      overflow: auto;
      padding: 1.2rem;
      position: relative;
      overscroll-behavior: contain;
      background:
        linear-gradient(180deg, rgba(42, 161, 152, 0.08), transparent 20%),
        linear-gradient(180deg, rgba(12, 54, 66, 0.98), rgba(6, 43, 54, 0.98));
    }
    .drawer-header {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 1rem;
      margin-bottom: 1rem;
    }
    .drawer-header h2 {
      margin: 0;
      font-size: 2rem;
      letter-spacing: -0.03em;
    }
    .drawer-close {
      border: 1px solid var(--border);
      background: rgba(7, 54, 66, 0.9);
      color: var(--ink);
      border-radius: 999px;
      width: 2.2rem;
      height: 2.2rem;
      font-size: 1.2rem;
      cursor: pointer;
      transition: background-color .18s ease, border-color .18s ease;
      touch-action: manipulation;
    }
    .drawer-close:hover {
      background: rgba(12, 72, 87, 0.95);
      border-color: rgba(42, 161, 152, 0.35);
    }
    .drawer-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 0.85rem;
      margin-bottom: 1rem;
    }
    .drawer-card {
      background:
        linear-gradient(180deg, rgba(131, 148, 150, 0.06), transparent 35%),
        rgba(0, 43, 54, 0.44);
      border: 1px solid var(--border);
      border-radius: 0.9rem;
      padding: 0.9rem;
    }
    .drawer-card h3 {
      margin: 0 0 0.55rem;
      font-size: 0.88rem;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: var(--muted);
    }
    .drawer-card dl {
      grid-template-columns: minmax(7.5rem, max-content) minmax(0, 1fr);
      align-items: start;
    }
    .drawer-card dd {
      min-width: 0;
      text-align: left;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    .section-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 1rem;
      margin-bottom: 0.55rem;
    }
    .section-header h2 {
      margin-bottom: 0;
    }
    .logs-toggle {
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      color: var(--muted);
      font-size: 0.9rem;
      font-family: "SFMono-Regular", "Menlo", monospace;
      user-select: none;
    }
    .logs-toggle input {
      margin: 0;
      accent-color: var(--accent);
    }
    .logs {
      background: #001d26;
      color: #eee8d5;
      border-radius: 0.95rem;
      padding: 0.9rem;
      font-family: "SFMono-Regular", "Menlo", monospace;
      font-size: 0.83rem;
      line-height: 1.45;
      white-space: pre-wrap;
      min-height: 18rem;
      max-height: 28rem;
      overflow: auto;
      overscroll-behavior: contain;
      border: 1px solid rgba(42, 161, 152, 0.14);
      font-variant-numeric: tabular-nums;
    }
    .drawer-meta {
      color: var(--muted);
      font-size: 0.95rem;
      font-variant-numeric: tabular-nums;
    }
    .mono {
      font-family: "SFMono-Regular", "Menlo", monospace;
      word-break: break-word;
    }
    @media (prefers-reduced-motion: reduce) {
      .skip-link, .card, .drawer-close, .view-toggle button {
        transition: none;
      }
      .drawer {
        backdrop-filter: none;
      }
      .card:hover {
        transform: none;
      }
    }
    @media (max-width: 680px) {
      .hero { flex-direction: column; align-items: start; }
      .meta { text-align: left; }
      dd { text-align: left; }
      dl { grid-template-columns: 1fr; }
      .section-header { align-items: start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#main-content">Skip To Main Content</a>
  <main class="shell" id="main-content">
    <section class="hero">
      <div>
        <h1>Gravity Bot Dashboard</h1>
        <div class="sub">Read-only local monitor for running GRVT bot containers. It reads Docker metadata, mounted config files, and state snapshots without talking to the exchange.</div>
      </div>
      <div class="meta">
        <div id="updated">Loading page…</div>
        <div>Refreshes every 10 seconds</div>
      </div>
    </section>
    <section class="banner" id="banner" aria-live="polite"></section>
    <section class="summary" id="summary"></section>
    <section class="toolbar" aria-label="Dashboard view options">
      <div class="view-toggle">
        <span class="view-toggle-label">View</span>
        <button id="view-vertical" type="button" data-view="vertical" aria-pressed="true">Vertical</button>
        <button id="view-horizontal" type="button" data-view="horizontal" aria-pressed="false">Horizontal</button>
      </div>
    </section>
    <section class="grid" id="cards" data-view="vertical"></section>
  </main>
  <aside class="drawer" id="drawer" role="dialog" aria-modal="true" aria-labelledby="drawer-title" aria-describedby="drawer-subtitle" aria-hidden="true">
    <section class="drawer-panel" tabindex="-1">
      <div class="drawer-header">
        <div>
          <h2 id="drawer-title">Bot details</h2>
          <div class="drawer-meta" id="drawer-subtitle"></div>
        </div>
        <button class="drawer-close" id="drawer-close" type="button" aria-label="Close">×</button>
      </div>
      <section class="drawer-grid" id="drawer-grid"></section>
      <section class="section" style="margin-top:0;padding-top:0;border-top:0">
        <div class="section-header">
          <h2>Live Logs</h2>
          <label class="logs-toggle" for="drawer-autoscroll">
            <input id="drawer-autoscroll" type="checkbox" checked>
            Auto-scroll
          </label>
        </div>
        <div class="logs" id="drawer-logs">Loading…</div>
      </section>
    </section>
  </aside>
  <script>
    var selectedBot = null;
    var focusLogsOnDrawerOpen = false;
    var selectedView = loadViewMode();
    var latestBots = [];
    var lastFocusedTrigger = null;
    var dateTimeFormatter = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short"
    });
    function clientLog(message) {
      var img = new Image();
      img.src = "/api/client-log?message=" + encodeURIComponent(message);
    }
    function safeValue(value) {
      if (value === null || value === undefined) return "";
      return String(value);
    }
    function esc(value) {
      return safeValue(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    }
    function badgeClass(kind) {
      if (kind === "running" || kind === "active") return "ok";
      if (kind === "inactive-max-cycles" || kind === "paused" || kind === "risk-reduce-only") return "warn";
      if (kind === "missing-state" || kind === "exited" || kind === "error") return "danger";
      return "info";
    }
    function field(label, value) {
      return '<dt>' + esc(label) + '</dt><dd>' + esc(value) + '</dd>';
    }
    function summaryCard(label, value) {
      return '<article class="summary-card"><div class="summary-label">' + esc(label) + '</div><div class="summary-value">' + esc(value) + '</div></article>';
    }
    function showBanner(message) {
      var banner = document.getElementById("banner");
      if (message) {
        banner.textContent = message;
        banner.classList.add("visible");
      } else {
        banner.textContent = "";
        banner.classList.remove("visible");
      }
    }
    function normalizeViewMode(value) {
      return value === "horizontal" ? "horizontal" : "vertical";
    }
    function currentUrl() {
      return new URL(window.location.href);
    }
    function readStateFromUrl() {
      var url = currentUrl();
      var viewParam = url.searchParams.get("view");
      return {
        view: viewParam ? normalizeViewMode(viewParam) : null,
        bot: url.searchParams.get("bot") || null
      };
    }
    function syncUrlState() {
      var url = currentUrl();
      url.searchParams.set("view", selectedView);
      if (selectedBot) {
        url.searchParams.set("bot", selectedBot);
      } else {
        url.searchParams.delete("bot");
      }
      window.history.replaceState(null, "", url.toString());
    }
    function loadViewMode() {
      var state = readStateFromUrl();
      if (state.view) return state.view;
      try {
        return normalizeViewMode(window.localStorage.getItem("gravity-dashboard-view"));
      } catch (error) {
        return "vertical";
      }
    }
    function formatDateTime(value) {
      if (!value) return "";
      var parsed = new Date(value);
      if (Number.isNaN(parsed.getTime())) return value;
      return dateTimeFormatter.format(parsed);
    }
    function applyViewMode(view) {
      selectedView = normalizeViewMode(view);
      document.getElementById("cards").setAttribute("data-view", selectedView);
      document.getElementById("view-vertical").setAttribute("aria-pressed", selectedView === "vertical" ? "true" : "false");
      document.getElementById("view-horizontal").setAttribute("aria-pressed", selectedView === "horizontal" ? "true" : "false");
      try {
        window.localStorage.setItem("gravity-dashboard-view", selectedView);
      } catch (error) {}
      syncUrlState();
      renderCards(latestBots);
    }
    function bindCardHandlers() {
      Array.prototype.forEach.call(document.querySelectorAll(".card-button[data-container]"), function(card) {
        card.addEventListener("click", function() { openDrawer(card.getAttribute("data-container"), card); });
      });
    }
    function renderCards(bots, errorMessage) {
      latestBots = bots || [];
      document.getElementById("cards").innerHTML = latestBots.length
        ? latestBots.map(renderBot).join('')
        : '<section class="card empty">' + (errorMessage ? 'Dashboard could not inspect Docker right now.' : 'No running bot containers detected.') + '</section>';
      bindCardHandlers();
    }
    function renderHorizontalBot(bot, statusBadges) {
      var primaryStats;
      if (bot.strategy_type === "momentum") {
        primaryStats = bot.active_trade
          ? '<dl>'
              + '<dt>Avg entry</dt><dd>' + esc(bot.active_trade.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_trade.total_quantity) + '</dd>'
              + '<dt>Trailing stop</dt><dd>' + esc(bot.thresholds.trailing_stop_price || bot.thresholds.stop_loss_price) + '</dd>'
              + '<dt>Take profit</dt><dd>' + esc(bot.thresholds.fixed_take_profit_price || bot.thresholds.take_profit_price) + '</dd>'
            + '</dl>'
          : '<dl>'
              + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
              + '<dt>Max cycles</dt><dd>' + esc(bot.max_cycles) + '</dd>'
              + '<dt>Timeframe</dt><dd>' + esc(bot.timeframe) + '</dd>'
              + '<dt>Dry run</dt><dd>' + (bot.dry_run ? 'true' : 'false') + '</dd>'
            + '</dl>';
      } else if (bot.strategy_type === "grid") {
        primaryStats = '<dl>'
            + '<dt>Band</dt><dd>' + esc(bot.price_band_low) + ' - ' + esc(bot.price_band_high) + '</dd>'
            + '<dt>Grid levels</dt><dd>' + esc(bot.grid_levels) + '</dd>'
            + '<dt>Open buys</dt><dd>' + esc(bot.active_trade ? bot.active_trade.active_buy_orders : 0) + '</dd>'
            + '<dt>Inventory</dt><dd>' + esc(bot.active_trade ? bot.active_trade.active_inventory_levels : 0) + '</dd>'
          + '</dl>';
      } else {
        primaryStats = bot.active_trade
          ? '<dl>'
              + '<dt>Avg entry</dt><dd>' + esc(bot.active_trade.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_trade.total_quantity) + '</dd>'
              + '<dt>Next trigger</dt><dd>' + esc(bot.thresholds.next_safety_trigger_price) + '</dd>'
              + '<dt>Take profit</dt><dd>' + esc(bot.thresholds.take_profit_price) + '</dd>'
            + '</dl>'
          : '<dl>'
              + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
              + '<dt>Max cycles</dt><dd>' + esc(bot.max_cycles) + '</dd>'
              + '<dt>State</dt><dd>' + esc(bot.lifecycle_state) + '</dd>'
              + '<dt>Dry run</dt><dd>' + (bot.dry_run ? 'true' : 'false') + '</dd>'
            + '</dl>';
      }
      var secondaryStats = '<dl>'
        + '<dt>Leverage</dt><dd>' + esc(bot.initial_leverage) + '</dd>'
        + '<dt>Poll</dt><dd>' + esc(bot.poll_seconds) + 's</dd>'
        + '<dt>Bot API</dt><dd>' + esc(bot.bot_api_port) + '</dd>'
        + '<dt>Telegram</dt><dd>' + (bot.telegram_enabled ? 'enabled' : 'disabled') + '</dd>'
        + '</dl>';
      return '<article class="card">'
        + '<button class="card-button" data-container="' + esc(bot.container_name) + '" type="button" aria-label="Open details for ' + esc(bot.symbol) + '">'
        + '<div class="card-header"><div>'
        + '<h2 class="title">' + esc(bot.symbol) + '</h2>'
        + '<div class="subtitle">' + esc(bot.container_name) + ' • ' + esc(bot.environment) + ' • ' + esc(bot.margin_type) + '</div>'
        + '</div><div class="badges">' + statusBadges + '</div></div>'
        + '<div class="card-layout">'
        + '<div class="card-primary">'
        + '<div class="section" style="margin-top:0;padding-top:0;border-top:0"><h2>' + (bot.active_trade ? (bot.active_trade_kind === "position" ? 'Live Position' : 'Live Cycle') : 'Runtime') + '</h2>' + primaryStats + '</div>'
        + '</div>'
        + '<div class="card-secondary">'
        + '<div class="section" style="margin-top:0;padding-top:0;border-top:0"><h2>Ops</h2>' + secondaryStats + '</div>'
        + '</div>'
        + '</div>'
        + '</button>'
        + '</article>';
    }
    function renderBot(bot) {
      var statusBadges = [
        '<span class="badge ' + badgeClass(bot.container_state) + '">' + esc(bot.container_state) + '</span>',
        '<span class="badge ' + badgeClass(bot.lifecycle_state) + '">' + esc(bot.lifecycle_state) + '</span>',
        '<span class="badge info">' + esc(bot.order_type) + '</span>'
      ].join("");
      if (bot.risk_reduce_only) {
        statusBadges += '<span class="badge ' + badgeClass("risk-reduce-only") + '">risk-reduce-only</span>';
      }
      if (selectedView === "horizontal") {
        return renderHorizontalBot(bot, statusBadges);
      }
      var activeCycle;
      if (bot.strategy_type === "momentum") {
        activeCycle = bot.active_trade
          ? '<dl>'
              + '<dt>Average entry</dt><dd>' + esc(bot.active_trade.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_trade.total_quantity) + '</dd>'
              + '<dt>Highest</dt><dd>' + esc(bot.active_trade.highest_price_since_entry) + '</dd>'
              + '<dt>Initial stop</dt><dd>' + esc(bot.thresholds.initial_stop_price) + '</dd>'
              + '<dt>Trailing stop</dt><dd>' + esc(bot.thresholds.trailing_stop_price || bot.thresholds.stop_loss_price) + '</dd>'
              + '<dt>Take profit</dt><dd>' + esc(bot.thresholds.fixed_take_profit_price || bot.thresholds.take_profit_price) + '</dd>'
            + '</dl>'
          : '<dl>'
              + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
              + '<dt>Max cycles</dt><dd>' + esc(bot.max_cycles) + '</dd>'
              + '<dt>Timeframe</dt><dd>' + esc(bot.timeframe) + '</dd>'
              + '<dt>State file</dt><dd class="mono">' + esc(bot.state_file) + '</dd>'
            + '</dl>';
      } else if (bot.strategy_type === "grid") {
        activeCycle = '<dl>'
            + '<dt>Band low</dt><dd>' + esc(bot.price_band_low) + '</dd>'
            + '<dt>Band high</dt><dd>' + esc(bot.price_band_high) + '</dd>'
            + '<dt>Grid levels</dt><dd>' + esc(bot.grid_levels) + '</dd>'
            + '<dt>Spacing</dt><dd>' + esc(bot.spacing_mode) + '</dd>'
            + '<dt>Seed on start</dt><dd>' + (bot.seed_enabled ? 'true' : 'false') + '</dd>'
            + '<dt>Open buys</dt><dd>' + esc(bot.active_trade ? bot.active_trade.active_buy_orders : 0) + '</dd>'
            + '<dt>Inventory</dt><dd>' + esc(bot.active_trade ? bot.active_trade.active_inventory_levels : 0) + '</dd>'
            + '<dt>Round trips</dt><dd>' + esc(bot.completed_round_trips || bot.completed_cycles) + '</dd>'
            + '<dt>State file</dt><dd class="mono">' + esc(bot.state_file) + '</dd>'
          + '</dl>';
      } else {
        activeCycle = bot.active_trade
          ? '<dl>'
              + '<dt>Average entry</dt><dd>' + esc(bot.active_trade.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_trade.total_quantity) + '</dd>'
              + '<dt>Safety orders</dt><dd>' + esc(bot.active_trade.completed_safety_orders) + '</dd>'
              + '<dt>Take profit</dt><dd>' + esc(bot.thresholds.take_profit_price) + '</dd>'
              + '<dt>Stop loss</dt><dd>' + esc(bot.thresholds.stop_loss_price) + '</dd>'
              + '<dt>Next trigger</dt><dd>' + esc(bot.thresholds.next_safety_trigger_price) + '</dd>'
            + '</dl>'
          : '<dl>'
              + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
              + '<dt>Max cycles</dt><dd>' + esc(bot.max_cycles) + '</dd>'
              + '<dt>State file</dt><dd class="mono">' + esc(bot.state_file) + '</dd>'
            + '</dl>';
      }
      var closedCycle = bot.last_closed_trade
        ? '<div class="section"><h2>Last Closed</h2><dl>'
            + '<dt>Reason</dt><dd>' + esc(bot.last_closed_trade.exit_reason) + '</dd>'
            + '<dt>Exit price</dt><dd>' + esc(bot.last_closed_trade.exit_price) + '</dd>'
            + '<dt>PnL est.</dt><dd>' + esc(bot.last_closed_trade.realized_pnl_estimate) + '</dd>'
          + '</dl></div>'
        : "";
      var logSection = (bot.last_log_line || bot.recent_error)
        ? '<div class="section"><h2>Logs</h2>'
            + (bot.recent_error ? '<div class="mono">' + esc(bot.recent_error) + '</div>' : '')
            + (bot.last_log_line ? '<div class="mono" style="margin-top:.45rem">' + esc(bot.last_log_line) + '</div>' : '')
          + '</div>'
        : "";
      return '<article class="card">'
        + '<button class="card-button" data-container="' + esc(bot.container_name) + '" type="button" aria-label="Open details for ' + esc(bot.symbol) + '">'
        + '<div class="card-header"><div>'
        + '<h2 class="title">' + esc(bot.symbol) + '</h2>'
        + '<div class="subtitle">' + esc(bot.container_name) + ' • ' + esc(bot.environment) + ' • ' + esc(bot.margin_type) + '</div>'
        + '</div><div class="badges">' + statusBadges + '</div></div>'
        + '<div class="card-layout">'
        + '<div class="card-primary">'
        + '<dl>'
        + '<dt>Config</dt><dd class="mono">' + esc(bot.config_file) + '</dd>'
        + '<dt>State file</dt><dd class="mono">' + esc(bot.state_file) + '</dd>'
        + '<dt>Dry run</dt><dd>' + (bot.dry_run ? 'true' : 'false') + '</dd>'
        + '<dt>Leverage</dt><dd>' + esc(bot.initial_leverage) + '</dd>'
        + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
        + '<dt>Poll seconds</dt><dd>' + esc(bot.poll_seconds) + '</dd>'
        + '</dl>'
        + '<div class="section"><h2>' + (bot.active_trade ? (bot.strategy_type === "momentum" ? 'Active Position' : (bot.strategy_type === "grid" ? 'Grid Runtime' : 'Active Cycle')) : 'Idle State') + '</h2>' + activeCycle + '</div>'
        + '</div>'
        + '<div class="card-secondary">'
        + closedCycle
        + logSection
        + '</div>'
        + '</div>'
        + '</button>'
        + '</article>';
    }
    function renderDrawerSection(title, rows) {
      return '<article class="drawer-card"><h3>' + esc(title) + '</h3><dl>' + rows.join('') + '</dl></article>';
    }
    function openDrawer(containerName, triggerElement) {
      selectedBot = containerName;
      focusLogsOnDrawerOpen = true;
      lastFocusedTrigger = triggerElement || document.activeElement;
      document.getElementById("drawer").classList.add("open");
      document.getElementById("drawer").setAttribute("aria-hidden", "false");
      document.querySelector(".drawer-panel").focus();
      syncUrlState();
      refreshDrawer();
    }
    function closeDrawer() {
      selectedBot = null;
      focusLogsOnDrawerOpen = false;
      document.getElementById("drawer").classList.remove("open");
      document.getElementById("drawer").setAttribute("aria-hidden", "true");
      syncUrlState();
      if (lastFocusedTrigger && typeof lastFocusedTrigger.focus === "function") {
        lastFocusedTrigger.focus();
      }
    }
    function shouldAutoScrollLogs() {
      var toggle = document.getElementById("drawer-autoscroll");
      return !!(toggle && toggle.checked);
    }
    function refreshDrawer() {
      if (!selectedBot) return;
      fetch("/api/bots/" + encodeURIComponent(selectedBot))
        .then(function(detailResponse) {
          if (!detailResponse.ok) return null;
          return detailResponse.json();
        })
        .then(function(bot) {
          if (!bot) return;
          var strategyRows = bot.strategy_type === "momentum"
            ? [
                field("Quote amount", bot.initial_quote_amount),
                field("Timeframe", bot.timeframe),
                field("EMA fast", bot.ema_fast_period),
                field("EMA slow", bot.ema_slow_period),
                field("Breakout lookback", bot.breakout_lookback),
                field("Min ADX", bot.min_adx),
                field("Min ATR %", bot.min_atr_percent),
                field("TP %", bot.take_profit_percent)
              ]
            : bot.strategy_type === "grid"
            ? [
                field("Band low", bot.price_band_low),
                field("Band high", bot.price_band_high),
                field("Grid levels", bot.grid_levels),
                field("Spacing", bot.spacing_mode),
                field("Quote / level", bot.quote_amount_per_level || bot.initial_quote_amount),
                field("Max open buys", bot.max_active_buy_orders),
                field("Max inventory", bot.max_inventory_levels),
                field("Seed on start", bot.seed_enabled ? "true" : "false")
              ]
            : [
                field("Initial quote", bot.initial_quote_amount),
                field("Safety quote", bot.safety_order_quote_amount),
                field("Max safety", bot.max_safety_orders),
                field("Deviation %", bot.price_deviation_percent),
                field("TP %", bot.take_profit_percent),
                field("SL %", bot.stop_loss_percent)
              ];
          var strategyStatusRows = [];
          var signalInfoRows = [
            field("Detail source", bot.detail_source),
            field("Signal status", bot.signal_status),
            field("Signal source", bot.signal_source),
            field("Signal note", bot.signal_note)
          ];
          if (bot.strategy_type === "momentum" && bot.strategy_status) {
            if (bot.strategy_status.mode === "entry") {
              strategyStatusRows = [
                field("Entry decision", bot.strategy_status.entry_decision),
                field("Entry reason", bot.strategy_status.entry_reason),
                field("Latest close", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.latest_close),
                field("Breakout level", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.breakout_level),
                field("EMA fast", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.ema_fast),
                field("EMA slow", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.ema_slow),
                field("ADX", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.adx),
                field("ATR", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.atr),
                field("ATR %", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.atr_percent),
                field("Initial stop", bot.strategy_status.initial_stop_price),
                field("Trailing stop", bot.strategy_status.trailing_stop_price)
              ];
            } else if (bot.strategy_status.mode === "position") {
              strategyStatusRows = [
                field("Exit decision", bot.strategy_status.exit_decision),
                field("Exit reason", bot.strategy_status.exit_reason),
                field("Latest close", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.latest_close),
                field("Breakout level", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.breakout_level),
                field("EMA fast", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.ema_fast),
                field("EMA slow", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.ema_slow),
                field("ADX", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.adx),
                field("ATR", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.atr),
                field("ATR %", bot.strategy_status.indicator_snapshot && bot.strategy_status.indicator_snapshot.atr_percent),
                field("Stop price", bot.strategy_status.stop_price),
                field("Trailing stop", bot.strategy_status.trailing_stop_price),
                field("Highest", bot.strategy_status.highest_price_since_entry)
              ];
            }
          }
          var sections = [
            renderDrawerSection("Container", [
              field("Image", bot.image),
              field("Config", bot.config_file),
              field("State file", bot.state_file),
              field("Dry run", bot.dry_run ? "true" : "false"),
              field("Order type", bot.order_type)
            ]),
            renderDrawerSection("Strategy", strategyRows),
            renderDrawerSection("Runtime", [
              field("Leverage", bot.initial_leverage),
              field("Margin type", bot.margin_type),
              field("Poll seconds", bot.poll_seconds),
              field("Bot API port", bot.bot_api_port),
              field("Risk reduce-only", bot.risk_reduce_only ? "true" : "false"),
              field("Restriction", bot.risk_reduce_only_reason),
              field("Completed cycles", bot.completed_cycles),
              field("Max cycles", bot.max_cycles),
              field("Telegram", bot.telegram_enabled ? "enabled" : "disabled")
            ])
          ];
          if (strategyStatusRows.length) {
            sections.push(renderDrawerSection("Signals", strategyStatusRows));
          } else if (bot.strategy_type === "momentum") {
            sections.push(renderDrawerSection("Signals", signalInfoRows));
          }
          if (bot.strategy_type !== "momentum") {
            sections.push(renderDrawerSection("Data source", signalInfoRows.slice(0, 2)));
          }
          document.getElementById("drawer-title").textContent = bot.symbol;
          document.getElementById("drawer-subtitle").textContent = bot.container_name + " • " + bot.environment + " • " + bot.container_state + " • " + bot.lifecycle_state;
          if (bot.active_trade) {
            sections.push(renderDrawerSection(bot.active_trade_kind === 'position' ? "Active position" : (bot.strategy_type === "grid" ? "Grid runtime" : "Active cycle"), bot.strategy_type === "momentum"
              ? [
                  field("Started at", formatDateTime(bot.active_trade.started_at)),
                  field("Side", bot.active_trade.side),
                  field("Average entry", bot.active_trade.average_entry_price),
                  field("Quantity", bot.active_trade.total_quantity),
                  field("Highest", bot.active_trade.highest_price_since_entry),
                  field("Initial stop", bot.thresholds.initial_stop_price),
                  field("Trailing stop", bot.thresholds.trailing_stop_price || bot.thresholds.stop_loss_price),
                  field("Take profit", bot.thresholds.fixed_take_profit_price || bot.thresholds.take_profit_price),
                  field("Breakout level", bot.active_trade.breakout_level),
                  field("Timeframe", bot.active_trade.timeframe),
                  field("Last order id", bot.active_trade.last_order_id),
                  field("Last client id", bot.active_trade.last_client_order_id)
                ]
              : bot.strategy_type === "grid"
              ? [
                  field("Started at", formatDateTime(bot.active_trade.started_at)),
                  field("Open buy orders", bot.active_trade.active_buy_orders),
                  field("Inventory levels", bot.active_trade.active_inventory_levels),
                  field("Round trips", bot.active_trade.completed_round_trips),
                  field("Last reconciled", formatDateTime(bot.active_trade.last_reconciled_at))
                ]
              : [
                  field("Started at", formatDateTime(bot.active_trade.started_at)),
                  field("Side", bot.active_trade.side),
                  field("Average entry", bot.active_trade.average_entry_price),
                  field("Quantity", bot.active_trade.total_quantity),
                  field("Completed safety", bot.active_trade.completed_safety_orders),
                  field("Last order id", bot.active_trade.last_order_id),
                  field("Last client id", bot.active_trade.last_client_order_id),
                  field("Take profit", bot.thresholds.take_profit_price),
                  field("Stop loss", bot.thresholds.stop_loss_price),
                  field("Next trigger", bot.thresholds.next_safety_trigger_price)
                ]
            ));
          }
          if (bot.strategy_type === "grid" && bot.levels && bot.levels.length) {
            sections.push(renderDrawerSection("Grid levels", bot.levels.map(function(level) {
              var text = [level.price, level.status];
              if (level.entry_quantity) text.push('qty=' + level.entry_quantity);
              if (level.entry_fill_price) text.push('entry=' + level.entry_fill_price);
              if (level.exit_fill_price) text.push('exit=' + level.exit_fill_price);
              return field('Level ' + level.level_index, text.join(' • '));
            })));
          }
          if (bot.last_closed_trade) {
            sections.push(renderDrawerSection(bot.last_closed_trade_kind === 'position' ? "Last closed position" : "Last closed cycle", [
              field("Closed at", formatDateTime(bot.last_closed_trade.closed_at)),
              field("Reason", bot.last_closed_trade.exit_reason),
              field("Exit price", bot.last_closed_trade.exit_price),
              field("PnL est.", bot.last_closed_trade.realized_pnl_estimate)
            ]));
          }
          document.getElementById("drawer-grid").innerHTML = sections.join("");
          return fetch("/api/bots/" + encodeURIComponent(selectedBot) + "/logs?tail=200");
        })
        .then(function(logsResponse) {
          if (!logsResponse || !logsResponse.ok) return null;
          return logsResponse.json();
        })
        .then(function(logs) {
          if (!logs) return;
          var logsElement = document.getElementById("drawer-logs");
          logsElement.textContent = (logs.lines || []).join("\\n") || "No recent logs.";
          if (focusLogsOnDrawerOpen) {
            logsElement.scrollIntoView({ block: "end" });
            focusLogsOnDrawerOpen = false;
          }
          if (shouldAutoScrollLogs()) {
            logsElement.scrollTop = logsElement.scrollHeight;
          }
        })
        .catch(function(error) {
          showBanner("Drawer refresh failed: " + error);
        });
    }
    function refresh() {
      clientLog("refresh-start");
      fetch("/api/bots")
        .then(function(response) { return response.json(); })
        .then(function(payload) {
          clientLog("refresh-success");
          showBanner(payload.error || "");
          document.getElementById('updated').textContent = 'Updated ' + formatDateTime(payload.generated_at);
          document.getElementById("summary").innerHTML = [
            summaryCard('Containers', payload.summary.total_containers),
            summaryCard('Active cycles', payload.summary.active_cycles),
            summaryCard('Inactive maxed', payload.summary.inactive_max_cycles),
            summaryCard('Errors', payload.summary.containers_with_errors)
          ].join('');
          applyViewMode(selectedView);
          renderCards(payload.bots, payload.error);
          if (selectedBot) {
            refreshDrawer();
          }
        })
        .catch(function(error) {
          clientLog("refresh-fail:" + error);
          showBanner("Dashboard refresh failed: " + error);
          document.getElementById('cards').innerHTML = '<section class="card empty">Dashboard refresh failed.</section>';
        });
    }
    window.onerror = function(message, source, lineno, colno) {
      clientLog("window-error:" + message + "@" + lineno + ":" + colno);
    };
    document.getElementById("drawer-close").addEventListener("click", closeDrawer);
    Array.prototype.forEach.call(document.querySelectorAll(".view-toggle button[data-view]"), function(button) {
      button.addEventListener("click", function() {
        applyViewMode(button.getAttribute("data-view"));
      });
    });
    document.addEventListener("keydown", function(event) {
      if (event.key === "Escape" && selectedBot) {
        closeDrawer();
      }
    });
    document.getElementById("drawer").addEventListener("click", function(event) {
      if (event.target.id === "drawer") closeDrawer();
    });
    clientLog("script-start");
    document.getElementById("updated").textContent = "Script started";
    applyViewMode(selectedView);
    var initialState = readStateFromUrl();
    if (initialState.bot) {
      selectedBot = initialState.bot;
      document.getElementById("drawer").classList.add("open");
      document.getElementById("drawer").setAttribute("aria-hidden", "false");
    }
    refresh();
    setInterval(refresh, 10000);
    setInterval(refreshDrawer, 4000);
  </script>
</body>
</html>"""
