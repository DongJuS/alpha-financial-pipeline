# 테스트 스위트 기존 실패 47건 (2026-03-29)

> e2e 테스트 중 발견. 우리 변경(unified_scheduler)과 무관한 기존 이슈.
> Python 3.9 환경(시스템 python)에서 실행, DB/Redis 미연결 상태.

---

## 분류 요약

| 원인 | 건수 | 우선순위 |
|------|------|----------|
| Python 3.9 `X \| None` 문법 비호환 | 8 | 높음 — `from __future__ import annotations` 누락 |
| pytest-asyncio event loop 이슈 | 14 | 중간 — pytest-asyncio 0.26 + Py3.9 조합 |
| API/모델 변경 후 테스트 미업데이트 | 17 | 높음 — 코드와 테스트 간 불일치 |
| DB 미연결 (PostgreSQL) | 3 | 낮음 — 환경 의존, CI에서만 실행 |
| 수집 오류 (import, 4개) | 5 | 중간 — collection 단계에서 실패 |

---

## 1. Python 3.9 `X | None` 문법 비호환 (8건)

**원인:** Python 3.10+ union 문법(`dict[str, X] | None`)을 3.9에서 사용. `from __future__ import annotations` 없으면 `TypeError: unsupported operand type(s) for |`

**파일:**
- `test/test_rl_policy_registry.py:38` — `created_at: datetime | None = None`
- `test/test_search_runner.py:33` — `dict[str, ResearchOutput] | None = None`
- `test/test_search_runner_integration.py:32` — 동일
- `test/test_blend_nway.py` — 5건 (TestStrategyRegistry 전체)
  - `test_empty_registry_returns_empty`
  - `test_failing_runner_returns_empty`
  - `test_run_all`
  - `test_run_selected`
  - `test_run_selected_missing_strategy`

**해결 방향:** 각 테스트 파일 상단에 `from __future__ import annotations` 추가, 또는 `Optional[X]` 문법으로 변경.

---

## 2. pytest-asyncio event loop 이슈 (14건)

**원인:** `RuntimeError: There is no current event loop in thread 'MainThread'`. pytest-asyncio 0.26 + Python 3.9 조합에서 event loop 생성 정책 불일치.

**파일:**
- `test/test_blend_nway.py` — 5건 (위 1번과 중복)
- `test/test_strategy_promotion.py` — 5건
  - `test_invalid_promotion_path_returns_not_ready`
  - `test_promotion_not_ready_insufficient_days`
  - `test_promotion_ready`
  - `test_promote_fails_without_force`
  - `test_promote_succeeds_with_force`
- `test/unit/test_blog_client.py` — 6건
  - `test_refresh_access_token`
  - `test_publish_success`
  - `test_publish_retry_on_401`
  - `test_publish_draft`
  - `test_find_existing`
  - `test_find_not_found`
- `test/test_data_pipeline.py` — 3건
  - `test_fetch_historical_daily_basic`
  - `test_fetch_historical_daily_empty`
  - `test_check_data_exists_returns_count`

**해결 방향:** `pytest.ini`에 `asyncio_mode = auto` 확인, 또는 각 테스트에 `@pytest.mark.asyncio` 명시적 추가. Python 3.11+ 환경에서는 자연 해결 가능.

---

## 3. API/모델 변경 후 테스트 미업데이트 (17건)

### 3a. Phase 9 RL 인터페이스 변경 (6건)

**파일:** `test/test_phase9_rl.py`
- `test_technical_features_calculation` — `TechnicalFeatures.compute()` 제거됨
- `test_technical_features_insufficient_data` — 동일
- `test_enriched_dataset_state_vector` — `__init__()` 인자 변경 (`return_1d` 미지원)
- `test_reset` — `TradingEnv.__init__()` 인자 변경 (`closes` 미지원)
- `test_step_hold` — 동일
- `test_full_episode` — 동일
- `test_buy_sell_sequence` — 동일

**원인:** RL V2 리팩토링 후 V1 테스트가 업데이트 안 됨.

### 3b. Orchestrator 인터페이스 변경 (3건)

**파일:** `test/test_orchestrator_independent.py`
- `test_run_cycle_exists` — `run_cycle` 메서드 시그니처/위치 변경
- `test_send_promotion_alert_in_notifier` — `NotifierAgent.send_promotion_alert()` 미존재
- `test_cli_independent_portfolio_uses_action_store_true` — CLI argparse 구조 변경

### 3c. RL Trading V1 호환성 (2건)

**파일:** `test/test_rl_trading.py`
- `test_orchestrator_bootstrap_loads_rl_registry_snapshot` — `__init__(use_rl=...)` 미지원
- `test_orchestrator_rl_mode_runs_training_and_routes_rl_orders` — 동일

### 3d. 설정값 변경 (4건)

- `test/test_aggregate_risk.py::test_custom_limits` — `30.0 != 50.0` (기본 리스크 한도 변경)
- `test/test_virtual_slippage.py::test_custom_slippage` — `5 != 25`
- `test/test_virtual_slippage.py::test_default_config` — `5 != 10`
- `test/test_strategy_promotion.py::test_criteria_override` — `30 != 10`

### 3e. 기타 인터페이스 불일치 (2건)

- `test/test_model_config_api.py::test_get_model_config_groups_strategy_rows` — `ProviderStatusItem`에 `mode` 필드 추가됨
- `test/test_model_config_api.py::test_update_model_config_returns_updated_rows` — 동일
- `test/test_gen_pipeline_e2e.py::test_collect_daily_bars_pipeline` — `gen_collector.store_daily_bars` 속성 제거됨
- `test/test_llm_cli_bridge.py::test_build_cli_command_replaces_model_placeholder` — `/bin/echo` vs `echo` 하드코딩

### 3f. market_hours 인터페이스 변경 (6건)

**파일:** `test/test_market_hours.py` — 전 6건
- `ensure_holidays_cached` 함수가 `market_hours` 모듈에서 제거/이동됨

---

## 4. DB 미연결 (3건)

**파일:**
- `test/test_portfolio_manager.py::test_process_predictions_executes_both_paper_and_real_when_enabled`
- `test/test_risk_validation.py::test_run_risk_rule_validation_passes`

**원인:** `OSError: Connect call failed ('127.0.0.1', 5432)` — 로컬 PostgreSQL 미실행.

**해결 방향:** CI 환경에서만 실행하도록 `@pytest.mark.integration` 마크 추가, 또는 DB mock 적용.

---

## 5. 수집 단계 오류 (5건)

`--ignore`로 제외한 파일들:
- `test/test_auth_regression.py` — `os.environ["DATABASE_URL"]` 직접 참조 (KeyError)
- `test/test_datalake_rl_episodes.py` — 미확인 (기존 제외 대상)
- `test/test_rl_policy_registry.py` — 3.9 문법 (1번과 중복)
- `test/test_search_pipeline.py` — `ExtractionResult` import 실패
- `test/test_search_runner.py` / `test_search_runner_integration.py` — 3.9 문법 (1번과 중복)

---

## 해결 현황

### PR #45 (2026-03-29): 1차 정비 — 462→512 passed

| 카테고리 | 원래 건수 | 해결 | 잔여 |
|---|---|---|---|
| Python 3.9 문법 | 8 | **8** ✅ | 0 |
| API/모델 인터페이스 불일치 | 17 | **17** ✅ | 0 |
| 수집 오류 | 5 | **4** | 1 |

### PR #50 (2026-03-29): 완전 정비 — 512→557 passed, **0 failed**

| 카테고리 | 잔여 | 해결 | 방법 |
|---|---|---|---|
| pytest-asyncio event loop 오염 | 32건 | **32** ✅ | conftest.py deprecated `event_loop` fixture 제거 + `IsolatedAsyncioTestCase` 전환 |
| test_search_pipeline import 오류 | 1건 | **1** ✅ | SearchAgent 현재 인터페이스에 맞게 전면 재작성 |
| DB 미연결 | 3건 | **3** ✅ | `@pytest.mark.integration` 마킹 (deselected) |

**최종: 557 passed, 0 failed, 2 skipped, 5 deselected (integration)**

### 근본 원인과 해결

**event loop 오염 (가장 큰 문제):**
- **원인:** `conftest.py`의 session-scoped `event_loop` fixture가 pytest-asyncio 0.26에서 deprecated됨. `IsolatedAsyncioTestCase`가 자체 loop를 만드는데, session loop와 충돌하여 "no current event loop" 에러 cascade 발생.
- **해결:** `event_loop` fixture 제거 + `asyncio.run()` 직접 호출을 `IsolatedAsyncioTestCase` + `await`로 전환.
- **영향 파일:** conftest.py, test_blend_nway.py, test_aggregate_risk.py, test_strategy_promotion.py, test_data_pipeline.py, test_rl_bootstrap.py

**SearchAgent 인터페이스 변경 (test_search_pipeline.py):**
- **원인:** `FetchResult`, `ExtractionResult` 클래스가 src에서 제거됨. `SearchAgent.__init__`에서 `searxng_client=` 인자 제거됨. `_extract_structured()`, `_fetch_pages()` 메서드 제거됨.
- **해결:** 삭제된 모델을 테스트 내 로컬 dataclass로 정의. SearchAgent 테스트를 `patch.object(agent, "_searxng")` 방식으로 재작성.

---

*작성: 2026-03-29, 업데이트: 2026-03-29 (PR #45 반영)*
