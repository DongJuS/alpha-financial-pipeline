"""
src/utils/config.py — 환경 변수 중앙 설정 관리

Pydantic v2 Settings로 모든 환경 변수를 타입-안전하게 로드합니다.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.utils.secret_validation import is_placeholder_secret


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = Field(default="development", alias="NODE_ENV")
    port: int = Field(default=8000)
    app_url: str = Field(default="http://localhost:8000")

    database_url: str = Field(..., alias="DATABASE_URL")

    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    jwt_secret: str = Field(..., alias="JWT_SECRET")
    jwt_expires_in: str = Field(default="7d", alias="JWT_EXPIRES_IN")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    anthropic_cli_command: str = Field(default="", alias="ANTHROPIC_CLI_COMMAND")
    llm_cli_timeout_seconds: int = Field(default=90, ge=5, le=600, alias="LLM_CLI_TIMEOUT_SECONDS")
    llm_daily_provider_limit: int = Field(default=30, ge=1, le=1000, alias="LLM_DAILY_PROVIDER_LIMIT")
    llm_usage_timezone: str = Field(default="Asia/Seoul", alias="LLM_USAGE_TIMEZONE")

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

    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")

    strategy_blend_ratio: float = Field(default=0.50, alias="STRATEGY_BLEND_RATIO")
    strategy_blend_weights: str = Field(
        default='{"A": 0.30, "B": 0.30, "RL": 0.20, "S": 0.20}',
        alias="STRATEGY_BLEND_WEIGHTS",
    )
    strategy_a_rolling_days: int = Field(default=5, ge=1, le=30, alias="STRATEGY_A_ROLLING_DAYS")
    strategy_a_min_samples: int = Field(default=3, ge=1, le=50, alias="STRATEGY_A_MIN_SAMPLES")
    strategy_b_max_rounds: int = Field(default=2, ge=1, le=5, alias="STRATEGY_B_MAX_ROUNDS")
    strategy_b_consensus_threshold: float = Field(
        default=0.67,
        ge=0.0,
        le=1.0,
        alias="STRATEGY_B_CONSENSUS_THRESHOLD",
    )
    search_max_concurrent: str = Field(default="3", alias="SEARCH_MAX_CONCURRENT")
    search_categories: str = Field(default="news", alias="SEARCH_CATEGORIES")
    search_max_sources: str = Field(default="5", alias="SEARCH_MAX_SOURCES")
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

    # ── Strategy Modes (전략별 독립 포트폴리오) ─────────────────────────────
    strategy_modes: str = Field(
        default='{"A": "paper", "B": "paper", "RL": "virtual", "S": "virtual", "L": "virtual"}',
        alias="STRATEGY_MODES",
    )
    strategy_capital_allocation: str = Field(
        default='{"A": 5000000, "B": 5000000, "RL": 10000000, "S": 10000000, "L": 10000000}',
        alias="STRATEGY_CAPITAL_ALLOCATION",
    )

    # ── Virtual Broker 시뮬레이션 설정 ────────────────────────────────────
    virtual_initial_capital: int = Field(default=10_000_000, alias="VIRTUAL_INITIAL_CAPITAL")
    virtual_slippage_bps: int = Field(default=5, ge=0, le=100, alias="VIRTUAL_SLIPPAGE_BPS")
    virtual_fill_delay_max_sec: float = Field(default=2.0, ge=0.0, le=30.0, alias="VIRTUAL_FILL_DELAY_MAX_SEC")
    virtual_partial_fill_enabled: bool = Field(default=False, alias="VIRTUAL_PARTIAL_FILL_ENABLED")

    # ── 합산 리스크 관리 ─────────────────────────────────────────────────
    max_single_stock_exposure_pct: float = Field(default=30.0, ge=1.0, le=100.0, alias="MAX_SINGLE_STOCK_EXPOSURE_PCT")
    max_strategy_overlap_count: int = Field(default=3, ge=1, le=10, alias="MAX_STRATEGY_OVERLAP_COUNT")

    # ── 전략 승격 기준 오버라이드 ──────────────────────────────────────────
    promotion_criteria_override: str = Field(default="", alias="PROMOTION_CRITERIA_OVERRIDE")

    # ── S3 / MinIO (Data Lake) ───────────────────────────────────────────────
    s3_endpoint_url: str = Field(default="", alias="S3_ENDPOINT_URL")
    s3_access_key: str = Field(default="", alias="S3_ACCESS_KEY")
    s3_secret_key: str = Field(default="", alias="S3_SECRET_KEY")
    s3_bucket_name: str = Field(default="alpha-datalake", alias="S3_BUCKET_NAME")
    s3_region: str = Field(default="us-east-1", alias="S3_REGION")

    # ── Gen Data Server (테스트용 랜덤 데이터 생성) ────────────────────────────
    gen_api_url: str = Field(default="", alias="GEN_API_URL")

    # ── Blog Auto-Posting (Google Blogger) ─────────────────────────────────
    blogger_blog_id: str = Field(default="", alias="BLOGGER_BLOG_ID")
    blogger_client_id: str = Field(default="", alias="BLOGGER_CLIENT_ID")
    blogger_client_secret: str = Field(default="", alias="BLOGGER_CLIENT_SECRET")
    blogger_refresh_token: str = Field(default="", alias="BLOGGER_REFRESH_TOKEN")

    # ── Logging ──────────────────────────────────────────────────────────────
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def kis_base_url(self) -> str:
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
    return Settings()


def kis_app_key_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_app_key_for_scope"):
        return settings.kis_app_key_for_scope(account_scope)
    if account_scope == "real":
        return getattr(settings, "kis_real_app_key", "") or getattr(settings, "kis_app_key", "")
    return getattr(settings, "kis_paper_app_key", "") or getattr(settings, "kis_app_key", "")


def kis_app_secret_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_app_secret_for_scope"):
        return settings.kis_app_secret_for_scope(account_scope)
    if account_scope == "real":
        return getattr(settings, "kis_real_app_secret", "") or getattr(settings, "kis_app_secret", "")
    return getattr(settings, "kis_paper_app_secret", "") or getattr(settings, "kis_app_secret", "")


def kis_account_number_for_scope(settings: Settings | object, account_scope: str) -> str:
    if hasattr(settings, "kis_account_number_for_scope"):
        return settings.kis_account_number_for_scope(account_scope)
    if account_scope == "real":
        return getattr(settings, "kis_real_account_number", "") or getattr(settings, "kis_account_number", "")
    return getattr(settings, "kis_paper_account_number", "") or getattr(settings, "kis_account_number", "")


def has_kis_credentials(
    settings: Settings | object,
    account_scope: str,
    *,
    require_account_number: bool = False,
) -> bool:
    app_key = kis_app_key_for_scope(settings, account_scope)
    app_secret = kis_app_secret_for_scope(settings, account_scope)
    if is_placeholder_secret(app_key) or is_placeholder_secret(app_secret):
        return False

    if require_account_number:
        account_number = kis_account_number_for_scope(settings, account_scope)
        if is_placeholder_secret(account_number):
            return False

    return True
