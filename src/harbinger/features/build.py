"""피처 빌드 — 점검 1건 = 학습 행 1개.

행의 시점 t 는 점검 수행 시각(performed_at)이다. 모든 피처는 t 이하의 데이터만 쓴다:
  - 체크리스트·메모·체류·지연: 당일 점검 포함 과거 롤링
  - 고장/정비 이력: opened_at < t 인 WO 만
  - 에너지 잔차: t 전날까지의 14/30일 평균. 잔차 모형은 fit_until 이전 데이터로만 적합
라벨:
  - y30      : (t, t+30일] 안에 고장수리(breakdown) WO 가 열렸는가
  - tte_days : 다음 고장까지 일수 (없으면 데이터 끝까지, event=0)
  - label_valid: t+30 이 데이터 끝 이전이어야 y30 을 쓸 수 있다
피처 접두사: st_ 정적 · ck_ 체크리스트 · wo_ 이력 · tx_ 텍스트 · q_ 점검품질 · en_ 에너지 · se_ 계절
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.config import HORIZON_DAYS
from harbinger.features.energy import energy_residuals, rolling_energy_features
from harbinger.features.text import memo_features, novelty
from harbinger.schema import ALL_CHECK_ITEMS, HVAC_CATEGORIES, LEGAL_CATEGORIES, AssetCategory

FEATURE_GROUPS = ("st", "ck", "wo", "tx", "q", "en", "se")
ID_COLS = ["inspection_id", "asset_id", "site_id", "inspector_id", "t", "memo", "category", "archetype"]
LABEL_COLS = ["y30", "label_valid", "tte_days", "event"]


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    names = ("sites", "inspectors", "assets", "inspections", "workorders", "energy")
    return {n: pd.read_parquet(data_dir / f"{n}.parquet") for n in names}


def _window_counts(
    times_by_key: dict, keys: np.ndarray, ts: np.ndarray, window_days: int | None
) -> np.ndarray:
    """키별 정렬된 이벤트 시각 배열에서, 각 행 시각 t 기준 (t-window, t) 안의 이벤트 수. window=None 이면 누적."""
    out = np.zeros(len(ts), dtype=float)
    ts64 = ts.astype("datetime64[ns]").astype("int64")
    for k in np.unique(keys):
        ev = times_by_key.get(k)
        idx = np.flatnonzero(keys == k)
        if ev is None or len(ev) == 0:
            continue
        ev64 = ev.astype("datetime64[ns]").astype("int64")
        hi = np.searchsorted(ev64, ts64[idx], side="left")
        if window_days is None:
            out[idx] = hi
        else:
            lo = np.searchsorted(ev64, ts64[idx] - window_days * 86_400_000_000_000, side="left")
            out[idx] = hi - lo
    return out


def _days_since_last(times_by_key: dict, keys: np.ndarray, ts: np.ndarray) -> np.ndarray:
    out = np.full(len(ts), np.nan)
    ts64 = ts.astype("datetime64[ns]").astype("int64")
    for k in np.unique(keys):
        ev = times_by_key.get(k)
        idx = np.flatnonzero(keys == k)
        if ev is None or len(ev) == 0:
            continue
        ev64 = ev.astype("datetime64[ns]").astype("int64")
        hi = np.searchsorted(ev64, ts64[idx], side="left")
        has = hi > 0
        out[idx[has]] = (ts64[idx[has]] - ev64[hi[has] - 1]) / 86_400_000_000_000
    return out


def _next_event(times_by_key: dict, keys: np.ndarray, ts: np.ndarray) -> np.ndarray:
    """t 이후(> t) 첫 이벤트까지의 일수. 없으면 nan."""
    out = np.full(len(ts), np.nan)
    ts64 = ts.astype("datetime64[ns]").astype("int64")
    for k in np.unique(keys):
        ev = times_by_key.get(k)
        idx = np.flatnonzero(keys == k)
        if ev is None or len(ev) == 0:
            continue
        ev64 = ev.astype("datetime64[ns]").astype("int64")
        pos = np.searchsorted(ev64, ts64[idx], side="right")
        has = pos < len(ev64)
        out[idx[has]] = (ev64[pos[has]] - ts64[idx[has]]) / 86_400_000_000_000
    return out


def build_features(
    tables: dict[str, pd.DataFrame],
    fit_until: pd.Timestamp | None = None,
    data_end: pd.Timestamp | None = None,
    verbose: bool = True,
) -> pd.DataFrame:
    t0 = time.time()
    ins = tables["inspections"].copy()
    assets = tables["assets"]
    sites = tables["sites"]
    wo = tables["workorders"]
    energy = tables["energy"]
    if data_end is None:
        data_end = max(ins["performed_at"].max(), wo["opened_at"].max())
    data_end = pd.Timestamp(data_end)
    if fit_until is None:
        fit_until = ins["performed_at"].min() + pd.Timedelta(days=365)
    fit_until = pd.Timestamp(fit_until)

    ins = ins.sort_values(["asset_id", "performed_at"]).reset_index(drop=True)
    ins = ins.rename(columns={"performed_at": "t"})
    a = assets.merge(sites[["site_id", "archetype"]], on="site_id")
    ins = ins.merge(
        a[["asset_id", "category", "criticality", "floor", "installed", "archetype"]],
        on="asset_id",
        how="left",
    )

    X = ins[
        ["inspection_id", "asset_id", "site_id", "inspector_id", "t", "memo", "category", "archetype"]
    ].copy()

    # ---- 정적 ----
    X["st_age_years"] = (ins["t"] - ins["installed"]).dt.days / 365.25
    X["st_criticality"] = ins["criticality"].astype(float)
    X["st_floor"] = ins["floor"].astype(float)
    X["st_is_legal"] = ins["category"].isin([c.value for c in LEGAL_CATEGORIES]).astype(float)
    X["st_is_hvac"] = ins["category"].isin([c.value for c in HVAC_CATEGORIES]).astype(float)
    X["st_category"] = pd.Categorical(ins["category"], categories=[c.value for c in AssetCategory])
    X["st_archetype"] = pd.Categorical(
        ins["archetype"], categories=["gov_office", "hospital", "hotel", "office"]
    )

    # ---- 체크리스트 (당일 + 롤링) ----
    g = ins.groupby("asset_id", sort=False)
    chk_cols = [f"chk_{i}" for i in ALL_CHECK_ITEMS if f"chk_{i}" in ins]
    chk = ins[chk_cols].astype("float")
    X["ck_overall"] = ins["overall"].astype(float)
    X["ck_n_caution"] = (chk == 1).sum(axis=1).astype(float)
    X["ck_n_bad"] = (chk == 2).sum(axis=1).astype(float)
    X["ck_n_items"] = chk.notna().sum(axis=1).astype(float)
    X["ck_frac_flagged"] = (X["ck_n_caution"] + X["ck_n_bad"]) / X["ck_n_items"].clip(lower=1)
    for c in chk_cols:
        X[f"ck_{c[4:]}"] = chk[c]
    ov = ins["overall"].astype(float)
    X["ck_overall_prev"] = g["overall"].shift(1).astype(float)
    X["ck_overall_mean3"] = ov.groupby(ins["asset_id"]).transform(
        lambda s: s.rolling(3, min_periods=1).mean()
    )
    X["ck_overall_mean6"] = ov.groupby(ins["asset_id"]).transform(
        lambda s: s.rolling(6, min_periods=1).mean()
    )
    X["ck_overall_max3"] = ov.groupby(ins["asset_id"]).transform(lambda s: s.rolling(3, min_periods=1).max())
    X["ck_flag_sum6"] = (
        X["ck_frac_flagged"].groupby(ins["asset_id"]).transform(lambda s: s.rolling(6, min_periods=1).sum())
    )
    X["ck_trend"] = X["ck_overall"] - X["ck_overall_mean6"]
    good = (ov == 0).astype(int)
    # 연속 양호 횟수 (당일 포함)
    grp_break = (good == 0).groupby(ins["asset_id"]).cumsum()
    X["ck_good_streak"] = good.groupby([ins["asset_id"], grp_break]).cumsum().astype(float)
    last_bad_t = ins["t"].where(ov == 2).groupby(ins["asset_id"]).ffill()
    last_cau_t = ins["t"].where(ov >= 1).groupby(ins["asset_id"]).ffill()
    X["ck_days_since_bad"] = (ins["t"] - last_bad_t).dt.total_seconds() / 86400
    X["ck_days_since_caution"] = (ins["t"] - last_cau_t).dt.total_seconds() / 86400
    X["ck_interval_days"] = g["t"].diff().dt.total_seconds() / 86400
    X["ck_n_inspections"] = g.cumcount().astype(float) + 1

    # ---- 텍스트 ----
    tx = memo_features(ins["memo"])
    prev_memo = g["memo"].shift(1)
    tx["tx_dup_prev"] = (ins["memo"].fillna("") == prev_memo.fillna("")).astype(
        float
    ) * prev_memo.notna().astype(float)
    tx["tx_novelty"] = novelty(prev_memo, ins["memo"])
    for col in ("tx_weak_score", "tx_strong_score", "tx_n_groups"):
        tx[f"{col}_sum3"] = (
            tx[col].groupby(ins["asset_id"]).transform(lambda s: s.rolling(3, min_periods=1).sum())
        )
        tx[f"{col}_ewm"] = (
            tx[col].groupby(ins["asset_id"]).transform(lambda s: s.ewm(halflife=2, min_periods=1).mean())
        )
    # 약신호가 '양호' 판정과 함께 나온 횟수 — 체크리스트가 놓친 것을 메모가 잡은 경우
    weak_on_good = ((tx["tx_weak_score"] > 0) & (ov == 0)).astype(float)
    tx["tx_weak_on_good_sum6"] = weak_on_good.groupby(ins["asset_id"]).transform(
        lambda s: s.rolling(6, min_periods=1).sum()
    )
    X = pd.concat([X, tx], axis=1)

    # ---- 점검 품질 ----
    X["q_dwell"] = ins["dwell_seconds"].astype(float)
    # 사이트 체류 중앙값은 '그 시점까지의' 확장 중앙값(당일 제외) — 전체 기간 중앙값을 쓰면 미래 정보가 샌다(테스트가 잡아냈다)
    order_site = ins.sort_values(["site_id", "t"]).index
    site_med = (
        ins.loc[order_site]
        .groupby("site_id")["dwell_seconds"]
        .transform(lambda s: s.shift(1).expanding(min_periods=20).median())
        .reindex(ins.index)
        .astype(float)
    )
    X["q_dwell_rel"] = ins["dwell_seconds"] / site_med.clip(lower=1)
    X["q_delay_days"] = (ins["t"] - ins["scheduled_at"]).dt.total_seconds() / 86400
    X["q_method_beacon"] = (ins["method"] == "beacon").astype(float)
    X["q_method_manual"] = (ins["method"] == "manual").astype(float)
    X["q_photos"] = ins["photo_count"].astype(float)
    lazy_or_dup = ((tx["tx_lazy"] > 0) | (tx["tx_dup_prev"] > 0)).astype(float)
    order = ins.sort_values(["inspector_id", "t"]).index
    ins_sorted_lazy = lazy_or_dup.loc[order]
    insp_lazy = ins_sorted_lazy.groupby(ins.loc[order, "inspector_id"]).transform(
        lambda s: s.rolling(30, min_periods=3).mean()
    )
    X["q_inspector_lazy_rate"] = insp_lazy.reindex(X.index)
    all_good = (ov == 0).astype(float).loc[order]
    insp_good = all_good.groupby(ins.loc[order, "inspector_id"]).transform(
        lambda s: s.rolling(30, min_periods=3).mean()
    )
    X["q_inspector_good_rate"] = insp_good.reindex(X.index)
    dwell_sorted = ins.loc[order, "dwell_seconds"].astype(float)
    insp_dwell = dwell_sorted.groupby(ins.loc[order, "inspector_id"]).transform(
        lambda s: s.rolling(30, min_periods=3).median()
    )
    X["q_inspector_dwell_med"] = insp_dwell.reindex(X.index)
    # 증거 가중치: 점검자가 복붙 성향이거나 체류가 짧으면 이 점검의 '양호'는 덜 믿는다
    lazy_rate = X["q_inspector_lazy_rate"].fillna(0.2)
    dwell_ok = np.where(X["q_dwell"] >= 20, 1.0, 0.5)
    X["q_evidence_weight"] = np.clip((0.25 + 0.75 * (1 - lazy_rate)) * dwell_ok, 0.2, 1.0)
    w = X["q_evidence_weight"]
    num = (w * ov).groupby(ins["asset_id"]).transform(lambda s: s.rolling(6, min_periods=1).sum())
    den = w.groupby(ins["asset_id"]).transform(lambda s: s.rolling(6, min_periods=1).sum())
    X["ck_overall_wmean6"] = num / den.clip(lower=1e-6)
    X["q_evidence_sum6"] = den

    # ---- 고장/정비 이력 (opened_at < t) ----
    wo_s = wo.sort_values("opened_at")
    by_type = {}
    for typ, gg in wo_s.groupby("type"):
        by_type[typ] = {k: v["opened_at"].to_numpy() for k, v in gg.groupby("asset_id")}
    keys = X["asset_id"].to_numpy()
    ts = X["t"].to_numpy()
    bd = by_type.get("breakdown", {})
    X["wo_bd_90d"] = _window_counts(bd, keys, ts, 90)
    X["wo_bd_365d"] = _window_counts(bd, keys, ts, 365)
    X["wo_bd_total"] = _window_counts(bd, keys, ts, None)
    X["wo_days_since_bd"] = _days_since_last(bd, keys, ts)
    X["wo_days_since_pm"] = _days_since_last(by_type.get("preventive", {}), keys, ts)
    X["wo_days_since_parts"] = _days_since_last(by_type.get("parts", {}), keys, ts)
    X["wo_parts_365d"] = _window_counts(by_type.get("parts", {}), keys, ts, 365)
    X["wo_pm_365d"] = _window_counts(by_type.get("preventive", {}), keys, ts, 365)
    X["wo_bd_rate_yr"] = X["wo_bd_total"] / (
        (X["t"] - X["t"].groupby(X["asset_id"]).transform("min")).dt.days / 365.25 + 0.25
    )
    # 사이트 수준 고장률 (최근 180일, 설비 수로 정규화) — 사이트 운영 문화 proxy
    site_bd = {k: v["opened_at"].to_numpy() for k, v in wo_s[wo_s["type"] == "breakdown"].groupby("site_id")}
    n_assets_site = assets.groupby("site_id").size()
    X["wo_site_bd_180d_per_asset"] = (
        _window_counts(site_bd, X["site_id"].to_numpy(), ts, 180) / X["site_id"].map(n_assets_site).to_numpy()
    )

    # ---- 에너지 ----
    resid = energy_residuals(energy, fit_until)
    roll = rolling_energy_features(resid)
    X["_day"] = X["t"].dt.normalize()
    roll = roll.rename(columns={"day": "_day"})
    X = X.merge(
        roll[
            [
                "site_id",
                "_day",
                "en_resid_ratio_14d",
                "en_resid_ratio_30d",
                "en_gas_resid_ratio_14d",
                "en_gas_resid_ratio_30d",
            ]
        ],
        on=["site_id", "_day"],
        how="left",
    )
    X["en_hvac_x_resid30"] = X["st_is_hvac"] * X["en_resid_ratio_30d"].fillna(0)
    X = X.drop(columns=["_day"])

    # ---- 계절 ----
    doy = X["t"].dt.dayofyear
    X["se_sin"] = np.sin(2 * np.pi * doy / 365.25)
    X["se_cos"] = np.cos(2 * np.pi * doy / 365.25)

    # ---- 라벨 ----
    nxt = _next_event(bd, keys, ts)
    X["tte_days"] = np.where(np.isnan(nxt), (data_end - X["t"]).dt.total_seconds() / 86400, nxt)
    X["event"] = (~np.isnan(nxt)).astype(int)
    X["y30"] = ((~np.isnan(nxt)) & (nxt <= HORIZON_DAYS)).astype(int)
    X["label_valid"] = X["t"] + pd.Timedelta(days=HORIZON_DAYS) <= data_end
    # 데이터 끝 이전에 고장이 없으면 끝에서 중도절단
    X.loc[(X["event"] == 0), "tte_days"] = (data_end - X.loc[X["event"] == 0, "t"]).dt.total_seconds() / 86400
    X["tte_days"] = X["tte_days"].clip(lower=0.01)

    X = X.sort_values(["t", "asset_id"]).reset_index(drop=True)
    if verbose:
        n_feat = len(feature_columns(X))
        print(
            f"[features] rows={len(X)} features={n_feat} pos_rate(valid)={X.loc[X.label_valid, 'y30'].mean():.4f} in {time.time() - t0:.1f}s"
        )
    return X


def feature_columns(X: pd.DataFrame, groups: tuple[str, ...] = FEATURE_GROUPS) -> list[str]:
    return [c for c in X.columns if c.split("_")[0] in groups and c not in ID_COLS + LABEL_COLS]


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="point-in-time 피처 빌드")
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--fit-until", type=str, default=None, help="에너지 잔차 모형 적합 종료일 (기본: 시작+365일)"
    )
    a = ap.parse_args(argv)
    tables = load_tables(a.data)
    X = build_features(tables, fit_until=pd.Timestamp(a.fit_until) if a.fit_until else None)
    out = a.out or (a.data / "features.parquet")
    X.to_parquet(out, index=False)
    meta = {
        "rows": int(len(X)),
        "n_features": len(feature_columns(X)),
        "groups": {g: len(feature_columns(X, (g,))) for g in FEATURE_GROUPS},
    }
    (a.data / "features_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
