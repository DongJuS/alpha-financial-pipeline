#!/usr/bin/env bash
# ================================================================
# scripts/run_docker_tests.sh — Docker 기반 pytest 실행 스크립트
#
# 사용법:
#   ./scripts/run_docker_tests.sh           # 일반 실행
#   ./scripts/run_docker_tests.sh --keep    # 컨테이너 유지 (디버깅용)
# ================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

# 옵션 처리
KEEP_CONTAINERS=false
if [[ "${1:-}" == "--keep" ]]; then
    KEEP_CONTAINERS=true
fi

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

# ────────────────────────────────────────────────────────────────
# 메인 실행
# ────────────────────────────────────────────────────────────────

print_status "Docker Compose 테스트 환경 구성..."

# 이미 실행 중인 컨테이너 확인
if docker compose -f docker-compose.yml -f docker-compose.test.yml ps 2>/dev/null | grep -q "test-runner"; then
    print_warning "기존 테스트 러너 컨테이너가 실행 중입니다. 정지합니다..."
    docker compose -f docker-compose.yml -f docker-compose.test.yml down -v 2>/dev/null || true
fi

print_status "테스트 컨테이너 빌드 및 실행..."
if docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --build test-runner; then
    print_status "${GREEN}✅ 모든 테스트가 통과했습니다!${NC}"
    TEST_RESULT=0
else
    print_error "테스트 실행 중 오류가 발생했습니다."
    TEST_RESULT=$?
fi

# 정리
if [ "$KEEP_CONTAINERS" = false ]; then
    print_status "정리 중 (컨테이너 및 볼륨 제거)..."
    docker compose -f docker-compose.yml -f docker-compose.test.yml down -v 2>/dev/null || true
    print_status "정리 완료."
else
    print_warning "컨테이너가 실행 중입니다. 수동으로 정리하려면 다음을 실행하세요:"
    echo "  docker compose -f docker-compose.yml -f docker-compose.test.yml down -v"
fi

exit $TEST_RESULT
