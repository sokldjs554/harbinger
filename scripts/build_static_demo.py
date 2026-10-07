"""정적 데모 빌드 — 전체 번들로 콘솔이 쓰는 모든 응답을 JSON 파일로 미리 계산한다 (백엔드 없이 GitHub Pages 에서 동작).

    python scripts/build_static_demo.py --out docs/demo
콘솔 app.js 의 api() 가 `api/<slug(path)>.json` 을 읽는다. slug 규칙과 경로 문자열(P.*)은 app.js 와 글자 하나까지 같아야 하며,
`scripts/smoke_console.cjs` 가 정적 데모에서 404 가 하나라도 나면 실패시켜 어긋남을 잡는다.
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
    ap.add_argument(
        "--whatif-per-site",
        type=int,
        default=8,
        help="사이트별 What-if 를 미리 계산할 상위 위험 설비 수 (0 이면 건너뜀)",
    )
    a = ap.parse_args()
    os.environ["HARBINGER_DATA_DIR"] = str(a.data)
    os.environ["HARBINGER_MODEL_DIR"] = str(a.models)
    os.environ["HARBINGER_ARTIFACT_DIR"] = str(a.artifacts)
    os.environ["HARBINGER_DEMO_BOOTSTRAP"] = "0"
    from fastapi.testclient import TestClient

    from harbinger import config
    from harbinger.api import main as api_main
    from harbinger.api.backtest import summary_record
    from harbinger.api.store import console_dir
    from harbinger.prescribe.scenarios import preset_scenarios

    config.settings = config.Settings()
    api_main.settings = config.settings
    if a.out.exists():
        shutil.rmtree(a.out)
    out_api, out_rep = a.out / "api", a.out / "reports"
    out_api.mkdir(parents=True)
    out_rep.mkdir(parents=True)
    t0 = time.time()
    n = 0

    def dump(name: str, obj) -> None:
        nonlocal n
        (out_api / f"{name}.json").write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        n += 1

    with TestClient(api_main.app) as c:

        def save(path: str) -> dict:
            r = c.get(path)
            r.raise_for_status()
            dump(slug(path), r.json())
            return r.json()

        save("/version")
        lex = save("/v1/text/lexicon")
        assert lex["weak_modifiers"], "렉시콘이 비어 있다"
        sites = save("/v1/sites")
        d = sites["as_of"][:10]
        for name in ("metrics", "calibration", "ablation", "signals", "energy"):
            save(f"/v1/artifacts/{name}")
        save("/v1/monitoring/drift?window_days=60")
        print(f"[demo] global files done ({n}) {time.time() - t0:.0f}s — replay(all) 계산 중…")
        rep_all = save(f"/v1/replay?site=all&k={a.k}")
        # README·docs 의 숫자 마커가 읽는 요약 — 제품 순찰 목록(기대손실×중요도, 법정 강제 포함) 기준의 전체 사이트 재현
        a.artifacts.mkdir(parents=True, exist_ok=True)
        (a.artifacts / "replay_summary.json").write_text(
            json.dumps(summary_record(rep_all), ensure_ascii=False, indent=2)
        )
        print(f"[demo] replay(all) {time.time() - t0:.0f}s")
        for s in sites["sites"]:
            sid = s["site_id"]
            save(f"/v1/sites/{sid}?as_of={d}")
            save(f"/v1/sites/{sid}/patrol/today?as_of={d}&k={a.k}")
            assets = save(f"/v1/sites/{sid}/assets?as_of={d}&limit={a.assets_per_site}")
            for asset in assets["assets"]:
                save(f"/v1/sites/{sid}/assets/{asset['asset_id']}/risk?as_of={d}")
            save(f"/v1/sites/{sid}/energy/anomalies?as_of={d}&days=120")
            save(f"/v1/sites/{sid}/quality?as_of={d}")
            save(f"/v1/replay?site={sid}&k={a.k}")
            (out_rep / f"{sid}.md").write_text(c.get(f"/v1/sites/{sid}/report?as_of={d}&format=md").text)
            for asset in assets["assets"][: a.whatif_per_site]:
                body = {"scenarios": preset_scenarios(asset["category"])}
                r = c.post(f"/v1/sites/{sid}/assets/{asset['asset_id']}/whatif", json=body)
                r.raise_for_status()
                dump(slug(f"/v1/whatif/{sid}/{asset['asset_id']}"), r.json())
            print(f"[demo] {sid} done ({n} files, {time.time() - t0:.0f}s)")

    cdir = console_dir()
    for f in ("style.css", "charts.js", "memo.js", "app.js"):
        shutil.copy(cdir / f, a.out / f)
    html = (cdir / "index.html").read_text()
    html = html.replace(
        '<script src="charts.js"></script>',
        '<script>window.HARBINGER_STATIC = true;</script>\n<script src="charts.js"></script>',
    )
    html = html.replace("<title>harbinger 콘솔</title>", "<title>harbinger — 정적 데모</title>")
    (a.out / "index.html").write_text(html)
    (a.out / ".nojekyll").write_text("")
    (a.out / "README.md").write_text(
        "# harbinger 정적 데모\n\n`scripts/build_static_demo.py` 가 전체 합성 번들에서 미리 계산한 API 응답(`api/`)과 콘솔로 구성된다. "
        f"기준일 {d}, 순찰 K={a.k} 고정. 사이트별 실증 리포트는 `reports/`. 모든 데이터는 합성이다.\n"
    )
    total = sum(f.stat().st_size for f in a.out.rglob("*") if f.is_file())
    print(
        f"[demo] wrote {n} api files + reports to {a.out} ({total / 1e6:.1f} MB) in {time.time() - t0:.0f}s"
    )


if __name__ == "__main__":
    main()
