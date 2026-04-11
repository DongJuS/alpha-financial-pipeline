> 정책: 항상 200줄 이내를 유지한다.

# debate_transcripts

| 항목 | 내용 |
|------|------|
| 종류 | PostgreSQL |
| DB | alpha_db |
| 테이블 | `debate_transcripts` |
| 역할 | Strategy B 합의 토론 전문. Proposer → Challenger ×2 → Synthesizer 구조. |
| 사용 여부 | ✅ 활성 — strategy_b에서 토론 결과 저장 |

## 주요 컬럼

| 컬럼 | 타입 | 설명 |
|------|------|------|
| id | BIGSERIAL PK | 자동 증가 |
| trading_date | DATE | 매매일 |
| ticker | VARCHAR(10) | 종목코드 |
| rounds | INTEGER | 토론 라운드 수 |
| consensus_reached | BOOLEAN | 합의 도달 여부 |
| final_signal | VARCHAR(10) | BUY / SELL / HOLD |
| confidence | NUMERIC(4,3) | 합의 신뢰도 |
| proposer_content | TEXT | 제안자 발언 (lz4 압축) |
| challenger1/2_content | TEXT | 반론자 발언 (lz4 압축) |
| synthesizer_content | TEXT | 종합자 발언 (lz4 압축) |

## 테이블 관계

- ← `predictions(debate_transcript_id)` 논리적 참조
