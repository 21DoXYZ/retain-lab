"use client";

import { useState } from "react";
import {
  PageHeader,
  Eyebrow,
  Card,
  Panel,
  Banner,
  Field,
  Badge,
  Button,
  Modal,
  Input,
  FormField,
  Pill,
  PillRow,
  ErrorState,
  SkeletonText,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useResource, Note } from "./kit";
import type { KeysData, KeyToken, KeyRegenerated } from "./types";

/**
 * /keys — «Подключение данных» (онбординг, шаги 1-2 go-live чеклиста).
 * Структура ведёт за руку: 1) токен -> 2) сниппет на сайт -> 3) Stripe-вебхук.
 * Секреты НЕ показываем — только маска+длина; сырой токен виден РОВНО ОДИН РАЗ
 * в модалке после «пересоздать». IP-allowlist — внизу как advanced.
 */

export function KeysScreen() {
  const t = useT();

  function errMsg(e: unknown): string {
    return flaskErrorText(e, t, "monitor.keys.genericError");
  }

  const { state, data, error, reload } = useResource<KeysData>("/api/v1/keys");
  const loading = state === "loading";
  const d = data;

  const [busy, setBusy] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [revealed, setRevealed] = useState<KeyRegenerated | null>(null);
  const [newIp, setNewIp] = useState("");

  async function regenerate(which: string, label: string) {
    // Подтверждение перед деструктивным действием (борд :3281): один промах —
    // и живой ingest казино падает, пока не выдадут новый токен.
    if (!window.confirm(t("monitor.keys.confirm.regenerate", { label }))) return;
    setBusy(`regen:${which}`);
    setActionError(null);
    try {
      const res = await flaskFetch<KeyRegenerated>("/api/v1/keys/regenerate", {
        method: "POST",
        body: { which },
      });
      setRevealed(res); // shown once in the modal
      reload();
    } catch (e) {
      setActionError(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  async function addIp() {
    const ip = newIp.trim();
    if (!ip) return;
    setBusy("ip:add");
    setActionError(null);
    try {
      await flaskFetch<{ ips: string[] }>("/api/v1/keys/ip/add", { method: "POST", body: { ip } });
      setNewIp("");
      reload();
    } catch (e) {
      setActionError(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  async function removeIp(ip: string) {
    // Подтверждение перед удалением IP из allowlist (борд :3299).
    if (!window.confirm(t("monitor.keys.confirm.removeIp", { ip }))) return;
    setBusy(`ip:rm:${ip}`);
    setActionError(null);
    try {
      await flaskFetch<{ ips: string[] }>("/api/v1/keys/ip/remove", { method: "POST", body: { ip } });
      reload();
    } catch (e) {
      setActionError(errMsg(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <PageHeader
        title={t("monitor.keys.title")}
        accent={t("monitor.keys.accent")}
        lead={t("monitor.keys.lead")}
        right={
          <PillRow>
            <Pill live>{t("monitor.keys.pill.sensitive")}</Pill>
          </PillRow>
        }
      />

      {state === "error" ? (
        <ErrorState description={error ?? undefined} onRetry={reload} />
      ) : (
        <>
          {actionError ? (
            <Banner className="border-l-neg">
              <span className="text-neg font-semibold">{t("monitor.keys.errorPrefix")}</span> {actionError}
            </Banner>
          ) : null}

          <Eyebrow>{t("monitor.keys.eyebrow.tokens")}</Eyebrow>
          <p className="mt-1 mb-2 text-[13px] text-steel max-w-[640px]">{t("monitor.keys.tokensHint")}</p>
          {loading ? (
            <Card className="mt-1">
              <SkeletonText lines={4} />
            </Card>
          ) : (
            <div className="grid gap-4 grid-cols-1 lg:grid-cols-2">
              {(d?.tokens ?? []).map((tok: KeyToken) => (
                <Card key={tok.key}>
                  <div className="flex items-baseline justify-between gap-3">
                    <h3 className="text-[15px] font-semibold text-ink">{tok.label}</h3>
                    {tok.is_set ? (
                      <Badge bg="#dcfce7" fg="#166534">{t("monitor.keys.badge.set")}</Badge>
                    ) : (
                      <Badge bg="#fee2e2" fg="#991b1b">{t("monitor.keys.badge.unset")}</Badge>
                    )}
                  </div>
                  <div className="mt-3 grid gap-2">
                    <Field label={t("monitor.keys.field.mask")} value={tok.masked || "—"} />
                    <Field label={t("monitor.keys.field.length")} value={tok.is_set ? t("monitor.keys.field.lengthValue", { n: tok.length }) : "—"} />
                    <Field label={t("monitor.keys.field.key")} value={tok.key} />
                  </div>
                  <div className="mt-3.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      loading={busy === `regen:${tok.key}`}
                      disabled={busy !== null}
                      onClick={() => regenerate(tok.key, tok.label)}
                    >
                      {t("monitor.keys.regenerate")}
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}

          <Eyebrow>{t("monitor.keys.eyebrow.ingest")}</Eyebrow>
          <p className="mt-1 mb-2 text-[13px] text-steel max-w-[640px]">{t("monitor.keys.snippetHint")}</p>
          <Card>
            <Field label={t("monitor.keys.field.ingestUrl")} value={d?.ingest.url ?? "—"} />
            {d?.ingest.example_curl ? (
              <pre className="mt-3 overflow-x-auto rounded-ctl bg-sb text-sb-text2 text-[12px] leading-relaxed p-3.5 font-mono whitespace-pre">
                {d.ingest.example_curl}
              </pre>
            ) : null}
            <p className="mt-3 text-[13px] text-steel">{t("monitor.keys.snippetCheck")}</p>
          </Card>

          {d?.stripe ? (
            <>
              <Eyebrow>{t("monitor.keys.eyebrow.stripe")}</Eyebrow>
              <p className="mt-1 mb-2 text-[13px] text-steel max-w-[640px]">{t("monitor.keys.stripeHint")}</p>
              <Card>
                <div className="flex items-baseline justify-between gap-3">
                  <h3 className="text-[15px] font-semibold text-ink">{t("monitor.keys.stripe.title")}</h3>
                  {d.stripe.secret_set ? (
                    <Badge bg="#dcfce7" fg="#166534">{t("monitor.keys.stripe.on")}</Badge>
                  ) : (
                    <Badge bg="#fef3c7" fg="#92400e">{t("monitor.keys.stripe.off")}</Badge>
                  )}
                </div>
                <div className="mt-3 grid gap-2">
                  <Field label={t("monitor.keys.stripe.urlLabel")} value={d.stripe.webhook_url} />
                </div>
                <p className="mt-3 text-[13px] text-slate">{t("monitor.keys.stripe.step1")}</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {d.stripe.events.map((ev) => (
                    <span key={ev} className="rounded-md border border-hair2 bg-surface px-2 py-0.5 font-mono text-[11.5px] text-slate">
                      {ev}
                    </span>
                  ))}
                </div>
                <p className="mt-3 text-[13px] text-slate">{t("monitor.keys.stripe.step2")}</p>
              </Card>
            </>
          ) : null}

          <Eyebrow>{t("monitor.keys.eyebrow.ipAllowlist")}</Eyebrow>
          <p className="mt-1 mb-2 text-[13px] text-steel max-w-[640px]">{t("monitor.keys.ipHint")}</p>
          <Panel className="p-4">
            <div className="flex flex-wrap items-end gap-2">
              <FormField label={t("monitor.keys.ipField.label")} className="min-w-[240px] flex-1" hint={t("monitor.keys.ipField.hint")}>
                <Input
                  value={newIp}
                  onChange={(e) => setNewIp(e.target.value)}
                  placeholder="57.129.125.90"
                  onKeyDown={(e) => {
                    if (e.key === "Enter") addIp();
                  }}
                />
              </FormField>
              <Button variant="brand" loading={busy === "ip:add"} disabled={busy !== null || !newIp.trim()} onClick={addIp}>
                {t("monitor.keys.ipAdd")}
              </Button>
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              {loading ? (
                <SkeletonText lines={1} className="w-full" />
              ) : (d?.ips ?? []).length === 0 ? (
                <span className="text-steel text-[13px]">{t("monitor.keys.ipEmpty")}</span>
              ) : (
                (d?.ips ?? []).map((ip) => (
                  <span
                    key={ip}
                    className="inline-flex items-center gap-2 font-mono text-[12.5px] bg-cream border border-beige rounded-full pl-3 pr-1.5 py-1"
                  >
                    {ip}
                    <button
                      type="button"
                      aria-label={t("monitor.keys.ipRemoveAria", { ip })}
                      title={t("monitor.keys.ipRemoveTitle")}
                      disabled={busy !== null}
                      onClick={() => removeIp(ip)}
                      className="text-steel hover:text-neg text-base leading-none cursor-pointer disabled:opacity-50"
                    >
                      ×
                    </button>
                  </span>
                ))
              )}
            </div>
          </Panel>

          {d?.kafka_note ? <Banner>{d.kafka_note}</Banner> : null}

          <Note>{t("monitor.keys.note")}</Note>
        </>
      )}

      <Modal
        open={revealed !== null}
        onClose={() => setRevealed(null)}
        title={t("monitor.keys.modal.title")}
        footer={
          <Button variant="primary" onClick={() => setRevealed(null)}>
            {t("monitor.keys.modal.done")}
          </Button>
        }
      >
        {revealed ? (
          <div className="space-y-3">
            <p className="text-neg font-semibold">{t("monitor.keys.modal.warning")}</p>
            <div>
              <div className="text-[12px] text-steel mb-1">{revealed.label}</div>
              <pre className="overflow-x-auto rounded-ctl bg-cream border border-beige text-ink text-[13px] p-3 font-mono whitespace-pre-wrap break-all select-all">
                {revealed.token}
              </pre>
            </div>
            <p className="text-[13px] text-steel">{t("monitor.keys.modal.nextStep")}</p>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
