FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Контекст (./signals) содержит только код сигналов — копируем целиком,
# чтобы новый модуль не пришлось дописывать в этот список.
COPY . .

CMD ["python", "pusher.py"]
