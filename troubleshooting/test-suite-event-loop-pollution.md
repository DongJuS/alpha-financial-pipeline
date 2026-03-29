# 테스트 스위트 event loop 오염 (32건) ✅ 해결

> 생성일: 2026-03-29
> **해결일: 2026-03-29 (PR #50)**
> 상태: **해결 완료**
> 관련 PR: #45 (1차), #50 (완전 해결)

---

## 증상

전체 테스트(`python3.11 -m pytest test/`)를 실행하면 32건이 `RuntimeError: There is no current event loop in thread 'MainThread'`로 실패하지만, 해당 파일만 독립 실행하면 **전부 통과**한다.

```bash
# 전체 실행 → 실패
python3.11 -m pytest test/ --ignore=test/test_search_pipeline.py
# 512 passed, 38 failed

# 독립 실행 → 통과
python3.11 -m pytest test/test_schedulers.py test/test_scheduler_market_flow.py test/unit/test_blog_client.py
# 39 passed
```

## 영향 파일 (32건)

- `test/test_scheduler_market_flow.py` — 17건
- `test/test_schedulers.py` — 9건
- `test/unit/test_blog_client.py` — 6건

## 원인

1. `unittest.TestCase` 내에서 `asyncio.run()`을 호출하는 테스트가 있음 (`test_blend_nway.py`, `test_aggregate_risk.py`, `test_strategy_promotion.py` 등)
2. `asyncio.run()`은 **새 event loop를 생성하고 실행 후 닫음**
3. 닫힌 loop가 이후 `pytest-asyncio`가 관리하는 loop를 오염시킴
4. 이후 실행되는 `@pytest.mark.asyncio` 테스트들이 닫힌 loop를 참조하여 `RuntimeError` 발생

## 시도한 대응

1. `conftest.py`에서 `pytest_configure`에 event loop 사전 생성 → 부분 개선
2. `pytest.ini`에 `asyncio_default_fixture_loop_scope = session` 추가 → 효과 없음
3. `event_loop` 픽스처에서 `asyncio.set_event_loop(loop)` 호출 → 부분 개선
4. `asyncio.run()` → `asyncio.get_event_loop().run_until_complete()` 변환 시도 → 이미 실행 중인 loop에서 호출 불가 에러 발생

## 근본 해결 방안

### 방안 1: `asyncio.run()` 사용 테스트를 `async def`로 전환 (권장)
```python
# Before (unittest.TestCase)
class TestBlending(unittest.TestCase):
    def test_run_all(self):
        results = asyncio.run(reg.run_all(["005930"]))

# After (IsolatedAsyncioTestCase 또는 pytest native)
class TestBlending(unittest.IsolatedAsyncioTestCase):
    async def test_run_all(self):
        results = await reg.run_all(["005930"])
```

### 방안 2: pytest-asyncio 0.23+ 업그레이드
pytest-asyncio 0.23 이후 `loop_scope` 관리가 개선됨. 현재 0.26인데 `asyncio_mode=auto`와 `unittest.TestCase`의 조합이 문제.

### 방안 3: 테스트 실행 순서 격리
```bash
# asyncio.run() 사용 테스트를 먼저, @pytest.mark.asyncio 테스트를 나중에
python3.11 -m pytest test/ -p no:randomly --import-mode=importlib
```

## 관련 테스트 목록

`asyncio.run()` 호출 파일 (오염 원인):
- `test/test_blend_nway.py` (5건)
- `test/test_aggregate_risk.py` (4건)
- `test/test_strategy_promotion.py` (5건)
- `test/test_data_pipeline.py` (3건)
- `test/test_rl_bootstrap.py` (7건)

---

*작성: 2026-03-29*
