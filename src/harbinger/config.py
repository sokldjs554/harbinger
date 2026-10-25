"""런타임 설정과 전역 상수.

모든 경로는 환경변수 HARBINGER_* 로 바꿀 수 있다. 모델·평가에서 쓰는 상수는 여기 한 곳에만 둔다.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

HORIZON_DAYS = 30  # 분류 라벨: 이 기간 안의 비계획 고장
SURVIVAL_BIN_DAYS = 30  # 이산시간 위험 모델의 구간 폭
SURVIVAL_BINS = 12  # 12 구간 = 360일
DEFAULT_SEED = 20260101
RISK_BUDGET = 0.05  # 권고 점검 주기: 다음 점검 전 고장 확률 상한


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HARBINGER_", env_file=".env", extra="ignore", hide_input_in_errors=True
    )

    data_dir: Path = Path("data")
    model_dir: Path = Path("models")
    artifact_dir: Path = Path("artifacts")
    demo_bootstrap: bool = True
    allow_shared_ingest: bool = False
    log_level: str = "INFO"
    protected_mode: bool = False
    auth_users_file: Path | None = None
    auth_origin: str | None = None
    auth_cookie_secure: bool = True
    auth_ttl_seconds: int = Field(1800, ge=60, le=86400)
    auth_max_sessions: int = Field(256, ge=1, le=2048)
    auth_metrics_token: SecretStr | None = None

    @field_validator("auth_metrics_token", mode="before")
    @classmethod
    def metrics_token(cls, value):
        if value is None or value == "":
            return None
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(secret, str) or not 32 <= len(secret) <= 256 or not secret.isascii():
            raise ValueError("Metrics token must contain 32–256 ASCII characters")
        return value


settings = Settings()
