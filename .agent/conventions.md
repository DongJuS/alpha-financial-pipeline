# 📏 conventions.md — 코드 스타일 및 컨벤션

> 에이전트가 코드를 작성할 때 반드시 따라야 할 규칙들입니다.
> 이 프로젝트는 **Python(백엔드)** 과 **TypeScript(프론트엔드)** 를 모두 사용합니다.

---

## 🐍 Python 컨벤션 (백엔드 / 에이전트)

### 코드 스타일
- **포매터:** `ruff format` (Black 호환)
- **린터:** `ruff check`
- **들여쓰기:** 스페이스 4칸
- **최대 줄 길이:** 100자

### 타입 힌트
- 모든 함수에 타입 힌트 필수 (파라미터 + 반환값)
- Pydantic v2 모델로 데이터 검증 (dict 직접 사용 금지)
```python
# ✅ Good
async def get_quote(ticker: str) -> QuoteResponse:
    ...

# ❌ Bad
async def get_quote(ticker):
    ...
```

### 파일 및 폴더 네이밍
- **모듈 파일:** snake_case (`collector_agent.py`)
- **클래스:** PascalCase (`CollectorAgent`)
- **함수/변수:** snake_case (`fetch_ohlcv`)
- **상수:** UPPER_SNAKE_CASE (`MAX_RETRY_COUNT`)
- **폴더:** snake_case (`src/agents/`)

### 비동기 규칙
- I/O 작업은 반드시 `async/await` 사용 (blocking 호출 금지)
- `asyncio.run()`은 엔트리포인트에서만 사용
- DB/Redis 클라이언트는 비동기 드라이버 사용 (`asyncpg`, `redis.asyncio`)

### 에러 처리
- 예외는 반드시 명시적으로 처리 (빈 `except:` 금지)
- 에이전트 레벨 에러는 로깅 후 `agent_heartbeats`/`collector_errors` 테이블에 기록
```python
# ✅ Good
try:
    result = await kis_api.get_quote(ticker)
except KISApiError as e:
    logger.error(f"KIS API 오류: {e}")
    await log_error("collector_agent", str(e))
    raise

# ❌ Bad
try:
    result = await kis_api.get_quote(ticker)
except:
    pass
```

### 테스트 규칙
- 테스트 파일: `test/unit/test_*.py`, `test/integration/test_*.py`
- 프레임워크: `pytest` + `pytest-asyncio`
- 커버리지 목표: 80% 이상

---

## 🌐 TypeScript 컨벤션 (프론트엔드)

### 코드 스타일
- **언어:** TypeScript strict mode (`"strict": true`)
- **포매터:** Prettier (`.prettierrc` 참조)
- **린터:** ESLint (`.eslintrc` 참조)
- **들여쓰기:** 스페이스 2칸

### 파일 및 폴더 네이밍
- **컴포넌트 파일:** PascalCase (`SignalCard.tsx`)
- **훅/유틸 파일:** camelCase (`useAgentStatus.ts`)
- **상수 파일:** UPPER_SNAKE_CASE (`API_ENDPOINTS.ts`)
- **폴더:** kebab-case (`signal-card/`)

### 상태 관리
- 서버 상태: TanStack React Query (로컬 캐싱/폴링)
- 클라이언트 UI 상태: Zustand
- `useState`는 단순 로컬 UI 상태에만 사용

### 테스트 규칙
- 테스트 파일: `*.test.ts` / `*.test.tsx`
- 프레임워크: `vitest`
- 커버리지 목표: 80% 이상

---

## 🏗️ 공통 아키텍처 규칙

- 에러 처리는 반드시 명시적으로 한다 (silent fail 금지)
- 함수는 단일 책임 원칙을 따른다
- 하드코딩된 값은 상수 또는 환경변수로 분리
- 공통 Python 로직은 `src/utils/`, 공통 TS 로직은 `ui/src/utils/`에 위치

---

## 📝 커밋 메시지

```
feat: 새로운 기능 추가
fix: 버그 수정
docs: 문서 변경
style: 코드 포매팅 변경
refactor: 코드 리팩토링
test: 테스트 추가/수정
chore: 빌드 관련 수정
```

---

## 🗂️ 논의 문서 규칙

- 논의 문서는 `.agent/templates/discussion.md`를 복사해 생성합니다.
- 위치는 `.agent/discussions/`를 기본으로 사용합니다.
- 파일명 규칙은 `YYYYMMDD-topic-slug.md` 입니다.
- `1개 문서 = 1개 주제` 원칙을 지킵니다.
- 논의 종료 순서는 아래와 같습니다.
  1. 논의 문서에서 결론 확정
  2. 결론만 영구 문서에 반영
  3. 논의 문서 삭제
- 영구 문서 반영 기준은 아래와 같습니다.
  - 구조/장기 방향 변경: `.agent/roadmap.md`
  - 이번 세션의 할 일: `progress.md`
  - 앞으로 AI들이 계속 알아야 하는 운영 규칙: `MEMORY.md`

---

*Last updated: 2026-03-14*
