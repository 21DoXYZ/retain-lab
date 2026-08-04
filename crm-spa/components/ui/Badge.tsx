"use client";

import type { CSSProperties, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { useT, type MessageKey } from "@/lib/i18n";
import {
  ACCOUNT_TYPE,
  ACCOUNT_TYPE_FALLBACK,
  ACTION,
  ACTION_FALLBACK,
  LIFECYCLE,
  LIFECYCLE_FALLBACK,
  TIER,
  TIER_FALLBACK,
  VIP_TONE,
} from "./badges";

/**
 * Badge — pill label, board .badge (11px, weight 600, radius 999px, 3/10 pad).
 * Colours come in as bg/fg (inline) to stay data-driven like the dashboard.
 * Semantic `tone` covers pos/neg text-only badges (board .badge.pos/.neg).
 */
type SemanticTone = "pos" | "neg" | "neutral";

interface BadgeProps {
  children: ReactNode;
  bg?: string;
  fg?: string;
  tone?: SemanticTone;
  title?: string;
  className?: string;
}

const TONE_STYLE: Record<SemanticTone, CSSProperties> = {
  pos: { color: "#1f9d57" },
  neg: { color: "#dc2626" },
  neutral: {},
};

export function Badge({ children, bg, fg, tone, title, className }: BadgeProps) {
  const style: CSSProperties = tone
    ? TONE_STYLE[tone]
    : { background: bg, color: fg };
  return (
    <span
      title={title}
      className={cn(
        "inline-block text-[11px] font-semibold rounded-full px-2.5 py-[3px] align-middle whitespace-nowrap",
        className,
      )}
      style={style}
    >
      {children}
    </span>
  );
}

/** Lifecycle stage badge (board life_badge). */
export function LifecycleBadge({ stage }: { stage: string | null | undefined }) {
  const t = useT();
  const tone = stage ? LIFECYCLE[stage] : undefined;
  if (tone) {
    // Подсказка с реальным порогом в днях (ТЗ по копирайту, задача 6.3): по
    // бейджу «остывает» непонятно, почему игрок туда попал — при наведении
    // видно правило («последняя ставка 8–30 дней назад»).
    const tipKey = `ui.badge.lifecycleTip.${stage === "at_risk" ? "atRisk" : stage}` as MessageKey;
    return (
      <Badge bg={tone.bg} fg={tone.fg} title={t(tipKey)}>
        {t(tone.labelKey)}
      </Badge>
    );
  }
  // Unmapped stage: show the raw (backend) value or the dash placeholder —
  // neither is translatable copy.
  return (
    <Badge bg={LIFECYCLE_FALLBACK.bg} fg={LIFECYCLE_FALLBACK.fg}>
      {stage || LIFECYCLE_FALLBACK.label}
    </Badge>
  );
}

/** Account-type badge; renders nothing for normal accounts (board at_badge). */
export function AccountTypeBadge({ type }: { type: string | null | undefined }) {
  const t = useT();
  if (!type || type === "normal") return null;
  const tone = ACCOUNT_TYPE[type];
  if (tone) {
    return (
      <Badge bg={tone.bg} fg={tone.fg}>
        {t(tone.labelKey)}
      </Badge>
    );
  }
  return (
    <Badge bg={ACCOUNT_TYPE_FALLBACK.bg} fg={ACCOUNT_TYPE_FALLBACK.fg}>
      {type}
    </Badge>
  );
}

/**
 * Next-best-action badge (board act_badge).
 *
 * API отдаёт «КОД · пояснение по-русски» ("NURTURE · растить"). Берём КОД
 * (первое слово) и печатаем ЛОКАЛИЗОВАННУЮ подпись — иначе турецкий оператор
 * читал бы русское пояснение из витрины. Незнакомый код → сырое значение API.
 */
export function ActionBadge({ action }: { action: string | null | undefined }) {
  const t = useT();
  const key = String(action ?? "").split(" ")[0];
  const c = ACTION[key] ?? ACTION_FALLBACK;
  const label = "labelKey" in c ? t(c.labelKey) : (action ?? "—");
  return (
    <Badge bg={c.bg} fg={c.fg}>
      {label}
    </Badge>
  );
}

/** LTV early-tier badge (board tier_badge). */
export function TierBadge({ tier }: { tier: string | null | undefined }) {
  const t = useT();
  const tone = tier ? TIER[tier] : undefined;
  if (tone) {
    return (
      <Badge bg={tone.bg} fg={tone.fg}>
        {t(tone.labelKey)}
      </Badge>
    );
  }
  return (
    <Badge bg={TIER_FALLBACK.bg} fg={TIER_FALLBACK.fg}>
      {tier || "—"}
    </Badge>
  );
}

/** VIP-level badge (board VIPLBL). Level clamped to 0–5. */
export function VipBadge({ level }: { level: number | null | undefined }) {
  const lvl = Math.max(0, Math.min(5, Math.round(Number(level ?? 0))));
  const tone = VIP_TONE[lvl];
  return (
    <Badge bg={tone.bg} fg={tone.fg}>
      {tone.label}
    </Badge>
  );
}

/** 🎯 "beats the casino" marker (board wm/🎯 span). */
export function BeatsCasinoBadge({ title }: { title?: string }) {
  const t = useT();
  return (
    <span
      title={title ?? t("ui.badge.beatsCasino.tooltip")}
      className="cursor-help align-middle"
      aria-label={t("ui.badge.beatsCasino.ariaLabel")}
    >
      🎯
    </span>
  );
}
