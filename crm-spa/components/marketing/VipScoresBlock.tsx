"use client";

import { Eyebrow, Card, SCard, SCardGrid, Badge, Banner } from "@/components/ui";
import { formatInt, formatPct } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useFlaskData } from "./useFlaskData";
import type { VipModel, VipScoresResponse } from "./types";

/**
 * VipScoresBlock — surfaces the three in-house VIP models
 * (vip_churn / early_vip / non_promising) from /api/v1/vip-scores.
 * Rendered as a block on the Actions screen (SPA_BUILD_PLAN.md §2C C4).
 */

function ModelCard({ model, icon, accent }: { model: VipModel; icon: string; accent: "alert" | "cream" | "orange" }) {
  const t = useT();
  if (!model.available) {
    return (
      <SCard
        variant="default"
        icon={icon}
        label={model.label}
        value="—"
        sub={t("marketing.vipScores.unavailable")}
      />
    );
  }
  return (
    <SCard
      variant={accent}
      icon={icon}
      label={model.label}
      value={formatInt(model.buckets?.ge_70 ?? 0)}
      sub={
        <>
          {t("marketing.vipScores.card.sub1", { scored: formatInt(model.scored ?? 0), avg: formatPct((model.avg ?? 0) * 100) })}
          <br />
          {t("marketing.vipScores.card.sub2", { ge90: formatInt(model.buckets?.ge_90 ?? 0), ge50: formatInt(model.buckets?.ge_50 ?? 0) })}
        </>
      }
    />
  );
}

export function VipScoresBlock() {
  const t = useT();
  const { state, data, error, reload } = useFlaskData<VipScoresResponse>("/api/v1/vip-scores");

  const modelMeta: {
    key: keyof VipScoresResponse["models"];
    icon: string;
    accent: "alert" | "cream" | "orange";
    action: string;
  }[] = [
    { key: "vip_churn", icon: "🚨", accent: "alert", action: t("marketing.vipScores.action.churn") },
    { key: "early_vip", icon: "💎", accent: "cream", action: t("marketing.vipScores.action.early") },
    { key: "non_promising", icon: "🧹", accent: "orange", action: t("marketing.vipScores.action.nonPromising") },
  ];

  const tableHeaders = [
    t("marketing.vipScores.col.id"),
    t("marketing.vipScores.col.score"),
    t("marketing.vipScores.col.stage"),
    t("marketing.vipScores.col.vip"),
    t("marketing.vipScores.col.turnover"),
    t("marketing.vipScores.col.dep"),
    t("marketing.vipScores.col.silence"),
  ];
  const daySuffix = t("marketing.vipScores.daySuffix");

  return (
    <section className="mt-7">
      <Eyebrow>
        {t("marketing.vipScores.eyebrow.main")} <span className="text-steel font-normal">{t("marketing.vipScores.eyebrow.note")}</span>
      </Eyebrow>

      {state === "loading" ? (
        <SCardGrid className="lg:grid-cols-3">
          <SCard loading label="" value="" />
          <SCard loading label="" value="" />
          <SCard loading label="" value="" />
        </SCardGrid>
      ) : state === "error" ? (
        <Card className="mt-2">
          <div className="text-neg text-[13px]">{error}</div>
          <button onClick={reload} className="mt-2 text-primary text-[13px] underline">
            {t("common.retry")}
          </button>
        </Card>
      ) : (
        <>
          <SCardGrid className="lg:grid-cols-3">
            {modelMeta.map((m) => (
              <ModelCard key={m.key} model={data!.models[m.key]} icon={m.icon} accent={m.accent} />
            ))}
          </SCardGrid>

          <Banner className="mt-3">
            🤖 {t("marketing.vipScores.banner.p1")} <b>{t("marketing.vipScores.banner.bold1")}</b>{" "}
            {t("marketing.vipScores.banner.p2")}
            <b> {t("marketing.vipScores.banner.bold2")}</b> {t("marketing.vipScores.banner.p3")}{" "}
            <b>{t("marketing.vipScores.banner.bold3")}</b> {t("marketing.vipScores.banner.p4")}{" "}
            <b>{t("marketing.vipScores.banner.bold4")}</b> {t("marketing.vipScores.banner.p5")}
          </Banner>

          {modelMeta.map((m) => {
            const model = data!.models[m.key];
            if (!model.available || !model.top || model.top.length === 0) return null;
            return (
              <div key={m.key} className="mt-4">
                <div className="text-[13px] text-slate font-medium mb-1.5">
                  {m.icon} {model.label}
                  <span className="text-steel font-normal"> {t("marketing.vipScores.topByScore")} {m.action}</span>
                </div>
                <Card padded={false} className="overflow-x-auto">
                  <table className="w-full border-collapse text-[13px]">
                    <thead>
                      <tr>
                        {tableHeaders.map((h, i) => (
                          <th
                            key={h}
                            className={
                              "bg-surface px-3 py-2 border-b border-hair text-steel text-[11px] uppercase tracking-[0.5px] whitespace-nowrap " +
                              (i === 0 ? "text-left" : "text-right")
                            }
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {model.top.slice(0, 8).map((p) => (
                        <tr key={p.player_id} className="hover:bg-cream transition-colors">
                          <td className="px-3 py-2 border-b border-hair font-mono text-primary text-left">
                            {p.player_id}
                          </td>
                          <td className="px-3 py-2 border-b border-hair font-mono text-right font-semibold">
                            {formatPct((p.score ?? 0) * 100)}
                          </td>
                          <td className="px-3 py-2 border-b border-hair text-right">
                            <Badge bg="#f1f5f9" fg="#475569">{p.lifecycle}</Badge>
                          </td>
                          <td className="px-3 py-2 border-b border-hair font-mono text-right">{p.vip_level}</td>
                          <td className="px-3 py-2 border-b border-hair font-mono text-right">
                            {formatInt(p.turnover)}
                          </td>
                          <td className="px-3 py-2 border-b border-hair font-mono text-right">{p.dep_count}</td>
                          <td className="px-3 py-2 border-b border-hair font-mono text-right">
                            {p.recency_days}{daySuffix}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </Card>
              </div>
            );
          })}
        </>
      )}
    </section>
  );
}
