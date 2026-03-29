# ================================================================
# Multi-stage Dockerfile — dev / prod 분리
#
# 빌드 타겟:
#   docker build --target dev  -t alpha-trading:dev .
#   docker build --target prod -t alpha-trading:prod .
#   docker build              -t alpha-trading:prod .   (기본=prod)
# ================================================================

# ── Stage 1: base (공통 의존성) ────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

# ── Stage 2: dev (기존 호환 — Claude CLI, Node.js, 볼륨 마운트용) ──
FROM base AS dev

# Node.js 설치 (Claude CLI npm 패키지에 필요)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI 설치
RUN npm install -g @anthropic-ai/claude-code \
    || echo "Claude CLI npm 설치 실패 — 호스트 CLI 마운트로 대체"
ENV PATH="/root/.claude/bin:/usr/lib/node_modules/.bin:${PATH}"

# dev에서는 테스트 의존성 포함
RUN pip install pytest pytest-asyncio pytest-mock

COPY src ./src
COPY scripts ./scripts
COPY .env.example ./.env.example

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ── Stage 3: prod (최소 이미지, non-root) ──────────────────────
FROM base AS prod

# 프로덕션에서는 gcc 제거 (빌드 완료)
RUN apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# non-root 사용자 생성
RUN groupadd -r alpha && useradd -r -g alpha -d /app -s /sbin/nologin alpha

# 앱 코드 복사 (테스트/개발 도구 제외)
COPY src ./src
COPY scripts ./scripts
# 소유권 변경
RUN chown -R alpha:alpha /app

USER alpha

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
