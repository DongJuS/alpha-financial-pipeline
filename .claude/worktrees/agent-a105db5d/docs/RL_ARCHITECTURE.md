# 🧱 RL_ARCHITECTURE.md — 강화학습 레인 아키텍처

> RL lane의 오프라인 학습, 평가, 정책 적용 경계를 설명합니다.

---

## 1. 아키텍처 원칙

- 학습과 실시간 추론을 분리합니다.
- 평가를 통과하지 않은 정책은 활성화하지 않습니다.
- 실주문은 RL이 아니라 `PortfolioManagerAgent`가 담당합니다.
- 검색/스크래핑에서 생성된 feature는 선택적 입력으로 주입하되, 출처 추적이 가능해야 합니다.

---

## 2. 상위 흐름

```text
CollectorAgent / Portfolio history / Research extractions
    -> RL Dataset Builder
    -> Feature Store / Dataset Version
    -> Trainer
    -> Policy Artifact Registry
    -> Evaluator
    -> Approved Policy
    -> RL Policy Inference
    -> OrchestratorAgent
    -> PortfolioManagerAgent
```

---

## 3. 계층별 책임

### Dataset Builder
- 시계열 정렬
- lookahead leakage 방지
- feature schema/version 부여
- 학습/검증/테스트 구간 분리
- 기본 입력은 Yahoo history seed 일봉 + KIS WebSocket 실시간 tick 조합

### Trainer
- 알고리즘, 보상 함수, 환경 설정 기록
- seed와 하이퍼파라미터 저장
- artifact 생성

### Evaluator
- out-of-sample 성과 측정
- drawdown, turnover, 거래 빈도, 보상 안정성 확인
- 기존 전략 대비 비교 리포트 작성

### Policy Registry
- 활성 정책 후보와 보류 정책 구분
- 평가 보고서와 artifact를 묶어서 조회 가능하게 관리

### Policy Inference
- 승인된 정책만 로드
- 시장 상태와 feature 입력을 받아 signal 후보 생성
- 실행 로그를 남기고 Orchestrator에 전달

---

## 4. 온라인/오프라인 경계

| 구간 | 목적 | 주문 권한 |
|------|------|-----------|
| Offline training | 정책 학습 | 없음 |
| Offline evaluation | 성능/리스크 평가 | 없음 |
| Shadow inference | 실시간 비교 관측 | 없음 |
| Paper trading | 제한된 주문 실험 | `PortfolioManagerAgent`만 가능 |
| Real trading | 운영 주문 | `PortfolioManagerAgent`만 가능 |

---

## 5. 권장 저장 단위

| 엔터티 | 예시 키 |
|--------|---------|
| dataset | `rl_dataset:{version}` |
| training job | `rl_training_job:{job_id}` |
| evaluation report | `rl_eval:{eval_id}` |
| policy | `rl_policy:{policy_id}` |
| inference run | `rl_inference:{run_id}` |

실제 저장소는 PostgreSQL, object storage, Redis 조합으로 구현할 수 있으나, 메타데이터와 감사 로그는 조회 가능한 형태로 유지해야 합니다.

---

## 6. Orchestrator 연결 원칙

- Orchestrator는 RL lane을 별도 signal source로 호출할 수 있습니다.
- RL inference 실패 시 코어 Strategy A/B 경로는 유지되어야 합니다.
- RL signal이 없더라도 시스템 전체 거래 루프는 계속 동작해야 합니다.

---

*Last updated: 2026-03-14*
