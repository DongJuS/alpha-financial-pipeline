"""
src/utils/logging.py — 공통 로거 설정

모든 에이전트·API 모듈에서 이 모듈을 통해 로거를 가져옵니다.
"""

import logging
import sys
from src.utils.config import get_settings


def setup_logging() -> None:
    """앱 시작 시 한 번 호출하여 루트 로거를 초기화합니다."""
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    fmt = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(handler)

    # 외부 라이브러리 노이즈 억제
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """모듈별 로거를 반환합니다. 예: get_logger(__name__)"""
    return logging.getLogger(name)
