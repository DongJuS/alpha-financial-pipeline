FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Node.js 설치 (Claude CLI npm 패키지에 필요)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI 설치 (npm으로 Linux 네이티브 바이너리 설치)
# 호스트의 ~/.claude/ (인증 토큰)을 docker-compose에서 마운트하여 인증 공유
RUN npm install -g @anthropic-ai/claude-code \
    || echo "Claude CLI npm 설치 실패 — 호스트 CLI 마운트로 대체"
ENV PATH="/root/.claude/bin:/usr/lib/node_modules/.bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY .env.example ./.env.example

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
