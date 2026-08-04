"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/cn";
import { useT } from "@/lib/i18n";

/**
 * Modal — centered dialog over a dimmed backdrop. Card surface (12px radius),
 * Esc-to-close, click-outside-to-close, scroll-locked body. Portaled to
 * document.body (guarded for SSR).
 */
interface ModalProps {
  open: boolean;
  onClose: () => void;
  title?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  /** Tailwind max-width class for the panel (default max-w-lg). */
  widthClass?: string;
}

export function Modal({ open, onClose, title, children, footer, widthClass = "max-w-lg" }: ModalProps) {
  const t = useT();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [open, onClose]);

  if (!open || !mounted) return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-label={typeof title === "string" ? title : undefined}
      // React проводит события портала по ДЕРЕВУ КОМПОНЕНТОВ, а не по DOM:
      // без этого клик в модалке, отрендеренной внутри кликабельной строки
      // (getRowHref/onClick), всплывает до неё и навигирует. Модалка не должна
      // протекать в onClick предка — гасим здесь, для всех использований.
      onClick={(e) => e.stopPropagation()}
    >
      <div
        className="absolute inset-0 bg-ink/40"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className={cn(
          "relative w-full bg-canvas rounded-card border border-hair2 shadow-2xl flex flex-col max-h-[90vh]",
          widthClass,
        )}
      >
        {title ? (
          <div className="flex items-center justify-between gap-4 px-5 py-4 border-b border-hair">
            <h2 className="text-[16px] font-semibold text-ink">{title}</h2>
            <button
              type="button"
              onClick={onClose}
              aria-label={t("ui.modal.close")}
              className="text-steel hover:text-ink text-xl leading-none cursor-pointer"
            >
              ×
            </button>
          </div>
        ) : null}
        <div className="px-5 py-4 overflow-auto text-[13.5px] text-slate">{children}</div>
        {footer ? (
          <div className="flex justify-end gap-2 px-5 py-4 border-t border-hair">{footer}</div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
