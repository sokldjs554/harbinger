from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from harbinger.features.text import analyze_memo, lexicon

router = APIRouter(prefix="/v1/text", tags=["text"])


class MemoIn(BaseModel):
    memo: str = Field("", max_length=500, description="점검 메모 원문")


@router.post("/analyze")
def analyze(body: MemoIn) -> dict:
    """메모 한 건이 모델에 어떤 피처(증상군 수·약신호·강신호·형식적 여부)로 들어가는지 — 학습에 쓴 것과 같은 코드."""
    return analyze_memo(body.memo)


@router.get("/lexicon")
def get_lexicon() -> dict:
    """증상군 키워드·약/강 수식어·형식적 메모 목록. 브라우저 포트(console/memo.js)가 같은 렉시콘을 쓴다."""
    return lexicon()
