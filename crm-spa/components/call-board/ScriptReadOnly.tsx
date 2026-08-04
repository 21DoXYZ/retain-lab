"use client";

import { PageHeader, Card, EmptyState, Badge } from "@/components/ui";
import { useT } from "@/lib/i18n";
import type { ScriptVersion, ScriptBlock, CheckLevel } from "./types";

/**
 * Скрипт — просмотр оператору (§10.9). Активная версия, только чтение, на TR, с
 * пометками zorunlu söz / adım / serbest. «Нельзя судить человека по линейке,
 * которую он не может прочитать.» Роли: operator, vip_manager.
 */
export function ScriptReadOnly({ active }: { active: ScriptVersion | null }) {
  const t = useT();

  const version = active?.version;
  const blocks = active?.blocks ?? [];

  return (
    <>
      <PageHeader
        title={t("callsboard.script.ro.title")}
        accent={version != null ? t("callsboard.script.ro.version", { version }) : undefined}
      />

      {blocks.length === 0 ? (
        <div className="mt-8">
          <EmptyState title={t("callsboard.script.ro.empty")} />
        </div>
      ) : (
        <div className="mt-6 space-y-3">
          {blocks.map((b, i) => (
            <BlockView key={i} index={i} block={b} />
          ))}
        </div>
      )}
    </>
  );
}

function BlockView({ index, block }: { index: number; block: ScriptBlock }) {
  const t = useT();
  const level = (block.check_level ?? "meaning") as CheckLevel;

  return (
    <Card>
      <div className="flex items-center justify-between gap-2">
        <div className="text-[14px] font-semibold text-ink">
          {index + 1}
          {block.title ? <span className="ml-2 font-normal text-steel">· {block.title}</span> : null}
        </div>
        <MarkBadge level={level} />
      </div>
      {block.text ? (
        <blockquote className="mt-2 rounded-ctl bg-surface px-3.5 py-2 font-mono text-[13.5px] leading-relaxed text-slate">
          «{block.text}»
        </blockquote>
      ) : null}
      {level === "verbatim" ? <p className="mt-2 text-[12.5px] text-steel">ⓘ {t("callsboard.script.ro.mustSay")}</p> : null}
      {level === "none" ? <p className="mt-2 text-[12.5px] text-steel">ⓘ {t("callsboard.script.ro.ownWords")}</p> : null}
    </Card>
  );
}

function MarkBadge({ level }: { level: CheckLevel }) {
  const t = useT();
  if (level === "verbatim") return <Badge bg="#fef3c7" fg="#92400e">{t("callsboard.script.mark.zorunlu")}</Badge>;
  if (level === "none") return <Badge bg="#e5e7eb" fg="#475569">{t("callsboard.script.mark.serbest")}</Badge>;
  return <Badge bg="#eff6ff" fg="#1e40af">{t("callsboard.script.mark.adim")}</Badge>;
}
