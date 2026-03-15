# 🤖 RL_TRADING.md — 강화학습 트레이딩 확장 개요

> 이 문서는 RL Trading을 기존 멀티 에이전트 트레이딩 시스템에 어떻게 편입할지 설명합니다.

---

## 1. 목표와 상태

RL Trading은 기존 Strategy A / Strategy B를 대체하지 않습니다.
현재 상태는 운영 기능이 아니라 구조 편입과 통합 테스트 진행 단계입니다.

목표:
- 시장 데이터와 연구 데이터를 활용한 별도 signal lane 추가
- 오프라인 학습, 평가, 정책 관리, inference를 분리
- 기존 PortfolioManager 중심의 주문 통제 구조 유지

---

## 2. 절대 원칙

- RL 정책은 직접 브로커를 호출하지 않습니다.
- 최종 주문 권한은 계속 `PortfolioManagerAgent`에만 있습니다.
- RL 신호도 기존 리스크 규칙과 시장 시간 정책을 그대로 통과해야 합니다.
- RL 평가는 학습과 분리되어야 하며, 실시간 운영 전 shadow 또는 paper 단계 검증이 선행되어야 합니다.

---

## 3. RL lane 구성요소

| 구성요소 | 설명 |
|----------|------|
| `rl_data_builder_agent` | 시장/포트폴리오/연구 추출 데이터를 RL feature dataset으로 변환 |
| `rl_trainer_agent` | 환경 설정과 하이퍼파라미터를 받아 정책 학습 실행 |
| `rl_evaluator_agent` | 백테스트, walk-forward, 리스크 지표 평가 수행 |
| `rl_policy_agent` | 승인된 정책만 로드해 inference 전용 signal 후보 생성 |

이 네 계층은 각각 독립적으로 기록과 재실행이 가능해야 하며, 결과물은 versioned artifact로 남겨야 합니다.

---

## 4. 데이터 입력

RL Trading은 아래 입력을 사용할 수 있습니다.

- Yahoo Finance 기반 history seed 일봉 데이터
- KIS WebSocket 기반 장중 tick 시세
- 기존 포트폴리오 상태와 체결 이력
- Strategy A / B의 과거 의사결정 결과
- Search/Scraping 파이프라인에서 생성된 구조화 feature
- 휴장일, 거래 가능 시간, 리스크 제한 같은 운영 제약

입력 데이터는 학습 시점과 평가 시점을 구분해 누수(leakage)를 막아야 합니다.
현재 기본 RL 경로는 `Yahoo history seed -> KIS WebSocket 실시간 tick`입니다.

---

## 5. 실행 흐름

```text
market_data + portfolio_state + research_features
    -> rl_data_builder_agent
    -> rl_trainer_agent
    -> rl_evaluator_agent
    -> approved_policy_registry
    -> rl_policy_agent (inference only)
    -> OrchestratorAgent
    -> PortfolioManagerAgent
```

중요한 점:
- `rl_policy_agent`는 signal 후보만 만듭니다.
- 실제 주문 여부는 기존 blend/risk gate와 `PortfolioManagerAgent`가 결정합니다.

---

## 6. 기존 전략과의 관계

- Strategy A는 계속 토너먼트 기반 시그널을 생산합니다.
- Strategy B는 계속 토론 기반 시그널을 생산합니다.
- RL은 세 번째 signal source가 될 수 있지만, 초기에는 shadow 또는 paper-only 운영이 기본값입니다.
- RL의 성과가 좋아도 Strategy A/B를 즉시 제거하지 않습니다.

---

## 7. 통합 단계

1. 데이터셋 builder와 simulator를 먼저 고정합니다.
2. 학습 job과 평가 job을 분리해 기록합니다.
3. 정책 레지스트리와 활성 정책 조회 경로를 추가합니다.
4. shadow inference를 통해 기존 전략과 나란히 비교합니다.
5. paper 환경 통과 후에만 signal source로 승격합니다.

---

## 8. 산출물

RL lane은 최소한 아래 결과물을 남겨야 합니다.

- dataset version
- feature schema version
- training config
- model artifact hash/location
- evaluation report
- promotion decision
- inference run log

---

*Last updated: 2026-03-14*
