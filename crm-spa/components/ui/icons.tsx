import type { ReactNode } from "react";

/**
 * Line icons ported 1:1 from player_board.py ICONS (feather-style, 24x24,
 * stroke=currentColor). Keys match nav item keys. Items without a custom
 * icon fall back to their emoji in the nav data (as the board does).
 */
const PATHS: Record<string, ReactNode> = {
  overview: (
    <>
      <rect x="3" y="3" width="7" height="9" rx="1" />
      <rect x="14" y="3" width="7" height="5" rx="1" />
      <rect x="14" y="12" width="7" height="9" rx="1" />
      <rect x="3" y="16" width="7" height="5" rx="1" />
    </>
  ),
  players: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
    </>
  ),
  affiliates: (
    <>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
      <path d="M16 3.13a4 4 0 0 1 0 7.75" />
      <path d="M20 8v6M23 11h-6" />
    </>
  ),
  analytics: (
    <>
      <path d="M3 3v18h18" />
      <rect x="7" y="11" width="3" height="6" rx=".5" />
      <rect x="12" y="7" width="3" height="10" rx=".5" />
      <rect x="17" y="4" width="3" height="13" rx=".5" />
    </>
  ),
  ltv: (
    <>
      <path d="M6 3h12l4 6-10 12L2 9z" />
      <path d="M2 9h20M9 3 6 9l6 12 6-12-3-6" />
    </>
  ),
  dist: (
    <>
      <path d="M3 21V3" />
      <path d="M7 21v-6M11 21v-10M15 21v-7M19 21v-13" />
    </>
  ),
  funnel: <path d="M3 4h18l-7 8v7l-4-2v-5z" />,
  rfm: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1.2" fill="currentColor" />
    </>
  ),
  cohorts: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="3" width="7" height="7" rx="1" />
      <rect x="14" y="14" width="7" height="7" rx="1" />
      <rect x="3" y="14" width="7" height="7" rx="1" />
    </>
  ),
  archetypes: (
    <>
      <circle cx="6" cy="7" r="3" />
      <circle cx="18" cy="7" r="3" />
      <circle cx="12" cy="17" r="3" />
      <path d="M9 7h6M7.5 9.5 10.5 15M16.5 9.5 13.5 15" />
    </>
  ),
  games: (
    <>
      <rect x="2" y="6" width="20" height="12" rx="4" />
      <line x1="7" y1="12" x2="11" y2="12" />
      <line x1="9" y1="10" x2="9" y2="14" />
      <circle cx="16" cy="11" r="0.6" fill="currentColor" />
      <circle cx="18.5" cy="13.5" r="0.6" fill="currentColor" />
    </>
  ),
  schema: (
    <>
      <line x1="6" y1="3" x2="6" y2="15" />
      <circle cx="18" cy="6" r="3" />
      <circle cx="6" cy="18" r="3" />
      <path d="M18 9a9 9 0 0 1-9 9" />
    </>
  ),
  formulas: <path d="M18 4H7l7 8-7 8h11" />,
  glossary: (
    <>
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </>
  ),
  desk: (
    <>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M9 9v12" />
      <circle cx="6" cy="6" r="0.6" fill="currentColor" />
    </>
  ),
  live: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M5 12a7 7 0 0 1 14 0M2 12a10 10 0 0 1 20 0" />
    </>
  ),
  report: (
    <>
      <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
      <path d="M14 2v6h6M8 13h8M8 17h5" />
    </>
  ),
  actions: <path d="M13 2 3 14h7l-1 8 10-12h-7l1-8z" />,
  bonus: (
    <>
      <rect x="3" y="8" width="18" height="13" rx="1" />
      <path d="M3 12h18M12 8v13M12 8S9 3 6.5 4.5 9 8 12 8 15 6 14.5 4.5 12 8 12 8z" />
    </>
  ),
  campaigns: (
    <>
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="5" />
      <circle cx="12" cy="12" r="1" />
    </>
  ),
  cash: (
    <>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <line x1="2" y1="10" x2="22" y2="10" />
    </>
  ),
  risk: (
    <>
      <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>
  ),
};

export type IconName = keyof typeof PATHS;

export function hasIcon(name: string): name is IconName {
  return name in PATHS;
}

interface IconProps {
  name: string;
  size?: number;
  className?: string;
}

/** Renders a ported line icon by key. Returns null for unknown keys. */
export function Icon({ name, size = 19, className }: IconProps) {
  const path = PATHS[name];
  if (!path) return null;
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {path}
    </svg>
  );
}
