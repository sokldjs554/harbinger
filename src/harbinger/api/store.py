"""인메모리 스토어 — 테이블·피처·모델 번들을 들고 있고, 시점(as_of) 기준 최신 예측을 만든다.

운영에서는 테이블이 FMS DB(또는 그 리플리카)이고 피처는 배치/스트리밍으로 갱신된다. 여기서는 parquet 를 읽어 같은 인터페이스를 제공한다.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.api import backtest, whatif
from harbinger.api.records import inspection_frame, site_tables
from harbinger.config import Settings
from harbinger.features.build import FEATURE_SEMANTICS_VERSION, build_features, load_tables
from harbinger.features.refresh import Refresher
from harbinger.features.text import LAZY_MEMOS
from harbinger.models import site_policy
from harbinger.models.registry import list_versions, load_bundle
from harbinger.monitoring.drift import feature_drift, prediction_drift
from harbinger.monitoring.metrics import (
    ASSETS_LOADED,
    DRIFT_ALERTS,
    DRIFT_LAST_ATTEMPT,
    DRIFT_LAST_SUCCESS,
    DRIFT_STATES,
    DRIFT_STATUS,
    MODEL_INFO,
    PRED_P30,
)
from harbinger.prescribe.explain import Explainer, evidence_for_asset
from harbinger.prescribe.priority import rank_patrol
from harbinger.prescribe.schedule import recommend_interval

log = logging.getLogger("harbinger.store")


class Store:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.tables: dict[str, pd.DataFrame] = {}
        self.X: pd.DataFrame | None = None
        self.bundle: dict | None = None
        self._explainer: Explainer | None = None
        self.loaded_at: float | None = None
        self.data_meta: dict = {}
        self._refresher: Refresher | None = None
        self._drift_cache: dict[int, dict] = {}

    # ---------- 로드 ----------
    def load(self) -> None:
        t0 = time.time()
        d, m = self.settings.data_dir, self.settings.model_dir
        if not (m / "manifest.json").exists() or not (d / "features.parquet").exists():
            if not self.settings.demo_bootstrap:
                raise RuntimeError(
                    "모델 번들 또는 피처가 없습니다. `harbinger bootstrap` 을 먼저 실행하세요."
                )
            log.warning("번들/피처 없음 → 데모 부트스트랩 실행 (합성 데이터, 축소 스케일)")
            from harbinger.cli import bootstrap

            bootstrap(d, m, self.settings.artifact_dir, scale=0.25, months=24)
        self.tables = load_tables(d)
        self.X = pd.read_parquet(d / "features.parquet")
        self.bundle = load_bundle(m)
        try:
            self.bundle["_policy_bundle_hash"] = site_policy.bundle_hash(m, self.bundle)
        except (OSError, ValueError):
            # The optional policy may not weaken the existing baseline loader.
            # Unverifiable in-memory bundles cannot activate policy routing.
            self.bundle["_policy_bundle_hash"] = None
        inspections = self.tables["inspections"]
        if inspections.groupby("inspector_id")["site_id"].nunique().gt(1).any():
            feature_meta_path = d / "features_meta.json"
            feature_meta = json.loads(feature_meta_path.read_text()) if feature_meta_path.exists() else {}
            cache_version = feature_meta.get("provenance", {}).get(
                "feature_semantics_version", feature_meta.get("feature_semantics_version")
            )
            model_version = self.bundle["entry"].get("feature_semantics_version")
            if cache_version != FEATURE_SEMANTICS_VERSION or model_version != FEATURE_SEMANTICS_VERSION:
                raise RuntimeError(
                    "Inspector IDs are reused across sites with legacy feature semantics; "
                    "rebuild features and retrain the model before loading."
                )
        meta_p = d / "meta.json"
        self.data_meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        MODEL_INFO.labels(version=self.bundle["version"]).set(1)
        ASSETS_LOADED.set(len(self.tables["assets"]))
        self.loaded_at = time.time()
        self._refresh_monitoring()
        log.info(
            "store loaded: assets=%d features_rows=%d bundle=%s in %.1fs",
            len(self.tables["assets"]),
            len(self.X),
            self.bundle["version"],
            time.time() - t0,
        )

    @property
    def refresher(self) -> Refresher:
        if self._refresher is None:
            self._refresher = Refresher(self.tables)
        return self._refresher

    @property
    def explainer(self) -> Explainer | None:
        if self._explainer is None and self.bundle is not None:
            try:
                self._explainer = Explainer(self.bundle["classifier"])
            except Exception as e:  # shap 미지원 환경
                log.warning("explainer unavailable: %r", e)
                self._explainer = None
        return self._explainer

    @property
    def data_end(self) -> pd.Timestamp:
        if getattr(self, "_observation_end", None) is not None:
            return self._observation_end
        provenance = (self.bundle or {}).get("entry", {}).get("metrics", {}).get("observation", {})
        return (
            pd.Timestamp(provenance["observation_end"])
            if provenance.get("observation_end")
            else self.X["t"].max()
        )

    def resolve_as_of(self, as_of: str | None) -> pd.Timestamp:
        if not as_of:
            return self.data_end
        ts = pd.Timestamp(as_of)
        return ts + pd.Timedelta(hours=23, minutes=59) if ts == ts.normalize() else ts

    def model_for(self, site_id: str, as_of: pd.Timestamp):
        return site_policy.resolve(self.settings.model_dir, self.bundle, site_id, as_of)

    def explainer_for(self, selected_model: str):
        # Existing TreeExplainer is certified only for the baseline classifier.
        # Returning unavailable is safer than displaying another model's SHAP.
        return self.explainer if selected_model == "baseline" else None

    def score_rows(self, rows: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
        rows = rows.copy()
        routes = site_policy.resolve_many(
            self.settings.model_dir, self.bundle, rows["site_id"].unique(), as_of
        )
        for site_id, index in rows.groupby("site_id").groups.items():
            model, trace = routes[str(site_id)]
            rows.loc[index, "p30"] = model.predict_proba(rows.loc[index])
            for key, value in trace.items():
                if key not in rows:
                    rows[key] = pd.Series(index=rows.index, dtype=object)
                rows.loc[index, key] = value
        return rows

    @staticmethod
    def routing_trace(row) -> dict:
        return {
            key: row.get(key)
            for key in ("selected_model", "policy_revision", "policy_reason", "policy_test_start")
        }

    # ---------- 예측 ----------
    def latest_rows(self, site_id: str | None, as_of: pd.Timestamp, max_age_days: int = 120) -> pd.DataFrame:
        X = self.X
        m = (X["t"] <= as_of) & (X["t"] > as_of - pd.Timedelta(days=max_age_days))
        if site_id:
            m &= X["site_id"] == site_id
        sub = X[m]
        if sub.empty:
            return sub
        rows = sub.loc[sub.groupby("asset_id")["t"].idxmax()].copy()
        rows = rows.merge(self.tables["assets"][["asset_id", "name", "zone"]], on="asset_id", how="left")
        # 점검 뒤에 생긴 고장·정비와 시간 경과를 기준 시각에 맞춰 반영한다 (features/refresh.py)
        rows = self.refresher.apply(rows, as_of)
        rows = self.score_rows(rows, as_of)
        for probability in rows["p30"]:
            if np.isfinite(probability) and 0 <= probability <= 1:
                PRED_P30.observe(float(probability))
        return rows

    def with_deep(self, rows: pd.DataFrame) -> tuple[np.ndarray | None, np.ndarray | None]:
        deep = self.bundle.get("deep")
        if deep is None or rows.empty:
            return None, None
        S = deep.survival_curve(rows)
        return deep.p_fail_within(rows, 30), S

    def asset_risk(
        self, site_id: str, asset_id: str, as_of: pd.Timestamp, explain: bool = True
    ) -> dict | None:
        rows = self.latest_rows(site_id, as_of, max_age_days=36500)
        rows = rows[rows["asset_id"] == asset_id]
        if rows.empty:
            return None
        r = rows.iloc[0]
        p_deep, S = self.with_deep(rows)
        surv = S[0].tolist() if S is not None else None
        out = {
            "asset_id": asset_id,
            "site_id": site_id,
            "name": r["name"],
            "category": r["category"],
            "floor": int(r["st_floor"]),
            "zone": r["zone"],
            "criticality": int(r["st_criticality"]),
            "as_of": as_of.isoformat(timespec="minutes"),
            "last_inspection_at": r["t"].isoformat(timespec="minutes"),
            "p30": float(r["p30"]),
            "p30_deep": (float(p_deep[0]) if p_deep is not None else None),
            "survival_curve_30d_bins": surv,
            "recommendation": recommend_interval(
                r["category"], float(r["p30"]), np.array(surv) if surv else None
            ),
            "model_version": self.bundle["version"],
            **self.routing_trace(r),
        }
        if explain:
            ex = self.explainer_for(r["selected_model"])
            out["explanation"] = {
                "contributions": ex.top_contributions(rows, k=6)[0] if ex else None,
                "status": "available" if ex else "unavailable_for_selected_model",
                "selected_model": r["selected_model"],
                "evidence": evidence_for_asset(
                    self.tables["inspections"], self.tables["workorders"], asset_id, as_of
                ),
            }
        return out

    def patrol(self, site_id: str, as_of: pd.Timestamp, k: int = 10, explain: bool = True) -> dict:
        rows = self.latest_rows(site_id, as_of)
        if rows.empty:
            return {
                "site_id": site_id,
                "as_of": as_of.isoformat(),
                "items": [],
                "note": "해당 시점에 유효한 점검 기록이 없습니다.",
            }
        expl = None
        ex = self.explainer_for(rows.iloc[0]["selected_model"]) if explain else None
        if ex is not None:
            # 상위 후보 3k 개만 설명해 비용을 줄인다
            cand = rows.nlargest(min(len(rows), 3 * k), "p30")
            contrib = ex.top_contributions(cand, k=4)
            cmap = dict(zip(cand["asset_id"], contrib))
            expl = [cmap.get(a, []) for a in rows["asset_id"]]
        items = rank_patrol(rows, as_of, k=k, explanations=expl)
        return {
            "site_id": site_id,
            "as_of": as_of.isoformat(timespec="minutes"),
            "k": k,
            "n_assets_considered": int(len(rows)),
            "expected_breakdowns_in_list": float(sum(i.p30 for i in items)),
            "expected_breakdowns_round_robin": float(rows.nsmallest(k, "t")["p30"].sum()),
            "items": [
                i.to_dict() | self.routing_trace(rows[rows.asset_id == i.asset_id].iloc[0]) for i in items
            ],
            "explanation_status": "available" if ex else "unavailable_for_selected_model",
            **self.routing_trace(rows.iloc[0]),
            "model_version": self.bundle["version"],
        }

    def schedule(self, site_id: str, as_of: pd.Timestamp) -> list[dict]:
        rows = self.latest_rows(site_id, as_of, max_age_days=36500)
        if rows.empty:
            return []
        _, S = self.with_deep(rows)
        out = []
        for i, (_, r) in enumerate(rows.iterrows()):
            rec = recommend_interval(r["category"], float(r["p30"]), S[i] if S is not None else None)
            out.append(
                {
                    "asset_id": r["asset_id"],
                    "name": r["name"],
                    "category": r["category"],
                    "p30": float(r["p30"]),
                    **self.routing_trace(r),
                    "current_interval_days": (
                        None if pd.isna(r["ck_interval_days"]) else float(r["ck_interval_days"])
                    ),
                    **rec,
                }
            )
        return sorted(out, key=lambda x: -x["p30"])

    # ---------- 분석 ----------
    def site_summary(self, site_id: str, as_of: pd.Timestamp) -> dict | None:
        s = self.tables["sites"]
        row = s[s["site_id"] == site_id]
        if row.empty:
            return None
        rows = self.latest_rows(site_id, as_of)
        wo = self.tables["workorders"]
        wo_s = wo[(wo["site_id"] == site_id) & (wo["opened_at"] <= as_of)]
        recent = wo_s[wo_s["opened_at"] > as_of - pd.Timedelta(days=90)]
        a = self.tables["assets"][self.tables["assets"]["site_id"] == site_id]
        return {
            "site_id": site_id,
            "name": row.iloc[0]["name"],
            "archetype": row.iloc[0]["archetype"],
            "floors": int(row.iloc[0]["floors"]),
            "n_assets": int(len(a)),
            "n_inspectors": int((self.tables["inspectors"]["site_id"] == site_id).sum()),
            "as_of": as_of.isoformat(timespec="minutes"),
            "assets_with_recent_inspection": int(len(rows)),
            "mean_p30": float(rows["p30"].mean()) if len(rows) else None,
            "n_high_risk(p30>=0.15)": int((rows["p30"] >= 0.15).sum()) if len(rows) else 0,
            "breakdowns_90d": int((recent["type"] == "breakdown").sum()),
            "downtime_hours_90d": float(recent.loc[recent["type"] == "breakdown", "downtime_hours"].sum()),
            "by_category": rows.groupby("category")["p30"]
            .agg(["count", "mean", "max"])
            .round(4)
            .reset_index()
            .to_dict("records")
            if len(rows)
            else [],
        }

    def sites(self, as_of: pd.Timestamp) -> list[dict]:
        rows = self.latest_rows(None, as_of)
        agg = rows.groupby("site_id")["p30"].agg(["count", "mean", "max"]) if len(rows) else pd.DataFrame()
        out = []
        for _, s in self.tables["sites"].sort_values("site_id").iterrows():
            r = agg.loc[s["site_id"]] if s["site_id"] in agg.index else None
            out.append(
                {
                    "site_id": s["site_id"],
                    "name": s["name"],
                    "archetype": s["archetype"],
                    "floors": int(s["floors"]),
                    "n_assets": int((self.tables["assets"]["site_id"] == s["site_id"]).sum()),
                    "assets_scored": int(r["count"]) if r is not None else 0,
                    "mean_p30": float(r["mean"]) if r is not None else None,
                    "max_p30": float(r["max"]) if r is not None else None,
                }
            )
        return out

    def energy_anomalies(self, site_id: str, as_of: pd.Timestamp, days: int = 120) -> dict:
        eb = self.bundle.get("energy")
        en = self.tables["energy"]
        # Compute on preceding history, then crop the presentation window.
        history = en[(en["site_id"] == site_id) & (en["day"] <= as_of)].sort_values("day")
        lower = as_of - pd.Timedelta(days=days)
        visible = history[history["day"] > lower]
        target = eb.target if eb is not None else "electricity_kwh"

        def number(value):
            return float(value) if pd.notna(value) and np.isfinite(value) else None

        out = {
            "site_id": site_id,
            "window_days": days,
            "target": target,
            "status": "no_data",
            "days": [],
            "anomalies": [],
            "n_observed_days": int(visible.loc[np.isfinite(visible[target]), "day"].nunique()),
            "n_evaluable_days": 0,
            "n_anomaly_days": None,
        }
        if visible.empty:
            return out
        if eb is None:
            out["status"] = "no_model"
            out["days"] = [
                {
                    "day": r["day"].date().isoformat(),
                    "actual": number(r[target]),
                    "expected": None,
                    "resid_ratio": None,
                    "resid_ma7": None,
                    "z": None,
                    "anomaly": None,
                    "status": "no_model",
                }
                for _, r in visible.iterrows()
            ]
            return out
        an = eb.anomalies(history)
        an = an[an["day"] > lower]

        out["days"] = [
            {
                "day": r["day"].date().isoformat(),
                "actual": number(r[target]),
                "expected": number(r["yhat"]),
                "resid_ratio": number(r["resid_ratio"]),
                "resid_ma7": number(r["resid_ma"]),
                "z": number(r["z"]),
                "anomaly": None if pd.isna(r["anomaly"]) else bool(r["anomaly"]),
                "status": r["status"],
            }
            for _, r in an.iterrows()
        ]
        out["n_evaluable_days"] = int(an["anomaly"].notna().sum())
        out["anomalies"] = [d["day"] for d in out["days"] if d["anomaly"] is True]
        if out["n_evaluable_days"]:
            out["status"] = "available"
            out["n_anomaly_days"] = len(out["anomalies"])
        else:
            out["status"] = "no_model" if (an["status"] == "no_model").all() else "insufficient_observation"
        return out

    def quality(self, site_id: str, as_of: pd.Timestamp, days: int = 180) -> dict:
        ins = self.tables["inspections"]
        g = ins[
            (ins["site_id"] == site_id)
            & (ins["performed_at"] <= as_of)
            & (ins["performed_at"] > as_of - pd.Timedelta(days=days))
        ].sort_values(["asset_id", "performed_at"])
        if g.empty:
            return {"site_id": site_id, "inspectors": []}
        g = g.copy()
        g["lazy"] = g["memo"].fillna("").str.strip().isin(LAZY_MEMOS)
        g["dup"] = g["memo"] == g.groupby("asset_id")["memo"].shift(1)
        g["delay"] = (g["performed_at"] - g["scheduled_at"]).dt.total_seconds() / 86400
        g["all_good"] = g["overall"] == 0
        g["short_dwell"] = g["dwell_seconds"] < 20
        rows = []
        for iid, h in g.groupby("inspector_id"):
            rows.append(
                {
                    "inspector_id": iid,
                    "n_inspections": int(len(h)),
                    "lazy_memo_rate": float(h["lazy"].mean()),
                    "dup_memo_rate": float(h["dup"].mean()),
                    "short_dwell_rate": float(h["short_dwell"].mean()),
                    "dwell_median_s": float(h["dwell_seconds"].median()),
                    "delay_mean_days": float(h["delay"].mean()),
                    "delay_over_7d_rate": float((h["delay"] > 7).mean()),
                    "all_good_rate": float(h["all_good"].mean()),
                    "photos_per_inspection": float(h["photo_count"].mean()),
                }
            )
        for r in rows:  # 종합 신뢰도 점수 (0~1): 형식적 메모·짧은 체류·지연이 많을수록 낮다
            r["reliability_score"] = float(
                np.clip(
                    1
                    - 0.5 * r["lazy_memo_rate"]
                    - 0.3 * r["short_dwell_rate"]
                    - 0.2 * r["delay_over_7d_rate"],
                    0,
                    1,
                )
            )
        rows.sort(key=lambda r: r["reliability_score"])
        site_avg = {
            k: float(np.mean([r[k] for r in rows]))
            for k in (
                "lazy_memo_rate",
                "short_dwell_rate",
                "delay_over_7d_rate",
                "all_good_rate",
                "reliability_score",
            )
        }
        return {
            "site_id": site_id,
            "window_days": days,
            "n_inspections": int(len(g)),
            "inspectors": rows,
            "site_average": site_avg,
        }

    def drift(self, window_days: int = 60) -> dict:
        """Cache by data revision and window; scrapes never run model inference."""
        if window_days not in self._drift_cache:
            checked_at = time.time()
            try:
                result = self._calculate_drift(window_days)
            except Exception:
                log.exception("drift calculation failed")
                result = {
                    "status": "error",
                    "window_days": window_days,
                    "features": None,
                    "predictions": None,
                    "model_version": (self.bundle or {}).get("version"),
                }
            result["computed_at"] = checked_at
            self._drift_cache[window_days] = result
        return self._drift_cache[window_days]

    def _refresh_monitoring(self) -> None:
        """Refresh once after load/ingestion; retain the last successful timestamp."""
        self._drift_cache.clear()
        result = self.drift()
        status = result["status"]
        DRIFT_LAST_ATTEMPT.set(result["computed_at"])
        for state in DRIFT_STATES:
            DRIFT_STATUS.labels(state=state).set(int(state == status))
        DRIFT_ALERTS.set(result["features"]["n_alert"] if status == "success" else float("nan"))
        if status == "success":
            DRIFT_LAST_SUCCESS.set(result["computed_at"])

    def _calculate_drift(self, window_days: int) -> dict:
        X = self.X
        # Recent inspections advance monitoring, not certified outcome follow-up.
        monitoring_end = max(self.data_end, X["t"].max()) if len(X) else self.data_end
        feats = self.bundle["entry"]["features"]
        tw = self.bundle["entry"]["metrics"].get("test_window", {})
        ref_end = pd.Timestamp(tw.get("to", str(self.data_end.date()))) - pd.Timedelta(days=365)
        ref = X[X["t"] < ref_end] if (X["t"] < ref_end).sum() > 500 else X.iloc[: len(X) // 2]
        cur = X[(X["t"] > monitoring_end - pd.Timedelta(days=window_days)) & (X["t"] <= monitoring_end)]
        fd = feature_drift(ref, cur, feats)
        p_ref = (
            self.bundle["classifier"].predict_proba(ref.sample(min(5000, len(ref)), random_state=0))
            if len(ref)
            else np.array([])
        )
        p_cur = self.bundle["classifier"].predict_proba(cur) if len(cur) else np.array([])
        predictions = prediction_drift(p_ref, p_cur)
        return {
            "status": "success"
            if fd["status"] == predictions["status"] == "success"
            else "insufficient_data",
            "window_days": window_days,
            "features": fd,
            "predictions": predictions,
            "data_as_of": monitoring_end.isoformat(),
            "model_version": self.bundle["version"],
        }

    def models(self) -> dict:
        return {
            "active": self.bundle["version"],
            "versions": list_versions(self.settings.model_dir),
            "data_meta": self.data_meta,
        }

    # ---------- 인제스트 ----------
    # ---------- 재현·시뮬레이션 ----------
    def replay(self, site: str, start, end, step_days: int = 7, k: int = 10) -> dict:
        return backtest.replay(self, site, start, end, step_days, k)

    def whatif(self, site_id: str, asset_id: str, scenarios: list[dict]) -> dict:
        return whatif.run_whatif(self, site_id, asset_id, scenarios)

    def ingest_inspections(self, site_id: str, records: list[dict]) -> dict:
        """새 점검 기록을 받아 테이블에 붙이고, 영향 받은 설비의 피처를 다시 계산한다 (사이트 단위 재계산)."""
        observation_end = self.data_end
        ins = self.tables["inspections"]
        new = inspection_frame(ins, self.tables["assets"], site_id, records)
        self.tables["inspections"] = pd.concat([ins, new], ignore_index=True)
        self._refresher = None
        # 사이트만 잘라 피처 재계산 (에너지 잔차 적합 구간은 기존과 동일하게 1년)
        sub = site_tables(self.tables, site_id)
        Xs = build_features(
            sub,
            data_end=max(self.tables["inspections"]["performed_at"].max(), self.X["t"].max()),
            verbose=False,
        )
        self.X = pd.concat([self.X[self.X["site_id"] != site_id], Xs], ignore_index=True)
        # Inspection ingestion alone does not certify failure-outcome completeness.
        self._observation_end = observation_end
        self._refresh_monitoring()
        rows = self.latest_rows(site_id, self.X["t"].max(), max_age_days=36500)
        touched = rows[rows["asset_id"].isin(set(new["asset_id"]))]
        return {
            "ingested": int(len(new)),
            "site_id": site_id,
            "features_rebuilt_rows": int(len(Xs)),
            "updated": [
                {
                    "asset_id": r["asset_id"],
                    "p30": float(r["p30"]),
                    "last_inspection_at": r["t"].isoformat(timespec="minutes"),
                }
                for _, r in touched.iterrows()
            ],
        }


def console_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "console"
