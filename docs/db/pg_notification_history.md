> 정책: 항상 200줄 이내를 유지한다.

# notification_history

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `notification_history` |
| 역할 | 알림 발송 이력. Telegram 등 외부 채널 발송 성공/실패 기록. |
| 사용 여부 | ✅ 활성 — notifier_agent에서 발송마다 기록 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| event_type | VARCHAR(30) | 이벤트 유형 |
| message | TEXT | 알림 메시지 |
| sent_at | TIMESTAMPTZ | 발송 시각 |
| success | BOOLEAN | 발송 성공 여부 |
| error_msg | TEXT | 실패 시 에러 메시지 |

## 테이블 관계

- 독립 로그 테이블 (FK 없음)
