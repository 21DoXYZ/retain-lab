#!/usr/bin/env bash
# Регенерация локальных файлов-секретов из .env (они в .gitignore и могут
# пропасть при git clean/discard). Запуск:  ./gen_secrets.sh  (потом restart clickhouse/caddy)
set -euo pipefail
cd "$(dirname "$0")"
CHP=$(sed -n 's/^CH_PASSWORD=//p' .env)
CU=$(sed -n 's/^KAFKA_CONSUMER_USER=//p' .env)
CP=$(sed -n 's/^KAFKA_CONSUMER_PASS=//p' .env)
mkdir -p ch_users.d ch_config.d certs
cat > ch_users.d/default-password.xml <<X
<clickhouse><users><default>
    <password>${CHP}</password>
    <networks><ip>::/0</ip></networks>
</default></users></clickhouse>
X

# Профиль памяти (баг Б1: «Деньги не открываются»). Живёт в ch_users.d/ (там же,
# где пароль), поэтому директория gitignore'ится — файл пересоздаём здесь, чтобы
# он не терялся при git clean. Спилл тяжёлых агрегаций на диск + лимит на запрос:
# при одновременных тяжёлых запросах OvercommitTracker больше не убивает их -> нет
# 500 на /ggr и /money/overview. RAM реально ~1 ГБ из 15 — упираемся не в железо.
cat > ch_users.d/profiles.xml <<X
<clickhouse>
    <profiles>
        <default>
            <max_memory_usage>6000000000</max_memory_usage>
            <max_bytes_before_external_group_by>2000000000</max_bytes_before_external_group_by>
            <max_bytes_before_external_sort>2000000000</max_bytes_before_external_sort>
        </default>
    </profiles>
</clickhouse>
X
cat > ch_config.d/kafka.xml <<X
<clickhouse><kafka>
    <security_protocol>sasl_plaintext</security_protocol>
    <sasl_mechanism>SCRAM-SHA-256</sasl_mechanism>
    <sasl_username>${CU}</sasl_username>
    <sasl_password>${CP}</sasl_password>
</kafka></clickhouse>
X
[ -f certs/key.pem ] || openssl req -x509 -newkey rsa:2048 -nodes -keyout certs/key.pem -out certs/cert.pem -days 3650 \
  -subj "/CN=72.62.146.171" -addext "subjectAltName=IP:72.62.146.171,DNS:localhost,IP:127.0.0.1" 2>/dev/null
echo "секреты сгенерированы: ch_users.d/ ch_config.d/kafka.xml certs/"
