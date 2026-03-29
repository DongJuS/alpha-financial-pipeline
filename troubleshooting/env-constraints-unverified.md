# 환경 제약으로 미검증 항목 (2026-03-29)

> 로컬 개발 환경(macOS, Python 3.9, Docker/K8s 미실행)의 제약으로
> 실제 동작을 확인하지 못한 항목. 프로덕션/CI 환경에서 반드시 검증 필요.

---

## 1. Docker 컨테이너 내 LLM 인증 경로

**변경 파일:** `src/llm/gemini_client.py`, `src/llm/claude_client.py`

**미검증 사항:**
- K8s secret mount 경로(`/var/secrets/google/credentials.json`) 실제 마운트 후 Gemini OAuth 인증 성공 여부
- GKE workload identity 경로(`/etc/google/auth/application_default_credentials.json`) 동작 여부
- `_is_running_in_container()`: `/proc/1/cgroup` 파싱이 Docker Desktop(macOS) vs containerd(K3s) vs CRI-O에서 동일하게 동작하는지
- Claude CLI가 Docker 이미지에 설치되지 않았을 때 SDK fallback이 정상 동작하는지 (API key만으로)

**검증 방법:**
```bash
# Docker에서 직접 확인
docker run --rm -e ANTHROPIC_API_KEY=... -e GOOGLE_APPLICATION_CREDENTIALS=/creds/sa.json \
  -v ./sa.json:/creds/sa.json \
  agents-investing python -c "from src.llm.gemini_client import load_gemini_oauth_credentials; print(load_gemini_oauth_credentials())"
```

**위험도:** 높음 — LLM 호출 실패 시 전략 A/B 전체 불능

---

## 2. Python 3.9 vs 3.11+ 호환성

**현재 상태:** 로컬은 시스템 Python 3.9.6, 프로젝트 요구사항은 Python 3.11+

**미검증 사항:**
- pytest-asyncio 0.26 + Python 3.9에서 event loop 충돌 (14건 기존 실패 원인)
- `X | None` union 문법: `src/` 코드는 `from __future__ import annotations`로 보호되지만 일부 테스트 파일은 누락
- `match` 구문, `ExceptionGroup` 등 3.10+ 전용 기능이 프로덕션 코드에 숨어있을 가능성
- `test/test_blend_weight_optimizer.py`와 다른 async 테스트를 같이 돌리면 event loop가 꼬지는 현상 — Python 3.11+에서 해결되는지 미확인

**검증 방법:**
```bash
# Python 3.11+ 환경에서 전체 테스트 실행
python3.11 -m pytest test/ -v --tb=short
```

**위험도:** 중간 — CI에서 Python 3.11 사용 시 자연 해결 가능, 3.9 유지 시 테스트 수정 필요

---

## 3. S3/MinIO RL 에피소드 저장

**변경 파일:** `src/services/datalake.py`, `src/agents/rl_continuous_improver.py`

**미검증 사항:**
- `store_rl_episodes()`의 Parquet 직렬화 → MinIO 실제 업로드 (S3 엔드포인트 미연결)
- `_upload_with_retry()` 3회 재시도 후 최종 실패 시 `rl_continuous_improver`의 retrain 결과에 영향 없는지 (비필수 try/except로 감쌌지만 실환경 확인 필요)
- Parquet 파일이 실제로 Hive-style 파티션(`rl_episodes/date=2026-03-29/`)으로 저장되어 Athena/Trino에서 쿼리 가능한지
- `RLEvaluationMetrics.baseline_return_pct`를 `train_return_pct`로 매핑한 것이 의미적으로 맞는지 (baseline = buy-and-hold 기준, train 학습 수익률과 다를 수 있음)

**검증 방법:**
```bash
# MinIO 실행 후 확인
docker compose up -d minio
python -c "
import asyncio
from src.services.datalake import store_rl_episodes
from datetime import datetime, timezone
record = {'ticker': '005930', 'policy_id': 'test', 'profile_id': 'test', 'dataset_days': 180,
          'train_return_pct': 10.0, 'holdout_return_pct': 8.0, 'excess_return_pct': 5.0,
          'max_drawdown_pct': -3.0, 'walk_forward_passed': True, 'walk_forward_consistency': 0.8,
          'deployed': True, 'created_at': datetime.now(timezone.utc)}
print(asyncio.run(store_rl_episodes([record])))
"
```

**위험도:** 낮음 — S3 저장은 비필수(실패해도 학습 자체는 진행됨)

---

## 4. K8s Readiness 체크

**변경 파일:** `src/utils/readiness.py`

**미검증 사항:**
- `_evaluate_k8s_readiness()`가 실제 K3s 클러스터에서 정상 동작하는지
- ServiceAccount 토큰 경로(`/var/run/secrets/kubernetes.io/serviceaccount/token`)가 K3s에서도 동일한지 (K3s는 경량 배포라 경로가 다를 수 있음)
- 볼륨 마운트 경로(`/data/rl/models`, `/data/rl/experiments`)가 실제 Helm chart의 volumeMounts와 일치하는지 (Worker 1의 Helm chart 완성 후 맞춰야 함)
- DNS 체크(`socket.getaddrinfo("postgres", None)`)가 K8s 서비스명과 일치하는지 (Helm chart에서 서비스명이 `alpha-trading-postgres` 같은 prefix를 가질 수 있음)

**검증 방법:**
```bash
# K3s 클러스터 내 Pod에서 확인
kubectl exec -it deploy/alpha-trading-api -- python -c "
import asyncio
from src.utils.readiness import _evaluate_k8s_readiness
checks = asyncio.run(_evaluate_k8s_readiness())
for c in checks:
    print(f\"{'OK' if c['ok'] else 'FAIL'} {c['key']}: {c['message']}\")
"
```

**위험도:** 중간 — 체크 실패 시 실거래 전환 블로킹, 하지만 false negative는 설정 수정으로 해결

---

## 5. 스케줄러 장 전/후 잡 실행

**변경 파일:** `src/schedulers/unified_scheduler.py`

**미검증 사항:**
- `rl_bootstrap` (08:00): `RLContinuousImprover.retrain_ticker(dataset_days=720)` 실행 시 실제 소요 시간이 TTL(30분) 내에 완료되는지
- `rl_retrain` (16:00): `retrain_all()` 멀티 티커 순차 학습 시 TTL(60분) 내에 완료되는지
- `blend_weight_adjust` (16:30): `DYNAMIC_BLEND_WEIGHTS_ENABLED=true` 설정 후 Redis에 가중치가 올바르게 캐싱되고 다음 오케스트레이터 사이클에서 읽히는지
- `predictor_warmup` (08:05): PredictorAgent 인스턴스 생성만으로 LLM API 연결이 실제로 워밍업되는지 (lazy init일 수 있음)
- 분산 락: 동일 잡이 여러 Pod에서 동시 실행될 때 Redis NX 락이 정상 동작하는지

**검증 방법:**
```bash
# APScheduler 잡 수동 트리거
python -c "
import asyncio
from src.schedulers.unified_scheduler import start_unified_scheduler
asyncio.run(start_unified_scheduler())
# 로그에서 9개 잡 등록 확인 후 수동 트리거
"
```

**위험도:** 중간 — 스케줄 잡 실패 시 당일 트레이딩에는 영향 없지만(기존 잡은 유지) RL 학습/가중치 갱신이 지연됨

---

## 권장 검증 순서

1. **Python 3.11+ 테스트 실행** — CI 환경 구축 시 가장 먼저
2. **Docker 내 LLM 인증** — Dockerfile 프로덕션화(Worker 2) 완료 후
3. **K8s Readiness + 스케줄러** — Helm chart(Worker 1) 완료 후 K3s에서 통합 테스트
4. **S3 RL 에피소드** — MinIO docker-compose로 즉시 검증 가능

---

*작성: 2026-03-29*
