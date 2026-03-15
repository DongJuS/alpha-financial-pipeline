#!/usr/bin/env bash
# ============================================================================
# PR 워크플로우 스크립트
# 사용법:
#   ./scripts/pr.sh check          # PR 전 사전 검증만 실행
#   ./scripts/pr.sh create         # 대화형 PR 생성 (branch → check → commit → push → PR)
#   ./scripts/pr.sh quick "메시지"  # 빠른 PR (현재 변경사항 → 커밋 → 푸시 → PR)
# ============================================================================

set -euo pipefail

# ── 색상 정의 ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ── 유틸 함수 ────────────────────────────────────────────────────────────────
info()    { echo -e "${BLUE}ℹ${NC}  $*"; }
success() { echo -e "${GREEN}✅${NC} $*"; }
warn()    { echo -e "${YELLOW}⚠️${NC}  $*"; }
error()   { echo -e "${RED}❌${NC} $*"; }
step()    { echo -e "\n${CYAN}━━━ $* ━━━${NC}"; }

# 프로젝트 루트로 이동
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# ── 사전 검증 (pre-pr check) ────────────────────────────────────────────────
run_check() {
    local has_error=0

    step "1/5  Merge conflict 마커 검사"
    if grep -rn '<<<<<<< \|=======$\|>>>>>>> ' --include='*.py' --include='*.ts' --include='*.tsx' src/ test/ ui/ 2>/dev/null; then
        error "Merge conflict 마커가 남아있습니다!"
        has_error=1
    else
        success "Merge conflict 마커 없음"
    fi

    step "2/5  Python AST 구문 검증"
    local py_errors=0
    while IFS= read -r -d '' pyfile; do
        if ! python3 -c "import ast; ast.parse(open('$pyfile').read())" 2>/dev/null; then
            error "SyntaxError: $pyfile"
            py_errors=1
        fi
    done < <(find src/ test/ scripts/ -name '*.py' -print0 2>/dev/null)
    if [ "$py_errors" -eq 0 ]; then
        success "Python 구문 검증 통과"
    else
        has_error=1
    fi

    step "3/5  Ruff 린트 (설치된 경우)"
    if command -v ruff &>/dev/null; then
        if ruff check src/ --quiet 2>/dev/null; then
            success "Ruff 린트 통과"
        else
            warn "Ruff 린트 경고 있음 (--fix 로 자동 수정 가능)"
        fi
    else
        warn "ruff 미설치 — 스킵"
    fi

    step "4/5  TypeScript 타입 검사 (설치된 경우)"
    if [ -f "ui/tsconfig.json" ] && command -v npx &>/dev/null; then
        if (cd ui && npx tsc --noEmit 2>/dev/null); then
            success "TypeScript 타입 검사 통과"
        else
            warn "TypeScript 타입 에러 있음"
        fi
    else
        warn "TypeScript 환경 없음 — 스킵"
    fi

    step "5/5  테스트 실행 (Docker 환경인 경우)"
    if command -v pytest &>/dev/null; then
        if pytest test/ -x -q --tb=line 2>/dev/null; then
            success "테스트 통과"
        else
            warn "일부 테스트 실패"
        fi
    elif [ -f "scripts/run_docker_tests.sh" ]; then
        warn "pytest 미설치 — Docker 테스트는 'make test-docker'로 별도 실행하세요"
    else
        warn "테스트 환경 없음 — 스킵"
    fi

    echo ""
    if [ "$has_error" -eq 1 ]; then
        error "사전 검증 실패 — 위 이슈를 수정 후 다시 시도하세요"
        return 1
    else
        success "사전 검증 모두 통과!"
        return 0
    fi
}

# ── 브랜치 생성/확인 ────────────────────────────────────────────────────────
ensure_branch() {
    local current
    current=$(git branch --show-current)

    if [ "$current" = "main" ] || [ "$current" = "master" ]; then
        warn "현재 $current 브랜치입니다. PR용 브랜치를 만들어야 합니다."
        echo ""
        read -rp "$(echo -e "${CYAN}새 브랜치 이름 (예: feature/my-feature):${NC} ")" branch_name
        if [ -z "$branch_name" ]; then
            error "브랜치 이름이 비어있습니다."
            exit 1
        fi
        git checkout -b "$branch_name"
        success "브랜치 생성: $branch_name"
    else
        info "현재 브랜치: $current"
    fi
}

# ── 변경사항 스테이징 ────────────────────────────────────────────────────────
stage_changes() {
    step "변경사항 확인"

    # .env 파일 제외 경고
    local sensitive_files
    sensitive_files=$(git diff --name-only --cached 2>/dev/null | grep -E '\.env$|credentials|secret' || true)
    if [ -n "$sensitive_files" ]; then
        warn "민감 파일이 스테이징에 포함되어 있습니다:"
        echo "$sensitive_files"
        read -rp "$(echo -e "${YELLOW}계속하시겠습니까? (y/N):${NC} ")" confirm
        if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
            error "중단됨"
            exit 1
        fi
    fi

    echo ""
    git status --short

    echo ""
    read -rp "$(echo -e "${CYAN}모든 변경사항을 스테이징할까요? (Y/n):${NC} ")" stage_all
    if [ "$stage_all" != "n" ] && [ "$stage_all" != "N" ]; then
        git add -A
        # .env 자동 제외
        git reset HEAD -- '*.env' '.env*' 2>/dev/null || true
        success "스테이징 완료 (.env 파일 자동 제외)"
    else
        info "수동으로 git add 후 다시 실행하세요."
        exit 0
    fi
}

# ── 커밋 ────────────────────────────────────────────────────────────────────
create_commit() {
    step "커밋 생성"

    if git diff --cached --quiet; then
        warn "스테이징된 변경사항이 없습니다."
        return 1
    fi

    echo -e "${CYAN}커밋 타입을 선택하세요:${NC}"
    echo "  1) feat     — 새로운 기능"
    echo "  2) fix      — 버그 수정"
    echo "  3) docs     — 문서 변경"
    echo "  4) refactor — 리팩토링"
    echo "  5) test     — 테스트"
    echo "  6) chore    — 빌드/설정"
    echo ""
    read -rp "번호 선택 (1-6): " type_num

    case $type_num in
        1) commit_type="feat" ;;
        2) commit_type="fix" ;;
        3) commit_type="docs" ;;
        4) commit_type="refactor" ;;
        5) commit_type="test" ;;
        6) commit_type="chore" ;;
        *) commit_type="feat" ;;
    esac

    echo ""
    read -rp "$(echo -e "${CYAN}커밋 메시지 (한글 OK):${NC} ")" commit_msg

    if [ -z "$commit_msg" ]; then
        error "커밋 메시지가 비어있습니다."
        return 1
    fi

    git commit -m "${commit_type}: ${commit_msg}"
    success "커밋 완료: ${commit_type}: ${commit_msg}"
}

# ── 푸시 ────────────────────────────────────────────────────────────────────
push_branch() {
    step "원격 저장소 푸시"

    local current
    current=$(git branch --show-current)
    local remote_exists
    remote_exists=$(git ls-remote --heads origin "$current" 2>/dev/null | wc -l)

    if [ "$remote_exists" -eq 0 ]; then
        info "원격에 '$current' 브랜치가 없습니다. 새로 생성합니다."
        git push -u origin "$current"
    else
        git push origin "$current"
    fi

    success "푸시 완료: origin/$current"
}

# ── PR 생성 ─────────────────────────────────────────────────────────────────
create_pr() {
    step "Pull Request 생성"

    if ! command -v gh &>/dev/null; then
        warn "gh CLI가 설치되어 있지 않습니다."
        local current
        current=$(git branch --show-current)
        info "GitHub에서 직접 PR을 생성하세요:"
        echo -e "  ${BLUE}https://github.com/$(git remote get-url origin | sed 's/.*github.com[:/]\(.*\)\.git/\1/')/compare/main...$current${NC}"
        return 0
    fi

    echo ""
    read -rp "$(echo -e "${CYAN}PR 제목:${NC} ")" pr_title
    if [ -z "$pr_title" ]; then
        # 마지막 커밋 메시지를 기본값으로
        pr_title=$(git log -1 --pretty=%s)
        info "기본 제목 사용: $pr_title"
    fi

    echo ""
    info "PR 본문을 입력하세요 (빈 줄에서 Ctrl+D로 종료, 빈 입력 시 자동 생성):"
    local pr_body=""
    read -rp "" pr_body_input
    if [ -z "$pr_body_input" ]; then
        # 자동 생성: 커밋 로그 기반
        local base_branch="main"
        local commits
        commits=$(git log "$base_branch"..HEAD --pretty="- %s" 2>/dev/null || git log -5 --pretty="- %s")
        pr_body="## Summary
${commits}

## Test plan
- [ ] AST 구문 검증 통과
- [ ] 린트 통과
- [ ] 유닛 테스트 통과
- [ ] API 엔드포인트 동작 확인"
        info "커밋 기반 PR 본문 자동 생성됨"
    else
        pr_body="$pr_body_input"
    fi

    gh pr create --title "$pr_title" --body "$pr_body"
    success "PR 생성 완료!"
}

# ── Quick PR (한 번에 처리) ─────────────────────────────────────────────────
quick_pr() {
    local msg="${1:-}"
    if [ -z "$msg" ]; then
        error "사용법: ./scripts/pr.sh quick \"커밋 메시지\""
        exit 1
    fi

    step "Quick PR 시작"

    ensure_branch
    run_check || { error "사전 검증 실패"; exit 1; }

    git add -A
    git reset HEAD -- '*.env' '.env*' 2>/dev/null || true

    if git diff --cached --quiet; then
        warn "커밋할 변경사항이 없습니다."
        exit 0
    fi

    git commit -m "$msg"
    success "커밋: $msg"

    push_branch
    create_pr
}

# ── 대화형 PR 생성 ─────────────────────────────────────────────────────────
interactive_pr() {
    step "대화형 PR 워크플로우"

    ensure_branch
    run_check || { error "사전 검증 실패 — 수정 후 다시 시도하세요"; exit 1; }
    stage_changes
    create_commit || exit 1
    push_branch
    create_pr

    echo ""
    success "PR 워크플로우 완료!"
}

# ── 메인 ────────────────────────────────────────────────────────────────────
case "${1:-help}" in
    check)
        run_check
        ;;
    create)
        interactive_pr
        ;;
    quick)
        quick_pr "${2:-}"
        ;;
    help|--help|-h|*)
        echo ""
        echo -e "${CYAN}PR 워크플로우 스크립트${NC}"
        echo ""
        echo "사용법:"
        echo -e "  ${GREEN}./scripts/pr.sh check${NC}            사전 검증만 실행"
        echo -e "  ${GREEN}./scripts/pr.sh create${NC}           대화형 PR 생성"
        echo -e "  ${GREEN}./scripts/pr.sh quick \"메시지\"${NC}   빠른 PR (커밋→푸시→PR)"
        echo ""
        echo "사전 검증 항목:"
        echo "  • Merge conflict 마커 검사"
        echo "  • Python AST 구문 검증"
        echo "  • Ruff 린트 (설치 시)"
        echo "  • TypeScript 타입 검사 (설치 시)"
        echo "  • 테스트 실행 (pytest 설치 시)"
        echo ""
        ;;
esac
