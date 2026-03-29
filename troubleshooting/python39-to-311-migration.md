# Python 3.9 → 3.11 마이그레이션

> 생성일: 2026-03-29
> 상태: 진행 중
> 관련 PR: #45

---

## 배경

프로젝트 요구사항은 Python 3.11+이지만 로컬 개발 환경은 시스템 Python 3.9.6이었음.
Python 3.11.15를 `brew install python@3.11`로 설치하여 테스트 실행 환경을 전환함.

## 3.11 전환으로 해결된 이슈

1. **`X | None` union 문법** — 3.9에서 `TypeError: unsupported operand type(s) for |`
   - `from __future__ import annotations`를 4개 테스트 파일에 추가하여 3.9에서도 호환되도록 조치
   - 3.11에서는 네이티브 지원

2. **pytest-asyncio event loop 생성** — 3.9에서 `RuntimeError: There is no current event loop`
   - 3.11에서 개선되었지만 `asyncio.run()` 오염 문제는 여전히 존재 (별도 트러블슈팅 참조)

## 남은 이슈

### 1. 시스템 Python과의 공존
- `python3` → 3.9.6 (시스템)
- `python3.11` → 3.11.15 (brew)
- CI에서는 `python3.11`을 명시적으로 사용해야 함
- `Dockerfile`은 `python:3.11-slim` 베이스이므로 프로덕션에서는 문제 없음

### 2. 의존성 이중 설치
- `python3.11 -m pip install -r requirements.txt`로 별도 설치 완료
- `python3`(3.9)용 site-packages와 `python3.11`용 site-packages가 별도 관리됨
- venv 미사용 → 글로벌 설치 상태

### 3. 3.11 전용 기능 사용 가능성
- `match` 구문 (3.10+)
- `ExceptionGroup` / `except*` (3.11+)
- `tomllib` (3.11+)
- 현재 코드에서는 사용하지 않지만, 향후 도입 시 Dockerfile 및 CI 환경 확인 필요

## 권장 사항

1. **venv 도입**: `python3.11 -m venv .venv && source .venv/bin/activate`
2. **CI 환경**: GitHub Actions에서 `python-version: '3.11'` 명시
3. **pyproject.toml**: `requires-python = ">=3.11"` 명시

---

*작성: 2026-03-29*
