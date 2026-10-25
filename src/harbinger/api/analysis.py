"""Real model scoring and honest, bounded snapshot evaluation for the workbench."""

from __future__ import annotations

import numpy as np
import pandas as pd

from harbinger.api.backtest import breakdown_index, days_to_next_breakdown, heldout_start
from harbinger.eval.metrics import classification_metrics


def safe_json(value):
    if isinstance(value, dict):
        return {str(k): safe_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [safe_json(v) for v in value]
    if isinstance(value, (np.floating, float)) and not np.isfinite(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def analyze(store, as_of, site=None, k=10, source="synthetic-example", observation_confirmed=True):
    rows = store.latest_rows(site, as_of, max_age_days=36500).copy()
    cutoff = heldout_start(store)
    period_complete = as_of + pd.Timedelta(days=30) <= store.data_end
    observed = period_complete and observation_confirmed
    selection_test = pd.to_datetime(
        rows.get("policy_test_start", pd.Series(dtype=object)), errors="coerce"
    ).max()
    selection_held_out = pd.isna(selection_test) or as_of >= selection_test
    model_held_out = cutoff is not None and as_of >= cutoff
    held_out = model_held_out and selection_held_out
    reasons = []
    if not observation_confirmed:
        reasons.append(
            "고장 기록의 완전성이 확인되지 않았습니다. 시설 데이터 담당자 확인 후 다시 업로드하면 평가할 수 있습니다."
        )
    if not period_complete:
        reasons.append("기준일 이후 30일의 관측이 완료되지 않았습니다.")
    if not model_held_out:
        reasons.append("모델 학습·보정 관측 종료 이전이거나 모델 관측 메타데이터가 없습니다.")
    if not selection_held_out:
        reasons.append("사이트 모델 선택 이후 예약된 보류 평가 시작일 이전입니다.")
    if rows.empty:
        reasons.append("이 기준일 이전에 점검된 설비가 없습니다.")
    index = breakdown_index(store)
    records, comparisons, per_site = [], [], []
    if not rows.empty:
        rows["outcome"] = [int(days_to_next_breakdown(index, a, as_of) is not None) for a in rows.asset_id]
        rows["days_since_inspection"] = (as_of - rows.t).dt.total_seconds() / 86400
        for name, model in store.bundle.get("comparators", {}).items():
            rows[name] = model.predict_proba(rows)
        rows["current_model"] = rows.p30
        rows["last_inspection_rule"] = rows.ck_overall * 10000 + rows.days_since_inspection
        rows["age_rule"] = rows.st_age_years
        rows["recent_repair_rule"] = -rows.wo_days_since_bd.fillna(10000)
        rows["oldest_inspection_rule"] = rows.days_since_inspection
        candidates = [
            "current_model",
            *store.bundle.get("comparators", {}),
            "last_inspection_rule",
            "age_rule",
            "recent_repair_rule",
            "oldest_inspection_rule",
        ]
        positives = int(rows.outcome.sum())
        if positives < 3 or len(rows) - positives < 3:
            reasons.append("양성·음성 설비가 각각 3개 이상이어야 성능을 비교합니다.")
        eligible = observed and held_out and positives >= 3 and len(rows) - positives >= 3
        for name in candidates:
            tops = [g.nlargest(min(k, len(g)), name) for _, g in rows.groupby("site_id")]
            selected = pd.concat(tops)
            met = classification_metrics(rows.outcome, rows[name]) if eligible else {}
            comparisons.append(
                {
                    "method": name,
                    "status": "available" if eligible else "withheld",
                    "metrics": met,
                    "precision_at_k": float(selected.outcome.mean()) if eligible else None,
                    "recall_at_k": float(selected.outcome.sum() / positives) if eligible else None,
                    "selected": len(selected),
                    "selected_asset_ids": selected.asset_id.tolist(),
                    "k_per_site": k,
                }
            )
        random_picks = sum(min(k, len(g)) for _, g in rows.groupby("site_id"))
        random_hits = sum(min(k, len(g)) * g.outcome.mean() for _, g in rows.groupby("site_id"))
        comparisons.append(
            {
                "method": "random_expectation",
                "status": "available" if eligible else "withheld",
                "metrics": {},
                "precision_at_k": float(random_hits / random_picks) if eligible else None,
                "recall_at_k": float(random_hits / positives) if eligible else None,
                "selected": random_picks,
                "k_per_site": k,
            }
        )
        for sid, group in rows.groupby("site_id"):
            pos = int(group.outcome.sum())
            ok = observed and held_out and pos >= 3 and len(group) - pos >= 3
            per_site.append(
                {
                    "site_id": sid,
                    "assets": len(group),
                    "positives": pos if observed else None,
                    "status": "available" if ok else "withheld",
                    "reason": None
                    if ok
                    else "고장 기록 완전성·관측 30일·모델 시간 보류·양성/음성 각 3개 조건 확인 필요",
                    "metrics": classification_metrics(group.outcome, group.p30) if ok else {},
                }
            )
        for r in rows.sort_values("p30", ascending=False).to_dict("records"):
            records.append(
                {
                    "asset_id": r["asset_id"],
                    "site_id": r["site_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "floor": r.get("st_floor"),
                    "zone": r.get("zone"),
                    "p30": r["p30"],
                    "selected_model": r.get("selected_model", "baseline"),
                    "policy_revision": r.get("policy_revision"),
                    "policy_reason": r.get("policy_reason", "no_policy"),
                    "policy_test_start": r.get("policy_test_start"),
                    "memo": r["memo"],
                    "inspection_at": r["t"].isoformat(),
                    "overall": int(r["ck_overall"]),
                    "breakdowns_90d": int(r["wo_bd_90d"]),
                    "days_since_inspection": r["days_since_inspection"],
                    "failed_within_30d": bool(r["outcome"]) if observed else None,
                    "days_to_failure": days_to_next_breakdown(index, r["asset_id"], as_of)
                    if observed
                    else None,
                }
            )
    return safe_json(
        {
            "source": source,
            "computation": "live-python-model",
            "model_version": store.bundle["version"],
            "as_of": as_of.isoformat(),
            "observation_end": store.data_end.isoformat(),
            "model_observed_until": cutoff.isoformat() if cutoff is not None else None,
            "selection_test_start": selection_test.isoformat() if pd.notna(selection_test) else None,
            "outcomes_observed": bool(observed),
            "observation_confirmed": bool(observation_confirmed),
            "time_held_out": bool(held_out),
            "customer_holdout": "see published LOSO experiment; this session is not LOSO",
            "evaluation_status": "withheld" if reasons else "available",
            "evaluation_reasons": reasons,
            "assets": records,
            "model_routing": list(
                {
                    (r["site_id"], r["selected_model"], r["policy_revision"], r["policy_reason"]): {
                        key: r[key]
                        for key in (
                            "site_id",
                            "selected_model",
                            "policy_revision",
                            "policy_reason",
                            "policy_test_start",
                        )
                    }
                    for r in records
                }.values()
            ),
            "comparisons": comparisons,
            "per_site": per_site,
            "interpretation": "30일 내 비계획 고장 위험의 탐색적 순위. 합성 학습 모델이며 안전·고장 예방 효과를 보증하지 않습니다.",
        }
    )


def markdown_report(result):
    lines = [
        "# harbinger 분석 보고서",
        "",
        f"- 데이터: {result['source']}",
        f"- 모델: {result['model_version']}",
        f"- 예측 기준: {result['as_of']}",
        f"- 모델 관측 종료: {result['model_observed_until']}",
        f"- 정답 관측 종료: {result['observation_end']}",
        f"- 평가: {result['evaluation_status']}",
        "",
        result["interpretation"],
        "",
        *result["evaluation_reasons"],
        "",
        "| 방법 | Precision@K | Recall@K | AUROC |",
        "|---|---:|---:|---:|",
    ]

    for route in result.get("model_routing", []):
        lines.insert(
            8,
            f"- 사이트 {route['site_id']}: {route['selected_model']} / 정책 {route['policy_revision'] or '없음'} / {route['policy_reason']}",
        )

    def fmt(x):
        return "평가 보류" if x is None else f"{x:.4f}"

    for row in result["comparisons"]:
        lines.append(
            f"| {row['method']} | {fmt(row.get('precision_at_k'))} | {fmt(row.get('recall_at_k'))} | {fmt(row.get('metrics', {}).get('auroc'))} |"
        )
    lines += [
        "",
        "고객사 보류(LOSO)는 별도 실험입니다. 단일 기준일 표에는 신뢰구간을 붙이지 않습니다.",
        "반복 관측의 불확실성은 저장소 평가 산출물의 고객사 단위 bootstrap을 참고하세요.",
        "이 보고서는 실제 고객 실증이나 인과 효과의 증거가 아닙니다.",
    ]
    return "\n".join(lines)
