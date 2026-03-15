# ============================================================================
# agents-investing Makefile
# ============================================================================

.PHONY: help pr-check pr-create pr-quick lint test test-docker dev build

# ── 기본 타겟 ────────────────────────────────────────────────────────────────
help: ## 사용 가능한 명령어 목록
	@echo ""
	@echo "📋 agents-investing 명령어"
	@echo ""
	@grep -P '^[a-zA-Z_-]+:.*##' $(MAKEFILE_LIST) | grep -v '^help:' | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'
	@echo ""

# ── PR 워크플로우 ────────────────────────────────────────────────────────────
pr-check: ## PR 사전 검증 (conflict 마커, AST, 린트, 테스트)
	@./scripts/pr.sh check

pr-create: ## 대화형 PR 생성 (브랜치 > 검증 > 커밋 > 푸시 > PR)
	@./scripts/pr.sh create

pr-quick: ## 빠른 PR / make pr-quick MSG="feat: 메시지"
	@./scripts/pr.sh quick "$(MSG)"

# ── 코드 품질 ────────────────────────────────────────────────────────────────
lint: ## Ruff 린트 실행
	@ruff check src/ --fix
	@ruff format src/

lint-check: ## Ruff 린트 (수정 없이 검사만)
	@ruff check src/
	@ruff format src/ --check

ast-check: ## Python 전체 AST 구문 검증
	@python3 -c "\
	import ast, sys, pathlib; \
	errors = []; \
	[errors.append(f) for f in pathlib.Path('src').rglob('*.py') \
	 if not (lambda p: (ast.parse(p.read_text()) and False) if True else True)(f)]; \
	print('✅ AST 검증 통과' if not errors else f'❌ {len(errors)}개 파일 오류')"
	@find src/ test/ -name '*.py' -exec python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read()); print(f'  ✅ {sys.argv[1]}')" {} \; 2>&1 | grep -v '✅' || echo "✅ 모든 Python 파일 구문 정상"

# ── 테스트 ────────────────────────────────────────────────────────────────────
test: ## pytest 실행 (로컬)
	@pytest test/ -v --tb=short

test-docker: ## Docker 환경 테스트 실행
	@./scripts/run_docker_tests.sh

test-feedback: ## 피드백 파이프라인 테스트만 실행
	@pytest test/test_feedback_pipeline.py -v --tb=short

# ── 개발 서버 ────────────────────────────────────────────────────────────────
dev: ## FastAPI 개발 서버 실행
	@uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

dev-ui: ## 프론트엔드 개발 서버 실행
	@cd ui && npm run dev

# ── 빌드/배포 ────────────────────────────────────────────────────────────────
build: ## Docker 이미지 빌드
	@docker compose build

up: ## Docker 전체 서비스 시작
	@docker compose up -d

down: ## Docker 전체 서비스 중지
	@docker compose down

logs: ## Docker 로그 확인 (실시간)
	@docker compose logs -f --tail=100

# ── 유틸리티 ─────────────────────────────────────────────────────────────────
health: ## 서비스 헬스체크
	@python3 scripts/health_check.py

smoke: ## 스모크 테스트
	@python3 scripts/smoke_test.py

validate: ## 전체 Phase 유효성 검증
	@python3 scripts/validate_all_phases.py

security: ## 보안 감사
	@python3 scripts/security_audit.py
