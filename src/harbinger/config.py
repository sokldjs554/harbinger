"""런타임 설정과 전역 상수.

모든 경로는 환경변수 HARBINGER_* 로 바꿀 수 있다. 모델·평가에서 쓰는 상수는 여기 한 곳에만 둔다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

HORIZON_DAYS = 30  # 분류 라벨: 이 기간 안의 비계획 고장
SURVIVAL_BIN_DAYS = 30  # 이산시간 위험 모델의 구간 폭
SURVIVAL_BINS = 12  # 12 구간 = 360일
DEFAULT_SEED = 20260101
RISK_BUDGET = 0.05  # 권고 점검 주기: 다음 점검 전 고장 확률 상한


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="HARBINGER_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    model_dir: Path = Path("models")
    artifact_dir: Path = Path("artifacts")
    demo_bootstrap: bool = True
    log_level: str = "INFO"


settings = Settings()
