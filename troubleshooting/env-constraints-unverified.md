# 환경 제약으로 미검증 항목 (2026-03-29)

> 로컬 개발 환경(macOS, Python 3.9, Docker/K8s 미실행)의 제약으로
> 실제 동작을 확인하지 못한 항목. 프로덕션/CI 환경에서 반드시 검증 필요.

---

## ~~1. Docker 컨테이너 내 LLM 인증 경로~~ ✅ 해결 (PR #25)

**PR #25에서 해결됨:**
- Claude CLI: `${HOME}/.claude:/root/.claude:ro` bind mount → CLI 모드 정상 동작 확인
- Gemini OAuth: `${HOME}/.config/gcloud:/root/.config/gcloud:ro` bind mount → ADC 정상 로드 확인
- Gemini API key 모드는 의도적으로 제거, OAuth/ADC 전용으로 결정

**잔여 확인 사항 (K8s 배포 시):**
- K8s에서는 bind mount 대신 Secret/ConfigMap으로 인증 파일 마운트 필요
- 현재 Kustomize base/secrets.yaml에 `ANTHROPIC_API_KEY` 포함됨

---

## 2. Python 3.9 vs 3.11+ 호환성

**현재 상태:** 로컬은 시스템 Python 3.9.6, Dockerfile은 Python 3.11-slim

**미검증 사항:**
- pytest-asyncio 0.26 + Python 3.9에서 event loop 충돌 (14건 기존 실패 원인)
- `X | None` union 문법: `src/` 코드는 `from __future__ import annotations`로 보호되지만 일부 테스트 파일은 누락
- `test/test_blend_weight_optimizer.py`와 다른 async 테스트를 같이 돌리면 event loop가 꼬지는 현상

**검증 방법:**
```bash
# Docker 내 Python 3.11 환경에서 전체 테스트 실행
docker compose run --rm api pytest test/ -v --tb=short
```

**위험도:** 중간 — Docker/프로덕션은 3.11이므로 실환경에선 문제 없음. 로컬 개발만 영향.

---

## 3. S3/MinIO RL 에피소드 저장

**변경 파일:** `src/services/datalake.py`, `src/agents/rl_continuous_improver.py`

**검증 완료 (로컬):**
- ✅ Parquet round-trip 정상 (직렬화 → 역직렬화 → 12개 필드 일치)
- ✅ retry 3회 exponential backoff (1s → 2s) 동작 확인
- ✅ 실패 시 None 반환 (예외 전파 안 함, 학습 자체는 진행)
- ✅ Hive-style 키: `rl_episodes/date=2026-03-29/rl_episodes_120554.parquet`

**미검증 사항 (MinIO 실제 연결):**
- MinIO 엔드포인트 실제 업로드
- `alpha-lake` 버킷에 Parquet 파일이 올바르게 저장되어 S3 API로 조회 가능한지

**검증 방법:**
```bash
docker compose up -d minio minio-init
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

**위험도:** 낮음 — S3 저장은 비필수

---

## 4. K8s Readiness 체크

**변경 파일:** `src/utils/readiness.py`

**미검증 사항:**
- `_evaluate_k8s_readiness()`가 실제 K3s 클러스터에서 정상 동작하는지
- ServiceAccount 토큰 경로(`/var/run/secrets/kubernetes.io/serviceaccount/token`)가 K3s에서도 동일한지
- 볼륨 마운트 경로(`/data/rl/models`, `/data/rl/experiments`)가 Kustomize worker.yaml의 mountPath(`/app/artifacts/rl`)와 불일치 — **수정 필요**
- DNS 체크(`socket.getaddrinfo("postgres", None)`)가 K8s 서비스명과 일치하는지

**검증 방법:**
```bash
kubectl apply -k k8s/overlays/dev
kubectl exec -it deploy/api -- python -c "
import asyncio
from src.utils.readiness import _evaluate_k8s_readiness
checks = asyncio.run(_evaluate_k8s_readiness())
for c in checks:
    print(f\"{'OK' if c['ok'] else 'FAIL'} {c['key']}: {c['message']}\")
"
```

**위험도:** 중간

---

## 5. 스케줄러 장 전/후 잡 실행

**변경 파일:** `src/schedulers/unified_scheduler.py`

**검증 완료 (로컬):**
- ✅ 9개 잡 등록 확인 (mock scheduler)
- ✅ TTL 설정 확인 (rl_bootstrap 60분, rl_retrain 60분)
- ✅ predictor_warmup: 모듈 캐시 워밍업으로 개선 (Gemini OAuth 캐싱, Claude SDK 가용성)

**미검증 사항 (실환경):**
- `rl_bootstrap`/`rl_retrain` 실제 소요 시간이 TTL(60분) 내 완료되는지
- `blend_weight_adjust`: Redis 가중치 캐싱 → 오케스트레이터 사이클에서 읽히는지
- 분산 락: 멀티 Pod 환경에서 Redis NX 락 정상 동작하는지

**검증 방법:**
```bash
# Docker 환경에서 스케줄러 시작
docker compose up -d postgres redis minio
docker compose run --rm api python -c "
import asyncio
from src.schedulers.unified_scheduler import start_unified_scheduler
asyncio.run(start_unified_scheduler())
"
```

**위험도:** 중간

---

## 권장 검증 순서

1. ~~Docker 내 LLM 인증~~ ✅ (PR #25)
2. **S3 RL 에피소드** — `docker compose up -d minio`로 즉시 검증 가능
3. **Python 3.11 테스트** — `docker compose run api pytest`
4. **K8s Readiness + 스케줄러** — K3s 배포 후 통합 테스트

---

*작성: 2026-03-29, 수정: 2026-03-29 (PR #25 반영, G/I 로컬 검증 완료 반영)*
