"""
src/brokers/kis.py — KIS paper/real 브로커 및 API 클라이언트
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from uuid import uuid4

import httpx

from src.brokers.paper import PaperBroker, PaperBrokerExecution
from src.db.models import PaperOrderRequest
from src.db.queries import (
    attach_broker_order_reference,
    get_trading_account,
    insert_broker_order,
    update_broker_order_status,
    upsert_trading_account,
)
from src.services.kis_session import ensure_kis_token
from src.utils.account_scope import AccountScope, normalize_account_scope
from src.utils.config import (
    Settings,
    get_settings,
    kis_account_number_for_scope,
    kis_app_key_for_scope,
    kis_app_secret_for_scope,
)
from src.utils.logging import get_logger

logger = get_logger(__name__)

ORDER_TR_IDS: dict[str, dict[str, str]] = {
    "paper": {
        "BUY": "VTTC0802U",
        "SELL": "VTTC0801U",
        "BALANCE": "VTTC8434R",
        "DAILY_CCLD": "VTTC0081R",
    },
    "real": {
        "BUY": "TTTC0802U",
        "SELL": "TTTC0801U",
        "BALANCE": "TTTC8434R",
        "DAILY_CCLD": "TTTC0081R",
    },
}


class KISAPIError(RuntimeError):
    """KIS API 호출 또는 응답 파싱 오류."""


@dataclass
class KISOrderReceipt:
    order_no: str
    raw: dict


class KISApiClient:
    def __init__(
        self,
        *,
        account_scope: AccountScope,
        settings: Settings | None = None,
        token_provider=ensure_kis_token,
    ) -> None:
        self.account_scope = normalize_account_scope(account_scope)
        self.settings = settings or get_settings()
        self._token_provider = token_provider

    def is_configured(self) -> bool:
        return bool(
            kis_app_key_for_scope(self.settings, self.account_scope)
            and kis_app_secret_for_scope(self.settings, self.account_scope)
            and kis_account_number_for_scope(self.settings, self.account_scope)
        )

    def _account_parts(self) -> tuple[str, str]:
        account_number = kis_account_number_for_scope(self.settings, self.account_scope)
        digits = "".join(ch for ch in account_number if ch.isdigit())
        if len(digits) < 10:
            raise KISAPIError("KIS_ACCOUNT_NUMBER 형식이 올바르지 않습니다. 예: 50012345-01")
        return digits[:-2], digits[-2:]

    async def _resolve_token(self) -> str:
        try:
            token = await self._token_provider(self.account_scope)
        except TypeError:
            token = await self._token_provider()
        if not token:
            raise KISAPIError(
                "KIS 토큰이 없습니다. `python scripts/kis_auth.py --scope "
                f"{self.account_scope}`를 실행하거나 자동 발급이 가능한지 확인하세요."
            )
        return str(token)

    async def _base_headers(self, tr_id: str) -> dict[str, str]:
        token = await self._resolve_token()
        return {
            "authorization": f"Bearer {token}",
            "appkey": kis_app_key_for_scope(self.settings, self.account_scope),
            "appsecret": kis_app_secret_for_scope(self.settings, self.account_scope),
            "tr_id": tr_id,
            "custtype": "P",
            "content-type": "application/json; charset=utf-8",
        }

    async def _create_hashkey(self, payload: dict, tr_id: str) -> str:
        headers = await self._base_headers(tr_id)
        url = f"{self.settings.kis_base_url_for_scope(self.account_scope)}/uapi/hashkey"
        async with httpx.AsyncClient(timeout=self.settings.kis_request_timeout_seconds) as client:
            response = await client.post(url, headers=headers, content=json.dumps(payload))
            response.raise_for_status()
            data = response.json()

        hashkey = data.get("HASH") or data.get("hash")
        if not hashkey:
            raise KISAPIError("KIS hashkey 발급에 실패했습니다.")
        return str(hashkey)

    async def _request_json(
        self,
        method: str,
        path: str,
        tr_id: str,
        *,
        params: dict | None = None,
        json_body: dict | None = None,
        use_hashkey: bool = False,
    ) -> dict:
        headers = await self._base_headers(tr_id)
        if use_hashkey and json_body is not None:
            headers["hashkey"] = await self._create_hashkey(json_body, tr_id)

        url = f"{self.settings.kis_base_url_for_scope(self.account_scope)}{path}"
        async with httpx.AsyncClient(timeout=self.settings.kis_request_timeout_seconds) as client:
            response = await client.request(method, url, headers=headers, params=params, json=json_body)
            response.raise_for_status()
            data = response.json()

        if data.get("rt_cd") not in {None, "0"}:
            raise KISAPIError(data.get("msg1", "KIS API 호출 실패"))
        return data

    def _tr_id(self, key: str) -> str:
        return ORDER_TR_IDS[self.account_scope][key]

    async def place_order(self, order: PaperOrderRequest) -> KISOrderReceipt:
        if not self.is_configured():
            raise KISAPIError(f"KIS {self.account_scope} 주문 API 설정이 비어 있습니다.")

        cano, account_product = self._account_parts()
        tr_id = self._tr_id("BUY" if order.signal == "BUY" else "SELL")
        payload = {
            "CANO": cano,
            "ACNT_PRDT_CD": account_product,
            "PDNO": order.ticker,
            "ORD_DVSN": "01",
            "ORD_QTY": str(order.quantity),
            "ORD_UNPR": "0",
            "EXCG_ID_DVSN_CD": "KRX",
            "SLL_TYPE": "",
            "CNDT_PRIC": "",
        }

        data = await self._request_json(
            "POST",
            "/uapi/domestic-stock/v1/trading/order-cash",
            tr_id,
            json_body=payload,
            use_hashkey=True,
        )
        output = data.get("output") or {}
        order_no = str(output.get("ODNO") or output.get("odno") or "")
        return KISOrderReceipt(order_no=order_no, raw=data)

    async def inquire_balance(self) -> dict:
        cano, account_product = self._account_parts()
        data = await self._request_json(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-balance",
            self._tr_id("BALANCE"),
            params={
                "CANO": cano,
                "ACNT_PRDT_CD": account_product,
                "AFHR_FLPR_YN": "N",
                "OFL_YN": "",
                "INQR_DVSN": "02",
                "UNPR_DVSN": "01",
                "FUND_STTL_ICLD_YN": "N",
                "FNCG_AMT_AUTO_RDPT_YN": "N",
                "PRCS_DVSN": "01",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
            },
        )
        return {
            "positions": data.get("output1") or [],
            "summary": (data.get("output2") or [{}])[0],
        }

    async def inquire_daily_ccld(
        self,
        *,
        start_date: date,
        end_date: date,
        ticker: str = "",
        fill_type: str = "00",
    ) -> dict:
        cano, account_product = self._account_parts()
        data = await self._request_json(
            "GET",
            "/uapi/domestic-stock/v1/trading/inquire-daily-ccld",
            self._tr_id("DAILY_CCLD"),
            params={
                "CANO": cano,
                "ACNT_PRDT_CD": account_product,
                "INQR_STRT_DT": start_date.strftime("%Y%m%d"),
                "INQR_END_DT": end_date.strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",
                "PDNO": ticker,
                "CCLD_DVSN": fill_type,
                "INQR_DVSN": "00",
                "INQR_DVSN_3": "00",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
                "EXCG_ID_DVSN_CD": "KRX",
            },
        )
        return {
            "orders": data.get("output1") or [],
            "summary": data.get("output2") or {},
        }


class KISPaperApiClient(KISApiClient):
    def __init__(self, *, settings: Settings | None = None, token_provider=ensure_kis_token) -> None:
        super().__init__(account_scope="paper", settings=settings, token_provider=token_provider)


class KISRealApiClient(KISApiClient):
    def __init__(self, *, settings: Settings | None = None, token_provider=ensure_kis_token) -> None:
        super().__init__(account_scope="real", settings=settings, token_provider=token_provider)


class KISBroker:
    def __init__(
        self,
        *,
        account_scope: AccountScope,
        settings: Settings | None = None,
        execution_mode: str = "kis",
        fallback_broker: PaperBroker | None = None,
        client: KISApiClient | None = None,
    ) -> None:
        self.account_scope = normalize_account_scope(account_scope)
        self.settings = settings or get_settings()
        self.execution_mode = execution_mode
        self.fallback_broker = fallback_broker
        self.client = client or KISApiClient(account_scope=self.account_scope, settings=self.settings)

    async def execute_order(self, order: PaperOrderRequest) -> PaperBrokerExecution:
        scope = normalize_account_scope(order.account_scope)
        if scope != self.account_scope:
            if self.fallback_broker is not None:
                return await self.fallback_broker.execute_order(order)
            return await self._reject_without_order(order, f"{self.account_scope} 브로커에 다른 scope 주문이 전달되었습니다.")

        if self.account_scope == "paper" and self.execution_mode == "kis_shadow":
            if self.fallback_broker is None:
                return await self._reject_without_order(order, "kis_shadow 모드는 paper fallback broker가 필요합니다.")
            return await self._execute_shadow_order(order)

        if self.execution_mode != "kis":
            if self.fallback_broker is not None:
                return await self.fallback_broker.execute_order(order)
            return await self._reject_without_order(order, f"{self.account_scope} 브로커 실행 모드가 지원되지 않습니다: {self.execution_mode}")

        if not self.client.is_configured():
            if self.account_scope == "paper" and self.fallback_broker is not None:
                logger.warning("KIS paper broker 설정이 없어 internal paper broker로 폴백합니다.")
                return await self.fallback_broker.execute_order(order)
            return await self._reject_without_order(order, f"KIS {self.account_scope} 브로커 설정이 없습니다.")

        return await self._execute_kis_order(order, scope)

    async def _execute_shadow_order(self, order: PaperOrderRequest) -> PaperBrokerExecution:
        assert self.fallback_broker is not None
        execution = await self.fallback_broker.execute_order(order)
        if execution.status == "REJECTED":
            return execution

        try:
            receipt = await self.client.place_order(order)
            if receipt.order_no:
                await attach_broker_order_reference(
                    execution.client_order_id,
                    broker_name="internal-paper+kis-shadow",
                    broker_order_id=receipt.order_no,
                )
        except KISAPIError as exc:
            logger.warning("KIS shadow 주문 기록 실패: %s", exc)

        return execution

    async def _execute_kis_order(
        self,
        order: PaperOrderRequest,
        scope: AccountScope,
    ) -> PaperBrokerExecution:
        client_order_id = f"kis-{uuid4().hex[:16]}"
        strategy_id = getattr(order, "strategy_id", None)
        await self._ensure_account(scope)
        account = await get_trading_account(scope)
        cash_balance = int(account["cash_balance"]) if account else 0
        total_equity = int(account["total_equity"]) if account else 0

        await insert_broker_order(
            client_order_id=client_order_id,
            account_scope=scope,
            broker_name="한국투자증권 KIS",
            ticker=order.ticker,
            name=order.name,
            side=order.signal,
            requested_quantity=order.quantity,
            requested_price=order.price,
            signal_source=order.signal_source,
            agent_id=order.agent_id,
            status="PENDING",
            strategy_id=strategy_id,
        )

        try:
            receipt = await self.client.place_order(order)
        except KISAPIError as exc:
            await update_broker_order_status(
                client_order_id=client_order_id,
                status="REJECTED",
                rejection_reason=str(exc),
            )
            return PaperBrokerExecution(
                client_order_id=client_order_id,
                account_scope=scope,
                status="REJECTED",
                ticker=order.ticker,
                side=order.signal,
                quantity=order.quantity,
                price=order.price,
                cash_balance=cash_balance,
                total_equity=total_equity,
                rejection_reason=str(exc),
            )

        await update_broker_order_status(
            client_order_id=client_order_id,
            status="PENDING",
            broker_order_id=receipt.order_no or None,
        )
        return PaperBrokerExecution(
            client_order_id=client_order_id,
            account_scope=scope,
            status="PENDING",
            ticker=order.ticker,
            side=order.signal,
            quantity=order.quantity,
            price=order.price,
            cash_balance=cash_balance,
            total_equity=total_equity,
        )

    async def _ensure_account(self, scope: AccountScope) -> None:
        account = await get_trading_account(scope)
        if account:
            return
        await upsert_trading_account(
            account_scope=scope,
            broker_name="한국투자증권 KIS",
            account_label="KIS 모의투자 계좌" if scope == "paper" else "KIS 실거래 계좌",
            seed_capital=10_000_000 if scope == "paper" else 0,
            cash_balance=10_000_000 if scope == "paper" else 0,
            buying_power=10_000_000 if scope == "paper" else 0,
            total_equity=10_000_000 if scope == "paper" else 0,
            is_active=True,
        )

    async def _reject_without_order(
        self,
        order: PaperOrderRequest,
        reason: str,
    ) -> PaperBrokerExecution:
        await self._ensure_account(self.account_scope)
        account = await get_trading_account(self.account_scope)
        return PaperBrokerExecution(
            client_order_id=f"rejected-{uuid4().hex[:12]}",
            account_scope=self.account_scope,
            status="REJECTED",
            ticker=order.ticker,
            side=order.signal,
            quantity=order.quantity,
            price=order.price,
            cash_balance=int(account["cash_balance"]) if account else 0,
            total_equity=int(account["total_equity"]) if account else 0,
            rejection_reason=reason,
        )


class KISPaperBroker(KISBroker):
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        execution_mode: str = "kis",
        fallback_broker: PaperBroker | None = None,
        client: KISPaperApiClient | None = None,
    ) -> None:
        paper_fallback = fallback_broker or PaperBroker()
        super().__init__(
            account_scope="paper",
            settings=settings,
            execution_mode=execution_mode,
            fallback_broker=paper_fallback,
            client=client or KISPaperApiClient(settings=settings),
        )


class KISRealBroker(KISBroker):
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        execution_mode: str = "kis",
        client: KISRealApiClient | None = None,
    ) -> None:
        super().__init__(
            account_scope="real",
            settings=settings,
            execution_mode=execution_mode,
            fallback_broker=None,
            client=client or KISRealApiClient(settings=settings),
        )
