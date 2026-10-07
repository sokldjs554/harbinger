"""what-if 시나리오 프리셋 — 같은 설비에 "이렇게 기록하면 위험도가 어떻게 바뀌나"를 보여 주는 네 가지 전형.

A 형식적 메모(전부 양호 + '특이사항 없음') · B 전부 양호 + 약신호 메모 · C 주의 + 구체적 메모 · D 불량 + 즉시 수리 요청.
A 와 B 는 **체크리스트가 완전히 같고 메모만 다르다** — 이 프로젝트가 메모를 읽는 이유를 한 번에 보여 준다.
D 는 일부러 넣었다: 불량으로 적으면 위험이 *내려가는* 것이 이 모델이 라벨 정의(조치로 막은 고장은 양성이 아님)에서 배운 것이고,
이를 숨기면 시나리오를 골라 보여 준 셈이 된다.
메모 문장은 합성 생성기의 템플릿(synth/memos.py)을 그대로 쓴다. 즉 모델이 학습한 분포 안의 문장이다.
"""

from __future__ import annotations

from harbinger.schema import CHECK_ITEMS, AssetCategory
from harbinger.synth.memos import PHRASES

SCENARIO_META = {
    "A": ("형식적 메모", '체크리스트 전부 양호, 메모는 "특이사항 없음"'),
    "B": ("약신호 메모", '체크리스트 전부 양호, 메모에만 "약간·미세" 같은 약신호'),
    "C": ("주의 + 구체적 메모", "첫 항목 주의, 증상을 구체적으로 적음"),
    "D": ("불량 + 수리 요청", "첫 항목 불량, 즉시 수리를 요청"),
}


def preset_scenarios(category: str) -> list[dict]:
    items = CHECK_ITEMS[AssetCategory(category)]
    first, second = items[0], items[1] if len(items) > 1 else items[0]
    zero = {i: 0 for i in items}
    weak = f"{PHRASES[first][0][0]}, {PHRASES[second][0][0]}"
    scenarios = [
        ("A", dict(zero), "특이사항 없음"),
        ("B", dict(zero), weak),
        ("C", {**zero, first: 1}, PHRASES[first][1][0]),
        ("D", {**zero, first: 2}, PHRASES[first][2][0]),
    ]
    out = []
    for sid, chk, memo in scenarios:
        title, desc = SCENARIO_META[sid]
        out.append(
            {
                "id": sid,
                "name": title,
                "description": desc,
                "items": chk,
                "overall": max(chk.values()),
                "memo": memo,
                "dwell_seconds": 120,
            }
        )
    return out
