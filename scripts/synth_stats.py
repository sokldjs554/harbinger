"""합성 데이터의 핵심 분포를 출력한다 — 생성 모델 튜닝과 문서 수치 확인용."""

import sys

import pandas as pd

d = sys.argv[1] if len(sys.argv) > 1 else "data/"
ins = pd.read_parquet(f"{d}/inspections.parquet")
wo = pd.read_parquet(f"{d}/workorders.parquet")
lat = pd.read_parquet(f"{d}/latent.parquet")
a = pd.read_parquet(f"{d}/assets.parquet")
insp = pd.read_parquet(f"{d}/inspectors.parquet")
years = (lat.day.max() - lat.day.min()).days / 365.25
print("overall dist:", ins.overall.value_counts(normalize=True).round(3).sort_index().to_dict())
print("WO/asset/yr:", {k: round(v / len(a) / years, 2) for k, v in wo.type.value_counts().to_dict().items()})
print("latent D quantiles:", lat.d.quantile([0.1, 0.25, 0.5, 0.75, 0.9, 0.99]).round(2).to_dict())
bd = (
    wo[wo.type == "breakdown"][["asset_id", "opened_at"]]
    .sort_values("opened_at")
    .rename(columns={"opened_at": "next_bd"})
)
ins2 = ins[["asset_id", "performed_at", "overall"]].sort_values("performed_at")
m = pd.merge_asof(ins2, bd, left_on="performed_at", right_on="next_bd", by="asset_id", direction="forward")
lab = (m.next_bd - m.performed_at).dt.days <= 30
print("30d positive rate:", round(float(lab.mean()), 4), "n=", len(lab))
print("P(fail30 | overall):", m.assign(y=lab).groupby("overall").y.mean().round(3).to_dict())
s = ins.sort_values(["asset_id", "performed_at"])
print(
    "memo len mean:",
    round(float(ins.memo.str.len().mean()), 1),
    " dup-with-prev:",
    round(float((s.groupby("asset_id").memo.shift(1) == s.memo).mean()), 3),
)
print(
    "dwell median:",
    float(ins.dwell_seconds.median()),
    " method:",
    ins.method.value_counts(normalize=True).round(2).to_dict(),
)
dl = (ins.performed_at - ins.scheduled_at).dt.days
print("delay mean:", round(float(dl.mean()), 2), " >7d:", round(float((dl > 7).mean()), 3))
print(ins.sample(10, random_state=1)[["overall", "memo", "dwell_seconds"]].to_string())
print(
    "inspector traits:\n",
    insp[["diligence", "copy_paste_rate", "delay_tendency"]].describe().round(2).loc[["mean", "25%", "75%"]],
)
