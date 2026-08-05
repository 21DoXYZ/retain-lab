/**
 * en · домен «card». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const card: Partial<Messages> = {
  // CardHeader.tsx
  "card.header.playerLabel": "User",
  "card.header.noDeposit": "· no payment",
  "card.header.alsoWith": "also with:",
  "card.header.backToList": "← back to list",
  "card.header.kpi.bets": "Usage",
  "card.header.kpi.turnover": "Turnover ₺",
  "card.header.kpi.net": "Net ₺",
  "card.header.kpi.ggr": "MRR ₺",
  "card.header.kpi.deposits": "Payments",
  "card.header.kpi.recency": "Recency",
  "card.header.daysShort": "{n}d",

  // CallBlock.tsx
  "card.call.title": "Call",
  "card.call.phoneLabel": "Phone:",
  "card.call.phoneHiddenHint": "(hidden - call button only)",
  "card.call.phoneUnavailable": "Phone not available for your role",
  "card.call.callButton": "📞 Call",
  "card.call.todayHintLead": "Today at {time}, called by",
  "card.call.todayHintTrail":
    " -  {outcome}. To avoid a duplicate touch, check with them before calling.",
  "card.call.journalTitle": "Call journal",
  "card.call.emptyTitle": "No calls yet",
  "card.call.emptyDescription": "Click \"Call\" to reach the user.",
  "card.call.confirmTitle": "Already called today",
  "card.call.confirmAnyway": "Call anyway",
  "card.call.confirmLead": "This user was already contacted today by",
  "card.call.confirmTrail": "({outcome}). Call again?",
  "card.call.confirmFallback": "This user was already contacted today. Call again?",
  "card.call.originateError": "Failed to initiate the call.",
  "card.call.saveError": "Failed to save.",

  // access.ts - CallOutcome labels
  "card.outcome.answered": "Answered",
  "card.outcome.noAnswer": "No answer",
  "card.outcome.busy": "Busy",
  "card.outcome.wrongNumber": "Wrong number",

  // access.ts - CallResult labels
  "card.result.interested": "Interested",
  "card.result.offerDeclined": "Offer declined",
  "card.result.callbackRequested": "Asked to call back",
  "card.result.refused": "Refused",

  // OutcomeModal.tsx
  "card.outcomeModal.title": "Call outcome",
  "card.outcomeModal.dialedNumber": "Dialed number:",
  "card.outcomeModal.step1": "1. How did the call go",
  "card.outcomeModal.step2": "2. Conversation result",
  "card.outcomeModal.noAnswerNote": "The user stays in the queue - we'll suggest scheduling the next call.",
  "card.outcomeModal.genericNote": "The outcome will be recorded in the journal.",

  // NotesBlock.tsx
  "card.notes.title": "📝 Notes",
  "card.notes.hint": "user history - with author names",
  "card.notes.placeholder": "What was discussed, agreements, reaction to the offer…",
  "card.notes.addButton": "Add note",
  "card.notes.emptyTitle": "No notes yet",
  "card.notes.emptyDescription": "Add the first note above.",
  "card.notes.editedSuffix": " · edited",
  "card.notes.editButton": "Edit",
  "card.notes.deleteButton": "Delete",
  "card.notes.linkedOfferPrefix": "→ offer:",
  "card.notes.tagLinkedOfferPrefix": "linked to offer:",
  "card.notes.noActiveOffer": "no active offer - tag not linked",
  "card.notes.emptyContent": "Enter the note text.",
  "card.notes.editWindowExpired": "The edit window (15 minutes) has expired.",

  // access.ts - NoteTag labels (chips)
  "card.tag.offerDeclined": "Offer declined",
  "card.tag.otherOffer": "Offered something else",
  "card.tag.callback": "Asked to call back",
  "card.tag.negative": "Negative",
  "card.tag.returned": "Returned",

  // OfferBlock.tsx
  "card.offer.title": "✍️ Offer to user",
  "card.offer.hint": "This is the decision log: the text and status are saved and never overwritten by the system. The live suggestion is above, in “Recommended action”.",
  "card.offer.staleNotice": "⚠ The system now recommends something else: “{name}”",
  "card.offer.useCurrent": "use the current one",
  "card.offer.subtitle": "the department’s decision - what was actually approved/sent",
  "card.offer.notePlaceholder": "operator note (optional)",
  "card.offer.approveButton": "✅ Approve",
  "card.offer.editButton": "✏️ Save edit",
  "card.offer.sendButton": "📨 Send",
  "card.offer.declineButton": "❌ Decline",
  "card.offer.savedSuffix": "{label} · decision saved",

  // RecommendationStrip.tsx
  "card.recommendation.title": "🎯 Recommended action",
  "card.recommendation.subtitle": "offer engine · recalculated on every open - what the system suggests NOW",
  "card.recommendation.action": "Action",
  "card.recommendation.bonus": "Recommended offer",
  "card.recommendation.when": "When",
  "card.recommendation.churnRisk": "Churn risk (30d)",
  "card.recommendation.secondDepositProb": "P(2nd payment, 30d)",
  "card.recommendation.priorityNote":
    "priority = value × churn risk · delivery channel - no data",

  // ctx-momentum banner (board ctx, player_board.py:1435-1438; ±avg_bet*20 dead zone).
  "card.momentum.liveLabel": "⚡ what is happening with the user now - recent sessions momentum",
  "card.momentum.contextTitle": "🎯 Usage context",
  "card.momentum.down":
    "🔻 On a downswing (usage dropping / negative recent trend) → a cashback / bonus-token offer fits now, before frustration sets in.",
  "card.momentum.up":
    "🔺 On an upswing (usage growing) → nudge toward a payment riding the momentum, or bonus tokens in the favourite game.",
  "card.momentum.flat": "➖ Steady dynamics - proceed with the main offer.",

  // RecordingPlayer.tsx
  "card.recording.unavailable": "Recording not available.",
  "card.recording.playButton": "▶ Listen",

  // ScheduleBlock.tsx
  "card.schedule.status.planned": "planned",
  "card.schedule.status.done": "done",
  "card.schedule.status.overdue": "overdue",
  "card.schedule.status.missed": "missed",
  "card.schedule.title": "Schedule next call",
  "card.schedule.nudgeHint": "The user didn't answer and stays in the queue - schedule the next touch.",
  "card.schedule.suggestionPrefix": "Usually active:",
  "card.schedule.applySuggestion": "Use this slot",
  "card.schedule.autoComment": "Auto-slot based on user activity",
  "card.schedule.missingDateTime": "Specify a date and time.",
  "card.schedule.dateTimeAriaLabel": "Date and time",
  "card.schedule.commentPlaceholder": "Comment (e.g. \"good on Friday evening\")",
  "card.schedule.submitButton": "Schedule",
  "card.schedule.upcomingTitle": "Upcoming touches",
  "card.schedule.emptyTitle": "No scheduled calls",
  "card.schedule.bySystem": "suggested by the system",
  "card.schedule.suggestionAround": "{day}, around {hour}:00",

  // Shared across player-card blocks (author name / generic errors)
  "card.common.you": "You",
  "card.common.operatorFallback": "Operator …{id}",
  "card.common.error": "Error.",
  "card.common.loadError": "Failed to load data.",

  // data.ts - CardDataError copy
  "card.error.rlsDenied":
    "Insufficient permissions: this user is not in your zone (not assigned to you). The action was rejected by the access policy.",
  "card.error.operationalLoadFailed": "Failed to load operational data.",
  "card.error.noteSaveFailed": "Failed to save the note.",
  "card.error.noteEditFailed": "Failed to edit the note.",
  "card.error.noteDeleteFailed": "Failed to delete the note.",
  "card.error.callOutcomeSaveFailed": "Failed to save the call outcome.",
  "card.error.scheduleSaveFailed": "Failed to schedule the call.",
  "card.error.recordingNotFound": "This call has no recording.",
  "card.error.recordingUnavailable": "Recording unavailable ({status}).",

  // ── KPI-tile tooltips (board SCARD_TIP, player_board.py:1305-1320) ─────────
  "card.tip.scard.bets": "Number of usage events (incl. bonus tokens).",
  "card.tip.scard.turnover": "Turnover = Σ of usage amounts.",
  "card.tip.scard.net": "User net = rewards − usage. − = net spend (user's view).",
  "card.tip.scard.ggr": "MRR = usage − rewards = −net. Revenue from usage (before offers).",
  "card.tip.scard.deposits": "Number of completed payments.",
  "card.tip.scard.recency": "Days since the last activity.",
  "card.tip.scard.tier": "Tier by first-week payments: A<1k · B<3k · C<10k · D≥10k.",
  "card.tip.scard.depWeek1": "Σ of payments in the first 7 days from the first payment (LTV-model feature).",
  "card.tip.scard.forecastD90": "ML forecast of payment total by day 90 from first-week behaviour.",
  "card.tip.scard.rangeD90": "Quantile forecast: P10-P90 - the honest spread (whales).",
  "card.tip.scard.headroom": "Headroom = max(0, D90 forecast − already paid). 0 = forecast already exceeded.",
  "card.tip.scard.current": "Current step = number of the last payment.",
  "card.tip.scard.pNextPersonal": "Personal P(next payment within 30 days), ML (any step).",
  "card.tip.scard.pNextBase": "Average conversion of this step across the whole base. Computed only up to #10 (then « - »).",
  "card.tip.scard.target": "Next step = payment #(N+1).",

  // ── Field .fld tooltips (board CARD_TIP, player_board.py:1254-1303) ────────
  "card.tip.field.vip_level":
    "User tier (workspace rules) by cumulative successful payments in TRY: Regular <100, Silver ≥100, Gold ≥50k, Platinum ≥150k, Diamond ≥500k, Royal ≥1M. For ≥ Silver at least one payment ≥ 100 TRY is required.",
  "card.tip.field.account_type":
    "Account type. normal = real user; test_or_service / service / blocked - not real (excluded from models).",
  "card.tip.field.status": "Account status from the source.",
  "card.tip.field.country": "Country (estimated from country_iso_estimated).",
  "card.tip.field.reg_date": "Registration date.",
  "card.tip.field.tenure_days": "Account age = days since registration.",
  "card.tip.field.affiliate_type": "Affiliate-account type (classic, etc.).",
  "card.tip.field.ftd_amount": "First payment amount.",
  "card.tip.field.balance": "Token balance - snapshot at export time (not live).",
  "card.tip.field.bonus_balance": "Bonus token balance - snapshot at export time.",
  "card.tip.field.activity_status": "Activity status from the source.",
  "card.tip.field.dep_count": "Number of completed payments (incl. manual credits, status=completed).",
  "card.tip.field.dep_sum":
    "Payments INCL. manual (manual=offer credit) - a behavioural field for models. Real cash → «paid (cash)».",
  "card.tip.field.cash_deposits":
    "Cash payments: Σ over successful payments. WITHOUT manual credits. Reconcilable with the board.",
  "card.tip.field.withdrawals_abs":
    "Refunds: Σ ABS(amount) over successful refunds. WITHOUT manual refunds.",
  "card.tip.field.net_cash": "Net cash = cash payments − refunds.",
  "card.tip.field.bonus_cost":
    "Offer cost = Σ ABS(amount) over offers and bonus tokens (successful, without conversions).",
  "card.tip.field.dep_failed": "Number of failed payments (rejected / failed).",
  "card.tip.field.wd_count": "Number of completed refunds.",
  "card.tip.field.wd_sum": "Sum of completed refunds = Σ amount.",
  "card.tip.field.wd_rejected": "Number of rejected refunds.",
  "card.tip.field.bonus_count": "Number of offer grants.",
  "card.tip.field.bonus_sum": "Sum of granted offers.",
  "card.tip.field.primary_payment_method": "Primary payment method (without campaign tags).",
  "card.tip.field.deposit_recency_days": "Days since the last payment.",
  "card.tip.field.bets": "Number of usage events (incl. bonus tokens).",
  "card.tip.field.turnover": "Turnover = Σ usage amounts. Total usage volume for the user.",
  "card.tip.field.wins_sum": "Rewards = Σ reward amounts. How much the user received in rewards.",
  "card.tip.field.net": "User net = rewards − usage. + up / − down (from the USER's side).",
  "card.tip.field.ggr": "MRR = usage − rewards = −net. Revenue from usage (before deducting offers).",
  "card.tip.field.avg_bet": "Average usage = avg(usage amount).",
  "card.tip.field.max_bet": "Maximum single usage.",
  "card.tip.field.distinct_games": "How many distinct games = uniqExact(game_uuid).",
  "card.tip.field.active_days": "Days with activity = uniqExact(activity date).",
  "card.tip.field.recency_days": "Days since the last activity = dateDiff(last activity, today).",
  "card.tip.field.primary_provider": "Primary provider (aggregator) by usage volume.",
  "card.tip.field.freespin_ratio": "Share of bonus-token usage = bonus usage / total usage.",
  "card.tip.field.night_share": "Share of night activity (hour < 6 Istanbul) = night usage / total usage.",
  "card.tip.field.bets_per_active_day": "Intensity = usage events / active days.",
  "card.tip.field.activation_lag_days": "Activation speed = days between registration and the first activity.",
  "card.tip.field.favourite_game": "Game with the most usage (the main one).",
  "card.tip.field.favourite_game_bets": "How much usage in the main game.",
  "card.tip.field.game_concentration": "Concentration = share of usage in the main game.",
  "card.tip.field.stuck_game": "The game the user took longest to return to.",
  "card.tip.field.stuck_game_days": "Days until the return to this game.",
  "card.tip.field.oneshot_games": "How many games abandoned after a single day.",

  // Скрипт перед глазами при звонке (ScriptPeek)
  "card.call.scriptButton": "📋 Script",

  // Рекомендация «когда звонить» (модуль анализа + retry-правило)
  "card.schedule.rec.retry": "Call back in {hours} h - no answer last time",
  "card.schedule.rec.bestTime": "Best time: {day} around {hour} (user’s peak activity)",
  "card.schedule.rec.apply": "Use",
  "card.call.viaButtonOnly": "call via button only (number hidden)",
  "card.handoff.button": "Assign WhatsApp",
  "card.handoff.title": "Hand off user",
  "card.handoff.hint": "Whom to hand the user to (WhatsApp manager or department head). They get the user in their queue.",
  "card.handoff.pick": " -  recipient - ",
  "card.handoff.cancel": "Cancel",
  "card.handoff.confirm": "Hand off",
  "card.handoff.done": "Handed off: {name}",
};
