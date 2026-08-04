# REBUILD-TASK.md — Casino Retention CRM → Revenue Autopilot (SaaS preset)

**Read this file first. It is the execution plan for rebuilding this fork into Revenue Autopilot** — an automated revenue machine for subscription businesses (first tenant: Hub Content, a video-generation SaaS with subscriptions + tokens). This plan is based on a code audit of this exact repository (2026-08-04), not on assumptions.

Companion docs (product source of truth, in project knowledge base): `ТЗ-Revenue-Autopilot-SaaS-MVP.md` (product spec: stages, scoring, offers, campaigns), `Шпаргалка` (one-page reference). Where this file and the product spec conflict on engineering, this file wins; on product behavior, the spec wins.

---

## 0. Non-negotiable decisions (do not revisit)

1. **UI language: English only.** `en` becomes the default and the only shipped locale. The EN dictionary becomes the source of truth. RU/TR dictionaries: keep files in the repo but remove from `i18n/config.ts` supported locales and hide the LocaleSwitcher. Every screen name, button, label, tooltip, empty-state, and error message must read as native SaaS English (see terminology map, §3).
2. 7 user stages: `ACTIVATE / CONVERT / UPGRADE / SAVE / DUNNING / WINBACK / MONITOR`.
3. Every campaign runs with a 10% holdout (control group) — the existing `cityHash64(...) % 100 < control_pct` mechanism in `chains/runner.py` stays.
4. Offer hygiene: no monetary offers to users with high P(convert); max 1 monetary offer per user per 14 days.
5. MVP scoring = transparent heuristics (P_convert, P_churn, LTV_estimate, power_score) with data contracts compatible with future ML. Casino CatBoost models are NOT retrained now.
6. Casino modules are disabled via feature flags, never deleted.
7. Multi-tenant from day 1: `tenant_id` on every new table and every new API path. Tenant #1 = Hub Content.
8. No manual steps after tenant onboarding: no manual CSV loads, no hand-run training, no SSH cron babysitting. Everything scheduled or event-driven.

## 1. Verified ground truth (what exists in this repo)

- `chains/` — chain engine (runner 677 LOC): segment/event triggers, holdout, quiet hours 11:00–22:00 by user timezone, wait fixed/ml/event, conditions, desk tasks, goal attribution. **Fork as is; swap the vocabulary, not the engine.**
- `ingest/app.py` — HTTP event gateway → Kafka (Redpanda) → ClickHouse `live_events`; Bearer tokens, at-least-once. **Extend, don't rewrite.**
- `chains/senders.py` — unified `send()` interface: email (bare SMTP), telegram, `casino_webhook`, `bonus_grant` (POST to client callback). `bonus_grant` is the pattern for the SaaS token-credit executor.
- `chains/presets.py` — idempotent seeder of draft chains. **Reuse to seed campaigns K1–K5 per tenant.**
- `signals/rt_trigger.py` — near-real-time event reactions (~5s poll).
- `crm-spa/` — Next.js SPA, ~45 route screens; module hiding via `lib/modules.ts` (`STATIC_DISABLED` + `NEXT_PUBLIC_DISABLED_MODULES`); i18n in `lib/i18n/` (ru base / en / tr).
- `api/` — Flask REST (~12.8k LOC).
- Known gaps (confirmed): production data inflow was manual CSV; ML training is hand-run and unversioned; email is bare SMTP; there are TWO UIs — the legacy Flask dashboard (`player_board.py`) is ballast.

**Ballast — exclude from build, do not port, do not translate**: `player_board.py` + Flask dashboard screens, `call_analyzer/`, `tegsoft/`, `материалы все 2/`, `mico_docs/`, `sellrise_docs/`, `sellrise_internal/`, casino models `deposit_ladder_model.py`, `early_vip_model.py`, `vip_churn_model.py`, `non_promising_vip_model.py`, `BillionBahis_бонусы.md`.

## 2. SPA modules: keep / hide

**Hide via `lib/modules.ts`** (casino-specific): `games`, `ggr`, `vip-risk`, `affiliate`, `affiliates`, `call-analysis`, `verdicts`, `pool`, casino-specific parts of `audit`, `live` (casino live-momentum; revisit later).
**Keep (rename per §3)**: overview, players→users, desk, chains, segments, campaigns, bonuses→offers, cohorts, funnel, rfm, ltv, analytics, reports, queue, flags, keys, admin, calendar, channels, exports, glossary, formulas, schema, archetypes, dist, signals.
**Add (new screens)**: `leak-audit` (revenue leak report per tenant), `uplift` (weekly incremental-revenue report; may start as a section inside reports).

## 3. Terminology map (EN dictionary rewrite)

Apply across the EN i18n dictionary, API field names in NEW endpoints, and all user-facing text. Do not rename existing DB columns in this pass (create views/aliases instead) — UI and new APIs speak SaaS, storage migrates later.

| Casino term | Revenue Autopilot term |
|---|---|
| player | user |
| deposit | payment / first payment |
| redeposit | repeat payment / renewal |
| bonus | offer / reward |
| free spins | bonus tokens (tenant currency) |
| GGR / NGR | MRR / net revenue |
| wager / bets | usage / activity |
| VIP | power user |
| casino | workspace / tenant |
| retention department | revenue autopilot |
| deposit ladder | expansion path |
| balance | token balance |

Stage names in UI: Activate, Convert, Upgrade, Save, Dunning, Winback, Monitor (title case). Campaign names: `K1 Activation`, `K2 Trial Conversion`, `K3 Payment Recovery`, `K4 Save`, `K5 Upgrade`.

## 4. Phases (with acceptance criteria)

### Phase 0 — Boot & freeze (0.5–1 day)
Bring the stack up locally via docker-compose; SPA renders, chain-runner ticks, ingest accepts a test event end-to-end into ClickHouse. **Stop-gate: if the stack doesn't boot in a day, halt and report before any further work.**

### Phase 1 — Data pipeline (5–7 days, critical path)
1. **Stripe in**: tenant config stores a restricted/read-preferred Stripe key (encrypted at rest; Stripe Connect if feasible). One-time backfill: customers, subscriptions, invoices, charges → ClickHouse (`stripe_*` raw + `subscriptions`, `invoices`, `mrr_facts` marts). Webhook adapter: new Kafka topic `saas.events`; map `invoice.payment_failed`, `customer.subscription.*`, `checkout.session.*`, `charge.refunded` into the unified event schema.
2. **Site snippet**: one-line JS → new ingest endpoint; auto-events: `login`, `session_start`, `page_view` (pricing/cancel pages), plus custom events per the spec vocabulary (`generation_completed`, `tokens_low`, ...); carries `client_user_id` + email hash.
3. **Identity stitching** (top technical risk): `identities` table merging Stripe customer ↔ snippet `client_user_id` ↔ product API user, keyed by email (normalized) with explicit merge rules and an unmatched-queue. **Acceptance: on a test Stripe account + demo site, ≥95% of users stitch into a single identity automatically.**

### Phase 2 — Domain (3–4 days)
SaaS event vocabulary registered; heuristic scoring jobs (P_convert, P_churn, LTV_estimate, power_score) writing to `user_scores` with `scored_at`/`version`; 7-stage assignment in `user_actions` view per spec rules; DUNNING assignment is event-driven (immediate on `invoice.payment_failed`), the rest nightly. **Acceptance: every stitched user has exactly one stage and a recommended action.**

### Phase 3 — Offers & executors (3 days)
Offer catalog with capability levels: **Level C (Stripe-only, works for any tenant)**: coupon create+apply, `trial_end` extension, `pause_collection`, customer balance credit. **Level A (tenant currency)**: token credit via tenant callback (reuse `bonus_grant` sender pattern → rename `client_callback`). Hygiene rules implemented in `chains/checks.py` style: high-P(convert) exclusion, 14-day monetary cap. **Acceptance: each executor demonstrably fires against a test Stripe account and a mock callback.**

### Phase 4 — Campaigns & channels (3–4 days; domain warm-up runs in parallel from day 1)
Seed K1–K5 as draft chains via `presets.py` mechanism, per tenant. Email: replace bare SMTP with Resend or Postmark; DKIM/SPF on tenant subdomain; **start domain warm-up on the first day of Phase 1** — until warm-up completes, sends go only to an opt-in internal list. In-app widget: minimal embed (low-balance moment, pause-instead-of-cancel) served via the snippet. Telegram/WhatsApp capture: **out of MVP scope.** **Acceptance: K3 (payment recovery) runs fully automated on a test failed invoice: email sent via provider, card-update link works, holdout logged.**

### Phase 5 — UI (4–5 days)
EN-only locale switch (per §0.1) + full EN dictionary rewrite per §3; hide casino modules per §2; Leak Audit screen: per-tenant report — dunning losses, dead trials (expired, never paid, no touch), silent cancellations, under-upgrades; number headline: "you are leaking ~$X/mo". **Acceptance: click-through of every visible screen shows zero casino terminology and zero non-English strings.**

### Phase 6 — Measurement & ops (4–5 days)
Weekly uplift report: per campaign, target vs holdout conversion × average check → incremental $; emailed to tenant owner and rendered in `uplift` screen. Replace all hand-run steps with scheduled jobs (systemd timers or cron in compose). Draft-approval mode: first 14 days of a new tenant, chain sends require one-click approval; then full autopilot. **Acceptance = MVP Definition of Done below.**

## 5. Definition of Done (MVP)

On a test Stripe account + demo site with the snippet: a synthetic user goes through "sign-up → trial → failed payment". The system — with zero manual intervention after onboarding — stitches identity, assigns stages, enrolls into K2/K3 with 90/10 split, sends provider emails, applies a Stripe coupon, and one week later produces an uplift report with a non-empty holdout. All UI screens are English-only with SaaS terminology. Total: **22–29 working days**.

## 6. Engineering rules

- Feature flags over deletion; ballast stays untouched in-tree.
- `DRY_RUN` stays default-on for senders until Phase 4 acceptance.
- Secrets: tenant Stripe keys encrypted at rest, never logged; ingest keeps fail-closed auth.
- Every new table: `tenant_id`, `created_at`; every score/stage row: `version`, `computed_at`.
- Do not rename existing ClickHouse/Postgres columns in this pass; new views map old→new names.
- Commit per phase with the phase number in the message; report at every stop-gate.
