/**
 * Данные модуля «Анализ звонков» (ядро). Всё идёт через flaskFetch к
 * api/call_analysis.py (JWT + X-Locale, конверт {ok,data} разворачивается сам).
 * Аудио — отдельным Bearer-fetch'ем в blob (плеер <audio> не носит заголовок),
 * образец — components/player-card/RecordingPlayer.tsx / players/download.ts.
 */
import { createClient } from "@/lib/supabase/client";
import { flaskFetch } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";

const API = "/api/v1/call-analysis";

// ── Очередь (§10.2, GET /queue) ──────────────────────────────────────────────
export interface QueueItem {
  call_id: string;
  operator_id: string | null;
  operator_name: string | null;
  player_id: number | string | null;
  status: string | null;
  flags: string[];
  duration_s: number | null;
  at: string | null;
  score: number | null;
  pass_fail: string | null;
  needs_human: boolean | null;
}

export interface QueueSeriesMember {
  call_id: string;
  duration_s: number | null;
  at: string | null;
}

export interface QueueSeries {
  kind: string;
  operator_id: string;
  operator_name: string | null;
  members: QueueSeriesMember[];
}

export interface DisputedCard {
  card_id: string;
  call_id: string;
  operator_id: string | null;
  operator_name?: string | null;
  reason: string | null;
  responded_at: string | null;
}

export interface QueueResponse {
  items: QueueItem[];
  series: QueueSeries[];
  disputed_cards: DisputedCard[];
}

export function fetchQueue(): Promise<QueueResponse> {
  return flaskFetch<QueueResponse>(`${API}/queue`);
}

// ── Карточка звонка (§10.3, GET /calls/<id>) ─────────────────────────────────
export interface Dimension {
  name: string;
  score: number | null;
  justification?: string | null;
  evidence_ts?: string[] | null;
  needs_human?: boolean | null;
}

export interface ComplianceCheck {
  key: string;
  present: boolean;
  evidence_ts?: string | null;
}

export interface AuditVersions {
  prompt?: number | string | null;
  rubric?: number | string | null;
  script?: number | string | null;
  model?: string | null;
}

export interface HumanReview {
  reviewed?: boolean | null;
  override_score?: number | null;
  reviewer_id?: string | null;
  notes?: string | null;
}

/** Возражение (§8): API отдаёт объект, НЕ строку. type — код для перевода. */
export interface Objection {
  type: string;
  reason?: string | null;
  handled?: boolean | null;
}

export interface CallAudit {
  score: number | null;
  pass_fail: string | null;
  needs_human: boolean | null;
  dimensions: Dimension[];
  objections?: Objection[] | null;
  compliance?: ComplianceCheck[] | null;
  offer_outcome?: string | null;
  versions: AuditVersions;
  coaching_narrative?: string | null;
  highlights?: unknown;
  improvement_areas?: unknown;
  human?: HumanReview | null;
}

export interface TranscriptWord {
  w: string;
  start: number;
  end: number;
  role: string; // "AGENT" | "PLAYER"
  conf?: number;
}

export interface Transcript {
  language: string | null;
  text: string | null;
  words: TranscriptWord[] | null;
  translation_verified?: boolean | null;
  translation?: { lang: string; text: string } | null;
}

export interface CallInfo {
  call_id: string;
  operator_id: string | null;
  player_id: number | string | null;
  status: string | null;
  duration_s: number | null;
  started_at: string | null;
  flags: string[];
  recommended_offer_id?: string | null;
}

export interface CallReviewRow {
  review_id: string;
  reviewer_id: string | null;
  reviewer_name?: string | null;
  kind: "confirm" | "override" | string;
  scores?: Record<string, number> | null;
  reason?: string | null;
  counted?: boolean | null;
  created_at: string | null;
}

/** Реакция игрока ПОСЛЕ звонка (минуты до события, окно 7 дней; null = не было). */
export interface CallReaction {
  deposit_min?: number | null;
  played_min?: number | null;
}

export interface CallCardResponse {
  call: CallInfo;
  audit: CallAudit | null;
  transcript: Transcript | null;
  verdict_unlocked: boolean;
  can_play_audio: boolean;
  offer_signal?: unknown;
  reviews?: CallReviewRow[];
  reaction?: CallReaction;
}

/** GET карточки. lang задаёт перевод транскрипта (?lang=ru|en, on-demand §10.3). */
export function fetchCall(callId: string, lang?: "ru" | "en"): Promise<CallCardResponse> {
  const q = lang ? `?lang=${lang}` : "";
  return flaskFetch<CallCardResponse>(`${API}/calls/${callId}${q}`);
}

// ── Подтверждение / правка (§7, §10.4) ───────────────────────────────────────
export interface ConfirmResult {
  call_id: string;
  review_id?: string;
  counted: boolean;
  min_review_time_s?: number;
  idempotent?: boolean;
}

/** POST /confirm — подтверждение оценки. review_time_s: секунды на разборе. */
export function confirmCall(callId: string, reviewTimeS: number): Promise<ConfirmResult> {
  return flaskFetch<ConfirmResult>(`${API}/calls/${callId}/confirm`, {
    method: "POST",
    body: { review_time_s: reviewTimeS },
  });
}

export interface OverrideResult {
  call_id: string;
  model_score: number | null;
  human_score: number | null;
  counted: boolean;
}

/** POST /override — правка по критериям (§10.4). Итог считает БЭК, не фронт. */
export function overrideCall(
  callId: string,
  scores: Record<string, number>,
  reason: string,
  reviewTimeS: number,
): Promise<OverrideResult> {
  return flaskFetch<OverrideResult>(`${API}/calls/${callId}/override`, {
    method: "POST",
    body: { scores, reason, review_time_s: reviewTimeS },
  });
}

// ── Аудио: Bearer-fetch в blob (§10.3) ───────────────────────────────────────
export class AudioFetchError extends Error {
  readonly key: MessageKey;
  constructor(key: MessageKey) {
    super(key);
    this.name = "AudioFetchError";
    this.key = key;
  }
}

/** Скачивает запись с токеном и отдаёт object URL для <audio src>. */
export async function fetchAudioUrl(callId: string): Promise<string> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  const base = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";
  const res = await fetch(`${base}${API}/calls/${callId}/audio`, {
    headers: session?.access_token ? { Authorization: `Bearer ${session.access_token}` } : undefined,
  });
  if (!res.ok) throw new AudioFetchError("calls.audio.unavailable");
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}
