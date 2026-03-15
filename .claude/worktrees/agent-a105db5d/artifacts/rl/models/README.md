# RL 모델 저장소

종목별/알고리즘별 Q-learning 정책을 관리합니다.

## 디렉토리 구조

```
artifacts/rl/models/
├── tabular/                    # Tabular Q-Learning 정책
│   ├── 259960.KS/
│   │   └── rl_259960.KS_<timestamp>.json
│   ├── 005930/
│   │   └── rl_005930_<timestamp>.json
│   └── EURUSD_TRUEFX/
│       └── rl_EURUSD_TRUEFX_<timestamp>.json
├── dqn/
│   └── samples/                # Git 추적 허용 샘플 가중치/예제
├── ppo/
│   └── samples/                # Git 추적 허용 샘플 가중치/예제
├── registry.json               # 통합 인덱스 (활성 정책 포인터 포함)
└── README.md
```

## 핵심 파일

- `registry.json` — 모든 정책의 메타데이터 통합 인덱스. Orchestrator 부팅 시 이 파일만 로드하면 전체 활성 정책을 파악할 수 있습니다.
- `src/agents/rl_policy_registry.py` — PolicyRegistry Pydantic 모델
- `src/agents/rl_policy_store_v2.py` — RLPolicyStoreV2 (저장/로드/승격/정리)

## 정책 JSON 스키마

```json
{
  "policy_id": "rl_259960.KS_20260314T061942Z",
  "ticker": "259960.KS",
  "algorithm": "tabular_q_learning",
  "state_version": "qlearn_v2",
  "evaluation": {
    "total_return_pct": 47.84,
    "baseline_return_pct": -26.58,
    "excess_return_pct": 74.41,
    "max_drawdown_pct": -38.21,
    "trades": 178,
    "win_rate": 0.51,
    "approved": true
  },
  "q_table": { ... }
}
```

## 활성 정책 관리

`registry.json`의 `tickers.<ticker>.active_policy_id`가 현재 추론에 사용할 정책을 지정합니다.

## Git 추적 정책

- `registry.json`과 이 `README.md`는 Git으로 관리합니다.
- tabular 정책 JSON 및 Q-table 본문은 기본적으로 Git ignore 대상입니다.
- 향후 neural 계열 예제 파일은 `dqn/samples/`, `ppo/samples/` 하위에만 샘플 형태로 버전 관리합니다.
- 실제 대용량 학습 가중치/체크포인트는 계속 Git 밖에서 관리하는 것을 기본 원칙으로 합니다.

승격 조건:
- `approved == true`
- `return_pct > 현재 활성 정책의 return_pct`
- `max_drawdown_pct >= -50%`
- paper 환경에서만 자동 승격, real 환경은 수동 승인 필수

## 자동 정리 규칙

- 미승인 정책: 생성 후 30일 경과 시 삭제 (최근 실패 1개 보존)
- 승인 정책: 종목당 최대 5개 보존 (활성 정책 제외)
- 활성 정책: 삭제 불가

실행: `python scripts/cleanup_rl_policies.py --execute`

## 마이그레이션

레거시 구조(`artifacts/rl/*.json`)에서 새 구조로 전환:
```bash
python scripts/migrate_rl_policies.py --execute --clean
```
