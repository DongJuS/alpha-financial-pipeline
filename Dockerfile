FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc curl \
    && rm -rf /var/lib/apt/lists/*

# Claude CLI 설치
RUN curl -fsSL https://cli.anthropic.com/install.sh | sh 2>/dev/null \
    || echo "Claude CLI 설치 스킵 (호스트 바이너리 마운트로 대체 가능)"
ENV PATH="/root/.claude/bin:${PATH}"

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY src ./src
COPY scripts ./scripts
COPY .env.example ./.env.example

EXPOSE 8000

CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
