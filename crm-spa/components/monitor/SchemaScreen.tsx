"use client";

import {
  PageHeader,
  ModuleHeader,
  Eyebrow,
  Card,
  Badge,
  Banner,
  Pill,
  PillRow,
  ErrorState,
  Skeleton,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT, type MessageKey } from "@/lib/i18n";
import { useResource } from "./kit";
import type { SchemaData, SchemaColumn } from "./types";

/**
 * Roadmap-блок модуля «Данные / API» (ТЗ §3.7). Статичный: показывает, что́ уже
 * готово и что́ на подходе. Тона бейджей — из существующей палитры (зелёный
 * готово · стальной скоро · янтарный ждёт-казино), новых цветов не вводим.
 */
type RoadmapStatus = "done" | "soon" | "waitingCasino";

const ROADMAP: { key: string; labelKey: MessageKey; status: RoadmapStatus }[] = [
  { key: "multibrand", labelKey: "monitor.schema.roadmap.multibrand", status: "soon" },
  { key: "roles", labelKey: "monitor.schema.roadmap.roles", status: "done" },
  { key: "connectors", labelKey: "monitor.schema.roadmap.connectors", status: "soon" },
  { key: "bonusEvents", labelKey: "monitor.schema.roadmap.bonusEvents", status: "waitingCasino" },
];

const ROADMAP_STATUS: Record<RoadmapStatus, { bg: string; fg: string; labelKey: MessageKey }> = {
  done: { bg: "#e7f6ee", fg: "#1f9d57", labelKey: "monitor.schema.roadmap.status.done" },
  soon: { bg: "#eef2f6", fg: "#344054", labelKey: "monitor.schema.roadmap.status.soon" },
  waitingCasino: { bg: "#fef9c3", fg: "#854d0e", labelKey: "monitor.schema.roadmap.status.waitingCasino" },
};

/**
 * /schema — «Схема данных» (paritet с schema() борда). 4 таблицы ClickHouse с
 * live-счётчиками строк, связи через casino_player_id / session_id. Справочная:
 * доступна любому аутентифицированному (require_auth() в api/monitor.py).
 */

function ColumnChip({ col, t }: { col: SchemaColumn; t: ReturnType<typeof useT> }) {
  const KIND_STYLE: Record<SchemaColumn["kind"], { cls: string; title: string }> = {
    pk: { cls: "bg-cream text-primary border-beige", title: t("monitor.schema.pk") },
    fk: { cls: "bg-[#eef2ff] text-[#4338ca] border-[#e0e7ff]", title: t("monitor.schema.fk") },
    col: { cls: "bg-canvas text-steel border-hair2", title: "" },
  };
  const s = KIND_STYLE[col.kind];
  return (
    <span
      title={s.title || undefined}
      className={`inline-block text-[11.5px] font-mono rounded-full border px-2.5 py-[3px] ${s.cls}`}
    >
      {col.name}
    </span>
  );
}

export function SchemaScreen() {
  const t = useT();
  const { state, data, error, reload } = useResource<SchemaData>("/api/v1/schema");
  const loading = state === "loading";
  const d = data;

  return (
    <>
      <PageHeader
        title={t("monitor.schema.title")}
        accent={t("monitor.schema.accent")}
        lead={t("monitor.schema.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.schema.pill.liveCounters")}</Pill>
          </PillRow>
        }
      />

      <ModuleHeader module="data" />

      <Card className="mt-6">
        <Eyebrow>{t("monitor.schema.roadmap.eyebrow")}</Eyebrow>
        <ul className="mt-3 flex flex-col gap-2.5">
          {ROADMAP.map((it) => {
            const s = ROADMAP_STATUS[it.status];
            return (
              <li key={it.key} className="flex items-center justify-between gap-3 text-[13.5px]">
                <span className="text-ink">{t(it.labelKey)}</span>
                <Badge bg={s.bg} fg={s.fg}>
                  {t(s.labelKey)}
                </Badge>
              </li>
            );
          })}
        </ul>
      </Card>

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          <Eyebrow>{t("monitor.schema.eyebrow.tables")}</Eyebrow>
          <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
            {loading
              ? Array.from({ length: 4 }).map((_, i) => (
                  <Card key={i}>
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-3 w-56 mt-3" />
                    <Skeleton className="h-16 w-full mt-4" />
                  </Card>
                ))
              : (d?.tables ?? []).map((tbl) => (
                  <Card key={tbl.name}>
                    <div className="flex items-baseline justify-between gap-3">
                      <h3 className="font-mono text-[15px] font-semibold text-ink">{tbl.name}</h3>
                      <span className="text-[12px] text-steel font-mono">{t("monitor.schema.rowsCount", { n: formatInt(tbl.rows) })}</span>
                    </div>
                    <div className="text-[13px] text-steel mt-1">
                      {tbl.role} · {t("monitor.schema.colsCount", { n: formatInt(tbl.cols_count) })}
                    </div>
                    <div className="flex flex-wrap gap-1.5 mt-3.5">
                      {tbl.columns.map((c) => (
                        <ColumnChip key={c.name} col={c} t={t} />
                      ))}
                    </div>
                  </Card>
                ))}
          </div>

          {d ? (
            <>
              <Eyebrow>{t("monitor.schema.eyebrow.relations")}</Eyebrow>
              <Banner>{d.relations}</Banner>
            </>
          ) : null}
        </>
      )}
    </>
  );
}
