# Swagger / OpenAPI Guide

이 문서는 `alpha-financial-pipeline` 프로젝트에서 Swagger(OpenAPI)를 어떻게 이해하고 사용하는지 정리한 운영 메모입니다.

## 기본 주소

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`

로컬 Docker 실행 기준:

- [http://localhost:8000/docs](http://localhost:8000/docs)
- [http://localhost:8000/redoc](http://localhost:8000/redoc)

## 언제 Swagger에 자동 반영되는가

프로젝트 내부에 함수를 추가하는 것만으로는 Swagger에 나타나지 않습니다.

Swagger에 자동 반영되는 경우:

- FastAPI 라우트 데코레이터가 붙어 있음
  - 예: `@router.get(...)`, `@router.post(...)`
- 해당 `router`가 최종적으로 `app.include_router(...)`로 앱에 등록됨

Swagger에 반영되지 않는 경우:

- 일반 유틸 함수
- 서비스 함수
- DB 접근 함수
- 워커 내부 함수
- 라우터 파일 안에 있어도 데코레이터가 없는 함수

즉, "REST API로 등록된 함수"만 Swagger에 자동 반영됩니다.

## 왜 `Responses 200`인데 실제 실행은 `500`일 수 있는가

Swagger 화면에는 보통 두 종류의 정보가 함께 보입니다.

`Responses`

- 문서에 선언된 정상 응답 스펙입니다.
- 예를 들어 FastAPI에서 `response_model=...`을 선언하면 기본적으로 `200` 응답이 문서에 표시됩니다.

`Server response`

- 방금 `Try it out`으로 실제 실행한 결과입니다.
- 여기서 `500 Internal Server Error`가 나오면 런타임 예외가 발생한 것입니다.

따라서 아래 상황은 자연스럽습니다.

- 문서에는 `200`이 보임
- 실제 실행 결과는 `500`

이 경우 뜻은:

- API 설계상 정상 응답은 `200`으로 정의되어 있음
- 하지만 현재 실행 환경에서는 예외가 발생함

## Swagger가 안 열릴 때 먼저 볼 것

Swagger UI는 FastAPI 서버가 같이 제공하는 화면입니다. 따라서 `/docs`가 안 열리면 브라우저 문제보다 API startup 문제일 가능성이 큽니다.

먼저 확인할 것:

1. `api` 컨테이너가 떠 있는지
2. `postgres`, `redis`, `minio`가 같이 떠 있는지
3. API 로그에 startup failure가 없는지

이 프로젝트에서는 API startup 시 DB/Redis 연결을 먼저 시도하므로, 의존 컨테이너가 내려가 있으면 `/docs`도 열리지 않을 수 있습니다.

## 이 프로젝트에서 Swagger의 역할

Swagger는 이 프로젝트에서 "시각적인 API 테스트 창" 역할을 합니다.

주요 사용 목적:

- 인증 후 실제 응답 JSON 확인
- `Strategy A/B` 결과 확인
- `Portfolio` 응답 구조 확인
- `Agents` 상태 응답 확인
- 프론트 없이 API 계약 확인

즉, Swagger는 "지금 바깥으로 어떤 응답이 나가는가"를 확인하는 도구입니다.

## pytest, 로그와의 역할 분담

세 도구의 역할은 다릅니다.

- Swagger: 실제 요청/응답을 눈으로 확인
- pytest: 규칙이 앞으로도 유지되는지 회귀 검증
- 로그: 500 등 런타임 오류의 실제 원인 확인

그래서 운영/검증 흐름은 보통 아래처럼 보는 것이 가장 효율적입니다.

1. Swagger로 응답 확인
2. pytest로 규칙 검증
3. 로그로 실패 원인 확인

## 새 API를 만들 때 권장 사항

새 API를 추가할 때는 Swagger 품질을 위해 아래를 함께 정의하는 것이 좋습니다.

- `response_model`
- `summary`
- `description`
- 요청/응답 예시
- 필요한 경우 에러 응답 예시

이렇게 하면 `/docs`에서 API를 더 쉽게 이해하고 테스트할 수 있습니다.

## 빠른 확인 순서

Swagger에서 먼저 보기 좋은 엔드포인트 예시:

1. `POST /api/v1/auth/login`
2. `GET /api/v1/users/me`
3. `GET /api/v1/strategy/a/tournament`
4. `GET /api/v1/strategy/a/signals`
5. `GET /api/v1/agents/status`
6. `GET /api/v1/portfolio/account-overview`

추천 흐름:

1. 로그인해서 JWT 발급
2. `Authorize`에 토큰 입력
3. Strategy / Agents / Portfolio 순서로 확인
