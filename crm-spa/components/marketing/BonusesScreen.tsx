"use client";

import Link from "next/link";
import {
  PageHeader,
  Eyebrow,
  SCard,
  SCardGrid,
  Panel,
  Card,
  Banner,
  DataTable,
  Badge,
  type Column,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import type { BonusesResponse, CatalogBonus } from "./types";

export function BonusesScreen() {
  const t = useT();
  const { state, data, error, reload } = useFlaskData<BonusesResponse>("/api/v1/bonuses");
  const loading = state === "loading";
  const k = data?.kpi;

  const cols: Column<CatalogBonus>[] = [
    {
      key: "name",
      header: t("marketing.bonuses.col.promo"),
      align: "left",
      render: (r) => (
        <span>
          <span className="mr-1.5">{r.icon}</span>
          <b>{r.name_ru}</b>
          <span className="block text-[11px] text-steel">{r.name_tr}</span>
        </span>
      ),
    },
    {
      key: "kind",
      header: t("marketing.bonuses.col.typeZone"),
      align: "left",
      render: (r) => (
        <span className="whitespace-nowrap">
          <Badge bg="#f2f4f7" fg="#344054">{r.kind_label}</Badge>
          <span className="text-steel ml-1.5 text-[12px]">{r.area}</span>
        </span>
      ),
    },
    {
      key: "limits",
      header: t("marketing.bonuses.col.limits"),
      align: "left",
      render: (r) => (
        <span className="text-[12px]">
          <b>{r.percent_label}</b>
          {r.limits.length > 0 ? <span className="text-steel"> · {r.limits.join(" · ")}</span> : null}
        </span>
      ),
    },
    {
      key: "today",
      header: t("marketing.bonuses.col.today"),
      align: "left",
      render: (r) => (
        <span className="whitespace-nowrap text-[12px]">
          {r.available_today ? "🟢" : "⚪"} {r.days.join(", ")}
        </span>
      ),
    },
    { key: "players", header: t("marketing.bonuses.col.players"), mono: true, render: (r) => formatInt(r.players) },
    {
      key: "example",
      header: t("marketing.bonuses.col.example"),
      align: "left",
      render: (r) =>
        r.example_reason ? (
          <span className="text-[12px] text-steel">
            {r.example_player != null ? (
              <>
                {t("marketing.bonuses.examplePrefix")}
                {/* id игрока → карточка (борд player_board.py:3635 <a href="/player/{id}">) */}
                <Link
                  href={`/players/${r.example_player}`}
                  className="text-primary hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  {r.example_player}
                </Link>
                {t("marketing.bonuses.exampleDash")}
              </>
            ) : null}
            {r.example_reason}
          </span>
        ) : (
          <span className="text-steel">—</span>
        ),
    },
  ];

  return (
    <>
      <PageHeader
        title={<>{t("marketing.bonuses.title")}</>}
        lead={t("marketing.bonuses.lead")}
      />

      {state === "error" ? (
        <Card className="mt-5">
          <div className="text-neg text-[13.5px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <>
          <div className="mt-5">
            <SCardGrid>
              <SCard
                loading={loading}
                variant="orange"
                icon="🎁"
                label={t("marketing.bonuses.card.catalogSize.label")}
                value={formatInt(k?.catalog_size)}
                sub={t("marketing.bonuses.card.catalogSize.sub")}
              />
              <SCard
                loading={loading}
                icon="🟢"
                label={t("marketing.bonuses.card.availableToday.label")}
                value={formatInt(k?.available_today)}
                sub={t("marketing.bonuses.card.availableToday.sub")}
              />
              <SCard
                loading={loading}
                variant="cream"
                icon="🎯"
                label={t("marketing.bonuses.card.matched.label")}
                value={formatInt(k?.matched)}
                sub={t("marketing.bonuses.card.matched.sub", { n: formatInt(k?.total) })}
              />
              <SCard
                loading={loading}
                icon="⭐"
                label={t("marketing.bonuses.card.mostCommon.label")}
                value={<span className="text-[18px] font-mono break-all">{k?.most_common ?? "—"}</span>}
                sub={t("marketing.bonuses.card.mostCommon.sub")}
              />
            </SCardGrid>
          </div>

          <div className="mt-6">
            <Eyebrow>{t("marketing.bonuses.catalogEyebrow.main")} <span className="text-steel font-normal">{t("marketing.bonuses.catalogEyebrow.note")}</span></Eyebrow>
            <Panel>
              <DataTable
                columns={cols}
                rows={data?.bonuses ?? []}
                getRowKey={(r) => r.id}
                state={loading ? "loading" : data && data.bonuses.length === 0 ? "empty" : "data"}
                emptyTitle={t("marketing.bonuses.empty.title")}
              />
            </Panel>
          </div>

          <Banner>
            {t("marketing.bonuses.banner")}
          </Banner>
        </>
      )}
    </>
  );
}
