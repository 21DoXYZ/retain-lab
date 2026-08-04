"use client";

import type {
  InputHTMLAttributes,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
  ReactNode,
} from "react";
import { cn } from "@/lib/cn";

/**
 * Form controls — board input/select styling: 42px tall, 8px radius, hair3
 * border, 2px primary focus ring. FormField wraps a control with a label,
 * optional hint and error message.
 */

const CONTROL =
  "w-full bg-canvas text-ink border border-hair3 rounded-ctl px-3 text-[13.5px] " +
  "outline-none focus:border-2 focus:border-primary placeholder:text-stone " +
  "disabled:opacity-60 disabled:cursor-not-allowed";

const CONTROL_H = "h-[42px]";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input className={cn(CONTROL, CONTROL_H, className)} {...rest} />;
}

/** Date picker input (board uses native type=date). */
export function DateInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input type="date" className={cn(CONTROL, CONTROL_H, className)} {...rest} />;
}

export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cn(CONTROL, CONTROL_H, "pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea className={cn(CONTROL, "py-2.5 min-h-[84px] resize-y", className)} {...rest} />;
}

interface FormFieldProps {
  label?: ReactNode;
  htmlFor?: string;
  hint?: ReactNode;
  error?: ReactNode;
  required?: boolean;
  children: ReactNode;
  className?: string;
}

export function FormField({
  label,
  htmlFor,
  hint,
  error,
  required,
  children,
  className,
}: FormFieldProps) {
  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      {label ? (
        <label htmlFor={htmlFor} className="text-[12.5px] font-medium text-slate">
          {label}
          {required ? <span className="text-neg ml-0.5">*</span> : null}
        </label>
      ) : null}
      {children}
      {error ? (
        <span className="text-[12px] text-neg">{error}</span>
      ) : hint ? (
        <span className="text-[12px] text-steel">{hint}</span>
      ) : null}
    </div>
  );
}
