from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.deps import get_current_settings
from src.api.routers import auth, strategy


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
