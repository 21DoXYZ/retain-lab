#!/usr/bin/env bash
# Смена пароля пользователя CRM (Supabase/GoTrue). По умолчанию пароль ГЕНЕРИРУЕТСЯ.
#
# ПОЧЕМУ СКРИПТ ОТКАЗЫВАЕТСЯ РАБОТАТЬ БЕЗ ТЕРМИНАЛА.
# Сгенерированный пароль нужно показать человеку — а показ и есть та операция,
# на которой он утекает. Поэтому:
#   • пароль печатается НЕ в stdout, а прямо в /dev/tty — то есть на живой экран.
#     Если вывод скрипта перехватывают (агент, `| tee`, `> log`, CI), в перехват
#     попадёт всё, КРОМЕ пароля;
#   • при этом скрипт вообще не стартует, если stdout не терминал — иначе кто-то
#     запустил бы его через агента, и пароль осел бы в чужом транскрипте
#     (именно так был скомпрометирован предыдущий пароль admin@21do.xyz);
#   • в curl пароль уходит через stdin, а не аргументом -d "..." — иначе был бы
#     виден в `ps aux` любому процессу машины;
#   • bash-переменная с паролем не создаётся: python генерирует его, печатает в
#     /dev/tty и отдаёт в curl JSON'ом. Значит пароль не попадёт ни в set -x,
#     ни в дамп окружения, ни в ~/.bash_history.
#
# Запуск (ЛИЧНО в своём SSH):
#   ./rotate_crm_password.sh                     # admin@21do.xyz, пароль сгенерируется
#   ./rotate_crm_password.sh user@example.com    # другому пользователю
#   ./rotate_crm_password.sh --manual [email]    # ввести свой пароль вручную (скрыто)
set -euo pipefail
cd "$(dirname "$0")"

MANUAL=0
if [ "${1:-}" = "--manual" ]; then MANUAL=1; shift; fi
EMAIL="${1:-admin@21do.xyz}"

# ── Защита от запуска «через кого-то»: нужен настоящий терминал ──────────────────
if [ ! -t 1 ] || ! { : > /dev/tty; } 2>/dev/null; then
  cat >&2 <<'EOF'
Отказ: нет интерактивного терминала.

Скрипт показывает пароль на экран и не запускается там, где вывод могут
перехватить (агент, пайп, редирект в файл, CI) — иначе пароль осядет в логе
или транскрипте. Зайди по SSH и запусти его руками:

    cd /home/retention-board && ./rotate_crm_password.sh
EOF
  exit 1
fi

SB_URL=$(sed -n 's/^SUPABASE_URL=//p' .env | head -1)
SB_URL="${SB_URL:-http://127.0.0.1:54321}"

# service_role спрашиваем у самого стека — копию ключа в репозитории не держим
SR=$(supabase status -o json 2>/dev/null \
     | python3 -c "import sys,json;print(json.load(sys.stdin).get('SERVICE_ROLE_KEY',''))" 2>/dev/null || true)
[ -n "$SR" ] || { echo "Не удалось получить SERVICE_ROLE_KEY — запущен ли стек? (supabase status)" >&2; exit 1; }

UID_=$(docker exec -e PGPASSWORD=postgres supabase_db_Dima_ret \
        psql -U postgres -d postgres -tA \
        -c "SELECT id FROM auth.users WHERE email='${EMAIL}'" 2>/dev/null | tr -d '[:space:]')
[ -n "$UID_" ] || { echo "Пользователь ${EMAIL} не найден." >&2; exit 1; }

set_password() {   # stdin: JSON {"password": "..."} -> HTTP-код
  curl -s -o /dev/null -w '%{http_code}' -X PUT "${SB_URL}/auth/v1/admin/users/${UID_}" \
    -H "apikey: ${SR}" -H "Authorization: Bearer ${SR}" \
    -H "Content-Type: application/json" --data-binary @-
}

if [ "$MANUAL" = "1" ]; then
  read -rsp "Новый пароль для ${EMAIL}: " P1; echo
  read -rsp "Повтори: " P2; echo
  [ "$P1" = "$P2" ] || { echo "Пароли не совпали." >&2; exit 1; }
  [ ${#P1} -ge 12 ] || { echo "Слишком короткий: минимум 12 символов." >&2; exit 1; }
  CODE=$(P="$P1" python3 -c 'import json,os;print(json.dumps({"password":os.environ["P"]}))' | set_password)
  unset P1 P2
else
  # Пароль живёт только внутри python: на экран (/dev/tty) и в JSON для curl.
  CODE=$(EMAIL="$EMAIL" python3 - <<'PY' | set_password
import secrets, string, json, os
alphabet = string.ascii_letters + string.digits + '!@#%^*-_=+'
pw = ''.join(secrets.choice(alphabet) for _ in range(28))
with open('/dev/tty', 'w') as tty:
    tty.write('\n' + '═' * 64 + '\n')
    tty.write(f"  Пользователь: {os.environ['EMAIL']}\n")
    tty.write(f"  Новый пароль: {pw}\n")
    tty.write('  Сохрани его сейчас — восстановить нельзя, только сменить заново.\n')
    tty.write('═' * 64 + '\n')
print(json.dumps({'password': pw}))
PY
  )
fi

if [ "$CODE" != "200" ]; then
  echo "✗ Не удалось сменить пароль (HTTP ${CODE})." >&2
  exit 1
fi
echo "✓ Пароль ${EMAIL} обновлён."

# Гасим живые сессии: смена пароля сама по себе НЕ инвалидирует уже выданные
# refresh-токены — по ним можно было бы продолжать входить со старым доступом.
docker exec -e PGPASSWORD=postgres supabase_db_Dima_ret psql -U postgres -d postgres -q \
  -c "DELETE FROM auth.refresh_tokens WHERE user_id = '${UID_}';
      DELETE FROM auth.sessions       WHERE user_id = '${UID_}'::uuid;" >/dev/null 2>&1 \
  && echo "✓ Старые сессии и refresh-токены отозваны." \
  || echo "⚠ Пароль сменён, но сессии отозвать не удалось — проверь вручную." >&2
