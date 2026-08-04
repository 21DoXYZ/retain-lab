/**
 * components/reports/types.ts — типы и ЧИСТЫЕ хелперы конструктора отчётов (W5-T4).
 *
 * Здесь нет JSX/хуков/сети — только формы данных (1:1 с контрактом api/reports.py)
 * и функции без побочных эффектов (пресеты периода, применимость разрезов, порядок
 * разрезов). Компоненты держат тонкими, а всю арифметику spec — здесь, чтобы её
 * можно было переиспользовать и не плодить дубли.
 */
import type { UserRole } from "@/lib/types";

// ── реестр полей (GET /api/v1/reports/fields) ───────────────────────────────
export type MetricSource = "money" | "game" | "users" | "derived";
export type MetricFmt = "try" | "int" | "pct";
export type ColumnType = "money" | "int" | "date" | "string" | "pct";
export type DimKind = "time" | "profile" | "transaction" | "state_at";

export interface MetricDef {
  key: string;
  label: string;
  source: MetricSource;
  fmt: MetricFmt;
  type: "money" | "int" | "pct";
  derived?: boolean;    // производная колонка (отношение base-метрик, post-agg)
  deps?: string[];      // базовые метрики, от которых зависит производная
}

export interface DimensionDef {
  key: string;
  label: string;
  kind: DimKind;
  value_type: "str" | "int" | "date";
  type: ColumnType;
  applicable_sources: MetricSource[];
}

export interface FieldsCatalog {
  metrics: Record<string, MetricDef>;
  dimensions: Record<string, DimensionDef>;
}

// ── spec отчёта (тело POST /reports/run) ────────────────────────────────────
export type FilterOp = "in" | "not_in";
export type FilterValue = string | number;

export interface ReportFilter {
  dim: string;
  op: FilterOp;
  value: FilterValue[];
}

export interface ReportPeriod {
  from: string; // YYYY-MM-DD
  to: string;
}

export type ReportCurrency = "TRY" | "USD";

export interface ReportSpec {
  metrics: string[];
  dims: string[]; // порядок = вложенность (≤ 3)
  filters: ReportFilter[];
  period: ReportPeriod;
  currency?: ReportCurrency;   // валюта сумм (П6); деф TRY. USD — по фикс-курсу
}

// ── результат прогона (POST /reports/run) ───────────────────────────────────
export interface ResultColumn {
  key: string;
  label: string;
  type: ColumnType;
}

export type ResultCell = string | number | null;
export type ResultRow = Record<string, ResultCell>;

export interface RunMeta {
  took_ms: number;
  result_rows: number;
  rows_scanned: number | null;
  history_from: string | null;
  uses_state_at: boolean;
  currency?: ReportCurrency;   // валюта, в которой отданы суммы
  usd_rate?: number | null;    // фикс-курс TRY→USD (если currency=USD)
}

export interface RunResult {
  columns: ResultColumn[];
  rows: ResultRow[];
  totals: Record<string, ResultCell>;
  meta: RunMeta;
}

// ── сохранённые отчёты (GET/POST/PUT/DELETE /reports/saved) ──────────────────
export type Visibility = "personal" | "shared" | "roles";

export interface SavedReport {
  report_id: string;
  name: string;
  spec: ReportSpec;
  owner_id: string | null;
  owner_name: string | null;
  visibility: Visibility;
  roles: string[];
  is_official: boolean;
  mine: boolean;
  created_at: string;
  updated_at: string;
}

export interface Freshness {
  money_until: string | null;
  game_until: string | null;
}

// ── пределы (зеркало api/report_builder.py) ─────────────────────────────────
export const MAX_DIMS = 3;

/** Порядок источников метрик в панели (для группировки чипов). */
export const METRIC_SOURCE_ORDER: readonly MetricSource[] = ["money", "game", "users", "derived"];

/** Порядок групп разрезов в выпадашке «добавить разрез». */
export const DIM_KIND_ORDER: readonly DimKind[] = ["time", "profile", "transaction", "state_at"];

/** Роли, доступные для visibility='roles' (whitelist reports_store.USER_ROLES). */
export const SAVE_ROLE_OPTIONS: readonly UserRole[] = [
  "super_admin",
  "director",
  "head_retention",
  "head_department",
  "operator",
  "vip_manager",
  "affiliate_manager",
  "marketing_manager",
  "analyst",
  "finance",
  "risk_officer",
  "support",
  "viewer",
];

/**
 * Известные значения enum-разрезов (для фильтров чипами). Профильные строковые
 * разрезы (страна/валюта/аффилиат/метод оплаты) вводятся текстом — их домены
 * открытые. Для этих же ключей backend ждёт Array(Int64) (int) или Array(String).
 */
export const ENUM_VALUES: Record<string, FilterValue[]> = {
  weekday: [1, 2, 3, 4, 5, 6, 7],
  hour: Array.from({ length: 24 }, (_, i) => i),
  vip_level_at: [0, 1, 2, 3, 4, 5],
  lifecycle_at: ["active", "cooling", "at_risk", "dormant", "churned", "never"],
  early_tier_at: ["A", "B", "C", "D"],
};

// ── чистые хелперы ──────────────────────────────────────────────────────────

/** Источники выбранных метрик (для проверки применимости разрезов). */
export function sourcesOfMetrics(metricKeys: string[], catalog: FieldsCatalog): Set<MetricSource> {
  const out = new Set<MetricSource>();
  for (const k of metricKeys) {
    const m = catalog.metrics[k];
    if (!m) continue;
    // производная не имеет своего источника — берём источники её зависимостей
    if (m.source === "derived") {
      for (const dep of m.deps ?? []) {
        const dm = catalog.metrics[dep];
        if (dm) out.add(dm.source);
      }
    } else {
      out.add(m.source);
    }
  }
  return out;
}

/** Разрез применим, если все источники метрик входят в его applicable_sources. */
export function isDimApplicable(dim: DimensionDef, sources: Set<MetricSource>): boolean {
  if (sources.size === 0) return true; // метрик ещё нет — не ограничиваем
  for (const s of sources) if (!dim.applicable_sources.includes(s)) return false;
  return true;
}

/**
 * Разрез можно фильтровать? Даты (день/неделя/месяц) не фильтруем — за это отвечает
 * период. Фильтруем enum-разрезы (weekday/hour/vip/lifecycle/tier) и строковые
 * профильные (страна/валюта/аффилиат/метод оплаты).
 */
export function isDimFilterable(dim: DimensionDef): boolean {
  if (dim.key in ENUM_VALUES) return true;
  return dim.value_type === "str";
}

/** Символ единицы метрики для подписи колонки/чипа (₺ / % / #). */
export function metricUnit(m: MetricDef): string {
  return m.type === "money" ? "₺" : m.type === "pct" ? "%" : "#";
}

/** Неизменяемая перестановка элемента массива на delta позиций (для ↑↓ разрезов). */
export function moveItem<T>(arr: readonly T[], index: number, delta: number): T[] {
  const next = [...arr];
  const target = index + delta;
  if (target < 0 || target >= next.length) return next;
  const [item] = next.splice(index, 1);
  next.splice(target, 0, item);
  return next;
}

// ── даты и пресеты периода ──────────────────────────────────────────────────

/** iso + delta дней (UTC-арифметика, без tz-дрейфа). */
export function addDaysISO(iso: string, delta: number): string {
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  d.setUTCDate(d.getUTCDate() + delta);
  return d.toISOString().slice(0, 10);
}

/**
 * Максимальная дата данных из /api/v1/meta/freshness ("15.07.2026 20:40" →
 * "2026-07-15"). null — если распарсить нельзя (UI тогда не подставляет пресеты).
 */
export function parseFreshnessMaxISO(f: Freshness | null | undefined): string | null {
  const raw = f?.game_until ?? f?.money_until;
  if (!raw) return null;
  const datePart = raw.split(" ")[0]; // "15.07.2026"
  const m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(datePart);
  if (!m) return null;
  return `${m[3]}-${m[2]}-${m[1]}`;
}

export type PeriodPreset = "30d" | "quarter" | "all";

/**
 * Границы периода по пресету, отсчитывая от maxISO (край данных). «Всё» ограничено
 * 366 днями (лимит билдера) и не уходит раньше historyFrom, если он известен.
 */
export function presetPeriod(
  preset: PeriodPreset,
  maxISO: string,
  historyFromISO: string | null,
): ReportPeriod {
  if (preset === "30d") return { from: addDaysISO(maxISO, -29), to: maxISO };
  if (preset === "quarter") return { from: addDaysISO(maxISO, -89), to: maxISO };
  // all: от максимально допустимого начала (лимит 366 дней), но не раньше данных
  const floor = addDaysISO(maxISO, -365);
  const from = historyFromISO && historyFromISO > floor ? historyFromISO : floor;
  return { from, to: maxISO };
}

/** Период по умолчанию: последние 30 дней от края данных (или пустой до загрузки). */
export function defaultPeriod(maxISO: string | null): ReportPeriod {
  if (!maxISO) return { from: "", to: "" };
  return presetPeriod("30d", maxISO, null);
}
