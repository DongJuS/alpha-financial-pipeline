# AI Handoff

작성일: 2026-03-14  
목적: 이 프로젝트를 다른 AI에게 인수인계할 때, 사용자 의도와 현재 상태를 헷갈리지 않게 전달하기 위한 요약 문서입니다.

---

## 1. 사용자 의도 요약

이 프로젝트는 기존 멀티 에이전트 한국 주식 투자 시스템을 유지한 채, 아래 두 기능을 구조적으로 추가하려는 상태입니다.

1. 강화학습 트레이딩
2. 검색/스크래핑 기반 리서치 파이프라인

중요한 점:

- 이 둘은 "넣을지 말지 검토하는 실험 후보"가 아니라, 구조에 편입되는 추가 기능입니다.
- 기존 Strategy A / Strategy B / PortfolioManager / paper-real 실행 구조는 유지합니다.
- 새 기능은 기존 시스템을 대체하는 것이 아니라 레이어로 추가합니다.

---

## 2. 절대 헷갈리면 안 되는 규칙

다음 항목은 다음 AI가 반드시 지켜야 합니다.

### 문서 편집 원칙

- 기존 문서의 원문은 가능한 한 유지합니다.
- 새 방향을 반영할 때는 기존 내용을 갈아엎지 말고, 하단 또는 별도 섹션에 "확장" 형태로 추가합니다.
- 특히 이번 문서 작업에서 사용자는 "기존 내용은 그대로 두고 확장만 하라"는 의도를 분명히 밝혔습니다.

### 강화학습 관련 원칙

- RL Trading은 기존 Strategy A/B를 대체하지 않습니다.
- RL 정책은 직접 브로커를 호출하면 안 됩니다.
- 최종 주문 권한은 계속 `PortfolioManagerAgent`에만 있어야 합니다.

### 검색/스크래핑 관련 원칙

- Tavily는 사용하지 않습니다.
- 검색 스택은 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI` 방향으로 갑니다.
- ScrapeGraphAI는 페이지 구조화/파싱 역할입니다.
- 최종 추출/요약/판단은 Claude CLI 계층이 맡습니다.

### README 상태 표기 원칙

- README에는 현재 RL과 검색 스택을 `통합 테스트 진행 중`으로 적습니다.
- 이 문구는 실제 검증 완료 후 운영 상태에 맞게 반드시 수정해야 합니다.

### Gemini 관련 원칙
- Gemini는 OAuth(ADC) 우선 경로를 사용합니다.

---

## 3. 현재까지 반영된 문서 상태

다음 파일들은 기존 본문을 유지한 상태에서, 하단 확장 섹션만 추가된 상태입니다.

- `CLAUDE.md`
- `README.md`
- `architecture.md`
- `docs/BOOTSTRAP.md`

현재 이 4개 파일의 diff는 "기존 내용 수정"이 아니라 "하단 추가" 형태입니다.

이미 구조 방향이 반영되어 있는 파일:

- `.agent/roadmap.md`
- `.agent/tech_stack.md`

이 두 파일은 현재 다음 방향을 담고 있습니다.

- RL Trading lane 구조 편입
- `SearXNG -> ScrapeGraphAI -> Claude CLI` 검색 파이프라인
- Tavily 미사용
- Gemini CLI 미사용

---

## 4. 아직 해야 하는 문서 작업

다음 작업은 아직 남아 있습니다.

### 우선순위 높음

1. `docs/api_spec.md`
2. `docs/AGENTS.md`
3. `.agent/roadmap.md`
4. RL 관련 별도 문서 추가
5. 검색/스크래핑 관련 별도 문서 추가

### `docs/api_spec.md`에 추가할 내용

기존 명세를 유지한 채 하단에 확장 API 메모를 붙이는 방식이 좋습니다.

추가 후보:

- RL 학습 실행 API
- RL 평가 결과 조회 API
- RL 정책 목록/활성 정책 조회 API
- 검색 실행 API
- 검색 결과/스크랩 결과 조회 API
- 출처 문서/추출 결과 조회 API

### `.agent/roadmap.md`에 추가할 내용

RL trading에서 앞으로 개발 할 일들을 넣기

### `docs/AGENTS.md`에 추가할 내용

여기는 확정형보다 "추가 예정 agent 역할"로 쓰는 것이 안전합니다.

권장 후보:

- `rl_data_builder_agent`
- `rl_trainer_agent`
- `rl_evaluator_agent`
- `rl_policy_agent`
- `search_query_agent`
- `scrape_worker_agent`
- `claude_extraction_agent`

주의:

- 아직 역할을 너무 고정적으로 쓰면 문서가 빨리 낡을 수 있습니다.
- 따라서 `planned` 또는 `extension agents` 섹션으로 두는 편이 좋습니다.

### 새로 만들 별도 문서 후보

- `docs/RL_TRADING.md`
- `docs/RL_ARCHITECTURE.md`
- `docs/RL_EVALUATION.md`
- `docs/SEARCH_STACK.md`
- `docs/SEARCH_PIPELINE.md`
- 필요 시 `docs/SEARCH_STORAGE.md`

---

## 5. 현재 코드/프로젝트 상태에 대한 사실 요약

다음은 문서 작업을 진행할 AI가 알아야 할 현재 코드베이스의 큰 상태입니다.

- 코어 트레이딩 시스템은 이미 존재합니다.
- Strategy A / Strategy B / PortfolioManager / paper-real 구조는 이미 있습니다.
- 장외 주문 차단 정책도 이미 있습니다.
- 모델 관리 화면과 paper/real 제어도 이미 있습니다.
- RL Trading은 이제 최소 runnable lane이 구현되어 있으며, `train -> evaluate -> infer -> order route` 자동 검증 경로도 존재합니다.
- 다만 RL lane은 아직 운영 최종형이 아니라 통합 테스트 진행 중인 확장 기능입니다.
- 검색/스크래핑 스택도 아직 실제 구현 완료 상태는 아니고, 방향 확정 및 문서 반영 단계입니다.

즉:

- "코어는 존재"
- "RL/Search는 구조에 편입 중"
- "README 표기는 통합 테스트 진행 중"

---

## 6. 작업 방식 가이드

다음 AI는 아래 방식으로 진행하는 것이 안전합니다.

1. 기존 문서 본문은 유지한다.
2. 확장 내용은 하단에 추가한다.
3. 새 기능은 별도 `docs/` 파일로 분리한다.
4. RL/Search를 기존 시스템의 대체처럼 표현하지 않는다.
5. 주문 권한은 계속 `PortfolioManagerAgent`에 집중된다고 쓴다.
6. Tavily나 Gemini CLI 같은 폐기 방향을 다시 되살리지 않는다.

---

## 7. 현재 워크트리 주의사항

이 저장소는 현재 dirty worktree 상태일 수 있습니다.  
문서 작업 외에도 백엔드, UI, 설정 관련 수정이 이미 섞여 있습니다.

따라서 다음 AI는:

- 먼저 `git status`를 확인해야 합니다.
- 자신이 하지 않은 변경을 되돌리면 안 됩니다.
- 문서 작업을 하더라도 unrelated change를 덮어쓰지 않도록 주의해야 합니다.

---

## 8. 다음 AI에게 바로 줄 수 있는 짧은 인수인계 문구

아래 문장을 그대로 다음 AI에게 전달해도 됩니다.

> 이 프로젝트는 기존 Strategy A/B 기반 멀티 에이전트 트레이딩 시스템 위에 RL Trading과 Search/Scraping pipeline을 추가하는 중이다. 둘 다 구조에 포함되는 기능이며, 기존 시스템을 대체하지 않는다. 문서 작업 시 기존 본문은 유지하고 확장 섹션만 추가해야 한다. Search stack은 Tavily가 아니라 `SearXNG -> 웹 페이지 접속 -> ScrapeGraphAI -> Claude CLI` 방향이다. Gemini CLI는 쓰지 않고 OAuth 기반만 쓴다. RL Trading은 최소 runnable lane과 자동 검증 경로가 이미 추가되었지만, 여전히 운영 최종형이 아니라 `통합 테스트 진행 중` 상태다.

---

## 9. 참고 파일

- `CLAUDE.md`
- `README.md`
- `architecture.md`
- `docs/BOOTSTRAP.md`
- `docs/api_spec.md`
- `docs/AGENTS.md`
- `.agent/roadmap.md`
- `.agent/tech_stack.md`
