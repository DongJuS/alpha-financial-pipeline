# RL 장 후 파이프라인 e2e 검증 중 발견된 이슈 (2026-03-30)

> RL 재학습 → 정책 배포 → 추론 e2e 테스트 중 발견한 3건의 이슈.
> 상태: **전부 해결**

---

## 1. ohlcv_daily 테이블 미존재

- **증상:** `RLContinuousImprover.retrain_ticker()` 실행 시 `relation "ohlcv_daily" does not exist`
- **원인:** 코드는 `ohlcv_daily` 테이블을 참조하도록 마이그레이션(14파일)했지만, 실제 DB에 테이블을 아직 생성하지 않았음. `scripts/db/create_market_tables.py`가 다른 AI의 Docker 환경에서만 실행됐고, 현재 로컬 DB에는 적용 안 됨.
- **해결:** `python scripts/db/create_market_tables.py` 실행 → markets(4), instruments, ohlcv_daily(파티셔닝 2010~2027) 생성. 이후 market_data(daily) → ohlcv_daily + instruments로 데이터 마이그레이션 SQL 수동 실행.
- **영향:** ohlcv_daily를 참조하는 모든 쿼리 (queries.py, collector.py, ranking_calculator.py 등 14파일)
- **교훈:** 스키마 마이그레이션 코드와 실제 DB 적용은 별개. 브랜치 간 DB 상태 동기화 주의.

---

## 2. find_in_map()이 레거시 None 엔트리에 매칭

- **증상:** `RLRunner.run(['005930'])` → 0건 시그널. 활성 정책이 `005930.KS`에 등록되어 있는데 못 찾음.
- **원인:** `registry.list_active_policies()`가 `{'005930': None, '005930.KS': 'rl_005930.KS_...'}` 반환. `find_in_map('005930', active_map)`에서 `005930` 키가 먼저 직접 매칭되어 `None` 반환 → 정규화 매칭(`005930.KS`)까지 도달 못함.
- **해결:** `find_in_map()`에서 `lookup[key] is not None` 조건 추가. None 값이면 건너뛰고 다음 매칭(정규화/raw) 시도.
- **영향:** `src/utils/ticker.py` — RL Runner, RL Continuous Improver 등에서 사용
- **교훈:** instrument_id 체계 전환(005930 → 005930.KS) 시 레거시 registry 엔트리가 None으로 남아있으면 매칭이 실패함. 마이그레이션 시 레거시 엔트리 정리 또는 None 방어 필요.

---

## 3. 시스템 파일 디스크립터 고갈 (Too many open files)

- **증상:** API 컨테이너에서 `OSError: [Errno 23] Too many open files in system`. uvicorn이 코드 reload 실패, 로그인 401 (디버그 코드가 로드 안 됨).
- **원인:** K3s Pod(23개) + Docker Compose(8개) + Airflow(3개) = 34개 컨테이너가 동시 실행. Colima VM의 파일 디스크립터 한도 초과.
- **해결:** K3s/Airflow 컨테이너 전부 중지 → Colima 재시작 → Docker Compose만 8개로 제한. K3s를 사용할 때는 Docker Compose를 내리고, 반대도 마찬가지.
- **영향:** 모든 Docker 서비스 (API, Worker, gen-collector 등)
- **교훈:** Colima(K3s) + Docker Compose + Airflow를 동시에 돌리면 fd 고갈. 한 번에 하나의 환경만 사용하거나, Colima의 `--kubernetes=false` 옵션으로 K3s 비활성화.

**예방책:**
```bash
# Docker Compose만 사용할 때
colima start --cpu 4 --memory 8  # K8s 없이

# K3s가 필요할 때
colima start --kubernetes --cpu 4 --memory 8
docker compose down  # Docker Compose는 내리기
```

---

*작성: 2026-03-30*
