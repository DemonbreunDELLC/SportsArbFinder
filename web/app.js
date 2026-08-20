/* SportsArbFinder Pro — dashboard frontend (vanilla JS, no build step) */
"use strict";

/* ============================================================ helpers */
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const fmt = {
  num: (n, d = 2) => Number(n).toLocaleString("en-US", {
    minimumFractionDigits: d, maximumFractionDigits: d,
  }),
  american(decimal) {
    if (!decimal || decimal <= 1) return "—";
    return decimal >= 2 ? `+${Math.round((decimal - 1) * 100)}` : `${Math.round(-100 / (decimal - 1))}`;
  },
  pct(n, d = 2) { return `${fmt.num(n, d)}%`; },
  money(n) { return `$${fmt.num(n, 2)}`; },
  countdown(iso) {
    if (!iso) return "—";
    const t = new Date(iso).getTime() - Date.now();
    if (t <= 0) return "LIVE";
    const m = Math.floor(t / 60000);
    if (m < 60) return `${m}m`;
    return `${Math.floor(m / 60)}h ${m % 60}m`;
  },
  timeAgo(ts) {
    if (!ts) return "never";
    const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
    if (s < 5) return "just now";
    if (s < 60) return `${s}s ago`;
    if (s < 3600) return `${Math.floor(s / 60)}m ago`;
    return `${Math.floor(s / 3600)}h ago`;
  },
  esc(s) {
    return String(s ?? "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  },
};

function toast(msg, ms = 2600) {
  const el = $("#toast");
  el.textContent = msg;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), ms);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied to clipboard ✓");
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
    toast("Copied to clipboard ✓");
  }
}

/* ============================================================ state */
const state = {
  results: null,
  meta: null,
  ws: null,
  seen: new Set(),
  notifyOn: false,
  markets: ["h2h", "spreads", "totals"],
  settings: null,
};

const MARKET_LABELS = {
  h2h: "Moneyline", spreads: "Spreads", totals: "Totals",
  outrights: "Outrights", h2h_lay: "Back/Lay", outrights_lay: "Outright Lay",
};

/* ============================================================ websocket */
function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  state.ws = ws;
  ws.onopen = () => console.log("[ws] connected");
  ws.onmessage = (ev) => {
    let msg;
    try { msg = JSON.parse(ev.data); } catch { return; }
    if (msg.type === "state") {
      onState(msg.results, msg.meta);
    } else if (msg.type === "settings") {
      state.settings = msg.settings;
      fillSettings();
    }
  };
  ws.onclose = () => setTimeout(connect, 3000);
}

function onState(results, meta) {
  state.results = results;
  state.meta = meta;

  // NEW arbs (id not seen before) — highlight + optional notification
  const fresh = (results?.arbitrage_opportunities || []).filter((a) => !state.seen.has(a.id));
  (results?.arbitrage_opportunities || []).forEach((a) => state.seen.add(a.id));
  if (fresh.length && state.notifyOn && document.hidden) {
    fresh.slice(0, 3).forEach((a) => {
      try {
        new Notification("⚡ New arbitrage!", {
          body: `${a.event} — ${fmt.pct(a.profit_margin)} margin (${a.market.toUpperCase()})`,
        });
      } catch { /* notifications unavailable */ }
    });
  }
  window._freshIds = new Set(fresh.map((a) => a.id));

  updateTopbar();
  renderStats();
  renderArbs();
  renderEV();
  renderOddsScreen();
  renderSportsOptions();
}

/* ============================================================ topbar */
function updateTopbar() {
  const r = state.results;
  const src = r?.source;
  const badge = $("#source-badge");
  const label = $("#source-label");
  if (state.meta?.static) {
    badge.className = "badge"; label.textContent = "SAVED RESULTS";
  } else if (!src) {
    badge.className = "badge warn"; label.textContent = "CONNECTING…";
  } else if (src === "live") {
    badge.className = "badge live"; label.textContent = "LIVE · The Odds API";
  } else if (src === "sample-data") {
    badge.className = "badge warn";
    const reason = r.fallback_reason ? ` — ${r.fallback_reason}` : "";
    label.textContent = `SAMPLE DATA${reason}`;
    badge.title = "No live feed available; showing built-in sample data.";
  } else {
    badge.className = "badge"; label.textContent = "OFFLINE FILE";
  }

  const usage = r?.api_usage;
  if (usage && usage.remaining_requests != null) {
    $("#credits-badge").style.display = "";
    const n = Number(usage.remaining_requests);
    $("#credits-label").textContent = `${n} credits left`;
    $("#credits-badge").className = "badge " + (n < 100 ? "err" : n < 300 ? "warn" : "live");
  } else {
    $("#credits-badge").style.display = "none";
  }

  $("#updated-label").textContent = `scanned ${fmt.timeAgo(state.meta?.last_scan)}`;
}

/* ============================================================ tabs */
$$(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    $$(".tab-btn").forEach((b) => b.classList.remove("active"));
    $$(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

/* ============================================================ arbitrage tab */
const arbFilters = {
  sport: "", market: "all", min: 0, max: 20, search: "", sort: "margin-desc",
};

function arbStakeSplit(arb, stake) {
  const odds = arb.outcomes.map((o) => o.odds);
  const inv = odds.map((d) => 1 / d);
  const total = inv.reduce((a, b) => a + b, 0);
  return inv.map((p) => stake * p / total);
}

function renderStats() {
  const arbs = state.results?.arbitrage_opportunities || [];
  const sum = state.results?.summary;
  $("#st-arb").textContent = arbs.length;
  $("#st-avg").textContent = arbs.length
    ? fmt.pct(arbs.reduce((a, b) => a + b.profit_margin, 0) / arbs.length) : "0.00%";
  $("#st-best").textContent = arbs.length ? fmt.pct(Math.max(...arbs.map((a) => a.profit_margin))) : "0.00%";
  $("#st-events").textContent = sum?.events_analyzed ?? 0;
  $("#cnt-arb").textContent = arbs.length;
  $("#cnt-arb").classList.toggle("hot", arbs.length > 0);
  $("#cnt-ev").textContent = state.results?.value_bets?.length ?? 0;
  $("#cnt-ev").classList.toggle("hot", (state.results?.value_bets?.length ?? 0) > 0);
}

function renderSportsOptions() {
  const arbs = state.results?.arbitrage_opportunities || [];
  const evs = state.results?.value_bets || [];
  const screen = state.results?.odds_screen || [];
  const sports = [...new Set([
    ...arbs.map((a) => a.sport_key),
    ...evs.map((v) => v.sport_key),
    ...screen.map((e) => e.sport_key),
  ])].sort();
  const title = (key) =>
    [...arbs, ...evs, ...screen].find((x) => x.sport_key === key)?.sport_title || key;
  [$("#f-sport"), $("#ev-sport"), $("#o-sport")].forEach((sel) => {
    const current = sel.value;
    sel.innerHTML = '<option value="">All</option>' +
      sports.map((s) => `<option value="${s}">${fmt.esc(title(s))}</option>`).join("");
    sel.value = sports.includes(current) ? current : "";
  });
}

function renderArbs() {
  const list = $("#arb-list");
  let arbs = state.results?.arbitrage_opportunities || [];
  const stake = parseFloat($("#f-stake").value) || 100;
  const marketChips = state.markets;

  if (arbFilters.sport) arbs = arbs.filter((a) => a.sport_key === arbFilters.sport);
  if (state.markets.length) arbs = arbs.filter((a) => state.markets.includes(a.market));
  arbs = arbs.filter((a) => {
    const m = a.profit_margin;
    return m >= (parseFloat(arbFilters.min) || 0) && m <= (parseFloat(arbFilters.max) || 1e9);
  });
  if (arbFilters.search) {
    const q = arbFilters.search.toLowerCase();
    arbs = arbs.filter((a) => (a.event + " " + a.sport_title).toLowerCase().includes(q));
  }
  if (arbFilters.sort === "soonest") {
    arbs.sort((a, b) => (a.starts_in_minutes ?? 1e9) - (b.starts_in_minutes ?? 1e9));
  } else if (arbFilters.sort === "margin-asc") {
    arbs.sort((a, b) => a.profit_margin - b.profit_margin);
  } else {
    arbs.sort((a, b) => b.profit_margin - a.profit_margin);
  }

  if (!state.results) {
    list.innerHTML = '<div class="loading"><div class="spinner"></div>Waiting for first scan…</div>';
    return;
  }
  if (!arbs.length) {
    list.innerHTML = '<div class="empty-state"><div class="big">🎯</div>No arbitrage opportunities match your filters.<br>Try lowering the minimum margin or widening the market selection.</div>';
    return;
  }

  list.innerHTML = arbs.map((a) => {
    const fresh = window._freshIds?.has(a.id);
    const isLay = a.market.endsWith("_lay");
    const split = isLay ? null : arbStakeSplit(a, stake);
    const legs = a.outcomes.map((o, i) => {
      const stakeAmt = split ? split[i] : o.stake;
      const sharp = o.bookmaker_key === "pinnacle" || o.bookmaker_key === "betfair";
      return `<div class="leg${sharp ? " sharp" : ""}">
        <div class="leg-name">${fmt.esc(o.name)} ${sharp && !isLay ? '<span class="sharp-tag">SHARP</span>' : ""}</div>
        <div class="leg-book">🏛 ${fmt.esc(o.bookmaker)}</div>
        <div class="leg-odds">${fmt.num(o.odds)} <span class="muted">(${fmt.esc(o.american)})</span></div>
        <div class="leg-stake">Stake <b>${fmt.money(stakeAmt)}</b> <span class="muted">· ${fmt.num(isLay ? o.stake_pct : 100 * stakeAmt / stake, 1)}%</span></div>
      </div>`;
    }).join("");
    const markets = [a.market, ...(a.n_way > 2 ? [`${a.n_way}-way`] : [])];
    const live = (a.starts_in_minutes ?? 999) <= 0;
    return `<div class="arb">
      <div class="arb-head">
        <div class="arb-margin">${fmt.pct(a.profit_margin)}<small>margin</small></div>
        <div class="arb-event">${fmt.esc(a.event)}
          <span class="sport">${fmt.esc(a.sport_title)}</span>
        </div>
        <div class="arb-meta">
          ${fresh ? '<span class="tag new">NEW</span>' : ""}
          ${isLay ? `<span class="tag market lay">${MARKET_LABELS[a.market] || a.market}</span>`
                  : `<span class="tag market">${MARKET_LABELS[a.market] || a.market}</span>`}
          ${markets.length > 1 ? `<span class="tag nway">${a.n_way}-WAY</span>` : ""}
          <span class="tag countdown${live ? " live" : ""}" data-iso="${a.commence_time}">⏱ ${live ? "LIVE" : fmt.countdown(a.commence_time)}</span>
        </div>
      </div>
      <div class="arb-body">${legs}</div>
      <div class="arb-foot">
        <span>Stake <b>${fmt.money(stake)}</b></span>
        <span>Guaranteed return <b class="profit">${fmt.money(split ? stake / a.total_implied_prob : a.guaranteed_return)}</b></span>
        <span>Profit <b class="profit">${fmt.money(split ? stake / a.total_implied_prob - stake : a.guaranteed_return - stake)}</b></span>
        <button class="btn copy" data-copy="${fmt.esc(JSON.stringify(a)).replace(/"/g, "&quot;")}">⧉ Copy</button>
      </div>
    </div>`;
  }).join("");
}

$("#arb-list").addEventListener("click", (ev) => {
  const btn = ev.target.closest(".copy");
  if (!btn) return;
  const a = JSON.parse(btn.dataset.copy);
  const lines = [
    `⚡ ARB ${fmt.pct(a.profit_margin)} — ${a.event} (${a.sport_title})`,
    `   Market: ${MARKET_LABELS[a.market] || a.market}${a.points != null ? ` @ ${a.points}` : ""} | Stake: $${fmt.num(a.stake)}`,
    ...a.outcomes.map((o) => `   • ${o.name}: ${fmt.num(o.odds)} (${o.american}) @ ${o.bookmaker} — bet $${fmt.num(o.stake)}`),
    `   Guaranteed return: $${fmt.num(a.guaranteed_return)} → profit $${fmt.num(a.guaranteed_return - a.stake)}`,
  ];
  copyText(lines.join("\n"));
});

/* ---- arb filters wiring ---- */
$("#f-sport").addEventListener("change", (e) => { arbFilters.sport = e.target.value; renderArbs(); });
$("#f-min").addEventListener("input", (e) => { arbFilters.min = e.target.value; renderArbs(); });
$("#f-max").addEventListener("input", (e) => { arbFilters.max = e.target.value; renderArbs(); });
$("#f-search").addEventListener("input", (e) => { arbFilters.search = e.target.value; renderArbs(); });
$("#f-sort").addEventListener("change", (e) => { arbFilters.sort = e.target.value; renderArbs(); });
$("#f-stake").addEventListener("input", () => renderArbs());

function renderMarketChips() {
  const chipKeys = ["h2h", "spreads", "totals", "outrights", "h2h_lay"];
  const box = $("#f-market-chips");
  box.innerHTML = chipKeys.map((k) =>
    `<span class="chip${state.markets.includes(k) ? " on" : ""}" data-market="${k}">${MARKET_LABELS[k]}</span>`
  ).join("");
  box.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => {
    const k = c.dataset.market;
    state.markets = state.markets.includes(k)
      ? state.markets.filter((m) => m !== k)
      : [...state.markets, k];
    renderMarketChips();
    renderArbs();
  }));
}
renderMarketChips();

/* ============================================================ +EV tab */
const evSort = { key: "ev_percent", dir: -1 };

function renderEV() {
  const body = $("#ev-body");
  let evs = state.results?.value_bets || [];
  const sport = $("#ev-sport").value;
  const minEv = parseFloat($("#ev-min").value) || 0;
  const sharpOnly = $("#ev-sharp").checked;
  if (sport) evs = evs.filter((v) => v.sport_key === sport);
  if (minEv) evs = evs.filter((v) => v.ev_percent >= minEv);
  if (sharpOnly) evs = evs.filter((v) => v.sharp);
  evs.sort((a, b) => (a[evSort.key] - b[evSort.key]) * evSort.dir);

  if (!state.results) {
    body.innerHTML = '<tr><td colspan="8" class="muted" style="text-align:center;padding:30px">Waiting for data…</td></tr>';
    return;
  }
  if (!evs.length) {
    body.innerHTML = '<tr><td colspan="8" class="muted" style="text-align:center;padding:30px">No +EV bets match — lower the EV threshold or check back after the next scan.</td></tr>';
    return;
  }
  body.innerHTML = evs.map((v) => `<tr>
    <td class="ev-cell">${fmt.pct(v.ev_percent)}</td>
    <td>${fmt.esc(v.event)} <span class="muted">· ${fmt.esc(v.sport_title)}</span></td>
    <td><span class="tag market">${MARKET_LABELS[v.market] || v.market}</span>${v.points != null ? ` <span class="muted">${v.points}</span>` : ""}</td>
    <td>${fmt.esc(v.outcome)}</td>
    <td class="book-cell">${fmt.esc(v.bookmaker)}${v.sharp ? '<span class="star">★</span>' : ""}</td>
    <td class="mono">${fmt.num(v.odds)} <span class="muted">(${fmt.esc(v.american)})</span></td>
    <td class="mono">${fmt.pct(v.fair_prob * 100, 1)}</td>
    <td class="muted">${(v.starts_in_minutes ?? 0) <= 0 ? "LIVE" : fmt.countdown(v.commence_time)}</td>
  </tr>`).join("");
}

$$("#ev-table thead th").forEach((th) => th.addEventListener("click", () => {
  const key = th.dataset.key;
  if (!key) return;
  if (evSort.key === key) evSort.dir *= -1;
  else { evSort.key = key; evSort.dir = -1; }
  $$("#ev-table thead th").forEach((t) => t.classList.remove("sorted"));
  th.classList.add("sorted");
  renderEV();
}));
$("#ev-sport").addEventListener("change", renderEV);
$("#ev-min").addEventListener("input", renderEV);
$("#ev-sharp").addEventListener("change", renderEV);

/* ============================================================ odds screen */
function renderOddsScreen() {
  const wrap = $("#odds-screen");
  const sport = $("#o-sport").value;
  let events = state.results?.odds_screen || [];
  if (sport) events = events.filter((e) => e.sport_key === sport);
  events.sort((a, b) => (a.starts_in_minutes ?? 1e9) - (b.starts_in_minutes ?? 1e9));

  if (!state.results) {
    wrap.innerHTML = '<div class="loading"><div class="spinner"></div>Waiting for first scan…</div>';
    return;
  }
  if (!events.length) {
    wrap.innerHTML = '<div class="empty-state"><div class="big">📊</div>No events with line data yet.</div>';
    return;
  }

  wrap.innerHTML = events.map((e) => {
    const best = e.best || {};
    const books = Object.entries(e.books || {});
    const rows = books.map(([key, b]) => {
      const cell = (mkey, side) => {
        const m = b[mkey];
        if (!m || !m.sides || !m.sides[side]) return '<td class="muted">—</td>';
        const price = m.sides[side];
        const isBest = best[mkey] && best[mkey][mkey === "h2h" ? "h2h" : m.point]
          && best[mkey][mkey === "h2h" ? "h2h" : m.point][side]?.price === price.price;
        return `<td class="${isBest ? "best" : ""} mono">${fmt.num(price.price)}<span class="point-col"> ${price.american}</span></td>`;
      };
      const h2h = b.h2h ? `<td class="team-col">${fmt.esc(e.home_team)}</td>${cell("h2h", "home")}<td class="team-col">${fmt.esc(e.away_team)}</td>${cell("h2h", "away")}` : '<td class="muted" colspan="2">—</td><td class="muted" colspan="2">—</td>';
      const sp = b.spreads
        ? `<td class="point-col">${fmt.num(b.spreads.point, 1)}</td>${cell("spreads", "home")}<td class="point-col">${fmt.num(b.spreads.point, 1)}</td>${cell("spreads", "away")}`
        : '<td class="muted" colspan="2">—</td><td class="muted" colspan="2">—</td>';
      const tot = b.totals
        ? `<td class="point-col">O ${fmt.num(b.totals.point, 1)}</td>${cell("totals", "over")}<td class="point-col">U ${fmt.num(b.totals.point, 1)}</td>${cell("totals", "under")}`
        : '<td class="muted" colspan="2">—</td><td class="muted" colspan="2">—</td>';
      return `<tr><td class="book-cell">${fmt.esc(b.title)}${key === "pinnacle" ? '<span class="star">★</span>' : ""}</td>
        ${h2h}${sp}${tot}</tr>`;
    }).join("");
    const lowHold = (m) => e.hold && e.hold[m] != null && e.hold[m] < 3
      ? `<span class="lowhold">LOW HOLD ${fmt.num(e.hold[m], 2)}%</span>` : "";
    const live = (e.starts_in_minutes ?? 999) <= 0;
    return `<div class="event-block">
      <h3>${fmt.esc(e.event)}
        <span class="tag countdown${live ? " live" : ""}" data-iso="${e.commence_time}">⏱ ${live ? "LIVE" : fmt.countdown(e.commence_time)}</span>
        <span class="tag market">${fmt.esc(e.sport_title)}</span>
        ${lowHold("h2h")}${lowHold("totals")}${lowHold("spreads")}
      </h3>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Book</th>
            <th>${fmt.esc(e.home_team)} ML</th><th></th>
            <th>${fmt.esc(e.away_team)} ML</th><th></th>
            <th>Spread</th><th>Home</th><th>Spread</th><th>Away</th>
            <th>Total</th><th>Over</th><th>Total</th><th>Under</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}
$("#o-sport").addEventListener("change", renderOddsScreen);

/* ============================================================ calculators */
function calcArb() {
  const rows = $$("#arb-calc-legs .leg-row");
  const odds = rows.map((r) => parseFloat(r.querySelector(".ac-odds").value)).filter((o) => o > 1);
  const stake = parseFloat($("#ac-stake").value) || 100;
  const box = $("#ac-result");
  if (odds.length < 2) { box.innerHTML = '<div class="line">Add at least 2 outcomes.</div>'; return; }
  const inv = odds.map((d) => 1 / d);
  const total = inv.reduce((a, b) => a + b, 0);
  const margin = (1 / total - 1) * 100;
  const ret = stake / total;
  box.innerHTML = `
    <div class="line"><span>Implied probability</span><b>${fmt.pct(total * 100, 2)}</b></div>
    <div class="line"><span>Guaranteed return</span><b class="pos">${fmt.money(ret)}</b></div>
    <div class="line"><span>Profit on ${fmt.money(stake)}</span><b class="${margin >= 0 ? "pos" : "neg"}">${fmt.money(ret - stake)} (${fmt.pct(margin, 3)})</b></div>
    ${odds.map((o, i) => {
      const s = stake * inv[i] / total;
      return `<div class="line"><span>Leg ${i + 1} @ ${fmt.num(o)}</span><b>${fmt.money(s)}</b></div>`;
    }).join("")}`;
}

function addLeg(value = "") {
  const wrap = $("#arb-calc-legs");
  const row = document.createElement("div");
  row.className = "leg-row";
  row.innerHTML = `<input class="ac-odds" type="number" min="1.01" step="0.01" placeholder="Odds e.g. 2.10" value="${value}">
    <button class="rm" title="Remove">✕</button>`;
  row.querySelector(".rm").addEventListener("click", () => { row.remove(); calcArb(); });
  row.querySelector(".ac-odds").addEventListener("input", calcArb);
  wrap.appendChild(row);
  calcArb();
}
["2.10", "2.10"].forEach(addLeg);
$("#ac-add").addEventListener("click", () => addLeg());
$("#ac-stake").addEventListener("input", calcArb);

function calcEV() {
  const prob = parseFloat($("#evc-prob").value) / 100;
  const odds = parseFloat($("#evc-odds").value);
  const stake = parseFloat($("#evc-stake").value) || 100;
  if (!prob || !odds || odds <= 1) {
    $("#evc-result").innerHTML = '<div class="line">Enter a probability and odds.</div>';
    return;
  }
  const ev = prob * odds - 1;
  $("#evc-result").innerHTML = `
    <div class="line"><span>Expected value</span><b class="${ev >= 0 ? "pos" : "neg"}">${fmt.pct(ev * 100, 2)}</b></div>
    <div class="line"><span>EV profit per ${fmt.money(stake)}</span><b class="${ev >= 0 ? "pos" : "neg"}">${fmt.money(ev * stake)}</b></div>
    <div class="line"><span>Fair odds (breakeven)</span><b>${fmt.num(1 / prob)}</b></div>`;
}
["evc-prob", "evc-odds", "evc-stake"].forEach((id) => $(`#${id}`).addEventListener("input", calcEV));
calcEV();

/* odds converter — bidirectional sync */
let converting = false;
function convFromDecimal() {
  if (converting) return; converting = true;
  const d = parseFloat($("#oc-decimal").value);
  if (d > 1) {
    $("#oc-american").value = d >= 2 ? `+${Math.round((d - 1) * 100)}` : `${Math.round(-100 / (d - 1))}`;
    $("#oc-implied").value = fmt.num(100 / d, 2);
    let frac = "";
    for (let den = 1; den <= 100; den++) {
      const num = Math.round((d - 1) * den);
      if (num > 0 && Math.abs(num / den + 1 - d) < 0.002) { frac = `${num}/${den}`; break; }
    }
    $("#oc-fractional").value = frac || fmt.num(d - 1, 2);
  }
  converting = false;
}
function convFromAmerican() {
  if (converting) return; converting = true;
  const a = parseFloat($("#oc-american").value);
  if (a && a !== -100) {
    const d = a > 0 ? 1 + a / 100 : 1 + 100 / Math.abs(a);
    $("#oc-decimal").value = fmt.num(d, 3);
    $("#oc-implied").value = fmt.num(100 / d, 2);
    let frac = "";
    for (let den = 1; den <= 100; den++) {
      const num = Math.round((d - 1) * den);
      if (num > 0 && Math.abs(num / den + 1 - d) < 0.002) { frac = `${num}/${den}`; break; }
    }
    $("#oc-fractional").value = frac || fmt.num(d - 1, 2);
  }
  converting = false;
}
function convFromImplied() {
  if (converting) return; converting = true;
  const p = parseFloat($("#oc-implied").value) / 100;
  if (p > 0 && p < 1) {
    const d = 1 / p;
    $("#oc-decimal").value = fmt.num(d, 3);
    $("#oc-american").value = d >= 2 ? `+${Math.round((d - 1) * 100)}` : `${Math.round(-100 / (d - 1))}`;
  }
  converting = false;
}
$("#oc-decimal").addEventListener("input", convFromDecimal);
$("#oc-american").addEventListener("input", convFromAmerican);
$("#oc-implied").addEventListener("input", convFromImplied);
$("#oc-fractional").addEventListener("input", () => {
  const raw = $("#oc-fractional").value.trim();
  const m = raw.match(/^(\d+)\s*\/\s*(\d+)$/);
  if (m) {
    const d = 1 + parseInt(m[1], 10) / parseInt(m[2], 10);
    if (!converting) {
      converting = true;
      $("#oc-decimal").value = fmt.num(d, 3);
      $("#oc-american").value = d >= 2 ? `+${Math.round((d - 1) * 100)}` : `${Math.round(-100 / (d - 1))}`;
      $("#oc-implied").value = fmt.num(100 / d, 2);
      converting = false;
    }
  }
});

function calcHedge() {
  const stake = parseFloat($("#hc-stake").value) || 0;
  const back = parseFloat($("#hc-back").value);
  const lay = parseFloat($("#hc-lay").value);
  const comm = (parseFloat($("#hc-comm").value) || 0) / 100;
  const box = $("#hc-result");
  if (stake <= 0 || back <= 1 || lay <= 1) { box.innerHTML = '<div class="line">Enter stake &amp; odds.</div>'; return; }
  const layStake = stake * back / (lay - comm);
  const win = stake * (back - 1) - layStake * (lay - 1) - comm * layStake * (lay - 1);
  const lose = layStake * (1 - comm) - stake;
  box.innerHTML = `
    <div class="line"><span>Lay stake</span><b>${fmt.money(layStake)}</b></div>
    <div class="line"><span>Profit if back wins</span><b class="${win >= 0 ? "pos" : "neg"}">${fmt.money(win)}</b></div>
    <div class="line"><span>Profit if back loses</span><b class="${lose >= 0 ? "pos" : "neg"}">${fmt.money(lose)}</b></div>
    <div class="line"><span>Guaranteed</span><b class="${Math.min(win, lose) > 0 ? "pos" : "neg"}">${fmt.money(Math.min(win, lose))}</b></div>`;
}
["hc-stake", "hc-back", "hc-lay", "hc-comm"].forEach((id) => $(`#${id}`).addEventListener("input", calcHedge));
calcHedge();

/* ============================================================ settings */
function fillSettings() {
  const s = state.settings;
  if (!s) return;
  $("#s-region").value = s.region;
  $("#s-refresh").value = s.refresh_seconds;
  $("#s-maxsports").value = s.max_sports;
  $("#s-cutoff").value = s.cutoff;
  $("#s-maxprofit").value = s.max_profit;
  $("#s-minev").value = s.min_ev;
  $("#s-stake").value = s.stake;
  $("#s-comm").value = (s.lay_commission * 100).toFixed(1);

  const box = $("#s-markets");
  box.innerHTML = Object.entries(MARKET_LABELS).map(([k, label]) =>
    `<label class="check-item"><input type="checkbox" value="${k}" ${s.markets.includes(k) ? "checked" : ""}> ${label}</label>`
  ).join("");

  // sports: union of configured sports + sports present in data
  const sports = [...new Set([
    ...(s.sports || []),
    ...(state.results?.odds_screen || []).map((e) => e.sport_key),
    ...(state.results?.value_bets || []).map((v) => v.sport_key),
  ])].sort();
  const title = (key) => state.results
    ? [...(state.results.odds_screen || []), ...(state.results.value_bets || [])]
        .find((x) => x.sport_key === key)?.sport_title || key
    : key;
  $("#s-sports").innerHTML = sports.length
    ? sports.map((k) =>
        `<label class="check-item"><input type="checkbox" value="${k}" ${s.sports ? s.sports.includes(k) : "checked"}> ${fmt.esc(title(k))}</label>`
      ).join("")
    : '<span class="muted">No sports in the current data yet.</span>';
}

$("#s-save").addEventListener("click", async () => {
  const markets = $$("#s-markets input:checked").map((i) => i.value);
  const sports = $$("#s-sports input:checked").map((i) => i.value);
  const body = {
    region: $("#s-region").value,
    markets,
    sports: sports.length ? sports : null,
    cutoff: parseFloat($("#s-cutoff").value) || 0,
    max_profit: parseFloat($("#s-maxprofit").value) || 20,
    min_ev: parseFloat($("#s-minev").value) || 0,
    stake: parseFloat($("#s-stake").value) || 100,
    refresh_seconds: parseInt($("#s-refresh").value, 10) || 300,
    lay_commission: (parseFloat($("#s-comm").value) || 2) / 100,
  };
  const res = await fetch("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (res.ok) {
    state.settings = data.settings;
    toast("Settings saved — rescanning…");
    $("#s-status").textContent = "Saved ✓";
    setTimeout(() => { $("#s-status").textContent = ""; }, 3000);
  } else {
    toast(`Error: ${data.error || "could not save"}`);
  }
});

/* ============================================================ topbar actions */
$("#scan-btn").addEventListener("click", () => {
  if (state.ws && state.ws.readyState === 1) {
    state.ws.send(JSON.stringify({ type: "scan" }));
  } else {
    fetch("/api/scan", { method: "POST" });
  }
  toast("Scanning…");
});

$("#notify-btn").addEventListener("click", async () => {
  if (!("Notification" in window)) { toast("Notifications not supported in this browser"); return; }
  if (Notification.permission === "default") await Notification.requestPermission();
  if (Notification.permission === "granted") {
    state.notifyOn = !state.notifyOn;
    $("#notify-btn").classList.toggle("active", state.notifyOn);
    toast(state.notifyOn ? "Alerts ON — you'll be pinged on new arbs" : "Alerts OFF");
  } else {
    toast("Notification permission denied by the browser");
  }
});

/* ============================================================ countdown ticker */
setInterval(() => {
  $$(".tag.countdown").forEach((el) => {
    const iso = el.dataset?.iso;
    if (!iso) return;
    const label = fmt.countdown(iso);
    el.textContent = `⏱ ${label}`;
    el.classList.toggle("live", label === "LIVE");
  });
}, 10000);

/* ============================================================ boot */
(async function boot() {
  const keyStatus = $("#s-key-status");
  try {
    const res = await fetch("/api/settings");
    const data = await res.json();
    state.settings = data.settings;
    keyStatus.className = "badge " + (data.has_api_key ? "live" : "warn");
    keyStatus.textContent = data.has_api_key ? "key configured" : "no key — sample data";
    fillSettings();
    // default the market chips to whatever the server is scanning
    if (data.settings.markets?.length) {
      state.markets = [...data.settings.markets];
      renderMarketChips();
    }
  } catch { /* server starting */ }
  connect();
})();
