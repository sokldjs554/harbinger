"""What-if(반사실) — 상태를 바꾸지 않고 "마지막 점검을 다르게 기록했다면 모델은 이 설비를 어떻게 봤을까"를 계산한다.

사이트 테이블 사본에서 그 설비의 **마지막 점검 1건을 가상의 기록으로 바꿔** point-in-time 피처를 다시 만들고(사이트 단위 0.4~1.3초),
같은 번들로 채점한다. 시각과 이력이 그대로이므로 기준선(실제 기록)과의 차이는 오직 그 기록 때문이다 — 점검 뒤 시간이
흘러 생긴 고장·정비가 섞이지 않게 하려고 '새 점검을 오늘 추가'하는 방식 대신 이 방식을 택했다(처음 방식은 섞였다).
SHAP 차이로 "무엇이 바뀌어서 확률이 움직였나"를 함께 돌려준다. 이 설비의 점검자 롤링 통계도 그 기록을 따라 바뀐다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from harbinger.api.records import inspection_frame, site_tables
from harbinger.features.build import build_features
from harbinger.features.text import analyze_memo
from harbinger.models.common import to_matrix
from harbinger.prescribe.explain import feature_label
from harbinger.schema import CHECK_ITEMS, AssetCategory


def _finite(v):
    return None if v is None or (isinstance(v, float) and not np.isfinite(v)) else float(v)


def _score(store, row: pd.DataFrame) -> tuple[float, float | None]:
    p = float(store.bundle["classifier"].predict_proba(row)[0])
    p_deep, _ = store.with_deep(row)
    return p, (float(p_deep[0]) if p_deep is not None else None)


def run_whatif(store, site_id: str, asset_id: str, scenarios: list[dict]) -> dict:
    assets = store.tables["assets"]
    arow = assets[(assets["asset_id"] == asset_id) & (assets["site_id"] == site_id)]
    if arow.empty:
        raise KeyError(asset_id)
    category = str(arow.iloc[0]["category"])
    valid_items = set(CHECK_ITEMS[AssetCategory(category)])
    sub = site_tables(store.tables, site_id)
    ins = sub["inspections"]
    mine = ins[ins["asset_id"] == asset_id].sort_values("performed_at")
    if mine.empty:
        raise ValueError("점검 기록이 없는 설비입니다")
    last = mine.iloc[-1]
    performed = last["performed_at"]
    ins_wo_last = ins[ins["inspection_id"] != last["inspection_id"]]

    # 기준선: 같은 사이트 사본에서 다시 만든 마지막 행
    Xb = build_features(sub, verbose=False)
    base_row = Xb[Xb["inspection_id"] == last["inspection_id"]]
    base_p, base_deep = _score(store, base_row)
    ex = store.explainer
    features = store.bundle["classifier"].features
    sv_base = ex.shap_values(base_row)[0] if ex else None
    base_matrix = to_matrix(base_row, features)

    out_scn = []
    for n, sc in enumerate(scenarios, start=1):
        items = {k: int(v) for k, v in (sc.get("items") or {}).items()}
        unknown = sorted(set(items) - valid_items)
        if unknown:
            raise ValueError(f"{category} 설비에 없는 점검 항목: {unknown}")
        overall = (
            int(sc["overall"]) if sc.get("overall") is not None else (max(items.values()) if items else 0)
        )
        rec = {
            "inspection_id": f"WHATIF-{n}",
            "asset_id": asset_id,
            "inspector_id": sc.get("inspector_id") or str(last["inspector_id"]),
            "scheduled_at": last["scheduled_at"],
            "performed_at": performed,
            "method": str(last["method"]),
            "dwell_seconds": int(sc.get("dwell_seconds", 120)),
            "overall": overall,
            "memo": str(sc.get("memo", "")),
            "photo_count": int(last["photo_count"]),
            **{f"chk_{k}": v for k, v in items.items()},
        }
        new = inspection_frame(ins, assets, site_id, [rec])
        sub2 = dict(sub)
        sub2["inspections"] = pd.concat([ins_wo_last, new], ignore_index=True)
        Xn = build_features(sub2, verbose=False)
        row = Xn[Xn["inspection_id"] == rec["inspection_id"]]
        p, p_deep = _score(store, row)
        changed = []
        if ex is not None:
            sv_new = ex.shap_values(row)[0]
            mat = to_matrix(row, features)
            for j in np.argsort(-np.abs(sv_new - sv_base))[:5]:
                if abs(sv_new[j] - sv_base[j]) < 1e-6:
                    continue
                changed.append(
                    {
                        "feature": features[j],
                        "label": feature_label(features[j]),
                        "from": _finite(base_matrix.iat[0, j]),
                        "to": _finite(mat.iat[0, j]),
                        "shap_delta": float(sv_new[j] - sv_base[j]),
                    }
                )
        out_scn.append(
            {
                "id": sc.get("id") or str(n),
                "name": sc.get("name") or f"시나리오 {n}",
                "description": sc.get("description", ""),
                "items": items,
                "overall": overall,
                "memo": rec["memo"],
                "dwell_seconds": rec["dwell_seconds"],
                "p30": p,
                "p30_deep": p_deep,
                "delta": p - base_p,
                "changed": changed,
                "memo_analysis": analyze_memo(rec["memo"]),
            }
        )
    return {
        "site_id": site_id,
        "asset_id": asset_id,
        "name": str(arow.iloc[0]["name"]),
        "category": category,
        "performed_at": performed.isoformat(timespec="minutes"),
        "baseline": {
            "p30": base_p,
            "p30_deep": base_deep,
            "last_inspection_at": last["performed_at"].isoformat(timespec="minutes"),
            "inspector_id": str(last["inspector_id"]),
            "dwell_seconds": int(last["dwell_seconds"]),
            "items": {c[4:]: int(last[c]) for c in ins.columns if c.startswith("chk_") and pd.notna(last[c])},
            "memo": str(last["memo"]),
            "overall": int(last["overall"]),
            "memo_analysis": analyze_memo(str(last["memo"])),
        },
        "scenarios": out_scn,
        "model_version": store.bundle["version"],
        "note": "반사실 시뮬레이션: 마지막 점검(기준선=실제 기록)을 가상의 기록으로 바꿔 같은 시각·같은 이력에서 다시 채점했습니다. 서버 상태는 바뀌지 않습니다.",
    }
