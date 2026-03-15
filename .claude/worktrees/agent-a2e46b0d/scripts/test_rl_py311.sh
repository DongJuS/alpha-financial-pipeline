#!/usr/bin/env bash
# scripts/test_rl_py311.sh
# Python 3.11 환경에서 RL 모델의 호환성과 안정성을 검증하기 위한 테스트 스크립트.

set -e

echo "=========================================================="
echo " Setting up Python 3.11 environment with uv..."
echo "=========================================================="

# 3.11 전용 가상환경 생성 (기존 환경과 격리)
uv venv --python 3.11 .venv_311

# 패키지 설치
VIRTUAL_ENV=.venv_311 uv pip install -r requirements.txt pytest pytest-asyncio

echo "=========================================================="
echo " Running RL tests (V1, V2, Registry) with Python 3.11..."
echo "=========================================================="

# PYTHONPATH를 지정하고 3.11 가상환경의 pytest 실행
PYTHONPATH=. .venv_311/bin/pytest \
    test/test_rl_trading.py \
    test/test_rl_trading_v2.py \
    test/test_rl_policy_registry.py \
    -v

echo "=========================================================="
echo " RL tests for Python 3.11 completed successfully! ✓"
echo "=========================================================="
