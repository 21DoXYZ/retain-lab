FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Контекст (./ingest) содержит только код шлюза — копируем целиком,
# чтобы новый модуль не пришлось дописывать в этот список.
COPY . .

# gunicorn: несколько воркеров для параллельного приёма POST
CMD ["gunicorn", "-w", "4", "-b", "0.0.0.0:8081", "--access-logfile", "-", "app:app"]
