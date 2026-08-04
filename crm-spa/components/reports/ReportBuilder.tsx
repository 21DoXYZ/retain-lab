"use client";

import { useState } from "react";
import {
  PageHeader,
  Tabs,
  Button,
  Banner,
  Card,
  Eyebrow,
  ErrorState,
  EmptyState,
  Skeleton,
  PillRow,
} from "@/components/ui";
import { formatInt, formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useRole } from "@/lib/role-context";
import type { UserRole } from "@/lib/types";
import { useFlaskData } from "@/components/marketing/useFlaskData";
import { BuilderForm } from "./BuilderForm";
import { PivotTable } from "./PivotTable";
import { SavedReportsList } from "./SavedReportsList";
import { SaveReportModal } from "./SaveReportModal";
import { useReportRun } from "./useReportRun";
import { downloadReport, ReportDownloadError } from "./download";
import { fieldLabel } from "./labels";
import {
  defaultPeriod,
  moveItem,
  parseFreshnessMaxISO,
  type FieldsCatalog,
  type Freshness,
  type ReportCurrency,
  type ReportFilter,
  type ReportPeriod,
  type ReportSpec,
  type SavedReport,
} from "./types";

/**
 * ReportBuilder — экран /reports (W5-T4). Оркестратор: реестр полей + свежесть
 * данных, состояние spec (метрики/разрезы/фильтры/период), прогон, сводная,
 * сохранение и список сохранённых. Вкладки «Конструктор»/«Сохранённые».
 *
 * Ядро «сводной как в Excel»: смена ПОРЯДКА разрезов (↑↓) сразу перезапрашивает
 * отчёт с новым порядком group by → PivotTable перестраивает вложенность. Правка
 * метрик/фильтров/периода требует явного «Построить» (крупные изменения).
 */
const OFFICIAL_ROLES: readonly UserRole[] = ["director", "head_retention", "super_admin"];

export function ReportBuilder() {
  const t = useT();
  const me = useRole();
  const canOfficial = OFFICIAL_ROLES.includes(me.role);

  const catalogQ = useFlaskData<FieldsCatalog>("/api/v1/reports/fields");
  const freshnessQ = useFlaskData<Freshness>("/api/v1/meta/freshness");
  const catalog = catalogQ.data;
  const maxISO = parseFreshnessMaxISO(freshnessQ.data);

  const run = useReportRun();

  // ── состояние spec ──
  const [metrics, setMetrics] = useState<string[]>([]);
  const [dims, setDims] = useState<string[]>([]);
  const [filters, setFilters] = useState<ReportFilter[]>([]);
  const [periodOverride, setPeriodOverride] = useState<ReportPeriod | null>(null);
  const [currency, setCurrency] = useState<ReportCurrency>("TRY");
  const period = periodOverride ?? defaultPeriod(maxISO);

  // ── UI-состояние ──
  const [tab, setTab] = useState("build");
  const [showSave, setShowSave] = useState(false);
  const [saveNonce, setSaveNonce] = useState(0);
  const [savedReloadKey, setSavedReloadKey] = useState(0);
  const [loaded, setLoaded] = useState<SavedReport | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);

  function buildSpec(over?: Partial<ReportSpec>): ReportSpec {
    return { metrics, dims, filters, period, currency, ...over };
  }

  // Смена валюты — пересчёт (post-agg): если отчёт уже построен, сразу перезапросим.
  function onCurrency(next: ReportCurrency) {
    setCurrency(next);
    if (run.state === "data" && metrics.length > 0) {
      run.run(buildSpec({ currency: next }));
    }
  }

  const canBuild = metrics.length > 0 && Boolean(period.from) && Boolean(period.to);

  function onBuild() {
    if (!canBuild) return;
    run.run(buildSpec());
  }

  function toggleMetric(key: string) {
    setMetrics((cur) => (cur.includes(key) ? cur.filter((m) => m !== key) : [...cur, key]));
  }
  function addDim(key: string) {
    if (!key) return;
    setDims((cur) => (cur.includes(key) || cur.length >= 3 ? cur : [...cur, key]));
  }
  function removeDim(index: number) {
    setDims((cur) => cur.filter((_, i) => i !== index));
  }
  // ↑↓: меняем порядок и, если отчёт уже построен, СРАЗУ перезапрашиваем —
  // это и есть перестройка сводной по новому порядку вложенности.
  function reorderDim(index: number, delta: number) {
    const next = moveItem(dims, index, delta);
    setDims(next);
    if (run.state === "data" && metrics.length > 0) {
      run.run(buildSpec({ dims: next }));
    }
  }

  function openSaved(report: SavedReport) {
    const s = report.spec;
    setMetrics(s.metrics ?? []);
    setDims(s.dims ?? []);
    setFilters(s.filters ?? []);
    setPeriodOverride(s.period ?? null);
    setCurrency(s.currency ?? "TRY");
    setLoaded(report);
    setTab("build");
    run.run(s);
  }

  async function onExport(fmt: "csv" | "xlsx") {
    if (!run.ranSpec || !catalog) return;
    setExportError(null);
    // локализованные заголовки колонок (разрезы + метрики) — как в UI
    const labels: Record<string, string> = {};
    for (const d of run.ranSpec.dims) {
      const dd = catalog.dimensions[d];
      if (dd) labels[d] = fieldLabel(t, d, dd.label);
    }
    for (const m of run.ranSpec.metrics) {
      const mm = catalog.metrics[m];
      if (mm) labels[m] = fieldLabel(t, m, mm.label);
    }
    try {
      await downloadReport(fmt, run.ranSpec, labels);
    } catch (e: unknown) {
      setExportError(
        e instanceof ReportDownloadError && e.code === "forbidden"
          ? t("reports.export.forbidden")
          : t("reports.export.failed"),
      );
    }
  }

  // ── история: предупреждение, если период раньше начала снапшотов ──
  const historyWarn =
    run.result?.meta.uses_state_at &&
    run.result.meta.history_from &&
    run.ranSpec &&
    run.ranSpec.period.from < run.result.meta.history_from
      ? run.result.meta.history_from
      : null;

  // ── состояния каталога (loading / error / data) ──
  if (catalogQ.state === "error") {
    return (
      <>
        <PageHeader title={t("reports.title")} lead={t("reports.lead")} />
        <div className="mt-6">
          <ErrorState
            title={t("reports.error.title")}
            description={catalogQ.error ?? t("reports.error.desc")}
            onRetry={catalogQ.reload}
          />
        </div>
      </>
    );
  }
  if (catalogQ.state === "loading" || !catalog) {
    return (
      <>
        <PageHeader title={t("reports.title")} lead={t("reports.lead")} />
        <div className="mt-6 space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title={t("reports.title")} lead={t("reports.lead")} />

      <div className="mt-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "build", label: t("reports.tab.build") },
            { key: "saved", label: t("reports.tab.saved") },
          ]}
        />
      </div>

      {tab === "saved" ? (
        <div className="mt-4">
          <SavedReportsList onOpen={openSaved} reloadKey={savedReloadKey} />
        </div>
      ) : (
        <div className="mt-4 flex flex-col gap-4">
          <Card>
            <BuilderForm
              catalog={catalog}
              maxISO={maxISO}
              historyFromISO={run.result?.meta.history_from ?? null}
              metrics={metrics}
              dims={dims}
              filters={filters}
              period={period}
              onToggleMetric={toggleMetric}
              onAddDim={addDim}
              onRemoveDim={removeDim}
              onReorderDim={reorderDim}
              onFiltersChange={setFilters}
              onPeriodChange={setPeriodOverride}
            />

            <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-hair pt-4">
              <Button
                variant="brand"
                onClick={onBuild}
                disabled={!canBuild}
                loading={run.state === "loading"}
              >
                {run.state === "data" ? t("reports.rebuild") : t("reports.build")}
              </Button>
              <PillRow>
                <Button
                  variant="ghost"
                  onClick={() => {
                    setSaveNonce((n) => n + 1);
                    setShowSave(true);
                  }}
                  disabled={metrics.length === 0}
                >
                  {t("reports.save")}
                </Button>
                <Button variant="ghost" onClick={() => onExport("csv")} disabled={!run.ranSpec}>
                  {t("reports.export.csv")}
                </Button>
                <Button variant="ghost" onClick={() => onExport("xlsx")} disabled={!run.ranSpec}>
                  {t("reports.export.xlsx")}
                </Button>
              </PillRow>
              {/* Валюта сумм (П6): TRY / USD. USD — по фиксированному курсу. */}
              <label className="ml-auto flex items-center gap-1.5 text-[12px] text-steel">
                {t("reports.currency.label")}
                <select
                  value={currency}
                  onChange={(e) => onCurrency(e.target.value as ReportCurrency)}
                  className="rounded-md border border-hair bg-canvas px-2 py-1 text-[12px] text-ink"
                >
                  <option value="TRY">₺ TRY</option>
                  <option value="USD">$ USD</option>
                </select>
              </label>
              {/* Почему кнопки неактивны — иначе конструктор «не создаёт отчёт»
                  молча (П2 Василия: «не разобрался, как пользоваться»). */}
              {!canBuild ? (
                <span className="text-[12px] text-steel">
                  {metrics.length === 0
                    ? t("reports.build.needMetric")
                    : t("reports.build.needPeriod")}
                </span>
              ) : null}
            </div>
            {/* Пометка: USD по фикс-курсу (в данных нет по-транзакционного курса). */}
            {run.result?.meta.currency === "USD" && run.result.meta.usd_rate ? (
              <p className="mt-2 text-[11.5px] text-steel">
                {t("reports.currency.usdNote", { rate: run.result.meta.usd_rate })}
              </p>
            ) : null}
            {exportError ? <p className="mt-2 text-[12.5px] text-neg">{exportError}</p> : null}
          </Card>

          {/* 422 / ошибка исполнения — инлайн-баннер с текстом бэкенда */}
          {run.state === "error" ? (
            <Banner className="!mt-0">
              <span className="font-semibold text-neg">⚠ </span>
              {run.error}
            </Banner>
          ) : null}

          {/* предупреждение об исторической глубине */}
          {historyWarn ? (
            <Banner className="!mt-0">
              ⏳ {t("reports.warn.history", { date: formatDate(historyWarn) })}
            </Banner>
          ) : null}

          {/* результат: idle / loading / empty / data */}
          {run.state === "idle" ? (
            <EmptyState
              icon="📊"
              title={t("reports.result.idle.title")}
              description={t("reports.result.idle.desc")}
            />
          ) : run.state === "loading" ? (
            <div className="overflow-hidden rounded-card border border-hair bg-canvas p-4 space-y-2.5">
              {Array.from({ length: 6 }).map((_, i) => (
                <Skeleton key={i} className="h-6 w-full" />
              ))}
            </div>
          ) : run.state === "data" && run.result && run.ranSpec ? (
            run.result.rows.length === 0 ? (
              <EmptyState
                title={t("reports.result.empty.title")}
                description={t("reports.result.empty.desc")}
              />
            ) : (
              <div className="flex flex-col gap-2">
                <PivotTable
                  result={run.result}
                  dims={run.ranSpec.dims}
                  metrics={run.ranSpec.metrics}
                  catalog={catalog}
                />
                <Eyebrow>
                  {t("reports.result.meta", {
                    rows: formatInt(run.result.meta.result_rows),
                    ms: String(run.result.meta.took_ms),
                  })}
                </Eyebrow>
              </div>
            )
          ) : null}
        </div>
      )}

      {showSave ? (
        <SaveReportModal
          key={saveNonce}
          spec={buildSpec()}
          loaded={loaded}
          canOfficial={canOfficial}
          onClose={() => setShowSave(false)}
          onSaved={() => setSavedReloadKey((k) => k + 1)}
        />
      ) : null}
    </>
  );
}
