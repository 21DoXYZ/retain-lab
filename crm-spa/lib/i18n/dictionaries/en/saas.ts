/**
 * en · домен «saas» - Revenue Autopilot screens (leak-audit onward).
 */
import type { Messages } from "../ru";

export const saas: Partial<Messages> = {
  "nav.leakAudit": "Leak audit",

  "saas.leak.title": "Leak audit",
  "saas.leak.lead":
    "Where your subscription revenue is leaking right now - failed payments, dead trials, silent cancellations, missed upgrades.",
  "saas.leak.headline": "You are leaking ~{amount}/mo",
  "saas.leak.dunning": "Failed payments (dunning)",
  "saas.leak.dunningSub": "{count} users - MRR at risk right now",
  "saas.leak.silent": "Silent cancellations (30d)",
  "saas.leak.silentSub": "{count} left without a save attempt",
  "saas.leak.upgrades": "Missed upgrades",
  "saas.leak.upgradesSub": "{count} power users at plan limit",
  "saas.leak.deadTrials": "Dead trials",
  "saas.leak.deadTrialsSub": "{count} expired without paying - pipeline",

  "nav.uplift": "Campaign uplift",

  "saas.uplift.title": "Uplift report",
  "saas.uplift.lead":
    "Honest measurement: target vs holdout conversion per campaign - in incremental dollars.",
  "saas.uplift.total": "Incremental this period: {amount}",
  "saas.uplift.col.campaign": "Campaign",
  "saas.uplift.col.target": "Target",
  "saas.uplift.col.holdout": "Holdout",
  "saas.uplift.col.check": "Avg check",
  "saas.uplift.col.incremental": "Incremental",
  "saas.uplift.col.goal": "Goal",
  "saas.uplift.na": "n/a - empty holdout",
  "saas.uplift.groupN": "n={n}",
  "saas.uplift.empty.title": "No reports yet",
  "saas.uplift.empty.desc": "The first uplift report lands after a weekly campaign run (Mon 08:00).",

  "saas.home.tagline":
    "Revenue Autopilot watches every user, sends the right touch itself and honestly measures the incremental revenue. Start with the three screens below.",
  "saas.home.kpi.mrr": "MRR",
  "saas.home.kpi.leak": "Leaking per month",
  "saas.home.kpi.users": "Users tracked",
  "saas.home.kpi.atRisk": "At risk right now",
  "saas.home.kpi.atRiskSub": "dunning + cooling",
  "saas.home.start": "Start here",
  "saas.home.start.leak.title": "Where money leaks",
  "saas.home.start.leak.desc": "Failed payments, silent cancellations, dead trials - in dollars per month.",
  "saas.home.start.users.title": "Users & stages",
  "saas.home.start.users.desc": "Every user with a lifecycle stage and a recommended next action.",
  "saas.home.start.uplift.title": "What campaigns earned",
  "saas.home.start.uplift.desc": "Conversion vs the holdout group - honest incremental dollars.",
  "saas.home.machine": "Autopilot right now",
  "saas.home.machine.body":
    "{active} users in campaigns · {holdout} in holdout · {touches} touches in 7 days · dry-run mode (no emails leave until you enable autopilot)",
  "saas.home.setup": "Setup",
  "saas.home.setup.stripe": "Client Stripe",
  "saas.home.setup.stripe.on": "connected",
  "saas.home.setup.stripe.off": "demo data - waiting for keys",
  "saas.home.setup.snippet": "Site snippet",
  "saas.home.setup.snippet.on": "events flowing",
  "saas.home.setup.snippet.off": "not installed",
  "saas.home.setup.autopilot": "Autopilot",
  "saas.home.setup.autopilot.off": "dry-run (safe)",
  "saas.home.allSections": "All sections",

  "nav.saasOffers": "Offers",

  "saas.users.demoBanner": "This is a demo dataset (generated users to prove the pipeline). Live data replaces it automatically once the client's Stripe key is connected.",
  "saas.users.title": "Users",
  "saas.users.lead": "Every user: lifecycle stage, recommended action, value at stake and scores.",
  "saas.users.all": "All",
  "saas.users.col.user": "User",
  "saas.users.col.plan": "Plan",
  "saas.users.col.mrr": "MRR",
  "saas.users.col.stage": "Stage",
  "saas.users.col.action": "Action",
  "saas.users.col.atStake": "At stake",
  "saas.users.col.churn": "P(churn)",
  "saas.users.col.ltv": "LTV",
  "saas.users.col.lastSeen": "Last seen",
  "saas.users.empty.title": "No users yet",
  "saas.users.empty.desc": "Connect Stripe and the site snippet - users will appear here with stages and actions.",

  "saas.offers.title": "Offers",
  "saas.offers.lead": "The incentive catalog: what we give, how it executes, limits and issue counts. {pct}% holdout on every campaign.",
  "saas.offers.col.offer": "Offer",
  "saas.offers.col.executor": "Executor",
  "saas.offers.col.monetary": "Monetary",
  "saas.offers.col.cost": "COGS",
  "saas.offers.col.limit": "Limit/30d",
  "saas.offers.col.issued": "Issued",
  "saas.offers.col.holdout": "Holdout",
  "saas.offers.col.rejected": "Rejected",
  "saas.offers.yes": "yes",
  "saas.offers.no": "no",

  "saas.camp.title": "Campaigns",
  "saas.camp.lead": "What the autopilot sends your users: stage-driven chains, the exact copy of every touch, the goal and an honest holdout.",
  "saas.camp.autopilot": "Autopilot",
  "saas.camp.autopilot.on": "enabled",
  "saas.camp.autopilot.off": "dry-run",
  "saas.camp.autopilot.onDesc": "Touches actually reach users. The holdout group stays silent to measure incremental revenue.",
  "saas.camp.autopilot.offDesc": "Safe mode: chains run, but no touch leaves - log only. Holdout {pct}%.",
  "saas.camp.autopilot.enable": "Enable",
  "saas.camp.autopilot.confirm": "Confirm enable?",
  "saas.camp.autopilot.disable": "Disable",
  "saas.camp.goal": "Goal",
  "saas.camp.offer": "Offer",
  "saas.camp.enrolled": "Enrolled",
  "saas.camp.active": "Active",
  "saas.camp.holdout": "Holdout",
  "saas.camp.touches": "Touches",

  "nav.channelsSetup": "Channels",

  "saas.channels.title": "Channels",
  "saas.channels.lead":
    "Every touch goes out under your brand: email from your subdomain, SMS and Viber under your sender name, Telegram through your own bot. Infrastructure and delivery are on us.",
  "saas.channels.col.contacts": "Contacts",
  "saas.channels.col.consented": "Consented",

  "saas.channels.name.email": "Email",
  "saas.channels.name.sms": "SMS",
  "saas.channels.name.viber": "Viber",
  "saas.channels.name.telegram": "Telegram",
  "saas.channels.name.inapp": "In-app",
  "saas.channels.inapp.activeNote": "Banners show right inside your product via the installed snippet - the highest-converting channel for dunning. No extra setup.",
  "saas.channels.inapp.setupNote": "Activates automatically once the snippet is installed and users are identified (ra.identify).",
  "saas.channels.name.whatsapp": "WhatsApp",

  "saas.channels.state.active": "connected",
  "saas.channels.state.pending_dns": "waiting for DNS",
  "saas.channels.state.pending_approval": "registering",
  "saas.channels.state.awaiting_provider": "platform pending",
  "saas.channels.state.sender_needed": "set the sender",
  "saas.channels.state.not_connected": "not connected",
  "saas.channels.state.coming_soon": "coming soon",

  "saas.channels.copy": "Copy",
  "saas.channels.copied": "Copied",

  "saas.channels.email.domainLabel": "Sending subdomain",
  "saas.channels.email.domainHint":
    "A dedicated subdomain of your domain, e.g. mail.yourbrand.com - emails are signed with it, your main domain stays untouched.",
  "saas.channels.email.connect": "Connect",
  "saas.channels.email.awaitingNote":
    "Domain recorded. The platform is finishing email provider setup - DNS records will appear here.",
  "saas.channels.email.dnsLead":
    "Add these records to your domain's DNS, then press Check DNS. Propagation takes minutes to a couple of hours.",
  "saas.channels.email.dns.type": "Type",
  "saas.channels.email.dns.name": "Name",
  "saas.channels.email.dns.value": "Value",
  "saas.channels.email.check": "Check DNS",
  "saas.channels.email.verifiedNote":
    "Domain verified. Set the From name and address - every email will be sent from it.",
  "saas.channels.email.fromLabel": "From",
  "saas.channels.email.senderName": "Sender name",
  "saas.channels.email.saveSender": "Save sender",

  "saas.channels.msg.label": "Sender name",
  "saas.channels.msg.hint":
    "The alpha name recipients see instead of a number (latin letters/digits, up to 11 chars). We register it with the operator.",
  "saas.channels.msg.request": "Request",
  "saas.channels.msg.pendingNote":
    "The name is being registered with the operator - usually 1-3 business days. The channel activates automatically.",
  "saas.channels.msg.awaitingNote": "Name approved. The platform is finishing provider setup.",

  "saas.channels.tg.step1": "Open @BotFather in Telegram and create a bot with /newbot - use your product's name and avatar.",
  "saas.channels.tg.step2": "Copy the token from BotFather's reply.",
  "saas.channels.tg.step3": "Paste the token here - we validate the bot and start accepting subscriptions.",
  "saas.channels.tg.connect": "Connect bot",
  "saas.channels.tg.linkLead":
    "Give users this link (with their ID substituted) - pressing Start subscribes them with consent:",
  "saas.channels.tg.disconnect": "Disconnect",

  "saas.channels.wa.note":
    "WhatsApp Business requires Meta verification of your business (WABA). We run the onboarding - tell us when you need the channel.",

  "saas.channels.err.invalid_domain": "Invalid domain - expected something like mail.yourbrand.com.",
  "saas.channels.err.email_not_on_domain": "The address must be on your connected subdomain.",
  "saas.channels.err.no_domain": "Connect a sending subdomain first.",
  "saas.channels.err.telegram_invalid_token": "Telegram rejected the token - make sure it is copied in full.",
  "saas.channels.err.invalid_sms_sender": "Name: latin letters/digits, 2-11 chars.",
  "saas.channels.err.invalid_viber_sender": "Name: latin letters/digits, 2-11 chars.",
  "saas.channels.err.resend_not_configured": "The email provider is not set up by the platform yet.",
  "saas.channels.err.generic": "Something went wrong - try again.",
};
