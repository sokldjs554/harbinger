"""생성 엔진 — 숨은 열화 상태 D(t) → 사람의 점검 관측 → 고장(WO) → 에너지.

하루 단위 루프. 열화·위험·고장은 전체 설비에 대해 벡터화하고, 점검 관측(메모 포함)만 당일 점검 대상에 대해 순회한다.

생성 모델 요약 (docs/synthetic-generator.md 에 수식과 함께 정리):
  D_{t+1} = D_t + Gamma(mean = rate · (1 + age_coef · age) · load · season(t), scale = 0.02)
  h_t     = h0 · exp(beta · D_t) + shock
  고장 → 고장수리 WO, D ← D · U(0.15, 0.5)      (불완전 수리)
  점검   : 항목별 P(주의)=σ((D−θ1)/0.15), P(불량)=σ((D−θ2)/0.12), 점검자 성실도로 감지율 조정
           복붙 점검자는 전부 양호 + 이전 메모 복사 + 체류 수초
  메모   : 양호 판정이어도 θ1 근처면 성실한 점검자는 약신호 문장을 남김
  불량 관측 → 부품교체 WO(수일 후) → D ← D · U(0.2, 0.5) / 연 1회 예방정비 → D ← D · U(0.1, 0.35)
  에너지 : 사이트 일별 전기 = 기준부하 × (0.5+0.5·재실) × (1 + 0.03·CDD·(1 + 1.2·냉방설비 평균 D) + 0.006·HDD) × (1+N(0,0.03))
           가스 = 기준 × (0.25 + 0.06·HDD·(1 + 0.8·보일러 평균 D)) × 재실항 × 잡음 — 열화된 HVAC 는 더운 날 더 많이 쓴다
"""

from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from harbinger.config import DEFAULT_SEED
from harbinger.schema import (
    CATEGORY_KO,
    CHECK_ITEMS,
    LEGAL_CATEGORIES,
    AssetCategory,
    SiteArchetype,
)
from harbinger.synth.calendar_kr import occupancy_index
from harbinger.synth.memos import make_memo
from harbinger.synth.sites import (
    ARCHETYPES,
    BETA_SCALE,
    CATEGORIES,
    HAZARD_SCALE,
    OBS_SHIFT,
    RATE_SCALE,
    SHOCK_HAZARD_PER_DAY,
    WEAK_WINDOW,
)

COOLING_CATS = {AssetCategory.chiller, AssetCategory.cooling_tower, AssetCategory.ahu}
HEATING_CATS = {AssetCategory.boiler}


@dataclass
class GenConfig:
    seed: int = DEFAULT_SEED
    start: date = date(2023, 1, 1)
    months: int = 36
    scale: float = 1.0  # 아키타입별 사이트 수에 곱한다 (CI 는 0.15)
    out: Path = Path("data")


def _sigmoid(x: np.ndarray | float) -> np.ndarray | float:
    return 1.0 / (1.0 + np.exp(-x))


def _temp_series(rng: np.random.Generator, start: date, n_days: int) -> np.ndarray:
    """서울형 일평균 기온: 사인 곡선 + AR(1) 잡음."""
    doy = np.array([(start + timedelta(days=i)).timetuple().tm_yday for i in range(n_days)])
    base = 12.8 + 14.5 * np.sin(2 * np.pi * (doy - 112) / 365.25)
    noise = np.zeros(n_days)
    for i in range(1, n_days):
        noise[i] = 0.7 * noise[i - 1] + rng.normal(0, 2.2)
    return base + noise


def _build_world(rng: np.random.Generator, cfg: GenConfig):
    sites, inspectors, assets = [], [], []
    site_params: dict[str, dict] = {}
    sid = 0
    for arch, spec in ARCHETYPES.items():
        n_sites = max(1, int(round(spec.n_sites * cfg.scale)))
        for k in range(n_sites):
            sid += 1
            site_id = f"S{sid:02d}"
            floors = int(rng.integers(spec.floors[0], spec.floors[1] + 1))
            sites.append(
                {
                    "site_id": site_id,
                    "name": f"{spec.name_prefix} {chr(65 + k)}",
                    "archetype": arch.value,
                    "floors": floors,
                    "opened": cfg.start - timedelta(days=int(rng.integers(365 * 3, 365 * 25))),
                    "region": "seoul",
                }
            )
            site_params[site_id] = {
                "arch": arch,
                "load": spec.load,
                "occupancy": spec.occupancy,
                "elec_base": float(rng.uniform(*spec.elec_base)),
                "gas_base": float(rng.uniform(*spec.gas_base)),
                "water_base": float(rng.uniform(*spec.water_base)),
                "district_heat": spec.district_heat,
                "temp_offset": float(rng.normal(0, 0.6)),
            }
            n_insp = int(rng.integers(spec.inspectors[0], spec.inspectors[1] + 1))
            ids = []
            for j in range(n_insp):
                iid = f"I-{site_id}-{j + 1:02d}"
                ids.append(iid)
                inspectors.append(
                    {
                        "inspector_id": iid,
                        "site_id": site_id,
                        "diligence": float(np.clip(rng.beta(*spec.diligence_beta), 0.05, 0.98)),
                        "copy_paste_rate": float(np.clip(rng.beta(*spec.copy_paste_beta), 0.0, 0.9)),
                        "delay_tendency": float(np.clip(rng.beta(*spec.delay_beta), 0.0, 0.95)),
                    }
                )
            n_assets = int(rng.integers(spec.assets[0], spec.assets[1] + 1))
            cats = list(spec.category_weights.keys())
            w = np.array([spec.category_weights[c] for c in cats], dtype=float)
            w /= w.sum()
            chosen = rng.choice(len(cats), size=n_assets, p=w)
            counter: dict[AssetCategory, int] = {}
            for n, ci in enumerate(chosen):
                cat = cats[ci]
                counter[cat] = counter.get(cat, 0) + 1
                # 기계실 설비는 지하, 공조·환풍·자동문·승강기는 지상층 분포
                if cat in (
                    AssetCategory.chiller,
                    AssetCategory.pump,
                    AssetCategory.boiler,
                    AssetCategory.generator,
                    AssetCategory.switchgear,
                    AssetCategory.fire_pump,
                    AssetCategory.water_tank,
                ):
                    floor = int(rng.integers(-2, 1))
                elif cat == AssetCategory.cooling_tower:
                    floor = floors
                else:
                    floor = int(rng.integers(1, floors + 1))
                age_years = float(rng.uniform(0.5, 22))
                spec_c = CATEGORIES[cat]
                assets.append(
                    {
                        "asset_id": f"A-{site_id}-{n + 1:04d}",
                        "site_id": site_id,
                        "category": cat.value,
                        "name": f"{CATEGORY_KO[cat]} {('B' + str(-floor)) if floor < 0 else str(floor)}F-{counter[cat]}",
                        "floor": floor,
                        "zone": f"{('B' + str(-floor)) if floor < 0 else str(floor)}F-{rng.choice(list('ABC'))}",
                        "installed": cfg.start - timedelta(days=int(age_years * 365.25)),
                        "criticality": int(
                            np.clip(spec_c.criticality + (1 if rng.random() < 0.15 else 0), 1, 3)
                        ),
                        "beacon_id": f"BC-{site_id}-{n + 1:04d}"
                        if arch in (SiteArchetype.gov_office, SiteArchetype.hospital) or rng.random() < 0.3
                        else None,
                        "_primary_inspector": str(rng.choice(ids)),
                    }
                )
    return pd.DataFrame(sites), pd.DataFrame(inspectors), pd.DataFrame(assets), site_params


def generate(cfg: GenConfig, verbose: bool = True) -> dict[str, pd.DataFrame]:
    t0 = time.time()
    rng = np.random.default_rng(cfg.seed)
    n_days = int(
        (
            cfg.start.replace(
                year=cfg.start.year + cfg.months // 12, month=(cfg.start.month - 1 + cfg.months) % 12 + 1
            )
            - cfg.start
        ).days
    )
    sites_df, insp_df, assets_df, site_params = _build_world(rng, cfg)
    n = len(assets_df)
    cats = [AssetCategory(c) for c in assets_df["category"]]
    cat_idx = np.array([list(AssetCategory).index(c) for c in cats])
    cat_list = list(AssetCategory)
    rate = np.array([CATEGORIES[c].rate for c in cats]) * RATE_SCALE
    age_coef = np.array([CATEGORIES[c].age_coef for c in cats])
    beta = np.array([CATEGORIES[c].beta for c in cats]) * BETA_SCALE
    h0 = np.array([CATEGORIES[c].h0 for c in cats]) * HAZARD_SCALE
    season = np.array([CATEGORIES[c].season for c in cats])
    insp_every = np.array([CATEGORIES[c].insp_every for c in cats])
    is_legal = np.array([c in LEGAL_CATEGORIES for c in cats])
    site_ids = assets_df["site_id"].to_numpy()
    site_load = np.array([site_params[s]["load"] for s in site_ids])
    age0 = np.array([(cfg.start - d).days / 365.25 for d in assets_df["installed"]])
    insp_by_site = {s: g["inspector_id"].tolist() for s, g in insp_df.groupby("site_id")}
    insp_trait = insp_df.set_index("inspector_id")[
        ["diligence", "copy_paste_rate", "delay_tendency"]
    ].to_dict("index")
    primary = assets_df["_primary_inspector"].to_numpy()
    arch_by_site = {s: site_params[s]["arch"] for s in site_params}

    # 상태
    D = np.clip(rng.gamma(2.0, 0.18, size=n) * np.minimum(1.0, 0.4 + age0 / 12), 0, 1.1)
    sched_day = rng.integers(0, insp_every + 1, size=n)
    perf_day = sched_day.copy()
    pm_doy = rng.integers(1, 366, size=n)
    prev_memo: list[str | None] = [None] * n
    pending: list[tuple[int, int, float]] = []  # (asset_idx, close_day, reset_factor)
    down_until = np.full(n, -1)

    temps = _temp_series(rng, cfg.start, n_days)
    hol_cache: dict[int, set[date]] = {}
    latent = np.zeros((n_days, n), dtype=np.float32)

    inspections: list[dict] = []
    workorders: list[dict] = []
    energy: list[dict] = []
    n_ins = 0
    n_wo = 0

    def open_wo(
        i: int,
        day: int,
        kind: str,
        severity: int,
        downtime_h: float,
        cost: int,
        desc: str,
        close_after_days: float,
        reset: float,
    ):
        nonlocal n_wo
        n_wo += 1
        opened = datetime.combine(cfg.start + timedelta(days=int(day)), datetime.min.time()) + timedelta(
            hours=float(rng.uniform(7, 19))
        )
        closed = (
            opened + timedelta(hours=float(downtime_h))
            if kind == "breakdown"
            else opened + timedelta(days=float(close_after_days))
        )
        workorders.append(
            {
                "work_order_id": f"W{n_wo:07d}",
                "asset_id": assets_df.at[i, "asset_id"],
                "site_id": site_ids[i],
                "type": kind,
                "opened_at": opened,
                "closed_at": closed,
                "severity": severity,
                "downtime_hours": round(float(downtime_h), 1),
                "parts_cost_krw": int(cost),
                "description": desc,
            }
        )
        pending.append((i, int((closed.date() - cfg.start).days), reset))

    for t in range(n_days):
        day = cfg.start + timedelta(days=t)
        doy = day.timetuple().tm_yday
        T = temps[t]
        cdd = max(0.0, T - 24.0)
        hdd = max(0.0, 18.0 - T)
        age = age0 + t / 365.25

        # ---- 열화 (벡터) ----
        season_mult = np.ones(n)
        season_mult[season == "summer"] = np.clip(1 + 0.8 * cdd / 10, 1, 2.2)
        season_mult[season == "winter"] = np.clip(1 + 0.8 * hdd / 15, 1, 2.2)
        mean_inc = rate * (1 + age_coef * age) * site_load * season_mult
        D = D + rng.gamma(mean_inc / 0.02, 0.02)

        # ---- 조치 완료(WO 종료) → 열화 리셋 ----
        if pending:
            still = []
            for i, cd, rf in pending:
                if cd <= t:
                    D[i] = D[i] * rf
                else:
                    still.append((i, cd, rf))
            pending = still

        # ---- 연 1회 예방정비 ----
        pm_mask = (pm_doy == doy) & (down_until < t)
        for i in np.flatnonzero(pm_mask):
            open_wo(
                int(i),
                t,
                "preventive",
                1,
                0.0,
                int(rng.lognormal(3.6, 0.5) * 10000),
                "연간 예방정비",
                float(rng.uniform(0.5, 2)),
                float(rng.uniform(0.1, 0.35)),
            )

        # ---- 고장 (벡터) ----
        hazard = h0 * np.exp(beta * D) + SHOCK_HAZARD_PER_DAY
        fail = (rng.random(n) < hazard) & (down_until < t)
        for i in np.flatnonzero(fail):
            c = cats[i]
            sp = CATEGORIES[c]
            dt_h = float(np.exp(rng.normal(*sp.downtime)))
            cost = int(np.exp(rng.normal(*sp.cost)) * 10000)
            sev = int(assets_df.at[i, "criticality"])
            open_wo(
                int(i),
                t,
                "breakdown",
                sev,
                dt_h,
                cost,
                f"{CATEGORY_KO[c]} 고장 수리",
                0.0,
                float(rng.uniform(0.15, 0.5)),
            )
            down_until[i] = t + int(math.ceil(dt_h / 24))

        # ---- 점검 ----
        due = np.flatnonzero(perf_day <= t)
        for i in due:
            i = int(i)
            c = cats[i]
            sp = CATEGORIES[c]
            site = site_ids[i]
            insp_id = primary[i] if rng.random() < 0.75 else str(rng.choice(insp_by_site[site]))
            tr = insp_trait[insp_id]
            dil = tr["diligence"]
            copy_paste = rng.random() < tr["copy_paste_rate"]
            d = float(D[i])
            observed: dict[str, int] = {}
            weak: list[str] = []
            for item in CHECK_ITEMS[c]:
                th1, th2 = sp.thresholds[item]
                th1, th2 = th1 + OBS_SHIFT[0], th2 + OBS_SHIFT[1]
                p_bad = _sigmoid((d - th2) / 0.12) * (0.55 + 0.45 * dil)
                p_cau = _sigmoid((d - th1) / 0.15) * (0.45 + 0.55 * dil)
                if copy_paste:
                    lvl = 2 if (d > th2 + 0.3 and rng.random() < 0.5) else 0
                else:
                    u = rng.random()
                    lvl = 2 if u < p_bad else (1 if u < max(p_bad, p_cau) else 0)
                observed[item] = lvl
                if lvl == 0 and (th1 - WEAK_WINDOW) <= d < (th1 + 0.05) and not copy_paste:
                    weak.append(item)
            overall = max(observed.values()) if observed else 0
            if overall == 1 and rng.random() < 0.08:
                overall = 0  # 점검자가 종합 판정을 느슨하게
            memo = make_memo(rng, observed, weak, dil, prev_memo[i], copy_paste)
            prev_memo[i] = memo
            n_items = len(CHECK_ITEMS[c])
            dwell = (
                int(rng.uniform(3, 25))
                if copy_paste
                else int(np.exp(rng.normal(math.log(45 + 50 * dil + 12 * n_items), 0.35)))
            )
            arch = arch_by_site[site]
            if arch in (SiteArchetype.gov_office, SiteArchetype.hospital):
                method = "beacon" if rng.random() < 0.85 else ("nfc" if rng.random() < 0.7 else "manual")
            else:
                method = "nfc" if rng.random() < 0.8 else ("beacon" if rng.random() < 0.5 else "manual")
            sched_dt = datetime.combine(
                cfg.start + timedelta(days=int(sched_day[i])), datetime.min.time()
            ) + timedelta(hours=9)
            perf_dt = datetime.combine(day, datetime.min.time()) + timedelta(hours=float(rng.uniform(8, 18)))
            n_ins += 1
            row = {
                "inspection_id": f"N{n_ins:08d}",
                "asset_id": assets_df.at[i, "asset_id"],
                "site_id": site,
                "inspector_id": insp_id,
                "scheduled_at": sched_dt,
                "performed_at": perf_dt,
                "method": method,
                "dwell_seconds": dwell,
                "overall": overall,
                "memo": memo,
                "photo_count": int(rng.poisson(0.3 + 0.9 * overall)),
            }
            for item in CHECK_ITEMS[c]:
                row[f"chk_{item}"] = observed[item]
            inspections.append(row)

            # 관측 → 조치
            if overall == 2 and rng.random() < 0.85 and down_until[i] < t:
                lag = int(rng.integers(1, 6))
                open_wo(
                    i,
                    t + lag,
                    "parts",
                    2,
                    0.0,
                    int(np.exp(rng.normal(sp.cost[0] - 0.6, 0.5)) * 10000),
                    f"{CATEGORY_KO[c]} 점검 불량 조치",
                    float(rng.uniform(1, 3)),
                    float(rng.uniform(0.2, 0.5)),
                )
            elif overall == 1 and rng.random() < 0.2:
                lag = int(rng.integers(2, 11))
                open_wo(
                    i,
                    t + lag,
                    "preventive",
                    1,
                    0.0,
                    int(np.exp(rng.normal(sp.cost[0] - 1.0, 0.5)) * 10000),
                    f"{CATEGORY_KO[c]} 주의 항목 정비",
                    float(rng.uniform(0.5, 2)),
                    float(rng.uniform(0.4, 0.7)),
                )

            # 다음 점검 일정 — 점검자 지연 성향 반영, 법정 설비는 31일 넘지 않게
            nxt = t + int(sp.insp_every) + int(rng.integers(-2, 3))
            # 지연: 성향이 높을수록 자주, 길게. 기하분포 꼬리로 7일 넘는 지연도 드물게 나온다.
            td = tr["delay_tendency"]
            delay = int(rng.geometric(1.0 / (1.0 + 12.0 * td)) - 1) if rng.random() < (td + 0.1) else 0
            if is_legal[i]:
                delay = min(delay, max(0, 31 - (nxt - t)))
            sched_day[i] = nxt
            perf_day[i] = nxt + delay

        latent[t] = D.astype(np.float32)

        # ---- 에너지 (사이트별) ----
        for s, p in site_params.items():
            mask = site_ids == s
            occ = occupancy_index(day, p["occupancy"], hol_cache)
            Ts = T + p["temp_offset"]
            cdd_s = max(0.0, Ts - 24.0)
            hdd_s = max(0.0, 18.0 - Ts)
            cool_pen = (
                float(np.mean(D[mask & np.isin(cat_idx, [cat_list.index(c) for c in COOLING_CATS])]))
                if np.any(mask & np.isin(cat_idx, [cat_list.index(c) for c in COOLING_CATS]))
                else 0.0
            )
            heat_pen = (
                float(np.mean(D[mask & np.isin(cat_idx, [cat_list.index(c) for c in HEATING_CATS])]))
                if np.any(mask & np.isin(cat_idx, [cat_list.index(c) for c in HEATING_CATS]))
                else 0.0
            )
            elec = (
                p["elec_base"]
                * (0.5 + 0.5 * occ)
                * (1 + 0.03 * cdd_s * (1 + 1.2 * cool_pen) + 0.006 * hdd_s)
                * (1 + rng.normal(0, 0.03))
            )
            gas = (
                p["gas_base"]
                * (0.25 + 0.06 * hdd_s * (1 + 0.8 * heat_pen))
                * (0.6 + 0.4 * occ)
                * (1 + rng.normal(0, 0.05))
            )
            water = p["water_base"] * (0.4 + 0.6 * occ) * (1 + rng.normal(0, 0.07))
            heat = (
                (0.012 * hdd_s * p["elec_base"] / 1000 * (0.7 + 0.3 * occ) * (1 + rng.normal(0, 0.06)))
                if p["district_heat"]
                else 0.0
            )
            energy.append(
                {
                    "site_id": s,
                    "day": day,
                    "electricity_kwh": round(max(0.0, elec), 1),
                    "gas_m3": round(max(0.0, gas), 1),
                    "water_m3": round(max(0.0, water), 1),
                    "heat_gcal": round(max(0.0, heat), 3),
                    "temp_mean_c": round(float(Ts), 1),
                    "occupancy_index": round(float(occ), 2),
                }
            )

        if verbose and (t % 180 == 0 or t == n_days - 1):
            print(
                f"[synth] day {t + 1}/{n_days} inspections={len(inspections)} workorders={len(workorders)} elapsed={time.time() - t0:.1f}s"
            )

    insp_out = pd.DataFrame(inspections)
    for item in sorted({i for v in CHECK_ITEMS.values() for i in v}):
        col = f"chk_{item}"
        if col not in insp_out:
            insp_out[col] = np.nan
        insp_out[col] = insp_out[col].astype("Int8")
    wo_out = pd.DataFrame(workorders).sort_values("opened_at").reset_index(drop=True)
    days = pd.to_datetime([cfg.start + timedelta(days=i) for i in range(n_days)])
    latent_df = (
        pd.DataFrame(latent, index=days, columns=assets_df["asset_id"]).stack().rename("d").reset_index()
    )
    latent_df.columns = ["day", "asset_id", "d"]
    assets_out = assets_df.drop(columns=["_primary_inspector"])
    assets_out["installed"] = pd.to_datetime(assets_out["installed"])
    sites_df["opened"] = pd.to_datetime(sites_df["opened"])
    energy_df = pd.DataFrame(energy)
    energy_df["day"] = pd.to_datetime(energy_df["day"])
    if verbose:
        print(
            f"[synth] done sites={len(sites_df)} assets={n} inspections={len(insp_out)} workorders={len(wo_out)} "
            f"breakdowns={(wo_out['type'] == 'breakdown').sum()} energy_rows={len(energy_df)} in {time.time() - t0:.1f}s"
        )
    return {
        "sites": sites_df,
        "inspectors": insp_df,
        "assets": assets_out,
        "inspections": insp_out,
        "workorders": wo_out,
        "energy": energy_df,
        "latent": latent_df,
    }


def write_tables(tables: dict[str, pd.DataFrame], out: Path, cfg: GenConfig) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        df.to_parquet(out / f"{name}.parquet", index=False)
    meta = {
        "seed": cfg.seed,
        "start": cfg.start.isoformat(),
        "months": cfg.months,
        "scale": cfg.scale,
        "rows": {k: int(len(v)) for k, v in tables.items()},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "synthetic": True,
    }
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="합성 FMS 데이터 생성")
    ap.add_argument("--out", type=Path, default=Path("data"))
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--months", type=int, default=36)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--start", type=lambda s: date.fromisoformat(s), default=date(2023, 1, 1))
    a = ap.parse_args(argv)
    cfg = GenConfig(seed=a.seed, start=a.start, months=a.months, scale=a.scale, out=a.out)
    tables = generate(cfg)
    write_tables(tables, a.out, cfg)


if __name__ == "__main__":
    main()
