import { I18nProvider } from "@/lib/i18n";
import { resolveLocale } from "@/lib/i18n/server";

/**
 * Layout для публичной зоны (внешние read-only ссылки, напр. /a/<token>).
 * НАМЕРЕННО без проверки сессии - эти страницы открывают без входа. Задача
 * та же, что у (auth)/layout: поднять локаль из cookie и отдать <I18nProvider>,
 * чтобы useT()/useLocale() работали и здесь. Guard (app)/layout сюда не
 * распространяется - (public) отдельная группа роутов.
 */
export default async function PublicLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const locale = await resolveLocale();
  return (
    <I18nProvider initialLocale={locale}>
      <div className="min-h-screen bg-surface">
        <div className="max-w-5xl mx-auto px-4 py-8 sm:py-12">{children}</div>
      </div>
    </I18nProvider>
  );
}
