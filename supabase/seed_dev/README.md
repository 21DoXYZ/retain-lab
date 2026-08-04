# Демо-сид (НЕ в цепочке миграций)

`0003_seed.sql` заводит 18 демо-учёток (пароль у всех `crm12345`, включая
**super_admin**) и демо-данные по игрокам 900001–900020.

## Почему он лежит здесь, а не в `supabase/migrations/`

Пока файл был в `migrations/`, `supabase start` и `supabase db reset` применяли его
**автоматически** вместе со всей цепочкой — то есть демо-учётки заводились и там, где
их быть не должно. Ровно от этого предупреждал и сам файл в шапке («для боевого деплоя
исключить из пуша»), и записка о деплое.

На VPS (рабочая CRM) сид был применён по ошибке и удалён вручную; чтобы он не вернулся
при следующем `db reset`, файл выведен из цепочки.

## Как применить локально, если нужны демо-роли

```bash
supabase db reset                       # чистая база без демо-учёток
psql "$SUPABASE_DB_URL" -f supabase/seed_dev/0003_seed.sql
```

## Как завести реального пользователя (прод)

Через Admin API GoTrue — он корректно хеширует пароль и заводит identity;
роль хук `custom_access_token_hook` (0004) берёт из `crm.crm_users`:

```bash
UID=$(curl -s -X POST "$SUPABASE_URL/auth/v1/admin/users" \
  -H "apikey: $SERVICE_ROLE_KEY" -H "Authorization: Bearer $SERVICE_ROLE_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"<сильный пароль>","email_confirm":true}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

psql "$SUPABASE_DB_URL" -c "INSERT INTO crm.crm_users
  (id, full_name, role, department, affiliate_code, is_active, created_by)
  VALUES ('$UID', 'Имя', 'operator', 'retention', '', true, '$UID');"
```

Значения enum: `crm.department` = retention | call_center | whatsapp.
