"""테스트 픽스처 — 아주 작은 합성 데이터(아키타입별 1 사이트, 10개월)로 전체 파이프라인을 한 번 돌린다."""

from __future__ import annotations

import os
import warnings
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

warnings.filterwarnings("ignore")


@pytest.fixture(scope="session")
def tiny(tmp_path_factory) -> dict:
    from harbinger.features.build import build_features, load_tables
    from harbinger.synth.generate import GenConfig, generate, write_tables

    root = tmp_path_factory.mktemp("tiny")
    data = root / "data"
    cfg = GenConfig(seed=11, start=date(2024, 1, 1), months=10, scale=0.12, out=data)
    tables = generate(cfg, verbose=False)
    write_tables(tables, data, cfg)
    X = build_features(load_tables(data), verbose=False)
    X.to_parquet(data / "features.parquet", index=False)
    return {"root": root, "data": data, "tables": tables, "X": X, "cfg": cfg}


@pytest.fixture(scope="session")
def trained(tiny) -> dict:
    from harbinger.eval.run import run

    models = tiny["root"] / "models"
    artifacts = tiny["root"] / "artifacts"
    res = run(tiny["data"], models, artifacts, seed=1, quick=True, skip_loso=True)
    return {"results": res, "models": models, "artifacts": artifacts, **tiny}


@pytest.fixture(scope="session")
def client(trained):
    from fastapi.testclient import TestClient

    os.environ["HARBINGER_DATA_DIR"] = str(trained["data"])
    os.environ["HARBINGER_MODEL_DIR"] = str(trained["models"])
    os.environ["HARBINGER_ARTIFACT_DIR"] = str(trained["artifacts"])
    os.environ["HARBINGER_DEMO_BOOTSTRAP"] = "0"
    from harbinger import config
    from harbinger.api import main as api_main

    config.settings = config.Settings()
    api_main.settings = config.settings
    with TestClient(api_main.app) as c:
        yield c


def first_site(client) -> str:
    return client.get("/v1/sites").json()["sites"][0]["site_id"]


def as_ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


__all__ = ["Path"]
