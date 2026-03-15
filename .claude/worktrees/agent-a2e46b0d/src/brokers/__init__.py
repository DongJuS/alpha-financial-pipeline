from __future__ import annotations

from src.brokers.kis import KISPaperApiClient, KISPaperBroker, KISRealApiClient, KISRealBroker
from src.brokers.paper import PaperBroker, PaperBrokerExecution
from src.brokers.virtual_broker import VirtualBroker, VirtualBrokerExecution
from src.utils.account_scope import normalize_account_scope
from src.utils.config import Settings, get_settings
from src.utils.logging import get_logger

logger = get_logger(__name__)


def build_paper_broker(settings: Settings | None = None):
    broker_settings = settings or get_settings()
    backend = broker_settings.paper_broker_backend.strip().lower()
    internal = PaperBroker()

    if backend == "internal":
        return internal

    if backend in {"kis", "kis_shadow"}:
        return KISPaperBroker(
            settings=broker_settings,
            execution_mode=backend,
            fallback_broker=internal,
            client=KISPaperApiClient(settings=broker_settings),
        )

    logger.warning("알 수 없는 PAPER_BROKER_BACKEND=%s, internal 브로커로 폴백합니다.", backend)
    return internal


def build_real_broker(settings: Settings | None = None):
    broker_settings = settings or get_settings()
    backend = str(getattr(broker_settings, "real_broker_backend", "kis")).strip().lower()

    if backend == "kis":
        return KISRealBroker(
            settings=broker_settings,
            execution_mode=backend,
            client=KISRealApiClient(settings=broker_settings),
        )

    logger.warning("알 수 없는 REAL_BROKER_BACKEND=%s, KIS 실거래 브로커를 사용합니다.", backend)
    return KISRealBroker(
        settings=broker_settings,
        execution_mode="kis",
        client=KISRealApiClient(settings=broker_settings),
    )


def build_virtual_broker(
    strategy_id: str | None = None,
    initial_capital: int | None = None,
) -> VirtualBroker:
    """Virtual 계좌 전용 브로커를 생성합니다."""
    return VirtualBroker(
        strategy_id=strategy_id,
        initial_capital=initial_capital,
    )


def build_broker_for_scope(
    account_scope: str,
    settings: Settings | None = None,
    strategy_id: str | None = None,
):
    scope = normalize_account_scope(account_scope)
    if scope == "real":
        return build_real_broker(settings)
    if scope == "virtual":
        return build_virtual_broker(strategy_id=strategy_id)
    return build_paper_broker(settings)


__all__ = [
    "PaperBroker",
    "PaperBrokerExecution",
    "VirtualBroker",
    "VirtualBrokerExecution",
    "KISPaperApiClient",
    "KISPaperBroker",
    "KISRealApiClient",
    "KISRealBroker",
    "build_broker_for_scope",
    "build_paper_broker",
    "build_real_broker",
    "build_virtual_broker",
]
