/* Applied analysis conditions are immutable until the next successful calculation. */
"use strict";
window.HarbingerReports = function (ctx) {
  const $ = (id) => document.getElementById(id);
  const esc = ctx.esc;
  const pct = (v) => (v == null ? "평가 보류" : `${(v * 100).toFixed(1)}%`);
  const number = (v) => (v == null ? "—" : Number(v).toFixed(3));
  const names = {
    current_model: "현재 모델",
    logistic: "단순 모델 로지스틱",
    without_text: "메모 제거 모델",
    without_history: "고장 이력 제거 모델",
    last_inspection_rule: "최근 점검 판정 규칙",
    age_rule: "설비 연식 규칙",
    recent_repair_rule: "최근 고장 규칙",
    oldest_inspection_rule: "오래 미점검 규칙",
    random_expectation: "무작위 기대치",
  };
  let result = null,
    applied = null,
    currentView = "validation",
    generation = 0,
    artifactPromise = null;
  function criteria() {
    return {
      as_of: $("report-date").value,
      site: $("report-site").value,
      k: ctx.saved() ? "10" : $("report-budget").value,
    };
  }
  function syncPending() {
    $("report-pending").textContent =
      applied && JSON.stringify(criteria()) !== JSON.stringify(applied)
        ? "조건 변경 미적용 · 적용 전 결과입니다. ‘조건 적용’을 눌러 새로 계산하세요."
        : "";
  }
  function dateControl(value) {
    const saved = ctx.saved();
    $("report-date").outerHTML = saved
      ? `<select id="report-date" aria-label="예측 기준일">${saved.dates.map((d) => `<option>${esc(d)}</option>`).join("")}</select>`
      : '<input id="report-date" type="date" required>';
    $("report-date").value = value;
    $("report-date").max =
      ctx.session().latest_as_of_date ||
      ctx.session().observation_end.slice(0, 10);
  }
  function configure() {
    const session = ctx.session();
    dateControl(ctx.date());
    $("report-site").innerHTML =
      '<option value="">전체 고객사</option>' +
      session.sites
        .map((s) => `<option value="${esc(s.site_id)}">${esc(s.name)}</option>`)
        .join("");
    $("report-site").value = ctx.customer();
    $("report-budget").value = "10";
    $("report-budget").disabled = !!ctx.saved();
    $("report-mode").textContent = ctx.saved()
      ? "저장된 합성 응답 · 점검 수 10개 고정"
      : "Python 모델 실제 계산";
  }
  function showView() {
    const titles = {
      validation: "과거 예측 검증",
      customers: "고객사별 결과",
      downloads: "분석 결과 내보내기",
    };
    $("report-title").textContent = titles[currentView];
    for (const name of Object.keys(titles))
      $(name + "-content").hidden = name !== currentView || !result;
  }
  async function calculate() {
    const request = ++generation,
      c = criteria();
    $("report-apply").disabled = true;
    $("report-loading").hidden = false;
    $("report-error").hidden = true;
    try {
      const next = await ctx.analyze(c);
      if (request !== generation) return;
      result = next;
      applied = { ...c };
      render();
      showView();
      syncPending();
    } catch (e) {
      if (request !== generation) return;
      $("report-error").querySelector("span").textContent =
        e.message + (result ? " 이전에 적용한 조건의 결과를 유지합니다." : "");
      $("report-error").hidden = false;
    } finally {
      if (request === generation) {
        $("report-apply").disabled = false;
        $("report-loading").hidden = true;
      }
    }
  }
  function conditionText() {
    return `${applied.as_of} 기준 · ${applied.site ? ctx.siteName(applied.site) : "전체 고객사"} · 고객사마다 ${applied.k}개 선택 · 분석 설비 ${result.assets.length.toLocaleString()}개`;
  }
  function outcome(a) {
    return a.failed_within_30d == null
      ? (result.observation_confirmed === false ? "기록 완전성 미확인 · 결과 미확정" : "관측 부족 · 결과 미확정")
      : a.failed_within_30d
        ? `고장 기록 있음${a.days_to_failure != null ? ` · ${a.days_to_failure.toFixed(1)}일 후` : ""}`
        : "관측 기간 내 고장 기록 없음";
  }
  function render() {
    $("applied-conditions").textContent = "적용된 조건: " + conditionText();
    $("report-time-context").textContent = `${applied.as_of} 당시 예측과 이후 30일 동안 확인된 기록을 비교합니다. 오늘의 고장 상태가 아닙니다.`;
    $("evaluation-note").textContent =
      result.evaluation_status === "available"
        ? "평가 조건 충족 · 학습에 쓰지 않은 시간과 완전한 이후 30일 기록을 비교합니다. 합성 학습 모델의 탐색적 평가입니다."
        : "평가 보류 · " + result.evaluation_reasons.join(" ");
    $("evaluation-note").classList.toggle(
      "withheld",
      result.evaluation_status !== "available",
    );
    $("comparison-rows").innerHTML =
      result.comparisons
        .map(
          (m) =>
            `<tr><th scope="row">${esc(names[m.method] || m.method)}</th><td>${pct(m.precision_at_k)}</td><td>${pct(m.recall_at_k)}</td><td>${m.selected}</td><td>${number(m.metrics?.auroc)}</td><td>${number(m.metrics?.pr_auc)}</td><td>${number(m.metrics?.brier)}</td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="7">평가할 점검 기록이 없습니다.</td></tr>';
    const selection = result.comparisons.find(
      (m) => m.method === "current_model",
    )?.selected_asset_ids;
    const selectedIds = new Set(selection || []);
    const selected = result.assets.filter((a) => selectedIds.has(a.asset_id));
    $("outcome-count").textContent =
      `${selected.length}개 선택 · 최대 250개 표시`;
    $("outcome-rows").innerHTML =
      selected
        .slice(0, 250)
        .map(
          (a) =>
            `<tr data-outcome-asset="${esc(a.asset_id)}"><th scope="row">${esc(a.name)}<small>${esc(ctx.siteName(a.site_id))}</small></th><td>${esc(a.memo || "메모 없음")}</td><td>${pct(a.p30)}</td><td>${esc(outcome(a))}</td></tr>`,
        )
        .join("") ||
      `<tr><td colspan="4">${selection ? "선택할 설비가 없습니다." : "이 응답에는 선택된 설비 식별 정보가 없습니다. 지표와 일치하지 않을 수 있어 목록을 임의로 만들지 않습니다."}</td></tr>`;
    $("customer-rows").innerHTML =
      result.per_site
        .map(
          (s) =>
            `<tr><th scope="row">${esc(ctx.siteName(s.site_id))}<small>${esc(s.site_id)}</small></th><td>${s.assets}</td><td>${s.positives ?? "미확정"}</td><td>${s.status === "available" ? "평가 가능" : `평가 보류 · ${esc(s.reason)}`}</td><td>${number(s.metrics?.auroc)}</td><td>${number(s.metrics?.brier)}</td></tr>`,
        )
        .join("") ||
      '<tr><td colspan="6">이 기준일의 고객사별 결과가 없습니다.</td></tr>';
    $("report-provenance").textContent =
      `${ctx.saved() ? "저장된 Python 응답 재생" : "Python 모델 계산"} · 데이터 ${result.source.startsWith("synthetic") ? "합성 예제" : "사용자 업로드"} · 모델 ${result.model_version} · 모델 관측 종료 ${result.model_observed_until || "미제공"} · 정답 관측 종료 ${result.observation_end}. 현재 표는 고객사 보류 실험과 다릅니다.`;
    $("download-status").textContent = "";
    document
      .querySelectorAll("[data-format]")
      .forEach((b) => (b.disabled = false));
  }
  async function experiments() {
    if (!artifactPromise) artifactPromise = ctx.artifacts();
    try {
      const artifacts = await artifactPromise,
        a = artifacts.ablation || {},
        l = artifacts.loso || {};
      const label = {
        checklist_only: "점검표만",
        "+text": "점검표 + 메모",
        "+text+quality": "점검표 + 메모 + 기록 품질",
        "+text+quality+history": "점검표 + 메모 + 품질 + 고장 이력",
        "full(+energy)": "전체 모델",
        "full−text": "메모와 메모 파생 특징 제거",
        "full−quality": "기록 품질 특징 제거",
        "full−history": "고장·정비 이력 제거",
      };
      $("experiment-content").innerHTML = Object.keys(a).length
        ? '<p class="source-note">동일한 시간 경계로 학습한 전체 기간 제거 실험입니다. 업로드 자료의 실증 결과가 아니며 합성 생성 가정에 의존합니다.</p><div class="data-table-wrap"><table class="data-table"><thead><tr><th>입력 조건</th><th>AUROC</th><th>PR-AUC</th><th>Brier</th></tr></thead><tbody>' +
          Object.entries(a)
            .map(
              ([k, v]) =>
                `<tr><th scope="row">${esc(label[k] || k)}</th><td>${number(v.auroc)}</td><td>${number(v.pr_auc)}</td><td>${number(v.brier)}</td></tr>`,
            )
            .join("") +
          '</tbody></table></div><p class="source-note">메모를 넣었다는 사실만으로 추가 성능을 주장하지 않습니다. 전체 모델과 제거 모델의 수치를 함께 확인하세요. 반복 주간 평가의 불확실성은 저장소의 고객사 단위 bootstrap 산출물을 참고하세요.</p>'
        : '<p class="source-note">제거 실험 산출물이 없습니다. 추가 기여를 확인했다고 표시하지 않습니다.</p>';
      const sites = Object.keys(l.per_site || {});
      $("loso-content").innerHTML =
        `<p class="evaluation-note">고객사 보류 실험 ${sites.length}곳 완료 / ${(l.holdout_sites || []).length}곳 선정. ${sites.length ? "합성 고객사의 전체 기록을 학습·보정에서 제외한 별도 실험입니다." : "제공된 실험 산출물이 없습니다."}</p>` +
        (sites.length
          ? '<div class="data-table-wrap"><table class="data-table"><thead><tr><th>보류 고객사</th><th>자체 정답 0개월 AUROC</th><th>PR-AUC</th><th>Brier</th></tr></thead><tbody>' +
            sites
              .map((id) => {
                const m = l.per_site[id]["0"];
                return `<tr><th scope="row">${esc(id)}</th><td>${number(m?.auroc)}</td><td>${number(m?.pr_auc)}</td><td>${number(m?.brier)}</td></tr>`;
              })
              .join("") +
            "</tbody></table></div>"
          : "") +
        `<p class="source-note">미선정: ${esc((l.not_selected_sites || []).join(", ") || "정보 없음")}<br>평가 제외: ${esc(Object.keys(l.skipped_sites || {}).join(", ") || "없음")}<br>에너지 특징을 제외하고 자체 정답 0개월 조건을 표시합니다. 실제 고객 일반화나 통계적 유의성을 입증한 결과는 아닙니다.</p>`;
    } catch (e) {
      artifactPromise = null;
      $("experiment-content").textContent =
        "실험 산출물을 불러오지 못했습니다: " + e.message;
      $("loso-content").textContent =
        "고객사 보류 실험 산출물을 불러오지 못했습니다.";
    }
  }
  function download(format) {
    if (!result) return;
    let body, mime;
    if (format === "json") {
      body = JSON.stringify({ ...result, export_criteria: applied }, null, 2);
      mime = "application/json";
    } else if (format === "csv") {
      const keys = [
        "asset_id",
        "site_id",
        "name",
        "p30",
        "inspection_at",
        "memo",
        "failed_within_30d",
        "days_to_failure",
      ];
      const cell = (v) => {
        let s = String(v ?? "");
        if (/^[=+@\-\t\r]/.test(s)) s = "'" + s;
        return '"' + s.replace(/"/g, '""') + '"';
      };
      body =
        "\ufeff" +
        [keys, ...result.assets.map((a) => keys.map((k) => a[k]))]
          .map((row) => row.map(cell).join(","))
          .join("\n");
      mime = "text/csv";
    } else {
      body =
        `# harbinger 분석 보고서\n\n${conditionText()}\n\n데이터: ${result.source}\n\n계산: ${ctx.saved() ? "저장된 Python 모델 응답 재생" : "Python 모델 계산"}\n\n모델: ${result.model_version}\n\n모델 관측 종료: ${result.model_observed_until || "미제공"}\n\n정답 관측 종료: ${result.observation_end}\n\n평가: ${result.evaluation_status === "available" ? "평가 조건 충족" : "평가 보류"}\n\n${result.evaluation_reasons.join("\n")}\n\n| 방법 | 선택 설비 고장 비율 | 고장 설비 발견 비율 | AUROC | PR-AUC | Brier |\n|---|---:|---:|---:|---:|---:|\n` +
        result.comparisons
          .map(
            (m) =>
              `| ${names[m.method] || m.method} | ${pct(m.precision_at_k)} | ${pct(m.recall_at_k)} | ${number(m.metrics?.auroc)} | ${number(m.metrics?.pr_auc)} | ${number(m.metrics?.brier)} |`,
          )
          .join("\n") +
        "\n\n합성 학습 모델의 탐색적 결과입니다. 실제 고객 실증이나 안전 판정이 아닙니다. 고객사 보류 실험은 별도이며, 이 단일 날짜 결과에는 신뢰구간을 붙이지 않습니다.\n";
      mime = "text/markdown";
    }
    const url = URL.createObjectURL(
        new Blob([body], { type: mime + ";charset=utf-8" }),
      ),
      link = document.createElement("a");
    link.href = url;
    link.download = `harbinger-${applied.as_of}.${format}`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    $("download-status").textContent =
      `내려받기 준비 완료 · ${conditionText()}`;
  }
  $("report-form").onsubmit = (e) => {
    e.preventDefault();
    calculate();
  };
  $("report-form").addEventListener("input", syncPending);
  $("report-form").addEventListener("change", syncPending);
  $("report-retry").onclick = calculate;
  document
    .querySelectorAll("[data-format]")
    .forEach((b) => (b.onclick = () => download(b.dataset.format)));
  return {
    reset() {
      generation++;
      result = null;
      applied = null;
      $("report-apply").disabled = false;
      $("report-loading").hidden = true;
      $("report-error").hidden = true;
      $("applied-conditions").textContent = "";
      $("report-time-context").textContent = "";
    },
    async open(view) {
      currentView = view;
      showView();
      if (!result) {
        configure();
        await calculate();
      }
      experiments();
    },
  };
};
