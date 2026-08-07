"use client";

import { useCallback, useEffect, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT, type MessageKey } from "@/lib/i18n";
import { Button, Card, DataTable, PageHeader, type Column, type TableState } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /offers — каталог офферов тенанта + статистика выдач. Щедрость и лимиты
 * редактируются здесь (overrides поверх базового каталога, без деплоя):
 * GET /api/v1/saas/offers, POST /api/v1/saas/offers/update.
 */

interface OfferRow {
  offer_id: string;
  title: string;
  executor: string;
  monetary: boolean;
  cost_estimate: number;
  max_per_user_30d: number;
  params: Record<string, unknown>;
  edited: boolean;
  custom: boolean;
  disabled: boolean;
  stats: { issued: number; dry_run: number; holdout: number; rejected: number };
  role: string;
  stage: string;
  economics: {
    cost?: number; share?: number; payback_months?: number;
    ok?: boolean; note?: string;
    // cash - деньги, которые уйдут со счёта; monthly_margin - из чего подарок
    // окупается; basis - измерено, предположено по типу бизнеса или неизвестно
    cash?: number | null; monthly_margin?: number | null;
    basis?: "stated" | "margin" | "assumed" | "price";
  };
  /** ступень лестницы уступок: слово -> отсрочка -> маржа -> выручка -> деньги */
  tier?: number;
  /** сколько сделка приносит после вычета уступки; blocked - почему отложена */
  ev?: number | null;
  blocked?: {
    code: "stake_too_small" | "budget_spent" | "cheaper_rung_first" | "negative_value";
    stake?: number; budget?: number; tier?: number;
    gain?: number | null; cost?: number | null;
  } | null;
}

interface OffersData {
  control_pct: number;
  offers: OfferRow[];
  /** измерена ли себестоимость или пока предположена - решает тон всего экрана */
  cost_basis?: "stated" | "margin" | "assumed" | "price";
  monthly_margin?: number | null;
}

/** Типы подарков - человеческий язык; исполнитель и command под капотом.
 * Поля = ключи params (лейблы в i18n saas.offers.p.*). */
const GIFT_TYPES: { key: string; executor: string; fields: { key: string; kind: "str" | "num"; req: boolean }[] }[] = [
  { key: "units", executor: "client_callback", fields: [
    { key: "amount", kind: "num", req: true },
    { key: "unit", kind: "str", req: true },
    { key: "expires_days", kind: "num", req: false },
  ]},
  { key: "discount", executor: "stripe_coupon", fields: [
    { key: "percent_off", kind: "num", req: true },
    { key: "duration_in_months", kind: "num", req: true },
  ]},
  { key: "trial", executor: "trial_extend", fields: [{ key: "days", kind: "num", req: true }]},
  { key: "pause", executor: "pause_collection", fields: [{ key: "months", kind: "num", req: true }]},
  { key: "credit", executor: "balance_credit", fields: [{ key: "amount_usd", kind: "num", req: true }]},
];

const inputCls =
  "h-[38px] w-full rounded-ctl border border-hair2 bg-canvas px-3 text-[13px] " +
  "text-ink outline-none transition-[border-color] duration-150 focus:border-primary";

function OfferEditor({
  offer,
  onDone,
}: {
  offer: OfferRow;
  onDone: (reload: boolean) => void;
}) {
  const t = useT();
  const numericParams = Object.entries(offer.params).filter(
    ([, v]) => typeof v === "number",
  ) as [string, number][];

  const [title, setTitle] = useState(offer.title);
  const [cap, setCap] = useState(String(offer.max_per_user_30d));
  const [params, setParams] = useState<Record<string, string>>(
    Object.fromEntries(numericParams.map(([k, v]) => [k, String(v)])),
  );
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const post = (body: Record<string, unknown>) => {
    setBusy(true);
    setErr("");
    flaskFetch("/api/v1/saas/offers/update", {
      method: "POST",
      body: { offer_id: offer.offer_id, ...body },
    })
      .then(() => onDone(true))
      .catch((e: unknown) => setErr(e instanceof Error ? e.message : t("saas.channels.err.generic")))
      .finally(() => setBusy(false));
  };

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="flex items-baseline justify-between gap-3">
        <div className="text-[15px] font-semibold text-ink">
          {t("saas.offers.editTitle")}{" "}
          <span className="font-mono text-[12px] text-steel">{offer.offer_id}</span>
        </div>
        {offer.edited && (
          <span className="rounded-full border border-[#b2ddff] bg-[#eff8ff] px-2 py-0.5 text-[10.5px] font-semibold text-primary">
            {t("saas.camp.edited")}
          </span>
        )}
      </div>

      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.f.title")}
          <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.col.limit")}
          <input className={inputCls} value={cap} inputMode="numeric"
                 onChange={(e) => setCap(e.target.value)} />
        </label>
        {numericParams.map(([k]) => (
          <label key={k} className="flex flex-col gap-1 text-[12px] text-steel">
            <span className="font-mono">{k}</span>
            <input
              className={inputCls}
              value={params[k] ?? ""}
              inputMode="decimal"
              onChange={(e) => setParams((p) => ({ ...p, [k]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <p className="text-[11.5px] text-steel">{t("saas.offers.f.note")}</p>
      {err && <p className="text-[12px] text-neg">{err}</p>}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="brand" size="sm" loading={busy}
          onClick={() =>
            post({
              title,
              max_per_user_30d: Number(cap),
              params: Object.fromEntries(
                Object.entries(params).map(([k, v]) => [k, Number(v)]),
              ),
            })
          }
        >
          {t("saas.camp.save")}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDone(false)}>
          {t("saas.camp.cancel")}
        </Button>
        {offer.edited && (
          <Button variant="ghost" size="sm" loading={busy} onClick={() => post({ reset: true })}>
            {t("saas.camp.resetDefault")}
          </Button>
        )}
      </div>
    </Card>
  );
}

function NewOfferForm({ onDone }: { onDone: (reload: boolean) => void }) {
  const t = useT();
  const [title, setTitle] = useState("");
  const [gift, setGift] = useState("units");
  const [cap, setCap] = useState("1");
  const [cost, setCost] = useState("0");
  const [params, setParams] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const giftType = GIFT_TYPES.find((g) => g.key === gift) ?? GIFT_TYPES[0];
  const fields = giftType.fields;

  return (
    <Card className="flex flex-col gap-3 p-5">
      <div className="text-[15px] font-semibold text-ink">{t("saas.offers.new.title")}</div>
      <p className="text-[13px] text-steel">{t("saas.offers.new.lead")}</p>

      <div className="grid gap-2.5 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-[12px] text-steel sm:col-span-2">
          {t("saas.offers.f.title")}
          <input className={inputCls} placeholder={t("saas.offers.new.titlePh")}
                 value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.new.giftType")}
          <select
            className={inputCls + " cursor-pointer"}
            value={gift}
            onChange={(e) => {
              setGift(e.target.value);
              setParams({});
            }}
          >
            {GIFT_TYPES.map((g) => (
              <option key={g.key} value={g.key}>{t(`saas.offers.gift.${g.key}` as Parameters<typeof t>[0])}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.col.limit")}
          <input className={inputCls} value={cap} inputMode="numeric"
                 onChange={(e) => setCap(e.target.value)} />
        </label>
        {fields.map((f) => (
          <label key={f.key} className="flex flex-col gap-1 text-[12px] text-steel">
            <span>
              {t(`saas.offers.p.${f.key}` as Parameters<typeof t>[0])}
              {f.req ? " *" : ""}
            </span>
            <input className={inputCls} value={params[f.key] ?? ""}
                   inputMode={f.kind === "num" ? "decimal" : "text"}
                   onChange={(e) => setParams((p) => ({ ...p, [f.key]: e.target.value }))} />
          </label>
        ))}
        <label className="flex flex-col gap-1 text-[12px] text-steel">
          {t("saas.offers.col.cost")}
          <input className={inputCls} value={cost} inputMode="decimal"
                 onChange={(e) => setCost(e.target.value)} />
        </label>
      </div>
      <p className="text-[11.5px] text-steel">{t("saas.offers.exec.hint")}</p>
      {err && <p className="text-[12px] text-neg">{err}</p>}

      <div className="flex flex-wrap gap-2">
        <Button
          variant="brand" size="sm" loading={busy} disabled={!title.trim()}
          onClick={() => {
            setBusy(true);
            setErr("");
            const extra: Record<string, unknown> = {};
            if (gift === "discount") {
              extra.duration = "repeating";   // купон на N месяцев
            }
            const body: Record<string, unknown> = {
              title: title.trim(), executor: giftType.executor,
              max_per_user_30d: Number(cap), cost_estimate: Number(cost),
              params: {
                ...Object.fromEntries(
                  Object.entries(params).filter(([, v]) => v !== "").map(([k, v]) => {
                    const f = fields.find((x) => x.key === k);
                    return [k, f?.kind === "num" ? Number(v) : v];
                  }),
                ),
                ...extra,
              },
            };
            flaskFetch("/api/v1/saas/offers/create", { method: "POST", body })
              .then(() => onDone(true))
              .catch((e: unknown) => setErr(e instanceof Error ? e.message : t("saas.channels.err.generic")))
              .finally(() => setBusy(false));
          }}
        >
          {t("saas.offers.new.create")}
        </Button>
        <Button variant="ghost" size="sm" disabled={busy} onClick={() => onDone(false)}>
          {t("saas.camp.cancel")}
        </Button>
      </div>
    </Card>
  );
}

/**
 * Один подарок - одна карточка, которая читается фразой: что даём, кому,
 * во сколько обходится и как часто. Таблица с колонками COGS и executor
 * отвечала на вопросы инженера, а не владельца продукта.
 */
function OfferCard({ o, onEdit }: { o: OfferRow; onEdit: () => void }) {
  const t = useT();
  const params = Object.entries(o.params || {})
    .map(([k, v]) => `${k}: ${String(v)}`)
    .join(" · ");
  return (
    <div className={"rounded-card border p-4 " +
      (o.disabled ? "border-hair bg-surface opacity-60" : "border-hair bg-canvas")}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          <div className="text-[15px] font-semibold text-ink">{o.title}</div>
          {/* Чем платим за этот подарок - главное свойство оффера, а не деталь */}
          {o.tier != null && (
            <span className="rounded-full border border-hair2 bg-surface px-2 py-0.5 text-[11px] text-steel">
              {t("saas.offers.tier", { tier: t(`saas.offers.tier.${o.tier}` as MessageKey) })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded-full border border-hair2 px-2 py-0.5 text-[11px] text-steel">
            {o.offer_id.startsWith("C_") ? t("saas.offers.byOwner") : t("saas.offers.bySystem")}
          </span>
          {o.edited && <span className="rounded-full border border-[#b2ddff] bg-[#eff8ff] px-2 py-0.5 text-[11px] font-semibold text-primary">{t("saas.offers.editedTag")}</span>}
          <button type="button" onClick={onEdit}
                  className="cursor-pointer rounded-md border border-hair2 px-2 py-0.5 text-[11.5px] text-steel transition-[color,border-color] duration-150 hover:border-primary hover:text-primary">
            {t("saas.camp.edit")}
          </button>
        </div>
      </div>

      <p className="mt-1.5 text-[13px] leading-relaxed text-slate">
        {o.stage
          ? t("saas.offers.card.who", { stage: t(`saas.stage.${o.stage}` as MessageKey) })
          : t("saas.offers.card.whoUnknown")}{" "}
        {t(`saas.offers.how.${o.executor}` as MessageKey)}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-steel">
        <span className={o.economics?.ok === false ? "text-[#b54708]" : ""}>
          {costPhrase(t, o.economics)}
        </span>
        <span>{t("saas.offers.card.cap", { n: o.max_per_user_30d || 1 })}</span>
        {o.stats.issued + o.stats.dry_run > 0 && (
          <span>{t("saas.offers.card.issued", { n: o.stats.issued, dry: o.stats.dry_run })}</span>
        )}
        {o.stats.rejected > 0 && (
          <span>{t("saas.offers.card.rejected", { n: o.stats.rejected })}</span>
        )}
      </div>

      {/* Почему подарок стоит в очереди, а не выдаётся. Молчащий каталог -
          это то же серое неактивное состояние без объяснения причины. */}
      {o.blocked && (
        <p className="mt-1.5 text-[12px] leading-relaxed text-[#b54708]">
          {t("saas.offers.card.held")}{" "}
          {t(`saas.offers.held.${o.blocked.code}` as MessageKey, {
            stake: `$${o.blocked.stake ?? 0}`,
            budget: `$${o.blocked.budget ?? 0}`,
            gain: `$${o.blocked.gain ?? 0}`,
            cost: `$${o.blocked.cost ?? 0}`,
            tier: t(`saas.offers.tier.${o.blocked.tier ?? 0}` as MessageKey),
          })}
        </p>
      )}

      {params && (
        <div className="mt-1.5 font-mono text-[11.5px] text-steel">{params}</div>
      )}
    </div>
  );
}

/**
 * Цена подарка человеческой фразой.
 *
 * Живые деньги и недополученная выручка - РАЗНЫЕ вещи, и путать их опасно:
 * скидку платят из будущего, а себестоимость подарка списывают со счёта
 * сегодня, ещё до того, как человек решил остаться. Окупаемость всегда в
 * месяцах МАРЖИ: тариф за $99 при валовой марже 10% приносит $10 в месяц.
 */
function costPhrase(
  t: ReturnType<typeof useT>,
  e: OfferRow["economics"] | undefined,
): string {
  if (!e || e.cost == null || e.share == null) return t("saas.offers.card.costUnknown");
  if (e.cost === 0) return t("saas.offers.card.free");
  const payback = e.payback_months ?? 0;
  // Пока маржа не названа, окупаемость посчитана от ВЫРУЧКИ. Называть её
  // месяцами маржи в этот момент - вранье в пользу подарка.
  const measured = e.basis === "stated" || e.basis === "margin";
  if (e.cash != null && e.cash > 0 && e.monthly_margin != null && e.cash > e.monthly_margin) {
    return t("saas.offers.card.overMargin", {
      cost: `$${e.cash}`,
      margin: `$${e.monthly_margin}`,
    });
  }
  if (e.cash != null && e.cash > 0) {
    return t(measured ? "saas.offers.card.cashLine" : "saas.offers.card.cashLineRevenue",
             { cost: `$${e.cash}`, payback });
  }
  return t(measured ? "saas.offers.card.costLine" : "saas.offers.card.costLineRevenue", {
    cost: `$${e.cost}`,
    share: Math.round((e.share ?? 0) * 100),
    payback,
  });
}

export function OffersView() {
  const t = useT();
  const [data, setData] = useState<OffersData | null>(null);
  const [state, setState] = useState<TableState>("loading");
  const [noTenant, setNoTenant] = useState(false);
  const [editId, setEditId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const toggleDisabled = (r: OfferRow) => {
    setBusyId(r.offer_id);
    flaskFetch("/api/v1/saas/offers/disable", {
      method: "POST",
      body: { offer_id: r.offer_id, disabled: !r.disabled },
    })
      .then(() => load())
      .catch(() => {})
      .finally(() => setBusyId(null));
  };

  const load = useCallback(() => {
    setState("loading");
    flaskFetch<OffersData>("/api/v1/saas/offers")
      .then((d) => {
        setData(d);
        setState(d.offers.length ? "data" : "empty");
      })
      .catch((e: unknown) => {
        setNoTenant(isNoTenant(e));
        setState("error");
      });
  }, []);

  useEffect(load, [load]);


  const editing = editId ? data?.offers.find((o) => o.offer_id === editId) : null;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title={t("saas.offers.title")}
        lead={t("saas.offers.lead", { pct: data?.control_pct ?? 10 })}
        right={
          !creating ? (
            <Button variant="brand" size="sm" onClick={() => setCreating(true)}>
              {t("saas.offers.new.btn")}
            </Button>
          ) : undefined
        }
      />
      {creating && (
        <NewOfferForm
          onDone={(reload) => {
            setCreating(false);
            if (reload) load();
          }}
        />
      )}
      {editing && (
        <OfferEditor
          key={editing.offer_id + (editing.edited ? ":e" : ":b")}
          offer={editing}
          onDone={(reload) => {
            setEditId(null);
            if (reload) load();
          }}
        />
      )}
      {/* ОТКУДА ВЗЯТА СЕБЕСТОИМОСТЬ - один раз на экран, а не на каждой
          карточке: повторённое четыре раза предупреждение перестаёт читаться.
          Пока маржа не названа, все суммы ниже - оценка сверху. */}
      {(data?.cost_basis === "price" || data?.cost_basis === "assumed") &&
        (data?.offers ?? []).length > 0 && (
        <div className="rounded-ctl border border-[#fedf89] bg-[#fffcf5] px-3.5 py-2.5 text-[12.5px] leading-relaxed text-[#b54708]">
          {t(data.cost_basis === "assumed"
            ? "saas.offers.basis.assumed"
            : "saas.offers.basis.price")}
        </div>
      )}
      {noTenant ? (
        <NoTenant />
      ) : (
      <div className="flex flex-col gap-2.5">
        {(data?.offers ?? []).map((o) => (
          <OfferCard key={o.offer_id} o={o} onEdit={() => setEditId(o.offer_id)} />
        ))}
        {state === "data" && !(data?.offers ?? []).length && (
          <div className="rounded-card border border-hair bg-canvas p-6 text-center">
            <div className="text-[15px] font-semibold text-ink">{t("saas.offers.empty.title")}</div>
            <p className="mt-1 text-[13px] text-steel">{t("saas.offers.empty.desc")}</p>
          </div>
        )}
      </div>
      )}
    </div>
  );
}
