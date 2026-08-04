"use client";

import { useCallback, useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import {
  PageHeader,
  Panel,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Badge,
  LifecycleBadge,
  VipBadge,
  Button,
  Chip,
  ChipBar,
  Modal,
  FormField,
  Input,
  Select,
  SCard,
  SCardGrid,
  Banner,
  EmptyState,
} from "@/components/ui";
import { formatInt } from "@/lib/format";
import { LIFECYCLE } from "@/components/ui/badges";
import { useT, type MessageKey } from "@/lib/i18n";
import type { CurrentUser } from "@/lib/types";
import {
  assignPlayers,
  removeFromOperator,
  transferPlayers,
  clearQueue,
  type AssignMode,
  type MutationResult,
} from "./mutations";
import { useRealtimeRefresh } from "./useRealtimeRefresh";
import type { OperatorOption, PoolData, PoolRow } from "./types";

/**
 * Assignment pool (/pool) for heads (head_retention / head_department /
 * super_admin). Filter players, select N rows, then:
 *   - «Назначить»  — split round-robin OR give the whole batch to each operator;
 *   - «Перенести»  — move selected players from one operator to another
 *     (cross-department for head_retention); history stays with the player;
 *   - «Убрать»     — drop selected players from one operator's queue;
 *   - «Очистить»   — wipe an operator's whole queue.
 * Every mutation writes crm.audit_log (in mutations.ts). RLS is the hard gate.
 */

const LIFECYCLES = Object.keys(LIFECYCLE);

type Flash = { type: "ok" | "err"; text: string } | null;

function flashFrom(
  res: MutationResult,
  okText: string,
  errFallback: string,
  t: (key: MessageKey) => string,
): Flash {
  if (res.ok) return { type: "ok", text: okText };
  const text = res.errorKey ? t(res.errorKey) : (res.error ?? errFallback);
  return { type: "err", text };
}

export function PoolBoard({ me, data }: { me: CurrentUser; data: PoolData }) {
  const t = useT();
  const router = useRouter();
  const [, startTransition] = useTransition();
  const refresh = useCallback(() => startTransition(() => router.refresh()), [router]);
  useRealtimeRefresh([{ table: "player_assignments" }], refresh);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [flash, setFlash] = useState<Flash>(null);

  // filters
  const [query, setQuery] = useState("");
  const [stages, setStages] = useState<Set<string>>(new Set());
  const [unassignedOnly, setUnassignedOnly] = useState(false);
  const [opFilter, setOpFilter] = useState<string>("");

  // modals
  const [assignOpen, setAssignOpen] = useState(false);
  const [transferOpen, setTransferOpen] = useState(false);
  const [removeOpen, setRemoveOpen] = useState(false);
  const [clearTarget, setClearTarget] = useState<OperatorOption | null>(null);

  const opCounts = useMemo(() => {
    const m = new Map<string, number>();
    for (const r of data.rows) for (const a of r.assignees) m.set(a.id, (m.get(a.id) ?? 0) + 1);
    return m;
  }, [data.rows]);

  const rows = useMemo(() => {
    return data.rows.filter((r) => {
      if (query && !String(r.playerId).includes(query.trim())) return false;
      if (stages.size > 0 && !(r.directory.lifecycle && stages.has(r.directory.lifecycle)))
        return false;
      if (unassignedOnly && r.assignees.length > 0) return false;
      if (opFilter && !r.assignees.some((a) => a.id === opFilter)) return false;
      return true;
    });
  }, [data.rows, query, stages, unassignedOnly, opFilter]);

  const visibleIds = useMemo(() => rows.map((r) => r.playerId), [rows]);
  const allVisibleSelected =
    visibleIds.length > 0 && visibleIds.every((id) => selected.has(id));

  function toggleStage(s: string) {
    setStages((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });
  }

  function toggleRow(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAllVisible() {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) visibleIds.forEach((id) => next.delete(id));
      else visibleIds.forEach((id) => next.add(id));
      return next;
    });
  }

  const selectedIds = useMemo(() => [...selected], [selected]);

  async function run(fn: () => Promise<MutationResult>, okText: string, onDone?: () => void) {
    setBusy(true);
    setFlash(null);
    const res = await fn();
    setBusy(false);
    setFlash(flashFrom(res, okText, t("players.pool.opErrorFallback"), t));
    if (res.ok) {
      onDone?.();
      setSelected(new Set());
      router.refresh();
    }
  }

  return (
    <>
      <PageHeader title={t("players.pool.title")} lead={t("players.pool.lead")} />

      <SCardGrid className="mt-5 lg:grid-cols-4">
        <SCard label={t("players.pool.card.inPool")} value={formatInt(data.rows.length)} icon="👥" />
        <SCard
          label={t("players.pool.card.selected")}
          value={formatInt(selected.size)}
          icon="✅"
          variant={selected.size > 0 ? "cream" : "default"}
        />
        <SCard label={t("players.pool.card.operators")} value={formatInt(data.operators.length)} icon="🎧" />
        <SCard
          label={t("players.pool.card.unassigned")}
          value={formatInt(data.rows.filter((r) => r.assignees.length === 0).length)}
          icon="🕳"
        />
      </SCardGrid>

      {data.prioritiesDegraded ? <Banner>{t("players.pool.degraded")}</Banner> : null}

      {/* Operators strip: per-operator queue size + clear */}
      {data.operators.length > 0 ? (
        <div className="mt-5 flex flex-wrap gap-2">
          {data.operators.map((o) => (
            <div
              key={o.id}
              className="flex items-center gap-2 bg-canvas border border-hair2 rounded-ctl pl-3 pr-1.5 py-1.5 text-[12.5px]"
            >
              <span className="font-medium text-ink">{o.full_name}</span>
              <span className="text-steel">· {opCounts.get(o.id) ?? 0}</span>
              <button
                type="button"
                onClick={() => setClearTarget(o)}
                disabled={busy || (opCounts.get(o.id) ?? 0) === 0}
                className="text-[11.5px] text-steel hover:text-neg disabled:opacity-40 px-1.5 py-0.5 cursor-pointer"
                title={t("players.pool.clearOperatorTitle")}
              >
                {t("players.pool.clearAction")}
              </button>
            </div>
          ))}
        </div>
      ) : null}

      {/* Filters */}
      <ChipBar>
        <Input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("players.pool.searchPlaceholder")}
          className="max-w-[220px] h-[34px]"
        />
        {LIFECYCLES.map((s) => (
          <Chip key={s} active={stages.has(s)} onClick={() => toggleStage(s)}>
            {t(LIFECYCLE[s].labelKey)}
          </Chip>
        ))}
        <Chip active={unassignedOnly} onClick={() => setUnassignedOnly((v) => !v)}>
          {t("players.pool.unassignedOnly")}
        </Chip>
        <Select
          value={opFilter}
          onChange={(e) => setOpFilter(e.target.value)}
          className="max-w-[220px] h-[34px]"
        >
          <option value="">{t("players.pool.allOperators")}</option>
          {data.operators.map((o) => (
            <option key={o.id} value={o.id}>
              {t("players.pool.queueOf", { name: o.full_name })}
            </option>
          ))}
        </Select>
      </ChipBar>

      {/* Selection toolbar */}
      {selected.size > 0 ? (
        <div className="flex flex-wrap items-center gap-2 bg-cream border border-beige rounded-ctl px-3.5 py-2.5 mb-3">
          <span className="text-[13px] text-ink font-medium">
            {t("players.pool.selectedCount", { n: selected.size })}
          </span>
          <Button size="sm" variant="brand" onClick={() => setAssignOpen(true)} disabled={busy}>
            {t("players.pool.assignTo")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setTransferOpen(true)} disabled={busy}>
            {t("players.pool.transfer")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setRemoveOpen(true)} disabled={busy}>
            {t("players.pool.removeFromQueue")}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setSelected(new Set())} disabled={busy}>
            {t("players.pool.deselect")}
          </Button>
        </div>
      ) : null}

      {flash ? (
        <div
          className={
            "mb-3 text-[13px] rounded-ctl px-3.5 py-2.5 border " +
            (flash.type === "ok"
              ? "text-pos bg-cream border-beige"
              : "text-neg bg-cream border-beige")
          }
        >
          {flash.text}
        </div>
      ) : null}

      {/* Table */}
      {rows.length === 0 ? (
        <Panel>
          <EmptyState title={t("players.pool.emptyTitle")} description={t("players.pool.emptyDesc")} />
        </Panel>
      ) : (
        <Panel>
          <Table>
            <THead>
              <TR>
                <TH>
                  <input
                    type="checkbox"
                    checked={allVisibleSelected}
                    onChange={toggleAllVisible}
                    aria-label={t("players.pool.selectAllVisible")}
                  />
                </TH>
                <TH className="text-left">{t("players.pool.col.player")}</TH>
                <TH className="text-left">{t("players.pool.col.stage")}</TH>
                <TH className="text-left">VIP</TH>
                <TH className="text-left">{t("players.pool.col.country")}</TH>
                <TH className="text-left">{t("players.pool.col.affiliate")}</TH>
                <TH>{t("players.pool.col.value")}</TH>
                <TH className="text-left">{t("players.pool.col.queueOwner")}</TH>
              </TR>
            </THead>
            <TBody>
              {rows.map((r) => (
                <PoolRowView
                  key={r.playerId}
                  row={r}
                  checked={selected.has(r.playerId)}
                  onToggle={() => toggleRow(r.playerId)}
                />
              ))}
            </TBody>
          </Table>
        </Panel>
      )}

      <AssignModal
        open={assignOpen}
        onClose={() => setAssignOpen(false)}
        operators={data.operators}
        selectedCount={selected.size}
        busy={busy}
        onConfirm={(operatorIds, mode) =>
          run(
            () => assignPlayers({ actorId: me.id, playerIds: selectedIds, operatorIds, mode }),
            mode === "split"
              ? t("players.pool.result.split", { count: selected.size, ops: operatorIds.length })
              : t("players.pool.result.all", { count: selected.size, ops: operatorIds.length }),
            () => setAssignOpen(false),
          )
        }
      />

      <TransferModal
        open={transferOpen}
        onClose={() => setTransferOpen(false)}
        operators={data.operators}
        selectedCount={selected.size}
        busy={busy}
        onConfirm={(from, to) =>
          run(
            () =>
              transferPlayers({
                actorId: me.id,
                playerIds: selectedIds,
                fromOperatorId: from,
                toOperatorId: to,
              }),
            t("players.pool.result.transfer", { count: selected.size }),
            () => setTransferOpen(false),
          )
        }
      />

      <RemoveModal
        open={removeOpen}
        onClose={() => setRemoveOpen(false)}
        operators={data.operators}
        selectedCount={selected.size}
        busy={busy}
        onConfirm={(operatorId) =>
          run(
            () => removeFromOperator({ actorId: me.id, operatorId, playerIds: selectedIds }),
            t("players.pool.result.remove", { count: selected.size }),
            () => setRemoveOpen(false),
          )
        }
      />

      <Modal
        open={clearTarget !== null}
        onClose={() => setClearTarget(null)}
        title={t("players.pool.clearOperatorTitle")}
        footer={
          <>
            <Button variant="ghost" onClick={() => setClearTarget(null)}>
              {t("players.pool.cancel")}
            </Button>
            <Button
              variant="brand"
              loading={busy}
              onClick={() =>
                clearTarget &&
                run(
                  () => clearQueue({ actorId: me.id, operatorId: clearTarget.id }),
                  t("players.pool.result.clear", { name: clearTarget.full_name }),
                  () => setClearTarget(null),
                )
              }
            >
              {t("players.pool.clearConfirm")}
            </Button>
          </>
        }
      >
        <div className="text-[13.5px] text-steel">
          {t("players.pool.clearBody", { name: clearTarget?.full_name ?? "" })}
        </div>
      </Modal>
    </>
  );
}

function PoolRowView({
  row,
  checked,
  onToggle,
}: {
  row: PoolRow;
  checked: boolean;
  onToggle: () => void;
}) {
  const t = useT();
  const assignees = row.assignees.map((a) => a.name).join(", ");
  return (
    <TR className={checked ? "bg-cream" : undefined}>
      <TD>
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={t("players.pool.selectRow", { id: row.playerId })}
        />
      </TD>
      <TD className="text-left font-mono text-primary font-medium">
        {row.directory.display_id ?? row.playerId}
      </TD>
      <TD className="text-left">
        <LifecycleBadge stage={row.directory.lifecycle} />
      </TD>
      <TD className="text-left">
        <VipBadge level={row.directory.vip_level} />
      </TD>
      <TD className="text-left text-slate">{row.directory.country ?? "—"}</TD>
      <TD className="text-left text-slate">
        {row.directory.affiliate_code ? (
          <Badge bg="#eff6ff" fg="#1d4ed8">
            {row.directory.affiliate_code}
          </Badge>
        ) : (
          <span className="text-stone">—</span>
        )}
      </TD>
      <TD mono>{row.priority?.value_try != null ? formatInt(row.priority.value_try) : "—"}</TD>
      <TD className="text-left text-slate">
        {row.assignees.length > 0 ? assignees : <span className="text-stone">{t("players.pool.free")}</span>}
      </TD>
    </TR>
  );
}

/* --------------------------- assignment modals --------------------------- */

function OperatorChecklist({
  operators,
  selected,
  onToggle,
}: {
  operators: OperatorOption[];
  selected: Set<string>;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="flex flex-col gap-1.5 max-h-[220px] overflow-auto">
      {operators.map((o) => (
        <label
          key={o.id}
          className="flex items-center gap-2.5 text-[13.5px] text-ink px-2 py-1.5 rounded-ctl hover:bg-cream cursor-pointer"
        >
          <input type="checkbox" checked={selected.has(o.id)} onChange={() => onToggle(o.id)} />
          <span>{o.full_name}</span>
          {o.department ? <span className="text-steel text-[12px]">· {o.department}</span> : null}
        </label>
      ))}
    </div>
  );
}

function AssignModal({
  open,
  onClose,
  operators,
  selectedCount,
  busy,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  operators: OperatorOption[];
  selectedCount: number;
  busy: boolean;
  onConfirm: (operatorIds: string[], mode: AssignMode) => void;
}) {
  const t = useT();
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [mode, setMode] = useState<AssignMode>("split");

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const k = picked.size;
  const perOp = k > 0 ? Math.ceil(selectedCount / k) : 0;
  const preview =
    k === 0
      ? t("players.pool.assign.previewChoose")
      : mode === "split"
        ? t("players.pool.assign.previewSplit", { count: selectedCount, k, perOp })
        : t("players.pool.assign.previewAll", { k, count: selectedCount, total: selectedCount * k });

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("players.pool.assign.title")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("players.pool.cancel")}
          </Button>
          <Button
            variant="brand"
            loading={busy}
            disabled={k === 0}
            onClick={() => onConfirm([...picked], mode)}
          >
            {t("players.pool.assign.confirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="text-[13px] text-steel">
          {t("players.pool.assign.selectedCount", { count: selectedCount })}
        </div>
        <FormField label={t("players.pool.assign.modeLabel")}>
          <div className="flex flex-col gap-1.5">
            <label className="flex items-center gap-2 text-[13.5px] cursor-pointer">
              <input
                type="radio"
                name="assign-mode"
                checked={mode === "split"}
                onChange={() => setMode("split")}
              />
              {t("players.pool.assign.modeSplit")}
            </label>
            <label className="flex items-center gap-2 text-[13.5px] cursor-pointer">
              <input
                type="radio"
                name="assign-mode"
                checked={mode === "all"}
                onChange={() => setMode("all")}
              />
              {t("players.pool.assign.modeAll")}
            </label>
          </div>
        </FormField>
        <FormField label={t("players.pool.assign.operatorsLabel")}>
          <OperatorChecklist operators={operators} selected={picked} onToggle={toggle} />
        </FormField>
        <div className="text-[12.5px] text-primary bg-cream border border-beige rounded-ctl px-3 py-2">
          {preview}
        </div>
      </div>
    </Modal>
  );
}

function TransferModal({
  open,
  onClose,
  operators,
  selectedCount,
  busy,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  operators: OperatorOption[];
  selectedCount: number;
  busy: boolean;
  onConfirm: (from: string, to: string) => void;
}) {
  const t = useT();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const valid = from && to && from !== to && selectedCount > 0;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("players.pool.transfer.title")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("players.pool.cancel")}
          </Button>
          <Button variant="brand" loading={busy} disabled={!valid} onClick={() => onConfirm(from, to)}>
            {t("players.pool.transfer.confirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="text-[13px] text-steel">
          {t("players.pool.transfer.body", { count: selectedCount })}
        </div>
        <FormField label={t("players.pool.transfer.fromLabel")}>
          <Select value={from} onChange={(e) => setFrom(e.target.value)}>
            <option value="">{t("players.pool.selectPlaceholder")}</option>
            {operators.map((o) => (
              <option key={o.id} value={o.id}>
                {o.full_name}
                {o.department ? ` · ${o.department}` : ""}
              </option>
            ))}
          </Select>
        </FormField>
        <FormField label={t("players.pool.transfer.toLabel")}>
          <Select value={to} onChange={(e) => setTo(e.target.value)}>
            <option value="">{t("players.pool.selectPlaceholder")}</option>
            {operators.map((o) => (
              <option key={o.id} value={o.id}>
                {o.full_name}
                {o.department ? ` · ${o.department}` : ""}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Modal>
  );
}

function RemoveModal({
  open,
  onClose,
  operators,
  selectedCount,
  busy,
  onConfirm,
}: {
  open: boolean;
  onClose: () => void;
  operators: OperatorOption[];
  selectedCount: number;
  busy: boolean;
  onConfirm: (operatorId: string) => void;
}) {
  const t = useT();
  const [operatorId, setOperatorId] = useState("");
  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("players.pool.remove.title")}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t("players.pool.cancel")}
          </Button>
          <Button
            variant="brand"
            loading={busy}
            disabled={!operatorId || selectedCount === 0}
            onClick={() => onConfirm(operatorId)}
          >
            {t("players.pool.remove.confirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4">
        <div className="text-[13px] text-steel">
          {t("players.pool.remove.body", { count: selectedCount })}
        </div>
        <FormField label={t("players.pool.remove.operatorLabel")}>
          <Select value={operatorId} onChange={(e) => setOperatorId(e.target.value)}>
            <option value="">{t("players.pool.selectPlaceholder")}</option>
            {operators.map((o) => (
              <option key={o.id} value={o.id}>
                {o.full_name}
                {o.department ? ` · ${o.department}` : ""}
              </option>
            ))}
          </Select>
        </FormField>
      </div>
    </Modal>
  );
}
