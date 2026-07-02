# Interests / Collaboration Context

> **목적**: 새 세션 · 새 프로젝트 시작 시 참조. 사용자 성향 · Claude 협업 방식 · 반복 결정 축 · 프로젝트별 픽스된 결정을 재활용 가능한 형태로 정리.
> **첫 작성**: 2026-07-02

## Why this folder exists

세션마다 반복적으로 같은 성향/선호도/결정 축을 재확인하는 낭비를 줄인다. 그리고 **다른 프로젝트에서도 활용** 가능하도록 프로젝트-무관 정보와 프로젝트-특유 정보를 분리해 관리한다.

## 구조

```
docs/interests/
├── README.md                              ← 사용법 (이 파일)
├── USER_PROFILE.md                        ← 일반 사용자 성향 (프로젝트 무관)
├── CLAUDE_PERSONA.md                      ← 이 사용자와 잘 통하는 Claude 협업 방식
├── DECISION_PATTERNS.md                   ← 재사용 가능한 결정 축 카탈로그
└── projects/
    └── alpha-financial-pipeline.md        ← 이 프로젝트의 픽스된 결정
    └── (미래 프로젝트마다 파일 추가)
```

### 프로젝트-무관 vs 프로젝트-특유

**프로젝트 무관** (사용자 자체 성향, 어느 프로젝트에서도 유효):
- `USER_PROFILE.md`, `CLAUDE_PERSONA.md`, `DECISION_PATTERNS.md`

**프로젝트 특유** (이 프로젝트만의 픽스된 결정):
- `projects/alpha-financial-pipeline.md`
- 새 프로젝트 시작 시 그 프로젝트 파일 만들고 결정 축 재확정

**왜 분리?** — Investment Mandate (자본 보존, 단타 등) 는 이 알고리즘 트레이딩 프로젝트만의 결정. 다른 프로젝트 (예: 인프라 자동화, 데이터 파이프라인 등) 는 다른 축을 픽스. 그러나 **"감사 우선", "실용주의", "완결 vs 확장" 같은 상위 사고 축** 은 사용자 자체 성향이라 다 재활용 가능.

## 사용법

### 새 세션 초입 (같은 프로젝트)
1. `projects/이프로젝트.md` 확인 → 픽스된 결정 파악
2. `DECISION_PATTERNS.md` skim → 사용자 축별 선호 재상기
3. 사용자 첫 요청 반영 시 문서 인용 가능:
   `docs/interests/projects/alpha-financial-pipeline.md#investment-mandate` 등

### 새 프로젝트 시작
1. `projects/새프로젝트.md` 파일 생성
2. `DECISION_PATTERNS.md` 의 축 카탈로그 참고해 새 프로젝트의 축을 확정
3. `USER_PROFILE.md` · `CLAUDE_PERSONA.md` 는 그대로 재활용

### 갱신 시점
- 새 결정 축이 등장했는데 카탈로그에 없을 때 → `DECISION_PATTERNS.md` 추가
- 프로젝트 결정이 확정될 때 → `projects/이프로젝트.md` 갱신
- 사용자 일반 성향이 명시적으로 변할 때 → `USER_PROFILE.md` 갱신
- **갱신은 항상 PR** — main 에 바로 push 금지

## 원칙

1. **관찰 기반, 추측 X**: 대화에서 사용자가 실제로 표명한 것만 기록. "아마도" 추측은 삭제 대상.
2. **재사용 가능한 형태**: 서술문보다 표/리스트. 다른 세션에서 grep 가능하게.
3. **미래 자기 수정 가능**: 사용자가 "이제 아니다" 하면 즉시 갱신. 낡은 정보 방치는 잘못된 협업 유도.
4. **경량 유지**: 각 파일 500 lines 넘지 않기. 넘으면 세분화.
