# Cloudflare R2 — 구독 내역

- **서비스:** Cloudflare R2 Object Storage
- **활성화 일자:** 2026-04-16
- **상태:** Active (Purchase complete)
- **월 요금:** **$0 / month** (무료 티어)
- **최초 결제:** **$0 / month** (Due today)
- **용도:** S3 호환 Object Storage. 프로젝트 데이터레이크(일봉/분봉/틱 Parquet) 저장.

## 무료 티어 포함 항목 (Included features)

S3-compatible object storage with **zero egress fees**.

| 항목 | 무료 한도 |
|------|----------|
| R2 Storage | **10 GB / month** |
| Class A operations (쓰기: PUT, POST, LIST 등) | **1,000,000 / month** (100만 건) |
| Class B operations (읽기: GET, HEAD 등) | **10,000,000 / month** (1,000만 건) |

## 초과 요율 (Overage rates)

무료 한도 초과 시 아래 요율로 종량 과금.

| 항목 | 요율 |
|------|------|
| R2 Storage | **$0.015 / GB-month** |
| Class A operations | **$4.50 / million** (100만 건당 $4.50) |
| Class B operations | **$0.36 / million** (100만 건당 $0.36) |
| Egress (데이터 외부 전송) | **$0** (무료, Zero Egress) |

## 예상 사용량 (현재 규모 기준)

| 항목 | 예상량 | 무료 한도 대비 |
|------|--------|----------------|
| Storage (Parquet 압축 후) | ~1~2 GB/월 | 여유 8~9 GB |
| Class A (일봉/분봉/틱 쓰기) | ~10~50만/월 | 여유 |
| Class B (읽기: RL 학습/백테스트) | ~100~500만/월 | 여유 |

**결론:** 현재 모의투자·3종목 규모에서는 **무료 티어 내에서 $0 유지 가능**.
종목이 100개 이상으로 확장되거나 틱 아카이브 정책이 변경될 때 재산정 필요.

## 과금 트리거 모니터링

- **10 GB 스토리지 임박 시** → Lifecycle Rule로 오래된 틱 데이터 IA/Glacier 전환 또는 삭제
- **Class A 100만 건 임박 시** → 쓰기 배치화 (개별 Put → 묶음 Put) 검토
- Cloudflare 대시보드 → Billing → Notifications에서 $1, $5 알림 설정 권장

## 버킷 정보

- **Bucket name:** `alpha-datalake`
- **Location:** APAC (Asia-Pacific)
- **S3 Endpoint:** `.env`의 `S3_ENDPOINT_URL` 참조 (git에 커밋 금지)
- **API Token:** `.env`의 `S3_ACCESS_KEY` / `S3_SECRET_KEY` (git에 커밋 금지)

## 해지·변경 조건

- **해지 절차:** Cloudflare 대시보드 → R2 → Manage → Cancel Subscription
- **데이터 보존:** 구독 해지 후 버킷/객체는 계정에 남음. 별도로 삭제 필요
- **요금제 변경:** 무료 티어 외 유료 플랜 없음 (종량제만 존재)

## 참고

- 공식 가격표: https://developers.cloudflare.com/r2/pricing/
- 프로젝트 내 R2 관련 코드: `src/utils/s3_client.py` (ensure_bucket R2 graceful 처리)
- 환경변수 설정: `.env.example` L36~40
