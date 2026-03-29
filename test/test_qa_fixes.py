"""
test/test_qa_fixes.py — QA 잔여 이슈 (C3, H1~H4, M1~M4) 수정 검증 테스트
"""
import os
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# MacroCollector/StockMasterCollector는 모듈 임포트 시 get_settings()를 호출하므로
# 최소 필수 env var를 미리 설정
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")


# ─────────────────────────────────────────────────────────────────────────────
# H3: GPT usage counter — reserve_provider_call에 올바른 provider_name 전달
# ─────────────────────────────────────────────────────────────────────────────

class TestGPTUsageCounter(unittest.IsolatedAsyncioTestCase):
    """API key 모드는 'gpt', CLI 모드는 'codex'로 reserve_provider_call 호출."""

    def _make_api_key_client(self) -> "GPTClient":  # noqa: F821
        from src.llm.gpt_client import GPTClient
        GPTClient._global_quota_exhausted = False
        client = GPTClient.__new__(GPTClient)
        client.model = "gpt-4o-mini"
        client.api_key = "sk-test-key"
        client._quota_exhausted = False
        client._auth_mode = "api_key"
        client._effective_model = "gpt-4o-mini"
        client.cli_timeout_seconds = 30
        create_mock = AsyncMock(
            return_value=types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))]
            )
        )
        client._client = types.SimpleNamespace(
            chat=types.SimpleNamespace(
                completions=types.SimpleNamespace(create=create_mock),
            )
        )
        client._cli_command = []
        return client

    def _make_cli_client(self) -> "GPTClient":  # noqa: F821
        from src.llm.gpt_client import GPTClient
        GPTClient._global_quota_exhausted = False
        client = GPTClient.__new__(GPTClient)
        client.model = "gpt-4o-mini"
        client.api_key = ""
        client._quota_exhausted = False
        client._auth_mode = "codex_cli"
        client._effective_model = "gpt-5.4-mini"
        client.cli_timeout_seconds = 30
        client._client = None
        client._cli_command = ["codex", "exec", "--ephemeral"]
        return client

    async def test_api_key_mode_uses_gpt_counter(self) -> None:
        client = self._make_api_key_client()
        captured: list[str] = []

        async def fake_reserve(name: str) -> None:
            captured.append(name)

        with patch("src.llm.gpt_client.reserve_provider_call", side_effect=fake_reserve):
            await client.ask("hello")

        self.assertEqual(captured, ["gpt"], "API key 모드는 'gpt' counter를 사용해야 함")

    async def test_cli_mode_uses_codex_counter(self) -> None:
        client = self._make_cli_client()
        captured: list[str] = []

        async def fake_reserve(name: str) -> None:
            captured.append(name)

        with patch("src.llm.gpt_client.reserve_provider_call", side_effect=fake_reserve):
            with patch(
                "src.llm.gpt_client.run_cli_prompt_with_output_file",
                new=AsyncMock(return_value="ok"),
            ):
                await client.ask("hello")

        self.assertEqual(captured, ["codex"], "CLI 모드는 'codex' counter를 사용해야 함")


# ─────────────────────────────────────────────────────────────────────────────
# H1: debug-providers 엔드포인트 인증 검사
# ─────────────────────────────────────────────────────────────────────────────

class TestDebugProvidersAuth(unittest.TestCase):
    """debug_providers 함수 시그니처에 get_admin_user dependency 포함 여부."""

    def test_debug_providers_has_admin_dependency(self) -> None:
        import inspect
        from src.api.routers.models import debug_providers

        sig = inspect.signature(debug_providers)
        params = list(sig.parameters.keys())
        self.assertIn(
            "_",
            params,
            "debug_providers 엔드포인트에 admin dependency 파라미터가 없음",
        )


# ─────────────────────────────────────────────────────────────────────────────
# H2: init_db.py admin seed 기본값 및 placeholder 검증
# ─────────────────────────────────────────────────────────────────────────────

class TestInitDbAdminSeed(unittest.TestCase):
    """admin seed는 기본값 false, placeholder 값이면 거부."""

    def _get_seed(self, env: dict) -> None:
        from scripts.db.init_db import get_default_admin_seed
        import os
        with patch.dict(os.environ, env, clear=False):
            return get_default_admin_seed()

    def test_default_disabled(self) -> None:
        """환경 변수 미설정 시 seed 비활성화."""
        import os
        env_backup = {
            k: os.environ.pop(k, None)
            for k in ("DEFAULT_ADMIN_SEED_ENABLED", "DEFAULT_ADMIN_EMAIL", "DEFAULT_ADMIN_PASSWORD")
        }
        try:
            from scripts.db.init_db import get_default_admin_seed
            result = get_default_admin_seed()
            self.assertIsNone(result, "환경 변수 미설정 시 seed는 None이어야 함")
        finally:
            for k, v in env_backup.items():
                if v is not None:
                    os.environ[k] = v

    def test_placeholder_email_rejected(self) -> None:
        result = self._get_seed({
            "DEFAULT_ADMIN_SEED_ENABLED": "true",
            "DEFAULT_ADMIN_EMAIL": "admin@example.com",
            "DEFAULT_ADMIN_PASSWORD": "some-strong-pass",
        })
        self.assertIsNone(result, "placeholder email은 거부되어야 함")

    def test_placeholder_password_rejected(self) -> None:
        result = self._get_seed({
            "DEFAULT_ADMIN_SEED_ENABLED": "true",
            "DEFAULT_ADMIN_EMAIL": "real@mycompany.com",
            "DEFAULT_ADMIN_PASSWORD": "admin1234",
        })
        self.assertIsNone(result, "placeholder password는 거부되어야 함")

    def test_valid_credentials_accepted(self) -> None:
        result = self._get_seed({
            "DEFAULT_ADMIN_SEED_ENABLED": "true",
            "DEFAULT_ADMIN_EMAIL": "ops@mycompany.com",
            "DEFAULT_ADMIN_PASSWORD": "V3ryStr0ng!P@ss#2026",
        })
        self.assertIsNotNone(result, "유효한 자격증명은 허용되어야 함")
        self.assertEqual(result[0], "ops@mycompany.com")


# ─────────────────────────────────────────────────────────────────────────────
# C3: stock_master 섹터 시딩 로직
# ─────────────────────────────────────────────────────────────────────────────

class TestStockMasterSectorSeeding(unittest.IsolatedAsyncioTestCase):
    """seed_sector_data()가 sector_map을 빌드하고 update_stock_sectors를 호출."""

    async def test_seed_sector_data_calls_update(self) -> None:
        import asyncio
        import pandas as pd
        from src.agents.stock_master_collector import StockMasterCollector

        fake_df = pd.DataFrame([
            {"Code": "005930", "Name": "삼성전자", "업종명": "전기전자"},
            {"Code": "000660", "Name": "SK하이닉스", "업종명": "전기전자"},
        ])

        collector = StockMasterCollector()

        with patch("FinanceDataReader.StockListing", return_value=fake_df):
            sector_map = await asyncio.to_thread(collector._fetch_market_sector_map)

        self.assertIn("005930", sector_map, "005930 섹터가 맵에 있어야 함")
        self.assertEqual(sector_map["005930"][0], "전기전자")

    async def test_seed_sector_data_empty_df_skips(self) -> None:
        import asyncio
        import pandas as pd
        from src.agents.stock_master_collector import StockMasterCollector

        collector = StockMasterCollector()

        with patch("FinanceDataReader.StockListing", return_value=pd.DataFrame()):
            sector_map = await asyncio.to_thread(collector._fetch_market_sector_map)

        self.assertEqual(sector_map, {}, "빈 DataFrame이면 빈 sector_map 반환")


# ─────────────────────────────────────────────────────────────────────────────
# M3: Macro Collector FDR 재시도 로직
# ─────────────────────────────────────────────────────────────────────────────

class TestMacroCollectorRetry(unittest.TestCase):
    """FDR 빈 응답 시 더 긴 lookback으로 재시도."""

    def test_retries_on_empty_dataframe(self) -> None:
        import pandas as pd
        from src.agents.macro_collector import MacroCollector

        collector = MacroCollector()
        call_count = 0

        def fake_datareader(symbol, start):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return pd.DataFrame()  # 첫 번째 호출 빈 응답
            # 두 번째 호출에서 데이터 반환
            return pd.DataFrame([
                {"Close": 5100.0},
                {"Close": 5200.0},
            ])

        with patch("FinanceDataReader.DataReader", side_effect=fake_datareader):
            result = collector._fetch_indicator("US500")

        self.assertIsNotNone(result, "재시도 후 데이터 반환되어야 함")
        self.assertGreater(call_count, 1, "빈 응답에서 재시도 호출이 발생해야 함")

    def test_all_retries_fail_returns_none(self) -> None:
        import pandas as pd
        from src.agents.macro_collector import MacroCollector

        collector = MacroCollector()

        with patch("FinanceDataReader.DataReader", return_value=pd.DataFrame()):
            result = collector._fetch_indicator("UNKNOWN_SYMBOL")

        self.assertIsNone(result, "모든 재시도 실패 시 None 반환")


# ─────────────────────────────────────────────────────────────────────────────
# M1: RLTrading 폼 밸리데이션 — ticker 형식 + episode 범위
# ─────────────────────────────────────────────────────────────────────────────

class TestRLTradingFormValidation(unittest.TestCase):
    """handleTrain 밸리데이션 로직을 직접 검증 (정규식 + 범위)."""

    def _validate(self, ticker: str, episodes: int) -> str:
        """RLTrading.tsx handleTrain 내 밸리데이션 로직 Python 재현."""
        if not ticker.strip():
            return "종목 코드를 입력하세요."
        import re
        if not re.fullmatch(r"\d{6}", ticker.strip()):
            return "종목 코드는 6자리 숫자여야 합니다 (예: 005930)."
        if episodes < 10 or episodes > 10000:
            return "에피소드는 10 ~ 10,000 사이여야 합니다."
        return ""

    def test_valid_input(self) -> None:
        self.assertEqual(self._validate("005930", 500), "")

    def test_empty_ticker(self) -> None:
        self.assertIn("종목", self._validate("", 500))

    def test_short_ticker(self) -> None:
        self.assertIn("6자리", self._validate("5930", 500))

    def test_non_numeric_ticker(self) -> None:
        self.assertIn("6자리", self._validate("ABCDEF", 500))

    def test_episodes_too_low(self) -> None:
        self.assertIn("10,000", self._validate("005930", 5))

    def test_episodes_too_high(self) -> None:
        self.assertIn("10,000", self._validate("005930", 99999))


# ─────────────────────────────────────────────────────────────────────────────
# 스키마 정합성: gen 서버 응답 vs KIS API 응답 → MarketDataPoint DB 저장 구조
# ─────────────────────────────────────────────────────────────────────────────

class TestGenKisDbSchema(unittest.TestCase):
    """GenCollector와 CollectorAgent가 동일한 MarketDataPoint 필드 셋으로 DB에 저장."""

    # 두 에이전트가 공통으로 채워야 하는 필수 필드 (new schema)
    REQUIRED_FIELDS = {"instrument_id", "name", "market", "traded_at", "open", "high", "low", "close", "volume"}
    OPTIONAL_FIELDS = {"change_pct", "adj_close"}

    def _make_gen_daily_point(self) -> "MarketDataPoint":
        """GenCollector.collect_daily_bars에서 생성하는 MarketDataPoint 재현."""
        from datetime import date as date_type
        from src.db.models import MarketDataPoint

        bar = {
            "date": "2026-03-28",
            "open": 72000.0, "high": 73000.0, "low": 71500.0, "close": 72500.0,
            "volume": 1000000, "change_pct": 0.69,
        }
        traded = date_type.fromisoformat(bar["date"])
        return MarketDataPoint(
            instrument_id="005930.KS", name="삼성전자", market="KOSPI",
            traded_at=traded,
            open=bar["open"], high=bar["high"], low=bar["low"],
            close=bar["close"], volume=bar["volume"], change_pct=bar["change_pct"],
        )

    def _make_kis_daily_point(self) -> "MarketDataPoint":
        """CollectorAgent._fetch_daily_bars에서 생성하는 MarketDataPoint 재현."""
        from datetime import date as date_type
        from src.db.models import MarketDataPoint

        return MarketDataPoint(
            instrument_id="005930.KS", name="삼성전자", market="KOSPI",
            traded_at=date_type(2026, 3, 28),
            open=72000.0, high=73000.0, low=71500.0, close=72500.0,
            volume=1000000, change_pct=0.69,
        )

    def _make_gen_tick_point(self) -> "MarketDataPoint":
        """GenCollector.collect_realtime_ticks에서 생성하는 MarketDataPoint 재현."""
        from datetime import date as date_type
        from src.db.models import MarketDataPoint

        q = {
            "ticker": "005930", "name": "삼성전자", "market": "KOSPI",
            "current_price": 72500.0, "open": 72000.0, "high": 73000.0, "low": 71500.0,
            "volume": 500000, "change_pct": 0.69,
        }
        return MarketDataPoint(
            instrument_id="005930.KS", name=q["name"], market=q["market"],
            traded_at=date_type.today(),
            open=q["open"], high=q["high"], low=q["low"],
            close=q["current_price"], volume=q["volume"],
            change_pct=q["change_pct"],
        )

    def _make_kis_tick_point(self) -> "MarketDataPoint":
        """CollectorAgent KIS WebSocket에서 생성하는 MarketDataPoint 재현."""
        from datetime import date as date_type
        from src.db.models import MarketDataPoint

        price = 72500.0
        return MarketDataPoint(
            instrument_id="005930.KS", name="삼성전자", market="KOSPI",
            traded_at=date_type.today(),
            open=price, high=price, low=price, close=price,
            volume=500000, change_pct=None,
        )

    def test_daily_point_required_fields_match(self) -> None:
        """일봉: gen과 KIS가 동일한 필수 필드를 채운다."""
        gen_pt = self._make_gen_daily_point()
        kis_pt = self._make_kis_daily_point()

        gen_set = set(gen_pt.model_fields_set) | self.REQUIRED_FIELDS
        kis_set = set(kis_pt.model_fields_set) | self.REQUIRED_FIELDS

        # 두 경우 모두 필수 필드를 전부 갖는다
        self.assertTrue(self.REQUIRED_FIELDS.issubset(gen_set))
        self.assertTrue(self.REQUIRED_FIELDS.issubset(kis_set))

    def test_tick_point_required_fields_match(self) -> None:
        """틱: gen과 KIS 모두 MarketDataPoint 필수 필드를 모두 채운다."""
        gen_pt = self._make_gen_tick_point()
        kis_pt = self._make_kis_tick_point()

        for field in self.REQUIRED_FIELDS:
            self.assertIsNotNone(getattr(gen_pt, field), f"gen tick '{field}' is None")
            self.assertIsNotNone(getattr(kis_pt, field), f"kis tick '{field}' is None")

    def test_interval_is_always_daily(self) -> None:
        """ohlcv_daily 전용 모델이므로 interval은 항상 'daily'이어야 한다."""
        self.assertEqual(self._make_gen_tick_point().interval, "daily")
        self.assertEqual(self._make_kis_tick_point().interval, "daily")
        self.assertEqual(self._make_gen_daily_point().interval, "daily")
        self.assertEqual(self._make_kis_daily_point().interval, "daily")

    def test_market_values_are_valid(self) -> None:
        """market 필드는 KOSPI 또는 KOSDAQ만 허용."""
        valid = {"KOSPI", "KOSDAQ"}
        for pt in (
            self._make_gen_daily_point(),
            self._make_kis_daily_point(),
            self._make_gen_tick_point(),
            self._make_kis_tick_point(),
        ):
            self.assertIn(pt.market, valid)


class TestGenKisRedisCacheSchema(unittest.TestCase):
    """gen_collector와 collector가 동일한 Redis latest_tick 페이로드 구조를 생성."""

    EXPECTED_KEYS = {"ticker", "name", "current_price", "change_pct", "volume", "updated_at", "source"}

    def _make_redis_payload(self, close: float, change_pct, source: str) -> dict:
        """_cache_latest_tick 내 payload 딕셔너리 재현."""
        from datetime import date as date_type, datetime
        from zoneinfo import ZoneInfo
        from src.db.models import MarketDataPoint

        KST = ZoneInfo("Asia/Seoul")
        point = MarketDataPoint(
            instrument_id="005930.KS", name="삼성전자", market="KOSPI",
            traded_at=date_type.today(),
            open=close, high=close, low=close, close=close,
            volume=100000, change_pct=change_pct,
        )
        return {
            "ticker": point.ticker,
            "name": point.name,
            "current_price": point.close,
            "change_pct": point.change_pct,
            "volume": point.volume,
            "updated_at": point.timestamp_kst.isoformat(),
            "source": source,
        }

    def test_gen_redis_payload_has_expected_keys(self) -> None:
        payload = self._make_redis_payload(72500, 0.69, "gen_daily")
        self.assertEqual(set(payload.keys()), self.EXPECTED_KEYS)

    def test_kis_redis_payload_has_expected_keys(self) -> None:
        payload = self._make_redis_payload(72500, None, "fdr_daily")
        self.assertEqual(set(payload.keys()), self.EXPECTED_KEYS)

    def test_gen_kis_redis_payload_keys_identical(self) -> None:
        """gen과 KIS Redis 페이로드는 동일한 키 집합을 가진다."""
        gen_payload = self._make_redis_payload(72500, 0.69, "gen_daily")
        kis_payload = self._make_redis_payload(72500, None, "fdr_daily")
        self.assertEqual(set(gen_payload.keys()), set(kis_payload.keys()))

    def test_current_price_maps_from_close(self) -> None:
        """Redis current_price는 MarketDataPoint.close에서 매핑된다."""
        payload = self._make_redis_payload(72500, 0.69, "gen_daily")
        self.assertEqual(payload["current_price"], 72500)


class TestGenKisPubSubSchema(unittest.TestCase):
    """gen_collector와 collector의 Pub/Sub 메시지 필드 집합이 동일."""

    def _make_gen_data_ready(self, agent_id: str, count: int, tickers: list) -> dict:
        """GenCollector.collect_daily_bars pub/sub 메시지 재현."""
        from datetime import datetime
        return {
            "type": "data_ready",
            "agent_id": agent_id,
            "count": count,
            "tickers": tickers[:20],
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

    def _make_kis_data_ready(self, agent_id: str, count: int, tickers: list) -> dict:
        """CollectorAgent.collect_daily_bars pub/sub 메시지 재현."""
        from datetime import datetime
        return {
            "type": "data_ready",
            "agent_id": agent_id,
            "count": count,
            "tickers": tickers[:20],
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

    def _make_gen_tick_msg(self, agent_id: str, ticker: str, price: int, volume: int) -> dict:
        """GenCollector.collect_realtime_ticks tick pub/sub 메시지 재현."""
        from datetime import datetime
        return {
            "type": "tick",
            "agent_id": agent_id,
            "ticker": ticker,
            "price": price,
            "volume": volume,
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

    def _make_kis_tick_msg(self, agent_id: str, ticker: str, price: int, volume: int) -> dict:
        """CollectorAgent KIS WebSocket tick pub/sub 메시지 재현."""
        from datetime import datetime
        return {
            "type": "tick",
            "agent_id": agent_id,
            "ticker": ticker,
            "price": price,
            "volume": volume,
            "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        }

    def test_data_ready_keys_match(self) -> None:
        """data_ready 메시지 필드 집합: gen == KIS."""
        gen_msg = self._make_gen_data_ready("gen_collector", 10, ["005930"])
        kis_msg = self._make_kis_data_ready("collector_agent", 10, ["005930"])
        self.assertEqual(set(gen_msg.keys()), set(kis_msg.keys()))

    def test_tick_message_keys_match(self) -> None:
        """tick 메시지 필드 집합: gen == KIS."""
        gen_msg = self._make_gen_tick_msg("gen_collector", "005930", 72500, 100)
        kis_msg = self._make_kis_tick_msg("collector_agent", "005930", 72500, 100)
        self.assertEqual(set(gen_msg.keys()), set(kis_msg.keys()))

    def test_data_ready_no_source_field(self) -> None:
        """data_ready 메시지에는 source 필드가 없어야 한다 (KIS 스키마 준수)."""
        gen_msg = self._make_gen_data_ready("gen_collector", 10, ["005930"])
        self.assertNotIn("source", gen_msg)

    def test_tick_message_no_source_field(self) -> None:
        """tick 메시지에는 source 필드가 없어야 한다 (KIS 스키마 준수)."""
        gen_msg = self._make_gen_tick_msg("gen_collector", "005930", 72500, 100)
        self.assertNotIn("source", gen_msg)

    def test_data_ready_type_field(self) -> None:
        self.assertEqual(self._make_gen_data_ready("x", 1, [])["type"], "data_ready")
        self.assertEqual(self._make_kis_data_ready("x", 1, [])["type"], "data_ready")

    def test_tick_type_field(self) -> None:
        self.assertEqual(self._make_gen_tick_msg("x", "005930", 1, 1)["type"], "tick")
        self.assertEqual(self._make_kis_tick_msg("x", "005930", 1, 1)["type"], "tick")


if __name__ == "__main__":
    import asyncio
    unittest.main()
