/**
 * ru · домен «admin» — базовые (русские) строки. Этот файл — ИСТОЧНИК КЛЮЧЕЙ:
 * ключ обязан быть здесь, иначе он не MessageKey. Переводы — en/admin.ts, tr/admin.ts.
 * Ключи: "admin.<имя>" (плоские, через точку). Интерполяция: {var}.
 */
export const admin = {
  // Роли (подписи) — используются в UsersAdmin и везде, где показывается
  // ROLE_LABELS[role] (lib/permissions.ts — данные, сам файл не трогаем).
  "admin.role.super_admin": "Супер-админ",
  "admin.role.director": "Директор",
  "admin.role.head_retention": "Глава ретеншена",
  "admin.role.head_department": "Глава отдела",
  "admin.role.operator": "Оператор",
  "admin.role.vip_manager": "VIP-менеджер",
  "admin.role.affiliate_manager": "Трафик-менеджер",
  "admin.role.marketing_manager": "Маркетинг",
  "admin.role.analyst": "Аналитик",
  "admin.role.finance": "Финансист",
  "admin.role.risk_officer": "Риск-офицер",
  "admin.role.support": "Саппорт",
  "admin.role.affiliate": "Аффилиат",
  "admin.role.viewer": "Гость",

  // Отделы (подписи) — DEPT_LABELS[dept].
  "admin.dept.retention": "Ретеншн",
  "admin.dept.call_center": "Колл-центр",
  "admin.dept.whatsapp": "WhatsApp",

  // /admin/users — заголовок и шапка
  "admin.users.title": "Пользователи",
  "admin.users.lead":
    "Создание, блокировка, сброс пароля и передача игроков. Каждое действие пишется в журнал (audit_log).",
  "admin.users.createOperator": "+ Сотрудник",
  "admin.users.createAffiliate": "+ Кабинет аффилиата",

  // Таблица
  "admin.users.col.name": "Имя",
  "admin.users.col.login": "Логин",
  "admin.users.col.role": "Роль",
  "admin.users.col.scope": "Отдел / код",
  "admin.users.col.status": "Статус",
  "admin.users.col.actions": "Действия",
  "admin.users.status.active": "активна",
  "admin.users.status.blocked": "заблокирована",
  "admin.users.action.block": "Блок",
  "admin.users.action.unblock": "Разблок",
  "admin.users.action.password": "Пароль",
  "admin.users.action.delete": "Удалить",

  // Модалки — заголовки
  "admin.users.modal.createAffiliateTitle": "Кабинет аффилиата",
  "admin.users.modal.createUserTitle": "Новый пользователь",
  "admin.users.modal.resetTitle": "Сброс пароля",
  "admin.users.modal.deleteTitle": "Удаление с передачей игроков",

  // Кнопки общего назначения
  "admin.users.btn.cancel": "Отмена",
  "admin.users.btn.create": "Создать",
  "admin.users.btn.save": "Сохранить",

  // Форма создания
  "admin.users.field.name": "Имя",
  "admin.users.field.namePlaceholder": "Например, Mehmet Yilmaz",
  "admin.users.field.loginEmail": "Логин (e-mail)",
  "admin.users.field.loginHint": "используется для входа",
  "admin.users.field.role": "Роль",
  "admin.users.field.dept": "Отдел",
  "admin.users.field.affCode": "Affiliate-код",
  "admin.users.field.affCodeHint": "например, AF104",
  "admin.users.field.password": "Пароль",
  "admin.users.field.passwordHint":
    "если пусто — временный crm12345, сменить при первом входе",

  // Модалка сброса пароля
  "admin.users.resetBody": "Пользователь: {name} ({email})",
  "admin.users.field.newPassword": "Новый пароль",
  "admin.users.field.newPasswordHint": "минимум 6 символов",
  "admin.users.field.newPasswordPlaceholder": "новый пароль",

  // Модалка удаления
  "admin.users.deleteBody":
    "Удаляется: {name} ({email}). Его назначенные игроки будут переданы выбранному оператору (история заметок и звонков едет с игроком).",
  "admin.users.field.reassignTo": "Передать игроков оператору",
  "admin.users.field.reassignHint":
    "можно оставить пустым — тогда очередь просто закроется",
  "admin.users.reassignNone": "— не передавать —",

  // Флэш-сообщения
  "admin.users.flash.created": "Пользователь создан",
  "admin.users.flash.blocked": "Учётка заблокирована",
  "admin.users.flash.unblocked": "Учётка разблокирована",
  "admin.users.flash.passwordChanged": "Пароль изменён",
  "admin.users.flash.deleted": "Пользователь удалён, игроки переданы",
  "admin.users.flash.errorStatus": "Ошибка ({status})",
  "admin.users.flash.networkError": "Сеть недоступна",

  // Машинные коды ошибок из app/api/admin/users/*route.ts (fail(msg, status, code)).
  // UsersAdmin.tsx переводит по code, если он есть и замаплен; иначе показывает
  // json.error как раньше (RU-текст с сервера) — так динамические ошибки
  // Supabase/GoTrue (без code) не ломаются и не теряют смысл.
  "admin.error.unauthorized": "Не авторизовано",
  "admin.error.bad_request": "Некорректный запрос",
  "admin.error.name_required": "Укажите имя",
  "admin.error.invalid_email": "Укажите корректный e-mail (логин)",
  "admin.error.unknown_role": "Неизвестная роль",
  "admin.error.unknown_department": "Неизвестный отдел",
  "admin.error.password_too_short": "Пароль минимум 6 символов",
  "admin.error.affiliate_code_required": "Укажите affiliate-код",
  "admin.error.department_required": "Укажите отдел",
  "admin.error.role_not_allowed": "Недостаточно прав для создания пользователя с этой ролью",
  "admin.error.email_already_exists": "Пользователь с таким e-mail уже существует",
  "admin.error.user_not_found": "Пользователь не найден",
  "admin.error.forbidden": "Недостаточно прав",
  "admin.error.unknown_action": "Неизвестное действие",
  "admin.error.reassign_same_operator": "Нельзя передать игроков тому же оператору",
  "admin.error.reassign_target_not_found": "Оператор для передачи не найден",
} satisfies Record<string, string>;
