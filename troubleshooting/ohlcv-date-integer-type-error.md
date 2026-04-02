# ohlcv_daily DATE - integer 타입 불일치

> 발생일: 2026-03-30
> 상태: 해결 (PR #78)

---

## 증상

RL 부트스트랩에서 `fetch_recent_market_data` 호출 시:
```
operator does not exist: date >= integer
HINT: No operator matches the given name and argument types
```

## 원인

기존 `market_data` 테이블은 `timestamp_kst TIMESTAMPTZ` → `CURRENT_DATE - $N` (integer) 연산 가능.
신규 `ohlcv_daily` 테이블은 `traded_at DATE` → `DATE - integer`는 PostgreSQL에서 지원 안 됨.

```sql
-- 이전 (동작함): TIMESTAMPTZ - integer
WHERE timestamp_kst >= CURRENT_DATE - $2

-- 신규 (실패): DATE - integer
WHERE traded_at >= CURRENT_DATE - $2  -- ❌ operator does not exist
```

## 해결

```sql
-- DATE - N * INTERVAL '1 day'로 변환
WHERE traded_at >= CURRENT_DATE - $2 * INTERVAL '1 day'
```

## 영향

`src/db/queries.py`의 `fetch_recent_market_data` 1줄 수정.

---
