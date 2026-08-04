"use client";

import { useMemo, useState } from "react";
import {
  PageHeader,
  Eyebrow,
  Card,
  Panel,
  Badge,
  Button,
  Modal,
  DataTable,
  type Column,
} from "@/components/ui";
import { flaskFetch, flaskErrorText } from "@/lib/api";
import { formatInt } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useCriterionLabel, CRITERIA } from "./kit";
import { ScriptBlockEditor } from "./ScriptBlockEditor";
import type { ScriptData, ScriptBlock, ScriptVersionStats, DryRunData, DryRunCall } from "./types";

/**
 * Скрипт — разметка (§10.8) для руководителя/админа. Черновик ≠ версия (номер
 * присваивается при вводе в бой). «Проверить на прошлых» — эфемерный прогон
 * (в базу не пишет). «Ввести в бой» — подтверждение из спеки. Роли: head_retention,
 * super_admin.
 */
/** Юридические маркеры (§10.8): такие блоки получают пометку «предложено
 *  Дословно», но уровень ПОДТВЕРЖДАЕТ человек — комплаенс не автоназначаем. */
const LEGAL_MARKERS = ["kayıt", "18", "sorumlu oyun"];

/**
 * Резка вставленного текста на блоки (§10.8: «система режет на блоки по
 * нумерации и абзацам; границы правятся руками»). Блок = строка с нумерацией
 * («1.», «2)», «Adım 3:») или разделение пустой строкой. Дефолт уровня —
 * «По смыслу» (в продающем скрипте это большинство блоков).
 */
function splitScriptText(raw: string): ScriptBlock[] {
  const lines = raw.replace(/\r/g, "").split("\n");
  const chunks: { title: string | null; body: string[] }[] = [];
  const numbered = /^\s*(?:\d+[.)]|adım\s*\d+[:.]?|блок\s*\d+[:.]?)\s*(.*)$/i;
  for (const line of lines) {
    const m = line.match(numbered);
    if (m) {
      chunks.push({ title: m[1].trim() || null, body: [] });
    } else if (!line.trim()) {
      // пустая строка открывает новый блок, если в текущем уже есть текст
      if (chunks.length && chunks[chunks.length - 1].body.length) chunks.push({ title: null, body: [] });
    } else {
      if (!chunks.length) chunks.push({ title: null, body: [] });
      chunks[chunks.length - 1].body.push(line.trim());
    }
  }
  return chunks
    .map((c) => ({ title: c.title, text: c.body.join(" ").trim() }))
    .filter((c) => c.text || c.title)
    .map((c) => {
      const probe = `${c.title ?? ""} ${c.text}`.toLowerCase();
      const legal = LEGAL_MARKERS.some((mk) => probe.includes(mk));
      return {
        title: c.title,
        text: c.text,
        check_level: "meaning" as const,
        criterion: null,
        importance: "normal" as const,
        legal_proposed: legal || null,
      };
    });
}

export function ScriptEditor({
  initial,
  onReload,
  scriptRef = null,
  scriptName = null,
  isDefault = false,
}: {
  initial: ScriptData;
  onReload: () => void;
  /** Какой именованный скрипт правим (0011): null → дефолт казино. */
  scriptRef?: string | null;
  /** Имя скрипта для бейджа «что именно правим». */
  scriptName?: string | null;
  /** Этот скрипт — дефолт казино (зелёный бейдж, как раньше у дефолта). */
  isDefault?: boolean;
}) {
  const t = useT();
  const criterionLabel = useCriterionLabel();
  const [blocks, setBlocks] = useState<ScriptBlock[]>(
    initial.draft?.blocks ?? initial.active?.blocks ?? [],
  );
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [dryRun, setDryRun] = useState<DryRunData | null>(null);
  const [activating, setActivating] = useState(false);
  const [pasting, setPasting] = useState(false);
  const [pasteText, setPasteText] = useState("");

  function applyPaste() {
    const next = splitScriptText(pasteText);
    if (!next.length) return;
    setBlocks(next);          // границы дальше правятся руками в блоках
    setPasting(false);
    setPasteText("");
    setNotice(t("callsboard.script.pasted", { n: next.length }));
  }

  const activeCriteria = useMemo(() => {
    const set = new Set<string>();
    for (const b of blocks) if (b.check_level === "meaning" && b.criterion) set.add(b.criterion);
    return set;
  }, [blocks]);
  const missing = CRITERIA.filter((c) => !activeCriteria.has(c));

  const updateBlock = (i: number, next: ScriptBlock) =>
    setBlocks((prev) => prev.map((b, idx) => (idx === i ? next : b)));

  async function saveDraft(): Promise<boolean> {
    setBusy(true);
    setErr(null);
    setNotice(null);
    try {
      await flaskFetch("/api/v1/call-analysis/script/draft", { method: "POST", body: { blocks, script_ref: scriptRef } });
      setNotice(t("callsboard.script.saved"));
      return true;
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function runDryRun() {
    setBusy(true);
    setErr(null);
    try {
      const d = await flaskFetch<DryRunData>("/api/v1/call-analysis/script/dry-run", { method: "POST", body: { blocks, script_ref: scriptRef } });
      setDryRun(d);
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  async function activate() {
    setBusy(true);
    setErr(null);
    try {
      // Сначала сохраняем показанные блоки как черновик, затем вводим в бой.
      await flaskFetch("/api/v1/call-analysis/script/draft", { method: "POST", body: { blocks, script_ref: scriptRef } });
      const res = await flaskFetch<{ version: number }>("/api/v1/call-analysis/script/activate", { method: "POST", body: { script_ref: scriptRef } });
      setActivating(false);
      setNotice(t("callsboard.script.activated", { version: res.version }));
      onReload();
    } catch (e) {
      setErr(flaskErrorText(e, t, "callsboard.common.loadFailed"));
    } finally {
      setBusy(false);
    }
  }

  const dryCols: Column<DryRunCall>[] = [
    { key: "call", header: t("callsboard.script.dryRun.col.call"), id: true, render: (r) => `#${r.call_id.slice(0, 4).toUpperCase()}` },
    { key: "cur", header: t("callsboard.script.dryRun.col.current"), mono: true, render: (r) => (r.current == null ? "—" : formatInt(r.current)) },
    { key: "draft", header: t("callsboard.script.dryRun.col.draft"), mono: true, render: (r) => (r.draft == null ? "—" : formatInt(r.draft)) },
    { key: "delta", header: t("callsboard.script.dryRun.col.delta"), align: "right", render: (r) => <DeltaCell delta={r.delta} /> },
  ];

  const badge = initial.active?.version
    ? t("callsboard.script.activeBadge", { version: initial.active.version })
    : t("callsboard.script.draftBadge");

  // Какой скрипт правим — чтобы не перепутать варианты (0011).
  const scopeBadge = scriptName
    ? t("callsboard.script.scopeScript", { name: scriptName })
    : t("callsboard.script.groups.editingDefault");

  return (
    <>
      <PageHeader
        title={t("callsboard.script.title")}
        accent={t("callsboard.script.subtitle")}
        right={
          <div className="flex flex-wrap items-center gap-2">
            <Badge bg={isDefault ? "#f0fdf4" : "#f5f3ff"} fg={isDefault ? "#166534" : "#5b21b6"}>{scopeBadge}</Badge>
            <Badge bg="#eff6ff" fg="#1e293b">{badge}</Badge>
            <Button size="sm" variant="ghost" onClick={() => setPasting(true)}>{t("callsboard.script.pasteButton")}</Button>
            <Button size="sm" variant="ghost" loading={busy} disabled={!blocks.length} onClick={runDryRun}>{t("callsboard.script.dryRun")}</Button>
            <Button size="sm" variant="ghost" loading={busy} disabled={!blocks.length} onClick={saveDraft}>{t("callsboard.script.saveDraft")}</Button>
            <Button size="sm" variant="brand" disabled={!blocks.length} onClick={() => setActivating(true)}>{t("callsboard.script.activate")}</Button>
          </div>
        }
      />

      {err ? <div className="mt-4 text-[13px] text-neg">{err}</div> : null}
      {notice ? <div className="mt-4 text-[13px] text-primary">{notice}</div> : null}

      {blocks.length === 0 ? (
        <Card className="mt-6">
          <p className="text-[13.5px] text-steel">{t("callsboard.script.empty")}</p>
        </Card>
      ) : (
        <>
          <p className="mt-5 text-[13.5px] text-slate">{t("callsboard.script.intro")}</p>
          <div className="mt-4 space-y-4">
            {blocks.map((b, i) => (
              <ScriptBlockEditor key={i} index={i} block={b} onChange={(next) => updateBlock(i, next)} />
            ))}
          </div>
        </>
      )}

      <Eyebrow>{t("callsboard.script.missingSteps")}</Eyebrow>
      <Card>
        {missing.length ? (
          <>
            <div className="text-[14px] font-medium text-slate">{missing.map((c) => criterionLabel(c)).join(" · ")}</div>
            <p className="mt-2 text-[13px] text-steel">{t("callsboard.script.missingSteps.body")}</p>
          </>
        ) : (
          <p className="text-[13.5px] text-steel">{t("callsboard.script.missingSteps.none")}</p>
        )}
      </Card>

      {/* Версии по РЕЗУЛЬТАТУ: принятые офферы, деп/игра ≤7д, минуты до депа.
          Баллы версий несравнимы (§10.5) — сравниваем по исходам (§10.6). */}
      {initial.versions_stats?.length ? (
        <>
          <Eyebrow>{t("callsboard.script.stats.title")}</Eyebrow>
          <Panel>
            <DataTable
              columns={statsCols(t)}
              rows={initial.versions_stats}
              getRowKey={(r) => `${r.group_id ?? "default"}-${r.version}`}
              state="data"
            />
          </Panel>
          <p className="mt-2 text-[12.5px] text-steel">ⓘ {t("callsboard.script.groups.stats.note")}</p>
          <p className="mt-1 text-[12.5px] text-steel">ⓘ {t("callsboard.script.stats.note")}</p>
        </>
      ) : null}

      {/* Прогон черновика на прошлых (§10.8) */}
      <Modal
        open={!!dryRun}
        onClose={() => setDryRun(null)}
        title={dryRun ? t("callsboard.script.dryRun.title", { n: dryRun.sample_size }) : ""}
        widthClass="max-w-2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => setDryRun(null)}>{t("callsboard.script.dryRun.back")}</Button>
            <Button variant="brand" onClick={() => { setDryRun(null); setActivating(true); }}>{t("callsboard.script.activate")}</Button>
          </>
        }
      >
        {dryRun ? (
          dryRun.calls.length ? (
            <>
              <div className="mb-3 text-[14px] font-medium text-ink">
                {t("callsboard.script.dryRun.avg", {
                  current: dryRun.avg_current == null ? "—" : formatInt(dryRun.avg_current),
                  draft: dryRun.avg_draft == null ? "—" : formatInt(dryRun.avg_draft),
                })}
              </div>
              <Panel>
                <DataTable columns={dryCols} rows={dryRun.calls} getRowKey={(r) => r.call_id} state="data" />
              </Panel>
              <p className="mt-3 text-[12.5px] text-steel">ⓘ {t("callsboard.script.dryRun.note")}</p>
            </>
          ) : (
            <p className="text-[13.5px] text-steel">{t("callsboard.script.dryRun.empty")}</p>
          )
        ) : null}
      </Modal>

      {/* Ввод в бой (§10.8) */}
      <Modal
        open={activating}
        onClose={() => setActivating(false)}
        title={t("callsboard.script.activate.title")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setActivating(false)}>{t("callsboard.script.cancel")}</Button>
            <Button variant="brand" loading={busy} onClick={activate}>{t("callsboard.script.activate.confirm")}</Button>
          </>
        }
      >
        <p className="text-[13.5px] text-slate">{t("callsboard.script.activate.body")}</p>
        <p className="mt-3 font-medium text-[13.5px] text-ink">{t("callsboard.script.activate.activeCriteria", { n: activeCriteria.size })}</p>
        <p className="mt-1 text-[13px] text-steel">{t("callsboard.script.activate.markNote")}</p>
      </Modal>

      {/* Вставка скрипта текстом (§10.8: система режет на блоки, границы правятся руками) */}
      <Modal
        open={pasting}
        onClose={() => setPasting(false)}
        title={t("callsboard.script.paste.title")}
        widthClass="max-w-2xl"
        footer={
          <>
            <Button variant="ghost" onClick={() => setPasting(false)}>{t("callsboard.script.cancel")}</Button>
            <Button variant="brand" disabled={!pasteText.trim()} onClick={applyPaste}>{t("callsboard.script.paste.apply")}</Button>
          </>
        }
      >
        <p className="text-[13px] text-steel">{t("callsboard.script.paste.hint")}</p>
        <textarea
          value={pasteText}
          onChange={(e) => setPasteText(e.target.value)}
          rows={14}
          className="mt-3 w-full rounded-ctl border border-hair bg-canvas px-3 py-2 text-[13.5px] font-mono leading-relaxed text-ink outline-none focus:border-primary"
          placeholder={t("callsboard.script.paste.placeholder")}
        />
        {blocks.length ? (
          <p className="mt-2 text-[12.5px] text-neg">{t("callsboard.script.paste.replaceWarning", { n: blocks.length })}</p>
        ) : null}
      </Modal>
    </>
  );
}

/** Колонки «версии по результату». Минуты до депа — медиана по звонкам версии. */
function statsCols(t: ReturnType<typeof useT>): Column<ScriptVersionStats>[] {
  const dash = (v: number | null | undefined, suffix = "") => (v == null ? "—" : `${formatInt(v)}${suffix}`);
  return [
    { key: "variant", header: t("callsboard.script.groups.stats.variant"), render: (r) => r.script_name ?? r.group_name ?? t("callsboard.script.groups.stats.defaultVariant") },
    { key: "v", header: t("callsboard.script.stats.col.version"), id: true, render: (r) => `v${r.version}` },
    { key: "at", header: t("callsboard.script.stats.col.activated"), render: (r) => (r.activated_at ? r.activated_at.slice(0, 10) : "—") },
    { key: "n", header: t("callsboard.script.stats.col.analyzed"), mono: true, render: (r) => formatInt(r.analyzed) },
    { key: "acc", header: t("callsboard.script.stats.col.accepted"), mono: true, render: (r) => (r.accept_rate == null ? "—" : `${r.accepted} (${r.accept_rate}%)`) },
    { key: "dep", header: t("callsboard.script.stats.col.dep7d"), mono: true, render: (r) => dash(r.dep7d) },
    { key: "play", header: t("callsboard.script.stats.col.play7d"), mono: true, render: (r) => dash(r.play7d) },
    { key: "med", header: t("callsboard.script.stats.col.depMedian"), mono: true, render: (r) => dash(r.dep_median_min, t("callsboard.script.stats.minSuffix")) },
    { key: "score", header: t("callsboard.script.stats.col.score"), mono: true, render: (r) => dash(r.avg_score) },
  ];
}

function DeltaCell({ delta }: { delta: number | null }) {
  if (delta == null) return <span className="font-mono text-stone">—</span>;
  if (delta === 0) return <span className="font-mono text-steel">0</span>;
  const up = delta > 0;
  return <span className={`font-mono font-medium ${up ? "text-pos" : "text-neg"}`}>{up ? "+" : "−"}{Math.abs(delta)}</span>;
}
