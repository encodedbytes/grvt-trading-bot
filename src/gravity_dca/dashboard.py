from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import http.client
import io
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tarfile
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse

from .config import AppConfig, load_config, load_config_text
from .momentum_state import MomentumBotState, load_momentum_state, load_momentum_state_text
from .state import BotState, load_state, load_state_text
from .status_snapshot import build_status_snapshot, new_runtime_status


UTC = timezone.utc
LOGGER = logging.getLogger("gravity_dca.dashboard")
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
        primaryStats = bot.active_cycle
          ? '<dl>'
              + '<dt>Avg entry</dt><dd>' + esc(bot.active_cycle.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_cycle.total_quantity) + '</dd>'
              + '<dt>Trailing stop</dt><dd>' + esc(bot.thresholds.trailing_stop_price || bot.thresholds.stop_loss_price) + '</dd>'
              + '<dt>Take profit</dt><dd>' + esc(bot.thresholds.fixed_take_profit_price || bot.thresholds.take_profit_price) + '</dd>'
            + '</dl>'
          : '<dl>'
              + '<dt>Completed cycles</dt><dd>' + esc(bot.completed_cycles) + '</dd>'
              + '<dt>Max cycles</dt><dd>' + esc(bot.max_cycles) + '</dd>'
              + '<dt>Timeframe</dt><dd>' + esc(bot.timeframe) + '</dd>'
              + '<dt>Dry run</dt><dd>' + (bot.dry_run ? 'true' : 'false') + '</dd>'
            + '</dl>';
      } else {
        primaryStats = bot.active_cycle
          ? '<dl>'
              + '<dt>Avg entry</dt><dd>' + esc(bot.active_cycle.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_cycle.total_quantity) + '</dd>'
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
        + '<div class="section" style="margin-top:0;padding-top:0;border-top:0"><h2>' + (bot.active_cycle ? 'Live Cycle' : 'Runtime') + '</h2>' + primaryStats + '</div>'
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
        activeCycle = bot.active_cycle
          ? '<dl>'
              + '<dt>Average entry</dt><dd>' + esc(bot.active_cycle.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_cycle.total_quantity) + '</dd>'
              + '<dt>Highest</dt><dd>' + esc(bot.active_cycle.highest_price_since_entry) + '</dd>'
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
      } else {
        activeCycle = bot.active_cycle
          ? '<dl>'
              + '<dt>Average entry</dt><dd>' + esc(bot.active_cycle.average_entry_price) + '</dd>'
              + '<dt>Quantity</dt><dd>' + esc(bot.active_cycle.total_quantity) + '</dd>'
              + '<dt>Safety orders</dt><dd>' + esc(bot.active_cycle.completed_safety_orders) + '</dd>'
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
      var closedCycle = bot.last_closed_cycle
        ? '<div class="section"><h2>Last Closed</h2><dl>'
            + '<dt>Reason</dt><dd>' + esc(bot.last_closed_cycle.exit_reason) + '</dd>'
            + '<dt>Exit price</dt><dd>' + esc(bot.last_closed_cycle.exit_price) + '</dd>'
            + '<dt>PnL est.</dt><dd>' + esc(bot.last_closed_cycle.realized_pnl_estimate) + '</dd>'
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
        + '<div class="section"><h2>' + (bot.active_cycle ? (bot.strategy_type === "momentum" ? 'Active Position' : 'Active Cycle') : 'Idle State') + '</h2>' + activeCycle + '</div>'
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
            : [
                field("Initial quote", bot.initial_quote_amount),
                field("Safety quote", bot.safety_order_quote_amount),
                field("Max safety", bot.max_safety_orders),
                field("Deviation %", bot.price_deviation_percent),
                field("TP %", bot.take_profit_percent),
                field("SL %", bot.stop_loss_percent)
              ];
          var strategyStatusRows = [];
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
          }
          document.getElementById("drawer-title").textContent = bot.symbol;
          document.getElementById("drawer-subtitle").textContent = bot.container_name + " • " + bot.environment + " • " + bot.container_state + " • " + bot.lifecycle_state;
          if (bot.active_cycle) {
            sections.push(renderDrawerSection(bot.strategy_type === "momentum" ? "Active position" : "Active cycle", bot.strategy_type === "momentum"
              ? [
                  field("Started at", formatDateTime(bot.active_cycle.started_at)),
                  field("Side", bot.active_cycle.side),
                  field("Average entry", bot.active_cycle.average_entry_price),
                  field("Quantity", bot.active_cycle.total_quantity),
                  field("Highest", bot.active_cycle.highest_price_since_entry),
                  field("Initial stop", bot.thresholds.initial_stop_price),
                  field("Trailing stop", bot.thresholds.trailing_stop_price || bot.thresholds.stop_loss_price),
                  field("Take profit", bot.thresholds.fixed_take_profit_price || bot.thresholds.take_profit_price),
                  field("Breakout level", bot.active_cycle.breakout_level),
                  field("Timeframe", bot.active_cycle.timeframe),
                  field("Last order id", bot.active_cycle.last_order_id),
                  field("Last client id", bot.active_cycle.last_client_order_id)
                ]
              : [
                  field("Started at", formatDateTime(bot.active_cycle.started_at)),
                  field("Side", bot.active_cycle.side),
                  field("Average entry", bot.active_cycle.average_entry_price),
                  field("Quantity", bot.active_cycle.total_quantity),
                  field("Completed safety", bot.active_cycle.completed_safety_orders),
                  field("Last order id", bot.active_cycle.last_order_id),
                  field("Last client id", bot.active_cycle.last_client_order_id),
                  field("Take profit", bot.thresholds.take_profit_price),
                  field("Stop loss", bot.thresholds.stop_loss_price),
                  field("Next trigger", bot.thresholds.next_safety_trigger_price)
                ]
            ));
          }
          if (bot.last_closed_cycle) {
            sections.push(renderDrawerSection(bot.strategy_type === "momentum" ? "Last closed position" : "Last closed cycle", [
              field("Closed at", formatDateTime(bot.last_closed_cycle.closed_at)),
              field("Reason", bot.last_closed_cycle.exit_reason),
              field("Exit price", bot.last_closed_cycle.exit_price),
              field("PnL est.", bot.last_closed_cycle.realized_pnl_estimate)
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


@dataclass(frozen=True)
class DockerContainer:
    id: str
    name: str
    image: str
    status: str
    config_source: Path | None
    state_source: Path | None
    network_ips: list[str]


def _docker_bin() -> str:
    configured = os.environ.get("GRAVITY_DASHBOARD_DOCKER_BIN", "").strip()
    if configured:
        return configured
    discovered = shutil.which("docker")
    if discovered:
        return discovered
    raise FileNotFoundError(
        "docker CLI not found on PATH; mount /var/run/docker.sock or install Docker for host-side dashboard use"
    )


def _docker_socket_path() -> str | None:
    configured = os.environ.get("GRAVITY_DASHBOARD_DOCKER_SOCKET", "").strip()
    if configured:
        return configured
    docker_host = os.environ.get("DOCKER_HOST", "").strip()
    if docker_host.startswith("unix://"):
        return docker_host[len("unix://") :]
    default = Path("/var/run/docker.sock")
    if default.exists():
        return str(default)
    return None


class _UnixSocketHTTPConnection(http.client.HTTPConnection):
    def __init__(self, socket_path: str, timeout: float = 20) -> None:
        super().__init__("localhost", timeout=timeout)
        self._socket_path = socket_path

    def connect(self) -> None:
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(self._socket_path)


def _docker_api_get(path: str, *, query: dict[str, str] | None = None) -> bytes:
    socket_path = _docker_socket_path()
    if not socket_path:
        raise FileNotFoundError("docker socket not available")
    target = path
    if query:
        target += "?" + urlencode(query)
    connection = _UnixSocketHTTPConnection(socket_path)
    try:
        connection.request("GET", target)
        response = connection.getresponse()
        payload = response.read()
    finally:
        connection.close()
    if response.status >= 400:
        message = payload.decode("utf-8", errors="replace").strip()
        raise OSError(f"Docker API GET {target} failed: {response.status} {response.reason}: {message}")
    return payload


def _docker_api_read_file(container_id: str, path: str) -> bytes:
    payload = _docker_api_get(
        f"/containers/{quote(container_id, safe='')}/archive",
        query={"path": path},
    )
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as archive:
        member = archive.next()
        if member is None:
            raise FileNotFoundError(f"No file returned for container path {path}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise FileNotFoundError(f"Container path {path} is not a regular file")
        return extracted.read()


def _fetch_bot_status_from_api(container: DockerContainer, *, port: int) -> dict[str, Any] | None:
    for ip_address in container.network_ips:
        connection = http.client.HTTPConnection(ip_address, port, timeout=1.5)
        try:
            connection.request("GET", "/status")
            response = connection.getresponse()
            payload = response.read()
        except OSError:
            continue
        finally:
            connection.close()
        if response.status != 200:
            continue
        return json.loads(payload.decode("utf-8"))
    return None


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _run_docker(args: list[str]) -> str:
    docker_bin = _docker_bin()
    LOGGER.info("docker %s", " ".join(args))
    completed = subprocess.run(
        [docker_bin, *args],
        check=True,
        capture_output=True,
        text=True,
    )
    LOGGER.info("docker %s -> ok", " ".join(args))
    return completed.stdout


def _container_state(status: str) -> str:
    lowered = status.lower()
    if lowered.startswith("up "):
        return "running"
    if lowered.startswith("exited"):
        return "exited"
    return lowered or "unknown"


def _load_recent_log_info(container_name: str) -> tuple[str | None, str | None]:
    lines = get_container_logs(container_name, tail=40)
    if not lines:
        return None, None
    last_line = lines[-1] if lines else None
    recent_error = next((line for line in reversed(lines) if "ERROR" in line), None)
    return recent_error, last_line


def get_container_logs(container_name: str, *, tail: int = 200) -> list[str]:
    LOGGER.info("Loading logs for container=%s tail=%s", container_name, tail)
    try:
        try:
            payload = _docker_api_get(
                f"/containers/{quote(container_name, safe='')}/logs",
                query={"stdout": "1", "stderr": "1", "tail": str(tail)},
            )
            combined = payload.decode("utf-8", errors="replace").strip()
        except (FileNotFoundError, OSError):
            docker_bin = _docker_bin()
            completed = subprocess.run(
                [docker_bin, "logs", "--tail", str(tail), container_name],
                check=False,
                capture_output=True,
                text=True,
            )
            combined = "\n".join(
                line for line in [completed.stdout.strip(), completed.stderr.strip()] if line
            )
    except OSError:
        LOGGER.exception("Failed to load logs for container=%s", container_name)
        return []
    if not combined:
        LOGGER.info("No logs available for container=%s", container_name)
        return []
    lines = [line for line in combined.splitlines() if line.strip()]
    LOGGER.info("Loaded %s log lines for container=%s", len(lines), container_name)
    return lines


def _find_mount_source(mounts: list[dict[str, Any]], destination: str) -> Path | None:
    for mount in mounts:
        if mount.get("Destination") == destination and mount.get("Source"):
            return Path(str(mount["Source"]))
    return None


def list_running_bot_containers() -> list[DockerContainer]:
    try:
        rows = json.loads(_docker_api_get("/containers/json"))
        containers: list[DockerContainer] = []
        for row in rows:
            image = str(row.get("Image", ""))
            names = row.get("Names") or []
            name = str(names[0]).lstrip("/") if names else str(row.get("Names", ""))
            if "gravity-dca-bot" not in image and not name.startswith("grvt-dca"):
                continue
            inspect = json.loads(_docker_api_get(f"/containers/{quote(str(row['Id']), safe='')}/json"))
            network_ips = [
                str(network.get("IPAddress", ""))
                for network in (inspect.get("NetworkSettings", {}).get("Networks", {}) or {}).values()
                if network.get("IPAddress")
            ]
            containers.append(
                DockerContainer(
                    id=str(row["Id"])[:12],
                    name=name,
                    image=image,
                    status=str(row.get("Status", "")),
                    config_source=_find_mount_source(inspect.get("Mounts", []), "/app/config.toml"),
                    state_source=_find_mount_source(inspect.get("Mounts", []), "/state"),
                    network_ips=network_ips,
                )
            )
        LOGGER.info("Discovered %s bot containers via Docker API", len(containers))
        return containers
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        LOGGER.info("Docker API unavailable; falling back to docker CLI", exc_info=True)

    raw = _run_docker(["ps", "--format", "{{json .}}"])
    containers: list[DockerContainer] = []
    ids: list[str] = []
    rows = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        image = str(row.get("Image", ""))
        name = str(row.get("Names", ""))
        if "gravity-dca-bot" not in image and not name.startswith("grvt-dca"):
            continue
        rows.append(row)
        ids.append(str(row["ID"]))
    if not ids:
        LOGGER.info("No running bot containers matched Docker output")
        return []
    inspect = json.loads(_run_docker(["inspect", *ids]))
    mounts_by_id = {str(item["Id"])[:12]: item.get("Mounts", []) for item in inspect}
    for row in rows:
        container_id = str(row["ID"])
        mounts = mounts_by_id.get(container_id, [])
        containers.append(
            DockerContainer(
                id=container_id,
                name=str(row["Names"]),
                image=str(row["Image"]),
                status=str(row["Status"]),
                config_source=_find_mount_source(mounts, "/app/config.toml"),
                state_source=_find_mount_source(mounts, "/state"),
                network_ips=[],
            )
        )
    LOGGER.info("Discovered %s bot containers via docker CLI", len(containers))
    return containers


def _empty_thresholds() -> dict[str, str | None]:
    return {
        "take_profit_price": None,
        "stop_loss_price": None,
        "next_safety_trigger_price": None,
        "initial_stop_price": None,
        "trailing_stop_price": None,
        "fixed_take_profit_price": None,
    }


def _normalize_status_payload(status_payload: dict[str, Any]) -> dict[str, Any]:
    strategy_type = status_payload.get("strategy_type", "dca")
    thresholds = dict(_empty_thresholds())
    thresholds.update(status_payload.get("thresholds", {}))
    runtime_status = status_payload.get("runtime_status", {})
    if strategy_type == "momentum":
        thresholds["take_profit_price"] = (
            thresholds.get("take_profit_price") or thresholds.get("fixed_take_profit_price")
        )
        thresholds["stop_loss_price"] = (
            thresholds.get("stop_loss_price")
            or thresholds.get("trailing_stop_price")
            or thresholds.get("initial_stop_price")
        )
        return {
            "strategy_type": "momentum",
            "state_file": status_payload["state_file"],
            "symbol": status_payload["symbol"],
            "environment": status_payload["environment"],
            "order_type": status_payload["order_type"],
            "dry_run": status_payload["dry_run"],
            "initial_leverage": status_payload["initial_leverage"],
            "margin_type": status_payload["margin_type"],
            "poll_seconds": status_payload["poll_seconds"],
            "bot_api_port": status_payload["bot_api_port"],
            "initial_quote_amount": status_payload.get("quote_amount"),
            "safety_order_quote_amount": None,
            "max_safety_orders": None,
            "price_deviation_percent": None,
            "take_profit_percent": status_payload.get("take_profit_percent"),
            "stop_loss_percent": None,
            "safety_order_step_scale": None,
            "safety_order_volume_scale": None,
            "telegram_enabled": status_payload["telegram_enabled"],
            "completed_cycles": status_payload["completed_cycles"],
            "max_cycles": status_payload["max_cycles"],
            "active_cycle": status_payload.get("active_position"),
            "thresholds": thresholds,
            "last_closed_cycle": status_payload.get("last_closed_position"),
            "timeframe": status_payload.get("timeframe"),
            "ema_fast_period": status_payload.get("ema_fast_period"),
            "ema_slow_period": status_payload.get("ema_slow_period"),
            "breakout_lookback": status_payload.get("breakout_lookback"),
            "adx_period": status_payload.get("adx_period"),
            "min_adx": status_payload.get("min_adx"),
            "atr_period": status_payload.get("atr_period"),
            "min_atr_percent": status_payload.get("min_atr_percent"),
            "stop_atr_multiple": status_payload.get("stop_atr_multiple"),
            "trailing_atr_multiple": status_payload.get("trailing_atr_multiple"),
            "use_trend_failure_exit": status_payload.get("use_trend_failure_exit"),
            "strategy_status": runtime_status.get("strategy_status"),
        }
    return {
        "strategy_type": "dca",
        "state_file": status_payload["state_file"],
        "symbol": status_payload["symbol"],
        "environment": status_payload["environment"],
        "order_type": status_payload["order_type"],
        "dry_run": status_payload["dry_run"],
        "initial_leverage": status_payload["initial_leverage"],
        "margin_type": status_payload["margin_type"],
        "poll_seconds": status_payload["poll_seconds"],
        "bot_api_port": status_payload["bot_api_port"],
        "initial_quote_amount": status_payload["initial_quote_amount"],
        "safety_order_quote_amount": status_payload["safety_order_quote_amount"],
        "max_safety_orders": status_payload["max_safety_orders"],
        "price_deviation_percent": status_payload["price_deviation_percent"],
        "take_profit_percent": status_payload["take_profit_percent"],
        "stop_loss_percent": status_payload["stop_loss_percent"],
        "safety_order_step_scale": status_payload["safety_order_step_scale"],
        "safety_order_volume_scale": status_payload["safety_order_volume_scale"],
        "telegram_enabled": status_payload["telegram_enabled"],
        "completed_cycles": status_payload["completed_cycles"],
        "max_cycles": status_payload["max_cycles"],
        "active_cycle": status_payload["active_cycle"],
        "thresholds": thresholds,
        "last_closed_cycle": status_payload["last_closed_cycle"],
        "strategy_status": runtime_status.get("strategy_status"),
    }


def summarize_bot_container(container: DockerContainer) -> dict[str, Any]:
    LOGGER.info("Summarizing container=%s config=%s", container.name, container.config_source)
    state: BotState | MomentumBotState = BotState()
    config: AppConfig | None = None
    config_file = container.config_source
    state_file: Path | None = None
    load_error: str | None = None
    recent_error, last_log_line = _load_recent_log_info(container.name)
    if config_file is not None:
        try:
            if config_file.exists():
                config = load_config(config_file)
            else:
                config = load_config_text(
                    _docker_api_read_file(container.id, "/app/config.toml").decode("utf-8"),
                    config_path="/app/config.toml",
                    resolve_state_paths=False,
                )
            if config.strategy_type == "momentum":
                settings = config.momentum
                if settings is None:
                    raise ValueError("Momentum config is missing [momentum] settings")
                state_file = settings.state_file
                if state_file.exists():
                    state = load_momentum_state(state_file)
                else:
                    try:
                        state = load_momentum_state_text(
                            _docker_api_read_file(container.id, str(state_file)).decode("utf-8")
                        )
                    except (FileNotFoundError, OSError, tarfile.TarError):
                        state = MomentumBotState()
                symbol = settings.symbol
                active_runtime = state.active_position is not None
            else:
                state_file = config.dca.state_file
                if state_file.exists():
                    state = load_state(state_file)
                else:
                    try:
                        state = load_state_text(
                            _docker_api_read_file(container.id, str(state_file)).decode("utf-8")
                        )
                    except (FileNotFoundError, OSError, tarfile.TarError):
                        state = BotState()
                symbol = config.dca.symbol
                active_runtime = state.active_cycle is not None
            LOGGER.info(
                "Loaded config/state for container=%s strategy=%s symbol=%s state_file=%s active_runtime=%s completed_cycles=%s",
                container.name,
                config.strategy_type,
                symbol,
                state_file,
                active_runtime,
                state.completed_cycles,
            )
        except Exception as exc:  # pragma: no cover - defensive serialization path
            load_error = f"{type(exc).__name__}: {exc}"
            LOGGER.exception("Failed to load config/state for container=%s", container.name)
    status_payload = (
        _fetch_bot_status_from_api(container, port=config.runtime.bot_api_port)
        if config is not None
        else None
    )
    if status_payload is not None:
        LOGGER.info("Loaded bot status via bot API for container=%s", container.name)
        normalized = _normalize_status_payload(status_payload)
        return {
            "container_name": container.name,
            "container_id": container.id,
            "container_state": _container_state(container.status),
            "lifecycle_state": status_payload["lifecycle_state"],
            "image": container.image,
            "config_file": str(config_file) if config_file is not None else "/app/config.toml",
            **normalized,
            "risk_reduce_only": status_payload["runtime_status"].get("risk_reduce_only", False),
            "risk_reduce_only_reason": status_payload["runtime_status"].get(
                "risk_reduce_only_reason"
            ),
            "recent_error": status_payload["runtime_status"]["last_iteration_error"] or recent_error,
            "last_log_line": last_log_line,
        }
    if config is None:
        LOGGER.warning("Container=%s has no usable config; returning error summary", container.name)
        return {
            "container_name": container.name,
            "container_state": _container_state(container.status),
            "lifecycle_state": "error",
            "image": container.image,
            "config_file": str(config_file) if config_file is not None else "",
            "state_file": str(state_file) if state_file is not None else "",
            "symbol": container.name,
            "environment": "",
            "order_type": "",
            "dry_run": False,
            "initial_leverage": None,
            "margin_type": None,
            "poll_seconds": None,
            "bot_api_port": None,
            "strategy_type": "unknown",
            "strategy_status": None,
            "completed_cycles": 0,
            "max_cycles": None,
            "active_cycle": None,
            "thresholds": _empty_thresholds(),
            "last_closed_cycle": None,
            "risk_reduce_only": False,
            "risk_reduce_only_reason": None,
            "recent_error": load_error or recent_error,
            "last_log_line": last_log_line,
        }
    status_payload = build_status_snapshot(config, state, new_runtime_status())
    normalized = _normalize_status_payload(status_payload)
    active_runtime = normalized["active_cycle"] is not None
    LOGGER.info(
        "Container=%s lifecycle_state=%s strategy=%s active_runtime=%s",
        container.name,
        status_payload["lifecycle_state"],
        normalized["strategy_type"],
        active_runtime,
    )
    return {
        "container_name": container.name,
        "container_id": container.id,
        "container_state": _container_state(container.status),
        "lifecycle_state": status_payload["lifecycle_state"],
        "image": container.image,
        "config_file": str(config_file),
        **normalized,
        "risk_reduce_only": False,
        "risk_reduce_only_reason": None,
        "recent_error": recent_error,
        "last_log_line": last_log_line,
    }


def collect_dashboard_payload() -> dict[str, Any]:
    error: str | None = None
    try:
        bots = [summarize_bot_container(container) for container in list_running_bot_containers()]
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as exc:
        LOGGER.warning("Dashboard could not inspect Docker: %s", exc)
        bots = []
        error = f"Docker inspection unavailable: {exc}"
    LOGGER.info(
        "Dashboard payload generated bots=%s active=%s inactive_max=%s error=%s",
        len(bots),
        sum(1 for bot in bots if bot["active_cycle"] is not None),
        sum(1 for bot in bots if bot["lifecycle_state"] == "inactive-max-cycles"),
        error,
    )
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "summary": {
            "total_containers": len(bots),
            "active_cycles": sum(1 for bot in bots if bot["active_cycle"] is not None),
            "inactive_max_cycles": sum(
                1 for bot in bots if bot["lifecycle_state"] == "inactive-max-cycles"
            ),
            "containers_with_errors": sum(1 for bot in bots if bot["recent_error"] is not None),
        },
        "bots": sorted(bots, key=lambda bot: str(bot["symbol"])),
        "error": error,
    }


def get_bot_detail(container_name: str) -> dict[str, Any] | None:
    for container in list_running_bot_containers():
        if container.name == container_name:
            return summarize_bot_container(container)
    return None


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        LOGGER.info("HTTP GET %s", self.path)
        if parsed.path == "/":
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/api/bots":
            payload = json.dumps(collect_dashboard_payload()).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if parsed.path == "/api/client-log":
            message = parse_qs(parsed.query).get("message", [""])[0]
            LOGGER.info("Client log: %s", message)
            self.send_response(204)
            self.end_headers()
            return
        if parsed.path.startswith("/api/bots/"):
            suffix = parsed.path[len("/api/bots/") :]
            if suffix.endswith("/logs"):
                container_name = unquote(suffix[: -len("/logs")]).strip("/")
                LOGGER.info("Serving log detail for container=%s", container_name)
                query = parse_qs(parsed.query)
                tail = int(query.get("tail", ["200"])[0])
                payload = json.dumps(
                    {"container_name": container_name, "lines": get_container_logs(container_name, tail=tail)}
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            container_name = unquote(suffix).strip("/")
            LOGGER.info("Serving detail for container=%s", container_name)
            bot = get_bot_detail(container_name)
            if bot is None:
                LOGGER.warning("No bot detail found for container=%s", container_name)
                self.send_response(404)
                self.end_headers()
                return
            payload = json.dumps(bot).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        logging.getLogger("gravity_dca.dashboard").debug(format, *args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local web dashboard for GRVT bot containers.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind.")
    parser.add_argument("--port", default=8080, type=int, help="Port to listen on.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    logging.getLogger("gravity_dca.dashboard").info(
        "Dashboard listening on http://%s:%s", args.host, args.port
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover - operator shutdown
        pass
    finally:
        server.server_close()
