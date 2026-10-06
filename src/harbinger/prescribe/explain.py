"""설명 — SHAP 기여도를 현장 언어로 바꾸고, 실제 점검 기록(메모·체크리스트·이력)을 근거로 인용한다."""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from harbinger.features.text import STRONG_MODIFIERS, WEAK_MODIFIERS
from harbinger.models.common import to_matrix
from harbinger.schema import CHECK_ITEM_KO

FEATURE_KO: dict[str, str] = {
    "st_age_years": "설비 연식(년)",
    "st_criticality": "중요도",
    "st_floor": "층",
    "st_is_legal": "법정점검 대상",
    "st_is_hvac": "HVAC 계열",
    "ck_overall": "이번 점검 종합판정",
    "ck_n_caution": "주의 항목 수",
    "ck_n_bad": "불량 항목 수",
    "ck_frac_flagged": "주의·불량 항목 비율",
    "ck_overall_prev": "직전 점검 판정",
    "ck_overall_mean3": "최근 3회 판정 평균",
    "ck_overall_mean6": "최근 6회 판정 평균",
    "ck_overall_max3": "최근 3회 최악 판정",
    "ck_flag_sum6": "최근 6회 지적 항목 누적",
    "ck_trend": "판정 추세(이번−평균)",
    "ck_good_streak": "연속 양호 횟수",
    "ck_days_since_bad": "마지막 불량 후 경과일",
    "ck_days_since_caution": "마지막 주의 후 경과일",
    "ck_interval_days": "점검 간격(일)",
    "ck_n_inspections": "누적 점검 횟수",
    "ck_overall_wmean6": "증거가중 최근 6회 판정",
    "tx_len": "메모 길이",
    "tx_lazy": "형식적 메모",
    "tx_weak_hits": "약한 수식어 수",
    "tx_strong_hits": "강한 수식어 수",
    "tx_n_groups": "메모 증상군 수",
    "tx_weak_score": "메모 약신호 점수",
    "tx_strong_score": "메모 강신호 점수",
    "tx_dup_prev": "직전 메모와 동일",
    "tx_novelty": "메모 참신성",
    "tx_weak_score_sum3": "최근 3회 약신호 합",
    "tx_weak_score_ewm": "약신호 지수가중 평균",
    "tx_strong_score_sum3": "최근 3회 강신호 합",
    "tx_strong_score_ewm": "강신호 지수가중 평균",
    "tx_n_groups_sum3": "최근 3회 증상군 합",
    "tx_n_groups_ewm": "증상군 지수가중 평균",
    "tx_weak_on_good_sum6": "양호 판정인데 메모에 약신호(6회 중)",
    "q_dwell": "체류 시간(초)",
    "q_dwell_rel": "사이트 대비 체류 비율",
    "q_delay_days": "점검 지연(일)",
    "q_method_beacon": "비콘 점검",
    "q_method_manual": "수기 점검",
    "q_photos": "사진 수",
    "q_inspector_lazy_rate": "점검자 형식적 메모 비율",
    "q_inspector_good_rate": "점검자 전부양호 비율",
    "q_inspector_dwell_med": "점검자 체류 중앙값",
    "q_evidence_weight": "이번 점검 증거 가중치",
    "q_evidence_sum6": "최근 6회 증거 합",
    "wo_bd_90d": "최근 90일 고장 수",
    "wo_bd_365d": "최근 1년 고장 수",
    "wo_bd_total": "누적 고장 수",
    "wo_days_since_bd": "마지막 고장 후 경과일",
    "wo_days_since_pm": "마지막 예방정비 후 경과일",
    "wo_days_since_parts": "마지막 부품교체 후 경과일",
    "wo_parts_365d": "최근 1년 부품교체",
    "wo_pm_365d": "최근 1년 예방정비",
    "wo_bd_rate_yr": "연간 고장률",
    "wo_site_bd_180d_per_asset": "사이트 최근 180일 설비당 고장",
    "en_resid_ratio_14d": "전기 잔차 14일",
    "en_resid_ratio_30d": "전기 잔차 30일",
    "en_gas_resid_ratio_14d": "가스 잔차 14일",
    "en_gas_resid_ratio_30d": "가스 잔차 30일",
    "en_hvac_x_resid30": "HVAC×전기 잔차 30일",
    "se_sin": "계절(sin)",
    "se_cos": "계절(cos)",
}
for _item, _ko in CHECK_ITEM_KO.items():
    FEATURE_KO[f"ck_{_item}"] = f"체크리스트: {_ko}"
for _g, _ko in {
    "noise": "소음",
    "vibration": "진동",
    "leak": "누유·누수",
    "thermal": "온도",
    "pressure": "압력",
    "electric": "전기",
    "operation": "작동",
    "wear": "마모·소모품",
    "smell_smoke": "냄새·연기",
    "corrosion": "부식·외관",
    "power_fuel": "전원·연료",
    "level_door": "수위·도어·센서",
}.items():
    FEATURE_KO[f"tx_g_{_g}"] = f"메모 증상: {_ko}"


def feature_label(name: str) -> str:
    if name in FEATURE_KO:
        return FEATURE_KO[name]
    if name.startswith("st_category__"):
        return f"설비 종류={name.split('__')[1]}"
    if name.startswith("st_archetype__"):
        return f"건물 유형={name.split('__')[1]}"
    return name


class Explainer:
    """HGB 분류기용 SHAP 설명기. shap 이 실패하면 트리 기반 permutation 대체는 두지 않고 명시적으로 None 을 돌려준다."""

    def __init__(self, classifier_bundle):
        import shap

        self.bundle = classifier_bundle
        self.explainer = shap.TreeExplainer(classifier_bundle.model)

    def shap_values(self, X: pd.DataFrame) -> np.ndarray:
        M = to_matrix(X, self.bundle.features)
        sv = self.explainer.shap_values(M)
        if isinstance(sv, list):
            sv = sv[1]
        return np.asarray(sv)

    def top_contributions(self, X: pd.DataFrame, k: int = 6) -> list[list[dict]]:
        M = to_matrix(X, self.bundle.features)
        sv = self.shap_values(X)
        out = []
        for i in range(len(X)):
            order = np.argsort(-np.abs(sv[i]))[:k]
            out.append(
                [
                    {
                        "feature": self.bundle.features[j],
                        "label": feature_label(self.bundle.features[j]),
                        "value": (None if pd.isna(M.iat[i, j]) else float(M.iat[i, j])),
                        "contribution": float(sv[i, j]),
                    }
                    for j in order
                ]
            )
        return out

    def global_importance(self, X: pd.DataFrame, top: int = 25) -> list[dict]:
        sv = np.abs(self.shap_values(X)).mean(axis=0)
        order = np.argsort(-sv)[:top]
        return [
            {
                "feature": self.bundle.features[j],
                "label": feature_label(self.bundle.features[j]),
                "mean_abs_shap": float(sv[j]),
            }
            for j in order
        ]


_HL = re.compile(
    "|".join(map(re.escape, sorted(set(WEAK_MODIFIERS + STRONG_MODIFIERS), key=len, reverse=True)))
)


def highlight(memo: str) -> str:
    return _HL.sub(lambda m: f"[{m.group(0)}]", memo or "")


def evidence_for_asset(
    inspections: pd.DataFrame, workorders: pd.DataFrame, asset_id: str, until: pd.Timestamp, n_memos: int = 3
) -> dict:
    """설명에 인용할 원문: 최근 점검 메모(약·강 수식어 표시), 지적 항목, 최근 고장/정비."""
    ins = (
        inspections[(inspections["asset_id"] == asset_id) & (inspections["performed_at"] <= until)]
        .sort_values("performed_at")
        .tail(n_memos)
    )
    memos = []
    for _, r in ins.iterrows():
        flagged = [
            CHECK_ITEM_KO.get(c[4:], c[4:]) + ("(불량)" if r[c] == 2 else "(주의)")
            for c in ins.columns
            if c.startswith("chk_") and pd.notna(r[c]) and r[c] >= 1
        ]
        memos.append(
            {
                "performed_at": r["performed_at"].isoformat(timespec="minutes"),
                "overall": int(r["overall"]),
                "memo": r["memo"],
                "memo_highlighted": highlight(r["memo"]),
                "flagged_items": flagged,
                "dwell_seconds": int(r["dwell_seconds"]),
                "inspector_id": r["inspector_id"],
            }
        )
    wo = (
        workorders[(workorders["asset_id"] == asset_id) & (workorders["opened_at"] <= until)]
        .sort_values("opened_at")
        .tail(5)
    )
    history = [
        {
            "opened_at": r["opened_at"].isoformat(timespec="minutes"),
            "type": r["type"],
            "description": r["description"],
            "downtime_hours": float(r["downtime_hours"]),
        }
        for _, r in wo.iterrows()
    ]
    return {"recent_inspections": memos, "recent_workorders": history}
