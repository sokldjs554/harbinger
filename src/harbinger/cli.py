"""`harbinger` 명령 — synth · features · eval · serve · bootstrap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(prog="harbinger")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("synth", help="합성 데이터 생성", add_help=False)
    sub.add_parser("features", help="피처 빌드", add_help=False)
    sub.add_parser("eval", help="학습·평가·번들 저장", add_help=False)
    sv = sub.add_parser("serve", help="API 서버")
    sv.add_argument("--host", default="0.0.0.0")
    sv.add_argument("--port", type=int, default=8000)
    bs = sub.add_parser("bootstrap", help="데이터·모델이 없으면 작은 합성 번들을 만든다 (데모 컨테이너용)")
    bs.add_argument("--data", type=Path, default=Path("data"))
    bs.add_argument("--models", type=Path, default=Path("models"))
    bs.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    bs.add_argument("--scale", type=float, default=0.25)
    bs.add_argument("--months", type=int, default=24)
    a, rest = ap.parse_known_args(argv)
    if a.cmd == "synth":
        from harbinger.synth.generate import main as m

        m(rest)
    elif a.cmd == "features":
        from harbinger.features.build import main as m

        m(rest)
    elif a.cmd == "eval":
        from harbinger.eval.run import main as m

        m(rest)
    elif a.cmd == "serve":
        import uvicorn

        uvicorn.run("harbinger.api.main:app", host=a.host, port=a.port, log_level="info")
    elif a.cmd == "bootstrap":
        bootstrap(a.data, a.models, a.artifacts, a.scale, a.months)


def bootstrap(data: Path, models: Path, artifacts: Path, scale: float, months: int) -> None:
    from harbinger.eval.run import run
    from harbinger.features.build import build_features, load_tables
    from harbinger.synth.generate import GenConfig, generate, write_tables

    if not (data / "inspections.parquet").exists():
        cfg = GenConfig(scale=scale, months=months, out=data)
        write_tables(generate(cfg), data, cfg)
    if not (data / "features.parquet").exists():
        build_features(load_tables(data)).to_parquet(data / "features.parquet", index=False)
    if not (models / "manifest.json").exists():
        run(data, models, artifacts, quick=True, skip_loso=True)


if __name__ == "__main__":
    main()
