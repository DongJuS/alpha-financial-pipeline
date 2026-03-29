# Strategy A signals API 500 에러 → 해결

> 생성일: 2026-03-29
> 상태: 해결

---

## 증상

`GET /api/v1/strategy/a/signals` 호출 시 `500 Internal Server Error` 반환.

## 원인

`src/api/routers/strategy.py:243`에서 SQL 파라미터 바인딩 오류:
- `date` 파라미터가 None일 때 쿼리에 `$1`이 포함되지만 인자는 0개 전달
- `asyncpg.InterfaceError: the server expects 1 argument for this query, 0 were passed`

```python
# Before (버그)
AND p.trading_date = {date_filter if date else '$1'}::date
# date_filter = "CURRENT_DATE" 지만, date가 None이면 else '$1' → $1이 들어가면서 인자 0개

# After (수정)
AND p.trading_date = {'$1' if date else 'CURRENT_DATE'}::date
```

## 해결

`strategy.py:243` 조건 반전: date가 있으면 `$1`, 없으면 `CURRENT_DATE`.

---

*작성: 2026-03-29*
