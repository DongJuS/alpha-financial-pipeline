> 정책: 항상 200줄 이내를 유지한다.

# MinIO 데이터 레이크

| 항목 | 내용 |
|------|------|
| 종류 | MinIO (S3 호환 오브젝트 스토리지) |
| DB | minio:9000 |
| 버킷 | `alpha-lake` |
| 역할 | 콜드 데이터 아카이브. Parquet(Snappy 압축) 형식으로 장기 보존. |
| 사용 여부 | ✅ 활성 — datalake_service에서 적재 |

## 오브젝트 경로 패턴

| 경로 | 용도 |
|------|------|
| `daily_bars/date=YYYY-MM-DD/` | 일봉 OHLCV Parquet |
| `predictions/date=YYYY-MM-DD/` | 예측 시그널 Parquet |
| `orders/date=YYYY-MM-DD/` | 주문 기록 Parquet |
| `blend_results/date=YYYY-MM-DD/` | 블렌딩 결과 Parquet |

## 테이블 관계

- ← PostgreSQL `ohlcv_daily` → 일봉 아카이브
- ← PostgreSQL `predictions` → 예측 아카이브
- ← PostgreSQL `broker_orders` → 주문 아카이브
- 읽기: datalake_service에서 S3 GET → Parquet → pandas DataFrame
