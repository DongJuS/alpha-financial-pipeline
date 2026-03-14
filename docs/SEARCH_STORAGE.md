# 🗃️ SEARCH_STORAGE.md — 검색/스크래핑 저장 구조 메모

> 검색 파이프라인의 재현성과 감사 가능성을 확보하기 위한 저장 단위를 정리합니다.

---

## 1. 저장 원칙

- query, result, source, extraction을 분리 저장합니다.
- 동일 source는 여러 query에서 재사용될 수 있어야 합니다.
- extraction은 source와 prompt/config 버전을 함께 기록해야 합니다.

---

## 2. 권장 엔터티

| 엔터티 | 설명 |
|--------|------|
| `research_queries` | 검색 요청 메타데이터 |
| `research_results` | 검색 결과 목록과 순위 정보 |
| `research_sources` | fetch/render 후 확보한 원문 및 메타데이터 |
| `research_extractions` | Claude 기반 추출 결과 |
| `research_feature_views` | 전략/RL 소비용 요약 뷰 |

---

## 3. 최소 필드 예시

### `research_queries`
- `query_id`
- `ticker`
- `query_text`
- `intent`
- `requested_at`
- `status`

### `research_results`
- `result_id`
- `query_id`
- `url`
- `title`
- `snippet`
- `rank`
- `domain`

### `research_sources`
- `source_id`
- `url`
- `fetched_at`
- `http_status`
- `content_hash`
- `structured_payload`

### `research_extractions`
- `extraction_id`
- `source_id`
- `model`
- `prompt_version`
- `extracted_facts`
- `summary`
- `confidence`
- `created_at`

---

## 4. 보존 정책

- 검색 질의와 extraction 메타데이터는 장기 보존
- 원문 HTML/렌더 결과는 저장 비용과 법적 요구를 고려해 정책화
- content hash를 남겨 중복 수집 여부를 판단

---

*Last updated: 2026-03-14*
