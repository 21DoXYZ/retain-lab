"use client";

import { useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Card, PageHeader, Spinner, ErrorState } from "@/components/ui";

/**
 * «Деньги» (JTBD фаундера): откуда деньги и ПОЧЕМУ изменились. Ядро -
 * разложение: собрано = регистрации × активация × конверсия × чек, худший
 * множитель подсвечен - его и чинить. Плюс отмены с причинами.
 */

interface Factor { key: string; prev: number; cur: number; delta_pct: number | null }
interface Data {
  decomposition: {
    current: { cash: number; signups: number; payers: number };
    previous: { cash: number };
    factors: Factor[]; worst: string;
  } | null;
  cancel_reasons: { category: string; count: number; mrr_lost: number; examples: string[] }[] | null;
  cash: { d30: { collected: number; recurring: number; onetime: number; onetime_count: number; invoices: number } } | null;
  revenue: { plans: { plan: string; count: number; mrr: number; share: number }[]; mrr_total: number } | null;
}

const usd = (n: number) => "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtF = (k: string, v: number) =>
  k === "avg_check" ? usd(v) : k.endsWith("_rate") ? `${v}%` : v.toLocaleString("en-US");

export function MoneyView() {
  const t = useT();
  const [data, setData] = useState<Data | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "err">("loading");

  useEffect(() => {
    flaskFetch<Data>("/api/v1/saas/money")
      .then((d) => { setData(d); setState("ok"); })
      .catch(() => setState("err"));
  }, []);

  if (state === "loading") return <div className="py-16 flex justify-center"><Spinner /></div>;
  if (state === "err" || !data) return <ErrorState />;

  const d = data.decomposition;
  const cash = data.cash?.d30;
  const plans = data.revenue?.plans ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader title={t("saas.money.title")} lead={t("saas.money.lead")} />

      {/* Итог 30 дней */}
      {cash && (
        <Card className="p-6">
          <div className="flex flex-wrap items-start gap-x-10 gap-y-4">
            <div>
              <div className="text-[12px] font-medium text-steel">{t("saas.money.collected")}</div>
              <div className="mt-1 text-[32px] leading-none font-bold tracking-[-0.5px] text-ink tabular-nums">
                {usd(cash.collected)}
              </div>
              <div className="mt-1.5 text-[13px] text-steel tabular-nums">
                {cash.invoices} {t("saas.money.invoices")}
                {d?.previous.cash ? (
                  <> · {t("saas.money.vsPrev")}{" "}
                    <b className={cash.collected >= d.previous.cash ? "text-pos" : "text-neg"}>
                      {cash.collected >= d.previous.cash ? "+" : ""}
                      {Math.round(((cash.collected - d.previous.cash) / d.previous.cash) * 100)}%
                    </b>
                  </>
                ) : null}
              </div>
            </div>
            <div className="pt-[3px]">
              <div className="text-[12px] font-medium text-steel">{t("saas.money.recurring")}</div>
              <div className="mt-1 text-[22px] leading-none font-semibold text-ink tabular-nums">{usd(cash.recurring)}</div>
            </div>
            <div className="pt-[3px]">
              <div className="text-[12px] font-medium text-steel">{t("saas.money.onetime")}</div>
              <div className="mt-1 text-[22px] leading-none font-semibold text-ink tabular-nums">{usd(cash.onetime)}</div>
              <div className="mt-1 text-[12px] text-steel tabular-nums">{cash.onetime_count} {t("saas.money.payments")}</div>
            </div>
          </div>
        </Card>
      )}

      {/* Разложение: что именно изменилось */}
      {d && (
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold text-ink">{t("saas.money.decomp")}</h2>
          <p className="mt-1 text-[13px] text-steel">{t("saas.money.decompLead")}</p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {d.factors.map((f) => {
              const isWorst = f.key === d.worst;
              return (
                <div key={f.key}
                  className={"rounded-ctl border p-4 " + (isWorst ? "border-neg bg-neg/5" : "border-hair bg-surface")}>
                  <div className="text-[12px] font-medium text-steel">
                    {t(`saas.money.f.${f.key}` as MessageKey)}
                  </div>
                  <div className="mt-1 text-[22px] font-semibold text-ink tabular-nums">
                    {fmtF(f.key, f.cur)}
                  </div>
                  <div className="mt-1 text-[12px] tabular-nums">
                    <span className="text-steel">{fmtF(f.key, f.prev)} &rarr; </span>
                    {f.delta_pct === null ? (
                      <span className="text-steel">-</span>
                    ) : (
                      <span className={f.delta_pct >= 0 ? "font-semibold text-pos" : "font-semibold text-neg"}>
                        {f.delta_pct >= 0 ? "+" : ""}{f.delta_pct}%
                      </span>
                    )}
                  </div>
                  {isWorst ? (
                    <div className="mt-2 text-[12px] font-medium text-neg">{t("saas.money.worst")}</div>
                  ) : null}
                </div>
              );
            })}
          </div>
        </Card>
      )}

      <div className="grid gap-5 lg:grid-cols-2">
        {/* Отмены с причинами */}
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold text-ink">{t("saas.money.cancels")}</h2>
          {data.cancel_reasons?.length ? (
            <div className="mt-3 flex flex-col">
              {data.cancel_reasons.map((c) => (
                <div key={c.category} className="border-b border-hair py-2.5 last:border-0">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-[13px] font-medium text-ink">
                      {t(`saas.money.cr.${c.category}` as MessageKey)}
                    </span>
                    <span className="flex-none text-[13px] text-steel tabular-nums">
                      {c.count} · <span className="text-neg">-{usd(c.mrr_lost)}/{t("saas.ret.mo")}</span>
                    </span>
                  </div>
                  {c.examples[0] ? (
                    <p className="mt-1 text-[12.5px] italic text-steel">«{c.examples[0]}»</p>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <p className="mt-3 text-[13px] text-steel">{t("saas.money.noCancels")}</p>
          )}
        </Card>

        {/* По планам */}
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold text-ink">{t("saas.money.plans")}</h2>
          <div className="mt-3 flex flex-col gap-2.5">
            {plans.map((pl) => (
              <div key={pl.plan} className="flex items-center gap-3">
                <span className="w-32 flex-none truncate text-[13px] text-ink">
                  {pl.plan.startsWith("price_") && pl.count > 0
                    ? `${usd(Math.round(pl.mrr / pl.count))}/${t("saas.ret.mo")}`
                    : pl.plan}
                </span>
                <div className="h-2 flex-1 overflow-hidden rounded-full bg-surface">
                  <div className="h-full rounded-full bg-primary" style={{ width: `${pl.share}%` }} />
                </div>
                <span className="w-16 flex-none text-right text-[12px] tabular-nums text-ink">{usd(pl.mrr)}</span>
                <span className="w-8 flex-none text-right text-[11px] tabular-nums text-steel">{pl.count}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
