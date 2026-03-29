# 📝 progress.md — 현재 세션 진척도

> 에이전트와 "현재 어디까지 했는지" 맞추는 단기 기억 파일입니다.
> 완료된 이력은 `progress-archive.md`를 참조하세요.
> **정리 정책**: 150줄 초과 시 완료+코드 유추 가능 항목 삭제. 200줄 초과 시 오래된 완료 항목 강제 삭제.

---

## 📊 Phase 진행 현황

```
Phase 1  인프라 기반 구축        ██████████  100% ✅
Phase 2  코어 에이전트           ██████████  100% ✅
Phase 3  Strategy A Tournament  ██████████  100% ✅
Phase 4  Strategy B Consensus   ██████████  100% ✅
Phase 5  대시보드 + 운용 검증    ██████████  100% ✅
Phase 6  독립 포트폴리오 인프라  ██████████  100% ✅
Phase 7  S3 Data Lake (MinIO)   ██████████  100% ✅
Phase 8  Search Foundation      ██████████  100% ✅
Phase 9  RL Trading Lane        ██████████  100% ✅
Phase 10 피드백 루프 파이프라인  ██████████  100% ✅
Phase 11 N-way 블렌딩 + Registry ██████████  100% ✅
Phase 12 블로그 자동 포스팅      ██████████  100% ✅
Step 3   RL 부트스트랩 + 블렌딩  ██████████  100% ✅
Step 4   K3s 프로덕션 배포       █████████░   90% 🔧
Step 7   글로벌 데이터 레이크    ███░░░░░░░   30% 🔧
Step 7b  Airflow 비교 스파이크   ████████░░   80% 🔧
테스트   스위트 정비             ██████████  100% ✅
```

---

## 🔄 미완료 / 진행 중

### Step 7: 글로벌 데이터 레이크 확장 (🔵 진행 중)

> 목적: 한국(KOSPI/KOSDAQ) + 미국(NYSE/NASDAQ) 전 종목의 12년치 일봉 데이터를 수집하여,
> RL 학습 및 전략 분석의 데이터 기반을 확장한다.

**설계 결정 (2026-03-30 회의):**
- 기존 `market_data` 테이블(int, KST 고정)은 글로벌 확장에 부적합
- 신규 3개 테이블 설계: `markets` (시장 메타) + `instruments` (종목 마스터) + `ohlcv_daily` (일봉, 파티셔닝)
- 가격 타입: `int` → `NUMERIC(15,4)` (KRW/USD 통합, float 전처리)
- 파티셔닝: ohlcv_daily를 연도별 파티션 (2010~2027)
- FDR 최대 12년(3,000일) 일봉 수집, 예상 용량 ~5GB (PostgreSQL)

**완료:**
- [x] 테이블 생성: markets (4개 시장), instruments, ohlcv_daily (파티셔닝) — `scripts/db/create_market_tables.py`
- [x] 수집 스크립트: `scripts/db/seed_all_instruments.py` (종목 등록 + 일봉 수집)
- [ ] KR 수집 중: KOSPI(951) + KOSDAQ(1,821) = 2,772종목
- [ ] US 수집: NYSE(2,737) + NASDAQ(3,854) = 6,591종목
- [ ] 기존 market_data → ohlcv_daily 마이그레이션
- [ ] 기존 src/ 코드를 신규 테이블 구조에 맞게 수정

### Step 7b: Airflow 비교 스파이크 (브랜치: `feature/airflow-workflow-spike`)

> main에서 분기. Alpha와 Airflow를 동시에 띄워서 비교.

- [x] `docker-compose.airflow.yml` 작성
- [x] `dags/pre_market_collection.py` — 장 전 수집 DAG 6/6 SUCCESS
- [x] Airflow UI 접속 확인 (localhost:8080)
- [ ] DAG Graph View / Gantt Chart 스크린샷
- [ ] Obsidian `work/` 비교 기록 + 면접 답변 작성
- [ ] 신규 테이블 구조(ohlcv_daily)에 맞게 DAG 수정

### QA: Docker LLM 인증 해결 (2026-03-30)
- [x] Dockerfile target: dev 명시 (non-root Permission Denied 해결) — PR #73
- [x] GEMINI_API_KEY 완전 제거 (OAuth ADC 충돌 해결) — PR #73
- [x] Claude CLI 컨테이너 내 로그인 (.claude rw 마운트) — PR #73
- [x] Gemini OAuth ADC 정상 동작 확인
- ⚠️ LLM 일일 한도 30회 도달 (자정 리셋 후 정상 동작)

### 제출 (🔴 3/30 마감)
- [ ] 이력서 DE 언어 전환
- [ ] 제출

### 보류
- [ ] SearchAgent — Step 4 완료 후 재개

---

*Last updated: 2026-03-30*
