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

from harbinger.config import Settings
from harbinger.features.build import build_features, load_tables
from harbinger.features.text import LAZY_MEMOS
from harbinger.models.registry import list_versions, load_bundle
from harbinger.monitoring.drift import feature_drift, prediction_drift
from harbinger.monitoring.metrics import ASSETS_LOADED, DRIFT_ALERTS, MODEL_INFO
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
        meta_p = d / "meta.json"
        self.data_meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
        MODEL_INFO.labels(version=self.bundle["version"]).set(1)
        ASSETS_LOADED.set(len(self.tables["assets"]))
        self.loaded_at = time.time()
        log.info(
            "store loaded: assets=%d features_rows=%d bundle=%s in %.1fs",
            len(self.tables["assets"]),
            len(self.X),
            self.bundle["version"],
            time.time() - t0,
        )

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
        return self.X["t"].max()

    def resolve_as_of(self, as_of: str | None) -> pd.Timestamp:
        if not as_of:
            return self.data_end
        ts = pd.Timestamp(as_of)
        return ts + pd.Timedelta(hours=23, minutes=59) if ts == ts.normalize() else ts

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
        rows["p30"] = self.bundle["classifier"].predict_proba(rows)
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
        }
        if explain:
            ex = self.explainer
            out["explanation"] = {
                "contributions": ex.top_contributions(rows, k=6)[0] if ex else None,
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
        if explain and self.explainer is not None:
            # 상위 후보 3k 개만 설명해 비용을 줄인다
            cand = rows.nlargest(min(len(rows), 3 * k), "p30")
            contrib = self.explainer.top_contributions(cand, k=4)
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
            "items": [i.to_dict() for i in items],
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
        g = en[
            (en["site_id"] == site_id) & (en["day"] <= as_of) & (en["day"] > as_of - pd.Timedelta(days=days))
        ]
        if eb is None or g.empty:
            return {"site_id": site_id, "days": [], "anomalies": []}
        an = eb.anomalies(g)
        return {
            "site_id": site_id,
            "window_days": days,
            "target": eb.target,
            "days": [
                {
                    "day": r["day"].date().isoformat(),
                    "actual": float(r[eb.target]),
                    "expected": float(r["yhat"]),
                    "resid_ratio": float(r["resid_ratio"]),
                    "resid_ma7": (None if pd.isna(r["resid_ma"]) else float(r["resid_ma"])),
                    "z": (None if pd.isna(r["z"]) else float(r["z"])),
                    "anomaly": bool(r["anomaly"]),
                }
                for _, r in an.iterrows()
            ],
            "anomalies": [r["day"].date().isoformat() for _, r in an[an["anomaly"]].iterrows()],
            "n_anomaly_days": int(an["anomaly"].sum()),
        }

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
        X = self.X
        feats = self.bundle["entry"]["features"]
        tw = self.bundle["entry"]["metrics"].get("test_window", {})
        ref_end = pd.Timestamp(tw.get("to", str(self.data_end.date()))) - pd.Timedelta(days=365)
        ref = X[X["t"] < ref_end] if (X["t"] < ref_end).sum() > 500 else X.iloc[: len(X) // 2]
        cur = X[X["t"] > self.data_end - pd.Timedelta(days=window_days)]
        num_feats = [f for f in feats if f in X.columns]
        fd = feature_drift(ref, cur, num_feats)
        p_ref = self.bundle["classifier"].predict_proba(ref.sample(min(5000, len(ref)), random_state=0))
        p_cur = self.bundle["classifier"].predict_proba(cur) if len(cur) else p_ref
        DRIFT_ALERTS.set(fd["n_alert"])
        return {
            "window_days": window_days,
            "features": fd,
            "predictions": prediction_drift(p_ref, p_cur),
            "model_version": self.bundle["version"],
        }

    def models(self) -> dict:
        return {
            "active": self.bundle["version"],
            "versions": list_versions(self.settings.model_dir),
            "data_meta": self.data_meta,
        }

    # ---------- 인제스트 ----------
    def ingest_inspections(self, site_id: str, records: list[dict]) -> dict:
        """새 점검 기록을 받아 테이블에 붙이고, 영향 받은 설비의 피처를 다시 계산한다 (사이트 단위 재계산)."""
        ins = self.tables["inspections"]
        new = pd.DataFrame(records)
        new["site_id"] = site_id
        for c in ("scheduled_at", "performed_at"):
            new[c] = pd.to_datetime(new[c])
        known = set(self.tables["assets"].loc[self.tables["assets"]["site_id"] == site_id, "asset_id"])
        bad = sorted(set(new["asset_id"]) - known)
        if bad:
            raise ValueError(f"알 수 없는 설비: {bad[:5]}")
        for c in ins.columns:
            if c not in new:
                new[c] = pd.NA
        new = new[ins.columns]
        for c in [c for c in ins.columns if c.startswith("chk_")]:
            new[c] = new[c].astype("Int8")
        self.tables["inspections"] = pd.concat([ins, new], ignore_index=True)
        # 사이트만 잘라 피처 재계산 (에너지 잔차 적합 구간은 기존과 동일하게 1년)
        sub = {
            k: (v[v["site_id"] == site_id] if "site_id" in v.columns else v) for k, v in self.tables.items()
        }
        Xs = build_features(
            sub,
            data_end=max(self.tables["inspections"]["performed_at"].max(), self.X["t"].max()),
            verbose=False,
        )
        self.X = pd.concat([self.X[self.X["site_id"] != site_id], Xs], ignore_index=True)
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
