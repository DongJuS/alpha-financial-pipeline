"""
scripts/load_themes.py — 초기 테마 데이터 로더

30개 투자 테마를 theme_stocks 테이블에 로드합니다.

사용법:
    python scripts/load_themes.py
"""

import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from src.data.themes import INITIAL_THEMES
from src.db.marketplace_queries import upsert_theme_stocks

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


async def load_themes() -> int:
    """초기 테마 데이터를 DB에 로드합니다."""
    total = 0
    for slug, theme_data in INITIAL_THEMES.items():
        theme_name = theme_data["name"]
        tickers = theme_data["stocks"]
        # 첫 번째 종목을 리더로 설정
        leaders = [tickers[0]] if tickers else []

        count = await upsert_theme_stocks(
            theme_slug=slug,
            theme_name=theme_name,
            tickers=tickers,
            leader_tickers=leaders,
        )
        total += count
        logger.info("테마 '%s' (%s): %d개 종목 로드", slug, theme_name, count)

    logger.info("✅ 전체 테마 로드 완료: %d개 테마, %d개 매핑", len(INITIAL_THEMES), total)
    return total


def main() -> None:
    asyncio.run(load_themes())


if __name__ == "__main__":
    main()
