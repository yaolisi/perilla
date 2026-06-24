FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements/base.txt /tmp/requirements-base.txt
COPY backend/requirements/ubuntu.txt /tmp/requirements-ubuntu.txt

RUN pip install --upgrade pip \
    && pip install -r /tmp/requirements-base.txt -r /tmp/requirements-ubuntu.txt

COPY backend/ /app/backend/

RUN mkdir -p /app/backend/data /app/backend/logs \
    && groupadd --gid 1000 appuser \
    && useradd --uid 1000 --gid appuser --home /app/backend --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app/backend

USER appuser

EXPOSE 8000

# 使用 python main.py，使 Settings 中的 uvicorn_*（代理头、并发上限、关停超时等）传入 uvicorn.run，与 Helm 注入的 UVICORN_* / FORWARDED_ALLOW_IPS 一致
CMD ["python", "main.py"]
