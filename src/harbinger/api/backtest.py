"""과거 시점 재현(백테스트) — "그 주 월요일에 이 목록을 줬다면, 이후 30일에 무엇이 났나".

실증(PoC)은 결국 이 질문이다. 주마다 harbinger 상위 K 와 라운드로빈(가장 오래 안 본 K)을 같은 시점에서 뽑고,
각 설비가 (as_of, as_of+30일] 안에 실제로 비계획 고장을 냈는지 센다. 점수 산출에는 as_of 이전 데이터만 쓰인다
(피처가 point-in-time 이다). 모델 학습 기간 이전의 주는 held_out=False 로 표시한다.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from harbinger.prescribe.priority import rank_patrol

HORIZON_DAYS = 30


def breakdown_index(store) -> dict[str, np.ndarray]:
    if getattr(store, "_bd_index", None) is None:
        wo = store.tables["workorders"]
        bd = wo[wo["type"] == "breakdown"].sort_values("opened_at")
        store._bd_index = {a: g["opened_at"].to_numpy("datetime64[ns]") for a, g in bd.groupby("asset_id")}
    return store._bd_index


def days_to_next_breakdown(
    index: dict, asset_id: str, as_of: pd.Timestamp, horizon: int = HORIZON_DAYS
) -> float | None:
    arr = index.get(asset_id)
    if arr is None or len(arr) == 0:
        return None
    t0 = np.datetime64(as_of.to_datetime64(), "ns")
    pos = int(np.searchsorted(arr, t0, side="right"))
    if pos >= len(arr):
        return None
    d = float((arr[pos] - t0) / np.timedelta64(1, "D"))
    return d if d <= horizon else None


def heldout_start(store) -> pd.Timestamp:
    """모델이 학습·캘리브레이션에 쓰지 않은 첫 날. 평가 산출물에 없으면 데이터 끝 180일 전."""
    p = store.settings.artifact_dir / "metrics.json"
    if p.exists():
        try:
            return pd.Timestamp(json.loads(p.read_text())["split"]["val"]["to"])
        except Exception:
            pass
    return store.data_end.normalize() - pd.Timedelta(days=180)


def last_scorable_day(store, horizon: int = HORIZON_DAYS) -> pd.Timestamp:
    """결과(30일 후)까지 데이터가 있는 마지막 기준일."""
    return (store.data_end - pd.Timedelta(days=horizon)).normalize()


def _item(row: dict, days: float | None, extra: dict | None = None) -> dict:
    out = {
        "asset_id": row["asset_id"],
        "name": row["name"],
        "category": row["category"],
        "zone": row["zone"],
        "p30": float(row["p30"]),
        "days_since_inspection": float(row["days_since_inspection"]),
        "failed_within_30d": days is not None,
        "days_to_failure": None if days is None else round(days, 1),
    }
    if extra:
        out.update(extra)
    return out


def replay_site(
    store,
    site_id: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    step_days: int = 7,
    k: int = 10,
    with_items: bool = True,
) -> dict:
    index = breakdown_index(store)
    held = heldout_start(store)
    last_ok = last_scorable_day(store)
    weeks = []
    for d in pd.date_range(start.normalize(), end.normalize(), freq=f"{step_days}D"):
        if d > last_ok:
            break
        as_of = d + pd.Timedelta(hours=23, minutes=59)
        rows = store.latest_rows(site_id, as_of)
        if len(rows) < max(5, k):
            continue
        rows = rows.copy()
        rows["days_since_inspection"] = (as_of - rows["t"]).dt.total_seconds() / 86400
        days = {a: days_to_next_breakdown(index, a, as_of) for a in rows["asset_id"]}
        picks = rank_patrol(rows, as_of, k=k)
        by_id = rows.set_index("asset_id")
        harb_items = []
        for it in picks:
            r = by_id.loc[it.asset_id]
            harb_items.append(
                _item(
                    {**r.to_dict(), "asset_id": it.asset_id},
                    days[it.asset_id],
                    {"mandatory": it.mandatory},
                )
            )
        harb_items.sort(key=lambda x: -x["p30"])
        rr_rows = rows.nsmallest(k, "t")
        rr_items = [_item(r, days[r["asset_id"]]) for r in rr_rows.to_dict("records")]
        week = {
            "as_of": d.date().isoformat(),
            "held_out": bool(d >= held),
            "n_assets": int(len(rows)),
            "base_rate": float(np.mean([v is not None for v in days.values()])),
            "harbinger": {"n": len(harb_items), "hits": int(sum(i["failed_within_30d"] for i in harb_items))},
            "round_robin": {"n": len(rr_items), "hits": int(sum(i["failed_within_30d"] for i in rr_items))},
        }
        if with_items:
            week["harbinger"]["items"] = harb_items
            week["round_robin"]["items"] = rr_items
        weeks.append(week)
    return {
        "site_id": site_id,
        "k": k,
        "step_days": step_days,
        "horizon_days": HORIZON_DAYS,
        "weeks": weeks,
        "summary": summarize(weeks),
    }


def summarize(weeks: list[dict]) -> dict:
    def tot(key: str, field: str) -> int:
        return int(sum(w[key][field] for w in weeks))

    hn, hh = tot("harbinger", "n"), tot("harbinger", "hits")
    rn, rh = tot("round_robin", "n"), tot("round_robin", "hits")
    n_assets = sum(w["n_assets"] for w in weeks)
    base = float(sum(w["base_rate"] * w["n_assets"] for w in weeks) / n_assets) if n_assets else None
    h_rate = hh / hn if hn else None
    r_rate = rh / rn if rn else None
    return {
        "weeks": len(weeks),
        "harbinger_hits": hh,
        "harbinger_picks": hn,
        "harbinger_rate": h_rate,
        "round_robin_hits": rh,
        "round_robin_picks": rn,
        "round_robin_rate": r_rate,
        "base_rate": base,
        "lift_vs_round_robin": (h_rate / r_rate) if (h_rate is not None and r_rate) else None,
        "lift_vs_base": (h_rate / base) if (h_rate is not None and base) else None,
    }


def replay(
    store, site: str, start: pd.Timestamp | None, end: pd.Timestamp | None, step_days: int = 7, k: int = 10
) -> dict:
    """site='all' 이면 사이트별 결과를 주 단위로 합산한다(목록은 생략). 첫 계산은 오래 걸려 결과를 캐시한다."""
    start = start if start is not None else heldout_start(store)
    end = end if end is not None else last_scorable_day(store)
    key = (site, start.date().isoformat(), end.date().isoformat(), step_days, k)
    cache = store.__dict__.setdefault("_replay_cache", {})
    if key in cache:
        return cache[key]
    if site != "all":
        out = replay_site(store, site, start, end, step_days, k, with_items=True)
    else:
        merged: dict[str, dict] = {}
        n_sites = 0
        for sid in store.tables["sites"]["site_id"]:
            r = replay_site(store, sid, start, end, step_days, k, with_items=False)
            n_sites += 1
            for w in r["weeks"]:
                m = merged.setdefault(
                    w["as_of"],
                    {
                        "as_of": w["as_of"],
                        "held_out": w["held_out"],
                        "n_assets": 0,
                        "_base": 0.0,
                        "harbinger": {"n": 0, "hits": 0},
                        "round_robin": {"n": 0, "hits": 0},
                    },
                )
                m["n_assets"] += w["n_assets"]
                m["_base"] += w["base_rate"] * w["n_assets"]
                for who in ("harbinger", "round_robin"):
                    m[who]["n"] += w[who]["n"]
                    m[who]["hits"] += w[who]["hits"]
        weeks = []
        for as_of in sorted(merged):
            m = merged[as_of]
            m["base_rate"] = m.pop("_base") / m["n_assets"] if m["n_assets"] else 0.0
            weeks.append(m)
        out = {
            "site_id": "all",
            "n_sites": n_sites,
            "k": k,
            "step_days": step_days,
            "horizon_days": HORIZON_DAYS,
            "weeks": weeks,
            "summary": summarize(weeks),
        }
    out["heldout_start"] = heldout_start(store).date().isoformat()
    cache[key] = out
    return out


def summary_record(rep: dict) -> dict:
    """전체 사이트 재현 결과에서 문서 숫자 마커가 읽는 요약만 뽑는다 (artifacts/replay_summary.json)."""
    return {
        "k": rep["k"],
        "step_days": rep["step_days"],
        "horizon_days": rep["horizon_days"],
        "n_sites": rep["n_sites"],
        "heldout_start": rep["heldout_start"],
        **rep["summary"],
    }
