# User Profile

> 대화 관찰에서 도출한 프로젝트-무관 사용자 성향. 새 프로젝트에서도 재활용 가능.

## 관심 분야

- **알고리즘 트레이딩** — KIS API, LLM multi-agent consensus, RL Dreamer, 백테스트
- **Data engineering** — 시계열 파이프라인, 파티션 관리, DB 정규화, 마이그레이션
- **DevOps / 인프라** — k3s, Helm, Cloudflare Tunnel, OCI, CI/CD 자동화
- **AI agents** — LangGraph 스타일 orchestrator, LLM fallback chain, agent 상태 관리
- **커리어 활용** — 이력서 · 자소서 · 면접 후크로 사용할 수 있는 포트폴리오 가치

## 학습/작업 스타일

- **개념 우선 파악** — 코드 보기 전에 "왜, 무엇, 어떻게" 명확화
- **사전 배경 없는 사람도 이해** 요구 → 비유·일상 예시 자주
- **극단 vs 극단 스펙트럼** 이해 좋아함 (중간 회색 X)
- **회고/재활용 문서** 좋아함 — Obsidian vault, 이력서, 자소서
- **관찰 후 결정** — 데이터 기반, 데이터 없으면 dry-run 부터

## 실용주의 원칙

- **YAGNI** 강함 — "지금 필요한 것만"
- **과설계 회피** — 3층 아키텍처, 컬럼 여러 개 추가 등 → 사용자가 "정말 필요해?" 로 되물음
- **기존 유지 최대한** — 새로 만들기보다 기존 잘 되는 걸 안 건드림
- **재작성 회피** — 옛 base 의 옛 PR 은 close + main 기준 fresh PR

## 자본 관점

- **자본 보존 최우선** — 원금 잃지 않는 게 목표. 알파 창출은 그 다음.
- **소액으로 승산 검증 후 확장** — 실 진입 전에 항상 paper 검증
- **감내 손실은 tight** — 시장 표준 (프로 desk 기준) 준수 지향

## 자동화 관점

- **완전 자동 선호** — Human-in-the-loop 은 최소화
- **destructive action 은 예외** — volume 삭제, force-push, branch 삭제 등은 항상 사람 결정
- **classifier 차단을 safety net 으로 활용** — 마찰이 아니라 원칙

## 감사/투명성

- **감사 최우선** — 재현 가능성 > 성능
- **모든 결정 이력 남기기** — commit body 상세, snapshot JSONB 저장, ADR 문서화
- **PR body 는 외부 독자 기준** — "왜, 무엇, 어떻게" 를 그 PR 만 보고도 이해 가능하게

## 소통 스타일

- **짧고 핵심 위주** — 장황함 싫어함
- **옵션 3-4개** 제시 좋아함 — 극단 A · 극단 B · 중간 or 대안
- **"추천" 표시** 있으면 대체로 그거 선택
- **완결감** — 각 대화가 마무리 문장으로 닫히는 것 선호

## 인프라 관점

- **OCI Ampere ARM64 단일 노드** 를 상당 기간 유지 가능 (확장 절제)
- **cloudflared Quick Tunnel** 로 외부 노출 (도메인 안 사면서 실제 접근 가능)
- **repo 3분리** — public app + private 운영식별자 + private Infisical 인프라
- **모든 시크릿은 Infisical** — 평문 .env 절대 금지

## Anti-patterns (사용자가 싫어하는 것)

- **과설계** — 지금 필요 없는 아키텍처 미리 짓기
- **중복 관리** — 두 곳 sync 필요한 것 (예: `market_data` + `ohlcv_daily` 이중 저장)
- **옛 base 재사용** — 마이그레이션 후 옛 브랜치 PR 그대로 머지
- **불필요한 마이그레이션** — 문제없이 잘 되는 기존 스키마 손대기
- **컬럼 캐시 남발** — join 이 잘 되고 있는데 성능 이유로 컬럼 추가
- **UI 표시만 있는 것** — 실 동작 없이 UI 만 예쁘게 만드는 것 (예: mode 토글 표시만, credential 미전환)
