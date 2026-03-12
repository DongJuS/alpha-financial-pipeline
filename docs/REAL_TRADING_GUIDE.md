# 실거래 전환 운영 가이드

## 1. 기본 원칙
- 기본 모드는 항상 페이퍼 트레이딩(`is_paper=true`)입니다.
- 실거래 전환은 readiness 통과 + 확인 코드 일치가 모두 필요합니다.
- 전환/차단 시도는 `real_trading_audit`에 모두 기록됩니다.

## 2. 전환 전 필수 점검
1. 최근 30일 이상 페이퍼 트레이딩 이력 확보 (`READINESS_REQUIRED_PAPER_DAYS`)
2. 리스크 규칙 검증 통과 (`scripts/validate_risk_rules.py`)
3. 저장소 보안 감사 통과 (`scripts/security_audit.py`)
4. Telegram 경보 채널 확인
5. KIS 실거래 계좌 잔고/권한 확인

## 3. Docker 기준 점검 절차
```bash
# 서비스 기동
docker compose up -d postgres redis api worker

# 스키마 반영
docker compose run --rm api python scripts/db/init_db.py

# 운영 감사 + readiness 점검(기본: 감사 포함)
docker compose run --rm api python scripts/preflight_real_trading.py

# 감사만 개별 재실행
docker compose run --rm api python scripts/security_audit.py
docker compose run --rm api python scripts/validate_risk_rules.py
```

## 4. 실거래 전환 실행
1. 관리자 로그인 후 JWT 발급
2. `POST /portfolio/trading-mode` 호출

요청 예시:
```json
{
  "is_paper": false,
  "confirmation_code": "<REAL_TRADING_CONFIRMATION_CODE>"
}
```

차단 조건:
- confirmation_code 불일치
- readiness 항목 중 `critical` 또는 `high` 실패

## 5. 롤백 절차
- 즉시 페이퍼 모드로 복귀:
```json
{
  "is_paper": true,
  "confirmation_code": "<REAL_TRADING_CONFIRMATION_CODE>"
}
```
- 이후 `real_trading_audit`/`operational_audits` 로그를 확인해 원인 정리

## 6. 권장 운영 루틴
- 매일 장 종료 후:
  1. `scripts/security_audit.py`
  2. `scripts/validate_risk_rules.py`
  3. `scripts/preflight_real_trading.py --skip-audits` (최종 readiness 재확인)
- 감사 로그(`operational_audits`)의 최신 성공 이력이 7일 이내인지 유지
