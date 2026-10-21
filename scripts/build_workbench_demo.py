"""Publish only saved synthetic model responses, explicitly marked as static."""

import argparse
import json
import shutil
from pathlib import Path

import pandas as pd

from harbinger.api.analysis import analyze, safe_json
from harbinger.api.backtest import heldout_start
from harbinger.api.store import Store, console_dir
from harbinger.api.upload import export_example
from harbinger.config import Settings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--models", type=Path, default=Path("models"))
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--out", type=Path, default=Path("docs/demo"))
    args = ap.parse_args()
    store = Store(
        Settings(data_dir=args.data, model_dir=args.models, artifact_dir=args.artifacts, demo_bootstrap=False)
    )
    store.load()
    assert store.data_meta.get("synthetic") is True, "Only synthetic data may be published"
    assert heldout_start(store) is not None, "Boundary-safe model provenance required"
    start = heldout_start(store)
    good = min(start + pd.Timedelta(days=62), store.data_end - pd.Timedelta(days=31))
    dates = [good.date().isoformat(), (store.data_end - pd.Timedelta(days=1)).date().isoformat()]
    sites = store.tables["sites"][["site_id", "name"]].to_dict("records")
    session = {
        "session_id": "saved-example",
        "source": "synthetic-example",
        "summary": {"assets": len(store.tables["assets"]), "sites": len(sites)},
        "sites": sites,
        "default_as_of": dates[0],
        "observation_end": store.data_end.isoformat(),
        "model_version": store.bundle["version"],
    }
    out = {
        "mode": "saved-responses; no live inference",
        "session": session,
        "dates": dates,
        "snapshots": {},
        "evidence": {},
        "artifacts": {},
    }
    for date in dates:
        asof = pd.Timestamp(date) + pd.Timedelta(hours=23, minutes=59, seconds=59)
        evidence_ids = set()
        for site in [None] + [s["site_id"] for s in sites]:
            result = analyze(store, asof, site, 10)
            result["computation"] = "saved-python-model-response"
            out["snapshots"][f"{date}|{site or ''}"] = result
            evidence_ids.update(r["asset_id"] for r in result["assets"][: 10 if site else 50])
        for aid in sorted(evidence_ids):
            sid = store.tables["assets"].set_index("asset_id").loc[aid, "site_id"]
            out["evidence"][f"{date}|{aid}"] = safe_json(store.asset_risk(sid, aid, asof))
        print("saved", date, len(evidence_ids), flush=True)
    for name in ["metrics", "ablation", "loso", "patrol"]:
        path = args.artifacts / f"{name}.json"
        if path.exists():
            out["artifacts"][name] = safe_json(json.loads(path.read_text()))
    # docs/demo is generated output tracked in Git; refuse arbitrary destination deletion.
    args.out.mkdir(parents=True, exist_ok=True)
    for name in ["index.html", "workbench.js", "workbench.css"]:
        shutil.copy2(console_dir() / name, args.out / name)
    html = (
        (args.out / "index.html")
        .read_text()
        .replace(
            '<script src="workbench.js">',
            '<script>window.HARBINGER_SAVED=true;</script><script src="workbench.js">',
        )
    )
    (args.out / "index.html").write_text(html)
    (args.out / "workbench-data.json").write_text(
        json.dumps(out, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    )
    (args.out / "example.csv").write_bytes(export_example(store.tables, sites[0]["site_id"]))
    (args.out / ".nojekyll").touch()
    (args.out / "README.md").write_text(
        "# 저장된 합성 예제\n\n이 폴더는 build_workbench_demo.py로 생성합니다. 업로드와 임의 날짜 계산은 FastAPI 서버에서만 지원합니다.\n\n모델: "
        + store.bundle["version"]
        + "\n"
    )
    print("complete", store.bundle["version"], flush=True)


if __name__ == "__main__":
    main()
