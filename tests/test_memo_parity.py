"""메모 분석: 파이썬(학습에 쓰는 코드)과 브라우저 포트(console/memo.js)가 같은 결과를 내는지, 그리고 API 가 같은 코드를 쓰는지."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from harbinger.features.text import analyze_memo, lexicon, memo_features

ROOT = Path(__file__).resolve().parents[1]
EDGE = [
    "",
    " ",
    "-",
    "ㅇ",
    "특이사항 없음",
    "이상 無",
    "소음",
    "약간",
    "약간의소음",
    "누유 심함, 긴급 수리",
    "과전류, 트립 발생",
    "교체 필요",
    "수리 필요",
    "ABC noise 약간",
    "소음/진동/누수 약간씩 있음.",
    "  양호  ",
]


def _cases(tiny) -> list[str]:
    memos = list(dict.fromkeys(tiny["tables"]["inspections"]["memo"].dropna().tolist()))
    return EDGE + memos[:400]


def test_analysis_matches_feature_pipeline(tiny):
    """analyze_memo 의 점수는 학습 피처(memo_features)와 같은 값이어야 한다."""
    import pandas as pd

    memos = _cases(tiny)[:200]
    f = memo_features(pd.Series(memos))
    for i, m in enumerate(memos):
        a = analyze_memo(m)
        assert a["weak_score"] == f.iloc[i]["tx_weak_score"]
        assert a["strong_score"] == f.iloc[i]["tx_strong_score"]
        assert a["n_groups"] == f.iloc[i]["tx_n_groups"]
        assert a["lazy"] == bool(f.iloc[i]["tx_lazy"])
        assert "".join(s["text"] for s in a["segments"]) == m, "구간을 이으면 원문이 나와야 한다"


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_js_port_matches_python(tiny, tmp_path):
    cases = [analyze_memo(m) for m in _cases(tiny)]
    (tmp_path / "lexicon.json").write_text(json.dumps(lexicon(), ensure_ascii=False))
    (tmp_path / "cases.json").write_text(json.dumps(cases, ensure_ascii=False))
    proc = subprocess.run(
        [
            "node",
            str(ROOT / "scripts" / "check_memo_parity.cjs"),
            str(tmp_path / "lexicon.json"),
            str(tmp_path / "cases.json"),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert json.loads(proc.stdout.strip().splitlines()[-1])["mismatches"] == 0


def test_api_endpoints(client):
    r = client.post("/v1/text/analyze", json={"memo": "약간의 소음 감지, 미세 진동 감지"})
    assert r.status_code == 200
    a = r.json()
    assert a["weak_score"] == 2.0 and [g["id"] for g in a["groups"]] == ["noise", "vibration"]
    assert client.post("/v1/text/analyze", json={"memo": "x" * 501}).status_code == 422
    lex = client.get("/v1/text/lexicon").json()
    assert "소음" in lex["symptom_groups"]["noise"]["keywords"] and "약간" in lex["weak_modifiers"]
