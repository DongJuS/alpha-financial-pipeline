# 실시간 틱 수집 스케줄링 방식 결정

status: open
created_at: 2026-04-11
topic_slug: realtime-tick-scheduling
related_files:
- src/schedulers/unified_scheduler.py
- src/agents/collector/_realtime.py
- src/agents/collector/__init__.py

**⚠️ 본 문서는 `20260411-tick-collector-service-design.md`로 대체됨.** 100종목 스케일링 분석 결과 크론잡 추가(Option A) 대신 별도 서비스(Option B) 채택.

## 1. 핵심 질문

WebSocket 틱 수집 코드가 완성되어 있으나 unified_scheduler에 등록되지 않아 자동 실행되지 않는 문제를 어떻게 해결할 것인가.

## 2. 배경

- `_realtime.py`에 KIS WebSocket 틱 수집 코드 완성 (구독, 파싱, 배치 flush, 재연결)
- `unified_scheduler.py`에 10개 크론잡 등록되어 있으나 틱 수집은 없음
- `collector_daily` (08:30)는 `collect_daily_bars()`만 호출, `collect_realtime_ticks()`는 미호출
- 현재 CLI 수동 실행만 가능: `python -m src.agents.collector --realtime`
- 틱 축적은 RL 분봉 피처 확장의 선행 조건 (40영업일 필요)

## 3. 제약 조건

- 월 운영비 5,000~10,000원 이내
- 로컬 K3s 환경 (메모리 제한적)
- 현재 3종목만 수집
- KIS WebSocket 연결 당 최대 40종목
- 장중 시간: 09:00~15:30 KST (6.5시간)

## 4. 선택지 비교

| 선택지 | 장점 | 단점 | 비용/복잡도 |
|--------|------|------|------------|
| A. 크론잡 2개 추가 (시작+헬스체크) | 기존 스케줄러 활용, 최소 변경 | API 서버와 생명주기 공유 | 낮음 |
| B. 별도 워커 프로세스 | 격리된 생명주기, API 재시작에 무관 | 관리 포인트 증가, 프로세스 감시 필요 | 중간 |
| C. 사이드카 컨테이너 (K8s) | 완전 격리, K8s 네이티브 헬스체크 | 메모리 부담, K3s에 과도 | 높음 |

## 5. 결정 사항

### 5.1 결정

**A. unified_scheduler에 크론잡 2개 추가** 채택.

- **확장성:** 종목 수 증가 시 `max_tickers_per_ws=40` 범위 내에서 설정만 변경. 40종목 초과 시 별도 프로세스 분리를 그때 검토.
- **안전:** 헬스체크 잡이 5분마다 생존 확인 + 자동 재시작 + Telegram 알림. Pod 재시작 시에도 다음 주기에 자동 복구.
- **관리 수월함:** 기존 스케줄러 패턴(distributed lock, job wrapper) 그대로 활용. 새로운 인프라 구성 요소 없음.

3종목 · 1인 운영 · 로컬 K3s 규모에서 별도 프로세스/사이드카는 과도하다.

### 5.2 트레이드오프

- API 서버 Pod이 죽으면 틱 수집도 중단됨 → 헬스체크 재시작으로 보완 (최대 5분 갭)
- 6.5시간 장기 태스크가 API 이벤트 루프를 공유 → 3종목 수준에서 경합 무시 가능. 종목 증가 시 재검토.

## 6. 실행 계획

| 순서 | 항목 | 변경 대상 파일 | 완료 기준 |
|------|------|---------------|----------|
| 1 | CollectorAgent에 `_realtime_task` 속성 추가 | `src/agents/collector/__init__.py` | 태스크 참조 보관 가능 |
| 2 | `tick_realtime_start` 잡 등록 (09:00 KST 평일) | `src/schedulers/unified_scheduler.py` | 장 시작 시 `collect_realtime_ticks()` 백그라운드 spawn |
| 3 | `tick_realtime_health` 잡 등록 (5분 인터벌, 09:05~15:30) | `src/schedulers/unified_scheduler.py` | 태스크 죽으면 재시작 + Telegram 알림 |
| 4 | 통합 테스트 | `test/` | 잡 등록 확인 + mock 헬스체크 시나리오 |

## 7. 참조

### 7.1 참고 파일

- `src/schedulers/unified_scheduler.py` — 기존 10개 크론잡 등록 구조 확인
- `src/agents/collector/_realtime.py` — WebSocket 틱 수집 구현 (collect_realtime_ticks, _ws_collect_loop)
- `src/agents/collector/__init__.py` — CollectorAgent 파사드, CLI 진입점
- `src/schedulers/job_wrapper.py` — 잡 래퍼 (retry + 실행 이력)
- `src/schedulers/distributed_lock.py` — Redis 분산 락
- `src/utils/config.py:200-210` — WebSocket 설정 (batch_size, flush_interval)

### 7.2 참고 소스

없음.

### 7.3 영향받는 파일

- `src/schedulers/unified_scheduler.py` — 잡 2개 등록
- `src/agents/collector/__init__.py` — `_realtime_task` 속성 추가

## 8. Archive Migration

> 구현 완료 후 아카이브 시 아래 내용을 `MEMORY-archive.md`에 기록한다.
> 200자(한글 기준) 이내, 배경지식 없이 이해 가능하게 작성.

```
(구현 완료 후 작성)
```

## 9. Closure Checklist

- [x] 구조/장기 방향 변경 → `.agent/roadmap.md` 반영
- [x] 이번 세션 할 일 → `progress.md` 반영
- [ ] 운영 규칙 → `MEMORY.md` 반영
- [ ] 섹션 8의 Archive Migration 초안 작성
- [ ] `/discussion --archive <이 파일>` 실행
