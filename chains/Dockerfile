# chain-runner. Образец — signals/Dockerfile, но контекст сборки = КОРЕНЬ репо
# (docker-compose: build.context = ., dockerfile = chains/Dockerfile), потому что
# runner для узлов-condition переиспользует компилятор сегментов из api/
# (api/segment_compiler.py + api/segment_fields.py). Компилятор грузится напрямую
# из файлов (chains/runner.py::_load_compiler), БЕЗ пакета api/__init__ — flask в
# образ не тянем.
FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY chains/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Только нужное: код раннера и два файла компилятора сегментов (реестр + компилятор).
COPY chains/ ./chains/
COPY api/segment_fields.py api/segment_compiler.py ./api/

# Пакет chains импортируется как модуль → запускаем из корня /app.
CMD ["python", "-m", "chains.runner"]
