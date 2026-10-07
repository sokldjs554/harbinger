"""한국어 점검 메모 → 약신호 피처.

렉시콘은 증상 어근(소음·진동·누유…)과 강도 수식어(약간·미세 / 심함·긴급)로 구성한다.
생성 템플릿(synth/memos.py)을 그대로 베끼지 않도록 어근 단위로만 맞춘다.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

SYMPTOM_GROUPS: dict[str, list[str]] = {
    "noise": ["소음", "금속성"],
    "vibration": ["진동", "흔들"],
    "leak": ["누유", "오일", "누수", "물기", "습기", "누설"],
    "thermal": ["온도", "뜨거", "발열", "과열", "고온"],
    "pressure": ["압력", "차압"],
    "electric": ["전류", "과전류", "트립", "절연", "전압", "방전"],
    "operation": ["작동", "기동", "반응", "운행", "정지", "불가"],
    "wear": ["벨트", "필터", "마모", "장력", "슬립", "충진", "스케일", "팬"],
    "smell_smoke": ["탄내", "냄새", "연기"],
    "corrosion": ["부식", "도장", "외관", "손상"],
    "power_fuel": ["배터리", "연료", "점화", "연소", "실화"],
    "level_door": ["수위", "급수", "도어", "착상", "센서"],
}
WEAK_MODIFIERS = [
    "약간",
    "미세",
    "소량",
    "조금",
    "간헐",
    "소폭",
    "흔적",
    "의심",
    "느림",
    "둔함",
    "근접",
    "변동",
    "느슨",
    "번짐",
    "간혹",
]
STRONG_MODIFIERS = [
    "심함",
    "심각",
    "긴급",
    "즉시",
    "불가",
    "정지",
    "파손",
    "급등",
    "급저하",
    "과열",
    "과전류",
    "트립",
    "끊어",
    "방전",
    "실화",
    "경보",
    "침수",
    "위험",
    "불량",
    "고장",
    "교체 필요",
    "수리",
]
LAZY_MEMOS = {
    "",
    "-",
    "ㅇ",
    "양호",
    "정상",
    "이상없음",
    "이상 없음",
    "특이사항 없음",
    "점검완료",
    "점검 완료",
    "이상 無",
    "정상 운전 중",
    "정상 작동 확인",
    "운전 상태 양호",
    "계기판 정상",
}

_WEAK_RE = re.compile("|".join(map(re.escape, WEAK_MODIFIERS)))
_STRONG_RE = re.compile("|".join(map(re.escape, STRONG_MODIFIERS)))
_GROUP_RE = {g: re.compile("|".join(map(re.escape, kws))) for g, kws in SYMPTOM_GROUPS.items()}


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"\s+", "", s)
    return {s[i : i + 2] for i in range(len(s) - 1)} if len(s) > 1 else {s}


def memo_features(memo: pd.Series) -> pd.DataFrame:
    """메모 한 건당 피처. 이전 메모와의 관계(중복·참신성)는 build.py 에서 asset 별로 계산한다."""
    m = memo.fillna("").astype(str)
    out = pd.DataFrame(index=memo.index)
    out["tx_len"] = m.str.len().astype(float)
    out["tx_lazy"] = m.str.strip().isin(LAZY_MEMOS).astype(float)
    out["tx_weak_hits"] = m.apply(lambda s: float(len(_WEAK_RE.findall(s))))
    out["tx_strong_hits"] = m.apply(lambda s: float(len(_STRONG_RE.findall(s))))
    n_groups = np.zeros(len(m))
    for g, rx in _GROUP_RE.items():
        hit = m.apply(lambda s, rx=rx: 1.0 if rx.search(s) else 0.0)
        out[f"tx_g_{g}"] = hit
        n_groups += hit.to_numpy()
    out["tx_n_groups"] = n_groups
    # 약신호 점수: 증상 어근 수 × (약한 수식어가 있으면 1, 강한 수식어가 있으면 2)
    out["tx_weak_score"] = out["tx_n_groups"] * (out["tx_weak_hits"] > 0).astype(float)
    out["tx_strong_score"] = out["tx_n_groups"] * (out["tx_strong_hits"] > 0).astype(float)
    return out


def novelty(prev: pd.Series, cur: pd.Series) -> pd.Series:
    """1 − 문자 바이그램 자카드 유사도. 이전 메모가 없으면 1."""
    vals = []
    for p, c in zip(prev.fillna("").astype(str), cur.fillna("").astype(str)):
        if not p:
            vals.append(1.0)
            continue
        a, b = _bigrams(p), _bigrams(c)
        u = len(a | b)
        vals.append(1.0 - (len(a & b) / u if u else 0.0))
    return pd.Series(vals, index=cur.index, dtype=float)


GROUP_KO = {
    "noise": "소음",
    "vibration": "진동",
    "leak": "누유·누수",
    "thermal": "온도",
    "pressure": "압력",
    "electric": "전기",
    "operation": "작동",
    "wear": "마모·소모품",
    "smell_smoke": "냄새·연기",
    "corrosion": "부식·외관",
    "power_fuel": "전원·연료",
    "level_door": "수위·도어·센서",
}
SYMPTOM_KEYWORDS = sorted({kw for kws in SYMPTOM_GROUPS.values() for kw in kws}, key=lambda w: (-len(w), w))
_SYMPTOM_RE = re.compile("|".join(map(re.escape, SYMPTOM_KEYWORDS)))
_KEYWORD_GROUP: dict[str, str] = {}
for _g, _kws in SYMPTOM_GROUPS.items():
    for _kw in _kws:
        _KEYWORD_GROUP.setdefault(_kw, _g)
_KIND_PRIORITY = {"strong": 0, "weak": 1, "symptom": 2}


def lexicon() -> dict:
    """브라우저(JS) 포트가 같은 렉시콘을 쓰도록 내보낸다 — 단일 출처는 이 파일."""
    return {
        "symptom_groups": {g: {"label": GROUP_KO[g], "keywords": kws} for g, kws in SYMPTOM_GROUPS.items()},
        "symptom_keywords": SYMPTOM_KEYWORDS,
        "weak_modifiers": WEAK_MODIFIERS,
        "strong_modifiers": STRONG_MODIFIERS,
        "lazy_memos": sorted(LAZY_MEMOS),
    }


def segments(memo: str) -> list[dict]:
    """메모를 [{text, kind, group?}] 로 쪼갠다. kind: strong | weak | symptom | None.

    겹치면 시작이 빠른 것, 같으면 strong > weak > symptom, 같으면 긴 것이 이긴다 (JS 포트와 같은 규칙).
    """
    text = memo or ""
    spans: list[tuple[int, int, int, str]] = []
    for kind, rx in (("strong", _STRONG_RE), ("weak", _WEAK_RE), ("symptom", _SYMPTOM_RE)):
        for m in rx.finditer(text):
            spans.append((m.start(), m.end(), _KIND_PRIORITY[kind], kind))
    spans.sort(key=lambda t: (t[0], t[2], -(t[1] - t[0])))
    out: list[dict] = []
    pos = 0
    for start, end, _prio, kind in spans:
        if start < pos:
            continue
        if start > pos:
            out.append({"text": text[pos:start], "kind": None})
        piece = {"text": text[start:end], "kind": kind}
        if kind == "symptom":
            piece["group"] = _KEYWORD_GROUP.get(text[start:end])
        out.append(piece)
        pos = end
    if pos < len(text):
        out.append({"text": text[pos:], "kind": None})
    return out


def analyze_memo(memo: str) -> dict:
    """메모 한 건이 모델에 어떤 피처로 들어가는지 — 점수는 memo_features 와 같은 값이다."""
    text = memo or ""
    f = memo_features(pd.Series([text])).iloc[0]
    groups = [g for g, rx in _GROUP_RE.items() if rx.search(text)]
    return {
        "memo": text,
        "length": int(f["tx_len"]),
        "lazy": bool(f["tx_lazy"]),
        "n_groups": int(f["tx_n_groups"]),
        "groups": [{"id": g, "label": GROUP_KO[g]} for g in groups],
        "weak_hits": [m.group(0) for m in _WEAK_RE.finditer(text)],
        "strong_hits": [m.group(0) for m in _STRONG_RE.finditer(text)],
        "weak_score": float(f["tx_weak_score"]),
        "strong_score": float(f["tx_strong_score"]),
        "segments": segments(text),
    }


def highlight(memo: str) -> str:
    """수식어(약·강)를 [단어] 로 감싼 문자열 — 설명 응답에서 쓴다."""
    return "".join(f"[{s['text']}]" if s["kind"] in ("weak", "strong") else s["text"] for s in segments(memo))
