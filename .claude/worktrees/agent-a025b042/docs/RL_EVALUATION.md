# 📊 RL_EVALUATION.md — 강화학습 평가 기준

> RL 정책을 shadow, paper, 실거래 후보로 승격하기 위한 평가 기준을 정리합니다.

---

## 1. 평가 목적

- 학습 성과를 단순 수익률이 아니라 리스크 포함 지표로 검증
- 기존 Strategy A/B와 비교 가능한 기준 확보
- 승격 여부를 사람이 아닌 규칙 기반으로 설명 가능하게 유지

---

## 2. 평가 레벨

### Level 1. Offline 학습 검증
- reward 안정성
- policy collapse 여부
- feature 누락/누수 여부
- 동일 설정 재학습 시 성과 재현성

### Level 2. Out-of-sample / Walk-forward
- 훈련 구간 밖 성과
- 시장 체 regime 변화 구간에서의 성능 하락 폭
- 거래 횟수와 turnover의 과도한 증가 여부

### Level 3. Shadow Inference
- 실시간 입력에서 정상적으로 signal 생성 가능
- latency와 실패율 측정
- 기존 Strategy A/B와의 괴리 분석

### Level 4. Paper Trading
- 실제 주문 없이 끝나지 않고 paper 계좌에서 리스크 가드 통과 여부 확인
- 일손실 제한, 포지션 한도, 거래 가능 시간 규칙 준수

---

## 3. 핵심 지표

| 범주 | 지표 |
|------|------|
| 수익성 | cumulative return, average daily return, hit ratio |
| 리스크 | max drawdown, volatility, downside deviation |
| 효율성 | Sharpe/Sortino 유사 지표, turnover, holding period |
| 운영성 | inference latency, failure rate, missing feature ratio |
| 비교성 | Strategy A/B 대비 relative performance, conflict rate |

---

## 4. 승격 게이트

정책은 아래 순서로만 승격할 수 있습니다.

1. Offline 평가 통과
   최소 out-of-sample 수익률 `5%` 이상, max drawdown `-15%` 이내
2. Walk-forward 평가 통과
3. Shadow inference 안정성 통과
4. Paper trading 기준 통과
5. 운영 감사와 문서 업데이트 완료

하나라도 실패하면 다음 단계로 진행하지 않습니다.

---

## 5. 실패 조건 예시

- drawdown이 기존 허용 한도를 반복적으로 초과
- out-of-sample 성과가 학습 구간 대비 급격히 붕괴
- 특정 feature 또는 검색 데이터가 없을 때 추론 실패율이 높음
- paper 운영에서 리스크 가드 차단이 과도하게 빈번함

---

## 6. 보고서 최소 항목

평가 결과는 최소한 아래 항목을 포함해야 합니다.

- 평가 대상 policy id / dataset version
- 기간별 수익률 및 drawdown
- benchmark: Strategy A, Strategy B, blend
- 거래 빈도와 turnover
- 실패 사례와 주요 원인
- 승격 결정 (`approved`, `hold`, `rejected`)

---

*Last updated: 2026-03-14*
