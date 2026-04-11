from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings, get_current_user
from src.api.routers import (
    audit,
    auth,
    backtest,
    feedback,
    scheduler,
    strategy,
)


def build_docs_client() -> TestClient:
    app = FastAPI(
        title="Docs Test API",
        openapi_tags=[
            {"name": "auth", "description": "JWT 로그인 및 현재 사용자 조회"},
            {"name": "strategy", "description": "Strategy A/B 시그널, 토너먼트, 토론 transcript 조회"},
        ],
    )
    app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
    app.include_router(strategy.router, prefix="/api/v1/strategy", tags=["strategy"])
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(jwt_secret="test-secret")
    return TestClient(app)


def build_full_docs_client() -> TestClient:
    """모든 라우터를 포함한 OpenAPI 스키마 테스트용 클라이언트."""
    app = FastAPI(
        title="Full Docs Test API",
        openapi_tags=[
            {"name": "auth", "description": "JWT 로그인 및 현재 사용자 조회"},
            {"name": "strategy", "description": "Strategy A/B 시그널"},
            {"name": "audit", "description": "실거래/운영 감사 이력"},
            {"name": "feedback", "description": "전략 피드백 수집 및 조회"},
            {"name": "backtest", "description": "백테스트 실행 결과 조회"},
            {"name": "scheduler", "description": "통합 스케줄러 상태"},
        ],
    )
    app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
    app.include_router(strategy.router, prefix="/api/v1/strategy", tags=["strategy"])
    app.include_router(audit.router, prefix="/api/v1/audit", tags=["audit"])
    app.include_router(feedback.router, prefix="/api/v1/feedback", tags=["feedback"])
    app.include_router(backtest.router, prefix="/api/v1/backtest", tags=["backtest"])
    app.include_router(scheduler.router, prefix="/api/v1/scheduler", tags=["scheduler"])
    app.dependency_overrides[get_current_settings] = lambda: SimpleNamespace(jwt_secret="test-secret")

    async def mock_user():
        return {"sub": str(uuid4()), "email": "t@t.com", "name": "T", "is_admin": True}
    app.dependency_overrides[get_current_user] = mock_user

    return TestClient(app)


def test_openapi_includes_bearer_auth_and_login_examples() -> None:
    with build_docs_client() as client:
        schema = client.get("/openapi.json").json()

    security_schemes = schema["components"]["securitySchemes"]
    assert "BearerAuth" in security_schemes
    assert security_schemes["BearerAuth"]["type"] == "http"
    assert security_schemes["BearerAuth"]["scheme"] == "bearer"

    login_schema = schema["components"]["schemas"]["LoginRequest"]
    assert login_schema["example"] == {
        "email": "admin@example.com",
        "password": "admin1234",
    }


def test_openapi_documents_strategy_b_response_schema() -> None:
    with build_docs_client() as client:
        schema = client.get("/openapi.json").json()

    strategy_b_response = schema["paths"]["/api/v1/strategy/b/signals"]["get"]
    assert strategy_b_response["summary"] == "Strategy B 최신 시그널"
    response_ref = strategy_b_response["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert response_ref.endswith("/StrategyBResponse")


# ── 전체 라우터 OpenAPI 스키마 정합성 검증 ────────────────────────────────


def test_openapi_schema_is_valid_json() -> None:
    """OpenAPI 스키마가 유효한 JSON으로 반환된다."""
    with build_full_docs_client() as client:
        resp = client.get("/openapi.json")
    assert resp.status_code == 200
    schema = resp.json()
    assert "openapi" in schema
    assert "paths" in schema
    assert "components" in schema


def test_openapi_has_info_block() -> None:
    """OpenAPI 스키마에 info 블록이 포함된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    assert "info" in schema
    assert "title" in schema["info"]


def test_openapi_audit_endpoints_documented() -> None:
    """audit 라우터 엔드포인트가 OpenAPI에 문서화된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/audit/trail" in paths
    assert "/api/v1/audit/summary" in paths
    assert "get" in paths["/api/v1/audit/trail"]
    assert "get" in paths["/api/v1/audit/summary"]


def test_openapi_feedback_endpoints_documented() -> None:
    """feedback 라우터 엔드포인트가 OpenAPI에 문서화된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    expected_paths = [
        "/api/v1/feedback/accuracy",
        "/api/v1/feedback/llm-context/{strategy}",
        "/api/v1/feedback/backtest",
        "/api/v1/feedback/backtest/compare",
        "/api/v1/feedback/rl/retrain/{ticker}",
        "/api/v1/feedback/rl/retrain-all",
        "/api/v1/feedback/cycle",
    ]
    for path in expected_paths:
        assert path in paths, f"Missing path in OpenAPI: {path}"


def test_openapi_backtest_endpoints_documented() -> None:
    """backtest 라우터 엔드포인트가 OpenAPI에 문서화된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    expected_paths = [
        "/api/v1/backtest/runs",
        "/api/v1/backtest/runs/{run_id}",
        "/api/v1/backtest/runs/{run_id}/daily",
    ]
    for path in expected_paths:
        assert path in paths, f"Missing path in OpenAPI: {path}"


def test_openapi_scheduler_endpoints_documented() -> None:
    """scheduler 라우터 엔드포인트가 OpenAPI에 문서화된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/v1/scheduler/status" in paths
    assert "get" in paths["/api/v1/scheduler/status"]


def test_openapi_all_endpoints_have_responses() -> None:
    """모든 엔드포인트에 responses 블록이 존재한다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    for path, methods in schema["paths"].items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                assert "responses" in details, f"{method.upper()} {path} has no responses"
                assert len(details["responses"]) > 0, f"{method.upper()} {path} has empty responses"


def test_openapi_all_endpoints_have_200_response() -> None:
    """모든 엔드포인트에 200/201/202 성공 응답이 정의된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    success_codes = {"200", "201", "202"}
    for path, methods in schema["paths"].items():
        for method, details in methods.items():
            if method in ("get", "post", "put", "delete", "patch"):
                response_codes = set(details["responses"].keys())
                has_success = bool(response_codes & success_codes)
                assert has_success, f"{method.upper()} {path} has no success response (2xx)"


def test_openapi_schemas_component_exists() -> None:
    """OpenAPI 스키마에 components/schemas가 존재한다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()
    assert "schemas" in schema["components"]
    assert len(schema["components"]["schemas"]) > 0


def test_openapi_feedback_response_models_defined() -> None:
    """feedback 라우터의 응답 모델이 schemas에 정의된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    schemas = schema["components"]["schemas"]
    expected_models = [
        "AccuracyStats",
        "LLMFeedbackContext",
        "BacktestResult",
        "StrategyComparison",
        "RetrainResultItem",
        "RetrainBatchResponse",
        "FeedbackCycleResponse",
    ]
    for model in expected_models:
        assert model in schemas, f"Missing schema: {model}"


def test_openapi_audit_response_models_defined() -> None:
    """audit 라우터의 응답 모델이 schemas에 정의된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    schemas = schema["components"]["schemas"]
    expected_models = [
        "AuditTrailResponse",
        "AuditSummary",
    ]
    for model in expected_models:
        assert model in schemas, f"Missing schema: {model}"


def test_openapi_backtest_endpoints_have_responses_defined() -> None:
    """backtest 라우터의 엔드포인트에 응답이 정의된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    paths = schema["paths"]
    # backtest/runs 엔드포인트의 GET 응답이 정의되어 있는지 확인
    runs_get = paths["/api/v1/backtest/runs"]["get"]
    assert "200" in runs_get["responses"]

    # runs/{run_id} 상세 조회
    run_detail = paths["/api/v1/backtest/runs/{run_id}"]["get"]
    assert "200" in run_detail["responses"]

    # runs/{run_id}/daily 일별 스냅샷
    daily_get = paths["/api/v1/backtest/runs/{run_id}/daily"]["get"]
    assert "200" in daily_get["responses"]


def test_openapi_scheduler_response_models_defined() -> None:
    """scheduler 라우터의 응답 모델이 schemas에 정의된다."""
    with build_full_docs_client() as client:
        schema = client.get("/openapi.json").json()

    schemas = schema["components"]["schemas"]
    expected_models = [
        "SchedulerStatusResponse",
        "JobInfo",
    ]
    for model in expected_models:
        assert model in schemas, f"Missing schema: {model}"
