import { notFound } from "next/navigation";
import type { ReactNode } from "react";

/**
 * Гейт на всё поддерево /dev (витрина дизайн-системы «Эталон компонентов A2»).
 *
 * Страницы /dev лежат ВНЕ группы (app), т.е. не наследуют её авторизацию, и
 * попадали в прод-билд открытыми. Данные там демонстрационные (ни игроков, ни
 * PII), но неаутентифицированный роут в CRM — лишняя поверхность: он выдаёт
 * внутреннюю структуру и названия. В проде отдаём 404, в dev — работает как был.
 *
 * Серверный компонент: проверка выполняется на сервере и не уезжает в бандл.
 */
export default function DevLayout({ children }: { children: ReactNode }) {
  if (process.env.NODE_ENV === "production") notFound();
  return <>{children}</>;
}
