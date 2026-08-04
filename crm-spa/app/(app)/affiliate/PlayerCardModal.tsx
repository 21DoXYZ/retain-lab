"use client";

import { useEffect, useState } from "react";
import { Modal, Badge, Button, ErrorState, Skeleton, VipBadge, LifecycleBadge } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT, useLocale } from "@/lib/i18n";
import { lifecycleSignal, type AffiliatePlayer, type AffiliateSummary } from "./types";

/**
 * Сокращённая карточка игрока для кабинета аффилиата (ТЗ п.6): показывает
 * ТОЛЬКО стадию, VIP, сигнал модели, рекомендованный оффер и маскированный
 * контакт для звонка. НИКАКИХ денег казино (GGR/NGR/комиссий) — они не входят
 * в тип AffiliateSummary. Звонок — только кнопкой (номер не раскрывается).
 */
interface PlayerCardModalProps {
  player: AffiliatePlayer | null;
  onClose: () => void;
}

export function PlayerCardModal({ player, onClose }: PlayerCardModalProps) {
  const t = useT();
  // Локаль в зависимостях: оффер из каталога приходит локализованным (X-Locale).
  const { locale } = useLocale();
  const [summary, setSummary] = useState<AffiliateSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [calling, setCalling] = useState(false);
  const [callMsg, setCallMsg] = useState<string | null>(null);

  const pid = player?.casino_player_id ?? null;

  useEffect(() => {
    if (pid === null) return;
    let cancelled = false;
    setLoading(true);
    setError(false);
    setSummary(null);
    setCallMsg(null);
    flaskFetch<AffiliateSummary>(`/api/v1/players/${pid}/summary`)
      .then((data) => {
        if (!cancelled) setSummary(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pid, locale]);

  const phone = summary?.contact?.phone ?? null;

  async function handleCall() {
    if (pid === null) return;
    setCalling(true);
    setCallMsg(null);
    try {
      await flaskFetch(`/api/v1/calls/originate`, {
        method: "POST",
        body: { casino_player_id: pid }, // flaskFetch сам делает JSON.stringify (lib/api.ts:52)
      });
      setCallMsg(t("affiliate.callStarted"));
    } catch (err) {
      setCallMsg(flaskErrorText(err, t, "affiliate.callFailed"));
    } finally {
      setCalling(false);
    }
  }

  const signal = lifecycleSignal(summary?.stage ?? player?.lifecycle ?? null);

  return (
    <Modal
      open={player !== null}
      onClose={onClose}
      title={
        <span className="flex items-center gap-2">
          {t("affiliate.col.player")} <span className="font-mono">{player?.display_id ?? pid}</span>
        </span>
      }
    >
      {loading ? (
        <div className="space-y-3">
          <Skeleton className="h-6 w-40" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-4 w-2/3" />
        </div>
      ) : error ? (
        <ErrorState title={t("affiliate.card.loadError")} />
      ) : (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <LifecycleBadge stage={summary?.stage ?? player?.lifecycle ?? null} />
            <VipBadge level={summary?.vip_level ?? player?.vip_level ?? null} />
            <Badge bg={signal.bg} fg={signal.fg}>{t(signal.key)}</Badge>
          </div>

          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-[var(--color-steel)]">{t("affiliate.card.churnRisk")}</dt>
              <dd className="font-mono">
                {summary?.scores?.p_churn != null
                  ? `${Math.round(summary.scores.p_churn * 100)}%`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-[var(--color-steel)]">{t("affiliate.card.recommendedAction")}</dt>
              <dd>{summary?.recommendation?.action ?? "—"}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-[var(--color-steel)]">{t("affiliate.card.offer")}</dt>
              <dd>{summary?.recommendation?.offer_name ?? "—"}</dd>
            </div>
            <div className="col-span-2">
              <dt className="text-[var(--color-steel)]">{t("affiliate.card.contact")}</dt>
              <dd className="font-mono">{phone ?? t("affiliate.card.noContact")}</dd>
            </div>
          </dl>

          <div className="flex items-center gap-3 border-t border-[var(--color-hair2)] pt-3">
            <Button onClick={handleCall} disabled={calling || !phone}>
              {calling ? t("affiliate.calling") : t("affiliate.call")}
            </Button>
            {callMsg && <span className="text-sm text-[var(--color-steel)]">{callMsg}</span>}
          </div>
        </div>
      )}
    </Modal>
  );
}
