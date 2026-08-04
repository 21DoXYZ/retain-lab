/**
 * Design-system barrel — import UI primitives from a single path:
 *   import { SCard, DataTable, LifecycleBadge } from "@/components/ui";
 * All components derive from the tokens in app/globals.css and are 1:1 with
 * the live Flask dashboard. See /dev/ui for the full showcase.
 */

// Shell & layout
export { AppShell, PageHeader, Eyebrow } from "./AppShell";
export { NAV_GROUPS, canSee } from "./nav";
export type { NavItem, NavGroup } from "./nav";
export { Icon, hasIcon } from "./icons";
export type { IconName } from "./icons";

// Surfaces
export { Card, ChartBox, Panel, Banner, Field } from "./Card";
export { ModuleHeader } from "./ModuleHeader";
export type { ModuleHeaderKey } from "./ModuleHeader";
export { SCard, SCardGrid } from "./SCard";
export type { SCardVariant, ValueTone } from "./SCard";

// Badges / pills / chips
export {
  Badge,
  LifecycleBadge,
  AccountTypeBadge,
  ActionBadge,
  TierBadge,
  VipBadge,
  BeatsCasinoBadge,
} from "./Badge";
export * as badgeMaps from "./badges";
export { Pill, PillRow } from "./Pill";
export { Chip, ChipBar } from "./Chip";

// Data
export {
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  DataTable,
} from "./Table";
export type { Column, TableState } from "./Table";

// Forms & actions
export { Button } from "./Button";
export type { ButtonVariant, ButtonSize } from "./Button";
export { FormField, Input, Select, DateInput, Textarea } from "./FormField";
export { Tabs } from "./Tabs";
export type { TabItem } from "./Tabs";
export { Modal } from "./Modal";

// Access gate (для серверных page.tsx — переводимая ветка «нет доступа»)
export { AccessDenied } from "./AccessDenied";

// States
export { Skeleton, SkeletonText, Spinner, EmptyState, ErrorState } from "./States";

// Disclosure
export { Collapsible } from "./Collapsible";
