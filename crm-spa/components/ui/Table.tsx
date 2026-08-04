"use client";

import { useMemo, useState, type ReactNode, type ThHTMLAttributes, type TdHTMLAttributes } from "react";
import { useRouter } from "next/navigation";
import { cn } from "@/lib/cn";
import { Skeleton, EmptyState, ErrorState } from "./States";

/* ---------------------------------------------------------------------------
 * Low-level primitives — board table CSS (13.5px, right-aligned, sticky head,
 * first column left, hairline row borders, clickable-row hover).
 * ------------------------------------------------------------------------- */

export function Table({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full border-collapse text-[13.5px]", className)}>{children}</table>
    </div>
  );
}

export function THead({ children }: { children: ReactNode }) {
  return <thead>{children}</thead>;
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody>{children}</tbody>;
}

interface TRProps {
  children: ReactNode;
  /** Whole-row link — navigates on click (board onclick=location.href). */
  href?: string;
  className?: string;
}

export function TR({ children, href, className }: TRProps) {
  const router = useRouter();
  if (href) {
    return (
      <tr
        onClick={() => router.push(href)}
        onKeyDown={(e) => {
          if (e.key === "Enter") router.push(href);
        }}
        tabIndex={0}
        className={cn("cursor-pointer hover:bg-cream transition-colors", className)}
      >
        {children}
      </tr>
    );
  }
  return <tr className={className}>{children}</tr>;
}

export function TH({ children, className, ...rest }: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      className={cn(
        "text-right font-normal text-steel text-[11px] uppercase tracking-[0.5px]",
        "bg-surface px-3.5 py-[11px] border-b border-hair whitespace-nowrap sticky top-0",
        "first:text-left",
        className,
      )}
      {...rest}
    >
      {children}
    </th>
  );
}

interface TDProps extends TdHTMLAttributes<HTMLTableCellElement> {
  /** Monospaced numeric cell (board .num). */
  mono?: boolean;
  /** Primary-coloured monospace id cell (board td.id). */
  idCell?: boolean;
}

export function TD({ children, mono, idCell, className, ...rest }: TDProps) {
  return (
    <td
      className={cn(
        "text-right px-3.5 py-[11px] border-b border-hair whitespace-nowrap first:text-left",
        (mono || idCell) && "font-mono",
        idCell && "text-primary font-medium",
        className,
      )}
      {...rest}
    >
      {children}
    </td>
  );
}

/* ---------------------------------------------------------------------------
 * DataTable — columns + rows with the four required states built in.
 * ------------------------------------------------------------------------- */

export type TableState = "data" | "loading" | "empty" | "error";

export interface Column<T> {
  key: string;
  header: ReactNode;
  align?: "left" | "right";
  /** Monospace cell (numbers / ids). */
  mono?: boolean;
  /** Render as a primary-coloured id cell. */
  id?: boolean;
  render: (row: T) => ReactNode;
  className?: string;
  /**
   * Значение для сортировки по этой колонке. Если не задано — берётся row[key]
   * (когда это число/строка). Задайте явно для вычисляемых/форматированных колонок.
   */
  sortValue?: (row: T) => number | string | null | undefined;
  /** Отключить сортировку по колонке (напр. колонка действий/кнопок). */
  sortable?: boolean;
}

type SortDir = "desc" | "asc";
interface SortState {
  key: string;
  dir: SortDir;
}

/** Сравнимое значение колонки для строки (sortValue → row[key] → null). */
function sortValueOf<T>(col: Column<T>, row: T): number | string | null {
  if (col.sortValue) {
    const v = col.sortValue(row);
    return v === undefined ? null : v;
  }
  const raw = (row as Record<string, unknown>)?.[col.key];
  return typeof raw === "number" || typeof raw === "string" ? raw : null;
}

/** Клик по заголовку: none → desc → asc → none (первый клик = «от большего к меньшему»). */
function nextSort(cur: SortState | null, key: string): SortState | null {
  if (!cur || cur.key !== key) return { key, dir: "desc" };
  if (cur.dir === "desc") return { key, dir: "asc" };
  return null;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T, index: number) => string | number;
  /** Whole-row link target. */
  getRowHref?: (row: T) => string | undefined;
  state?: TableState;
  skeletonRows?: number;
  /** Empty-state copy. */
  emptyTitle?: ReactNode;
  emptyDescription?: ReactNode;
  /** Error-state retry handler. */
  onRetry?: () => void;
  errorTitle?: ReactNode;
  errorDescription?: ReactNode;
  className?: string;
  /**
   * Клиентская сортировка по клику на заголовок (первый клик — по убыванию).
   * По умолчанию включена; false — отключить для всей таблицы (напр. серверная
   * сортировка/фиксированный порядок). Отдельные колонки — через col.sortable.
   */
  sortable?: boolean;
}

export function DataTable<T>({
  columns,
  rows,
  getRowKey,
  getRowHref,
  state = "data",
  skeletonRows = 6,
  emptyTitle,
  emptyDescription,
  onRetry,
  errorTitle,
  errorDescription,
  className,
  sortable = true,
}: DataTableProps<T>) {
  const colCount = columns.length;
  const [sort, setSort] = useState<SortState | null>(null);

  function cellAlign(col: Column<T>, index: number): string {
    const align = col.align ?? (index === 0 ? "left" : "right");
    return align === "left" ? "text-left" : "text-right";
  }

  // Колонка сортируема, только если по ней реально есть сравнимые значения
  // (иначе не показываем «мёртвую» стрелку на колонках-действиях/пустых).
  const sortableKeys = useMemo(() => {
    if (!sortable) return new Set<string>();
    const keys = new Set<string>();
    for (const col of columns) {
      if (col.sortable === false) continue;
      if (col.sortable === true || col.sortValue) { keys.add(col.key); continue; }
      if (rows.some((r) => sortValueOf(col, r) !== null)) keys.add(col.key);
    }
    return keys;
  }, [columns, rows, sortable]);

  const canSortCol = (col: Column<T>) => sortableKeys.has(col.key);

  // Сортируем КОПИЮ строк (порядок из props сохраняется в idle-состоянии).
  const sortedRows = useMemo(() => {
    if (!sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col) return rows;
    const mul = sort.dir === "desc" ? -1 : 1;
    return [...rows].sort((a, b) => {
      const va = sortValueOf(col, a);
      const vb = sortValueOf(col, b);
      // null всегда внизу, независимо от направления
      if (va === null && vb === null) return 0;
      if (va === null) return 1;
      if (vb === null) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * mul;
      return String(va).localeCompare(String(vb), undefined, { numeric: true }) * mul;
    });
  }, [rows, sort, columns]);

  return (
    <div className="overflow-x-auto">
      <table className={cn("w-full border-collapse text-[13.5px]", className)}>
        <thead>
          <tr>
            {columns.map((col, i) => {
              const active = sort?.key === col.key;
              const canSort = canSortCol(col);
              const arrow = active ? (sort?.dir === "desc" ? "▼" : "▲") : "↕";
              return (
                <th
                  key={col.key}
                  onClick={canSort ? () => setSort((s) => nextSort(s, col.key)) : undefined}
                  aria-sort={active ? (sort?.dir === "desc" ? "descending" : "ascending") : undefined}
                  className={cn(
                    "font-normal text-steel text-[11px] uppercase tracking-[0.5px]",
                    "bg-surface px-3.5 py-[11px] border-b border-hair whitespace-nowrap sticky top-0",
                    cellAlign(col, i),
                    canSort && "cursor-pointer select-none hover:text-ink group",
                  )}
                >
                  {col.header}
                  {canSort ? (
                    <span
                      className={cn(
                        "ml-1 inline-block align-middle text-[10px]",
                        active ? "text-primary" : "text-hair2 opacity-0 group-hover:opacity-100",
                      )}
                    >
                      {arrow}
                    </span>
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {state === "loading" &&
            Array.from({ length: skeletonRows }).map((_, r) => (
              <tr key={`sk-${r}`}>
                {columns.map((col, i) => (
                  <td key={col.key} className="px-3.5 py-[11px] border-b border-hair">
                    <Skeleton className={cn("h-3.5", i === 0 ? "w-28" : "w-16 ml-auto")} />
                  </td>
                ))}
              </tr>
            ))}

          {state === "error" && (
            <tr>
              <td colSpan={colCount} className="p-0">
                <ErrorState title={errorTitle} description={errorDescription} onRetry={onRetry} />
              </td>
            </tr>
          )}

          {state === "empty" && (
            <tr>
              <td colSpan={colCount} className="p-0">
                <EmptyState title={emptyTitle} description={emptyDescription} />
              </td>
            </tr>
          )}

          {state === "data" &&
            sortedRows.map((row, r) => {
              const href = getRowHref?.(row);
              return (
                <TR key={getRowKey(row, r)} href={href}>
                  {columns.map((col, i) => (
                    <td
                      key={col.key}
                      className={cn(
                        "px-3.5 py-[11px] border-b border-hair whitespace-nowrap",
                        cellAlign(col, i),
                        (col.mono || col.id) && "font-mono",
                        col.id && "text-primary font-medium",
                        col.className,
                      )}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </TR>
              );
            })}
        </tbody>
      </table>
    </div>
  );
}
