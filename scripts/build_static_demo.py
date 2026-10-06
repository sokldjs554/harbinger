"""정적 데모 빌드 — 전체 번들로 API 를 띄우지 않고(TestClient) 콘솔이 쓰는 모든 응답을 JSON 파일로 미리 계산한다.

    python scripts/build_static_demo.py --out docs/demo
결과물은 GitHub Pages 같은 정적 호스팅에 그대로 올리면 된다. 콘솔 app.js 의 slug 규칙과 동일해야 한다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path


def slug(path: str) -> str:
    return path.lstrip("/").replace("?", "__").replace("&", "_").replace("=", "-").replace("/", "_")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("docs/demo"))
    ap.add_argument("--data", type=Path, default=Path("data"))
    ap.add_argument("--models", type=Path, default=Path("models"))
    ap.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--assets-per-site", type=int, default=15)
    a = ap.parse_args()
    os.environ["HARBINGER_DATA_DIR"] = str(a.data)
    os.environ["HARBINGER_MODEL_DIR"] = str(a.models)
    os.environ["HARBINGER_ARTIFACT_DIR"] = str(a.artifacts)
    os.environ["HARBINGER_DEMO_BOOTSTRAP"] = "0"
    from fastapi.testclient import TestClient

    from harbinger import config
    from harbinger.api import main as api_main
    from harbinger.api.store import console_dir

    config.settings = config.Settings()
    api_main.settings = config.settings
    out_api = a.out / "api"
    out_rep = a.out / "reports"
    if a.out.exists():
        shutil.rmtree(a.out)
    out_api.mkdir(parents=True)
    out_rep.mkdir(parents=True)
    t0 = time.time()
    n = 0

    with TestClient(api_main.app) as c:

        def save(path: str) -> dict:
            nonlocal n
            r = c.get(path)
            r.raise_for_status()
            (out_api / f"{slug(path)}.json").write_text(json.dumps(r.json(), ensure_ascii=False))
            n += 1
            return r.json()

        save("/version")
        sites = save("/v1/sites")
        as_of = sites["as_of"][:10]
        for name in ("calibration", "ablation"):
            save(f"/v1/artifacts/{name}")
        save("/v1/monitoring/drift?window_days=60")
        for s in sites["sites"]:
            sid = s["site_id"]
            save(f"/v1/sites/{sid}?as_of={as_of}")
            save(f"/v1/sites/{sid}/patrol/today?as_of={as_of}&k={a.k}&explain=false")
            save(f"/v1/sites/{sid}/patrol/today?as_of={as_of}&k={a.k}")
            assets = save(f"/v1/sites/{sid}/assets?as_of={as_of}&limit={a.assets_per_site}")
            for asset in assets["assets"]:
                save(f"/v1/sites/{sid}/assets/{asset['asset_id']}/risk?as_of={as_of}")
            save(f"/v1/sites/{sid}/energy/anomalies?as_of={as_of}&days=120")
            save(f"/v1/sites/{sid}/quality?as_of={as_of}")
            md = c.get(f"/v1/sites/{sid}/report?as_of={as_of}&format=md")
            (out_rep / f"{sid}.md").write_text(md.text)
            print(f"[demo] {sid} done ({n} files, {time.time() - t0:.0f}s)")

    # 콘솔 정적 파일 + 정적 모드 플래그
    cdir = console_dir()
    for f in ("style.css", "app.js"):
        shutil.copy(cdir / f, a.out / f)
    html = (cdir / "index.html").read_text()
    html = html.replace(
        '<script src="app.js"></script>',
        '<script>window.HARBINGER_STATIC = true;</script>\n<script src="app.js"></script>',
    )
    html = html.replace("<title>harbinger 콘솔</title>", "<title>harbinger 콘솔 (정적 데모)</title>")
    (a.out / "index.html").write_text(html)
    (a.out / ".nojekyll").write_text("")
    (a.out / "README.md").write_text(
        "# harbinger 정적 데모\n\n`scripts/build_static_demo.py` 가 전체 합성 번들에서 미리 계산한 API 응답(`api/`)과 콘솔로 구성된다. "
        f"기준일 {as_of}, 순찰 K={a.k} 고정. 사이트별 실증 리포트는 `reports/`. 모든 데이터는 합성이다.\n"
    )
    total = sum(f.stat().st_size for f in a.out.rglob("*") if f.is_file())
    print(
        f"[demo] wrote {n} api files + reports to {a.out} ({total / 1e6:.1f} MB) in {time.time() - t0:.0f}s"
    )


if __name__ == "__main__":
    main()
