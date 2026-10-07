"""평가 파이프라인 — 피처 → 시간 분할 → 모델/베이스라인/절제 → 생존 → 에너지 → 순찰 시뮬레이션 → LOSO → 번들 저장 → artifacts/*.json."""

from __future__ import annotations

import argparse
import json
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.config import DEFAULT_SEED
from harbinger.eval.metrics import c_index_from_risk, censoring_km, classification_metrics, integrated_brier
from harbinger.eval.patrol import breakdown_recall_at_top, simulate_patrol
from harbinger.eval.signals import signal_tables
from harbinger.features.build import FEATURE_GROUPS, build_features, load_tables
from harbinger.features.refresh import Refresher
from harbinger.models.calibration import reliability_table
from harbinger.models.classify import BASELINE_FEATURES, train_hgb, train_logistic
from harbinger.models.coldstart import apply_offset, site_offset
from harbinger.models.common import labeled, model_columns, split_by_time
from harbinger.models.deep import train_deep
from harbinger.models.energy import energy_metrics, train_energy
from harbinger.models.registry import save_bundle
from harbinger.models.survival import c_index, train_survival
from harbinger.prescribe.explain import Explainer
from harbinger.schema import AssetCategory
from harbinger.synth.sites import BETA_SCALE, CATEGORIES, HAZARD_SCALE, SHOCK_HAZARD_PER_DAY

warnings.filterwarnings("ignore")

ABLATIONS = {
    "checklist_only": ("st", "ck", "se"),
    "+text": ("st", "ck", "se", "tx"),
    "+text+quality": ("st", "ck", "se", "tx", "q"),
    "+text+quality+history": ("st", "ck", "se", "tx", "q", "wo"),
    "full(+energy)": FEATURE_GROUPS,
    "full−text": ("st", "ck", "se", "q", "wo", "en"),
    "full−quality": ("st", "ck", "se", "tx", "wo", "en"),
}
SURV_TIMES = [30.0, 60.0, 90.0, 180.0, 360.0]


def _dump(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=float))


def run(
    data_dir: Path,
    model_dir: Path,
    artifact_dir: Path,
    seed: int = DEFAULT_SEED,
    quick: bool = False,
    skip_loso: bool = False,
) -> dict:
    t_start = time.time()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    tables = load_tables(data_dir)
    fpath = data_dir / "features.parquet"
    if fpath.exists():
        X = pd.read_parquet(fpath)
    else:
        X = build_features(tables)
        X.to_parquet(fpath, index=False)
    months = max(1, int(round((X["t"].max() - X["t"].min()).days / 30.44)))
    if months >= 30:
        split = split_by_time(X, 24, 6)
    else:  # 짧은 데이터(CI): 60/15/25 비율
        split = split_by_time(X, max(3, int(months * 0.6)), max(1, int(months * 0.15)))
    trL, vaL, teL = labeled(split.train), labeled(split.val), labeled(split.test)
    full_cols = model_columns(X)
    print(
        f"[eval] split={split.describe()} features={len(full_cols)} labeled train/val/test={len(trL)}/{len(vaL)}/{len(teL)}"
    )
    _dump(artifact_dir / "signals.json", signal_tables(X))
    results: dict = {"split": split.describe(), "n_features": len(full_cols), "seed": seed, "quick": quick}

    # ---------- 1. 메인 분류기 ----------
    t0 = time.time()
    hgb = train_hgb(trL, vaL, full_cols, seed=seed)
    p_raw = hgb.predict_raw(teL)
    p_cal = hgb.predict_proba(teL)
    results["classifier"] = {
        "hgb_full": classification_metrics(teL["y30"], p_cal),
        "hgb_full_uncalibrated": classification_metrics(teL["y30"], p_raw),
        "n_iter": hgb.meta["n_iter"],
        "train_seconds": round(time.time() - t0, 1),
        "calibration": hgb.meta.get("calibration"),
    }
    results["classifier"]["hgb_full"]["c_index"] = c_index_from_risk(
        teL["tte_days"].to_numpy(), teL["event"].to_numpy(), p_cal
    )
    cal = hgb.meta.get("calibration") or {}
    hf = results["classifier"]["hgb_full"]
    hf["calibration_method"] = {
        "raw": "원시 확률(보정 없음)",
        "platt": "Platt 스케일링",
        "isotonic": "isotonic",
    }[cal.get("method", "raw")]
    for k in ("raw", "platt", "isotonic"):
        hf[f"calibration_val_logloss_{k}"] = (cal.get("val_logloss") or {}).get(k)
        hf[f"calibration_val_brier_{k}"] = (cal.get("val_brier") or {}).get(k)
    print(f"[eval] HGB full: {results['classifier']['hgb_full']}")
    _dump(
        artifact_dir / "calibration.json",
        {
            "calibrated": reliability_table(p_cal, teL["y30"].to_numpy()),
            "uncalibrated": reliability_table(p_raw, teL["y30"].to_numpy()),
            "ece_calibrated": results["classifier"]["hgb_full"]["ece"],
            "ece_uncalibrated": results["classifier"]["hgb_full_uncalibrated"]["ece"],
        },
    )

    # ---------- 2. 베이스라인 ----------
    base = {}
    lr = train_logistic(trL, vaL, full_cols, seed=seed)
    base["logistic_full"] = classification_metrics(teL["y30"], lr.predict_proba(teL))
    for name, cols in BASELINE_FEATURES.items():
        b = train_hgb(trL, vaL, cols, seed=seed, name=name)
        base[name] = classification_metrics(teL["y30"], b.predict_proba(teL))
    # 오라클: 숨은 열화 상태 D(t) — 합성 데이터에서만 가능한 상한선
    lat = pd.read_parquet(data_dir / "latent.parquet")
    key = teL[["asset_id", "t"]].copy()
    key["day"] = key["t"].dt.normalize()
    d_now = key.merge(lat, on=["asset_id", "day"], how="left")["d"].fillna(lat["d"].median()).to_numpy()
    # 생성 모델의 위험함수로 환산한 '현재 열화 기준' 30일 고장확률 (이후 30일의 추가 열화는 무시한 근사 상한)
    cat = teL["category"].astype(str).map(lambda c: CATEGORIES[AssetCategory(c)])
    h = (
        np.array([c.h0 for c in cat])
        * HAZARD_SCALE
        * np.exp(np.array([c.beta for c in cat]) * BETA_SCALE * d_now)
        + SHOCK_HAZARD_PER_DAY
    )
    base["oracle_latent_state"] = classification_metrics(teL["y30"], 1 - np.exp(-30 * h))
    # 사전 확률 (상수) — Brier 의 기준점
    base["constant_prior"] = classification_metrics(teL["y30"], np.full(len(teL), trL["y30"].mean()))
    results["baselines"] = base
    print(f"[eval] baselines: { {k: round(v['auroc'], 3) for k, v in base.items()} }")

    # ---------- 3. 절제 ----------
    abl = {}
    for name, groups in ABLATIONS.items():
        cols = model_columns(X, groups)
        b = train_hgb(trL, vaL, cols, seed=seed, name=name)
        abl[name] = classification_metrics(teL["y30"], b.predict_proba(teL)) | {"n_features": len(cols)}
    results["ablation"] = abl
    _dump(artifact_dir / "ablation.json", abl)
    print(f"[eval] ablation: { {k: round(v['auroc'], 3) for k, v in abl.items()} }")

    # ---------- 4. 생존분석 ----------
    surv = {}
    km_c = censoring_km(split.train["tte_days"].to_numpy(), split.train["event"].to_numpy())
    te_all = split.test
    for kind in ("cox", "aft"):
        t0 = time.time()
        try:
            sb = train_survival(
                split.train, full_cols, kind=kind, max_rows=(15000 if quick else 60000), seed=seed
            )
            S = sb.survival_at(te_all, SURV_TIMES)
            p30 = sb.p_fail_within(teL, 30)
            surv[kind] = {
                "c_index": c_index(sb, te_all),
                **integrated_brier(
                    S, SURV_TIMES, te_all["tte_days"].to_numpy(), te_all["event"].to_numpy(), km_c
                ),
                "p30": classification_metrics(teL["y30"], p30),
                "train_seconds": round(time.time() - t0, 1),
                "rows": sb.meta["rows"],
            }
            print(
                f"[eval] survival {kind}: c={surv[kind]['c_index']:.3f} ibs={surv[kind]['ibs']:.4f} p30_auroc={surv[kind]['p30']['auroc']:.3f}"
            )
        except Exception as e:  # 수렴 실패 등은 기록하고 진행
            surv[kind] = {"error": repr(e)}
            print(f"[eval] survival {kind} failed: {e!r}")
    # 분류기의 생존 지표 비교를 위해 HGB 의 P30 을 상수위험으로 펼친 S(t)
    lam = -np.log(1 - hgb.predict_proba(te_all)) / 30.0
    S_hgb = np.exp(-np.outer(lam, np.array(SURV_TIMES)))
    surv["hgb_constant_hazard"] = {
        "c_index": results["classifier"]["hgb_full"]["c_index"],
        **integrated_brier(
            S_hgb, SURV_TIMES, te_all["tte_days"].to_numpy(), te_all["event"].to_numpy(), km_c
        ),
    }

    # ---------- 5. 이산시간 위험 네트 ----------
    deep_res = {}
    deep_full = None
    variants = [("text+site", True, True), ("notext+site", False, True), ("text+nosite", True, False)]
    if quick:
        variants = variants[:1]
    for name, use_text, use_site in variants:
        t0 = time.time()
        db = train_deep(
            split.train,
            split.val,
            full_cols,
            use_text=use_text,
            use_site=use_site,
            epochs=(8 if quick else 40),
            seed=seed,
            verbose=True,
        )
        S = db.survival_curve(te_all)
        S_at = np.stack(
            [S[:, min(S.shape[1] - 1, max(0, int(np.ceil(t / 30)) - 1))] for t in SURV_TIMES], axis=1
        )
        p30 = db.p_fail_within(teL, 30)
        risk = 1 - S[:, -1]
        deep_res[name] = {
            "p30": classification_metrics(teL["y30"], p30),
            "c_index": c_index_from_risk(te_all["tte_days"].to_numpy(), te_all["event"].to_numpy(), risk),
            **integrated_brier(
                S_at, SURV_TIMES, te_all["tte_days"].to_numpy(), te_all["event"].to_numpy(), km_c
            ),
            "best_val_nll": db.meta["best_val_nll"],
            "epochs_run": db.meta["epochs_run"],
            "n_params": db.meta["n_params"],
            "train_seconds": round(time.time() - t0, 1),
        }
        print(
            f"[eval] deep {name}: p30_auroc={deep_res[name]['p30']['auroc']:.3f} c={deep_res[name]['c_index']:.3f} ibs={deep_res[name]['ibs']:.4f}"
        )
        if name == "text+site":
            deep_full = db
    results["survival"] = surv
    results["deep"] = deep_res
    _dump(artifact_dir / "survival.json", {"lifelines": surv, "deep": deep_res, "times": SURV_TIMES})

    # ---------- 6. 에너지 회귀 ----------
    en = tables["energy"]
    en_tr = en[en["day"] < split.train_end]
    en_te = en[en["day"] >= split.val_end]
    eb = train_energy(en_tr, seed=seed)
    en_res = {"test": energy_metrics(eb, en_te), "train": energy_metrics(eb, en_tr)}
    # 오라클 검증: 잔차 7일 이동평균이 숨은 냉방설비 열화(사이트 평균 D)와 얼마나 같이 움직이는가
    anom = eb.anomalies(en_te)
    cool = lat.merge(tables["assets"][["asset_id", "site_id", "category"]], on="asset_id")
    cool = (
        cool[cool["category"].isin(["chiller", "cooling_tower", "ahu"])]
        .groupby(["site_id", "day"])["d"]
        .mean()
        .rename("cool_pen")
        .reset_index()
    )
    a2 = anom.merge(cool, on=["site_id", "day"], how="left").dropna(subset=["cool_pen", "resid_ma"])
    summer = a2[a2["day"].dt.month.isin([6, 7, 8, 9])]
    if len(summer) > 50:
        corr = float(np.corrcoef(summer["resid_ma"], summer["cool_pen"])[0, 1])
        hi = (summer["cool_pen"] > summer["cool_pen"].quantile(0.75)).astype(int).to_numpy()
        en_res["oracle_check"] = {
            "summer_corr_resid_vs_cooling_degradation": corr,
            "auroc_z_vs_high_degradation": classification_metrics(hi, summer["z"].to_numpy())["auroc"],
            "anomaly_day_rate": float(summer["anomaly"].mean()),
            "rows": int(len(summer)),
        }
    results["energy"] = en_res
    _dump(artifact_dir / "energy.json", en_res)
    print(f"[eval] energy: {en_res['test']} oracle={en_res.get('oracle_check')}")

    # ---------- 7. 순찰 시뮬레이션 ----------
    bd_test = tables["workorders"][(tables["workorders"]["type"] == "breakdown")]
    refresher = Refresher(tables)
    score_fns = {"harbinger_hgb": hgb.predict_proba}
    if deep_full is not None:
        score_fns["harbinger_deep"] = lambda df: deep_full.p_fail_within(df, 30)
    patrol = simulate_patrol(te_all, score_fns, bd_test, refresher, k=10, step_days=7, seed=seed)
    scores = {
        "harbinger_hgb": hgb.predict_proba(te_all)
    }  # 행 시점 점수 — 직전 점검 기준 재현율(breakdown_recall_at_top)용
    bd_in_test = bd_test[(bd_test["opened_at"] >= split.val_end + pd.Timedelta(days=30))]
    patrol["recall_top20pct"] = breakdown_recall_at_top(
        te_all, scores["harbinger_hgb"], bd_in_test.head(400 if quick else 2000), 0.2
    )
    results["patrol"] = patrol
    _dump(artifact_dir / "patrol.json", patrol)
    print(
        f"[eval] patrol@10: { {k: round(v['precision_at_k'], 3) for k, v in patrol['methods'].items()} } recall@20%={patrol['recall_top20pct']}"
    )

    # ---------- 8. 설명·중요도 ----------
    imp = None
    try:
        ex = Explainer(hgb)
        sample = teL.sample(min(3000, len(teL)), random_state=seed)
        imp = ex.global_importance(sample, top=30)
        _dump(artifact_dir / "importance.json", imp)
        print(f"[eval] top features: {[(i['feature'], round(i['mean_abs_shap'], 3)) for i in imp[:8]]}")
    except Exception as e:
        print(f"[eval] shap failed: {e!r}")
        results["shap_error"] = repr(e)

    # ---------- 9. LOSO 콜드스타트 ----------
    if not skip_loso:
        results["loso"] = loso(X, split, full_cols, seed=seed, quick=quick)
        _dump(artifact_dir / "loso.json", results["loso"])

    # ---------- 10. 번들 저장 ----------
    headline = {
        "auroc": results["classifier"]["hgb_full"]["auroc"],
        "pr_auc": results["classifier"]["hgb_full"]["pr_auc"],
        "brier": results["classifier"]["hgb_full"]["brier"],
        "ece": results["classifier"]["hgb_full"]["ece"],
        "patrol_precision_at_10": patrol["methods"].get("harbinger_hgb", {}).get("precision_at_k"),
        "patrol_lift_vs_round_robin": patrol["methods"].get("harbinger_hgb", {}).get("lift_vs_round_robin"),
    }
    data_meta = json.loads((data_dir / "meta.json").read_text()) if (data_dir / "meta.json").exists() else {}
    version = save_bundle(
        model_dir,
        classifier=hgb,
        deep=deep_full,
        energy=eb,
        features=full_cols,
        metrics={"headline": headline, "test_window": results["split"]["test"]},
        data_meta=data_meta,
    )
    results["bundle_version"] = version
    results["elapsed_seconds"] = round(time.time() - t_start, 1)
    _dump(artifact_dir / "metrics.json", results)
    print(f"[eval] saved bundle {version}; total {results['elapsed_seconds']}s")
    return results


def loso(X: pd.DataFrame, split, full_cols: list[str], seed: int, quick: bool) -> dict:
    """Leave-one-site-out: 보류 사이트의 테스트 기간을, 다른 사이트로만 학습한 모델 + m 개월치 자체 데이터 오프셋으로 예측."""
    sites = X[["site_id", "st_archetype"]].drop_duplicates().astype(str)
    picks = []
    for _arch, g in sites.groupby("st_archetype"):
        picks += g["site_id"].sort_values().head(1 if quick else 2).tolist()
    months_hist = [0, 3, 6, 12]
    out = {"holdout_sites": picks, "months_of_own_data": months_hist, "per_site": {}, "kappa": 20.0}
    agg: dict[int, list] = {m: [] for m in months_hist}
    for s in picks:
        other_tr = labeled(split.train[split.train["site_id"] != s])
        other_va = labeled(split.val[split.val["site_id"] != s])
        hold_te = labeled(split.test[split.test["site_id"] == s])
        hold_hist = labeled(split.train[split.train["site_id"] == s]).sort_values("t")
        if len(hold_te) < 50 or hold_te["y30"].sum() < 3:
            continue
        b = train_hgb(other_tr, other_va, full_cols, seed=seed, name=f"loso-{s}")
        p_te = b.predict_proba(hold_te)
        per = {}
        t0 = hold_hist["t"].min() if len(hold_hist) else None
        for m in months_hist:
            if m == 0 or t0 is None:
                delta = 0.0
                n_hist = 0
            else:
                h = hold_hist[hold_hist["t"] < t0 + pd.DateOffset(months=m)]
                delta = site_offset(b.predict_proba(h), h["y30"].to_numpy()) if len(h) else 0.0
                n_hist = int(len(h))
            met = classification_metrics(hold_te["y30"], apply_offset(p_te, delta)) | {
                "offset": delta,
                "n_hist_rows": n_hist,
            }
            per[str(m)] = met
            agg[m].append(met)
        # 비교: 그 사이트를 포함해 학습한(warm) 모델
        warm = train_hgb(labeled(split.train), labeled(split.val), full_cols, seed=seed, name="warm")
        per["warm_in_sample_site"] = classification_metrics(hold_te["y30"], warm.predict_proba(hold_te))
        out["per_site"][s] = per
        print(
            f"[loso] {s}: cold={per['0']['auroc']:.3f} brier={per['0']['brier']:.4f} → 12mo brier={per['12']['brier']:.4f} warm={per['warm_in_sample_site']['auroc']:.3f}"
        )
    warm_rows = [v["warm_in_sample_site"] for v in out["per_site"].values()]
    out["mean_warm"] = (
        {k: float(np.nanmean([w[k] for w in warm_rows])) for k in ("auroc", "pr_auc", "brier", "ece")}
        if warm_rows
        else {}
    )
    out["mean_by_months"] = {
        str(m): {k: float(np.nanmean([x[k] for x in v])) for k in ("auroc", "pr_auc", "brier", "ece")}
        for m, v in agg.items()
        if v
    }
    return out


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="harbinger 평가 파이프라인")
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--models", type=Path, default=Path("models"))
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--skip-loso", action="store_true")
    a = ap.parse_args(argv)
    run(a.data, a.models, a.artifacts, seed=a.seed, quick=a.quick, skip_loso=a.skip_loso)


if __name__ == "__main__":
    main()
