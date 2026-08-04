"use client";

import { useState } from "react";
import { Chip, DateInput, Select, Eyebrow, Button } from "@/components/ui";
import { useT } from "@/lib/i18n";
import { useDimValue } from "./dimValue";
import {
  DIM_KIND_ORDER,
  ENUM_VALUES,
  METRIC_SOURCE_ORDER,
  MAX_DIMS,
  isDimApplicable,
  isDimFilterable,
  metricUnit,
  presetPeriod,
  sourcesOfMetrics,
  type DimensionDef,
  type FieldsCatalog,
  type FilterValue,
  type PeriodPreset,
  type ReportFilter,
  type ReportPeriod,
} from "./types";
import { fieldLabel } from "./labels";
import type { MessageKey } from "@/lib/i18n";

/**
 * BuilderForm — панель сборки отчёта (метрики × разрезы × фильтры × период).
 * Полностью управляемый компонент: всё состояние живёт в ReportBuilder, сюда
 * приходит через props и меняется через колбэки (иммутабельно). Применимость
 * разрезов к источникам метрик считается на месте (skryto недопустимые), но
 * жёсткая граница — 422 бэкенда (баннер в ReportBuilder).
 */
interface BuilderFormProps {
  catalog: FieldsCatalog;
  maxISO: string | null;
  historyFromISO: string | null;
  metrics: string[];
  dims: string[];
  filters: ReportFilter[];
  period: ReportPeriod;
  onToggleMetric: (key: string) => void;
  onAddDim: (key: string) => void;
  onRemoveDim: (index: number) => void;
  onReorderDim: (index: number, delta: number) => void;
  onFiltersChange: (filters: ReportFilter[]) => void;
  onPeriodChange: (period: ReportPeriod) => void;
}

const DIM_KIND_KEY: Record<string, MessageKey> = {
  time: "reports.dims.group.time",
  profile: "reports.dims.group.profile",
  transaction: "reports.dims.group.transaction",
  state_at: "reports.dims.group.state_at",
};

export function BuilderForm(props: BuilderFormProps) {
  const {
    catalog, maxISO, historyFromISO, metrics, dims, filters, period,
    onToggleMetric, onAddDim, onRemoveDim, onReorderDim, onFiltersChange, onPeriodChange,
  } = props;
  const t = useT();
  const sources = sourcesOfMetrics(metrics, catalog);
  const allDims = Object.values(catalog.dimensions);

  // ── разрезы, доступные для добавления (применимы + ещё не выбраны) ──
  const addableDims = allDims.filter((d) => isDimApplicable(d, sources) && !dims.includes(d.key));
  // ── разрезы, доступные для фильтра (enum/строковые + применимы) ──
  const filterableDims = allDims.filter((d) => isDimFilterable(d) && isDimApplicable(d, sources));

  function addFilter(dimKey: string) {
    if (!dimKey) return;
    onFiltersChange([...filters, { dim: dimKey, op: "in", value: [] }]);
  }
  function updateFilter(index: number, patch: Partial<ReportFilter>) {
    onFiltersChange(filters.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  }
  function removeFilter(index: number) {
    onFiltersChange(filters.filter((_, i) => i !== index));
  }

  function applyPreset(preset: PeriodPreset) {
    if (!maxISO) return;
    onPeriodChange(presetPeriod(preset, maxISO, historyFromISO));
  }

  return (
    <div className="flex flex-col gap-6">
      {/* ── МЕТРИКИ ──────────────────────────────────────────────────────── */}
      <section>
        <Eyebrow>{t("reports.section.metrics")}</Eyebrow>
        <p className="text-[12px] text-steel mt-0.5 mb-2">{t("reports.section.metrics.hint")}</p>
        <div className="flex flex-col gap-2.5">
          {METRIC_SOURCE_ORDER.map((src) => {
            const items = Object.values(catalog.metrics).filter((m) => m.source === src);
            if (items.length === 0) return null;
            return (
              <div key={src} className="flex flex-wrap items-center gap-1.5">
                <span className="text-[11px] uppercase tracking-[0.5px] text-stone w-16 shrink-0">
                  {t(`reports.metrics.source.${src}` as MessageKey)}
                </span>
                {items.map((m) => (
                  <Chip key={m.key} active={metrics.includes(m.key)} onClick={() => onToggleMetric(m.key)}>
                    <span className="text-stone mr-1">{metricUnit(m)}</span>
                    {fieldLabel(t, m.key, m.label)}
                  </Chip>
                ))}
              </div>
            );
          })}
        </div>
        {metrics.length === 0 ? (
          <p className="text-[12px] text-neg mt-2">{t("reports.metrics.empty")}</p>
        ) : null}
      </section>

      {/* ── РАЗРЕЗЫ ──────────────────────────────────────────────────────── */}
      <section>
        <Eyebrow>{t("reports.section.dims")}</Eyebrow>
        <p className="text-[12px] text-steel mt-0.5 mb-2">{t("reports.section.dims.hint")}</p>

        {dims.length === 0 ? (
          <p className="text-[12.5px] text-steel italic mb-2">{t("reports.dims.empty")}</p>
        ) : (
          <div className="flex flex-col gap-1.5 mb-2.5">
            {dims.map((key, i) => {
              const d = catalog.dimensions[key];
              return (
                <div
                  key={key}
                  className="flex items-center gap-2 bg-canvas border border-hair2 rounded-ctl px-3 py-2"
                >
                  <span className="text-[11px] font-mono text-stone w-14 shrink-0">
                    {t("reports.dims.level", { n: String(i + 1) })}
                  </span>
                  <span className="text-[13.5px] font-medium text-ink flex-1 truncate">
                    {d ? fieldLabel(t, d.key, d.label) : key}
                  </span>
                  <button
                    type="button"
                    onClick={() => onReorderDim(i, -1)}
                    disabled={i === 0}
                    aria-label={t("reports.dims.up")}
                    className="text-steel hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed px-1 cursor-pointer"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    onClick={() => onReorderDim(i, 1)}
                    disabled={i === dims.length - 1}
                    aria-label={t("reports.dims.down")}
                    className="text-steel hover:text-primary disabled:opacity-30 disabled:cursor-not-allowed px-1 cursor-pointer"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => onRemoveDim(i)}
                    aria-label={t("reports.dims.remove")}
                    className="text-steel hover:text-neg px-1 text-lg leading-none cursor-pointer"
                  >
                    ×
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <div className="flex items-center gap-2">
          <Select
            aria-label={t("reports.dims.add")}
            value=""
            disabled={dims.length >= MAX_DIMS || addableDims.length === 0}
            onChange={(e) => onAddDim(e.target.value)}
            className="max-w-xs"
          >
            <option value="">{t("reports.dims.add")}</option>
            {DIM_KIND_ORDER.map((kind) => {
              const group = addableDims.filter((d) => d.kind === kind);
              if (group.length === 0) return null;
              return (
                <optgroup key={kind} label={t(DIM_KIND_KEY[kind])}>
                  {group.map((d) => (
                    <option key={d.key} value={d.key}>
                      {fieldLabel(t, d.key, d.label)}
                    </option>
                  ))}
                </optgroup>
              );
            })}
          </Select>
          {dims.length >= MAX_DIMS ? (
            <span className="text-[12px] text-stone">{t("reports.dims.max")}</span>
          ) : null}
        </div>
      </section>

      {/* ── ФИЛЬТРЫ ──────────────────────────────────────────────────────── */}
      <section>
        <Eyebrow>{t("reports.section.filters")}</Eyebrow>
        {filters.length === 0 ? (
          <p className="text-[12.5px] text-steel italic mt-1 mb-2">{t("reports.filters.empty")}</p>
        ) : (
          <div className="flex flex-col gap-2 mt-2 mb-2.5">
            {filters.map((f, i) => (
              <FilterRow
                key={`${f.dim}-${i}`}
                catalog={catalog}
                filter={f}
                onOp={(op) => updateFilter(i, { op })}
                onValue={(value) => updateFilter(i, { value })}
                onRemove={() => removeFilter(i)}
              />
            ))}
          </div>
        )}
        <Select
          aria-label={t("reports.filters.add")}
          value=""
          disabled={filterableDims.length === 0}
          onChange={(e) => addFilter(e.target.value)}
          className="max-w-xs"
        >
          <option value="">{t("reports.filters.add")}</option>
          {DIM_KIND_ORDER.map((kind) => {
            const group = filterableDims.filter((d) => d.kind === kind);
            if (group.length === 0) return null;
            return (
              <optgroup key={kind} label={t(DIM_KIND_KEY[kind])}>
                {group.map((d) => (
                  <option key={d.key} value={d.key}>
                    {fieldLabel(t, d.key, d.label)}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </Select>
      </section>

      {/* ── ПЕРИОД ───────────────────────────────────────────────────────── */}
      <section>
        <Eyebrow>{t("reports.section.period")}</Eyebrow>
        <div className="flex flex-wrap items-end gap-3 mt-2">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-[0.5px] text-stone">
              {t("reports.period.from")}
            </span>
            <DateInput
              value={period.from}
              max={period.to || maxISO || undefined}
              onChange={(e) => onPeriodChange({ ...period, from: e.target.value })}
              className="w-[150px]"
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] uppercase tracking-[0.5px] text-stone">
              {t("reports.period.to")}
            </span>
            <DateInput
              value={period.to}
              min={period.from || undefined}
              max={maxISO || undefined}
              onChange={(e) => onPeriodChange({ ...period, to: e.target.value })}
              className="w-[150px]"
            />
          </label>
          <div className="flex gap-1.5 pb-1">
            <Button variant="ghost" size="sm" disabled={!maxISO} onClick={() => applyPreset("30d")}>
              {t("reports.period.preset.30d")}
            </Button>
            <Button variant="ghost" size="sm" disabled={!maxISO} onClick={() => applyPreset("quarter")}>
              {t("reports.period.preset.quarter")}
            </Button>
            <Button variant="ghost" size="sm" disabled={!maxISO} onClick={() => applyPreset("all")}>
              {t("reports.period.preset.all")}
            </Button>
          </div>
        </div>
      </section>
    </div>
  );
}

// ── строка фильтра ────────────────────────────────────────────────────────
interface FilterRowProps {
  catalog: FieldsCatalog;
  filter: ReportFilter;
  onOp: (op: "in" | "not_in") => void;
  onValue: (value: FilterValue[]) => void;
  onRemove: () => void;
}

function FilterRow({ catalog, filter, onOp, onValue, onRemove }: FilterRowProps) {
  const t = useT();
  const dim = catalog.dimensions[filter.dim];
  const enumValues = ENUM_VALUES[filter.dim];

  return (
    <div className="flex flex-wrap items-center gap-2 bg-canvas border border-hair2 rounded-ctl px-3 py-2">
      <span className="text-[13px] font-medium text-ink shrink-0">{dim ? fieldLabel(t, dim.key, dim.label) : filter.dim}</span>
      <Select
        aria-label={t("reports.filters.op.in")}
        value={filter.op}
        onChange={(e) => onOp(e.target.value as "in" | "not_in")}
        className="w-[120px] h-[34px]"
      >
        <option value="in">{t("reports.filters.op.in")}</option>
        <option value="not_in">{t("reports.filters.op.not_in")}</option>
      </Select>

      <div className="flex-1 min-w-[180px]">
        {dim && enumValues ? (
          <EnumValues dim={dim} values={enumValues} selected={filter.value} onChange={onValue} />
        ) : (
          <StrValues key={filter.dim} value={filter.value} onChange={onValue} />
        )}
      </div>

      <button
        type="button"
        onClick={onRemove}
        aria-label={t("reports.filters.remove")}
        className="text-steel hover:text-neg px-1 text-lg leading-none cursor-pointer shrink-0"
      >
        ×
      </button>
    </div>
  );
}

// enum-значения чипами (день недели / час / VIP / цикл / тир)
function EnumValues({
  dim, values, selected, onChange,
}: {
  dim: DimensionDef;
  values: FilterValue[];
  selected: FilterValue[];
  onChange: (v: FilterValue[]) => void;
}) {
  const t = useT();
  const dimValue = useDimValue();
  const selSet = new Set(selected.map(String));
  function toggle(v: FilterValue) {
    const key = String(v);
    onChange(selSet.has(key) ? selected.filter((x) => String(x) !== key) : [...selected, v]);
  }
  return (
    <div className="flex flex-wrap gap-1">
      {selected.length === 0 ? (
        <span className="text-[12px] text-stone italic self-center mr-1">{t("reports.filters.pick")}</span>
      ) : null}
      {values.map((v) => (
        <Chip key={String(v)} active={selSet.has(String(v))} onClick={() => toggle(v)}>
          {dimValue(dim, v)}
        </Chip>
      ))}
    </div>
  );
}

// строковые значения — ввод через запятую (домен открытый: страна/валюта/метод…)
function StrValues({ value, onChange }: { value: FilterValue[]; onChange: (v: FilterValue[]) => void }) {
  const t = useT();
  const [text, setText] = useState(value.map(String).join(", "));
  return (
    <input
      value={text}
      placeholder={t("reports.filters.values.placeholder")}
      title={t("reports.filters.values.hint")}
      onChange={(e) => {
        setText(e.target.value);
        const parsed = e.target.value
          .split(",")
          .map((s) => s.trim())
          .filter((s) => s.length > 0);
        onChange(parsed);
      }}
      className="w-full bg-canvas text-ink border border-hair3 rounded-ctl px-3 h-[34px] text-[13px] outline-none focus:border-2 focus:border-primary placeholder:text-stone"
    />
  );
}
