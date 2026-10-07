/* harbinger 콘솔 — 정적 데모(미리 계산한 JSON)와 라이브 API 가 같은 코드 경로를 쓴다. 차트는 charts.js, 메모 분석은 memo.js. */
(function () {
  "use strict";
  const C = window.HarbingerCharts, M = window.HarbingerMemo;
  const { el, fmtN, fmtP } = C;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const STATIC = !!window.HARBINGER_STATIC;
  const REPO = "https://github.com/sokldjs554/harbinger";
  const KO = { chiller: "냉동기", ahu: "공조기", pump: "펌프", boiler: "보일러", elevator: "승강기", generator: "비상발전기", switchgear: "수배전반", fire_pump: "소방펌프", cooling_tower: "냉각탑", exhaust_fan: "환풍기", auto_door: "자동문", water_tank: "급수탱크" };
  const OV = ["양호", "주의", "불량"];
  const WO_KO = { breakdown: "고장수리", preventive: "예방정비", parts: "부품교체" };
  const state = { site: null, siteName: "", asof: null, k: 10, tab: "today", ctx: null, assetId: null, scope: "all", weekIdx: null, scn: "B", loaded: {} };
  const cache = new Map();
  const whatifCache = new Map();

  /* ---------- API ---------- */
  const slug = (p) => p.replace(/^\//, "").replace(/\?/g, "__").replace(/&/g, "_").replace(/=/g, "-").replace(/\//g, "_");
  async function api(path, init) {
    if (!init && cache.has(path)) return cache.get(path);
    const r = await fetch(STATIC ? `api/${slug(path)}.json` : path, init);
    if (!r.ok) { const e = new Error(`${path} → ${r.status}`); e.status = r.status; throw e; }
    const j = await r.json();
    if (!init) cache.set(path, j);
    return j;
  }
  const P = {
    summary: () => `/v1/sites/${state.site}?as_of=${state.asof}`,
    patrol: () => `/v1/sites/${state.site}/patrol/today?as_of=${state.asof}&k=${state.k}`,
    assets: () => `/v1/sites/${state.site}/assets?as_of=${state.asof}&limit=15`,
    risk: (a) => `/v1/sites/${state.site}/assets/${a}/risk?as_of=${state.asof}`,
    energy: () => `/v1/sites/${state.site}/energy/anomalies?as_of=${state.asof}&days=120`,
    quality: () => `/v1/sites/${state.site}/quality?as_of=${state.asof}`,
    replay: (site) => `/v1/replay?site=${site}&k=${state.k}`,
  };
  async function ensureLex() {
    if (!state.ctx) state.ctx = M.build(await api("/v1/text/lexicon"));
    return state.ctx;
  }
  const memoDom = (text) => (state.ctx ? C.memoSpans(M.segments(state.ctx, text || "")) : document.createTextNode(text || ""));
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* 저장 불가 환경 */ } },
  };
  const shortDate = (iso) => (iso || "").slice(5, 10);
  const pp = (v) => `${v >= 0 ? "+" : "−"}${Math.abs(v * 100).toFixed(1)}%p`;
  const clear = (n) => n.replaceChildren();

  /* ---------- 탭 ---------- */
  const loaders = {};
  function openTab(name, push = true) {
    state.tab = name;
    $$("nav.tabs button").forEach((b) => b.setAttribute("aria-selected", b.dataset.tab === name ? "true" : "false"));
    $$("main > section.tab").forEach((s) => { s.hidden = s.id !== `tab-${name}`; });
    if (push) { try { history.replaceState(null, "", `#${name}`); } catch (e) { /* file:// 등 */ } }
    refresh();
  }
  async function refresh() {
    const key = `${state.site}|${state.asof}|${state.k}|${state.scope}`;
    if (state.loaded[state.tab] === key) return;
    const sec = $(`#tab-${state.tab}`);
    sec.classList.add("loading");
    try { await loaders[state.tab](); state.loaded[state.tab] = key; }
    catch (e) { console.error(e); sec.appendChild(el("div", { class: "empty err" }, `불러오지 못했습니다: ${e.message}`)); }
    sec.classList.remove("loading");
  }

  /* ---------- 오늘 + 현장 앱 ---------- */
  loaders.today = async function () {
    await ensureLex();
    const [s, p] = await Promise.all([api(P.summary()), api(P.patrol())]);
    const items = p.items;
    const rr = p.expected_breakdowns_round_robin, ex = p.expected_breakdowns_in_list;
    const lift = rr > 0 ? ex / rr : null;
    const head = $("#today-head"); clear(head);
    head.appendChild(el("h2", {}, `${s.name} — 오늘 먼저 볼 설비 ${items.length}개`));
    head.appendChild(el("p", {}, `기준 ${state.asof}. 모델이 보는 이 목록의 기대 고장은 ${fmtN(ex, 2)}건, 가장 오래 안 본 ${p.k}개를 보면 ${fmtN(rr, 2)}건${lift ? ` (×${lift.toFixed(1)})` : ""}. 이것은 모델의 기대치일 뿐 결과가 아닙니다 — 실제로 맞았는지는 “과거 재현” 탭에서 봅니다.`));
    const k = $("#today-kpis"); clear(k);
    k.appendChild(C.tile("설비 수", fmtN(s.n_assets), `최근 120일 안에 점검된 설비 ${s.assets_with_recent_inspection}개`));
    k.appendChild(C.tile("30일 고장확률 평균", fmtP(s.mean_p30)));
    k.appendChild(C.tile("고위험 설비 (P30 ≥ 15 %)", fmtN(s["n_high_risk(p30>=0.15)"])));
    k.appendChild(C.tile("최근 90일 비계획 고장", fmtN(s.breakdowns_90d), `다운타임 ${fmtN(s.downtime_hours_90d)}시간`));

    C.table($("#today-table"), [
      { h: "#", k: "rank", num: true },
      { h: "설비", render: (r) => { const d = el("div"); d.appendChild(el("b", {}, r.name)); d.appendChild(el("div", { class: "muted" }, `${r.zone} · ${KO[r.category] || r.category}`)); const m = el("div", { class: "memo-snip" }); m.appendChild(document.createTextNode(`${shortDate(r.last_inspected_at)} ${OV[r.last_overall]} · `)); m.appendChild(memoDom(r.last_memo)); d.appendChild(m); return d; } },
      { h: "P30", render: (r) => C.pbar(r.p30), nowrap: true },
      { h: "", render: (r) => (r.mandatory ? C.badge("legal", "법정점검 기한") : r.p30 >= 0.15 ? C.badge("urgent", "고위험") : document.createTextNode("")) },
      { h: "근거", render: (r) => el("div", { class: "reasons" }, (r.reasons || []).slice(0, 3).join(" · ")) },
    ], items, (r) => { focusPhone(r.asset_id); });
    renderPhone(s, p);
  };
  const doneKey = () => `harbinger:done:${state.site}:${state.asof}`;
  function loadDone() { try { return new Set(JSON.parse(store.get(doneKey()) || "[]")); } catch (e) { return new Set(); } }
  function renderPhone(s, p) {
    const done = loadDone();
    $("#ph-title").textContent = `오늘 순찰 · ${s.name}`;
    $("#ph-sub").textContent = `${p.items.length}개 · 동선 순(지하 → 고층)`;
    const list = $("#ph-list"); clear(list);
    const upd = () => { $("#ph-prog").style.width = `${(done.size / Math.max(1, p.items.length)) * 100}%`; };
    for (const it of p.items) {
      const card = el("div", { class: "pcard" + (done.has(it.asset_id) ? " done" : ""), id: `pc-${it.asset_id}` });
      const head = el("div", { class: "head", role: "button", tabindex: "0", "aria-expanded": "false" });
      head.appendChild(el("span", { class: "rank" }, String(it.rank)));
      const nm = el("div"); nm.appendChild(el("div", { class: "nm" }, it.name)); nm.appendChild(el("div", { class: "zn" }, `${it.zone} · ${KO[it.category] || it.category}`));
      head.appendChild(nm); head.appendChild(el("div", { class: "pp" }, fmtP(it.p30, 0)));
      card.appendChild(head);
      const bd = el("div", { class: "badges" });
      if (it.mandatory) bd.appendChild(C.badge("legal", "법정점검 기한"));
      else if (it.p30 >= 0.15) bd.appendChild(C.badge("urgent", "고위험"));
      bd.appendChild(C.badge("quiet", `${Math.round(it.days_since_inspection)}일 전 점검 · ${OV[it.last_overall]}`));
      card.appendChild(bd);
      const memo = el("div", { class: "memo" });
      memo.appendChild(el("small", {}, `최근 점검 메모 (${shortDate(it.last_inspected_at)})`));
      memo.appendChild(memoDom(it.last_memo));
      card.appendChild(memo);
      const more = el("div", { class: "more", hidden: "" });
      more.appendChild(el("div", {}, "왜 이 설비인가"));
      const ul = el("ul"); (it.reasons || []).forEach((r) => ul.appendChild(el("li", {}, r))); more.appendChild(ul);
      card.appendChild(more);
      const foot = el("div", { class: "foot" });
      const lab = el("label"); const cb = el("input", { type: "checkbox" }); cb.checked = done.has(it.asset_id);
      cb.addEventListener("change", () => { if (cb.checked) done.add(it.asset_id); else done.delete(it.asset_id); card.classList.toggle("done", cb.checked); store.set(doneKey(), JSON.stringify([...done])); upd(); });
      lab.appendChild(cb); lab.appendChild(document.createTextNode(" 확인함")); foot.appendChild(lab);
      const det = el("button", { type: "button" }, "설비 상세 →"); det.addEventListener("click", () => openAsset(it.asset_id)); foot.appendChild(det);
      card.appendChild(foot);
      const toggle = () => { const open = more.hidden; more.hidden = !open; head.setAttribute("aria-expanded", String(open)); };
      head.addEventListener("click", toggle);
      head.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      list.appendChild(card);
    }
    upd();
  }
  function focusPhone(id) {
    const c = document.getElementById(`pc-${id}`); if (!c) return;
    c.scrollIntoView({ block: "nearest", behavior: "smooth" });
    const more = $(".more", c); if (more.hidden) $(".head", c).click();
    c.style.outline = "2px solid var(--series-1)"; setTimeout(() => { c.style.outline = ""; }, 1400);
  }
  function openAsset(id) { state.assetId = id; state.loaded.assets = null; openTab("assets"); }

  /* ---------- 과거 재현 ---------- */
  loaders.replay = async function () {
    const all = state.scope === "all";
    $("#scope-all").setAttribute("aria-pressed", String(all)); $("#scope-site").setAttribute("aria-pressed", String(!all));
    $("#scope-site").textContent = state.siteName ? `이 사이트 (${state.siteName})` : "이 사이트";
    const data = await api(P.replay(all ? "all" : state.site));
    const weeks = data.weeks, sm = data.summary;
    $("#replay-scope-note").textContent = all ? `${data.n_sites ?? "전체"}개 사이트 합산 · 주마다 사이트별 상위 ${data.k}개` : `표본이 작아(${sm.harbinger_picks}건) 주마다 크게 흔들립니다 — 전체 사이트와 함께 읽으세요`;
    const kp = $("#replay-kpis"); clear(kp);
    kp.appendChild(C.tile(`harbinger 상위 ${data.k} 적중률`, fmtP(sm.harbinger_rate), `${sm.harbinger_hits} / ${sm.harbinger_picks}건 · ${sm.weeks}주`));
    kp.appendChild(C.tile("라운드로빈 (가장 오래 안 본 순)", fmtP(sm.round_robin_rate), `${sm.round_robin_hits} / ${sm.round_robin_picks}건`));
    const vsBase = sm.lift_vs_base ? ` · 무작위 대비 ×${sm.lift_vs_base.toFixed(1)}` : "";
    kp.appendChild(C.tile("라운드로빈 대비", sm.lift_vs_round_robin ? `×${sm.lift_vs_round_robin.toFixed(1)}` : "–", `같은 주·같은 사이트에서 K 개씩${vsBase}`, sm.lift_vs_round_robin > 1 ? "good" : ""));
    kp.appendChild(C.tile("무작위로 골랐을 때", fmtP(sm.base_rate), "기본 고장률 (설비 하나가 30일 안에 고장날 확률)"));
    const slider = $("#replay-week");
    slider.max = String(weeks.length - 1);
    if (state.weekIdx == null || state.weekIdx > weeks.length - 1) state.weekIdx = weeks.length - 1;
    slider.value = String(state.weekIdx);
    const draw = () => {
      const t = (w) => Date.parse(w.as_of);
      const rate = (w, who) => (w[who].n ? w[who].hits / w[who].n : null);
      C.lineChart($("#replay-chart"), [
        { name: "harbinger 상위 K", color: "var(--series-1)", markers: true, endLabel: (pt) => fmtP(pt.y, 0), points: weeks.map((w) => ({ x: t(w), y: rate(w, "harbinger") })) },
        { name: "라운드로빈 상위 K", color: "var(--muted)", width: 2, endLabel: (pt) => fmtP(pt.y, 0), points: weeks.map((w) => ({ x: t(w), y: rate(w, "round_robin") })) },
        { name: "기본 고장률(무작위)", color: "var(--axis)", width: 1, points: weeks.map((w) => ({ x: t(w), y: w.base_rate })) },
      ], {
        height: 240, y0: 0, fmtY: (v) => fmtP(v, 0), fmtX: (v) => new Date(v).toISOString().slice(5, 10), xTicks: Math.min(6, weeks.length - 1), rightPad: 44,
        label: "주별 적중률", marker: t(weeks[state.weekIdx]), onPick: (x) => { const i = weeks.findIndex((w) => t(w) === x); if (i >= 0) { state.weekIdx = i; slider.value = String(i); draw(); } },
        table: { headers: ["주", "harbinger 적중/선택", "라운드로빈 적중/선택", "기본 고장률"], rows: weeks.map((w) => [w.as_of, `${w.harbinger.hits}/${w.harbinger.n}`, `${w.round_robin.hits}/${w.round_robin.n}`, fmtP(w.base_rate)]) },
      });
      drawDetail();
    };
    const drawDetail = () => {
      const w = weeks[state.weekIdx], box = $("#replay-detail"); clear(box);
      if (all) {
        const c = el("div", { class: "card" }); c.appendChild(el("h2", {}, `${w.as_of} 기준 주 — 전체 사이트 합산`));
        c.appendChild(el("p", {}, `harbinger 가 고른 ${w.harbinger.n}개 중 ${w.harbinger.hits}개(${fmtP(w.harbinger.n ? w.harbinger.hits / w.harbinger.n : 0)})가 이후 30일 안에 고장났고, 라운드로빈이 고른 ${w.round_robin.n}개 중에는 ${w.round_robin.hits}개(${fmtP(w.round_robin.n ? w.round_robin.hits / w.round_robin.n : 0)})였습니다.`));
        c.appendChild(el("p", { class: "muted" }, "“이 사이트” 로 범위를 바꾸면 그 주에 뽑힌 설비 목록과 실제 결과를 볼 수 있습니다."));
        box.appendChild(c); return;
      }
      const cols = el("div", { class: "replay-cols" });
      const col = (title, who, sub) => {
        const c = el("div", { class: "card" }); c.appendChild(el("h2", {}, `${title} — ${w[who].hits}개가 30일 안에 고장`));
        c.appendChild(el("div", { class: "sub" }, sub));
        const ul = el("ul", { class: "rlist" });
        for (const it of w[who].items) {
          const li = el("li"); const l = el("div"); l.appendChild(el("div", { class: "nm" }, it.name));
          l.appendChild(el("div", { class: "zn" }, `${it.zone} · ${KO[it.category] || it.category} · P30 ${fmtP(it.p30, 0)} · ${Math.round(it.days_since_inspection)}일 전 점검${it.mandatory ? " · 법정" : ""}`));
          const r = el("div", { class: "rs" }); r.appendChild(it.failed_within_30d ? C.badge("fail", `${Math.round(it.days_to_failure)}일 뒤 고장`) : C.badge("quiet", "고장 없음"));
          li.appendChild(l); li.appendChild(r); ul.appendChild(li);
        }
        c.appendChild(ul); return c;
      };
      cols.appendChild(col("harbinger 상위 K", "harbinger", `${w.as_of} 기준. 위험 순(P30). 법정점검 기한 임박은 무조건 포함.`));
      cols.appendChild(col("라운드로빈 상위 K", "round_robin", "가장 오래 안 본 설비부터 — 현장의 기본 규칙을 단순화한 비교군."));
      box.appendChild(cols);
    };
    slider.oninput = () => { state.weekIdx = +slider.value; draw(); };
    $("#scope-all").onclick = () => { state.scope = "all"; state.weekIdx = null; state.loaded.replay = null; refresh(); };
    $("#scope-site").onclick = () => { state.scope = "site"; state.weekIdx = null; state.loaded.replay = null; refresh(); };
    $("#replay-caveat").textContent = `읽을 때 주의: 라운드로빈(${fmtP(sm.round_robin_rate)})은 무작위(${fmtP(sm.base_rate)})보다도 낮습니다 — 가장 오래 안 본 설비는 점검 주기가 긴 법정·저위험 설비로 쏠리기 때문이라 ‘라운드로빈 대비’ 배수는 부풀려 보이기 쉽습니다. 무작위 대비 배수를 함께 보세요. 합성 데이터입니다. 점수에는 각 주의 기준일 이전 데이터만 쓰였지만(점검 뒤 생긴 고장·정비는 반영), 라운드로빈은 현장 규칙을 단순화한 대리 비교군이라 실제 현장이 더 똑똑할 수 있습니다. ${weeks.length}주 × ${all ? "25개 사이트" : "1개 사이트"}이며 기간 시작 ${data.heldout_start} 이후만 봅니다.`;
    draw();
  };

  /* ---------- 설비 + What-if ---------- */
  loaders.assets = async function () {
    await ensureLex();
    const [s, a] = await Promise.all([api(P.summary()), api(P.assets())]);
    C.hbars($("#cat-bars"), (s.by_category || []).slice().sort((x, y) => y.mean - x.mean).map((c) => ({ label: `${KO[c.category] || c.category} (${c.count})`, value: c.mean })), { fmt: (v) => fmtP(v), valueName: "평균 P30", labelW: 120, table: false, barHeight: 14, gap: 7 });
    C.table($("#asset-table"), [
      { h: "설비", render: (r) => { const d = el("div"); d.appendChild(el("b", {}, r.name)); d.appendChild(el("div", { class: "muted" }, `${r.zone} · ${KO[r.category] || r.category} · ${r.age_years}년`)); return d; } },
      { h: "P30", render: (r) => C.pbar(r.p30), nowrap: true },
      { h: "마지막 판정", render: (r) => OV[r.last_overall], nowrap: true },
    ], a.assets, (r) => showAsset(r.asset_id));
    if (state.assetId) showAsset(state.assetId); else { clear($("#asset-detail")); $("#asset-detail").append(el("h2", {}, "설비 상세"), el("div", { class: "empty" }, "왼쪽에서 설비를 선택하세요.")); }
  };
  async function showAsset(id) {
    state.assetId = id;
    $$("#asset-table tr.clickable").forEach((tr) => tr.classList.remove("selected"));
    const box = $("#asset-detail"); box.classList.add("loading");
    let r;
    try { r = await api(P.risk(id)); } catch (e) { box.classList.remove("loading"); clear(box); box.appendChild(el("div", { class: "empty err" }, `불러오지 못했습니다: ${e.message}`)); return; }
    box.classList.remove("loading"); clear(box);
    const head = el("div", { class: "detail-head" }); head.appendChild(el("h2", {}, `${r.name} · ${KO[r.category] || r.category}`));
    head.appendChild(el("span", { class: "muted" }, `${r.zone} · 중요도 ${r.criticality} · 마지막 점검 ${r.last_inspection_at.slice(0, 10)}`)); box.appendChild(head);
    const hero = el("div", { class: "hero" }, fmtP(r.p30)); hero.appendChild(el("small", {}, "30일 내 비계획 고장 확률" + (r.p30_deep != null ? ` · 위험 네트 ${fmtP(r.p30_deep)}` : ""))); box.appendChild(hero);
    const rec = r.recommendation, dl = el("dl", { class: "dl" });
    const add = (a, b) => { dl.appendChild(el("dt", {}, a)); dl.appendChild(el("dd", {}, b)); };
    add("권고 점검 주기", `${rec.recommended_interval_days}일` + (rec.legal_max_days ? ` (법정 상한 ${rec.legal_max_days}일)` : "") + (rec.urgent ? " · 즉시 점검 권고" : ""));
    add("산출 방식", rec.basis === "survival_curve" ? "생존곡선(위험 네트)에서 5 % 위험 예산" : "일정 위험 근사"); box.appendChild(dl);

    const ev = r.explanation && r.explanation.evidence;
    if (ev) {
      box.appendChild(el("h3", {}, "최근 점검 메모 원문"));
      const wrap = el("div", { class: "evidence" });
      for (const m of ev.recent_inspections) {
        const d = el("div", { class: "memo" });
        d.appendChild(el("div", { class: "meta" }, `${m.performed_at.replace("T", " ")} · ${OV[m.overall]} · 체류 ${m.dwell_seconds}초 · ${m.inspector_id}` + (m.flagged_items.length ? ` · 지적: ${m.flagged_items.join(", ")}` : "")));
        d.appendChild(memoDom(m.memo)); wrap.appendChild(d);
      }
      if (ev.recent_workorders.length) wrap.appendChild(el("div", { class: "muted", style: "font-size:12px" }, "최근 이력: " + ev.recent_workorders.map((w) => `${w.opened_at.slice(0, 10)} ${WO_KO[w.type] || w.type}`).join(" · ")));
      box.appendChild(wrap);
    }
    const wf = el("div", { id: "whatif" }); box.appendChild(wf); renderWhatIf(wf, r);

    if (r.explanation && r.explanation.contributions) {
      box.appendChild(el("h3", {}, "무엇이 확률을 올리고 내렸나 (SHAP, 로그오즈)"));
      const c = el("div"); box.appendChild(c);
      C.hbars(c, r.explanation.contributions.map((x) => ({ label: x.label, value: x.contribution, sub: x.value == null ? "결측" : `값 ${fmtN(x.value, 2)}` })), { diverging: true, fmt: (v) => (v > 0 ? "+" : "") + v.toFixed(2), valueName: "기여도", labelW: 200, table: false, barHeight: 14, gap: 7 });
    }
    if (r.survival_curve_30d_bins) {
      box.appendChild(el("h3", {}, "생존곡선 — 이후 12개월 (고장 없이 버틸 확률)"));
      const c = el("div"); box.appendChild(c);
      const pts = r.survival_curve_30d_bins.map((s, i) => ({ x: (i + 1) * 30, y: s })), lam = -Math.log(1 - r.p30) / 30;
      C.lineChart(c, [
        { name: "위험 네트 S(t)", color: "var(--series-1)", points: pts, markers: true },
        { name: "분류기 P30 을 일정 위험으로 펼친 것", color: "var(--muted)", points: pts.map((p) => ({ x: p.x, y: Math.exp(-lam * p.x) })) },
      ], { y0: 0, y1: 1, fmtX: (v) => `${Math.round(v)}일`, fmtY: (v) => fmtP(v, 0), xTicks: 4, height: 190, label: "생존곡선" });
    }
    $$("#asset-table tr.clickable").forEach((tr) => { if (tr.textContent.includes(r.name)) tr.classList.add("selected"); });
  }
  async function loadWhatIf(r) {
    const key = `${state.site}|${r.asset_id}`;
    if (whatifCache.has(key)) return whatifCache.get(key);
    let data;
    if (STATIC) data = await api(`/v1/whatif/${state.site}/${r.asset_id}`);
    else {
      const pre = await api(`/v1/sites/${state.site}/assets/${r.asset_id}/whatif/presets`);
      data = await api(`/v1/sites/${state.site}/assets/${r.asset_id}/whatif`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ scenarios: pre.scenarios }) });
    }
    whatifCache.set(key, data);
    return data;
  }
  async function renderWhatIf(box, r) {
    box.appendChild(el("h3", {}, "What-if — 마지막 점검을 다르게 기록했다면"));
    const body = el("div", { class: "muted" }, "계산 중…"); box.appendChild(body);
    let d;
    try { d = await loadWhatIf(r); }
    catch (e) {
      clear(body); body.className = "callout";
      body.textContent = e.status === 404 && STATIC ? "이 설비의 What-if 는 정적 데모에 미리 계산돼 있지 않습니다(사이트별 위험 상위 8개만). docker compose up 으로 실행하면 모든 설비에서 계산됩니다." : `계산하지 못했습니다: ${e.message}`;
      return;
    }
    clear(body); body.className = "";
    body.appendChild(el("div", { class: "sub" }, d.note));
    const b = d.baseline;
    const actual = el("div", { class: "evidence" }); const am = el("div", { class: "memo" });
    am.appendChild(el("div", { class: "meta" }, `실제 기록 · ${b.last_inspection_at.slice(0, 10)} · ${OV[b.overall]} · 체류 ${b.dwell_seconds}초 · ${b.inspector_id} → P30 ${fmtP(b.p30)}`));
    am.appendChild(memoDom(b.memo)); actual.appendChild(am); body.appendChild(actual);
    const bars = el("div"); body.appendChild(bars);
    const rows = [{ label: "실제 기록", value: b.p30, color: "var(--series-1)" }, ...d.scenarios.map((s) => ({ label: `${s.id} ${s.name}`, value: s.p30, color: "var(--series-1-soft)" }))];
    C.hbars(bars, rows, { fmt: (v) => fmtP(v), valueName: "30일 고장확률", labelW: 130, barHeight: 16, gap: 8, max: Math.max(...rows.map((x) => x.value)) * 1.05, label: "시나리오별 30일 고장확률" });
    const A = d.scenarios.find((s) => s.id === "A"), B = d.scenarios.find((s) => s.id === "B");
    if (A && B) {
      const diff = B.p30 - A.p30;
      body.appendChild(el("div", { class: "callout" }, `A 와 B 는 체크리스트가 똑같이 “전부 양호”입니다. 메모만 다른데 P30 이 ${pp(diff)} ${diff >= 0 ? "높아집니다" : "낮아집니다"}. 이 모델이 메모를 읽는 이유입니다.`));
    }
    const list = el("div"); body.appendChild(list); const chg = el("div"); body.appendChild(chg);
    const draw = () => {
      clear(list);
      for (const s of d.scenarios) {
        const row = el("div", { class: "scn" + (s.id === state.scn ? " selected" : ""), role: "button", tabindex: "0" });
        row.appendChild(el("span", { class: "id" }, s.id));
        const mid = el("div"); mid.appendChild(el("div", { class: "nm" }, s.name)); mid.appendChild(el("div", { class: "ds" }, s.description));
        const mm = el("div", { class: "mm" }); mm.appendChild(memoDom(s.memo)); mid.appendChild(mm); row.appendChild(mid);
        const pv = el("div", { class: "pv" }, fmtP(s.p30)); pv.appendChild(el("small", {}, `실제 대비 ${pp(s.delta)}`)); row.appendChild(pv);
        const pick = () => { state.scn = s.id; draw(); };
        row.addEventListener("click", pick); row.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
        list.appendChild(row);
      }
      clear(chg);
      const s = d.scenarios.find((x) => x.id === state.scn) || d.scenarios[0];
      chg.appendChild(el("div", { class: "sub" }, `시나리오 ${s.id}에서 확률을 움직인 피처 (SHAP 변화, 로그오즈)`));
      const ul = el("ul", { class: "changed" });
      if (!s.changed.length) ul.appendChild(el("li", {}, "실제 기록과 거의 같은 값입니다."));
      for (const c of s.changed) ul.appendChild(el("li", {}, `${c.label}  ${c.from == null ? "–" : fmtN(c.from, 2)} → ${c.to == null ? "–" : fmtN(c.to, 2)}`)).appendChild(el("b", {}, (c.shap_delta > 0 ? "+" : "") + c.shap_delta.toFixed(2)));
      chg.appendChild(ul);
    };
    draw();
    if (!STATIC) {
      const det = el("details", { style: "margin-top:10px" }); det.appendChild(el("summary", {}, "직접 써 보기"));
      const ta = el("textarea", { class: "memo-in", rows: "2", maxlength: "500", "aria-label": "메모" }); ta.value = "미세한 소음 있음, 간헐적으로 진동"; det.appendChild(ta);
      const sel = el("select", { "aria-label": "첫 항목 판정" }); OV.forEach((o, i) => sel.appendChild(el("option", { value: String(i) }, `첫 점검 항목 ${o}`))); det.appendChild(sel);
      const go = el("button", { type: "button", class: "btn primary", style: "margin-left:8px" }, "계산"); det.appendChild(go);
      const out = el("div", { class: "muted", style: "margin-top:6px" }); det.appendChild(out);
      go.addEventListener("click", async () => {
        out.textContent = "계산 중…";
        try {
          const pre = await api(`/v1/sites/${state.site}/assets/${r.asset_id}/whatif/presets`);
          const items = { ...pre.scenarios[0].items }; items[Object.keys(items)[0]] = +sel.value;
          const res = await api(`/v1/sites/${state.site}/assets/${r.asset_id}/whatif`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ scenarios: [{ id: "직접", name: "직접 입력", items, memo: ta.value }] }) });
          const s = res.scenarios[0]; out.textContent = `P30 ${fmtP(s.p30)} (실제 기록 대비 ${pp(s.delta)})`;
        } catch (e) { out.textContent = `실패: ${e.message}`; }
      });
      body.appendChild(det);
    }
  }

  /* ---------- 메모 읽기 ---------- */
  const PRESETS = [["형식적 메모", "특이사항 없음"], ["약신호", "약간의 소음 감지, 미세 진동 감지"], ["증상만, 강도 없음", "소음 증가, 주의 관찰 필요"], ["강신호", "누유 심함, 긴급 수리 필요"], ["섞인 메모", "정상 운전 중이나 베어링 쪽 소음 약간, 오일 번짐 미세"]];
  loaders.memo = async function () {
    const ctx = await ensureLex();
    const ta = $("#memo-in");
    if (!$("#memo-presets").children.length) {
      for (const [lab, txt] of PRESETS) { const b = el("button", { class: "chip", type: "button" }, lab); b.addEventListener("click", () => { ta.value = txt; analyze(); }); $("#memo-presets").appendChild(b); }
      ta.value = PRESETS[1][1]; ta.addEventListener("input", analyze);
    }
    function analyze() {
      const a = M.analyze(ctx, ta.value);
      const out = $("#memo-out"); clear(out);
      if (a.memo) out.appendChild(C.memoSpans(a.segments)); else out.appendChild(el("span", { class: "muted" }, "메모를 입력하세요"));
      const g = $("#memo-groups"); clear(g);
      a.groups.forEach((x) => g.appendChild(el("span", { class: "chip" }, x.label)));
      if (!a.groups.length) g.appendChild(el("span", { class: "muted" }, "감지된 증상군 없음"));
      const sc = $("#memo-scores"); clear(sc);
      for (const [l, v] of [["증상군 수", a.n_groups], ["약신호 점수", a.weak_score], ["강신호 점수", a.strong_score]]) { const d = el("div"); d.appendChild(el("div", { class: "l" }, l)); d.appendChild(el("div", { class: "v" }, String(v))); sc.appendChild(d); }
      $("#memo-reading").textContent = M.reading(a) + (a.lazy ? "" : ` (피처: tx_n_groups=${a.n_groups}, tx_weak_score=${a.weak_score}, tx_strong_score=${a.strong_score})`);
    }
    analyze();
    const sg = await api("/v1/artifacts/signals");
    $("#signals-sub").textContent = `${fmtN(sg.n_rows)}개 점검 · 기본 고장률 ${fmtP(sg.base_rate)} · ${sg.scope}`;
    const J = sg.by_judgement, jn = { good: "양호", caution: "주의", bad: "불량" }, rows = [];
    for (const k of ["good", "caution", "bad"]) {
      rows.push({ label: `${jn[k]} · 약신호 없음`, value: J[k].without_weak.rate, lo: J[k].without_weak.lo, hi: J[k].without_weak.hi, color: "var(--deemph)", note: `n=${fmtN(J[k].without_weak.n)}` });
      rows.push({ label: `${jn[k]} · 약신호 있음`, value: J[k].with_weak.rate, lo: J[k].with_weak.lo, hi: J[k].with_weak.hi, color: "var(--series-1)", note: `n=${fmtN(J[k].with_weak.n)}` });
    }
    const jbox = $("#sig-judge"); clear(jbox);
    jbox.appendChild(C.legend([{ label: "메모에 약신호 없음", color: "var(--deemph)", rect: true }, { label: "메모에 약신호 있음", color: "var(--series-1)", rect: true }]));
    const jc = el("div"); jbox.appendChild(jc);
    C.hbars(jc, rows, { fmt: (v) => fmtP(v), valueName: "30일 내 고장률", labelW: 150, barHeight: 14, gap: 8, max: 0.2, label: "판정별 고장률" });
    C.hbars($("#sig-count"), sg.good_by_weak_count.map((c) => ({ label: c.label, value: c.rate, lo: c.lo, hi: c.hi, note: `n=${fmtN(c.n)}` })), { fmt: (v) => fmtP(v), valueName: "30일 내 고장률", labelW: 90, barHeight: 14, gap: 8, max: 0.14, label: "약신호 누적별 고장률" });
    const q = [];
    for (const c of sg.good_by_inspector) q.push({ label: c.label, value: c.rate, lo: c.lo, hi: c.hi, note: `n=${fmtN(c.n)}` });
    q.push({ label: "체류 20초 미만", value: sg.good_by_dwell.short_under_20s.rate, lo: sg.good_by_dwell.short_under_20s.lo, hi: sg.good_by_dwell.short_under_20s.hi, note: `n=${fmtN(sg.good_by_dwell.short_under_20s.n)}`, color: "var(--series-2)" });
    q.push({ label: "체류 정상", value: sg.good_by_dwell.normal.rate, lo: sg.good_by_dwell.normal.lo, hi: sg.good_by_dwell.normal.hi, note: `n=${fmtN(sg.good_by_dwell.normal.n)}`, color: "var(--deemph)" });
    C.hbars($("#sig-quality"), q, { fmt: (v) => fmtP(v), valueName: "30일 내 고장률", labelW: 190, barHeight: 14, gap: 8, max: 0.11, maxLabel: 30, label: "점검 품질별 고장률" });
    const insp = sg.good_by_inspector.map((c) => fmtP(c.rate)).join(" / ");
    const cc = $("#sig-caveat"); clear(cc);
    cc.append(el("b", {}, "읽을 때 주의 "), document.createTextNode(
      `① 이 신호는 생성기가 넣은 가정입니다(“성실한 점검자는 체크리스트가 넘어가기 전에 메모에 먼저 쓴다”) — 실데이터에서 가장 먼저 다시 만들 표입니다. ② 점검자의 형식적 메모 비율로는 “양호”의 신뢰도가 갈리지 않았습니다(${insp}). 체류 20초 미만만 뚜렷했습니다. ③ 이미 “주의”·“불량”이면 약신호가 오히려 낮습니다 — 조치 절차가 이미 시작됐기 때문으로 보이며 이는 해석일 뿐입니다. ④ 신뢰구간은 설비·점검자 군집을 무시한 Wilson 구간이라 실제보다 좁습니다.`));
  };

  /* ---------- 점검 품질 ---------- */
  loaders.quality = async function () {
    const [q, sg] = await Promise.all([api(P.quality()), api("/v1/artifacts/signals")]);
    C.table($("#quality-table"), [
      { h: "점검자", k: "inspector_id" }, { h: "점검 수", k: "n_inspections", num: true },
      { h: "신뢰도", nowrap: true, render: (r) => { const w = el("span"); const m = el("span", { class: `meter ${r.reliability_score < 0.5 ? "bad" : r.reliability_score < 0.75 ? "warn" : ""}` }); const f = el("span"); f.style.width = (r.reliability_score * 100).toFixed(0) + "%"; m.appendChild(f); w.appendChild(m); w.appendChild(document.createTextNode(r.reliability_score.toFixed(2))); return w; } },
      { h: "형식적 메모", render: (r) => fmtP(r.lazy_memo_rate), num: true }, { h: "직전 메모 복사", render: (r) => fmtP(r.dup_memo_rate), num: true },
      { h: "체류 중앙값", render: (r) => `${fmtN(r.dwell_median_s)}초`, num: true }, { h: "7일 초과 지연", render: (r) => fmtP(r.delay_over_7d_rate), num: true }, { h: "전부 양호", render: (r) => fmtP(r.all_good_rate), num: true },
    ], q.inspectors || []);
    const sd = sg.good_by_dwell;
    $("#quality-note").textContent = `이 점수는 점검자를 평가하려는 것이 아니라 기록 체계를 개선하려는 것입니다. 데이터에서 실제로 확인된 것: 체류 20초 미만으로 찍은 “양호”는 30일 안에 ${fmtP(sd.short_under_20s.rate)}가 고장났고, 정상 체류의 “양호”는 ${fmtP(sd.normal.rate)}였습니다. 반면 점검자별 형식적 메모 비율로는 “양호”의 신뢰도가 갈리지 않았습니다(“메모 읽기” 탭).`;
  };

  /* ---------- 에너지 ---------- */
  loaders.energy = async function () {
    const [e, en, ab] = await Promise.all([api(P.energy()), api("/v1/artifacts/energy"), api("/v1/artifacts/ablation")]);
    const days = e.days || [], fx = (v) => new Date(v).toISOString().slice(5, 10);
    C.lineChart($("#energy-line"), [
      { name: "실측 kWh", color: "var(--series-1)", points: days.map((d) => ({ x: Date.parse(d.day), y: d.actual })) },
      { name: "기대치 kWh", color: "var(--muted)", points: days.map((d) => ({ x: Date.parse(d.day), y: d.expected })) },
    ], { fmtX: fx, fmtY: (v) => fmtN(v), y0: 0, xTicks: 6, label: "전기 사용량" });
    const zc = $("#energy-z");
    const pts = days.filter((d) => d.z != null).map((d) => ({ x: Date.parse(d.day), y: d.z }));
    C.lineChart(zc, [{ name: "잔차 7일 평균 z", color: "var(--series-1)", points: pts }], { fmtX: fx, fmtY: (v) => v.toFixed(1), refY: 2.5, xTicks: 6, height: 160, label: "z-score" });
    const an = days.filter((d) => d.anomaly);
    zc.prepend(el("div", { class: "legend" }, `이상일(z > 2.5) ${e.n_anomaly_days}일` + (an.length ? ": " + an.map((d) => d.day.slice(5)).join(", ") : "")));
    const o = en.oracle_check || {}, full = ab["full(+energy)"], noen = ab["+text+quality+history"];
    $("#energy-note").textContent = `정직하게: 이 회귀는 날씨·재실을 감안한 기대 전기량을 R² ${en.test.r2.toFixed(3)}로 잘 맞히지만(MAPE ${fmtP(en.test.mape)}), 숨은 냉방설비 열화와 여름 잔차의 상관은 ${(o.summer_corr_resid_vs_cooling_degradation ?? 0).toFixed(2)}로 약합니다. 사이트 전기량만으로는 특정 설비를 지목하지 못하고, 절제 실험에서도 에너지 피처를 더해 AUROC 가 ${full && noen ? (full.auroc - noen.auroc >= 0 ? "+" : "") + (full.auroc - noen.auroc).toFixed(3) : "–"} 만큼 움직였을 뿐입니다. 서브미터링이 있는 현장에서야 의미가 커집니다.`;
  };

  /* ---------- 모델·가정 ---------- */
  loaders.model = async function () {
    const [v, m, cal, ab] = await Promise.all([api("/version"), api("/v1/artifacts/metrics"), api("/v1/artifacts/calibration"), api("/v1/artifacts/ablation")]);
    const mi = $("#model-info"); clear(mi);
    const dl = el("dl", { class: "dl" }), add = (a, b) => { dl.appendChild(el("dt", {}, a)); dl.appendChild(el("dd", {}, b)); };
    const h = v.headline_metrics || {};
    add("모델 버전", v.model_version); add("피처 수", String(v.n_features)); add("AUROC (30일 고장)", h.auroc != null ? h.auroc.toFixed(3) : "–"); add("PR-AUC", h.pr_auc != null ? h.pr_auc.toFixed(3) : "–"); add("Brier", h.brier != null ? h.brier.toFixed(4) : "–"); add("ECE", h.ece != null ? h.ece.toFixed(4) : "–");
    add("확률 보정", m.classifier.hgb_full.calibration_method || "–");
    add("데이터", v.synthetic_data ? `합성 · seed ${v.data.seed} · ${v.data.months}개월 · 사이트 ${v.data.scale === 1 ? 25 : "축소"}` : "실데이터"); mi.appendChild(dl);
    const series = [{ name: "예측 vs 실제", color: "var(--series-1)", markers: true, points: cal.calibrated.map((r) => ({ x: r.pred_mean, y: r.obs_rate })) }];
    const mx = Math.max(0.05, ...cal.calibrated.map((r) => Math.max(r.pred_mean, r.obs_rate))) * 1.05;
    series.push({ name: "완벽", color: "var(--muted)", width: 1, points: [{ x: 0, y: 0 }, { x: mx, y: mx }] });
    C.lineChart($("#calib"), series, { y0: 0, y1: mx, fmtX: (x) => fmtP(x, 0), fmtY: (x) => fmtP(x, 0), xTicks: 4, height: 220, label: "신뢰도 다이어그램" });
    const names = { checklist_only: "체크리스트만", "+text": "+ 메모 텍스트", "+text+quality": "+ 점검 품질", "+text+quality+history": "+ 고장 이력", "full(+energy)": "+ 에너지(전체)", "full−text": "전체 − 메모", "full−quality": "전체 − 점검 품질" };
    const rows = Object.entries(ab).map(([k, x]) => ({ label: names[k] || k, value: x.auroc }));
    rows.unshift({ label: "마지막 점검 판정만", value: m.baselines.last_inspection.auroc, color: "var(--deemph)" });
    rows.push({ label: "오라클 (숨은 상태)", value: m.baselines.oracle_latent_state.auroc, color: "var(--deemph)" });
    C.hbars($("#ablation"), rows, { fmt: (x) => x.toFixed(3), valueName: "AUROC", labelW: 150, barHeight: 14, gap: 8, max: 0.9, label: "절제 실험" });
    $("#drift").appendChild(el("div", { class: "muted drift-wait" }, "계산 중…"));
    api("/v1/monitoring/drift?window_days=60").then((d) => {
      const box = $("#drift"); clear(box); const f = d.features;
      box.appendChild(el("div", { class: "muted", style: "font-size:12px;margin-bottom:6px" }, `피처 ${f.n_features}개 중 경고 ${f.n_warn} · 경보 ${f.n_alert} · 예측 평균 ${fmtP(d.predictions.mean_ref)} → ${fmtP(d.predictions.mean_cur)}`));
      const c = el("div"); box.appendChild(c);
      C.hbars(c, f.top.slice(0, 8).map((r) => ({ label: r.feature, value: r.psi, color: r.level === "alert" ? "var(--critical)" : r.level === "warn" ? "var(--warning)" : "var(--series-1)" })), { fmt: (x) => x.toFixed(3), valueName: "PSI", labelW: 190, barHeight: 12, gap: 6, table: false });
    }).catch(() => { $("#drift").textContent = "드리프트를 계산하지 못했습니다."; });
    const a = $("#assumptions"); clear(a);
    a.appendChild(el("h2", {}, "가정과 한계 — 어디까지가 데이터이고 어디부터가 가정인가"));
    const items = [
      ["메모가 체크리스트보다 먼저 움직인다", "생성기에 직접 넣은 가정입니다. “메모 읽기”의 신호와 절제 실험의 메모 기여(+0.04 안팎)는 이 가정에서 나옵니다. 실데이터에서 가장 먼저 확인할 것.", "docs/synthetic-generator.md"],
      ["고장은 열화에 의해 주도된다", "열화-고장 결합 강도(BETA_SCALE)를 모델 간 차이가 보이도록 올렸습니다. 오라클 상한이 그 선택에 달려 있습니다.", "docs/synthetic-generator.md"],
      ["불량으로 적으면 위험이 내려간다", "라벨이 “조치되지 않은 고장”이기 때문입니다 — 불량은 곧 수리로 이어집니다. What-if 의 D 시나리오가 그 결과입니다. 배포 후 재학습에서는 개입 효과를 따로 다뤄야 합니다.", "docs/limitations.md"],
      ["점검 내용은 다음 점검 때만 갱신된다", "고장·정비 이력과 시간 경과는 기준 시각에 맞춰 갱신하지만, 체크리스트·메모·점검 품질은 점검 시점 값입니다.", "docs/limitations.md"],
      ["회사에 대한 판단은 추정입니다", "유비스 마스터의 실제 DB 를 보지 못했고 공개 기사에서 역추론했습니다. 센서 계측이 있을 수 있습니다.", "docs/company-research.md"],
    ];
    const ul = el("ul");
    for (const [t, d, f] of items) { const li = el("li", { style: "margin-bottom:8px" }); li.appendChild(el("b", {}, t + " — ")); li.appendChild(document.createTextNode(d + " ")); li.appendChild(el("a", { href: `${REPO}/blob/main/${f}`, target: "_blank", rel: "noopener" }, f)); ul.appendChild(li); }
    a.appendChild(ul);
  };

  /* ---------- 초기화 ---------- */
  async function init() {
    if (!STATIC) $("#live-ctrl").hidden = false;
    const v = await api("/version");
    $("#version").textContent = `모델 ${v.model_version} · 서비스 v${v.service}${STATIC ? " · 정적 데모(미리 계산한 응답)" : ""}`;
    const s = await api("/v1/sites"), sel = $("#site");
    state.sites = s.sites;
    for (const x of s.sites) sel.appendChild(el("option", { value: x.site_id }, `${x.name} (${x.site_id}) · 설비 ${x.n_assets}`));
    state.site = s.sites[0].site_id; state.siteName = s.sites[0].name; state.asof = s.as_of.slice(0, 10);
    if (!STATIC) $("#asof").value = state.asof;
    sel.addEventListener("change", () => { state.site = sel.value; state.siteName = (s.sites.find((x) => x.site_id === sel.value) || {}).name || ""; state.assetId = null; state.weekIdx = null; state.loaded = {}; whatifCache.clear(); refresh(); });
    $("#apply").addEventListener("click", () => { state.asof = $("#asof").value || state.asof; state.k = +$("#k").value || 10; state.loaded = {}; refresh(); });
    $("#theme").addEventListener("click", () => { const r = document.documentElement, cur = r.getAttribute("data-theme"), dark = cur ? cur === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; r.setAttribute("data-theme", dark ? "light" : "dark"); });
    $$("nav.tabs button").forEach((b) => b.addEventListener("click", () => openTab(b.dataset.tab)));
    $$("[data-go]").forEach((b) => b.addEventListener("click", () => { openTab(b.dataset.go); window.scrollTo({ top: 0, behavior: "smooth" }); }));
    const guide = $("#guide");
    guide.open = store.get("harbinger:guide") !== "closed" && window.innerWidth >= 900;
    guide.addEventListener("toggle", () => store.set("harbinger:guide", guide.open ? "open" : "closed"));
    const first = (location.hash || "").slice(1);
    openTab(["today", "replay", "assets", "memo", "quality", "energy", "model"].includes(first) ? first : "today", false);
  }
  init().catch((e) => { console.error(e); $("#today-head").appendChild(el("div", { class: "empty err" }, `API 연결 실패: ${e.message}`)); });
})();
