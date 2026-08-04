import { createClient } from "./supabase/client";
import { DEFAULT_LOCALE, LOCALE_COOKIE, isLocale, type Locale } from "./i18n/config";
import type { MessageKey } from "./i18n";

/**
 * flaskFetch — THE single entry point for the whole SPA to reach the Flask JSON
 * analytics backend (player_board.py + api/* blueprints, NEXT_PUBLIC_FLASK_API_URL).
 * Every C-agent (money, players, cohorts, marketing, affiliates, monitor) should
 * call analytics through here — do not hand-roll fetch()/token logic per screen.
 *
 * What it does:
 *   1. Reads the current Supabase access token from the browser session.
 *   2. Calls `${NEXT_PUBLIC_FLASK_API_URL}${path}` with `Authorization: Bearer <token>`.
 *      (Flask A3 middleware verifies the Supabase JWT and filters by role.)
 *   3. Parses the `{ ok, data, error }` envelope and returns `data` (typed T).
 *   4. Throws a FlaskApiError with a human-readable message on any failure
 *      (network, non-2xx, `ok: false`) — so screens can show ErrorState.
 *
 * Usage (client component):
 *   import { flaskFetch } from "@/lib/api";
 *   const summary = await flaskFetch<PlayerSummary>(`/api/v1/players/${id}/summary`);
 *
 * For a POST / custom method:
 *   await flaskFetch("/api/v1/calls/originate", { method: "POST", body: { player_id } });
 *
 * Server components: use flaskFetchWithToken(path, token) with a token from
 * lib/auth.getAccessToken() — the browser client is not available server-side.
 */

const BASE_URL = process.env.NEXT_PUBLIC_FLASK_API_URL ?? "";

export interface FlaskFetchInit extends Omit<RequestInit, "body"> {
  /** JSON body — serialised automatically; sets Content-Type: application/json. */
  body?: unknown;
}

/**
 * Error thrown by flaskFetch — `status` is the HTTP code (0 for network errors).
 *
 * `message` is always the ru copy (source of truth / log text); `key` is set
 * whenever the copy is OUR OWN (not a backend `error` string, which isn't ours
 * to translate) so the caller can render `t(key, vars)`. Same contract as
 * CardDataError in components/player-card/data.ts — see flaskErrorText below.
 */
export class FlaskApiError extends Error {
  readonly status: number;
  readonly key?: MessageKey;
  readonly vars?: Record<string, string | number>;
  /** Машинный код ошибки бэкенда (envelope.error_code) — домен переводит сам. */
  readonly code?: string;
  /** Параметры к коду (envelope.error_params) — подстановки в перевод. */
  readonly codeVars?: Record<string, string | number>;
  constructor(
    message: string,
    status: number,
    key?: MessageKey,
    vars?: Record<string, string | number>,
    code?: string,
    codeVars?: Record<string, string | number>,
  ) {
    super(message);
    this.name = "FlaskApiError";
    this.status = status;
    this.key = key;
    this.vars = vars;
    this.code = code;
    this.codeVars = codeVars;
  }
}

/**
 * Resolve a caught error to display-ready, translated text. Takes `t` as a
 * parameter rather than calling useT() — this module is not a hook, so the
 * component passes it in at the catch site:
 *
 *   catch (e) { setError(flaskErrorText(e, t, "common.fetchError")); }
 */
export function flaskErrorText(
  e: unknown,
  t: (key: MessageKey, vars?: Record<string, string | number>) => string,
  fallbackKey: MessageKey,
): string {
  if (e instanceof FlaskApiError) return e.key ? t(e.key, e.vars) : e.message;
  if (e instanceof Error) return e.message;
  return t(fallbackKey);
}

/**
 * Current UI locale from the `crm_locale` cookie (the switcher writes it).
 * Browser-only: on the server `document` is absent → DEFAULT_LOCALE. Unknown or
 * malformed values fall back too — Flask re-validates against its own whitelist.
 */
function readLocaleCookie(): Locale {
  if (typeof document === "undefined") return DEFAULT_LOCALE;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${LOCALE_COOKIE}=([^;]*)`),
  );
  if (!match) return DEFAULT_LOCALE;
  let value = match[1];
  try {
    value = decodeURIComponent(value);
  } catch {
    return DEFAULT_LOCALE;
  }
  return isLocale(value) ? value : DEFAULT_LOCALE;
}

function buildInit(
  token: string | null,
  init?: FlaskFetchInit,
  locale?: Locale,
): RequestInit {
  const { body, ...rest } = init ?? {};
  const headers = new Headers(rest.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  // X-Locale — язык оператора для бэкенд-контента (каталог акций: название,
  // условия, причина подбора). Optional: server calls omit it → Flask uses 'ru'.
  // Не перетираем локаль, если вызывающий задал заголовок явно.
  if (locale && !headers.has("X-Locale")) headers.set("X-Locale", locale);
  const requestInit: RequestInit = { ...rest, headers };
  if (body !== undefined) {
    headers.set("Content-Type", "application/json");
    requestInit.body = JSON.stringify(body);
  }
  return requestInit;
}

async function parse<T>(res: Response): Promise<T> {
  let json: unknown;
  try {
    json = await res.json();
  } catch {
    if (!res.ok) {
      throw new FlaskApiError(`Ошибка сервера (${res.status})`, res.status,
        "api.error.server", { status: res.status });
    }
    throw new FlaskApiError("Некорректный ответ сервера", res.status,
      "api.error.badResponse");
  }

  // Envelope { ok, data, error } (plan §2). Fall back to raw JSON if not enveloped.
  if (json && typeof json === "object" && "ok" in json) {
    const env = json as { ok: boolean; data?: T; error?: string };
    if (!res.ok || env.ok === false) {
      // env.error — текст бэкенда: не наша копирайт-строка, ключа не ставим.
      throw new FlaskApiError(
        env.error ?? `Запрос не выполнен (${res.status})`,
        res.status,
        env.error ? undefined : "api.error.failed",
        env.error ? undefined : { status: res.status },
      );
    }
    return env.data as T;
  }

  if (!res.ok) {
    throw new FlaskApiError(`Запрос не выполнен (${res.status})`, res.status,
      "api.error.failed", { status: res.status });
  }
  return json as T;
}

/**
 * Low-level call with an explicit token (usable from server components).
 * `locale` is optional — server callers may omit it and Flask defaults to 'ru'.
 * To pin a locale server-side, set an `X-Locale` header in `init` or pass `locale`.
 */
export async function flaskFetchWithToken<T = unknown>(
  path: string,
  token: string | null,
  init?: FlaskFetchInit,
  locale?: Locale,
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, buildInit(token, init, locale));
  } catch (err) {
    // Сообщение браузера (fetch) не наше и не переводимо → ключ только на фолбэк.
    throw new FlaskApiError(
      err instanceof Error ? err.message : "Сеть недоступна",
      0,
      err instanceof Error ? undefined : "api.error.network",
    );
  }
  return parse<T>(res);
}

/**
 * Client-side call — resolves the Supabase token from the browser session and
 * tags the request with the operator's locale (X-Locale), so backend-owned text
 * (bonus catalog: names, terms, match reasons) comes back translated.
 */
export async function flaskFetch<T = unknown>(
  path: string,
  init?: FlaskFetchInit,
): Promise<T> {
  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();
  return flaskFetchWithToken<T>(
    path,
    session?.access_token ?? null,
    init,
    readLocaleCookie(),
  );
}
