/* Equipment workflow: real API computation or explicitly saved synthetic responses. */
"use strict";
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (value) =>
    String(value ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const date = (value) => String(value || "").slice(0, 10);
  const percent = (value) =>
    Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "계산 불가";
  const overall = (value) => ["양호", "주의", "불량"][value] ?? "기록 없음";
  const categories = {
    chiller: "냉동기",
    ahu: "공조기",
    pump: "펌프",
    boiler: "보일러",
    elevator: "승강기",
    generator: "발전기",
    switchgear: "배전반",
    fire_pump: "소방 펌프",
    cooling_tower: "냉각탑",
    exhaust_fan: "환풍기",
    auto_door: "자동문",
    water_tank: "저수조",
  };
  const pageSize = 50;
  let session,
    data,
    saved,
    detail,
    selectedRecord = 0,
    generation = 0,
    loading = false;
  let listPosition = 0,
    lastAsset = null,
    rows = [],
    requestController;
  const evidenceCache = new Map();
  const reports = window.HarbingerReports({
    esc,
    session: () => session,
    saved: () => saved,
    date: () => date(data?.as_of) || session.default_as_of,
    customer: () => $("customer").value,
    siteName,
    analyze: async (c) => {
      const r = saved
        ? saved.snapshots[`${c.as_of}|${c.site}`]
        : await liveAnalysis(c.as_of, c.site, c.k);
      if (!r)
        throw Error(
          "이 날짜와 고객사의 저장 결과가 없습니다. 제공된 조건을 선택해 주세요.",
        );
      return r;
    },
    artifacts: async () =>
      saved
        ? saved.artifacts
        : Object.fromEntries(
            await Promise.all(
              ["ablation", "loso"].map(async (name) => [
                name,
                await api("/v1/artifacts/" + name).catch(() => null),
              ]),
            ),
          ),
  });
  const synthetic = () => !session || session.source.startsWith("synthetic");
  history.scrollRestoration = "manual";

  function params() {
    return new URLSearchParams(location.search);
  }
  function filters() {
    return {
      q: $("search").value.trim(),
      customer: $("customer").value,
      category: $("category").value,
      sort: $("sort").value,
      page: params().get("page") || "1",
    };
  }
  function changeUrl(values, push = false, state = history.state) {
    const url = new URL(location.href);
    Object.entries(values).forEach(([key, value]) => {
      if (value == null || value === "") url.searchParams.delete(key);
      else url.searchParams.set(key, value);
    });
    history[push ? "pushState" : "replaceState"](state, "", url);
  }
  function siteName(id) {
    return session?.sites.find((s) => s.site_id === id)?.name || id;
  }
  async function api(path, options) {
    const r = await fetch(path, options);
    if (!r.ok) {
      let message = `요청 실패 (${r.status})`;
      try {
        const body = await r.json();
        message = typeof body.detail === "string" ? body.detail : message;
      } catch {}
      const error = Error(message);
      error.status = r.status;
      throw error;
    }
    return r.json();
  }
  async function exampleSession(renew = false) {
    // Only this review's synthetic example metadata, scoped to the browser tab.
    // Never persist uploaded records or put session tokens in the address bar.
    const key = "harbinger:review:synthetic-example";
    if (!renew) {
      try {
        const cached = JSON.parse(sessionStorage.getItem(key));
        if (
          cached?.expires > Date.now() &&
          cached.session?.source === "synthetic-example"
        )
          return cached.session;
      } catch {
        /* Storage can be disabled; the API remains usable. */
      }
    }
    const next = await api("/v1/workbench/example", { method: "POST" });
    evidenceCache.clear();
    try {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          session: next,
          expires: Date.now() + next.ttl_seconds * 1000,
        }),
      );
    } catch {
      /* No persistent browser storage is required. */
    }
    return next;
  }
  async function liveAnalysis(asof, site = "", k = "10") {
    const path = () =>
      `/v1/workbench/sessions/${session.session_id}/analysis?${new URLSearchParams({ as_of: asof, k, ...(site ? { site } : {}) })}`;
    try {
      return await api(path());
    } catch (error) {
      if (error.status !== 404 || !synthetic()) throw error;
      session = await exampleSession(true);
      return api(path());
    }
  }
  function errorAt(id, error) {
    $(id).querySelector("span").textContent = error.message;
    $(id).hidden = false;
  }
  function readFilters() {
    const p = params();
    for (const [id, key] of [
      ["search", "q"],
      ["customer", "customer"],
      ["category", "category"],
      ["sort", "sort"],
    ]) {
      $(id).value = p.get(key) || (id === "sort" ? "risk" : "");
      if (id === "sort" && !$(id).value) $(id).value = "risk";
    }
    $("as-of").value = p.get("date") || session.default_as_of;
    syncFilterDisclosure();
  }
  function syncFilterDisclosure() {
    const open = params().get("filter_panel") === "open";
    $("filter-toggle").setAttribute("aria-expanded", String(open));
    $("filter-toggle-state").textContent = open ? "접기" : "펼치기";
    $("list-filter-fields").classList.toggle("is-open", open);
  }
  function renderFilterSummary() {
    if (!data) return;
    const labels = ["customer", "category", "sort"].map(
      (id) => $(id).selectedOptions[0].textContent,
    );
    const appliedDate = date(data.as_of);
    $("filter-summary").textContent =
      `적용: ${labels.join(" · ")} · ${appliedDate} 기준${$("as-of").value !== appliedDate ? " · 기준일 변경 미적용" : ""}`;
  }
  function renderList() {
    if (!data) return;
    renderFilterSummary();
    const f = filters(),
      q = f.q.toLocaleLowerCase();
    rows = data.assets.filter(
      (a) =>
        (!f.customer || a.site_id === f.customer) &&
        (!f.category || a.category === f.category) &&
        (!q ||
          `${a.name} ${a.asset_id} ${a.memo || ""}`
            .toLocaleLowerCase()
            .includes(q)),
    );
    rows.sort((a, b) =>
      f.sort === "inspection"
        ? a.inspection_at.localeCompare(b.inspection_at) ||
          a.asset_id.localeCompare(b.asset_id)
        : f.sort === "name"
          ? a.name.localeCompare(b.name, "ko") ||
            a.asset_id.localeCompare(b.asset_id)
          : b.p30 - a.p30 || a.asset_id.localeCompare(b.asset_id),
    );
    const pages = Math.max(1, Math.ceil(rows.length / pageSize));
    const current = Math.min(pages, Math.max(1, parseInt(f.page, 10) || 1));
    if (String(current) !== f.page) changeUrl({ page: String(current) });
    const start = (current - 1) * pageSize;
    $("result-count").textContent = `${rows.length.toLocaleString()}개 설비`;
    $("list-context").textContent =
      `${date(data.as_of)} 기준 · ${$("sort").selectedOptions[0].textContent} · 설비 이름을 눌러 원문 확인`;
    $("assets").innerHTML = rows
      .slice(start, start + pageSize)
      .map((a, index) => {
        const url = new URL(location.href);
        url.searchParams.set("asset", a.asset_id);
        return `<tr><td class="rank">${start + index + 1}</td><td class="asset-cell"><a href="${esc(url.pathname + url.search)}" data-asset="${esc(a.asset_id)}">${esc(a.name)}</a><span class="asset-id">${esc(a.asset_id)}</span></td><td class="site-cell" title="${esc(siteName(a.site_id))}">${esc(siteName(a.site_id))}</td><td class="date-cell">${esc(date(a.inspection_at))}</td><td class="memo-cell" title="${esc(a.memo || "메모 없음")}">${esc(a.memo || "메모 없음")}</td><td class="overall-cell">${overall(a.overall)}</td><td class="risk-cell">${percent(a.p30)}</td></tr>`;
      })
      .join("");
    $("asset-table").hidden = !rows.length;
    $("empty").hidden = !!rows.length;
    $("pagination").hidden = !rows.length;
    $("page-range").textContent =
      `${rows.length ? start + 1 : 0}–${Math.min(start + pageSize, rows.length)} / ${rows.length.toLocaleString()}개`;
    $("page-number").textContent = `${current} / ${pages}`;
    $("previous-page").disabled = current <= 1;
    $("next-page").disabled = current >= pages;
    $("list-note").textContent =
      `${synthetic() ? "합성 예제 · 실제 고객 실증이 아닙니다." : "사용자 업로드 · 합성 학습 모델의 탐색적 분석입니다."} ${saved ? "저장된 Python 모델 계산 결과를 재생합니다." : "실제 Python 모델로 계산한 결과입니다."} 모델 ${data.model_version}. 고장 가능성은 안전 판정이 아닙니다.`;
  }
  function filterChanged() {
    changeUrl({ ...filters(), page: "1" }, false, { view: "list", y: 0 });
    renderList();
  }
  function resetFilters() {
    $("search").value = "";
    $("customer").value = "";
    $("category").value = "";
    $("sort").value = "risk";
    filterChanged();
  }
  async function loadAnalysis(prefetched = null) {
    loading = true;
    $("calculate").disabled = true;
    $("list-error").hidden = true;
    $("list-loading").hidden = false;
    $("asset-table").hidden = true;
    $("pagination").hidden = true;
    $("empty").hidden = true;
    try {
      const asof = params().get("date") || session.default_as_of;
      const result =
        prefetched ||
        (saved ? saved.snapshots[`${asof}|`] : await liveAnalysis(asof));
      if (!result)
        throw Error(
          "이 날짜의 저장된 계산 결과가 없습니다. 제공된 예측 기준일을 선택해 주세요.",
        );
      if (data?.as_of !== result.as_of) reports.reset();
      data = result;
      changeUrl({ date: date(data.as_of) });
      readFilters();
      renderList();
      $("mode").textContent = saved
        ? "합성 예제 · 저장 결과 재생"
        : `${synthetic() ? "합성 예제" : "업로드 기록"} · Python 계산 완료`;
      return true;
    } catch (error) {
      data = null;
      $("result-count").textContent = "";
      $("list-context").textContent = "분석 결과를 불러오지 못했습니다.";
      errorAt("list-error", error);
      return false;
    } finally {
      loading = false;
      $("calculate").disabled = false;
      $("list-loading").hidden = true;
    }
  }
  function saveListPosition() {
    listPosition = window.scrollY;
    history.replaceState(
      { view: "list", y: listPosition, focus: lastAsset },
      "",
    );
  }
  async function openAsset(id) {
    if (loading) return;
    lastAsset = id;
    saveListPosition();
    changeUrl({ asset: id, inspection: null }, true, {
      view: "detail",
      fromList: true,
    });
    await route();
  }
  function backToList() {
    if (history.state?.fromList) history.back();
    else {
      changeUrl({ asset: null, inspection: null, view: "list" }, false, {
        view: "list",
        y: 0,
      });
      route();
    }
  }
  async function route() {
    const routeId = ++generation;
    requestController?.abort();
    const id = params().get("asset");
    const isDetail = !!id;
    const view = isDetail ? "detail" : params().get("view") || "list";
    const isReport = ["validation", "customers", "downloads"].includes(view);
    $("list-screen").hidden = view !== "list";
    $("detail-screen").hidden = view !== "detail";
    $("reports-screen").hidden = !isReport;
    $("data-screen").hidden = view !== "data";
    document
      .querySelectorAll(".app-nav [data-view],.app-actions [data-view]")
      .forEach((button) => {
        if (button.dataset.view === (isDetail ? "list" : view))
          button.setAttribute("aria-current", "page");
        else button.removeAttribute("aria-current");
      });
    if (view === "data") {
      renderData();
      window.scrollTo(0, 0);
      document.title = "데이터 불러오기 · harbinger";
      return;
    }
    if (!session || !data) {
      changeUrl({ view: "data", asset: null, inspection: null });
      return route();
    }
    if (isReport) {
      window.scrollTo(0, 0);
      await reports.open(view);
      document.title = $("report-title").textContent + " · harbinger";
      return;
    }
    if (!isDetail) {
      readFilters();
      if (data && date(data.as_of) !== $("as-of").value) await loadAnalysis();
      else renderList();
      document.title = "설비 목록 · harbinger";
      requestAnimationFrame(() => {
        if (generation !== routeId) return;
        window.scrollTo(0, history.state?.y ?? listPosition);
        const focusId = history.state?.focus || lastAsset;
        [...document.querySelectorAll("[data-asset]")]
          .find((a) => a.dataset.asset === focusId)
          ?.focus({ preventScroll: true });
      });
      return;
    }
    window.scrollTo(0, 0);
    $("detail-content").hidden = true;
    $("detail-error").hidden = true;
    $("detail-loading").hidden = false;
    $("detail-asof").textContent = `${date(data?.as_of)} 기준 예측`;
    try {
      const a = data?.assets.find((item) => item.asset_id === id);
      if (!a)
        throw Error(
          "이 분석 결과에 해당 설비가 없습니다. 목록으로 돌아가 설비를 선택해 주세요.",
        );
      const key = `${date(data.as_of)}|${id}`;
      requestController = new AbortController();
      let result = evidenceCache.get(key);
      if (!result) {
        result = saved
          ? saved.evidence[key]
          : await api(
              `/v1/workbench/sessions/${session.session_id}/assets/${encodeURIComponent(id)}?as_of=${encodeURIComponent(date(data.as_of))}`,
              { signal: requestController.signal },
            );
        if (result) evidenceCache.set(key, result);
      }
      if (generation !== routeId) return;
      detail = { asset: a, response: result || null };
      renderDetail();
      $("detail-content").hidden = false;
      document.title = `${a.name} · 점검 기록 · harbinger`;
      $("asset-title").focus({ preventScroll: true });
    } catch (error) {
      if (generation === routeId && error.name !== "AbortError")
        errorAt("detail-error", error);
    } finally {
      if (generation === routeId) $("detail-loading").hidden = true;
    }
  }
  function inspections() {
    const records = detail.response?.explanation?.evidence?.recent_inspections;
    return records?.length
      ? [...records].sort((a, b) =>
          String(b.performed_at || b.at).localeCompare(
            String(a.performed_at || a.at),
          ),
        )
      : [
          {
            performed_at: detail.asset.inspection_at,
            memo: detail.asset.memo,
            overall: detail.asset.overall,
          },
        ];
  }
  function sourceFor(c) {
    const f = c.feature;
    // Only these fields describe one latest inspection. All other derived fields
    // remain labelled as aggregates/context; never attribute their SHAP to a sentence.
    const latest = [
      "ck_overall",
      "ck_n_caution",
      "ck_n_bad",
      "ck_n_items",
      "ck_frac_flagged",
      "tx_len",
      "tx_lazy",
      "tx_weak_hits",
      "tx_strong_hits",
      "tx_n_groups",
      "tx_weak_score",
      "tx_strong_score",
    ];
    if (
      latest.includes(f) ||
      f.startsWith("tx_g_") ||
      /^ck_(noise|vibration|oil_leak|water_leak|temperature|pressure|current|belt|filter|combustion|door|leveling|operation|battery|fuel|insulation|odor|appearance|fill|fan|sensor|level)$/.test(
        f,
      )
    )
      return {
        type: "latest",
        text: `최근 점검 · ${date(detail.asset.inspection_at)}`,
      };
    if (f.startsWith("wo_"))
      return { type: "workorders", text: "기준일 이전 고장·정비 이력 집계" };
    if (f.startsWith("tx_") || f.startsWith("ck_") || f.startsWith("q_"))
      return { type: "history", text: "여러 점검의 이력·변화 집계" };
    return {
      type: "context",
      text: f.startsWith("st_") ? "설비·건물 등록 정보" : "기준일의 분석 조건",
    };
  }
  function renderDetail() {
    const a = detail.asset,
      r = detail.response;
    const records = inspections();
    $("asset-title").textContent = a.name;
    $("asset-location").textContent =
      `${siteName(a.site_id)} · ${categories[a.category] || a.category} · ${a.asset_id}${r?.zone ? ` · ${r.zone}` : ""}`;
    $("asset-risk").textContent = percent(a.p30);
    $("detail-summary").innerHTML =
      `<span>최근 점검 <b>${esc(date(a.inspection_at))}</b> · ${Math.floor(a.days_since_inspection)}일 경과</span><span>현장 종합 판정 <b>${overall(a.overall)}</b></span><span>최근 90일 고장 기록 <b>${a.breakdowns_90d}건</b></span>`;
    $("record-count").textContent = r
      ? `최근 ${records.length}회 · 날짜를 선택하세요`
      : "목록에 포함된 최근 원문 1회";
    $("inspection-dates").innerHTML = records
      .map(
        (m, i) =>
          `<button type="button" data-inspection="${i}" aria-pressed="false">${esc(date(m.performed_at || m.at))}${i === 0 ? "<small>최근 점검</small>" : ""}</button>`,
      )
      .join("");
    const chosen = params().get("inspection");
    selectedRecord = Math.max(
      0,
      records.findIndex((m) => (m.performed_at || m.at) === chosen),
    );
    renderRecord();
    const contributions = r?.explanation?.contributions || [];
    $("reasons").innerHTML = contributions.length
      ? contributions
          .map((c) => {
            const source = sourceFor(c),
              value = c.contribution ?? c.shap;
            return `<div class="reason-row"><strong>${esc(c.label || c.feature)}</strong><span class="direction ${value > 0 ? "up" : ""}">${value > 0 ? "위험 추정을 높인 항목" : value < 0 ? "위험 추정을 낮춘 항목" : "영향 없음"}</span><span class="origin">${esc(source.text)}</span>${source.type === "context" ? '<span class="no-link">등록 정보</span>' : `<button class="text-button" type="button" data-source="${source.type}">기록 보기 ↓</button>`}</div>`;
          })
          .join("")
      : `<p class="source-note">${saved ? "이 설비의 상세 근거는 저장된 데모에 포함되지 않았습니다. 최근 원문만 표시합니다." : "이 설비의 모델 기여도를 계산할 수 없습니다. 원문 기록을 확인해 주세요."}</p>`;
    $("model-values").innerHTML =
      `<p>모델 ${esc(data.model_version)} · 예측 기준 ${esc(data.as_of)}. SHAP 기여도는 모델 점수 단위이며 확률의 변화량(%p)이 아닙니다.</p><table><thead><tr><th>항목</th><th>입력값</th><th>기여도</th></tr></thead><tbody>${contributions.map((c) => `<tr><td>${esc(c.label || c.feature)}</td><td>${Number.isFinite(c.value) ? Number(c.value.toFixed(3)) : "—"}</td><td>${Number.isFinite(c.contribution ?? c.shap) ? (c.contribution ?? c.shap).toFixed(3) : "—"}</td></tr>`).join("")}</tbody></table>`;
    $("model-details").open = false;
    const orders = r?.explanation?.evidence?.recent_workorders || [];
    $("workorder-list").innerHTML = orders.length
      ? [...orders]
          .reverse()
          .map(
            (w) =>
              `<div class="workorder"><time>${esc(date(w.opened_at))}</time><span>${esc({ breakdown: "고장 수리", preventive: "예방 정비", parts: "부품 교체" }[w.type] || w.type)}</span><p>${esc(w.description || "설명 없음")}</p></div>`,
          )
          .join("")
      : '<p class="source-note">제공된 상세 응답에 정비 원문이 없습니다. 전체 이력이 없다는 뜻은 아닙니다.</p>';
    $("detail-provenance").textContent =
      `${synthetic() ? "합성 예제" : "사용자 업로드"} · ${saved ? "저장된 계산 결과" : "Python 모델 계산"} · 모델 ${data.model_version} · 예측 기준 ${data.as_of}. 이후 고장 결과는 검증에만 사용합니다.`;
    $("asset-outcome-text").textContent =
      a.failed_within_30d == null
        ? `평가 보류 · 기준일 이후 30일 관측이 부족합니다. 정답 관측 종료 ${data.observation_end}.`
        : `${date(data.as_of)} 당시 추정 ${percent(a.p30)} → ${a.failed_within_30d ? `이후 ${a.days_to_failure?.toFixed(1) ?? "—"}일에 고장 기록 있음` : "이후 30일 관측 기간 내 고장 기록 없음"}.${data.time_held_out ? "" : " 모델 학습·보정 기간과 겹쳐 성능 평가는 보류합니다."}`;
  }
  function renderRecord(message = "") {
    const records = inspections(),
      m = records[selectedRecord];
    document
      .querySelectorAll("[data-inspection]")
      .forEach((button) =>
        button.setAttribute(
          "aria-pressed",
          String(Number(button.dataset.inspection) === selectedRecord),
        ),
      );
    $("record-date").textContent = String(m.performed_at || m.at)
      .replace("T", " ")
      .slice(0, 16);
    $("record-inspector").textContent = m.inspector_id
      ? `점검자 ${m.inspector_id}`
      : "점검자 정보 미제공";
    $("record-overall").textContent = `현장 종합 판정 · ${overall(m.overall)}`;
    $("record-memo").textContent = m.memo || "작성된 메모가 없습니다.";
    $("record-flags").innerHTML =
      `<span>지적 항목: ${m.flagged_items ? esc(m.flagged_items.join(" · ") || "없음") : "상세 항목 미제공"}</span>${m.dwell_seconds != null ? `<span>점검 체류 ${m.dwell_seconds}초</span>` : ""}`;
    const related = (detail.response?.explanation?.contributions || []).filter(
      (c) => sourceFor(c).type === "latest",
    );
    $("record-connection").textContent =
      message ||
      (selectedRecord === 0 && related.length
        ? `이 점검에서 계산한 입력: ${related.map((c) => c.label || c.feature).join(" · ")}. 아래에서 각 항목의 기여 방향을 확인하세요.`
        : "이 날짜의 원문입니다. 아래 기여도는 선택한 기록 한 건의 점수가 아니라 예측 기준일의 모델 판단입니다.");
  }
  $("assets").addEventListener("click", (event) => {
    const link = event.target.closest("[data-asset]");
    if (
      !link ||
      event.ctrlKey ||
      event.metaKey ||
      event.shiftKey ||
      event.altKey
    )
      return;
    event.preventDefault();
    openAsset(link.dataset.asset);
  });
  $("filter-toggle").onclick = () => {
    changeUrl({
      filter_panel: params().get("filter_panel") === "open" ? null : "open",
    });
    syncFilterDisclosure();
  };
  $("filters").addEventListener("change", (event) => {
    if (event.target.id === "as-of") renderFilterSummary();
  });
  $("search").addEventListener("input", filterChanged);
  for (const id of ["customer", "category", "sort"])
    $(id).addEventListener("change", filterChanged);
  $("reset-filters").onclick = $("empty-reset").onclick = resetFilters;
  $("filters").onsubmit = async (event) => {
    event.preventDefault();
    if (loading || !session) return;
    changeUrl({ ...filters(), date: $("as-of").value, page: "1" }, false, {
      view: "list",
      y: 0,
    });
    await loadAnalysis();
  };
  for (const [id, delta] of [
    ["previous-page", -1],
    ["next-page", 1],
  ])
    $(id).onclick = () => {
      changeUrl(
        { page: String((Number(params().get("page")) || 1) + delta) },
        false,
        { view: "list", y: 0 },
      );
      renderList();
      window.scrollTo(0, 0);
      $("list-title").scrollIntoView();
    };
  $("back-list").onclick = backToList;
  $("retry-detail").onclick = async () => {
    evidenceCache.delete(`${date(data?.as_of)}|${params().get("asset")}`);
    if (await loadAnalysis()) route();
    else
      errorAt(
        "detail-error",
        Error($("list-error").querySelector("span").textContent),
      );
  };
  $("retry-list").onclick = async () => {
    if (session) await loadAnalysis();
    else await init();
  };
  $("inspection-dates").onclick = (event) => {
    const b = event.target.closest("[data-inspection]");
    if (!b) return;
    selectedRecord = Number(b.dataset.inspection);
    const m = inspections()[selectedRecord];
    changeUrl({ inspection: m.performed_at || m.at });
    renderRecord();
  };
  $("reasons").onclick = (event) => {
    const b = event.target.closest("[data-source]");
    if (!b) return;
    if (b.dataset.source === "workorders") {
      $("workorders").focus();
      return;
    }
    if (b.dataset.source === "latest") {
      selectedRecord = 0;
      changeUrl({ inspection: null });
      renderRecord();
    } else
      renderRecord(
        `여러 점검을 집계한 항목입니다. 여기에는 최근 ${inspections().length}회 원문만 표시되며 집계 기간의 전체 기록을 뜻하지 않습니다.`,
      );
    $("inspection-record").focus();
  };
  window.addEventListener("popstate", () => {
    route();
  });
  let scrollFrame;
  window.addEventListener(
    "scroll",
    () => {
      if ($("list-screen").hidden || scrollFrame) return;
      scrollFrame = requestAnimationFrame(() => {
        scrollFrame = null;
        if (!$("list-screen").hidden) saveListPosition();
      });
    },
    { passive: true },
  );
  function populateControls() {
    $("customer").innerHTML =
      '<option value="">전체 고객사</option>' +
      session.sites
        .map((s) => `<option value="${esc(s.site_id)}">${esc(s.name)}</option>`)
        .join("");
    $("category").innerHTML =
      '<option value="">전체 종류</option>' +
      Object.entries(categories)
        .map(([id, name]) => `<option value="${id}">${name}</option>`)
        .join("");
    $("as-of").max = session.latest_as_of_date || date(session.observation_end);
    $("observation-end").value =
      session.latest_as_of_date || date(session.observation_end);
    $("footer-source").textContent =
      `${synthetic() ? "합성 예제" : "사용자 업로드 · 합성 학습 모델"} · 설비의 안전 여부를 확정하지 않습니다.`;
    readFilters();
  }
  function navigate(view) {
    if (!$("list-screen").hidden) saveListPosition();
    changeUrl({ view, asset: null, inspection: null }, true, {
      view,
      y: view === "list" ? listPosition : 0,
      focus: lastAsset,
    });
    route();
  }
  document
    .querySelectorAll("[data-view]")
    .forEach(
      (button) => (button.onclick = () => navigate(button.dataset.view)),
    );
  document.querySelector(".brand").onclick = (event) => {
    event.preventDefault();
    navigate("list");
  };
  function renderData() {
    $("dataset-source").textContent = session
      ? `${synthetic() ? "합성 예제" : "업로드 기록"} · ${session.summary.assets}개 설비`
      : "열린 기록 없음";
    $("data-mode-note").textContent = saved
      ? "공개 정적 데모는 저장된 합성 계산 결과를 재생합니다. CSV 업로드·임의 날짜 계산은 README의 Docker 또는 Python 로컬 실행에서 사용할 수 있습니다."
      : "지원 CSV를 검사하고 실제 Python 모델로 계산합니다. 먼저 합성 예제를 사용하거나 아래 양식으로 점검 기록을 불러오세요.";
    $("sample-csv").href = saved
      ? "./example.csv"
      : "/v1/workbench/example.csv";
    for (const id of [
      "csv-file",
      "observation-end",
      "observation-confirm",
      "upload-submit",
    ])
      $(id).disabled = !!saved;
    $("close-session").disabled = !session;
  }
  async function releaseSession(old) {
    if (!old || saved) return;
    await fetch(`/v1/workbench/sessions/${old.session_id}`, {
      method: "DELETE",
    });
    if (old.source.startsWith("synthetic")) {
      try {
        sessionStorage.removeItem("harbinger:review:synthetic-example");
      } catch {}
    }
  }
  async function activate(next) {
    // Score the candidate before replacing the active session or its URL state.
    let result;
    try {
      result = saved
        ? saved.snapshots[`${next.default_as_of}|`]
        : await api(
            `/v1/workbench/sessions/${next.session_id}/analysis?${new URLSearchParams({ as_of: next.default_as_of, k: "10" })}`,
          );
      if (!result) throw Error("예제의 저장된 계산 결과가 없습니다.");
    } catch (error) {
      if (next.session_id !== session?.session_id) await releaseSession(next);
      throw error;
    }
    session = next;
    data = null;
    listPosition = 0;
    lastAsset = null;
    evidenceCache.clear();
    reports.reset();
    changeUrl(
      {
        view: "list",
        source: synthetic() ? null : "upload",
        date: next.default_as_of,
        asset: null,
        inspection: null,
        q: null,
        customer: null,
        category: null,
        sort: "risk",
        page: "1",
      },
      false,
      { view: "list", y: 0 },
    );
    populateControls();
    await loadAnalysis(result);
    await route();
  }
  async function dataTask(fn) {
    if (loading) return;
    loading = true;
    $("data-error").hidden = true;
    $("data-status").textContent = "기록을 검사하고 계산하고 있습니다…";
    for (const id of ["load-example", "upload-submit", "close-session"])
      $(id).disabled = true;
    try {
      await fn();
    } catch (error) {
      errorAt("data-error", error);
      $("data-status").textContent =
        "불러오지 못했습니다. 현재 열려 있는 기록은 유지됩니다.";
    } finally {
      loading = false;
      $("load-example").disabled = false;
      $("upload-submit").disabled = !!saved;
      $("close-session").disabled = !session;
    }
  }
  $("load-example").onclick = () =>
    dataTask(async () => {
      const next = saved
        ? saved.session
        : synthetic() && session
          ? session
          : await exampleSession();
      const previous = session;
      await activate(next);
      if (previous && previous.session_id !== next.session_id)
        await releaseSession(previous);
      $("data-status").textContent = "합성 예제를 불러왔습니다.";
    });
  $("close-session").onclick = () =>
    dataTask(async () => {
      await releaseSession(session);
      session = null;
      data = null;
      evidenceCache.clear();
      reports.reset();
      changeUrl({
        source: "closed",
        view: "data",
        asset: null,
        inspection: null,
      });
      await route();
      $("data-status").textContent = saved
        ? "저장 예제 화면을 닫았습니다."
        : "기록을 닫고 해당 서버 세션을 제거했습니다.";
    });
  $("upload-form").onsubmit = (event) => {
    event.preventDefault();
    if (saved) return;
    dataTask(async () => {
      const file = $("csv-file").files[0];
      if (!file || !file.name.toLowerCase().endsWith(".csv"))
        throw Error("CSV 파일만 지원합니다.");
      if (file.size > 5 * 1024 * 1024)
        throw Error("파일 크기 초과: 최대 5 MiB입니다.");
      const next = await api(
        "/v1/workbench/upload?observation_end=" +
          encodeURIComponent($("observation-end").value),
        { method: "POST", headers: { "Content-Type": "text/csv" }, body: file },
      );
      const previous = session;
      await activate(next);
      await releaseSession(previous);
      $("data-status").textContent =
        "CSV 검사와 분석 완료. " + (next.summary.warnings || []).join(" ");
    });
  };
  async function init() {
    $("list-error").hidden = true;
    $("list-loading").hidden = false;
    try {
      if (window.HARBINGER_SAVED) {
        saved = await api("./workbench-data.json");
        session = saved.session;
        $("as-of").outerHTML =
          `<select id="as-of" aria-label="예측 기준일">${saved.dates.map((d) => `<option>${esc(d)}</option>`).join("")}</select>`;
      } else if (["upload", "closed"].includes(params().get("source"))) {
        changeUrl({ view: "data", asset: null, inspection: null });
        await route();
        $("data-status").textContent =
          params().get("source") === "upload"
            ? "업로드 자료는 새로고침 후 다시 불러와 주세요. 합성 예제로 자동 전환하지 않았습니다."
            : "예제 또는 CSV를 불러와 시작하세요.";
        return;
      } else session = await exampleSession();
      populateControls();
      if (!params().get("date")) changeUrl({ date: session.default_as_of });
      if (await loadAnalysis()) await route();
    } catch (error) {
      errorAt("list-error", error);
      $("list-loading").hidden = true;
      $("mode").textContent = "연결 오류";
    }
  }
  init();
})();
