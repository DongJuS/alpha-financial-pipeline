"""
test/test_marketplace_week1.py — 마켓플레이스 Week 1 데이터 기반 테스트

종목 마스터, 매크로 지표, 랭킹, 관심종목, 테마 로직 단위 테스트.
"""

import unittest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from src.db.models import (
    DailyRanking,
    MacroIndicator,
    StockMasterRecord,
    WatchlistItem,
)
from src.data.themes import INITIAL_THEMES


class TestStockMasterRecord(unittest.TestCase):
    """StockMasterRecord Pydantic 모델 테스트."""

    def test_basic_creation(self):
        record = StockMasterRecord(
            ticker="005930",
            name="삼성전자",
            market="KOSPI",
            sector="반도체",
            market_cap=500_000_000_000_000,
        )
        self.assertEqual(record.ticker, "005930")
        self.assertEqual(record.market, "KOSPI")
        self.assertFalse(record.is_etf)
        self.assertEqual(record.tier, "universe")

    def test_etf_creation(self):
        record = StockMasterRecord(
            ticker="069500",
            name="KODEX 200",
            market="KOSPI",
            is_etf=True,
            sector="ETF",
        )
        self.assertTrue(record.is_etf)

    def test_market_validation(self):
        """유효하지 않은 market 값은 에러를 발생시켜야 합니다."""
        with self.assertRaises(Exception):
            StockMasterRecord(
                ticker="000001",
                name="테스트",
                market="NYSE",  # 유효하지 않은 시장
            )

    def test_tier_validation(self):
        for tier in ["core", "extended", "universe"]:
            record = StockMasterRecord(
                ticker="005930", name="삼성전자", market="KOSPI", tier=tier
            )
            self.assertEqual(record.tier, tier)

    def test_optional_fields_default_none(self):
        record = StockMasterRecord(ticker="005930", name="삼성전자", market="KOSPI")
        self.assertIsNone(record.sector)
        self.assertIsNone(record.industry)
        self.assertIsNone(record.market_cap)
        self.assertIsNone(record.listing_date)


class TestMacroIndicator(unittest.TestCase):
    """MacroIndicator Pydantic 모델 테스트."""

    def test_index_creation(self):
        ind = MacroIndicator(
            category="index",
            symbol="US500",
            name="S&P 500",
            value=5200.50,
            change_pct=0.35,
            snapshot_date=date(2026, 3, 15),
        )
        self.assertEqual(ind.category, "index")
        self.assertEqual(ind.source, "fdr")

    def test_currency_creation(self):
        ind = MacroIndicator(
            category="currency",
            symbol="USD/KRW",
            name="달러/원",
            value=1350.20,
            change_pct=-0.12,
            previous_close=1351.82,
            snapshot_date=date(2026, 3, 15),
        )
        self.assertAlmostEqual(ind.previous_close, 1351.82)

    def test_category_validation(self):
        with self.assertRaises(Exception):
            MacroIndicator(
                category="crypto",  # 유효하지 않은 카테고리
                symbol="BTC",
                name="Bitcoin",
                value=50000,
                snapshot_date=date(2026, 3, 15),
            )

    def test_commodity_creation(self):
        ind = MacroIndicator(
            category="commodity",
            symbol="GC=F",
            name="Gold",
            value=2350.10,
            snapshot_date=date(2026, 3, 15),
            source="fdr",
        )
        self.assertEqual(ind.symbol, "GC=F")


class TestDailyRanking(unittest.TestCase):
    """DailyRanking Pydantic 모델 테스트."""

    def test_market_cap_ranking(self):
        ranking = DailyRanking(
            ranking_date=date(2026, 3, 15),
            ranking_type="market_cap",
            rank=1,
            ticker="005930",
            name="삼성전자",
            value=500_000_000_000_000,
        )
        self.assertEqual(ranking.rank, 1)
        self.assertEqual(ranking.ranking_type, "market_cap")

    def test_gainer_ranking(self):
        ranking = DailyRanking(
            ranking_date=date(2026, 3, 15),
            ranking_type="gainer",
            rank=1,
            ticker="000660",
            name="SK하이닉스",
            change_pct=15.5,
        )
        self.assertAlmostEqual(ranking.change_pct, 15.5)

    def test_rank_must_be_positive(self):
        with self.assertRaises(Exception):
            DailyRanking(
                ranking_date=date(2026, 3, 15),
                ranking_type="volume",
                rank=0,  # 0 이하는 불가
                ticker="005930",
                name="삼성전자",
            )

    def test_invalid_ranking_type(self):
        with self.assertRaises(Exception):
            DailyRanking(
                ranking_date=date(2026, 3, 15),
                ranking_type="invalid_type",
                rank=1,
                ticker="005930",
                name="삼성전자",
            )

    def test_extra_jsonb(self):
        ranking = DailyRanking(
            ranking_date=date(2026, 3, 15),
            ranking_type="volume",
            rank=1,
            ticker="005930",
            name="삼성전자",
            extra={"volume": 1000000, "turnover": 5000000000},
        )
        self.assertIn("volume", ranking.extra)


class TestWatchlistItem(unittest.TestCase):
    """WatchlistItem Pydantic 모델 테스트."""

    def test_basic_creation(self):
        item = WatchlistItem(
            user_id="test-user-id",
            ticker="005930",
            name="삼성전자",
        )
        self.assertEqual(item.group_name, "default")
        self.assertIsNone(item.price_alert_above)

    def test_custom_group(self):
        item = WatchlistItem(
            user_id="test-user-id",
            group_name="관심섹터",
            ticker="005930",
            name="삼성전자",
            price_alert_above=80000,
            price_alert_below=60000,
        )
        self.assertEqual(item.group_name, "관심섹터")
        self.assertEqual(item.price_alert_above, 80000)


class TestThemeData(unittest.TestCase):
    """초기 테마 데이터 검증."""

    def test_theme_count(self):
        """30개 테마가 정의되어 있어야 합니다."""
        self.assertEqual(len(INITIAL_THEMES), 30)

    def test_all_themes_have_required_fields(self):
        """모든 테마에 name과 stocks가 있어야 합니다."""
        for slug, data in INITIAL_THEMES.items():
            self.assertIn("name", data, f"테마 '{slug}'에 name이 없습니다.")
            self.assertIn("stocks", data, f"테마 '{slug}'에 stocks가 없습니다.")
            self.assertIsInstance(data["stocks"], list)
            self.assertGreater(len(data["stocks"]), 0, f"테마 '{slug}'에 종목이 없습니다.")

    def test_theme_slugs_are_valid(self):
        """테마 slug는 영문 소문자, 숫자, 하이픈만 허용합니다."""
        import re
        pattern = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
        for slug in INITIAL_THEMES.keys():
            self.assertTrue(
                pattern.match(slug),
                f"테마 slug '{slug}'이(가) 규칙에 맞지 않습니다.",
            )

    def test_key_themes_present(self):
        """핵심 테마가 포함되어 있어야 합니다."""
        key_themes = {"ai", "semiconductor", "secondary-battery", "bio", "defense", "ev", "fintech"}
        for theme in key_themes:
            self.assertIn(theme, INITIAL_THEMES, f"핵심 테마 '{theme}'가 누락되었습니다.")

    def test_ticker_format(self):
        """모든 티커는 6자리 숫자여야 합니다."""
        import re
        pattern = re.compile(r"^\d{6}$")
        for slug, data in INITIAL_THEMES.items():
            for ticker in data["stocks"]:
                self.assertTrue(
                    pattern.match(ticker),
                    f"테마 '{slug}'의 티커 '{ticker}'가 6자리 숫자가 아닙니다.",
                )


class TestRedisKeyPatterns(unittest.TestCase):
    """Redis 키 패턴 및 TTL 상수 테스트."""

    def test_key_patterns_exist(self):
        from src.utils.redis_client import (
            KEY_STOCK_MASTER,
            KEY_SECTOR_MAP,
            KEY_THEME_MAP,
            KEY_RANKINGS,
            KEY_MACRO,
            KEY_ETF_LIST,
        )
        self.assertIn("stock_master", KEY_STOCK_MASTER)
        self.assertIn("sector_map", KEY_SECTOR_MAP)
        self.assertIn("theme_map", KEY_THEME_MAP)
        self.assertIn("{ranking_type}", KEY_RANKINGS)
        self.assertIn("{category}", KEY_MACRO)
        self.assertIn("etf_list", KEY_ETF_LIST)

    def test_ttl_constants_exist(self):
        from src.utils.redis_client import (
            TTL_STOCK_MASTER,
            TTL_SECTOR_MAP,
            TTL_THEME_MAP,
            TTL_RANKINGS,
            TTL_MACRO,
            TTL_ETF_LIST,
        )
        self.assertEqual(TTL_STOCK_MASTER, 86400)  # 24h
        self.assertEqual(TTL_SECTOR_MAP, 86400)
        self.assertEqual(TTL_THEME_MAP, 86400)
        self.assertEqual(TTL_RANKINGS, 300)  # 5min
        self.assertEqual(TTL_MACRO, 3600)  # 1h
        self.assertEqual(TTL_ETF_LIST, 86400)

    def test_rankings_key_formatting(self):
        from src.utils.redis_client import KEY_RANKINGS
        key = KEY_RANKINGS.format(ranking_type="market_cap")
        self.assertEqual(key, "redis:cache:rankings:market_cap")

    def test_macro_key_formatting(self):
        from src.utils.redis_client import KEY_MACRO
        key = KEY_MACRO.format(category="index")
        self.assertEqual(key, "redis:cache:macro:index")


class TestMacroCollectorDefinitions(unittest.TestCase):
    """매크로 수집기 정의 검증."""

    def test_foreign_indices_defined(self):
        from src.agents.macro_collector import FOREIGN_INDICES
        self.assertGreater(len(FOREIGN_INDICES), 3)
        self.assertIn("US500", FOREIGN_INDICES)
        self.assertIn("IXIC", FOREIGN_INDICES)
        self.assertIn("DJI", FOREIGN_INDICES)

    def test_currencies_defined(self):
        from src.agents.macro_collector import CURRENCIES
        self.assertGreater(len(CURRENCIES), 2)
        self.assertIn("USD/KRW", CURRENCIES)

    def test_commodities_defined(self):
        from src.agents.macro_collector import COMMODITIES
        self.assertGreater(len(COMMODITIES), 1)
        self.assertIn("GC=F", COMMODITIES)


class TestMarketplaceAPIRouterImport(unittest.TestCase):
    """마켓플레이스 API 라우터 임포트 테스트."""

    def test_router_import(self):
        from src.api.routers.marketplace import router
        self.assertIsNotNone(router)

    def test_router_has_routes(self):
        from src.api.routers.marketplace import router
        route_paths = [route.path for route in router.routes]
        # 핵심 엔드포인트가 존재하는지 확인
        self.assertIn("/stocks", route_paths)
        self.assertIn("/sectors", route_paths)
        self.assertIn("/themes", route_paths)
        self.assertIn("/rankings/{ranking_type}", route_paths)
        self.assertIn("/macro", route_paths)
        self.assertIn("/etf", route_paths)
        self.assertIn("/search", route_paths)
        self.assertIn("/watchlist", route_paths)


class TestDBSchemaDefinitions(unittest.TestCase):
    """DB 스키마 정의 검증 (DDL 문자열 포함 확인)."""

    def test_stock_master_table_exists_in_ddl(self):
        from scripts.db.init_db import CREATE_TABLES
        ddl_text = " ".join(CREATE_TABLES)
        self.assertIn("stock_master", ddl_text)
        self.assertIn("KOSPI", ddl_text)
        self.assertIn("KOSDAQ", ddl_text)

    def test_theme_stocks_table_exists_in_ddl(self):
        from scripts.db.init_db import CREATE_TABLES
        ddl_text = " ".join(CREATE_TABLES)
        self.assertIn("theme_stocks", ddl_text)
        self.assertIn("theme_slug", ddl_text)

    def test_macro_indicators_table_exists_in_ddl(self):
        from scripts.db.init_db import CREATE_TABLES
        ddl_text = " ".join(CREATE_TABLES)
        self.assertIn("macro_indicators", ddl_text)
        self.assertIn("category", ddl_text)

    def test_daily_rankings_table_exists_in_ddl(self):
        from scripts.db.init_db import CREATE_TABLES
        ddl_text = " ".join(CREATE_TABLES)
        self.assertIn("daily_rankings", ddl_text)
        self.assertIn("ranking_type", ddl_text)

    def test_watchlist_table_exists_in_ddl(self):
        from scripts.db.init_db import CREATE_TABLES
        ddl_text = " ".join(CREATE_TABLES)
        self.assertIn("watchlist", ddl_text)
        self.assertIn("price_alert_above", ddl_text)

    def test_drop_tables_includes_new_tables(self):
        from scripts.db.init_db import DROP_TABLES_SQL
        for table in ["stock_master", "theme_stocks", "macro_indicators", "daily_rankings", "watchlist"]:
            self.assertIn(table, DROP_TABLES_SQL, f"DROP_TABLES_SQL에 '{table}'가 없습니다.")


if __name__ == "__main__":
    unittest.main()
