"use client";

import type { ReactNode } from "react";
import { useState } from "react";
import { cn } from "@/lib/cn";

/**
 * Tabs — underline tab bar; active tab is primary blue (plan §4: active tabs
 * use --primary). Controlled (`value` + `onChange`) or uncontrolled
 * (`defaultValue`).
 */
export interface TabItem {
  key: string;
  label: ReactNode;
}

interface TabsProps {
  tabs: TabItem[];
  value?: string;
  defaultValue?: string;
  onChange?: (key: string) => void;
  className?: string;
}

export function Tabs({ tabs, value, defaultValue, onChange, className }: TabsProps) {
  const [internal, setInternal] = useState(defaultValue ?? tabs[0]?.key);
  const active = value ?? internal;

  function select(key: string) {
    if (value === undefined) setInternal(key);
    onChange?.(key);
  }

  return (
    <div className={cn("flex gap-1 border-b border-hair2 overflow-x-auto", className)} role="tablist">
      {tabs.map((tab) => {
        const on = tab.key === active;
        return (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={on}
            onClick={() => select(tab.key)}
            className={cn(
              "relative px-3.5 py-2.5 text-[13.5px] font-medium whitespace-nowrap -mb-px border-b-2 transition-colors cursor-pointer",
              on
                ? "text-primary border-primary"
                : "text-steel border-transparent hover:text-ink",
            )}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );
}
