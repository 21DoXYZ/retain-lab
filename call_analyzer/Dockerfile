# Call Analyzer (ingest-API + celery-воркер) — dev spec §12.
# Контекст сборки — КОРЕНЬ репозитория (как Dockerfile.scorer): пакет должен
# импортироваться по имени `call_analyzer`, а requirements-analyzer.txt лежит в корне.
#   build:
#     context: .
#     dockerfile: call_analyzer/Dockerfile
FROM python:3.12-slim

WORKDIR /app

# ca-certificates — для HTTPS к OpenRouter/Gladia
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-analyzer.txt .
RUN pip install --no-cache-dir -r requirements-analyzer.txt

# только пакет анализатора (scoring.py уже внутри). tegsoft/api/crm-spa не нужны.
COPY call_analyzer ./call_analyzer

ENV PYTHONPATH=/app PYTHONUNBUFFERED=1

# API слушает 0.0.0.0:8090 ВНУТРИ docker-сети; наружу порт не публикуется (см. compose).
EXPOSE 8090
CMD ["uvicorn", "call_analyzer.ingest_api:app", "--host", "0.0.0.0", "--port", "8090"]
