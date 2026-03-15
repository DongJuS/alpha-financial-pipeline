# tech_stack.md — 허용된 기술 스택

이 문서는 현재 사용 중인 코어 스택과, 구조적으로 승인된 확장 스택을 함께 정의합니다.
새 패키지 추가 시 이 문서를 함께 갱신합니다.

## 코어 백엔드 스택

| 패키지 | 용도 |
|--------|------|
| `fastapi` | REST API |
| `uvicorn` | ASGI 서버 |
| `pydantic`, `pydantic-settings` | 설정/검증 |
| `asyncpg` | PostgreSQL |
| `redis` | Redis 캐시/메시지 버스 |
| `httpx` | 비동기 HTTP |
| `websockets` | KIS 실시간 시세 |
| `langgraph` | 워크플로우 조율 |
| `FinanceDataReader` | 일봉 데이터 수집 |
| `python-dotenv` | `.env` 로딩 |
| `PyJWT` | 인증 토큰 |
| `python-telegram-bot` | Telegram 알림 |

## 코어 프런트엔드 스택

| 패키지 | 용도 |
|--------|------|
| `react` | UI |
| `typescript` | 타입 시스템 |
| `vite` | 개발/빌드 |
| `@tanstack/react-query` | 서버 상태 |
| `zustand` | 클라이언트 상태 |
| `recharts` | 차트 |
| `tailwindcss` | 스타일링 |

## LLM 스택

| 제공자 | 기본 경로 | 비고 |
|--------|-----------|------|
| Claude | Claude CLI 또는 SDK | 핵심 reasoning과 synthesis 담당 |
| OpenAI | `openai` SDK | GPT 계열 역할 수행 |
| Gemini | OAuth(ADC) 우선, 필요 시 API key fallback | Gemini CLI는 사용하지 않음 |

운영 원칙:
- Claude는 최종 reasoning 계층으로 우선 사용 가능
- Gemini는 CLI가 아니라 OAuth 기반 경로를 기준으로 한다
- 모델 선택은 UI/DB 설정으로 조정하되, 실행 권한은 코어 런타임이 통제한다

## 검색/스크래핑 확장 스택

아래 스택은 구조적으로 승인된 확장 스택입니다.

| 구성요소 | 역할 | 배포 방식 |
|----------|------|-----------|
| `SearXNG` | 검색 결과 생성 | Docker |
| `ScrapeGraphAI` | 페이지 구조화/파싱 | Docker 또는 worker 컨테이너 |
| `Claude CLI` | 추출 결과의 의미 해석과 최종 구조화 | agent/worker |
| 브라우저 렌더러 | JS-heavy 페이지 fetch/render | Docker sidecar |

규칙:
- Tavily는 사용하지 않는다
- 검색은 SearXNG가 담당한다
- ScrapeGraphAI는 페이지 구조화만 담당한다
- 최종 추출/판단은 Claude CLI가 담당한다

## RL 확장 스택

아래 스택은 RL lane 도입 시 사용할 수 있는 승인된 후보 스택입니다.

| 패키지 | 역할 |
|--------|------|
| `numpy` | 수치 계산 |
| `pandas` | feature engineering / tabular data |
| `torch` | RL 모델 학습 백엔드 |
| `gymnasium` | 트레이딩 environment 인터페이스 |
| `stable-baselines3` | 기본 RL 알고리즘 구현 |
| `scikit-learn` | 보조 전처리/평가 |

원칙:
- RL은 코어 런타임을 대체하지 않는다
- RL 신호도 기존 리스크 가드를 그대로 통과해야 한다
- 학습/평가와 실거래는 엄격히 분리한다

## Data Lake 스택

| 패키지 | 역할 |
|--------|------|
| `boto3` | S3/MinIO 오브젝트 스토리지 클라이언트 |
| `pyarrow` | Parquet 직렬화/역직렬화 |
| `MinIO` (Docker) | S3 호환 오브젝트 스토리지 (개발), 프로덕션은 AWS S3 |

원칙:
- 모든 데이터(틱, 일봉, 매크로, 검색, 리서치, 예측, 주문)는 Parquet 포맷으로 저장
- 파티셔닝: `{data_type}/year=YYYY/month=MM/day=DD/` Hive 스타일
- MinIO는 개발 환경 전용, endpoint_url만 바꾸면 AWS S3로 전환 가능
- 데이터 레이크는 읽기 전용 아카이브 — 분석/RL 학습용

## 인프라와 배포

| 구성요소 | 표준 |
|----------|------|
| Runtime | Python 3.11+, Node.js 20+ |
| Database | PostgreSQL 15+ |
| Cache / Bus | Redis 7+ |
| Local / Dev orchestration | Docker Compose |
| UI workspace | `ui/web`, `ui/ios` 분리 |

## 금지 또는 비권장 경로

| 항목 | 상태 | 이유 |
|------|------|------|
| Tavily MCP | 사용하지 않음 | SearXNG + ScrapeGraphAI 구조로 대체 |
| Gemini CLI | 사용하지 않음 | OAuth 기반 인증으로 통일 |
| RL의 직접 브로커 호출 | 금지 | 주문 권한은 PortfolioManager에만 존재 |
