import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { NAV_GROUPS, canSee } from "./nav";
import { isNavKeyEnabled, isGroupEnabled } from "@/lib/modules";
import { Icon, hasIcon } from "./icons";
import type { MessageKey } from "@/lib/i18n";
import { DEFAULT_LOCALE } from "@/lib/i18n/config";
import { getMessages } from "@/lib/i18n/messages";

/** Resolved default-locale dictionary for provider-less renders (/dev/ui). */
const FALLBACK_MESSAGES = getMessages(DEFAULT_LOCALE);

/**
 * AppShell — dark sidebar + white content area, 1:1 with the live dashboard.
 * Presentational only: `active` marks the current nav key, `role` filters
 * items via the (stub) role matrix. Real routing/guards are B1's job — this
 * component holds no state and works as a Server Component.
 */
interface AppShellProps {
  active?: string;
  role?: string;
  children: ReactNode;
  /** Optional slot pinned to the top-right of the content area. */
  headerRight?: ReactNode;
  /**
   * Translate nav group titles / item labels. AppChrome (client, inside the
   * global <I18nProvider>) passes useT() here so the sidebar follows the
   * active locale. Falls back to the resolved default-locale dictionary when
   * omitted, so AppShell keeps working standalone (e.g. the /dev/ui showcase)
   * without requiring a provider — this is why AppShell itself doesn't call
   * useT() and can stay a plain (server-renderable) component.
   */
  t?: (key: MessageKey) => string;
}

export function AppShell({ active, role, children, headerRight, t }: AppShellProps) {
  const translate = t ?? ((key: MessageKey) => FALLBACK_MESSAGES[key]);
  return (
    <div className="flex h-screen overflow-hidden">
      {/* Sidebar — hidden below ~lg, like the board. Own scroll + full-height dark
          bg (fix: min-h-screen let long nav overflow the dark panel onto the body). */}
      <aside className="hidden lg:flex w-[260px] flex-none flex-col overflow-y-auto bg-sb text-sb-text border-r border-sb-line px-4 py-[22px]">
        <div
          className="flex items-center gap-3 rounded-2xl px-3 py-[11px] mb-[22px]"
          style={{ background: "linear-gradient(180deg,#252b41,#1a1f33)" }}
        >
          <span
            className="grid place-items-center w-10 h-10 rounded-xl text-white font-extrabold text-base flex-none"
            style={{
              background: "linear-gradient(135deg,#60a5fa,#3b82f6)",
              boxShadow: "0 8px 20px rgba(59,130,246,.25)",
            }}
          >
            R
          </span>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">Retention</div>
            <div className="text-xs text-sb-grp mt-0.5">ClickHouse · live</div>
          </div>
        </div>

        <nav className="flex flex-col gap-[5px]">
          {NAV_GROUPS.filter((g) => isGroupEnabled(g.title)).map((group) => {
            // отключённые модули (правка Васи) прячем из сайдбара наряду с role-гейтом
            const items = group.items.filter((it) => canSee(it, role) && isNavKeyEnabled(it.key));
            if (items.length === 0) return null;
            return (
              <div key={group.title} className="contents">
                {group.section ? (
                  <div className="text-sb-grp text-[11px] font-bold uppercase tracking-[2px] px-3 pt-[30px] pb-0.5">
                    {translate(group.section)}
                  </div>
                ) : null}
                <div className="text-sb-grp text-[11px] font-semibold uppercase tracking-[1px] px-3 pt-[18px] pb-1.5">
                  {translate(group.title)}
                </div>
                {items.map((it) => {
                  const on = it.key === active;
                  return (
                    <Link
                      key={it.key}
                      href={it.href}
                      aria-current={on ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-3 text-sm font-medium px-3.5 py-[11px] rounded-[14px] transition-colors",
                        on
                          ? "bg-primary text-white"
                          : "text-sb-text hover:bg-sb-hover hover:text-sb-text2",
                      )}
                      style={on ? { boxShadow: "0 8px 20px rgba(37,99,235,.28)" } : undefined}
                    >
                      <span className="w-5 h-5 grid place-items-center flex-none">
                        {hasIcon(it.key) ? <Icon name={it.key} /> : <span>{it.emoji}</span>}
                      </span>
                      <span className="truncate">{translate(it.label)}</span>
                    </Link>
                  );
                })}
              </div>
            );
          })}
        </nav>
      </aside>

      {/* Content */}
      <main className="flex-1 min-w-0 bg-canvas overflow-auto px-[32px] pt-[26px] pb-[54px]">
        {headerRight ? (
          <div className="flex justify-end mb-2">{headerRight}</div>
        ) : null}
        {children}
      </main>
    </div>
  );
}

/**
 * PageHeader — the board's .h1/.lead heading block. `accent` renders the
 * blue-highlighted emphasis (board `.h1 em`).
 */
interface PageHeaderProps {
  title: ReactNode;
  accent?: ReactNode;
  lead?: ReactNode;
  right?: ReactNode;
}

export function PageHeader({ title, accent, lead, right }: PageHeaderProps) {
  return (
    <div className="flex items-start justify-between gap-4 flex-wrap">
      <div>
        <h1 className="font-extrabold text-[30px] tracking-[-0.6px] text-ink">
          {title} {accent ? <span className="text-primary">{accent}</span> : null}
        </h1>
        {lead ? <div className="text-steel text-[14.5px] mt-1.5">{lead}</div> : null}
      </div>
      {right ? <div className="flex gap-2 flex-wrap">{right}</div> : null}
    </div>
  );
}

/**
 * Eyebrow — uppercase blue section label with trailing hairline (board .eyebrow).
 */
export function Eyebrow({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 text-[11px] font-semibold uppercase tracking-[1px] text-primary mt-[30px] mb-[13px]">
      <span className="flex-none">{children}</span>
      <span className="flex-1 h-px bg-hair2" />
    </div>
  );
}
