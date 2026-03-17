# QA 체크리스트 — agents-investing UI 전체 점검

> **작성일:** 2026-03-16
> **목적:** 브라우저에서 모든 클릭 가능 요소의 정상 동작 확인
> **참고:** S3 데이터 미수신 이슈 확인됨 — 데이터레이크 섹션 집중 점검 필요

---

## 0. 로그인 (`/login`)

- [ ] 로그인 폼 렌더링 확인
- [ ] 아이디/비밀번호 입력 필드 동작
- [ ] 로그인 버튼 클릭 → 토큰 발급 및 `localStorage` 저장 확인
- [ ] 로그인 성공 시 `/dashboard`로 리다이렉트
- [ ] 잘못된 자격증명 입력 시 에러 메시지 표시
- [ ] 미인증 상태에서 다른 페이지 접근 시 `/login`으로 리다이렉트

---

## 1. 홈 — 대시보드 (`/dashboard`)

- [ ] 페이지 로딩 및 전체 레이아웃 렌더링
- [ ] 포트폴리오 요약 카드 (총 자산, 수익률 등) 데이터 표시
- [ ] 계좌 상태 지표 정상 렌더링
- [ ] 실시간 데이터 폴링 동작 (30초 간격)
- [ ] 로딩 중 스켈레톤 UI 표시

---

## 2. 전략 (`/strategy`)

### KPI 카드 영역
- [ ] Blend ratio 카드 수치 표시
- [ ] Combined signals 카드 수치 표시
- [ ] Conflict HOLD 카드 수치 표시
- [ ] Total HOLD 카드 수치 표시

### 교차 검증 보드
- [ ] 시그널 목록 렌더링 (티커, 시그널 뱃지, 신뢰도)
- [ ] "근거 보기" 버튼 클릭 → Debate 상세 정보 펼침
- [ ] Conflict 인디케이터 표시 및 확장

### 토너먼트 테이블
- [ ] TournamentTable 컴포넌트 정상 렌더링
- [ ] 테이블 데이터 로딩

### 최근 Debate 이력
- [ ] Debate 목록 스크롤 동작
- [ ] Debate #ID 클릭 → 해당 Debate 선택 및 하이라이트
- [ ] 상태 뱃지 (HOLD, BUY, SELL) 색상 정상 표시

### Strategy B · Consensus
- [ ] 시그널 목록 렌더링
- [ ] 각 시그널의 "Debate 보기" 버튼 클릭 → 트랜스크립트 뷰어 열림

### Debate Transcript 뷰어
- [ ] 조건부 렌더링 (Debate 선택 시에만 표시)
- [ ] 각 라운드별 `<details>` 요소 펼침/접힘
- [ ] Proposer, Challenger 1, Challenger 2, Synthesizer 내용 표시
- [ ] Policy 텍스트 정상 표시

### 확장 레이어
- [ ] RL Trading 카드 렌더링 및 상태 뱃지 ("planned")
- [ ] Search/Scraping Research 카드 렌더링 및 상태 뱃지 ("planned")

---

## 3. RL — 강화학습 트레이딩 (`/rl-trading`)

### 탭 내비게이션
- [ ] 4개 탭 버튼 렌더링 (정책 관리, 학습 실험, 섀도우 추론, 승격 게이트)
- [ ] 각 탭 클릭 시 해당 콘텐츠 전환

### 3-1. 정책 관리 탭
- [ ] KPI 카드 (총 정책 수, 활성 정책, WF 통과, 평가 수)
- [ ] 정책 테이블 렌더링 (티커, 버전, 알고리즘, 모드 뱃지)
- [ ] Excess Return, Sharpe, Win Rate 수치 표시
- [ ] WF 상태 뱃지 정상 색상
- [ ] Active 인디케이터 (초록 점) 표시
- [ ] "활성화" 버튼 클릭 → 비활성 정책 활성화 API 호출 확인
- [ ] 활성화 후 UI 상태 갱신

### 3-2. 학습 실험 탭
- [ ] 티커 코드 입력 필드 동작
- [ ] 에피소드 수 입력 필드 동작
- [ ] "학습 시작" 버튼 클릭 → 학습 API 호출
- [ ] 실험 테이블 렌더링 (Run ID, 티커, 상태 뱃지 등)
- [ ] Walk-Forward Validator: 정책 ID 입력 필드
- [ ] "Walk-Forward 실행" 버튼 클릭 → 실행 및 결과 (pass/fail) 표시

### 3-3. 섀도우 추론 탭
- [ ] 섀도우 정책 테이블 렌더링
- [ ] "성과 보기" 버튼 클릭 → 해당 정책 성과 표시
- [ ] KPI 카드 (정확도, 가상 수익률, 초과 수익률, 기간) 렌더링

### 3-4. 승격 게이트 탭
- [ ] Shadow → Paper 섹션: WF 통과 정책 테이블 표시
- [ ] "Paper 승격" 버튼 클릭 → 승격 API 호출 및 피드백 메시지
- [ ] Paper → Real 섹션: 정책 목록 표시
- [ ] Confirmation code 비밀번호 입력 필드
- [ ] "Real 승격" 버튼 클릭 → 승격 API 호출
- [ ] Policy Mode Lookup: 정책 ID 입력 → 현재 모드 및 다음 승격 단계 표시

---

## 4. 성과 분석 (`/feedback`)

- [ ] 페이지 로딩 및 렌더링
- [ ] 성과 지표 데이터 표시
- [ ] 피드백 루프 시각화 차트 렌더링
- [ ] 기간별 성과 데이터 표시
- [ ] 데이터 미수신 시 빈 상태(empty state) 처리

---

## 5. 모델 관리 (`/models`)

### Provider 상태 카드
- [ ] 3개 Provider 카드 렌더링 (Claude, GPT, Gemini)
- [ ] 상태 뱃지: READY / NOT CONFIGURED 정상 표시
- [ ] 기본 모델명 표시

### Strategy A 예측자 슬롯 (5개)
- [ ] 각 슬롯 카드 렌더링 (역할, 에이전트 ID, 전략 코드 뱃지)
- [ ] 모델 선택 드롭다운 변경 동작
- [ ] 페르소나 textarea 입력 동작

### Strategy B Debate 역할 (4개)
- [ ] Proposer, Challenger 1, Challenger 2, Synthesizer 카드 렌더링
- [ ] 모델 선택 드롭다운 변경 동작
- [ ] 페르소나 textarea 입력 동작

### 저장
- [ ] "모델 설정 저장" 버튼 클릭 → API 호출
- [ ] 저장 성공/실패 피드백

---

## 6. 마켓 (`/market`)

### 지수 카드
- [ ] KOSPI 지수 카드: 수치 및 등락률 표시 (초록/빨강)
- [ ] KOSDAQ 지수 카드: 수치 및 등락률 표시 (초록/빨강)

### 종목 선택
- [ ] 티커 선택 드롭다운: 종목 목록 표시
- [ ] 드롭다운 변경 → 차트 데이터 갱신

### 차트 소스 선택
- [ ] "내부 DB" / "오픈소스 API" 드롭다운 변경
- [ ] 소스 변경 시 차트 데이터 재로딩

### 차트 영역
- [ ] OHLCV 차트 렌더링 (High/Low 바, Open/Close 바, 종가 라인)
- [ ] 거래량 차트 렌더링 (Area chart)
- [ ] 실시간 시계열 차트 렌더링 (5초 폴링 인디케이터)
- [ ] 장 마감 시 Market Status "장 마감" 표시

---

## 7. 마켓플레이스 (`/marketplace`)

- [ ] 페이지 로딩 및 렌더링
- [ ] 섹터 분석 뷰 표시
- [ ] 랭킹 데이터 표시
- [ ] 매크로 지표 표시
- [ ] 각 섹션 클릭/상호작용 요소 동작

---

## 8. 모의 투자 (`/paper-trading`)

### 계좌 요약
- [ ] 계좌 카드 렌더링 (라벨, 누적 수익률 뱃지)
- [ ] 4개 정보 카드 (총 자산, 가용 현금, 포지션 수, 체결 주문)

### 기간 선택 및 차트
- [ ] Daily / Weekly / Monthly / All 버튼 각각 클릭
- [ ] 기간 변경 시 차트 데이터 갱신
- [ ] 계좌 스냅샷 차트 렌더링

### 주문 테이블
- [ ] 브로커 주문 테이블 렌더링 (최근 20건)
- [ ] 주문 상태 뱃지 색상: FILLED(초록), REJECTED(빨강), CANCELLED(빨강), PENDING(노랑)

### 포지션 테이블
- [ ] 포지션 목록 렌더링 (종목, 수량, 평균가, 현재가, 평가손익, 비중)

### 부가 정보
- [ ] Strategy Mix Summary (상위 3개 시그널 소스) 표시
- [ ] 체결률 및 상태별 건수 통계 표시

---

## 9. 내 계좌 — 포트폴리오 (`/portfolio`)

### 기간 선택
- [ ] 4개 기간 버튼 (Daily, Weekly, Monthly, All) 각각 클릭
- [ ] 기간 변경 시 데이터 갱신

### KPI 카드
- [ ] 수익률 카드 표시
- [ ] MDD 카드 표시
- [ ] Sharpe Ratio 카드 표시
- [ ] Win Rate 카드 표시

### 누적 수익률 차트
- [ ] 포트폴리오 vs 벤치마크 라인 차트 렌더링
- [ ] 범례(legend) 표시

### 포지션 테이블
- [ ] 종목, 수량, 평균가, 현재가, 평가손익, 비중 컬럼 표시
- [ ] 데이터 정상 로딩

### 거래 내역 테이블
- [ ] 최근 30건 거래 표시
- [ ] BUY/SELL 뱃지 색상
- [ ] 전략 소스 표시

---

## 10. 에이전트 (`/agent-control`)

### 에이전트 카드 그리드
- [ ] 에이전트 카드 목록 렌더링
- [ ] 각 카드: 에이전트 ID, 상태 뱃지, 활동 라벨, 마지막 액션, 접속 인디케이터
- [ ] 카드 클릭 → 선택 링(ring) 하이라이트

### 에이전트 제어 패널 (카드 선택 시)
- [ ] "재개" 버튼 클릭 → Resume API 호출
- [ ] "일시정지" 버튼 클릭 → Pause API 호출
- [ ] "재시작" 버튼 클릭 → Restart API 호출
- [ ] 로그 테이블 (Time, Status, Last Action) 렌더링
- [ ] 로그 스크롤 동작 (max-height overflow)

---

## 11. 헬스 — 시스템 건강 (`/system-health`)

### 전체 상태
- [ ] Overall 상태 뱃지 (healthy/degraded/unhealthy) 표시
- [ ] 마지막 오케스트레이터 사이클 타임스탬프

### 서비스 상태 카드
- [ ] 서비스별 카드 렌더링 (3열 그리드)
- [ ] 상태 뱃지 (ok/degraded/down) 색상
- [ ] 지연 시간(ms) 표시

### 에이전트 요약
- [ ] 4개 KPI 카드 (총 에이전트, Alive, Dead, Degraded)

### 24시간 메트릭스
- [ ] 에러 수 표시
- [ ] 총 하트비트 수 표시
- [ ] 활성 에이전트 수 표시
- [ ] 에이전트 포화율(%) 표시

---

## 12. 데이터 — 데이터레이크 (`/datalake`) ⚠️ 집중 점검

> **S3 데이터 미수신 이슈 확인됨 — 이 섹션 우선 점검**

- [ ] 페이지 로딩 및 렌더링
- [ ] S3 버킷 목록 표시 여부
- [ ] 파일/오브젝트 리스트 로딩 여부
- [ ] 데이터 업로드 컨트롤 동작
- [ ] 데이터 다운로드 컨트롤 동작
- [ ] 빈 데이터 시 empty state 또는 에러 메시지 확인
- [ ] API 응답 상태 코드 확인 (브라우저 DevTools Network 탭)
- [ ] S3 연결 설정 및 자격증명 유효성 점검
- [ ] 데이터 수신 파이프라인 로그 확인

---

## 13. 알림 (`/notifications`)

- [ ] 페이지 로딩 및 렌더링
- [ ] 알림 목록 표시
- [ ] 알림 항목 클릭 → 상세 보기
- [ ] 필터링/정렬 컨트롤 동작
- [ ] 읽음/안읽음 상태 표시

---

## 14. 감사 — 감사 추적 (`/audit`)

- [ ] 페이지 로딩 및 렌더링
- [ ] 감사 로그 테이블 표시
- [ ] 날짜/에이전트/액션 필터링 동작
- [ ] 로그 상세 내용 확인
- [ ] 내보내기(Export) 컨트롤 동작 (있는 경우)

---

## 15. 설정 (`/settings`)

### 전략/리스크 설정
- [ ] Strategy Blend Ratio 슬라이더 조작 (0.0~1.0)
- [ ] 슬라이더 값 변경 시 "Tournament (A) ↔ Debate (B)" 비율 표시 갱신
- [ ] Max Position % 입력 (1~100 범위 제한)
- [ ] Daily Loss Limit % 입력 (1~100 범위 제한)
- [ ] "전략 설정 저장" 버튼 클릭 → API 호출 및 성공/실패 피드백

### Telegram 알림 설정
- [ ] Morning Brief (08:30) 체크박스 토글
- [ ] Trade Alerts 체크박스 토글
- [ ] Circuit Breaker Trigger 체크박스 토글
- [ ] Daily Report (16:30) 체크박스 토글
- [ ] Weekly Summary (Friday 17:00) 체크박스 토글
- [ ] "알림 설정 저장" 버튼 클릭 → API 호출

### 실행 계좌 관리
- [ ] 마켓 시간 강제 적용 상태 표시
- [ ] Readiness 체크 항목 목록 스크롤
- [ ] Paper Trading 활성화 체크박스 토글
- [ ] Real Trading 활성화 체크박스 토글
- [ ] Primary Account Scope 드롭다운 (paper/real) 변경
- [ ] Confirmation Code 비밀번호 입력 필드
- [ ] "실행 계좌 저장" 버튼 클릭 → API 호출 및 피드백

---

## 공통 — 헤더/레이아웃

### 브랜드 및 타이틀
- [ ] 로고 (번개 아이콘 + 그라디언트 배경) 렌더링
- [ ] "투자 Agent" 타이틀 표시
- [ ] "Capital protection first" 모토 표시
- [ ] 태그라인 문구 표시

### 내비게이션 바
- [ ] 15개 NavLink 모두 렌더링 (홈, 전략, RL, 성과 분석, 모델 관리, 마켓, 마켓플레이스, 모의 투자, 내 계좌, 에이전트, 헬스, 데이터, 알림, 감사, 설정)
- [ ] 각 NavLink 클릭 → 해당 페이지로 라우팅
- [ ] 현재 페이지 NavLink 활성 스타일 (블루 그라디언트 배경)
- [ ] 호버 시 살짝 올라가는 애니메이션 (-translate-y-0.5)

### 상태 칩 (데스크톱)
- [ ] "Paper-first protocol" 뱃지 표시
- [ ] "투명성 로그 90일" 칩 표시
- [ ] "신뢰도 0.6 미만 HOLD" 칩 표시
- [ ] "데이터 30분 초과 시 예측 중단" 칩 표시

### 로그아웃
- [ ] 로그아웃 버튼 클릭 → 토큰 제거 및 `/login`으로 리다이렉트

### 모바일 반응형
- [ ] 모바일 뷰포트에서 내비게이션 가로 스크롤 동작
- [ ] 컴팩트 라벨 표시
- [ ] 반응형 그리드 전환 (1열 → 2열 → 4열)

---

## 크로스커팅 점검

### 네트워크/API
- [ ] 모든 페이지에서 API 호출 시 로딩 상태 표시
- [ ] API 실패 시 에러 메시지 또는 fallback UI
- [ ] 30초 폴링 간격 정상 동작 (React Query)
- [ ] 재시도 로직 (2회) 동작

### 데이터 표시
- [ ] 수익: 초록색, 손실: 빨강색 일관성
- [ ] 뱃지 색상 일관성 (BUY=초록, SELL=빨강, HOLD=노랑 등)
- [ ] 숫자 포맷 (천 단위 구분, 소수점 자릿수)
- [ ] 타임스탬프 형식 일관성

### 빈 상태 / 에러 처리
- [ ] 데이터 없을 때 빈 상태 UI 표시
- [ ] 네트워크 에러 시 사용자에게 안내
- [ ] 인증 만료 시 로그인 페이지로 리다이렉트

---

## 16. 실계좌 — KIS 실거래 계좌 (`/real-account`) ⚠️ 누락 발견

> **QA 검증 중 발견:** qa-checklist에 해당 페이지 항목이 없었음 (nav에는 존재)

- [ ] 페이지 로딩 및 렌더링
- [ ] 실계좌 번호 마스킹 표시 (예: 4423****01)
- [ ] 예수금 / 주식 평가금액 / 총 자산 / 평가 손익 카드 표시
- [ ] 보유종목 테이블 렌더링 (종목, 수량, 평균가, 현재가, 평가손익)
- [ ] 보유종목 없을 때 "보유 중인 종목이 없습니다" empty state
- [ ] "새로고침" 버튼 클릭 → KIS API 호출하여 실시간 데이터 갱신
- [ ] 새로고침 시 마지막 조회 시간 업데이트
- [ ] KIS API 미연결 시 에러 메시지 또는 fallback UI

---

## 인프라 연결 상태 점검 (Backend ↔ 외부 서비스)

> **QA 검증 중 추가:** UI 페이지 점검만으로는 확인 불가한 인프라 수준의 연결 상태

### PostgreSQL 연결
- [ ] `/health` 엔드포인트에서 `db_ok: true` 반환 확인
- [ ] `asyncpg` 커넥션 풀 정상 생성 (min=2, max=20)
- [ ] DB 테이블 수 확인 (예상: 27~28개 — `/api/v1/system/metrics`의 `db_table_count`)
- [ ] 대량 쿼리 시 타임아웃(30초) 설정 동작 여부

### Redis 연결
- [ ] `/health` 엔드포인트에서 `redis_ok: true` 반환 확인
- [ ] 캐시 키 정상 저장/조회 (`market_index`, `latest_ticks`, `stock_master` 등)
- [ ] Pub/Sub 토픽 발행/구독 동작 (`market_data`, `signals`, `orders`, `heartbeat`, `alerts`)
- [ ] 키 TTL 설정 정상 (heartbeat 90s, quote 60s, index 120s, stock_master 24h)

### S3/MinIO 연결 ⚠️ 현재 장애
- [ ] docker-compose.yml에 MinIO 서비스 정의 존재 여부 확인
- [ ] MinIO 컨테이너 실행 상태 확인 (`minio:9000` 접근 가능)
- [ ] `ensure_bucket("alpha-lake")` 자동 생성 동작
- [ ] `/api/v1/system/overview`에서 S3/MinIO 상태 `ok` 확인 (현재: `error`)
- [ ] S3 Parquet 쓰기/읽기 테스트 (`datalake.py` 경유)
- [ ] Data Lake Overview에서 총 객체 수 > 0 확인

### KIS API 연결
- [ ] KIS Paper 계좌 자격증명(APP_KEY, APP_SECRET, ACCOUNT_NUMBER) 설정 확인
- [ ] KIS Real 계좌 자격증명 설정 확인
- [ ] KIS OAuth 토큰 발급 정상 동작 (`scripts/kis_auth.py`)
- [ ] KIS REST API 호출 정상 (시세 조회, 잔고 조회)
- [ ] KIS WebSocket 연결 정상 (실시간 틱 수집)
- [ ] 토큰 만료 시 자동 갱신 동작

### LLM Provider 연결
- [ ] Claude CLI 키 설정 및 호출 정상 (ANTHROPIC_API_KEY)
- [ ] Gemini OAUTH 키 설정 및 호출 정상 (GEMINI_API_KEY)
- [ ] 모델 관리 페이지에서 Provider 상태 READY 표시 (현재: Claude ✅, Gemini ✅, GPT 미표시)

---

## 에이전트 상태 및 데이터 파이프라인

> **QA 검증 중 추가:** 에이전트 간 데이터 흐름이 실제로 동작하는지 확인

### Orchestrator Worker
- [ ] Worker 프로세스 실행 상태 확인 (docker-compose worker 서비스)
- [ ] Orchestrator 사이클 실행 주기 확인 (기본 120초)
- [ ] 마지막 Orchestrator 사이클 타임스탬프 확인 (system-health 페이지)
- [ ] Orchestrator 모드(blend/tournament/consensus) 전환 동작

### Collector Agent
- [ ] 일봉 데이터 수집 정상 (FinanceDataReader → PostgreSQL market_data)
- [ ] KIS WebSocket 실시간 틱 수집 정상 → Redis 캐시 저장
- [ ] 수집 에러 발생 시 `collector_errors` 테이블 기록

### Predictor Agent (1~5) ⚠️ 현재 장애
- [ ] 5개 Predictor 인스턴스 동시 실행 확인
- [ ] LLM 연동 호출 성공 (Claude CLI / openai SDK / Gemini OAuth) (현재: 0종목 성공, 20종목 실패 — 전원 error 상태)
- [ ] 예측 결과 `predictions` 테이블 저장
- [ ] Strategy A 토너먼트 스코어 갱신 (`predictor_tournament_scores`)
- [ ] Strategy B Debate 트랜스크립트 저장 (`debate_transcripts`)

### Portfolio Manager
- [ ] 시그널 기반 주문 생성 → `broker_orders` 저장
- [ ] 주문 체결 → `trade_history` 저장
- [ ] 포지션 업데이트 → `portfolio_positions` 갱신
- [ ] 계좌 스냅샷 주기적 기록 → `account_snapshots`

### Notifier Agent
- [ ] Telegram 알림 발송 정상 (현재: 1,759건 발송, 98.8% 성공률)
- [ ] 알림 유형별 통계 정상 (cycle_summary, paper_daily_report, test, manual)

---

## 데이터 정합성 검증

> **QA 검증 중 추가:** 여러 페이지에서 동일 데이터 표시 시 일관성 확인

- [ ] Dashboard 총 자산 == Portfolio 총 자산 == Paper Trading 총 자산 (동일 scope 기준)
- [ ] Dashboard 보유 종목 수 == Portfolio 포지션 테이블 행 수
- [ ] Agent Control 에이전트 수 == System Health 전체 에이전트 수
- [ ] Notifications 총 발송 수 == Audit 감사 로그의 notification 이벤트 수
- [ ] Market 지수 카드 데이터 == `/api/v1/market/index` 응답값
- [ ] 실계좌 페이지 계좌번호 == KIS 설정의 ACCOUNT_NUMBER (마스킹 포함)

---

## Debate Transcript 뷰어 동작 상세

> **QA 검증 중 추가:** Strategy 페이지의 Debate 클릭 시 트랜스크립트가 펼쳐지지 않는 현상 발견

- [ ] Debate 목록에서 항목 클릭 시 `/api/v1/strategy/b/debate/{id}` API 호출 발생 확인
- [ ] 선택된 Debate에 하이라이트(ring) 스타일 적용 확인
- [ ] Debate 선택 시 우측 또는 하단에 Transcript 뷰어 패널 표시
- [ ] 트랜스크립트 뷰어가 화면에 보이지 않는 경우 스크롤 자동 이동 여부

---

## 마켓플레이스 섹터 히트맵 데이터

> **QA 검증 중 추가:** 섹터 히트맵 영역이 비어있는 현상 발견

- [ ] `/api/v1/marketplace/sectors/heatmap` 응답에 실제 섹터 데이터 포함 여부
- [ ] `stock_master` 테이블에 sector/industry 데이터 시드 여부
- [x] 섹터 데이터 없을 때 적절한 empty state 표시 ~~(현재: 빈 공간만 보임)~~ → **FIX 완료 (2026-03-17)**: Marketplace.tsx에 히트맵·랭킹 empty state 메시지 추가

---

## 모델 관리 — GPT Provider 누락 확인

> **QA 검증 중 추가:** 모델 관리 페이지에서 GPT Provider 카드가 보이지 않음

- [x] Provider 상태 카드 3개 모두 렌더링 (Claude, GPT, Gemini) ~~— 현재 2개만 표시~~ → **FIX 완료 (2026-03-17)**: `model_config.py`에 GPT 프로바이더 및 모델 옵션 추가
- [ ] OPENAI_API_KEY 미설정 시 GPT 카드 "NOT CONFIGURED" 표시 여부
- [ ] OPENAI_API_KEY 설정 시 GPT 카드 "READY" 전환 확인

---

## 3rd QA 수정 반영 사항 (2026-03-17)

> **수정 완료 항목 (코드 변경)**

### 코드 수정

- [x] **GPT Provider 카드 누락**: `model_config.py`에 GPT 모델 3종(gpt-4o, gpt-4o-mini, gpt-4-turbo) 추가 + `provider_status()`에 GPT 상태 반환 + `provider_name_for_model()`에 GPT 분기 추가
- [x] **/real-account 라우트 누락**: `App.tsx`에 `/real-account` 라우트 추가 + `Layout.tsx` NAV_ITEMS에 실계좌 항목 추가
- [x] **Predictor silent failure**: `predictor.py`에서 `logger.warning` → `logger.error(exc_info=True)` + 실패 레코드 DB 기록 (다른 에이전트가 선수정)
- [x] **Marketplace empty state**: 히트맵·상승률·하락률·랭킹 탭에 데이터 없을 때 안내 메시지 추가

### QA 오판 정정

- [x] **ErrorBoundary**: 1st/2nd QA에서 "No global ErrorBoundary" FAIL 판정 → **실제로는 `main.tsx`에 `<ErrorBoundary>` 존재 확인**. 앱 전체를 감싸고 있으며 `ErrorBoundary.tsx`(145줄)에 완전한 에러 복구 UI 구현됨. **이 항목은 PASS로 정정해야 함.**
