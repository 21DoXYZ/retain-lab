"use client";

import { useState } from "react";
import { Textarea, Input, Button } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { MessageKey } from "@/lib/i18n";
import { saveOffer, cardErrorText } from "./data";
import type { OfferStatusCode, PlayerSummary } from "./types";

/**
 * «✍️ Оффер игроку» — 1:1 с бордом (player_board.py offer_form): рекомендованный
 * оффер (правится), заметка оператора и 4 действия (Утвердить / Сохранить правку /
 * Отправить / Отклонить).
 *
 * Решение уходит в retention.player_offers — ТУДА ЖЕ, куда пишет старый борд
 * (POST /offer/<pid>), через POST /api/v1/players/<pid>/offer. Один источник на
 * оба интерфейса: бейдж статуса на /desk и в HTML-карточке видит решение из SPA.
 * Для ролей без права правки (аналитик) — только просмотр оффера и статуса.
 */
interface OfferBlockProps {
  playerId: number;
  canWrite: boolean;
  summary: PlayerSummary | null;
  onChanged: () => void;
}

/** Кнопка → код статуса в player_offers (борд: status из формы). */
const BUTTON_STATUS = {
  approve: "approved",
  edit: "edited",
  send: "sent",
  decline: "rejected",
} as const satisfies Record<string, OfferStatusCode>;

type ButtonKind = keyof typeof BUTTON_STATUS;

/** Подписи статусов переиспользуем из монитора — те же коды, тот же смысл. */
const STATUS_KEY: Record<OfferStatusCode, MessageKey> = {
  approved: "monitor.offerStatus.approved",
  edited: "monitor.offerStatus.edited",
  rejected: "monitor.offerStatus.rejected",
  sent: "monitor.offerStatus.sent",
};

/** Цвета бейджа — из player_board.OFFER_STATUS (bg, fg), чтобы совпадало с бордом. */
const STATUS_TONE: Record<OfferStatusCode, { bg: string; fg: string }> = {
  approved: { bg: "#dcfce7", fg: "#166534" },
  edited: { bg: "#dde9ff", fg: "#1e40af" },
  rejected: { bg: "#fee2e2", fg: "#991b1b" },
  sent: { bg: "#fef9c3", fg: "#854d0e" },
};

export function OfferBlock({ playerId, canWrite, summary, onChanged }: OfferBlockProps) {
  const t = useT();
  const rec = summary?.recommendation;

  // Борд: cur_offer = ot_ if os_ else suggested — сохранённое решение отдела
  // приоритетнее подобранного системой оффера.
  const suggested = (rec?.offer_name && rec.offer_name !== "—" ? rec.offer_name : rec?.bonus) ?? "";
  const initialOffer = rec?.offer_saved_text || suggested;
  const savedStatus = rec?.offer_status ?? null;

  const savedAt = rec?.offer_saved_at ?? null;
  // решение отдела «заморожено», а движок с тех пор мог передумать — подсветим
  const stale = Boolean(
    rec?.offer_saved_text && suggested &&
    rec.offer_saved_text.trim() !== suggested.trim(),
  );

  const [offer, setOffer] = useState(initialOffer);
  const [touched, setTouched] = useState(false);
  // summary грузится асинхронно: пока оператор не трогал поле — показываем
  // серверное значение деривацией (без setState-в-эффекте)
  const shownOffer = touched ? offer : initialOffer;
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  if (!rec || (!initialOffer && !rec.action)) return null;

  async function act(kind: ButtonKind) {
    setBusy(true);
    setMsg(null);
    const status = BUTTON_STATUS[kind];
    try {
      await saveOffer({ playerId, status, offerText: shownOffer, note: note.trim() });
      setNote("");
      setTouched(false); // решение записано → показываем то, что вернёт бэкенд
      setMsg(t("card.offer.savedSuffix", { label: t(STATUS_KEY[status]) }));
      onChanged();
    } catch (e) {
      setMsg(cardErrorText(e, t, "card.common.error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <h2 className="font-bold text-[20px] leading-tight text-ink flex items-baseline gap-2 flex-wrap">
        {t("card.offer.title")}
        <span className="text-[13px] text-steel font-normal">{t("card.offer.subtitle")}</span>
        {savedStatus ? (
          <span
            className="text-[11px] font-semibold rounded-full px-2 py-[2px]"
            style={{ background: STATUS_TONE[savedStatus].bg, color: STATUS_TONE[savedStatus].fg }}
          >
            {t(STATUS_KEY[savedStatus])}
            {savedAt ? ` · ${savedAt}` : ""}
          </span>
        ) : null}
      </h2>
      {/* что это за блок: журнал РЕШЕНИЯ отдела, а не живая подсказка системы */}
      <p className="-mt-1 text-[12px] text-stone max-w-[560px]">{t("card.offer.hint")}</p>

      <div className="max-w-[560px]">
        <Textarea
          value={shownOffer}
          onChange={(e) => {
            setTouched(true);
            setOffer(e.target.value);
          }}
          disabled={!canWrite}
          rows={2}
        />
        {rec.offer_terms ? <div className="mt-1 text-[12px] text-steel">{rec.offer_terms}</div> : null}
        {rec.offer_saved_note ? (
          <div className="mt-1 text-[12px] text-steel">{rec.offer_saved_note}</div>
        ) : null}

        {/* решение устарело: движок сейчас рекомендует другое */}
        {stale ? (
          <div className="mt-2 rounded-[8px] border border-[#fde68a] bg-[#fffbeb] px-3 py-2 text-[12.5px] text-[#854d0e]">
            {t("card.offer.staleNotice", { name: suggested })}
            {canWrite ? (
              <button
                type="button"
                className="ml-2 underline decoration-dotted hover:text-ink cursor-pointer"
                onClick={() => {
                  setTouched(true);
                  setOffer(suggested);
                }}
              >
                {t("card.offer.useCurrent")}
              </button>
            ) : null}
          </div>
        ) : null}

        {canWrite ? (
          <>
            <div className="mt-2">
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t("card.offer.notePlaceholder")}
              />
            </div>
            <div className="mt-2 flex gap-2 flex-wrap">
              <Button variant="brand" size="sm" onClick={() => act("approve")} loading={busy}>
                {t("card.offer.approveButton")}
              </Button>
              <Button variant="primary" size="sm" onClick={() => act("edit")} disabled={busy}>
                {t("card.offer.editButton")}
              </Button>
              <Button variant="primary" size="sm" onClick={() => act("send")} disabled={busy}>
                {t("card.offer.sendButton")}
              </Button>
              <Button variant="ghost" size="sm" onClick={() => act("decline")} disabled={busy}>
                {t("card.offer.declineButton")}
              </Button>
            </div>
            {msg ? <div className="mt-2 text-[12.5px] text-steel">{msg}</div> : null}
          </>
        ) : null}
      </div>
    </div>
  );
}
