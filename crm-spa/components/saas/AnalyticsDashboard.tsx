"use client";

import { useLocale } from "@/lib/i18n";
import { SCard, SCardGrid } from "@/components/ui";

/**
 * AnalyticsDashboard — чистое представление вкладки «Аналитика». Данные приходят
 * готовым payload'ом (GET /api/v1/saas/analytics внутри кабинета или
 * /api/v1/public/analytics/<token> для внешней ссылки). Никаких запросов сам не
 * делает - это позволяет один и тот же экран показывать и владельцу, и наружу
 * по read-only ссылке (publicMode прячет всё, что уже спрятано на бэке, - здесь
 * просто убирает кнопку шаринга и добавляет брендовую шапку).
 *
 * Все графики - инлайновый SVG без библиотек (как Sparkline в HomeView): один
 * бандл, ноль внешних зависимостей, мгновенный рендер.
 */

// ── Данные ───────────────────────────────────────────────────────────────────

export interface AnalyticsData {
  coverage?: {
    last_event: string; minutes_since: number; stale: boolean;
    geo_pct: number; geo_located: number; geo_total: number;
  } | null;
  overview?: {
    users_total: number; paying: number; trialing: number; free: number;
    active_7d: number; active_30d: number; mrr: number; arr: number; arpu: number;
    new_signups_30d: number; new_paying_30d: number; churned_30d: number;
    paying_rate: number;
  } | null;
  cash?: {
    d30: { invoices: number; collected: number; recurring: number; onetime: number; onetime_count: number };
    all: { invoices: number; collected: number; recurring: number; onetime: number; onetime_count: number };
  } | null;
  growth?: {
    days: string[]; signups: number[]; active: number[]; generations: number[];
    new_paying: number[]; cumulative_users: number[];
  } | null;
  geography?: {
    countries: { code: string; name: string; flag: string; users: number; paying: number; mrr: number }[];
    known: number; total: number; unknown: number;
  } | null;
  funnel?: { steps: { key: string; count: number; pct: number }[] } | null;
  revenue?: { plans: { plan: string; count: number; mrr: number; share: number }[]; mrr_total: number } | null;
  engagement?: { dau: number; wau: number; mau: number; stickiness: number; gens_per_active_30d: number } | null;
  devices?: { mobile: number; desktop: number; platforms: { name: string; count: number }[] } | null;
  events?: { top: { type: string; count: number }[] } | null;
  share?: { enabled: boolean; url: string };
  brand?: { company: string };
}

// ── Локальный словарь (без раздувания глобальных словарей) ────────────────────

type Loc = "ru" | "en" | "tr";
const L: Record<string, Record<Loc, string>> = {
  overview: { ru: "Обзор", en: "Overview", tr: "Genel bakış" },
  growth: { ru: "Рост", en: "Growth", tr: "Büyüme" },
  geography: { ru: "География", en: "Geography", tr: "Coğrafya" },
  funnel: { ru: "Воронка до оплаты", en: "Path to revenue", tr: "Gelire giden yol" },
  revenue: { ru: "Выручка по планам", en: "Revenue by plan", tr: "Plana göre gelir" },
  engagement: { ru: "Вовлечённость", en: "Engagement", tr: "Etkileşim" },
  devices: { ru: "Устройства", en: "Devices", tr: "Cihazlar" },
  events: { ru: "Что делают в продукте", en: "Product activity", tr: "Ürün etkinliği" },
  mrr: { ru: "MRR", en: "MRR", tr: "MRR" },
  arr: { ru: "ARR", en: "ARR", tr: "ARR" },
  arpu: { ru: "ARPU", en: "ARPU", tr: "ARPU" },
  users: { ru: "Пользователи", en: "Users", tr: "Kullanıcılar" },
  paying: { ru: "Платящие", en: "Paying", tr: "Ödeme yapan" },
  payingRate: { ru: "Доля платящих", en: "Paid conversion", tr: "Ücretli dönüşüm" },
  trialing: { ru: "На триале", en: "On trial", tr: "Deneme" },
  active30: { ru: "Активны за 30 дней", en: "Active in 30d", tr: "30 günde aktif" },
  active7: { ru: "Активны за 7 дней", en: "Active in 7d", tr: "7 günde aktif" },
  stickiness: { ru: "Липкость DAU/MAU", en: "Stickiness DAU/MAU", tr: "Yapışkanlık DAU/MAU" },
  newSignups: { ru: "Регистраций за 30 дней", en: "Signups in 30d", tr: "30 günde kayıt" },
  newPaying: { ru: "Новых платящих за 30 дней", en: "New paying in 30d", tr: "30 günde yeni ödeme" },
  churned: { ru: "Ушло за 30 дней", en: "Churned in 30d", tr: "30 günde kayıp" },
  baseGrowth: { ru: "База пользователей", en: "User base", tr: "Kullanıcı tabanı" },
  signupsPerDay: { ru: "Регистрации в день", en: "Signups per day", tr: "Günlük kayıt" },
  activePerDay: { ru: "Активные в день", en: "Daily active", tr: "Günlük aktif" },
  generations: { ru: "Генерации", en: "Generations", tr: "Üretimler" },
  dau: { ru: "DAU", en: "DAU", tr: "DAU" },
  wau: { ru: "WAU", en: "WAU", tr: "WAU" },
  mau: { ru: "MAU", en: "MAU", tr: "MAU" },
  gensPerActive: { ru: "Генераций на активного", en: "Generations per active user", tr: "Aktif başına üretim" },
  mobile: { ru: "Мобильные", en: "Mobile", tr: "Mobil" },
  desktop: { ru: "Десктоп", en: "Desktop", tr: "Masaüstü" },
  ofUsers: { ru: "от пользователей", en: "of users", tr: "kullanıcıların" },
  knownGeo: { ru: "стран определено", en: "countries located", tr: "ülke tespit edildi" },
  fSignup: { ru: "Регистрация", en: "Signup", tr: "Kayıt" },
  fActivated: { ru: "Первый проект", en: "First project", tr: "İlk proje" },
  fValue: { ru: "Первая ценность", en: "First value", tr: "İlk değer" },
  fPaid: { ru: "Оплата", en: "Paid", tr: "Ödeme" },
  noData: { ru: "Пока нет данных", en: "No data yet", tr: "Henüz veri yok" },
  share: { ru: "Поделиться", en: "Share", tr: "Paylaş" },
  shareOn: { ru: "Внешняя ссылка включена", en: "Public link is on", tr: "Genel bağlantı açık" },
  copy: { ru: "Скопировать", en: "Copy", tr: "Kopyala" },
  copied: { ru: "Скопировано", en: "Copied", tr: "Kopyalandı" },
  rotate: { ru: "Новая ссылка", en: "New link", tr: "Yeni bağlantı" },
  disable: { ru: "Отключить", en: "Disable", tr: "Kapat" },
  enableShare: { ru: "Открыть внешний доступ", en: "Create public link", tr: "Genel bağlantı oluştur" },
  shareHint: {
    ru: "Read-only дашборд без имён и email - для инвестора или партнёра.",
    en: "Read-only dashboard, no names or emails - for an investor or partner.",
    tr: "Salt okunur pano, isim veya e-posta yok - yatırımcı veya ortak için.",
  },
  last30: { ru: "за 30 дней", en: "last 30 days", tr: "son 30 gün" },
  poweredBy: { ru: "Аналитика", en: "Analytics", tr: "Analitik" },
  updated: { ru: "Обновлено", en: "Updated", tr: "Güncellendi" },
  justNow: { ru: "только что", en: "just now", tr: "az önce" },
  minAgo: { ru: "мин назад", en: "min ago", tr: "dk önce" },
  hAgo: { ru: "ч назад", en: "h ago", tr: "sa önce" },
  dAgo: { ru: "дн назад", en: "d ago", tr: "gün önce" },
  geoCov: { ru: "гео размечено", en: "geo-located", tr: "konum tespit" },
  staleTitle: { ru: "Поток данных отстал", en: "Data feed is behind", tr: "Veri akışı geride" },
  staleBody: {
    ru: "Новые события не приходили более 6 часов - цифры могут быть неполными. Проверьте приём (экспорт-ключ / вебхуки).",
    en: "No new events for over 6 hours - figures may be incomplete. Check ingestion (export key / webhooks).",
    tr: "6 saattir yeni olay yok - veriler eksik olabilir. Alımı kontrol edin (dışa aktarma anahtarı / webhook).",
  },
  cash: { ru: "Собрано кэша", en: "Cash collected", tr: "Toplanan nakit" },
  collected: { ru: "Всего собрано", en: "Total collected", tr: "Toplam" },
  recurring: { ru: "Подписки (recurring)", en: "Recurring", tr: "Yinelenen" },
  onetime: { ru: "Разовые платежи", en: "One-time", tr: "Tek seferlik" },
  invoicesPaid: { ru: "оплаченных инвойсов", en: "paid invoices", tr: "ödenmiş fatura" },
  cashHint: {
    ru: "MRR - только повторяющаяся выручка подписок; разовые платежи (офферы, паки) сюда не входят, поэтому собрано больше MRR.",
    en: "MRR counts recurring subscription revenue only; one-time payments (offers, packs) are separate, so collected exceeds MRR.",
    tr: "MRR yalnızca yinelenen abonelik gelirini sayar; tek seferlik ödemeler ayrıdır, bu yüzden toplanan MRR'yi aşar.",
  },
  allTime: { ru: "за всё время", en: "all time", tr: "tüm zamanlar" },
};

// ── Форматтеры ────────────────────────────────────────────────────────────────

const usd = (n: number | undefined) =>
  "$" + (n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 0 });
const num = (n: number | undefined) => (n ?? 0).toLocaleString("en-US");
const pct = (n: number | undefined) => `${(n ?? 0).toFixed(1)}%`;

// dataviz: категориальные хью применяются ТОЛЬКО там, где цвет = сущность
// (recurring vs разовые, mobile vs desktop). Валидировано validate_palette.js
// (light+dark, все проверки PASS). Магнитудные бары остаются одним hue - длина
// уже кодирует величину, радуга там запрещена.
const VIZ_STYLE = `
.viz-root { --viz-1:#2a78d6; --viz-2:#eb6834; --viz-3:#1baf7a; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) .viz-root { --viz-1:#3987e5; --viz-2:#d95926; --viz-3:#199e70; }
}
:root[data-theme="dark"] .viz-root { --viz-1:#3987e5; --viz-2:#d95926; --viz-3:#199e70; }
`;

/** «Обновлено N назад» - человеческая свежесть из minutes_since. */
function ago(mins: number, t: (k: string) => string): string {
  if (mins < 2) return t("justNow");
  if (mins < 60) return `${mins} ${t("minAgo")}`;
  if (mins < 1440) return `${Math.round(mins / 60)} ${t("hAgo")}`;
  return `${Math.round(mins / 1440)} ${t("dAgo")}`;
}

// ── Мини-графики (чистый SVG) ─────────────────────────────────────────────────

function AreaLine({ data, height = 90 }: { data: number[]; height?: number }) {
  const w = 640, h = height, pad = 4;
  if (!data.length) return null;
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const span = max - min || 1;
  const x = (i: number) => (i / Math.max(data.length - 1, 1)) * w;
  const y = (v: number) => h - pad - ((v - min) / span) * (h - pad * 2);
  const line = data.map((v, i) => `${x(i)},${y(v)}`).join(" ");
  const area = `0,${h} ${line} ${w},${h}`;
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none"
         className="block" aria-hidden>
      <polygon points={area} className="fill-primary" opacity={0.08} />
      <polyline points={line} fill="none" className="stroke-primary" strokeWidth="2"
                strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Bars({ data, height = 90, tone = "primary" }: { data: number[]; height?: number; tone?: "primary" | "pos" }) {
  const w = 640, h = height;
  if (!data.length) return null;
  const max = Math.max(...data, 1);
  const bw = w / data.length;
  const cls = tone === "pos" ? "fill-pos" : "fill-primary";
  return (
    <svg viewBox={`0 0 ${w} ${h}`} width="100%" height={h} preserveAspectRatio="none"
         className="block" aria-hidden>
      {data.map((v, i) => {
        const bh = (v / max) * (h - 4);
        return <rect key={i} x={i * bw + bw * 0.15} y={h - bh} width={bw * 0.7} height={bh}
                     rx={1} className={cls} opacity={0.85} />;
      })}
    </svg>
  );
}

function Section({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="bg-canvas border border-hair2 rounded-card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[13px] font-semibold uppercase tracking-wide text-steel">{title}</h2>
        {right}
      </div>
      {children}
    </section>
  );
}

// ── Шаринг ────────────────────────────────────────────────────────────────────

function ShareBar({ share, onShare, t }: {
  share: { enabled: boolean; url: string };
  onShare: (action: "enable" | "rotate" | "disable") => void;
  t: (k: string) => string;
}) {
  const copy = () => { if (share.url) navigator.clipboard?.writeText(share.url); };
  if (!share.enabled) {
    return (
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => onShare("enable")}
                className="px-3.5 py-2 rounded-full bg-primary text-white text-[13px] font-semibold hover:opacity-90 transition-opacity">
          {t("enableShare")}
        </button>
        <span className="text-[12px] text-steel">{t("shareHint")}</span>
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="inline-flex items-center gap-1.5 text-[12px] text-pos font-medium">
        <span className="w-1.5 h-1.5 rounded-full bg-pos" />{t("shareOn")}
      </span>
      <code className="px-2.5 py-1.5 rounded-md bg-surface border border-hair text-[12px] text-ink max-w-[320px] truncate">
        {share.url}
      </code>
      <button onClick={copy} className="px-2.5 py-1.5 rounded-md border border-hair text-[12px] hover:border-primary transition-colors">{t("copy")}</button>
      <button onClick={() => onShare("rotate")} className="px-2.5 py-1.5 rounded-md border border-hair text-[12px] hover:border-primary transition-colors">{t("rotate")}</button>
      <button onClick={() => onShare("disable")} className="px-2.5 py-1.5 rounded-md border border-hair text-[12px] text-neg hover:border-neg transition-colors">{t("disable")}</button>
    </div>
  );
}

// ── Главный экран ─────────────────────────────────────────────────────────────

export function AnalyticsDashboard({ data, onShare, publicMode }: {
  data: AnalyticsData;
  onShare?: (action: "enable" | "rotate" | "disable") => void;
  publicMode?: boolean;
}) {
  const { locale } = useLocale();
  const lc = (["ru", "en", "tr"].includes(locale) ? locale : "en") as Loc;
  const t = (k: string) => (L[k]?.[lc] ?? L[k]?.en ?? k);

  const ov = data.overview;
  const cash = data.cash;
  const g = data.growth;
  const geo = data.geography;
  const fn = data.funnel;
  const rev = data.revenue;
  const eng = data.engagement;
  const dev = data.devices;
  const evs = data.events;

  const funnelLabel: Record<string, string> = {
    signup: t("fSignup"), activated: t("fActivated"), value: t("fValue"), paid: t("fPaid"),
  };
  const geoMax = Math.max(...(geo?.countries.map((c) => c.users) ?? [1]), 1);
  const devTotal = (dev?.mobile ?? 0) + (dev?.desktop ?? 0);
  const evMax = Math.max(...(evs?.top.map((e) => e.count) ?? [1]), 1);
  const cov = data.coverage;

  return (
    <div className="viz-root flex flex-col gap-5">
      <style>{VIZ_STYLE}</style>
      {publicMode && (
        <div className="flex items-center justify-between border-b border-hair pb-4">
          <div className="flex items-center gap-2.5">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-white text-[15px] font-bold">
              {(data.brand?.company ?? "R").slice(0, 1).toUpperCase()}
            </span>
            <span className="text-[18px] font-semibold text-ink">{data.brand?.company}</span>
          </div>
          <div className="text-right">
            <div className="text-[12px] text-steel">{t("poweredBy")} · Revenue Autopilot</div>
            {cov?.last_event ? <div className="text-[11px] text-steel">{t("updated")} {ago(cov.minutes_since, t)}</div> : null}
          </div>
        </div>
      )}

      {/* Доверие к данным: поток отстал - явное предупреждение сверху */}
      {cov?.stale && (
        <div className="flex items-start gap-3 rounded-card px-4 py-3"
             style={{
               border: "1px solid color-mix(in srgb, var(--viz-2) 45%, transparent)",
               background: "color-mix(in srgb, var(--viz-2) 7%, transparent)",
             }}>
          <span className="text-[16px] leading-none mt-0.5">⚠️</span>
          <div>
            <div className="text-[13px] font-semibold text-ink">{t("staleTitle")}</div>
            <div className="text-[12px] text-steel">{t("staleBody")}</div>
          </div>
        </div>
      )}

      {!publicMode && cov && !cov.stale && cov.last_event ? (
        <div className="flex items-center gap-1.5 text-[11.5px] text-steel">
          <span className="h-1.5 w-1.5 rounded-full bg-pos" />
          {t("updated")} {ago(cov.minutes_since, t)} · {cov.geo_pct}% {t("geoCov")}
        </div>
      ) : null}

      {!publicMode && data.share && onShare && (
        <Section title={t("share")}>
          <ShareBar share={data.share} onShare={onShare} t={t} />
        </Section>
      )}

      {/* KPI */}
      <SCardGrid>
        <SCard label={t("mrr")} value={usd(ov?.mrr)} sub={`${t("arr")} ${usd(ov?.arr)}`} icon="💰" variant="cream" />
        <SCard label={t("users")} value={num(ov?.users_total)} sub={`${num(ov?.active_30d)} · ${t("active30")}`} icon="👥" />
        <SCard label={t("payingRate")} value={pct(ov?.paying_rate)} sub={`${num(ov?.paying)} ${t("paying")}`} icon="✅" valueTone="pos" />
        <SCard label={t("arpu")} value={usd(ov?.arpu)} sub={`${num(ov?.trialing)} ${t("trialing")}`} icon="📈" />
        <SCard label={t("newSignups")} value={num(ov?.new_signups_30d)} sub={`+${num(ov?.new_paying_30d)} ${t("paying").toLowerCase()}`} icon="🚀" />
        <SCard label={t("churned")} value={num(ov?.churned_30d)} sub={t("last30")} icon="📉" valueTone={ov && ov.churned_30d > 0 ? "neg" : "default"} />
      </SCardGrid>

      {/* Собранный кэш: recurring vs разовые - то, что MRR не показывает */}
      {cash && cash.d30.collected > 0 && (
        <Section title={t("cash")} right={<span className="text-[12px] text-steel">{t("last30")}</span>}>
          <div className="grid gap-4 sm:grid-cols-3">
            <div className="bg-cream border border-beige rounded-md p-4">
              <div className="text-[11px] text-steel uppercase tracking-wide">{t("collected")}</div>
              <div className="text-[26px] font-semibold text-ink">{usd(cash.d30.collected)}</div>
              <div className="text-[11px] text-steel">{cash.d30.invoices} {t("invoicesPaid")}</div>
            </div>
            <div className="bg-surface rounded-md p-4">
              <div className="flex items-center gap-1.5 text-[11px] text-steel uppercase tracking-wide">
                <span className="h-2 w-2 rounded-full" style={{ background: "var(--viz-1)" }} />{t("recurring")}
              </div>
              <div className="text-[26px] font-semibold text-ink">{usd(cash.d30.recurring)}</div>
              <div className="text-[11px] text-steel">MRR {usd(ov?.mrr)}</div>
            </div>
            <div className="bg-surface rounded-md p-4">
              <div className="flex items-center gap-1.5 text-[11px] text-steel uppercase tracking-wide">
                <span className="h-2 w-2 rounded-full" style={{ background: "var(--viz-2)" }} />{t("onetime")}
              </div>
              <div className="text-[26px] font-semibold text-ink">{usd(cash.d30.onetime)}</div>
              <div className="text-[11px] text-steel">{cash.d30.onetime_count} · {t("last30")}</div>
            </div>
          </div>
          {/* Композиция кэша: recurring vs разовые одной полосой */}
          {cash.d30.collected > 0 && (
            <div className="mt-4 flex h-2.5 overflow-hidden rounded-full bg-surface" role="img"
                 aria-label={`recurring ${usd(cash.d30.recurring)}, one-time ${usd(cash.d30.onetime)}`}>
              <div style={{ width: `${(cash.d30.recurring / cash.d30.collected) * 100}%`, background: "var(--viz-1)" }} />
              <div style={{ width: `${(cash.d30.onetime / cash.d30.collected) * 100}%`, background: "var(--viz-2)", marginLeft: 2 }} />
            </div>
          )}
          <div className="text-[12px] text-steel mt-3">{t("cashHint")}</div>
          {cash.all.collected > cash.d30.collected && (
            <div className="text-[12px] text-steel mt-1">
              {t("allTime")}: <span className="text-ink font-medium">{usd(cash.all.collected)}</span> · {cash.all.invoices} {t("invoicesPaid")}
            </div>
          )}
        </Section>
      )}

      {/* Рост */}
      {g && g.days.length > 0 && (
        <Section title={t("growth")} right={<span className="text-[12px] text-steel">{t("last30")}</span>}>
          <div className="grid gap-6 md:grid-cols-2">
            <div>
              <div className="text-[12px] text-steel mb-1">{t("baseGrowth")}</div>
              <div className="text-[22px] font-semibold text-ink mb-2">{num(g.cumulative_users.at(-1))}</div>
              <AreaLine data={g.cumulative_users} />
            </div>
            <div>
              <div className="text-[12px] text-steel mb-1">{t("signupsPerDay")}</div>
              <div className="text-[22px] font-semibold text-ink mb-2">{num(g.signups.reduce((a, b) => a + b, 0))}</div>
              <Bars data={g.signups} tone="pos" />
            </div>
            <div>
              <div className="text-[12px] text-steel mb-1">{t("activePerDay")}</div>
              <div className="text-[22px] font-semibold text-ink mb-2">{num(Math.max(...g.active))}</div>
              <AreaLine data={g.active} />
            </div>
            <div>
              <div className="text-[12px] text-steel mb-1">{t("generations")}</div>
              <div className="text-[22px] font-semibold text-ink mb-2">{num(g.generations.reduce((a, b) => a + b, 0))}</div>
              <Bars data={g.generations} />
            </div>
          </div>
        </Section>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* География */}
        <Section title={t("geography")} right={geo ? <span className="text-[12px] text-steel">{num(geo.known)} {t("knownGeo")}</span> : undefined}>
          {geo && geo.countries.length > 0 ? (
            <div className="flex flex-col gap-2.5">
              {geo.countries.slice(0, 10).map((c) => (
                <div key={c.code} className="flex items-center gap-3"
                     title={`${c.name}: ${num(c.users)} users · ${c.paying} paying${c.mrr > 0 ? ` · ${usd(c.mrr)} MRR` : ""}`}>
                  <span className="text-[16px] w-6 text-center flex-none">{c.flag}</span>
                  <span className="text-[13px] text-ink w-32 flex-none truncate">{c.name}</span>
                  <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${(c.users / geoMax) * 100}%` }} />
                  </div>
                  <span className="text-[12px] text-ink w-10 text-right flex-none tabular-nums">{num(c.users)}</span>
                  <span className="text-[11px] text-steel w-16 text-right flex-none tabular-nums">
                    {c.mrr > 0 ? usd(c.mrr) : `${c.paying}✓`}
                  </span>
                </div>
              ))}
            </div>
          ) : <div className="text-[13px] text-steel py-6 text-center">{t("noData")}</div>}
        </Section>

        {/* Воронка */}
        <Section title={t("funnel")}>
          {fn && fn.steps.length > 0 ? (
            <div className="flex flex-col gap-3">
              {fn.steps.map((s, i) => (
                <div key={s.key} title={`${funnelLabel[s.key] ?? s.key}: ${num(s.count)} (${pct(s.pct)})`}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-[13px] text-ink">{funnelLabel[s.key] ?? s.key}</span>
                    <span className="text-[12px] text-steel tabular-nums">{num(s.count)} · {pct(s.pct)}</span>
                  </div>
                  <div className="h-6 rounded-md bg-surface overflow-hidden">
                    <div className={`h-full rounded-md ${i === fn.steps.length - 1 ? "bg-pos" : "bg-primary"}`}
                         style={{ width: `${Math.max(s.pct, 1.5)}%`, opacity: 0.85 }} />
                  </div>
                </div>
              ))}
            </div>
          ) : <div className="text-[13px] text-steel py-6 text-center">{t("noData")}</div>}
        </Section>

        {/* Выручка по планам */}
        <Section title={t("revenue")} right={rev ? <span className="text-[12px] text-steel tabular-nums">{usd(rev.mrr_total)}</span> : undefined}>
          {rev && rev.plans.length > 0 ? (
            <div className="flex flex-col gap-2.5">
              {rev.plans.map((pl) => (
                <div key={pl.plan} className="flex items-center gap-3"
                     title={`${pl.plan}: ${usd(pl.mrr)} MRR · ${pl.count} subs · ${pct(pl.share)}`}>
                  <span className="text-[13px] text-ink w-40 flex-none truncate">{pl.plan}</span>
                  <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${pl.share}%` }} />
                  </div>
                  <span className="text-[12px] text-ink w-16 text-right flex-none tabular-nums">{usd(pl.mrr)}</span>
                  <span className="text-[11px] text-steel w-8 text-right flex-none tabular-nums">{pl.count}</span>
                </div>
              ))}
            </div>
          ) : <div className="text-[13px] text-steel py-6 text-center">{t("noData")}</div>}
        </Section>

        {/* Вовлечённость + устройства */}
        <Section title={t("engagement")}>
          {eng ? (
            <div className="flex flex-col gap-4">
              <div className="grid grid-cols-3 gap-3 text-center">
                {[["dau", eng.dau], ["wau", eng.wau], ["mau", eng.mau]].map(([k, v]) => (
                  <div key={k as string} className="bg-surface rounded-md py-3">
                    <div className="text-[20px] font-semibold text-ink tabular-nums">{num(v as number)}</div>
                    <div className="text-[11px] text-steel uppercase">{t(k as string)}</div>
                  </div>
                ))}
              </div>
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-steel">{t("stickiness")}</span>
                <span className="text-ink font-medium tabular-nums">{pct(eng.stickiness)}</span>
              </div>
              <div className="flex items-center justify-between text-[13px]">
                <span className="text-steel">{t("gensPerActive")}</span>
                <span className="text-ink font-medium tabular-nums">{eng.gens_per_active_30d}</span>
              </div>
              {dev && devTotal > 0 && (
                <div title={`${t("mobile")} ${dev.mobile} · ${t("desktop")} ${dev.desktop}`}>
                  <div className="flex h-2.5 rounded-full overflow-hidden bg-surface mb-1.5">
                    <div className="h-full" style={{ width: `${(dev.mobile / devTotal) * 100}%`, background: "var(--viz-1)" }} />
                    <div className="h-full" style={{ width: `${(dev.desktop / devTotal) * 100}%`, background: "var(--viz-2)", marginLeft: 2 }} />
                  </div>
                  <div className="flex justify-between text-[11px] text-steel">
                    <span className="inline-flex items-center gap-1">
                      <span className="h-2 w-2 rounded-full" style={{ background: "var(--viz-1)" }} />📱 {t("mobile")} {pct((dev.mobile / devTotal) * 100)}
                    </span>
                    <span className="inline-flex items-center gap-1">
                      {t("desktop")} {pct((dev.desktop / devTotal) * 100)} 🖥 <span className="h-2 w-2 rounded-full" style={{ background: "var(--viz-2)" }} />
                    </span>
                  </div>
                </div>
              )}
            </div>
          ) : <div className="text-[13px] text-steel py-6 text-center">{t("noData")}</div>}
        </Section>
      </div>

      {/* Активность в продукте */}
      {evs && evs.top.length > 0 && (
        <Section title={t("events")} right={<span className="text-[12px] text-steel">{t("last30")}</span>}>
          <div className="grid gap-2.5 sm:grid-cols-2">
            {evs.top.map((e) => (
              <div key={e.type} className="flex items-center gap-3" title={`${e.type}: ${num(e.count)}`}>
                <span className="text-[13px] text-ink w-44 flex-none truncate">{e.type}</span>
                <div className="flex-1 h-2 rounded-full bg-surface overflow-hidden">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${(e.count / evMax) * 100}%`, opacity: 0.7 }} />
                </div>
                <span className="text-[12px] text-steel w-16 text-right flex-none tabular-nums">{num(e.count)}</span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {publicMode && (
        <div className="mt-2 flex items-center justify-between border-t border-hair pt-4 text-[11px] text-steel">
          <span>{data.brand?.company}</span>
          <span>Powered by Revenue Autopilot · retivo.digital</span>
        </div>
      )}
    </div>
  );
}
