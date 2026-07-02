# Project — alpha-financial-pipeline

> **Repo**: https://github.com/DongJuS/alpha-financial-pipeline (public)
> **성격**: KOSPI/KOSDAQ 멀티 에이전트 AI 트레이딩 시스템
> **첫 결정 이력 정리**: 2026-07-02

이 프로젝트에서 픽스된 실체 결정들. 새 세션 시작 시 첫 응답 안에 참조.

---

## 1. Investment Mandate (2026-07-02 확정)

| # | 축 | 결정 |
|---|---|---|
| 1 | 자본 우선순위 | **자본 보존 최우선** |
| 2 | 투자 기간 | **단타 (1~3일)** |
| 3 | 시스템 신뢰도 | **완전 자동** |
| 4 | 감내 손실 | 일일 **-3%** · 포트 drawdown **-8%** · 개별 종목 **-7%** |
| 5 | 감사 vs 속도 | **감사 최우선** |
| 6 | UX 대상 | **본인 (전문)** |
| 추가 | 초기 실 자본 | **10-20만원**, 승산 검증 후 확장 |
| 추가 | 검증 목적 | Phase A~D 는 **paper 3개월 관측** 후 real 전환 결정 |

**전문 문서**: [`docs/plans/SELL_STRATEGY_PHASES.md`](../../plans/SELL_STRATEGY_PHASES.md) §1

---

## 2. 인프라 결정 (Phase 1~6 k3s 마이그레이션 완료)

### 2-1. 호스트 · 클러스터

- **호스트**: OCI Compute, Ampere ARM64, 24GB / 4 vCPU / 200GB, Ubuntu 24.04
- **k3s v1.36**, `--disable traefik --disable servicelb` (80 포트 충돌 회피)
- **단일 노드** 유지 (확장 절제)

### 2-2. 시크릿

- **Infisical** self-hosted, k3s 안에서 운영
- **Infisical Kubernetes Operator** (secrets-operator v0.11.2) 로 자동 sync
- **Universal Auth Identity** (`alpha-k3s-operator`, project Viewer role)
- **부트스트랩 시크릿** (Infisical 자체용 4 키): **SOPS + age** 로 git commit 가능한 암호화 형태 유지
- **age private key** 는 GH Environment `production` 의 `AGE_PRIVATE_KEY` + 운영자 password manager 이중 보관

### 2-3. 외부 노출

- **Cloudflare Quick Tunnel** (도메인 미보유)
- 동적 `trycloudflare.com` URL, systemd restart 마다 새 URL + Telegram 통보
- `cloudflared tunnel --url http://localhost:30080` (ui NodePort)

### 2-4. 배포

- **CI**: lint · unit test · integration test · helm-lint · build api/ui (ARM64 buildx)
- **CD**: `workflow_dispatch` + `workflow_run on build-and-push` 성공 자동 트리거 (G9 활성)
- **helm** `--atomic --wait --timeout 10m` — fail 시 자동 rollback
- **SSH** `-o ServerAliveInterval=30 -o ServerAliveCountMax=20` (OCI NAT 3-4분 idle timeout 방어)

### 2-5. 데이터

- **postgres** k3s StatefulSet + PVC 20Gi
- **redis** k3s StatefulSet + PVC 2Gi
- **파티션**: `tick_data` (일별), `ohlcv_daily` / `ohlcv_minute` (연도별)
- **백업**: pg_dump 일일 23:00 KST cron → OCI Object Storage Archive

---

## 3. Repo 분리 (3개)

| Repo | 가시성 | 역할 |
|---|---|---|
| `DongJuS/alpha-financial-pipeline` | **Public** | 메인 앱 코드 (이력서/포트폴리오) |
| `DongJuS/agents-investing-ops` | Private | 운영 식별자 (IP, OCID, bastion 호스트명), 점검 리포트 |
| `DongJuS/agents-investing-infisical` | Private | Infisical 자체의 k3s helm chart + 배포 파이프라인 |

**격리 원칙**: "코드 ≠ 공격, 네트워크 정체성을 모르면 reach 불가"
- 5 패턴 gitleaks rule: `134\.185\.110\.214`, `ocid1\.(instance|tenancy|bastion|user)\.oc1`, `alpha-trading-server`, `ap-chuncheon-1`, `oraclecloud`
- pre-commit + GitHub Push Protection 이중 방어

---

## 4. Trading Mode 정책 (하이브리드)

**의도적 분리** — 자본 리스크 방지:

| Component | KIS_IS_PAPER_TRADING | 이유 |
|---|---|---|
| **tick-collector** | **false (real)** | 시세는 real endpoint 에서만. 돈 안 나감. |
| **worker** | true (paper) | 거래는 paper 모의로. 실 주문 API 자체 호출 불가 = **자본 리스크 0** |
| **api** | true (paper) | worker 와 mode 일치, read-only 조회 시 paper 계좌 |

**Chart default**: `tickCollector.kisTickMode: "real"` (PR #230). auto deploy 마다 리셋 방지.

**UI 토글** (`/api/v1/system/trading-mode`): Redis 저장 + 표시만. 실 credential 전환은 별개 (Session 5 참조).

---

## 5. DB 결정

### 5-1. 종목 마스터 이중 구조 (유지 결정)

- `instruments` (canonical, 시스템 identifier)
- `krx_stock_master` (KRX 원본 dump, name/sector/시가총액)
- **join 유지 결정** — 통합 안 함 (미래 미국 주식 / 코인 확장 여지)

### 5-2. ETF / KONEX 등록 (2026-07-02 완료)

- **ETF (1,150개)** 등록 O — UI 에서 조회 가능
- **KONEX (110개)** 등록 O — 완전성 우선
- **역방향 gap (35)** — `is_active=false` (감사 이력 보존)
- **RL 학습 대상 (trading_universe 20종목)** 은 변경 없음
- 실행 방식: **임시 SQL 1회 실행** (상시 로직 만들지 않음, YAGNI)

### 5-3. 정규화 상태

- PK: 100% 커버리지 (109 tables)
- FK: **15개만** — 실용 관점에서 유지 (RL / trading_universe / rebalance 만 FK)
- 컬럼 nullable 34.3% — audit / snapshot 성격 반정규화 정상
- **미래 개선**: 추가 FK 는 Alembic 도입 후 (별개 논의)

---

## 6. Sell Strategy Roadmap (Phase A~D)

**전문 문서**: [`docs/plans/SELL_STRATEGY_PHASES.md`](../../plans/SELL_STRATEGY_PHASES.md)

| Phase | 기능 | 상태 |
|---|---|---|
| A | Hard Stop-Loss (3-layer: -7% / -8% / -3%) | 착수 대기 |
| B | Partial Exit (단타 2-level: +3% / +5%) | Phase A 후 |
| C | Time-based Exit (T+3 강제 + overnight 방어) | Phase B 후 |
| D | Rebalancing | **SKIP** (단타 mandate) |

**설계 세션 참여자** (페르소나):
- Kim — Head of Systematic Trading, ex-JP Morgan + Toss
- Yoon — Principal Engineer, ex-JP Morgan Trade OMS + Toss 실시간 호가

---

## 7. 승산 검증 게이트 (Paper → Real)

Phase A~C 실 활성 후 3개월 관측. 다음 6 지표 **모두 통과** 시 real 전환:

- Sharpe > 0.8
- Win rate > 55%
- Max drawdown < 10%
- 월간 승률 12개월 중 5개월 이상 +
- Hard stop 트리거 하루 평균 < 5회
- Time exit 청산 시 손실 < 익절 시 이익 (기대값 양수)

---

## 8. 결정 이력 요약 (2026-07-02 기준)

주요 결정 순서 (시간 흐름):

1. **Phase 1~6 k3s 마이그레이션** (Docker → k3s, 25.8M rows 무손실 cutover)
2. **Repo 3분리 + G3 history scrub + G4 public 전환**
3. **G9 CI/CD 자동 트리거 활성**
4. **PR #229** UI 대량 404 해소 (include_empty filter)
5. **PR #230** tick-collector real mode chart default
6. **PR #231** Paper/Real 토글 UI + API (Redis 저장)
7. **PR #232** RealAccount shape mismatch fix (nested → flat)
8. **DB sync** ETF/KONEX 4046 종목 등록 (임시 SQL)
9. **Sell Strategy Mandate 확정** (본 문서)
10. **PR #233** [`docs/plans/SELL_STRATEGY_PHASES.md`](../../plans/SELL_STRATEGY_PHASES.md) 로드맵

---

## 9. Open Questions (프로젝트 진행 중 미결)

- Real 계좌 잔고 조회 실 KIS API 연동 (지금은 flat shape mock)
- Real 전환 시 초기 자본 소진 후 증액 방식
- Phase A Layer 2 "최약체 정의" (pnl 하위 vs Sharpe 하위)
- KIS API rate limit 대응 (여러 종목 동시 hard stop 트리거 시)
- Gemini OAuth 상태 매 분 토글 이슈 (PR #222 는 임시 완화, 근본은 별개)

---

## Anchors (외부 문서 · 회고록)

- 회고록 (Obsidian): `C:\Users\didsu\iCloudDrive\sseo_obsidian\sseo_obsidian\02_Areas\data-engineering\`
  - `Docker_Compose_to_K3s_Migration_2026-06-30.md` (전체 STAR 회고)
  - `K3s_Migration_Engineering_Highlights_2026-06-30.md` (portfolio edition)
  - `Zero_Downtime_DB_Migration_with_EndpointSlice.md`
  - `Secrets_Bootstrap_SOPS_Age_and_Infisical_API.md`
  - `Repo_Carveout_and_History_Scrub.md`
- 로드맵 (repo): [`docs/plans/SELL_STRATEGY_PHASES.md`](../../plans/SELL_STRATEGY_PHASES.md)
