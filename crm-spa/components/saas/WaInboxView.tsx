"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flaskFetch } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { Button, Card, PageHeader } from "@/components/ui";
import { NoTenant, isNoTenant } from "./NoTenant";

/**
 * /wa-inbox - переписка с личного WhatsApp-номера (трек C).
 *
 * Композиция - по дизайну sellrise.ai (страница UI UX, «Chats new» и
 * «Chats-user-card»): слева чаты с поиском и бейджем канала, в центре тред,
 * справа карточка контакта. Токены и цвета - НАШИ (retain-lab), не лиловые
 * из макета: продукт обязан выглядеть одним целым.
 *
 * Ответ отсюда - единственный путь отправки в личный канал, за ним всегда
 * живой человек. В карточке контакта только настоящие данные: имя из
 * WhatsApp, адрес, привязанный юзер продукта (если пришёл по connect-ссылке),
 * счётчики переписки. Никаких пустых полей «Company/Birthday» из макета.
 */

interface Chat {
  chat_id: string;
  display: string;
  phone: string;
  name: string;
  last_text: string;
  last_dir: string;
  last_ts: string;
  first_ts: string;
  inbound: number;
  total: number;
  client_user_id: string;
}

interface Msg {
  id: string;
  direction: string;
  text: string;
  name: string;
  ts: string;
}

function timeShort(ts: string): string {
  const d = ts.slice(0, 10);
  const today = new Date().toISOString().slice(0, 10);
  return d === today ? ts.slice(11, 16) : `${d.slice(8, 10)}.${d.slice(5, 7)}`;
}

function dayOf(ts: string): string {
  return ts.slice(0, 10);
}

// Прочитанность живёт в браузере: открыл чат - его последний ts записан.
// Честный компромисс v1: сервер не хранит read-маркеры, поэтому точка
// «непрочитанного» локальна для этого браузера - но никогда не врёт про
// содержимое (сравниваем настоящие ts настоящих входящих).
const READ_KEY = "ra_wa_read";

function readMarks(): Record<string, string> {
  try { return JSON.parse(localStorage.getItem(READ_KEY) || "{}"); }
  catch { return {}; }
}

function markRead(chatId: string, ts: string) {
  try {
    const m = readMarks();
    m[chatId] = ts;
    localStorage.setItem(READ_KEY, JSON.stringify(m));
  } catch { /* приватный режим: точки просто не работают */ }
}

/** Инициалы для аватара: имя из WhatsApp либо цифры адреса. */
function initials(name: string, display: string): string {
  const n = name.trim();
  if (n) {
    const parts = n.split(/\s+/);
    return (parts[0][0] + (parts[1]?.[0] ?? "")).toUpperCase();
  }
  return display.slice(-2);
}

/** Зелёный кружок WhatsApp - бейдж канала, как в макете. */
function WaBadge() {
  return (
    <span className="inline-flex h-[14px] w-[14px] flex-none items-center justify-center rounded-full bg-[#25D366]">
      <svg viewBox="0 0 24 24" width="9" height="9" fill="#fff" aria-hidden>
        <path d="M12 2a10 10 0 0 0-8.7 14.9L2 22l5.3-1.4A10 10 0 1 0 12 2Zm5.1 14.1c-.2.6-1.2 1.2-1.7 1.2-.4.1-1 .1-1.6-.1-.4-.1-.9-.3-1.5-.6-2.6-1.1-4.3-3.8-4.4-4-.1-.2-1.1-1.4-1.1-2.7 0-1.3.7-1.9.9-2.2.2-.3.5-.3.7-.3h.5c.2 0 .4 0 .6.4.2.5.7 1.8.8 1.9.1.1.1.3 0 .5-.1.2-.1.3-.3.5l-.4.5c-.1.1-.3.3-.1.6.2.3.8 1.3 1.7 2.1 1.2 1 2.1 1.3 2.4 1.5.3.1.5.1.6-.1.2-.2.7-.8.9-1.1.2-.3.4-.2.6-.1l1.9.9c.2.1.4.2.4.3.1.1.1.5-.1 1Z"/>
      </svg>
    </span>
  );
}

export function WaInboxView() {
  const t = useT();
  const [chats, setChats] = useState<Chat[]>([]);
  const [state, setState] = useState<"loading" | "data" | "error" | "no_tenant">("loading");
  const [active, setActive] = useState("");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [search, setSearch] = useState("");
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState("");
  const [showCard, setShowCard] = useState(true);
  const [reads, setReads] = useState<Record<string, string>>({});
  const [composing, setComposing] = useState(false);
  const [newPhone, setNewPhone] = useState("");
  const [newText, setNewText] = useState("");
  const [newErr, setNewErr] = useState("");
  const [newBusy, setNewBusy] = useState(false);
  const threadRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setReads(readMarks());
    // deep-link из карточки юзера: /wa-inbox?chat=<chat_id>
    const chat = new URLSearchParams(window.location.search).get("chat");
    if (chat) setActive(chat);
  }, []);

  const loadChats = useCallback(() => {
    flaskFetch<{ chats: Chat[] }>("/api/v1/saas/wa/chats")
      .then((d) => { setChats(d.chats); setState("data"); })
      .catch((e: unknown) => setState(isNoTenant(e) ? "no_tenant" : "error"));
  }, []);

  const loadMsgs = useCallback((chat: string) => {
    if (!chat) return;
    flaskFetch<{ messages: Msg[] }>(`/api/v1/saas/wa/messages?chat=${encodeURIComponent(chat)}`)
      .then((d) => setMsgs(d.messages))
      .catch(() => {});
  }, []);

  useEffect(() => {
    loadChats();
    const id = window.setInterval(loadChats, 10_000);
    return () => window.clearInterval(id);
  }, [loadChats]);

  useEffect(() => {
    loadMsgs(active);
    if (!active) return;
    const id = window.setInterval(() => loadMsgs(active), 4_000);
    return () => window.clearInterval(id);
  }, [active, loadMsgs]);

  useEffect(() => {
    threadRef.current?.scrollTo({ top: threadRef.current.scrollHeight });
  }, [msgs.length, active]);

  const send = () => {
    const text = draft.trim();
    if (!text || !active || sending) return;
    setSending(true);
    setSendErr("");
    setMsgs((m) => [...m, { id: `tmp-${Date.now()}`, direction: "out",
      text, name: "", ts: new Date().toISOString().replace("T", " ") }]);
    setDraft("");
    flaskFetch("/api/v1/saas/wa/reply", { method: "POST",
      body: { chat_id: active, text } })
      .catch((e: unknown) => {
        setSendErr(e instanceof Error ? e.message : "send failed");
        setDraft(text);
        setMsgs((m) => m.filter((x) => !x.id.startsWith("tmp-")));
      })
      .finally(() => setSending(false));
  };

  const startChat = () => {
    if (newBusy || !newPhone.trim() || !newText.trim()) return;
    setNewBusy(true);
    setNewErr("");
    flaskFetch<{ chat_id: string }>("/api/v1/saas/wa/start-chat", {
      method: "POST", body: { phone: newPhone.trim(), text: newText.trim() } })
      .then((d) => {
        setComposing(false);
        setNewPhone("");
        setNewText("");
        setActive(d.chat_id);          // эхо вебхука материализует чат в списке
        loadChats();
      })
      .catch((e: unknown) => {
        const msg = e instanceof Error ? e.message : "failed";
        setNewErr(msg.includes("number_not_on_whatsapp")
          ? t("saas.wainbox.new.notOnWa") : msg);
      })
      .finally(() => setNewBusy(false));
  };

  const q = search.trim().toLowerCase();
  const visible = q
    ? chats.filter((c) => (c.name + " " + c.display + " " + c.last_text).toLowerCase().includes(q))
    : chats;
  const activeChat = chats.find((c) => c.chat_id === active);

  // тред с разделителями по дням, как в мессенджерах
  const thread: (Msg | { day: string })[] = [];
  let lastDay = "";
  for (const m of msgs) {
    const d = dayOf(m.ts);
    if (d !== lastDay) { thread.push({ day: d }); lastDay = d; }
    thread.push(m);
  }

  return (
    <div className="flex h-full flex-col gap-5">
      <PageHeader title={t("saas.wainbox.title")} lead={t("saas.wainbox.lead")} />
      {state === "no_tenant" ? (
        <NoTenant />
      ) : (
        <Card className="flex min-h-[560px] flex-1 overflow-hidden p-0">
          {/* ── чаты ── */}
          <div className="flex w-[300px] flex-none flex-col border-r border-hair">
            <div className="flex items-center gap-2 border-b border-hair p-3">
              <input
                className="h-[36px] w-full rounded-full border border-hair2 bg-canvas px-3.5 text-[13px] text-ink outline-none transition-[border-color] focus:border-primary"
                placeholder={t("saas.wainbox.search")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              <button type="button" aria-label={t("saas.wainbox.new.btn")}
                      title={t("saas.wainbox.new.btn")}
                      className="grid h-[36px] w-[36px] flex-none cursor-pointer place-items-center rounded-full bg-primary text-[18px] leading-none text-white transition-transform active:scale-95"
                      onClick={() => { setComposing((v) => !v); setNewErr(""); }}>
                +
              </button>
            </div>
            {/* написать ПЕРВЫМ на новый номер - вручную, живым человеком */}
            {composing && (
              <div className="flex flex-col gap-2 border-b border-hair bg-canvas/60 p-3">
                <input
                  className="h-[36px] w-full rounded-ctl border border-hair2 bg-canvas px-3 font-mono text-[13px] text-ink outline-none transition-[border-color] focus:border-primary"
                  placeholder={t("saas.wainbox.new.phonePh")}
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                />
                <textarea
                  className="min-h-[60px] w-full resize-none rounded-ctl border border-hair2 bg-canvas px-3 py-2 text-[13px] text-ink outline-none transition-[border-color] focus:border-primary"
                  placeholder={t("saas.wainbox.new.textPh")}
                  value={newText}
                  onChange={(e) => setNewText(e.target.value)}
                />
                {newErr && <p className="text-[12px] text-neg">{newErr}</p>}
                <div>
                  <Button variant="brand" size="sm" loading={newBusy}
                          disabled={!newPhone.trim() || !newText.trim()}
                          onClick={startChat}>
                    {t("saas.wainbox.new.send")}
                  </Button>
                </div>
              </div>
            )}
            {/* «Добавить каналы» из макета: единственный клик до экрана каналов */}
            <a href="/channel-settings"
               className="flex items-center gap-2.5 border-b border-hair bg-primary/[.04] px-3.5 py-3 transition-colors hover:bg-primary/[.08]">
              <span className="grid h-9 w-9 flex-none place-items-center rounded-full border border-dashed border-primary/50 text-[16px] text-primary">+</span>
              <span className="min-w-0">
                <span className="block text-[13px] font-medium text-ink">{t("saas.wainbox.addChannels")}</span>
                <span className="block text-[11.5px] text-steel">{t("saas.wainbox.addChannelsSub")}</span>
              </span>
            </a>
            {state === "data" && chats.length === 0 && (
              <p className="p-4 text-[13px] leading-relaxed text-steel">
                {t("saas.wainbox.empty")}
              </p>
            )}
            <div className="flex-1 overflow-y-auto">
              {visible.map((c) => (
                <button key={c.chat_id} type="button"
                        onClick={() => {
                          setActive(c.chat_id);
                          setSendErr("");
                          markRead(c.chat_id, c.last_ts);
                          setReads((r) => ({ ...r, [c.chat_id]: c.last_ts }));
                        }}
                        className={"block w-full cursor-pointer border-b border-hair px-3.5 py-3 text-left transition-colors " +
                          (c.chat_id === active ? "bg-canvas" : "hover:bg-canvas/60")}>
                  <div className="flex items-center gap-2.5">
                    <span className="grid h-9 w-9 flex-none place-items-center rounded-full bg-primary/10 text-[12.5px] font-semibold text-primary">
                      {initials(c.name, c.display)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="flex min-w-0 items-center gap-1.5">
                          <span className="truncate text-[13.5px] font-medium text-ink">
                            {c.name || c.display}
                          </span>
                          <WaBadge />
                        </span>
                        <span className="flex flex-none items-center gap-1.5">
                          {c.last_dir === "in" && c.chat_id !== active &&
                            (reads[c.chat_id] ?? "") < c.last_ts && (
                            <span className="h-2 w-2 rounded-full bg-primary" />
                          )}
                          <span className="text-[11px] text-steel">{timeShort(c.last_ts)}</span>
                        </span>
                      </span>
                      <span className="mt-0.5 block truncate text-[12.5px] text-steel">
                        {c.last_dir === "out" ? t("saas.wainbox.you") + " " : ""}
                        {c.last_text}
                      </span>
                    </span>
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* ── тред ── */}
          <div className="flex min-w-0 flex-1 flex-col">
            {!active ? (
              <div className="grid flex-1 place-items-center p-6 text-center text-[13px] text-steel">
                {t("saas.wainbox.pick")}
              </div>
            ) : (
              <>
                <div className="flex items-center justify-between gap-2 border-b border-hair px-4 py-2.5">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate text-[13.5px] font-medium text-ink">
                      {activeChat?.name || activeChat?.display || active.split("@")[0]}
                    </span>
                    <WaBadge />
                  </span>
                  <button type="button"
                          className="cursor-pointer rounded-md border border-hair2 px-2 py-0.5 text-[11.5px] text-steel transition-colors hover:border-primary hover:text-primary"
                          onClick={() => setShowCard((v) => !v)}>
                    {t(showCard ? "saas.wainbox.hideCard" : "saas.wainbox.showCard")}
                  </button>
                </div>
                <div ref={threadRef} className="flex-1 space-y-2 overflow-y-auto bg-canvas/40 p-4">
                  {thread.map((item) =>
                    "day" in item ? (
                      <div key={`d-${item.day}`} className="flex items-center gap-3 py-1">
                        <span className="h-px flex-1 bg-hair" />
                        <span className="text-[11px] font-medium text-steel">{item.day}</span>
                        <span className="h-px flex-1 bg-hair" />
                      </div>
                    ) : (
                      <div key={item.id}
                           className={"flex " + (item.direction === "out" ? "justify-end" : "justify-start")}>
                        <div className={"max-w-[70%] rounded-2xl px-3.5 py-2 text-[13.5px] leading-relaxed shadow-sm " +
                          (item.direction === "out"
                            ? "rounded-br-md bg-primary text-white"
                            : "rounded-bl-md border border-hair bg-surface text-ink")}>
                          <div className="whitespace-pre-wrap break-words">{item.text}</div>
                          <div className={"mt-0.5 text-right text-[10.5px] " +
                            (item.direction === "out" ? "text-white/70" : "text-steel")}>
                            {timeShort(item.ts)}
                          </div>
                        </div>
                      </div>
                    ),
                  )}
                </div>
                <div className="border-t border-hair p-3">
                  {sendErr && <p className="mb-1.5 text-[12px] text-neg">{sendErr}</p>}
                  <div className="flex items-end gap-2">
                    <textarea
                      className="max-h-[120px] min-h-[42px] w-full resize-none rounded-2xl border border-hair2 bg-canvas px-[13px] py-2.5 text-sm text-ink outline-none transition-[border-color] focus:border-primary"
                      rows={1}
                      placeholder={t("saas.wainbox.placeholder")}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
                      }}
                    />
                    <Button variant="brand" size="sm" loading={sending}
                            disabled={!draft.trim()} onClick={send}>
                      {t("saas.wainbox.send")}
                    </Button>
                  </div>
                </div>
              </>
            )}
          </div>

          {/* ── карточка контакта («Chats-user-card» из макета) ── */}
          {active && showCard && activeChat && (
            <div className="hidden w-[260px] flex-none flex-col border-l border-hair p-4 lg:flex">
              <div className="flex flex-col items-center gap-2 pb-4 text-center">
                <span className="grid h-14 w-14 place-items-center rounded-full bg-primary/10 text-[17px] font-semibold text-primary">
                  {initials(activeChat.name, activeChat.display)}
                </span>
                <div className="text-[14.5px] font-semibold text-ink">
                  {activeChat.name || activeChat.display}
                </div>
                <div className="flex items-center gap-1.5 text-[12px] text-steel">
                  <WaBadge /> {t("saas.wainbox.card.lastSeen", { time: timeShort(activeChat.last_ts) })}
                </div>
              </div>

              <div className="rounded-ctl border border-hair bg-surface p-3 text-[12.5px]">
                <div className="font-medium text-ink">{t("saas.wainbox.card.info")}</div>
                <dl className="mt-2 space-y-1.5">
                  {activeChat.phone && (
                    <div className="flex justify-between gap-2">
                      <dt className="text-steel">{t("saas.wainbox.card.phone")}</dt>
                      <dd className="font-mono text-[11.5px] text-slate">+{activeChat.phone}</dd>
                    </div>
                  )}
                  <div className="flex justify-between gap-2">
                    <dt className="text-steel">{t("saas.wainbox.card.address")}</dt>
                    <dd className="truncate font-mono text-[11.5px] text-slate">{activeChat.display}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-steel">{t("saas.wainbox.card.messages")}</dt>
                    <dd className="text-slate">{activeChat.total}</dd>
                  </div>
                  <div className="flex justify-between gap-2">
                    <dt className="text-steel">{t("saas.wainbox.card.firstSeen")}</dt>
                    <dd className="text-slate">{activeChat.first_ts.slice(0, 10)}</dd>
                  </div>
                </dl>
              </div>

              <div className="mt-3 rounded-ctl border border-hair bg-surface p-3 text-[12.5px]">
                <div className="font-medium text-ink">{t("saas.wainbox.card.user")}</div>
                {activeChat.client_user_id ? (
                  <>
                    <p className="mt-1.5 leading-relaxed text-steel">
                      {t("saas.wainbox.card.linked")}
                    </p>
                    <div className="mt-1 truncate font-mono text-[11.5px] text-slate">
                      {activeChat.client_user_id}
                    </div>
                    <a href={`/users/${encodeURIComponent(activeChat.client_user_id)}`}
                       className="mt-2 inline-block text-[12.5px] font-medium text-primary hover:underline">
                      {t("saas.wainbox.card.openUser")}
                    </a>
                  </>
                ) : (
                  <p className="mt-1.5 leading-relaxed text-steel">
                    {t("saas.wainbox.card.unlinked")}
                  </p>
                )}
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
