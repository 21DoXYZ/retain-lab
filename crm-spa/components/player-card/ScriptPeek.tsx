"use client";

import { useState } from "react";
import { Badge, Button, Modal, SkeletonText } from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";

/**
 * «Скрипт» рядом с кнопкой звонка: оператор видит активную версию, НЕ уходя из
 * карточки игрока (спека §10.9 даёт отдельный экран, но во время звонка скрипт
 * нужен перед глазами — здесь он в один клик).
 *
 * Read-only, язык — оригинал TR (оператор на нём работает); пометки уровней те
 * же, что на полном экране (zorunlu söz / adım / serbest). Данные — тот же
 * GET /script, роли operator/vip_manager там уже пропущены (§10.9).
 */
interface PeekBlock {
  title?: string | null;
  text?: string | null;
  check_level?: "verbatim" | "meaning" | "none" | null;
}

interface PeekData {
  active: { version: number | null; blocks: PeekBlock[] } | null;
}

function LevelBadge({ level }: { level: PeekBlock["check_level"] }) {
  const t = useT();
  if (level === "verbatim") return <Badge bg="#fef3c7" fg="#92400e">{t("callsboard.script.mark.zorunlu")}</Badge>;
  if (level === "none") return <Badge bg="#f2f4f7" fg="#344054">{t("callsboard.script.mark.serbest")}</Badge>;
  return <Badge bg="#dde9ff" fg="#1e40af">{t("callsboard.script.mark.adim")}</Badge>;
}

export function ScriptPeek() {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<PeekData | null>(null);
  const [err, setErr] = useState<string | null>(null);

  function show() {
    setOpen(true);
    if (data) return;                      // активная версия за сессию не меняется
    flaskFetch<PeekData>("/api/v1/call-analysis/script")
      .then(setData)
      .catch((e) => setErr(flaskErrorText(e, t, "card.common.error")));
  }

  const blocks = data?.active?.blocks ?? [];

  return (
    <>
      <Button size="sm" variant="ghost" onClick={show}>
        {t("card.call.scriptButton")}
      </Button>

      <Modal
        open={open}
        onClose={() => setOpen(false)}
        widthClass="max-w-xl"
        title={
          <span className="flex items-baseline gap-2">
            {t("callsboard.script.ro.title")}
            {data?.active?.version != null ? (
              <span className="text-[12px] font-normal text-steel">
                {t("callsboard.script.ro.version", { version: data.active.version })}
              </span>
            ) : null}
          </span>
        }
      >
        {err ? (
          <p className="text-[13px] text-neg">{err}</p>
        ) : !data ? (
          <SkeletonText lines={6} />
        ) : blocks.length === 0 ? (
          <p className="text-[13.5px] text-steel">{t("callsboard.script.ro.empty")}</p>
        ) : (
          <div className="space-y-3">
            {blocks.map((b, i) => (
              <div key={i} className="rounded-ctl border border-hair bg-canvas px-3.5 py-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[13px] font-semibold text-ink">
                    {i + 1}{b.title ? ` · ${b.title}` : ""}
                  </div>
                  <LevelBadge level={b.check_level} />
                </div>
                {b.text ? (
                  <p className="mt-1.5 text-[13.5px] leading-relaxed text-slate">{b.text}</p>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </Modal>
    </>
  );
}
