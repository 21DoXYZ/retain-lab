FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Проект целиком. Раньше файлы перечислялись поимённо, и каждый новый модуль
# (api/, tegsoft/, …) ронял борд в краш-цикл: `from api import register_api` ->
# ModuleNotFoundError. Что НЕ должно попасть в образ (секреты, PII, crm-spa) —
# исключено в .dockerignore, правим только его.
COPY . .

# в контейнере слушаем 0.0.0.0 (наружу публикуем только на 127.0.0.1 — см. compose)
ENV BOARD_HOST=0.0.0.0 BOARD_PORT=8050 CH_HOST=clickhouse CH_PORT=8123 CH_DB=retention
EXPOSE 8050
CMD ["python", "player_board.py"]
