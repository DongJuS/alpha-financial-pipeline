"""
scripts/db/migrate_rl_registry.py -- registry.json -> rl_policies 테이블 마이그레이션

artifacts/rl/models/registry.json 의 정책 데이터를 PostgreSQL rl_policies 테이블에
일괄 INSERT 한다. idempotent (ON CONFLICT DO NOTHING).

마이그레이션 시 활성 정책 재평가:
  - registry.json 의 active_policy_id 를 기본으로 반영하되,
  - 해당 티커에 approved 정책 중 더 높은 return_pct 정책이 있으면
    최고 수익률 정책을 활성으로 승격한다.

사용법:
  python scripts/db/migrate_rl_registry.py            # 실행
  python scripts/db/migrate_rl_registry.py --dry-run   # 미리보기
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from src.utils.db_client import get_pool  # noqa: E402
from src.utils.logging import get_logger, setup_logging  # noqa: E402
from src.utils.ticker import normalize  # noqa: E402

setup_logging()
logger = get_logger(__name__)

REGISTRY_PATH = ROOT / "artifacts" / "rl" / "models" / "registry.json"

HYPERPARAMS_KEYS = [
    "lookback",
    "episodes",
    "learning_rate",
    "discount_factor",
    "epsilon",
    "trade_penalty_bps",
]


# ── 레지스트리 로드 ──────────────────────────────────────────────


def load_registry() -> dict:
    """registry.json 을 로드하여 반환한다."""
    if not REGISTRY_PATH.exists():
        logger.error("registry.json 이 존재하지 않습니다: %s", REGISTRY_PATH)
        sys.exit(1)
    with REGISTRY_PATH.open() as f:
        return json.load(f)


# ── instruments FK 검증 ──────────────────────────────────────────


async def fetch_valid_instruments(pool) -> set[str]:
    """instruments 테이블에 등록된 instrument_id 집합을 반환한다."""
    rows = await pool.fetch("SELECT instrument_id FROM instruments")
    return {r["instrument_id"] for r in rows}


# ── 활성 정책 결정 ───────────────────────────────────────────────


def decide_active_policy(
    ticker_key: str,
    ticker_data: dict,
    instrument_id: str,
) -> str | None:
    """해당 instrument 의 활성 정책 ID 를 결정한다.

    1. approved 정책 중 최고 return_pct 정책이 있으면 그것을 활성으로 설정.
    2. approved 정책이 없으면 registry 의 active_policy_id 를 그대로 사용.
    """
    policies = ticker_data.get("policies", [])
    original_active = ticker_data.get("active_policy_id")

    # approved 정책만 추출
    approved = [p for p in policies if p.get("approved")]
    if not approved:
        return original_active

    # 최고 수익률 정책
    best = max(approved, key=lambda p: p.get("return_pct", 0))
    best_id = best["policy_id"]

    if original_active and original_active != best_id:
        orig_return = next(
            (p.get("return_pct", 0) for p in policies if p["policy_id"] == original_active),
            0,
        )
        logger.info(
            "[%s] 활성 정책 재평가: %s (%.1f%%) -> %s (%.1f%%)",
            instrument_id,
            original_active,
            orig_return,
            best_id,
            best.get("return_pct", 0),
        )

    return best_id


# ── 마이그레이션 실행 ────────────────────────────────────────────


def build_rows(registry: dict, valid_instruments: set[str]) -> list[tuple]:
    """registry 데이터를 rl_policies 행 목록으로 변환한다.

    Returns:
        list of tuples:
            (policy_id, instrument_id, algorithm, state_version,
             return_pct, baseline_return_pct, excess_return_pct,
             max_drawdown_pct, trades, win_rate, holdout_steps,
             approved, is_active, file_path, hyperparams, created_at)
    """
    rows: list[tuple] = []
    tickers_data = registry.get("tickers", {})

    for ticker_key, ticker_data in tickers_data.items():
        policies = ticker_data.get("policies", [])
        if not policies:
            continue

        # 티커 정규화: registry 의 각 policy 에 ticker 필드가 있으면 그것을,
        # 없으면 ticker_key 를 normalize
        sample_ticker = policies[0].get("ticker", ticker_key)
        instrument_id = normalize(sample_ticker)

        # instruments FK 검증
        if instrument_id not in valid_instruments:
            logger.warning(
                "[SKIP] %s (정규화: %s) — instruments 테이블에 없음",
                ticker_key,
                instrument_id,
            )
            continue

        # 활성 정책 결정
        active_policy_id = decide_active_policy(ticker_key, ticker_data, instrument_id)

        for p in policies:
            hyperparams = {k: p[k] for k in HYPERPARAMS_KEYS if k in p}

            rows.append((
                p["policy_id"],
                instrument_id,
                p.get("algorithm", "tabular_q_learning"),
                p["state_version"],
                p.get("return_pct", 0),
                p.get("baseline_return_pct", 0),
                p.get("excess_return_pct", 0),
                p.get("max_drawdown_pct", 0),
                p.get("trades", 0),
                p.get("win_rate", 0),
                p.get("holdout_steps", 0),
                p.get("approved", False),
                p["policy_id"] == active_policy_id if active_policy_id else False,
                p["file_path"],
                json.dumps(hyperparams) if hyperparams else None,
                p.get("created_at"),
            ))

    return rows


async def migrate(*, dry_run: bool = False) -> int:
    """registry.json -> rl_policies 마이그레이션을 실행한다."""
    registry = load_registry()
    pool = await get_pool()

    valid_instruments = await fetch_valid_instruments(pool)
    logger.info("instruments 테이블: %d개 종목 등록됨", len(valid_instruments))

    rows = build_rows(registry, valid_instruments)
    if not rows:
        logger.warning("마이그레이션할 정책이 없습니다.")
        return 0

    if dry_run:
        logger.info("=== DRY-RUN 모드 (실제 DB 변경 없음) ===")
        for r in rows:
            active_mark = " [ACTIVE]" if r[12] else ""
            approved_mark = " [APPROVED]" if r[11] else ""
            logger.info(
                "  %s -> %s  return=%.1f%%%s%s",
                r[0],  # policy_id
                r[1],  # instrument_id
                r[4],  # return_pct
                approved_mark,
                active_mark,
            )
        logger.info("  총 %d건 예정", len(rows))
        return 0

    upsert_query = """
        INSERT INTO rl_policies (
            policy_id, instrument_id, algorithm, state_version,
            return_pct, baseline_return_pct, excess_return_pct,
            max_drawdown_pct, trades, win_rate, holdout_steps,
            approved, is_active, file_path, hyperparams, created_at
        ) VALUES (
            $1, $2, $3, $4,
            $5, $6, $7,
            $8, $9, $10, $11,
            $12, $13, $14, $15::jsonb, $16::timestamptz
        )
        ON CONFLICT (policy_id) DO NOTHING
    """

    async with pool.acquire() as conn:
        async with conn.transaction():
            # is_active 유니크 인덱스 충돌 방지: 기존 활성 해제 후 새로 설정
            # 먼저 모든 is_active 를 false 로 리셋
            await conn.execute("UPDATE rl_policies SET is_active = false")

            await conn.executemany(upsert_query, rows)

            # ON CONFLICT DO NOTHING 으로 기존 행이 갱신되지 않으므로,
            # is_active 를 별도 UPDATE 로 설정
            active_rows = [(r[0], r[1]) for r in rows if r[12]]  # (policy_id, instrument_id)
            for policy_id, instrument_id in active_rows:
                await conn.execute(
                    "UPDATE rl_policies SET is_active = true WHERE policy_id = $1",
                    policy_id,
                )

    logger.info("=== rl_policies 마이그레이션 완료: %d건 INSERT ===", len(rows))
    return len(rows)


# ── 검증 ────────────────────────────────────────────────────────


async def verify() -> None:
    """마이그레이션 결과를 확인한다."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT policy_id, instrument_id, return_pct, approved, is_active, algorithm
        FROM rl_policies
        ORDER BY instrument_id, created_at
        """
    )

    if not rows:
        logger.warning("[verify] rl_policies 테이블이 비어 있습니다.")
        return

    logger.info("\n=== rl_policies 검증: %d건 ===", len(rows))
    header = f"  {'policy_id':<42} {'instrument':<14} {'return%':>8} {'approved':>8} {'active':>6}"
    logger.info(header)
    logger.info("  " + "-" * len(header))
    for r in rows:
        logger.info(
            "  %-42s %-14s %8.1f %8s %6s",
            r["policy_id"],
            r["instrument_id"],
            r["return_pct"],
            str(r["approved"]),
            str(r["is_active"]),
        )


# ── 메인 ────────────────────────────────────────────────────────


async def main_async(args: argparse.Namespace) -> None:
    count = await migrate(dry_run=args.dry_run)
    if not args.dry_run and count > 0:
        await verify()


def main():
    parser = argparse.ArgumentParser(
        description="registry.json -> rl_policies 테이블 마이그레이션",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  %(prog)s              # 실행
  %(prog)s --dry-run     # 미리보기
        """,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 DB 변경 없이 미리보기만 출력",
    )
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
