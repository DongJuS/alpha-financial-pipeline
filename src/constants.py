"""
src/constants.py — 프로젝트 전역 상수

매직 넘버와 LLM 기본 모델명을 한 곳에서 관리합니다.
config.py(환경 변수)와 달리, 코드 레벨에서 변경 빈도가 낮은 값입니다.
"""

from __future__ import annotations

# ── 페이퍼/가상 트레이딩 초기 자본 ──────────────────────────────────
PAPER_TRADING_INITIAL_CAPITAL: int = 10_000_000

# ── LLM 기본 모델명 (fallback) ──────────────────────────────────────
# 생성자에서 특정 모델을 지정하지 않았을 때 사용하는 기본값
DEFAULT_CLAUDE_MODEL: str = "claude-3-5-sonnet-latest"
DEFAULT_GPT_MODEL: str = "gpt-4o-mini"
DEFAULT_GEMINI_MODEL: str = "gemini-1.5-pro"

# ── KIS WebSocket 실시간 수집 ──────────────────────────────────────
MAX_TICKERS_PER_WS: int = 20  # KIS WebSocket 1연결당 최대 구독 종목 수

# ── 백테스트 비용 모델 ──────────────────────────────────────────────
BACKTEST_COMMISSION_RATE_PCT: float = 0.015  # 매수/매도 양방향 (증권사 수수료)
BACKTEST_TAX_RATE_PCT: float = 0.18          # 매도 시에만 (증권거래세)
BACKTEST_SLIPPAGE_BPS: int = 3               # 고정 슬리피지 (재현성)
