"""실증(PoC) 리포트 — 고객사 한 곳의 현재 상태를 JSON 또는 마크다운으로."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from harbinger.api.deps import ensure_site, get_store, parse_as_of
from harbinger.api.store import Store
from harbinger.schema import CATEGORY_KO, AssetCategory

router = APIRouter(prefix="/v1/sites/{site_id}", tags=["report"])


def _ko(cat: str) -> str:
    try:
        return CATEGORY_KO[AssetCategory(cat)]
    except Exception:
        return cat


def build_report(store: Store, site_id: str, as_of) -> dict:
    summary = store.site_summary(site_id, as_of)
    patrol = store.patrol(site_id, as_of, k=10, explain=True)
    sched = store.schedule(site_id, as_of)
    energy = store.energy_anomalies(site_id, as_of, 90)
    quality = store.quality(site_id, as_of, 180)
    rows = store.latest_rows(site_id, as_of)
    top = rows.nlargest(10, "p30") if len(rows) else rows
    # Use the trace attached to the actual scored rows, not a model identity
    # inferred from the bundle's stored aggregate metrics.
    trace = store.routing_trace(rows.iloc[0]) if len(rows) else store.model_for(site_id, as_of)[1]
    trace = {
        key: trace.get(key)
        for key in ("selected_model", "policy_revision", "policy_reason", "policy_test_start")
    }
    baseline_headline = store.bundle["entry"].get("metrics", {}).get("headline")
    is_baseline = trace["selected_model"] == "baseline"
    return {
        "site": summary,
        "as_of": as_of.isoformat(timespec="minutes"),
        "top_risk_assets": [
            {
                "asset_id": r["asset_id"],
                "name": r["name"],
                "category": r["category"],
                "p30": float(r["p30"]),
                **store.routing_trace(r),
                "criticality": int(r["st_criticality"]),
                "last_overall": int(r["ck_overall"]),
                "last_inspection_at": r["t"].isoformat(timespec="minutes"),
            }
            for _, r in top.iterrows()
        ],
        "patrol": patrol,
        "schedule_changes": {
            "n_shorten": sum(
                1
                for i in sched
                if i["current_interval_days"]
                and i["recommended_interval_days"] < i["current_interval_days"] - 6
            ),
            "n_lengthen": sum(
                1
                for i in sched
                if i["current_interval_days"]
                and i["recommended_interval_days"] > i["current_interval_days"] + 6
            ),
            "urgent": [i for i in sched if i["urgent"]][:10],
        },
        "energy": {
            "status": energy.get("status", "no_data"),
            "n_observed_days_90d": energy.get("n_observed_days", 0),
            "n_evaluable_days_90d": energy.get("n_evaluable_days", 0),
            "n_anomaly_days_90d": energy.get("n_anomaly_days"),
            "anomalies": energy.get("anomalies", [])[-10:],
        },
        "quality": {
            "site_average": quality.get("site_average"),
            "least_reliable": quality.get("inspectors", [])[:3],
        },
        "model": {
            "version": store.bundle["version"],
            **trace,
            "headline": baseline_headline if is_baseline else None,
            "headline_status": "stored_reference" if is_baseline else "withheld_for_selected_model",
            "headline_scope": "stored_bundle_baseline_reference",
            "baseline_reference": {
                "selected_model": "baseline",
                "version": store.bundle["version"],
                "scope": "stored_bundle_baseline_reference",
                "headline": baseline_headline,
            },
        },
        "caveats": [
            "모든 수치는 합성 데이터 기반 데모입니다.",
            "P30 은 캘리브레이션된 30일 내 비계획 고장 확률 추정치이며 임계값은 고객사 리스크 예산에 맞춰 조정합니다.",
            "법정 점검 주기는 모델 권고와 무관하게 유지됩니다.",
        ],
    }


def to_markdown(r: dict) -> str:
    s = r["site"]
    risk_summary = (
        f"30일 고장확률 평균 {s['mean_p30']:.1%}, 고위험(≥15 %) 설비 {s['n_high_risk(p30>=0.15)']}개"
        if s["mean_p30"] is not None
        else "30일 고장확률 계산 불가 · 해당 시점의 유효한 점검 기록이 없습니다."
    )
    patrol_summary = (
        f"오늘 순찰 요청 {r['patrol']['k']}개 · 실제 선택 {r['patrol']['selected_count']}개 · 필수 {r['patrol']['mandatory_count']}개 · 예산 초과 {r['patrol']['budget_overflow']}개. 기대 고장 수 {r['patrol']['expected_breakdowns_in_list']:.2f} (같은 필수 조건의 오래 미점검 순 {r['patrol']['expected_breakdowns_round_robin']:.2f})"
        if r["patrol"]["items"]
        else "오늘 순찰 기대 고장 수 계산 불가 · 해당 시점의 유효한 점검 기록이 없습니다."
    )
    lines = [
        f"# {s['name']} 합성 실험 리포트",
        "",
        f"기준 시점: {r['as_of']} · 설비 {s['n_assets']}개 · 점검자 {s['n_inspectors']}명 · 모델 {r['model']['version']}",
        "",
        f"- 실제 점수 모델: {r['model']['selected_model']}",
        f"- 정책 리비전: {r['model']['policy_revision'] or '없음'} · 적용 이유: {r['model']['policy_reason']}",
        f"- 정책 보류 평가 시작: {r['model']['policy_test_start'] or '해당 없음'}",
        "- 모델 headline은 기본 모델의 저장된 참조 지표이며, 현재 사이트의 선택 모델 평가가 아닙니다.",
        "",
        "## 1. 요약",
        "",
        f"- 최근 90일 비계획 고장 {s['breakdowns_90d']}건, 다운타임 {s['downtime_hours_90d']:.0f}시간",
        f"- {risk_summary}",
        f"- {patrol_summary}",
        "",
        "## 2. 상위 위험 설비",
        "",
        "| 설비 | 종류 | P30 | 중요도 | 마지막 판정 |",
        "|---|---|---:|:-:|:-:|",
    ]
    for a in r["top_risk_assets"]:
        lines.append(
            f"| {a['name']} | {_ko(a['category'])} | {a['p30']:.1%} | {a['criticality']} | {['양호', '주의', '불량'][a['last_overall']]} |"
        )
    lines += ["", "## 3. 오늘 순찰 권고 (동선 순)", ""]
    for it in r["patrol"]["items"]:
        flag = " **[법정]**" if it["mandatory"] else ""
        lines.append(
            f"{it['rank']}. {it['name']} ({it['zone']}) — P30 {it['p30']:.1%}{flag} · "
            + "; ".join(it["reasons"][:3])
        )
    sc = r["schedule_changes"]
    lines += [
        "",
        "## 4. 점검 주기 권고",
        "",
        f"- 단축 권고 {sc['n_shorten']}개 · 연장 가능 {sc['n_lengthen']}개 · 즉시 점검 {len(sc['urgent'])}개",
        "",
        "## 5. 에너지",
        "",
        f"- 최근 90일 관측 {r['energy']['n_observed_days_90d']}일 · 판정 가능 {r['energy']['n_evaluable_days_90d']}일 · "
        + (
            f"이상 {r['energy']['n_anomaly_days_90d']}일"
            if r["energy"]["n_anomaly_days_90d"] is not None
            else "이상 여부 판정 보류"
        )
        + f" ({r['energy']['status']})"
        + (f": {', '.join(r['energy']['anomalies'])}" if r["energy"]["anomalies"] else ""),
        "",
        "## 6. 점검 기록 품질",
        "",
    ]
    q = r["quality"]["site_average"] or {}
    if q:
        lines.append(
            f"- 형식적 메모 비율 {q['lazy_memo_rate']:.1%} · 20초 미만 체류 {q['short_dwell_rate']:.1%} · 7일 초과 지연 {q['delay_over_7d_rate']:.1%} · 신뢰도 점수 {q['reliability_score']:.2f}"
        )
    for i in r["quality"]["least_reliable"]:
        lines.append(
            f"  - {i['inspector_id']}: 신뢰도 {i['reliability_score']:.2f} (형식적 메모 {i['lazy_memo_rate']:.0%}, 체류 중앙값 {i['dwell_median_s']:.0f}초)"
        )
    lines += ["", "## 7. 유의", ""] + [f"- {c}" for c in r["caveats"]]
    return "\n".join(lines) + "\n"


@router.get("/report")
def report(
    site_id: str,
    as_of: str | None = None,
    format: str = Query("json", pattern="^(json|md)$"),
    store: Store = Depends(get_store),
):
    ensure_site(store, site_id)
    r = build_report(store, site_id, parse_as_of(store, as_of))
    if format == "md":
        return PlainTextResponse(to_markdown(r), media_type="text/markdown; charset=utf-8")
    return r
