/* 차트 프리미티브 — 의존성 없는 인라인 SVG. dataviz 규칙: 얇은 마크(선 2px, 막대 ≤ 24px·끝만 4px 라운드),
 * 눈금선은 연한 실선, 값 라벨은 선택적으로, 텍스트는 잉크 토큰(시리즈 색을 쓰지 않음), 범례는 시리즈 2개 이상일 때 항상,
 * 모든 값은 툴팁과 "표로 보기"로도 읽힌다. 라벨은 신뢰할 수 없는 데이터이므로 전부 textContent 로 넣는다. */
(function (root) {
  const SVGNS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}, text) => {
    const e = tag.startsWith("svg:") ? document.createElementNS(SVGNS, tag.slice(4)) : document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) if (v !== undefined && v !== null) e.setAttribute(k, v);
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const fmtN = (n, d = 0) => (n == null || Number.isNaN(n) ? "–" : Number(n).toLocaleString("ko-KR", { maximumFractionDigits: d }));
  const fmtP = (p, d = 1) => (p == null || Number.isNaN(p) ? "–" : (p * 100).toFixed(d) + " %");
  /* viewBox 폭을 컨테이너 폭에 맞춰 글자 크기가 화면 폭과 무관하게 거의 일정하게 보이게 한다 */
  const chartWidth = (container) => Math.round(Math.min(760, Math.max(300, container.clientWidth || 680)));

  /* ---------- 툴팁 ---------- */
  let tip;
  function tooltip() {
    if (!tip) { tip = el("div", { class: "tooltip", hidden: "", role: "status" }); document.body.appendChild(tip); }
    return tip;
  }
  function showTip(x, y, title, rows) {
    const t = tooltip();
    t.replaceChildren();
    if (title) t.appendChild(el("div", { class: "t" }, title));
    for (const r of rows) {
      const row = el("div", { class: "row" });
      const left = el("span");
      if (r.color) { const k = el("span", { class: "k" }); k.style.background = r.color; left.appendChild(k); }
      left.appendChild(document.createTextNode(r.label));
      row.appendChild(left);
      row.appendChild(el("b", {}, r.value));
      t.appendChild(row);
    }
    t.hidden = false;
    const w = t.offsetWidth, h = t.offsetHeight;
    t.style.left = Math.max(8, Math.min(x + 14, window.innerWidth - w - 8)) + "px";
    t.style.top = Math.max(8, y - h - 12) + "px";
  }
  const hideTip = () => { if (tip) tip.hidden = true; };

  function niceTicks(a, b, n) {
    const span = b - a || 1, step0 = span / n, mag = Math.pow(10, Math.floor(Math.log10(step0)));
    const step = [1, 2, 2.5, 5, 10].map((c) => c * mag).find((c) => span / c <= n) || 10 * mag;
    const out = [];
    for (let v = Math.ceil(a / step - 1e-9) * step; v <= b + 1e-9; v += step) out.push(+v.toFixed(10));
    return out;
  }

  /* ---------- 표로 보기 ---------- */
  function tableView(container, headers, rows, summary = "표로 보기") {
    const d = el("details", { class: "tableview" });
    d.appendChild(el("summary", {}, summary));
    const t = el("table", { class: "data" });
    const tr = el("tr");
    headers.forEach((h, i) => tr.appendChild(el("th", { class: i ? "num" : "" }, h)));
    t.appendChild(el("thead")).appendChild(tr);
    const tb = el("tbody");
    for (const r of rows) {
      const row = el("tr");
      r.forEach((c, i) => row.appendChild(el("td", { class: i ? "num" : "" }, String(c))));
      tb.appendChild(row);
    }
    t.appendChild(tb);
    d.appendChild(t);
    container.appendChild(d);
  }

  /* ---------- 범례 ---------- */
  function legend(items) {
    const lg = el("div", { class: "legend" });
    for (const it of items) {
      const i = el("span");
      const k = el("span", { class: "key" + (it.rect ? " rect" : "") });
      k.style.background = it.color;
      if (it.thin) k.style.height = "1px";
      i.appendChild(k);
      i.appendChild(document.createTextNode(it.label));
      lg.appendChild(i);
    }
    return lg;
  }

  /* ---------- 선 차트 ----------
   * series: [{name, color, points:[{x:number, y:number|null}], markers?, area?, width?, endLabel?}]
   * opts: {height, y0, y1, fmtX, fmtY, xTicks, refY, label, onPick(x), marker:{x}} */
  function lineChart(container, series, opts = {}) {
    container.replaceChildren();
    const W = chartWidth(container), H = opts.height || 220, m = { l: 48, r: opts.rightPad ?? 16, t: 12, b: 28 };
    const xs = series.flatMap((s) => s.points.map((p) => +p.x));
    const ys = series.flatMap((s) => s.points.map((p) => p.y)).filter((v) => v != null);
    if (!xs.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return null; }
    const x0 = Math.min(...xs), x1 = Math.max(...xs);
    let y0 = opts.y0 ?? Math.min(0, ...ys), y1 = opts.y1 ?? Math.max(...ys);
    if (y1 === y0) y1 = y0 + 1;
    if (opts.y1 == null) y1 += (y1 - y0) * 0.08;
    const sx = (v) => m.l + ((v - x0) / (x1 - x0 || 1)) * (W - m.l - m.r);
    const sy = (v) => m.t + (1 - (v - y0) / (y1 - y0)) * (H - m.t - m.b);
    const svg = el("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" });
    const grid = el("svg:g", { class: "grid" });
    for (const t of niceTicks(y0, y1, 4)) {
      grid.appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(t), y2: sy(t) }));
      svg.appendChild(el("svg:text", { x: m.l - 6, y: sy(t) + 3, "text-anchor": "end" }, opts.fmtY ? opts.fmtY(t) : fmtN(t, 2)));
    }
    svg.insertBefore(grid, svg.firstChild);
    const base = sy(Math.max(y0, Math.min(0, y1)));
    svg.appendChild(el("svg:g", { class: "axis" })).appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: base, y2: base }));
    const xt = opts.xTicks ?? 5;
    for (let i = 0; i <= xt; i++) {
      const v = x0 + ((x1 - x0) * i) / xt;
      svg.appendChild(el("svg:text", { x: sx(v), y: H - 8, "text-anchor": i === 0 ? "start" : i === xt ? "end" : "middle" }, opts.fmtX ? opts.fmtX(v) : fmtN(v)));
    }
    if (opts.refY != null) svg.appendChild(el("svg:line", { x1: m.l, x2: W - m.r, y1: sy(opts.refY), y2: sy(opts.refY), stroke: "var(--axis)", "stroke-width": 1 }));
    for (const s of series) {
      const pts = s.points.filter((p) => p.y != null);
      if (!pts.length) continue;
      const d = pts.map((p, i) => `${i ? "L" : "M"}${sx(+p.x).toFixed(1)},${sy(p.y).toFixed(1)}`).join("");
      if (s.area) svg.appendChild(el("svg:path", { class: "area", fill: s.color, d: d + `L${sx(+pts[pts.length - 1].x)},${base}L${sx(+pts[0].x)},${base}Z` }));
      svg.appendChild(el("svg:path", { class: "line", stroke: s.color, "stroke-width": s.width || 2, d }));
      if (s.markers) for (const p of pts) svg.appendChild(el("svg:circle", { class: "marker", cx: sx(+p.x), cy: sy(p.y), r: 4, fill: s.color }));
      if (s.endLabel) {
        const last = pts[pts.length - 1];
        svg.appendChild(el("svg:text", { x: sx(+last.x) + 8, y: sy(last.y) + 4, class: "endlabel" }, s.endLabel(last)));
      }
    }
    let pick = null;
    if (opts.marker != null) {
      const mx = sx(opts.marker);
      svg.appendChild(el("svg:line", { x1: mx, x2: mx, y1: m.t, y2: H - m.b, stroke: "var(--text-primary)", "stroke-width": 1, "stroke-opacity": 0.28 }));
    }
    const cross = el("svg:line", { class: "crosshair", y1: m.t, y2: H - m.b, visibility: "hidden" });
    svg.appendChild(cross);
    const hit = el("svg:rect", { class: "hit", x: m.l, y: m.t, width: W - m.l - m.r, height: H - m.t - m.b, tabindex: "0" });
    const nearest = (clientX) => {
      const r = svg.getBoundingClientRect();
      const xv = x0 + (((clientX - r.left) * W) / r.width - m.l) / (W - m.l - m.r) * (x1 - x0);
      let best = null, bd = Infinity;
      for (const p of series[0].points) { const dd = Math.abs(+p.x - xv); if (dd < bd) { bd = dd; best = p; } }
      return best;
    };
    const rowsAt = (x) => series.map((s) => { const q = s.points.find((p) => +p.x === +x); return { label: s.name, color: s.color, value: q && q.y != null ? (opts.fmtY ? opts.fmtY(q.y) : fmtN(q.y, 2)) : "–" }; });
    hit.addEventListener("pointermove", (ev) => {
      const b = nearest(ev.clientX);
      if (!b) return;
      cross.setAttribute("x1", sx(+b.x)); cross.setAttribute("x2", sx(+b.x)); cross.setAttribute("visibility", "visible");
      showTip(ev.clientX, ev.clientY, opts.fmtX ? opts.fmtX(+b.x) : String(b.x), rowsAt(b.x));
    });
    hit.addEventListener("pointerleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
    if (opts.onPick) hit.addEventListener("click", (ev) => { const b = nearest(ev.clientX); if (b) opts.onPick(+b.x); });
    svg.appendChild(hit);
    if (series.length > 1) container.appendChild(legend(series.map((s) => ({ label: s.name, color: s.color, thin: s.width === 1 }))));
    container.appendChild(svg);
    if (opts.table) tableView(container, opts.table.headers, opts.table.rows);
    return pick;
  }

  /* ---------- 가로 막대 ----------
   * rows: [{label, value, color?, sub?, lo?, hi?, note?}] — 음수 허용(발산), lo/hi 가 있으면 신뢰구간 수염 */
  function hbars(container, rows, opts = {}) {
    container.replaceChildren();
    if (!rows.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return; }
    const W = chartWidth(container), bh = opts.barHeight || 18, gap = opts.gap || 10, labelW = Math.min(opts.labelW || 150, Math.round(W * 0.46)), valueW = opts.valueW || 74, H = rows.length * (bh + gap) + 6;
    const svg = el("svg:svg", { class: "chart", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": opts.label || "" });
    const vals = rows.flatMap((r) => [r.value, r.hi ?? r.value]);
    const neg = Math.min(0, ...rows.map((r) => r.value)), pos = Math.max(opts.max ?? 0, ...vals);
    const x0 = labelW, x1 = W - valueW, sx = (v) => x0 + ((v - neg) / (pos - neg || 1)) * (x1 - x0), zero = sx(0);
    svg.appendChild(el("svg:line", { x1: zero, x2: zero, y1: 0, y2: H, stroke: "var(--axis)" }));
    rows.forEach((r, i) => {
      const y = 3 + i * (bh + gap), w = Math.max(1, Math.abs(sx(r.value) - zero)), rx = 4;
      const color = r.color || (r.value < 0 ? "var(--div-neg)" : opts.diverging ? "var(--div-pos)" : "var(--series-1)");
      const d = r.value >= 0
        ? `M${zero},${y}h${Math.max(0, w - rx)}a${rx},${rx} 0 0 1 ${rx},${rx}v${bh - 2 * rx}a${rx},${rx} 0 0 1 -${rx},${rx}h-${Math.max(0, w - rx)}z`
        : `M${zero},${y}h-${Math.max(0, w - rx)}a${rx},${rx} 0 0 0 -${rx},${rx}v${bh - 2 * rx}a${rx},${rx} 0 0 0 ${rx},${rx}h${Math.max(0, w - rx)}z`;
      const p = el("svg:path", { d, fill: color, class: "bar-mark", tabindex: "0" });
      const tipRows = [{ label: opts.valueName || "값", value: opts.fmt ? opts.fmt(r.value) : fmtN(r.value, 3) }];
      if (r.lo != null) tipRows.push({ label: "95% 신뢰구간", value: `${opts.fmt ? opts.fmt(r.lo) : r.lo} ~ ${opts.fmt ? opts.fmt(r.hi) : r.hi}` });
      if (r.sub) tipRows.push({ label: "", value: r.sub });
      const show = (ev) => { const b = (ev.currentTarget || p).getBoundingClientRect(); showTip(ev.clientX || b.left + b.width / 2, ev.clientY || b.top, r.label, tipRows); };
      p.addEventListener("pointermove", show); p.addEventListener("focus", show);
      p.addEventListener("pointerleave", hideTip); p.addEventListener("blur", hideTip);
      svg.appendChild(p);
      if (r.lo != null && r.hi != null) {
        const cy = y + bh / 2;
        const g = el("svg:g", { stroke: "var(--text-secondary)", "stroke-width": 1.5 });
        g.appendChild(el("svg:line", { x1: sx(r.lo), x2: sx(r.hi), y1: cy, y2: cy }));
        g.appendChild(el("svg:line", { x1: sx(r.lo), x2: sx(r.lo), y1: cy - 4, y2: cy + 4 }));
        g.appendChild(el("svg:line", { x1: sx(r.hi), x2: sx(r.hi), y1: cy - 4, y2: cy + 4 }));
        svg.appendChild(g);
      }
      const maxChars = Math.max(8, Math.floor((labelW - 10) / 7.2)), lab = r.label.length > maxChars ? r.label.slice(0, maxChars - 1) + "…" : r.label;
      svg.appendChild(el("svg:text", { x: labelW - 8, y: y + bh / 2 + 4, "text-anchor": "end", class: "rowlabel" }, lab));
      const tx = (r.hi != null ? sx(r.hi) : r.value >= 0 ? sx(r.value) : sx(r.value)) + (r.value >= 0 ? 8 : -8);
      svg.appendChild(el("svg:text", { x: tx, y: y + bh / 2 + 4, "text-anchor": r.value >= 0 ? "start" : "end", class: "valuelabel" }, opts.fmt ? opts.fmt(r.value) : fmtN(r.value, 3)));
    });
    container.appendChild(svg);
    if (opts.table !== false) tableView(container, ["항목", opts.valueName || "값", ...(rows.some((r) => r.lo != null) ? ["95% 신뢰구간", "n"] : [])],
      rows.map((r) => [r.label, opts.fmt ? opts.fmt(r.value) : fmtN(r.value, 3), ...(r.lo != null ? [`${opts.fmt ? opts.fmt(r.lo) : r.lo} ~ ${opts.fmt ? opts.fmt(r.hi) : r.hi}`, r.note ?? ""] : [])]));
  }

  /* ---------- 표 ---------- */
  function table(container, cols, rows, onRow) {
    container.replaceChildren();
    if (!rows.length) { container.appendChild(el("div", { class: "empty" }, "데이터 없음")); return; }
    const t = el("table", { class: "data" });
    const tr = el("tr");
    for (const c of cols) tr.appendChild(el("th", { class: (c.num ? "num " : "") + (c.nowrap ? "nowrap" : "") }, c.h));
    t.appendChild(el("thead")).appendChild(tr);
    const tb = el("tbody");
    for (const r of rows) {
      const row = el("tr", { class: onRow ? "clickable" : "", tabindex: onRow ? "0" : null });
      for (const c of cols) {
        const td = el("td", { class: (c.num ? "num " : "") + (c.nowrap ? "nowrap" : "") });
        const v = c.render ? c.render(r) : r[c.k];
        if (v instanceof Node) td.appendChild(v); else td.textContent = v == null ? "–" : String(v);
        row.appendChild(td);
      }
      if (onRow) {
        row.addEventListener("click", () => onRow(r));
        row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onRow(r); } });
      }
      tb.appendChild(row);
    }
    t.appendChild(tb);
    container.appendChild(t);
  }

  /* ---------- 작은 부품 ---------- */
  function pbar(p, max = 0.5, width = 110) {
    const wrap = el("span", { class: "pbar" });
    const tr = el("span", { class: "bar-track" });
    tr.style.width = width + "px";
    const b = el("span", { class: "bar" });
    b.style.width = Math.max(2, Math.min(1, p / max) * width) + "px";
    tr.appendChild(b);
    wrap.appendChild(tr);
    wrap.appendChild(document.createTextNode(fmtP(p)));
    return wrap;
  }
  function badge(kind, text) {
    const b = el("span", { class: `badge ${kind}` });
    b.appendChild(el("span", { class: "dot", "aria-hidden": "true" }));
    b.appendChild(document.createTextNode(text));
    return b;
  }
  function tile(label, value, sub, subCls) {
    const t = el("div", { class: "tile" });
    t.appendChild(el("div", { class: "label" }, label));
    t.appendChild(el("div", { class: "value" }, value));
    if (sub) t.appendChild(el("div", { class: `delta ${subCls || ""}` }, sub));
    return t;
  }
  /* 메모 구간 → DOM. kind: strong/weak/symptom/null */
  function memoSpans(segments) {
    const frag = document.createDocumentFragment();
    for (const s of segments) {
      if (!s.kind) { frag.appendChild(document.createTextNode(s.text)); continue; }
      const label = { strong: "강한 강도어", weak: "약한 강도어", symptom: "증상어" }[s.kind];
      frag.appendChild(el("mark", { class: `m-${s.kind}`, title: label }, s.text));
    }
    return frag;
  }

  root.HarbingerCharts = { el, fmtN, fmtP, showTip, hideTip, lineChart, hbars, table, tableView, legend, pbar, badge, tile, memoSpans, niceTicks };
})(typeof self !== "undefined" ? self : this);
