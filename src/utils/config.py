"""
src/utils/config.py — 환경 변수 중앙 설정 관리

Pydantic v2 Settings로 모든 환경 변수를 타입-안전하게 로드합니다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: str = Field(default="development", alias="NODE_ENV")
    port: int = Field(default=8000)
    app_url: str = Field(default="http://localhost:8000")

    # ── Database ─────────────────────────────────────────────────────────────
    database_url: str = Field(..., alias="DATABASE_URL")

    # ── Redis ────────────────────────────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ── Auth (JWT) ────────────────────────────────────────────────────────────
    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_expires_in: str = Field(default="7d", alias="JWT_EXPIRES_IN")

    # ── LLM APIs ─────────────────────────────────────────────────────────────
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    anthropic_cli_command: str = Field(default="", alias="ANTHROPIC_CLI_COMMAND")
    llm_cli_timeout_seconds: int = Field(default=90, ge=5, le=600, alias="LLM_CLI_TIMEOUT_SECONDS")

    # ── KIS Developers (한국투자증권) ─────────────────────────────────────────
    kis_app_key: str = Field(default="", alias="KIS_APP_KEY")
    kis_app_secret: str = Field(default="", alias="KIS_APP_SECRET")
    kis_account_number: str = Field(default="", alias="KIS_ACCOUNT_NUMBER")
    kis_paper_app_key: str = Field(default="", alias="KIS_PAPER_APP_KEY")
    kis_paper_app_secret: str = Field(default="", alias="KIS_PAPER_APP_SECRET")
    kis_paper_account_number: str = Field(default="", alias="KIS_PAPER_ACCOUNT_NUMBER")
    kis_real_app_key: str = Field(default="", alias="KIS_REAL_APP_KEY")
    kis_real_app_secret: str = Field(default="", alias="KIS_REAL_APP_SECRET")
    kis_real_account_number: str = Field(default="", alias="KIS_REAL_ACCOUNT_NUMBER")
    kis_is_paper_trading: bool = Field(default=True, alias="KIS_IS_PAPER_TRADING")
    paper_broker_backend: str = Field(default="internal", alias="PAPER_BROKER_BACKEND")
    real_broker_backend: str = Field(default="kis", alias="REAL_BROKER_BACKEND")
    kis_request_timeout_seconds: int = Field(default=15, ge=5, le=60, alias="KIS_REQUEST_TIMEOUT_SECONDS")

    # ── Telegram ─────────────────────────────────────────────────────────────
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    # ── Strategy ─────────────────────────────────────────────────────────────
    strategy_blend_ratio: float = Field(default=0.50, alias="STRATEGY_BLEND_RATIO")
    strategy_a_rolling_days: int = Field(default=5, ge=1, le=30, alias="STRATEGY_A_ROLLING_DAYS")
    strategy_a_min_samples: int = Field(default=3, ge=1, le=50, alias="STRATEGY_A_MIN_SAMPLES")
    strategy_b_max_rounds: int = Field(default=2, ge=1, le=5, alias="STRATEGY_B_MAX_ROUNDS")
    strategy_b_consensus_threshold: float = Field(
        default=0.67,
        ge=0.0,
        le=1.0,
        alias="STRATEGY_B_CONSENSUS_THRESHOLD",
    )
    real_trading_confirmation_code: str = Field(
        default="CONFIRM_REAL_TRADING_2026",
        alias="REAL_TRADING_CONFIRMATION_CODE",
    )
    readiness_required_paper_days: int = Field(
        default=30,
        ge=1,
        le=365,
        alias="READINESS_REQUIRED_PAPER_DAYS",
    )
    readiness_audit_max_age_days: int = Field(
        default=7,
        ge=1,
        le=30,
        alias="READINESS_AUDIT_MAX_AGE_DAYS",
    )

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def kis_base_url(self) -> str:
        """페이퍼 트레이딩과 실거래 엔드포인트 자동 분기."""
        if self.kis_is_paper_trading:
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"

    def kis_base_url_for_scope(self, account_scope: str) -> str:
        if account_scope == "paper":
            return "https://openapivts.koreainvestment.com:29443"
        return "https://openapi.koreainvestment.com:9443"

    @property
    def kis_websocket_url(self) -> str:
        if self.kis_is_paper_trading:
            return "ws://ops.koreainvestment.com:31000"
        return "ws://ops.koreainvestment.com:21000"

    def kis_websocket_url_for_scope(self, account_scope: str) -> str:
        if account_scope == "paper":
            return "ws://ops.koreainvestment.com:31000"
        return "ws://ops.koreainvestment.com:21000"

    def kis_app_key_for_scope(self, account_scope: str) -> str:
        if account_scope == "real":
            return self.kis_real_app_key or self.kis_app_key
        return self.kis_paper_app_key or self.kis_app_key

    def kis_app_secret_for_scope(self, account_scope: str) -> str:
        if account_scope == "real":
            return self.kis_real_app_secret or self.kis_app_secret
        return self.kis_paper_app_secret or self.kis_app_secret

    def kis_account_number_for_scope(self, account_scope: str) -> str:
        if account_scope == "real":
            return self.kis_real_account_number or self.kis_account_number
        return self.kis_paper_account_number or self.kis_account_number


@lru_cache
def get_settings() -> Settings:
    """앱 전체에서 싱글턴으로 사용하는 설정 인스턴스를 반환합니다."""
    return Settings()


def kis_app_key_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_app_key_for_scope"):
        return settings.kis_app_key_for_scope(account_scope)  # type: ignore[attr-defined]
    if account_scope == "real":
        return getattr(settings, "kis_real_app_key", "") or getattr(settings, "kis_app_key", "")
    return getattr(settings, "kis_paper_app_key", "") or getattr(settings, "kis_app_key", "")


def kis_app_secret_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_app_secret_for_scope"):
        return settings.kis_app_secret_for_scope(account_scope)  # type: ignore[attr-defined]
    if account_scope == "real":
        return getattr(settings, "kis_real_app_secret", "") or getattr(settings, "kis_app_secret", "")
    return getattr(settings, "kis_paper_app_secret", "") or getattr(settings, "kis_app_secret", "")


def kis_account_number_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_account_number_for_scope"):
        return settings.kis_account_number_for_scope(account_scope)  # type: ignore[attr-defined]
    if account_scope == "real":
        return getattr(settings, "kis_real_account_number", "") or getattr(settings, "kis_account_number", "")
    return getattr(settings, "kis_paper_account_number", "") or getattr(settings, "kis_account_number", "")
