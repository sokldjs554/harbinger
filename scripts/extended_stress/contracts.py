"""Deterministic preregistered raw-input changes; no outcomes enter damage."""

from __future__ import annotations

import hashlib

import numpy as np
import pandas as pd
from scripts.robustness.contracts import stable_seed
from scripts.robustness.run import digest

CONDITIONS = (
    "clean",
    "cluster_asset",
    "cluster_inspector",
    "selective_missing",
    "hangul_substitution",
    "abbreviations",
    "delay_7d",
)
HIGH = ("심함", "심각", "긴급", "불량", "파손", "불가", "과열", "정지", "중지", "트립", "연기", "침수")
MEDIUM = (
    "주의",
    "증가",
    "저하",
    "누유",
    "누수",
    "진동",
    "소음",
    "발열",
    "탄내",
    "불안정",
    "오염",
    "부식",
    "마모",
)
ABBREVIATIONS = (
    ("특이사항 없음", "특이無"),
    ("정상 작동 확인", "정상확인"),
    ("운전 상태 양호", "운전OK"),
    ("점검 완료", "점검完"),
    ("교체 필요", "교체要"),
    ("수리 필요", "수리要"),
    ("주의 관찰", "주의관찰"),
    ("베어링", "BRG"),
    ("앵커볼트", "앵커BT"),
    ("필터", "FLT"),
    ("배터리", "BATT"),
    ("오일", "OIL"),
    ("온도", "TEMP"),
    ("압력", "PRESS"),
    ("전류", "AMP"),
)
PAIRS = ((0, 4), (1, 5), (2, 6), (3, 7), (8, 13), (9, 14), (10, 15), (11, 16), (12, 17), (18, 20))
VOWELS = {a: b for pair in PAIRS for a, b in (pair, pair[::-1])} | {19: 20}


def severity(text):
    return "high" if any(w in text for w in HIGH) else "medium" if any(w in text for w in MEDIUM) else "low"


def abbreviate(text):
    for old, new in ABBREVIATIONS:
        text = text.replace(old, new)
    return text


def substitute(text, rng, rate=0.15):
    result, count = [], 0
    for char in text:
        value = ord(char) - 0xAC00
        if 0 <= value < 11172 and rng.random() < rate:
            initial, rest = divmod(value, 588)
            vowel, final = divmod(rest, 28)
            char = chr(0xAC00 + initial * 588 + VOWELS[vowel] * 28 + final)
            count += 1
        result.append(char)
    return "".join(result), count


def perturb(inspections, start, kind, seed):
    if kind not in CONDITIONS[1:-1]:
        raise ValueError("Unknown memo perturbation")
    out = inspections.copy(deep=True)
    start = pd.Timestamp(start)
    eligible = out.performed_at >= start
    counts = {
        "kind": kind,
        "seed": seed,
        "eligible_rows": int(eligible.sum()),
        "changed_rows": 0,
        "removed_rows": 0,
        "eligible_hangul_characters": 0,
        "substituted_characters": 0,
        "severity": {k: {"eligible": 0, "removed": 0} for k in ("low", "medium", "high")},
    }
    for row in out.loc[eligible].itertuples():
        text = str(row.memo) if pd.notna(row.memo) else ""
        new = text
        if kind.startswith("cluster_"):
            group = row.asset_id if kind == "cluster_asset" else row.inspector_id
            phase = stable_seed(f"{seed}:{kind}:{row.site_id}:{group}") % 56
            if ((row.performed_at - start).days + phase) % 56 < 28:
                new = ""
        elif kind == "selective_missing":
            level = severity(text)
            counts["severity"][level]["eligible"] += 1
            rng = np.random.default_rng(stable_seed(f"{seed}:{kind}:{row.inspection_id}"))
            if rng.random() < {"low": 0.1, "medium": 0.5, "high": 0.8}[level]:
                new = ""
                counts["severity"][level]["removed"] += int(bool(text))
        elif kind == "hangul_substitution":
            rng = np.random.default_rng(stable_seed(f"{seed}:{kind}:{row.inspection_id}"))
            new, count = substitute(text, rng)
            counts["eligible_hangul_characters"] += sum(0xAC00 <= ord(c) <= 0xD7A3 for c in text)
            counts["substituted_characters"] += count
        else:
            new = abbreviate(text)
        counts["changed_rows"] += int(new != text)
        counts["removed_rows"] += int(bool(text) and not new)
        out.at[row.Index, "memo"] = new
    payload = out[["inspection_id", "performed_at", "memo"]].sort_values("inspection_id").to_csv(index=False)
    counts["transformed_memo_csv_sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    return out, counts


def verify_files(root, expected):
    for name, sha in expected.items():
        if digest(root / name) != sha:
            raise ValueError(f"hash mismatch: {root / name}")
    return dict(expected)


def rebuild(base, tables, start, condition, seed, fit_until, observation_end):
    from harbinger.features.build import FEATURE_GROUPS, build_features
    from harbinger.models.common import model_columns, to_matrix

    copied = dict(tables)
    copied["inspections"], counts = perturb(tables["inspections"], start, condition, seed)
    copied["energy"] = tables["energy"].iloc[:0].copy()
    altered = build_features(copied, fit_until=fit_until, data_end=observation_end, verbose=False)
    original = base.set_index("inspection_id", verify_integrity=True)
    assert set(altered.inspection_id) == set(original.index)
    for col in [c for c in base if c.startswith("en_")]:
        altered[col] = altered.inspection_id.map(original[col])
    altered = altered.set_index("inspection_id").loc[original.index].reset_index()
    past = base.t < pd.Timestamp(start)
    pd.testing.assert_frame_equal(
        base.loc[past].reset_index(drop=True), altered.loc[past].reset_index(drop=True)
    )
    for cols in (
        ["y30", "event", "tte_days", "label_valid"],
        model_columns(base, tuple(g for g in FEATURE_GROUPS if g != "tx")),
    ):
        pd.testing.assert_frame_equal(to_matrix(base, cols), to_matrix(altered, cols))
    return altered, counts
