/* harbinger 콘솔 — 의존성 없는 바닐라 JS + 인라인 SVG. 라벨은 전부 textContent 로 넣는다(신뢰하지 않는 데이터). */
(function () {
  const $ = (s, r = document) => r.querySelector(s);
  const el = (tag, attrs = {}, text) => {
    const e = tag.includes("svg:") ? document.createElementNS("http://www.w3.org/2000/svg", tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) { if (v !== undefined && v !== null) e.setAttribute(k, v); }
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmtP = (p) => (p == null ? "–" : (p * 100).toFixed(1) + " %");
  const fmtN = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString("ko-KR", { maximumFractionDigits: d }));
  const KO = { chiller: "냉동기", ahu: "공조기", pump: "펌프", boiler: "보일러", elevator: "승강기", generator: "비상발전기", switchgear: "수배전반", fire_pump: "소방펌프", cooling_tower: "냉각탑", exhaust_fan: "환풍기", auto_door: "자동문", water_tank: "급수탱크" };
  const OV = ["양호", "주의", "불량"];
  const state = { site: null, asof: null, k: 10 };
  const tooltip = $("#tooltip");

  // 정적 데모 모드: 백엔드 없이 미리 계산한 JSON(api/<slug>.json)을 읽는다. scripts/build_static_demo.py 가 같은 slug 규칙으로 만든다.
  const STATIC = !!window.HARBINGER_STATIC;
  const slug = (path) => path.replace(/^\//, "").replace(/\?/g, "__").replace(/&/g, "_").replace(/=/g, "-").replace(/\//g, "_");
  async function api(path) {
    const r = await fetch(STATIC ? `api/${slug(path)}.json` : path);
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  }
  function showTip(x, y, title, rows) {
    tooltip.replaceChildren();
    tooltip.appendChild(el("div", { class: "t" }, title));
    for (const r of rows) {
      const row = el("div", { class: "row" });
      const left = el("span");
      if (r.color) { const k = el("span", { class: "k" }); k.style.background = r.color; left.appendChild(k); }
      left.appendChild(document.createTextNode(r.label));
      row.appendChild(left);
      row.appendChild(el("b", {}, r.value));
      tooltip.appendChild(row);
    }
    tooltip.hidden = false;
    const w = tooltip.offsetWidth, h = tooltip.offsetHeight;
    tooltip.style.left = Math.min(x + 14, window.innerWidth - w - 8) + "px";
    tooltip.style.top = Math.max(8, y - h - 12) + "px";
  }
  const hideTip = () => { tooltip.hidden = true; };

  // ---------- 차트 프리미티브 ----------
  function lineChart(container, series, opts = {}) {
    // series: [{name, color, points:[{x: Date|number, y}], dashedRef?}] — 단일 y축, 크로스헤어 툴팁
    container.replaceChildren();
    const W = 640, H = opts.height || 220, m = { l: 48, r: 16, t: 12, b: 28 };
    const svg = el("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" });
    const xs = series.flatMap(s => s.points.map(p => +p.x)), ys = series.flatMap(s => s.points.map(p => p.y)).filter(v => v != null);
    if (!xs.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return; }
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = opts.y0 ?? Math.min(0, ...ys), y1 = opts.y1 ?? Math.max(...ys);
    if (y1 === y0) y1 = y0 + 1;
    const pad = (y1 - y0) * 0.08; if (opts.y1 == null) y1 += pad; if (opts.y0 == null && y0 < 0) y0 -= pad;
    const sx = v => m.l + (v - x0) / (x1 - x0 || 1) * (W - m.l - m.r), sy = v => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    const grid = el("svg:g", { class: "grid" }), axis = el("svg:g", { class: "axis" });
    const ticks = niceTicks(y0, y1, 4);
    for (const t of ticks) { grid.appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t) })); svg.appendChild(el("svg:text", { x: m.l - 6, y: sy(t) + 3, "text-anchor": "end" }, opts.fmtY ? opts.fmtY(t) : fmtN(t, 2))); }
    svg.appendChild(grid);
    axis.appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(Math.max(y0, Math.min(0, y1))), y2: sy(Math.max(y0, Math.min(0, y1))) }));
    svg.appendChild(axis);
    const xt = opts.xTicks || 5;
    for (let i = 0; i <= xt; i++) { const v = x0 + (x1 - x0) * i / xt; svg.appendChild(el("svg:text", { x: sx(v), y: H - 8, "text-anchor": i === 0 ? "start" : (i === xt ? "end" : "middle") }, opts.fmtX ? opts.fmtX(v) : fmtN(v))); }
    if (opts.refY != null) svg.appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(opts.refY), y2: sy(opts.refY), stroke: "var(--axis)", "stroke-width": 1 }));
    for (const s of series) {
      const pts = s.points.filter(p => p.y != null);
      const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(+p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
      if (s.area) svg.appendChild(el("svg:path", { class: "area", fill: s.color, d: d + `L${sx(+pts[pts.length - 1].x)},${sy(Math.max(y0, 0))}L${sx(+pts[0].x)},${sy(Math.max(y0, 0))}Z` }));
      svg.appendChild(el("svg:path", { class: "line", stroke: s.color, d }));
      if (s.markers) for (const p of pts) svg.appendChild(el("svg:circle", { class: "marker", cx: sx(+p.x), cy: sy(p.y), r: 4, fill: s.color }));
      if (s.endLabel && pts.length) svg.appendChild(el("svg:text", { x: sx(+pts[pts.length - 1].x) + 6, y: sy(pts[pts.length - 1].y) + 3 }, s.endLabel(pts[pts.length - 1])));
    }
    // 크로스헤어
    const cross = el("svg:line", { class: "crosshair", y1: m.t, y2: H - m.b, visibility: "hidden" });
    svg.appendChild(cross);
    const hit = el("svg:rect", { class: "hit", x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b });
    hit.addEventListener("pointermove", ev => {
      const rect = svg.getBoundingClientRect(); const px = (ev.clientX - rect.left) * W / rect.width;
      const xv = x0 + (px - m.l) / (W - m.l - m.r) * (x1 - x0);
      let best = null, bd = Infinity;
      for (const p of series[0].points) { const dd = Math.abs(+p.x - xv); if (dd < bd) { bd = dd; best = p; } }
      if (!best) return;
      cross.setAttribute("x1", sx(+best.x)); cross.setAttribute("x2", sx(+best.x)); cross.setAttribute("visibility", "visible");
      const rows = series.map(s => { const q = s.points.find(p => +p.x === +best.x); return { label: s.name, color: s.color, value: q && q.y != null ? (opts.fmtY ? opts.fmtY(q.y) : fmtN(q.y, 2)) : "–" }; });
      showTip(ev.clientX, ev.clientY, opts.fmtX ? opts.fmtX(+best.x) : String(best.x), rows);
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    svg.appendChild(hit);
    if (series.length > 1) {
      const lg = el("div", { class: "legend" });
      for (const s of series) { const i = el("span"); const k = el("span", { class: "key" }); k.style.background = s.color; i.appendChild(k); i.appendChild(document.createTextNode(s.name)); lg.appendChild(i); }
      container.appendChild(lg);
    }
    container.appendChild(svg);
  }
  function niceTicks(a, b, n) {
    const span = b - a, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0))), cand = [1, 2, 2.5, 5, 10].map(c => c * mag);
    const step = cand.find(c => span / c <= n) || cand[cand.length - 1];
    const out = []; for (let v = Math.ceil(a / step) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10)); return out;
  }
  function hbars(container, rows, opts = {}) {
    // rows: [{label, value, color?, sub?}] — 가로 막대, ≤24px, 끝 4px 라운드, 값은 끝에 (행 수 적을 때만)
    container.replaceChildren();
    if (!rows.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return; }
    const W = 640, bh = 18, gap = 8, labelW = opts.labelW || 150, H = rows.length * (bh + gap) + 8;
    const svg = el("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}` });
    const neg = Math.min(0, ...rows.map(r => r.value)), pos = Math.max(0, ...rows.map(r => r.value));
    const x0 = labelW, x1 = W - 70, zero = x0 + (0 - neg) / (pos - neg || 1) * (x1 - x0), sx = v => x0 + (v - neg) / (pos - neg || 1) * (x1 - x0);
    svg.appendChild(el("svg:line", { x1: zero, x2: zero, y1: 0, y2: H, stroke: "var(--axis)" }));
    rows.forEach((r, i) => {
      const y = 4 + i * (bh + gap), x = Math.min(zero, sx(r.value)), w = Math.max(1, Math.abs(sx(r.value) - zero));
      const color = r.color || (r.value < 0 ? "var(--div-neg)" : (opts.diverging ? "var(--div-pos)" : "var(--series-1)"));
      const rx = 4; // 끝만 둥글게: path 로 그린다
      const d = r.value >= 0 ? `M${zero},${y}h${w - rx}a${rx},${rx} 0 0 1 ${rx},${rx}v${bh - 2 * rx}a${rx},${rx} 0 0 1 -${rx},${rx}h-${w - rx}z` : `M${zero},${y}h-${w - rx}a${rx},${rx} 0 0 0 -${rx},${rx}v${bh - 2 * rx}a${rx},${rx} 0 0 0 ${rx},${rx}h${w - rx}z`;
      const p = el("svg:path", { d, fill: color });
      p.addEventListener("pointermove", ev => showTip(ev.clientX, ev.clientY, r.label, [{ label: opts.valueName || "값", value: opts.fmt ? opts.fmt(r.value) : fmtN(r.value, 3) }, ...(r.sub ? [{ label: "", value: r.sub }] : [])]));
      p.addEventListener("pointerleave", hideTip);
      svg.appendChild(p);
      svg.appendChild(el("svg:text", { x: labelW - 8, y: y + bh / 2 + 4, "text-anchor": "end", fill: "var(--text-secondary)" }, r.label.length > 22 ? r.label.slice(0, 21) + "…" : r.label));
      svg.appendChild(el("svg:text", { x: r.value >= 0 ? sx(r.value) + 6 : sx(r.value) - 6, y: y + bh / 2 + 4, "text-anchor": r.value >= 0 ? "start" : "end", fill: "var(--text-primary)" }, opts.fmt ? opts.fmt(r.value) : fmtN(r.value, 3)));
      void x;
    });
    container.appendChild(svg);
  }
  function table(container, cols, rows, onRow) {
    container.replaceChildren();
    if (!rows.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return; }
    const t = el("table", { class: "data" }), thead = el("thead"), tr = el("tr");
    for (const c of cols) tr.appendChild(el("th", { class: (c.num ? "num " : "") + (c.nowrap ? "nowrap" : "") }, c.h));
    thead.appendChild(tr); t.appendChild(thead);
    const tb = el("tbody");
    for (const r of rows) {
      const row = el("tr", { class: onRow ? "clickable" : "" });
      for (const c of cols) { const td = el("td", { class: (c.num ? "num " : "") + (c.nowrap ? "nowrap" : "") }); const v = c.render ? c.render(r) : r[c.k]; if (v instanceof Node) td.appendChild(v); else td.textContent = v == null ? "–" : String(v); row.appendChild(td); }
      if (onRow) row.addEventListener("click", () => onRow(r));
      tb.appendChild(row);
    }
    t.appendChild(tb); container.appendChild(t);
  }
  function pbar(p, max = 0.5) { const wrap = el("span"); const tr = el("span", { class: "bar-track" }); const b = el("span", { class: "bar" }); b.style.width = Math.max(2, Math.min(1, p / max) * 110) + "px"; tr.appendChild(b); wrap.appendChild(tr); wrap.appendChild(document.createTextNode(fmtP(p))); return wrap; }
  function badge(cls, text) { const b = el("span", { class: `badge ${cls}` }); b.appendChild(el("span", { class: "dot" })); b.appendChild(document.createTextNode(text)); return b; }
  function tile(label, value, delta, deltaCls) { const t = el("div", { class: "tile" }); t.appendChild(el("div", { class: "label" }, label)); t.appendChild(el("div", { class: "value" }, value)); if (delta) t.appendChild(el("div", { class: `delta ${deltaCls || ""}` }, delta)); return t; }

  // ---------- 탭 ----------
  async function loadOverview() {
    const s = await api(`/v1/sites/${state.site}?as_of=${state.asof}`);
    const p = await api(`/v1/sites/${state.site}/patrol/today?as_of=${state.asof}&k=${state.k}&explain=false`);
    const k = $("#kpis"); k.replaceChildren();
    k.appendChild(tile("설비 수", fmtN(s.n_assets), `${s.assets_with_recent_inspection}개 최근 120일 점검됨`));
    k.appendChild(tile("30일 고장확률 평균", fmtP(s.mean_p30)));
    k.appendChild(tile("고위험 설비 (P30 ≥ 15 %)", fmtN(s["n_high_risk(p30>=0.15)"])));
    k.appendChild(tile("최근 90일 비계획 고장", fmtN(s.breakdowns_90d), `다운타임 ${fmtN(s.downtime_hours_90d)}시간`));
    const lift = p.expected_breakdowns_round_robin > 0 ? p.expected_breakdowns_in_list / p.expected_breakdowns_round_robin : null;
    k.appendChild(tile(`순찰 상위 ${p.k} 기대 적중`, fmtN(p.expected_breakdowns_in_list, 2), lift ? `라운드로빈 대비 ×${lift.toFixed(1)}` : "", lift > 1 ? "good" : ""));
    hbars($("#cat-bars"), (s.by_category || []).sort((a, b) => b.mean - a.mean).map(c => ({ label: `${KO[c.category] || c.category} (${c.count})`, value: c.mean })), { fmt: fmtP, valueName: "평균 P30", labelW: 130 });
    hbars($("#patrol-expect"), [{ label: "harbinger 상위 K", value: p.expected_breakdowns_in_list }, { label: "라운드로빈 상위 K", value: p.expected_breakdowns_round_robin, color: "var(--deemph)" }], { fmt: v => fmtN(v, 2), valueName: "기대 고장 수", labelW: 150 });
  }
  async function loadPatrol() {
    const p = await api(`/v1/sites/${state.site}/patrol/today?as_of=${state.asof}&k=${state.k}`);
    table($("#patrol-table"), [
      { h: "#", k: "rank", num: true }, { h: "설비", render: r => { const d = el("div"); d.appendChild(document.createTextNode(r.name)); const s = el("div", { class: "muted" }, `${r.zone} · ${KO[r.category] || r.category}`); d.appendChild(s); return d; } },
      { h: "P30", render: r => pbar(r.p30), nowrap: true }, { h: "중요도", k: "criticality", num: true, nowrap: true },
      { h: "마지막 점검", render: r => `${Math.round(r.days_since_inspection)}일 전`, nowrap: true },
      { h: "", render: r => r.mandatory ? badge("legal", "법정점검 기한") : (r.p30 >= 0.15 ? badge("urgent", "고위험") : document.createTextNode("")) },
      { h: "근거", render: r => el("div", { class: "reasons" }, (r.reasons || []).join(" · ")) },
    ], p.items);
  }
  async function loadAssets() {
    const a = await api(`/v1/sites/${state.site}/assets?as_of=${state.asof}&limit=15`);
    table($("#asset-table"), [
      { h: "설비", render: r => { const d = el("div"); d.appendChild(document.createTextNode(r.name)); d.appendChild(el("div", { class: "muted" }, `${r.zone} · ${KO[r.category] || r.category} · ${r.age_years}년`)); return d; } },
      { h: "P30", render: r => pbar(r.p30), nowrap: true }, { h: "마지막 판정", render: r => OV[r.last_overall], nowrap: true },
    ], a.assets, r => loadAssetDetail(r.asset_id));
  }
  async function loadAssetDetail(assetId) {
    const box = $("#asset-detail"); box.classList.add("loading");
    const r = await api(`/v1/sites/${state.site}/assets/${assetId}/risk?as_of=${state.asof}`);
    box.classList.remove("loading"); box.replaceChildren();
    const head = el("div", { class: "detail-head" }); head.appendChild(el("h2", {}, `${r.name} · ${KO[r.category] || r.category}`)); head.appendChild(el("span", { class: "muted" }, `${r.zone} · 중요도 ${r.criticality} · 마지막 점검 ${r.last_inspection_at.slice(0, 10)}`)); box.appendChild(head);
    const hero = el("div", { class: "hero" }, fmtP(r.p30)); hero.appendChild(el("small", {}, `30일 내 비계획 고장 확률 (HGB·캘리브레이션)` + (r.p30_deep != null ? ` · 위험 네트 ${fmtP(r.p30_deep)}` : ""))); box.appendChild(hero);
    const rec = r.recommendation; const dl = el("dl", { class: "dl" });
    const add = (k, v) => { dl.appendChild(el("dt", {}, k)); dl.appendChild(el("dd", {}, v)); };
    add("권고 점검 주기", `${rec.recommended_interval_days}일` + (rec.legal_max_days ? ` (법정 상한 ${rec.legal_max_days}일)` : "") + (rec.urgent ? " · 즉시 점검 권고" : ""));
    add("근거 방식", rec.basis === "survival_curve" ? "생존곡선(위험 네트)" : "일정 위험 근사"); box.appendChild(dl);
    if (r.survival_curve_30d_bins) {
      box.appendChild(el("h2", { style: "margin-top:14px" }, "생존곡선 — 이후 12개월"));
      const pts = r.survival_curve_30d_bins.map((s, i) => ({ x: (i + 1) * 30, y: s }));
      const lam = -Math.log(1 - r.p30) / 30; const ch = pts.map(p => ({ x: p.x, y: Math.exp(-lam * p.x) }));
      lineChart(el("div"), [], {});
      const c = el("div"); box.appendChild(c);
      lineChart(c, [{ name: "위험 네트 S(t)", color: "var(--series-1)", points: pts, markers: true }, { name: "HGB 일정위험 근사", color: "var(--deemph)", points: ch }], { y0: 0, y1: 1, fmtX: v => `${Math.round(v)}일`, fmtY: v => (v * 100).toFixed(0) + " %", xTicks: 4, height: 180 });
    }
    if (r.explanation && r.explanation.contributions) {
      box.appendChild(el("h2", { style: "margin-top:14px" }, "무엇이 확률을 올리고 내렸나 (SHAP, 로그오즈)"));
      const c = el("div"); box.appendChild(c);
      hbars(c, r.explanation.contributions.map(x => ({ label: x.label, value: x.contribution, sub: x.value == null ? "결측" : `값 ${fmtN(x.value, 2)}` })), { diverging: true, fmt: v => (v > 0 ? "+" : "") + v.toFixed(2), valueName: "기여도", labelW: 210 });
    }
    if (r.explanation && r.explanation.evidence) {
      const ev = r.explanation.evidence; box.appendChild(el("h2", { style: "margin-top:14px" }, "근거 — 최근 점검 메모 원문"));
      const wrap = el("div", { class: "evidence" });
      for (const m of ev.recent_inspections) {
        const d = el("div", { class: "memo" });
        d.appendChild(el("div", { class: "meta" }, `${m.performed_at.replace("T", " ")} · ${OV[m.overall]} · 체류 ${m.dwell_seconds}초 · ${m.inspector_id}` + (m.flagged_items.length ? ` · 지적: ${m.flagged_items.join(", ")}` : "")));
        // [단어] 표시를 mark 로
        const parts = String(m.memo_highlighted || m.memo).split(/(\[[^\]]+\])/);
        for (const p of parts) { if (/^\[[^\]]+\]$/.test(p)) d.appendChild(el("mark", {}, p.slice(1, -1))); else d.appendChild(document.createTextNode(p)); }
        wrap.appendChild(d);
      }
      if (ev.recent_workorders.length) { const w = el("div", { class: "muted", style: "font-size:12px" }, "최근 이력: " + ev.recent_workorders.map(w => `${w.opened_at.slice(0, 10)} ${({ breakdown: "고장수리", preventive: "예방정비", parts: "부품교체" })[w.type] || w.type}`).join(" · ")); wrap.appendChild(w); }
      box.appendChild(wrap);
    }
  }
  async function loadEnergy() {
    const e = await api(`/v1/sites/${state.site}/energy/anomalies?as_of=${state.asof}&days=120`);
    const days = e.days || []; const fx = v => new Date(v).toISOString().slice(5, 10);
    lineChart($("#energy-line"), [
      { name: "실측 kWh", color: "var(--series-1)", points: days.map(d => ({ x: new Date(d.day), y: d.actual })) },
      { name: "기대치 kWh", color: "var(--deemph)", points: days.map(d => ({ x: new Date(d.day), y: d.expected })) },
    ], { fmtX: fx, fmtY: v => fmtN(v), y0: 0, xTicks: 6 });
    // z 막대 (세로 막대는 열 수가 많아 선+표식으로: 이상일만 상태색 표식)
    const zc = $("#energy-z"); zc.replaceChildren();
    const pts = days.filter(d => d.z != null).map(d => ({ x: new Date(d.day), y: d.z, a: d.anomaly }));
    lineChart(zc, [{ name: "z (7일)", color: "var(--series-1)", points: pts }], { fmtX: fx, fmtY: v => v.toFixed(1), refY: 2.5, xTicks: 6, height: 160 });
    const svg = zc.querySelector("svg"); if (svg && pts.length) {
      const W = 640, H = 160, m = { l: 48, r: 16, t: 12, b: 28 }; const xs = pts.map(p => +p.x), x0 = Math.min(...xs), x1 = Math.max(...xs); const ys = pts.map(p => p.y); let y0 = Math.min(0, ...ys), y1 = Math.max(...ys); const pad = (y1 - y0) * 0.08; y1 += pad; if (y0 < 0) y0 -= pad;
      for (const p of pts.filter(p => p.a)) { const cx = m.l + (+p.x - x0) / (x1 - x0 || 1) * (W - m.l - m.r), cy = m.t + (1 - (p.y - y0) / (y1 - y0)) * (H - m.t - m.b); svg.insertBefore(el("svg:circle", { class: "marker", cx, cy, r: 5, fill: "var(--critical)" }), svg.querySelector(".hit")); }
      const lg = el("div", { class: "legend" }); const i = el("span"); const k = el("span", { class: "key rect" }); k.style.background = "var(--critical)"; i.appendChild(k); i.appendChild(document.createTextNode(`이상일 (z > 2.5) — ${e.n_anomaly_days}일`)); lg.appendChild(i); zc.insertBefore(lg, zc.firstChild);
    }
  }
  async function loadQuality() {
    const q = await api(`/v1/sites/${state.site}/quality?as_of=${state.asof}`);
    table($("#quality-table"), [
      { h: "점검자", k: "inspector_id" }, { h: "점검 수", k: "n_inspections", num: true },
      { h: "신뢰도", render: r => { const w = el("span"); const m = el("span", { class: `meter ${r.reliability_score < 0.5 ? "bad" : (r.reliability_score < 0.75 ? "warn" : "")}` }); const f = el("span"); f.style.width = (r.reliability_score * 100).toFixed(0) + "%"; m.appendChild(f); w.appendChild(m); w.appendChild(document.createTextNode(r.reliability_score.toFixed(2))); return w; } },
      { h: "형식적 메모", render: r => fmtP(r.lazy_memo_rate), num: true }, { h: "직전 메모 복사", render: r => fmtP(r.dup_memo_rate), num: true },
      { h: "체류 중앙값", render: r => `${fmtN(r.dwell_median_s)}초`, num: true }, { h: "7일 초과 지연", render: r => fmtP(r.delay_over_7d_rate), num: true },
      { h: "전부 양호", render: r => fmtP(r.all_good_rate), num: true },
    ], q.inspectors || []);
  }
  async function loadModel() {
    const v = await api(`/version`); const mi = $("#model-info"); mi.replaceChildren();
    const dl = el("dl", { class: "dl" }); const add = (k, val) => { dl.appendChild(el("dt", {}, k)); dl.appendChild(el("dd", {}, val)); };
    add("모델 버전", v.model_version); add("git", v.git_sha || "–"); add("피처 수", String(v.n_features));
    const h = v.headline_metrics || {}; add("AUROC (30일 고장)", h.auroc != null ? h.auroc.toFixed(3) : "–"); add("PR-AUC", h.pr_auc != null ? h.pr_auc.toFixed(3) : "–"); add("Brier", h.brier != null ? h.brier.toFixed(4) : "–"); add("ECE", h.ece != null ? h.ece.toFixed(4) : "–");
    add("순찰 precision@10", h.patrol_precision_at_10 != null ? fmtP(h.patrol_precision_at_10) : "–"); add("라운드로빈 대비", h.patrol_lift_vs_round_robin != null ? `×${h.patrol_lift_vs_round_robin.toFixed(2)}` : "–");
    add("데이터", v.synthetic_data ? `합성 · seed ${v.data.seed} · ${v.data.months}개월` : "실데이터"); mi.appendChild(dl);
    try { const c = await api(`/v1/artifacts/calibration`); const rows = c.calibrated || []; const pts = rows.map(r => ({ x: r.pred_mean, y: r.obs_rate })); const mx = Math.max(0.05, ...pts.map(p => Math.max(p.x, p.y)));
      lineChart($("#calib"), [{ name: "캘리브레이션 후", color: "var(--series-1)", points: pts, markers: true }, { name: "완벽(대각선)", color: "var(--deemph)", points: [{ x: 0, y: 0 }, { x: mx, y: mx }] }], { y0: 0, y1: mx, fmtX: fmtP, fmtY: fmtP, xTicks: 4, height: 200 });
    } catch (e) { $("#calib").replaceChildren(el("div", { class: "empty" }, "산출물 없음")); }
    try { const a = await api(`/v1/artifacts/ablation`); hbars($("#ablation"), Object.entries(a).map(([k, m]) => ({ label: k, value: m.auroc })), { fmt: v => v.toFixed(3), valueName: "AUROC", labelW: 170 }); } catch (e) { $("#ablation").replaceChildren(el("div", { class: "empty" }, "산출물 없음")); }
    try { const d = await api(`/v1/monitoring/drift?window_days=60`); const box = $("#drift"); box.replaceChildren(); const f = d.features; box.appendChild(el("div", { class: "muted", style: "font-size:12px;margin-bottom:6px" }, `피처 ${f.n_features}개 중 경고 ${f.n_warn} · 경보 ${f.n_alert} · 예측 평균 ${fmtP(d.predictions.mean_ref)} → ${fmtP(d.predictions.mean_cur)}`)); const c = el("div"); box.appendChild(c); hbars(c, f.top.slice(0, 8).map(r => ({ label: r.feature, value: r.psi, color: r.level === "alert" ? "var(--critical)" : (r.level === "warn" ? "var(--warning)" : "var(--series-1)") })), { fmt: v => v.toFixed(3), valueName: "PSI", labelW: 200 }); } catch (e) { $("#drift").replaceChildren(el("div", { class: "empty" }, "드리프트 계산 불가")); }
  }
  const loaders = { overview: loadOverview, patrol: loadPatrol, assets: loadAssets, energy: loadEnergy, quality: loadQuality, model: loadModel };
  let current = "overview";
  async function refresh() {
    const sec = $(`#tab-${current}`); sec.classList.add("loading");
    try { await loaders[current](); } catch (e) { sec.replaceChildren(el("div", { class: "empty" }, `불러오기 실패: ${e.message}`)); }
    sec.classList.remove("loading");
  }
  for (const b of document.querySelectorAll("nav.tabs button")) b.addEventListener("click", () => {
    for (const x of document.querySelectorAll("nav.tabs button")) x.setAttribute("aria-selected", x === b ? "true" : "false");
    for (const s of document.querySelectorAll("main > section")) s.hidden = s.id !== `tab-${b.dataset.tab}`;
    current = b.dataset.tab; refresh();
  });
  $("#apply").addEventListener("click", () => { state.site = $("#site").value; state.asof = $("#asof").value; state.k = +$("#k").value || 10; refresh(); });
  $("#theme").addEventListener("click", () => { const r = document.documentElement; const cur = r.getAttribute("data-theme"); const dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; r.setAttribute("data-theme", dark ? "light" : "dark"); });
  (async function init() {
    const v = await api("/version"); $("#version").textContent = `모델 ${v.model_version} · 서비스 v${v.service}`;
    const s = await api("/v1/sites"); const sel = $("#site");
    for (const x of s.sites) sel.appendChild(el("option", { value: x.site_id }, `${x.name} (${x.site_id}) · 설비 ${x.n_assets}`));
    state.site = s.sites[0].site_id; state.asof = s.as_of.slice(0, 10); $("#asof").value = state.asof;
    if (STATIC) {
      for (const id of ["asof", "k", "apply"]) $(`#${id}`).disabled = true;
      const note = el("span", { class: "muted", style: "font-size:12px" }, `정적 데모 — 기준일 ${state.asof}, K=10 고정. 인제스트·임의 시점 조회는 docker compose up 으로 실행한 API 에서.`);
      $(".filters").appendChild(note);
    }
    refresh();
  })().catch(e => { $("#kpis").replaceChildren(el("div", { class: "empty" }, `API 연결 실패: ${e.message}`)); });
})();
