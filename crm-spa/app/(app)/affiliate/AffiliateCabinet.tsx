"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  Panel,
  DataTable,
  LifecycleBadge,
  VipBadge,
  Badge,
  ErrorState,
  type Column,
} from "@/components/ui";
import { useT, type Locale } from "@/lib/i18n";
import { PlayerCardModal } from "./PlayerCardModal";
import { lifecycleSignal, type AffiliatePlayer } from "./types";

/**
 * Client root for the affiliate cabinet: lists the affiliate's players with stage +
 * model signal, and opens a shortened card (PlayerCardModal) per player.
 *
 * i18n-провайдер живёт ГЛОБАЛЬНО в app/(app)/layout.tsx — здесь его оборачивать
 * НЕЛЬЗЯ: вложенный провайдер не реагировал бы на переключатель языка в шапке.
 */

export interface AffiliateCabinetProps {
  /** @deprecated локаль раздаёт глобальный I18nProvider; проп оставлен для совместимости вызова. */
  locale?: Locale;
  code: string;
  players: AffiliatePlayer[];
  error?: boolean;
}

export function AffiliateCabinet({ code, players, error }: AffiliateCabinetProps) {
  const t = useT();
  const router = useRouter();
  const [selected, setSelected] = useState<AffiliatePlayer | null>(null);

  const columns: Column<AffiliatePlayer>[] = [
    {
      key: "player",
      header: t("affiliate.col.player"),
      align: "left",
      id: true,
      render: (p) => p.display_id ?? `#${p.casino_player_id}`,
    },
    {
      key: "stage",
      header: t("affiliate.col.stage"),
      align: "left",
      render: (p) => <LifecycleBadge stage={p.lifecycle} />,
    },
    {
      key: "signal",
      header: t("affiliate.col.signal"),
      align: "left",
      render: (p) => {
        const s = lifecycleSignal(p.lifecycle);
        return (
          <Badge bg={s.bg} fg={s.fg}>
            {t(s.key)}
          </Badge>
        );
      },
    },
    {
      key: "vip",
      header: t("affiliate.col.vip"),
      align: "left",
      render: (p) => <VipBadge level={p.vip_level} />,
    },
    {
      key: "country",
      header: t("affiliate.col.country"),
      render: (p) => p.country ?? t("common.dash"),
    },
    {
      key: "notes",
      header: t("affiliate.col.notes"),
      render: (p) => (p.has_notes ? <span title={t("affiliate.notes.title")}>📝</span> : t("common.dash")),
    },
  ];

  return (
    <>
      <PageHeader
        title={t("affiliate.title")}
        lead={t("affiliate.lead", { code: code || "—" })}
      />

      <div className="mt-6">
        <Panel>
          {error ? (
            <ErrorState
              title={t("common.loadFailed")}
              description={t("common.loadFailedDesc")}
              retryLabel={t("common.retry")}
              onRetry={() => router.refresh()}
            />
          ) : (
            <DataTable
              columns={columns}
              rows={players}
              state={players.length === 0 ? "empty" : "data"}
              getRowKey={(p) => p.casino_player_id}
              getRowHref={undefined}
              emptyTitle={t("affiliate.empty.title")}
              emptyDescription={t("affiliate.empty.desc")}
            />
          )}
        </Panel>
      </div>

      {/* Row click opens the shortened card. DataTable rows aren't buttons, so we
          bind selection via a thin overlay list is unnecessary — attach onClick
          through a wrapper table would fight the primitive; instead we render an
          invisible click layer per row is overkill. Simplest: clickable names. */}
      {!error && players.length > 0 ? (
        <div className="mt-3 text-[12.5px] text-steel">
          {t("affiliate.card.title")}:{" "}
          <span className="inline-flex flex-wrap gap-1.5 align-middle">
            {players.map((p) => (
              <button
                key={p.casino_player_id}
                type="button"
                onClick={() => setSelected(p)}
                className="rounded-full border border-hair2 bg-canvas px-2.5 py-1 text-[12px] text-slate hover:border-primary hover:text-primary transition-colors cursor-pointer"
              >
                {p.display_id ?? `#${p.casino_player_id}`}
              </button>
            ))}
          </span>
        </div>
      ) : null}

      <PlayerCardModal player={selected} onClose={() => setSelected(null)} />
    </>
  );
}
