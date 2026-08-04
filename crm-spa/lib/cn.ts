/**
 * Minimal className joiner (no runtime deps).
 * Filters out falsy values so conditional classes stay readable:
 *   cn("base", isActive && "on", disabled ? "opacity-50" : null)
 */
export type ClassValue = string | number | false | null | undefined;

export function cn(...values: ClassValue[]): string {
  return values.filter(Boolean).join(" ");
}
