#!/usr/bin/env bash
# Ротация паролей ВСЕХ сид-учёток SaaS-пресета (dev-пароль crm12345 публично
# лежит в git - перед выходом в интернет обязательно менять). Запуск на VPS:
#   bash /opt/retain-lab/rotate_saas_passwords.sh
# Печатает новый пароль (один на все 18 учёток; логин = e-mail, напр.
# super_admin@crm.local). Пароль также сохраняется в /opt/retain-lab/.admin_password (600).
set -euo pipefail

NEWPW=$(openssl rand -base64 18 | tr -d '/+=' | cut -c1-16)
DB=$(docker ps --format '{{.Names}}' | grep supabase_db | head -1)
[ -z "$DB" ] && { echo "ERROR: контейнер supabase_db не найден (supabase start?)"; exit 1; }

docker exec "$DB" psql -U postgres -d postgres -v pw="$NEWPW" -c \
  "UPDATE auth.users SET encrypted_password = extensions.crypt(:'pw', extensions.gen_salt('bf'));" >/dev/null

printf '%s\n' "$NEWPW" > /opt/retain-lab/.admin_password
chmod 600 /opt/retain-lab/.admin_password

echo "OK: пароли всех учёток обновлены."
echo "Логин:  super_admin@crm.local"
echo "Пароль: $NEWPW"
