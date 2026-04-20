FROM python:3.11-slim

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

RUN mkdir -p /app/backend/data /app/backend/logs

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
