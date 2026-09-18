# 建置階段保留編譯工具，執行階段不攜帶它們
FROM python:3.10-slim AS builder

WORKDIR /app

COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.10-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# Run as an unprivileged user (defence in depth: a code path bug does not run as root).
RUN useradd --create-home --uid 10001 appuser

COPY --chown=appuser:appuser . .

USER appuser

ENV PORT 5000
EXPOSE 5000

# A finite worker timeout recycles a stuck thread instead of holding it forever
# (only 8 threads exist, so a few hung requests could otherwise exhaust the pool).
CMD exec gunicorn --bind :$PORT --workers 1 --threads 8 --timeout 120 --graceful-timeout 30 app:app
