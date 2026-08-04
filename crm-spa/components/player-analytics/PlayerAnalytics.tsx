"use client";

import { Card, SkeletonText } from "@/components/ui";
import type { UserRole } from "@/lib/types";
import { useT } from "@/lib/i18n";
import { useSection } from "./hooks";
import { SectionH2 } from "./ui";
import { LtvSection } from "./LtvSection";
import { LadderSection } from "./LadderSection";
import { ProfileSection } from "./ProfileSection";
import { MoneySection } from "./MoneySection";
import { DepositsSection } from "./DepositsSection";
import { GameSection } from "./GameSection";
import { PatternSection } from "./PatternSection";
import { RhythmSection } from "./RhythmSection";
import { SessionsSection } from "./SessionsSection";
import { BonusSection } from "./BonusSection";
import { MaxBalanceSection } from "./MaxBalanceSection";
import { VipIntelSection } from "./VipIntelSection";
import { TrajectorySection } from "./TrajectorySection";
import type { PlayerSummary, LtvData } from "./types";

/**
 * PlayerAnalytics (C2) — the analytical half of the player card, section order
 * 1:1 with player_board.py def player() (lines 1569-1585):
 *   💎 LTV → 🪜 Прогресс по депозитам → 👤 Профиль → 💰 Деньги → 💳 Депозиты[coll]
 *   → 🎮 Игра → 🧭 Паттерн → 🕐 Ритм → 🕐 Лог сессий[coll] → 🎁 Бонусы[coll]
 *   → 🗺 Траектория[coll].
 *
 * Data: LTV/ladder share ONE /ltv fetch; profile/money/game come from the shared
 * /summary slice; pattern/rhythm/sessions/trajectory each fetch independently
 * (parallel, isolated states — one failure never blocks the rest). Casino-money
 * sections (LTV, ladder, Деньги, Депозиты, Бонусы) are hidden for
 * operator/support/affiliate; the backend also omits money/game for them.
 */
const CASINO_MONEY_HIDDEN: readonly UserRole[] = ["operator", "support", "affiliate"];
// ТЗ «Бонусы + макс-баланс» (new_u/ТЗ_карточка_игрока_бонусы_и_макс_баланс.md):
// бонусы видит и support (sorry-бонусы, контроль злоупотреблений); операторам-звонарям
// блок скрыт до решения по ролям. Макс-баланс — инструмент разговора с игроком
// (саппорт/КЦ/VIP): скрыт только у affiliate; оператору backend отдаёт лишь своих.
const BONUS_HIDDEN: readonly UserRole[] = ["operator", "affiliate"];
const MAXBAL_HIDDEN: readonly UserRole[] = ["affiliate"];

function SummarySkeleton({ title }: { title: string }) {
  return (
    <section className="mt-6">
      <SectionH2>{title}</SectionH2>
      <Card>
        <SkeletonText lines={4} />
      </Card>
    </section>
  );
}

export function PlayerAnalytics({ playerId, role }: { playerId: number; role: UserRole }) {
  const t = useT();
  const showCasinoMoney = !CASINO_MONEY_HIDDEN.includes(role);
  const showBonuses = !BONUS_HIDDEN.includes(role);
  const showMaxbal = !MAXBAL_HIDDEN.includes(role);

  const summary = useSection<PlayerSummary>(`/api/v1/players/${playerId}/summary`);
  const ltv = useSection<LtvData>(`/api/v1/players/${playerId}/ltv`, showCasinoMoney);

  const loadingSummary = summary.state === "loading";
  const s = summary.data;

  return (
    <div className="flex flex-col" data-analytics-root>
      {/* 0 · Макс-баланс за период — над LTV (запрос владельца) */}
      {showMaxbal ? <MaxBalanceSection playerId={playerId} /> : null}

      {/* 1 · LTV-прогноз + 2 · Прогресс по депозитам (share the /ltv fetch) */}
      {showCasinoMoney ? (
        <>
          <LtvSection section={ltv} />
          <LadderSection section={ltv} />
        </>
      ) : null}

      {/* 2b · VIP-скоры (инхаус vip-intelligence) */}
      {showCasinoMoney ? <VipIntelSection playerId={playerId} /> : null}

      {/* 3 · Профиль */}
      {loadingSummary ? (
        <SummarySkeleton title={t("analytics.section.profile")} />
      ) : s?.profile ? (
        <ProfileSection summary={s} />
      ) : null}

      {/* 4 · Деньги */}
      {showCasinoMoney
        ? loadingSummary
          ? <SummarySkeleton title={t("analytics.section.money")} />
          : s?.money
            ? <MoneySection money={s.money} />
            : null
        : null}

      {/* 5 · Депозиты (сворачиваемая, закрыта) */}
      {showCasinoMoney ? <DepositsSection playerId={playerId} /> : null}

      {/* 6 · Игра */}
      {loadingSummary ? (
        <SummarySkeleton title={t("analytics.section.game")} />
      ) : s?.game ? (
        <GameSection game={s.game} />
      ) : null}

      {/* 7 · Паттерн */}
      <PatternSection playerId={playerId} />

      {/* 8 · Ритм ставок */}
      <RhythmSection playerId={playerId} />

      {/* 9 · Лог сессий (сворачиваемая) */}
      <SessionsSection playerId={playerId} />

      {/* 10 · Бонусы: сводка по статусам + таблица с фильтрами (сворачиваемая) */}
      {showBonuses ? <BonusSection playerId={playerId} /> : null}

      {/* 11 · Траектория игр (сворачиваемая) */}
      <TrajectorySection playerId={playerId} />
    </div>
  );
}
