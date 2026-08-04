/**
 * tr · домен «ui». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const ui: Partial<Messages> = {
  "ui.empty.title": "Hiçbir şey bulunamadı",
  "ui.error.title": "Yüklenemedi",
  "ui.error.description": "Sayfayı yenilemeyi deneyin. Sorun devam ederse yöneticinize bildirin.",
  "ui.error.retry": "Tekrar dene",

  "ui.collapsible.expand": "genişletmek için tıkla ▾",
  "ui.collapsible.collapse": "daralt ▴",

  "ui.modal.close": "Kapat",

  "ui.cancel": "İptal",
  "ui.save": "Kaydet",

  "ui.badge.lifecycle.active": "aktif",
  "ui.badge.lifecycle.cooling": "soğuyor",
  "ui.badge.lifecycle.atRisk": "risk altında",
  "ui.badge.lifecycle.dormant": "uykuda",
  "ui.badge.lifecycle.churned": "kayıp",
  "ui.badge.lifecycle.never": "hiç oynamadı",
  "ui.badge.lifecycleTip.active": "Son 7 gün içinde bahis yaptı",
  "ui.badge.lifecycleTip.cooling": "Son bahis 8–30 gün önce",
  "ui.badge.lifecycleTip.atRisk": "Son bahis 31–60 gün önce",
  "ui.badge.lifecycleTip.dormant": "Son bahis 61–90 gün önce",
  "ui.badge.lifecycleTip.churned": "Son bahis 90 günden fazla önce",
  "ui.badge.lifecycleTip.never": "Hiç bahis yok",

  "ui.badge.accountType.service": "🛡 servis/admin",
  "ui.badge.accountType.testOrService": "🧪 test",
  "ui.badge.accountType.blocked": "⛔ engellendi",

  "ui.badge.tier.a": "A · <1k/hafta",
  "ui.badge.tier.b": "B · 1–3k",
  "ui.badge.tier.c": "C · 3–10k",
  "ui.badge.tier.d": "D · 10k+ 🐋",

  "ui.badge.beatsCasino.tooltip":
    "kazinoyu yeniyor: kasada ve oyunda artıda — bonus önerilmez",
  "ui.badge.beatsCasino.ariaLabel": "kazinoyu yeniyor",

  // app header (UserMenu)
  "ui.signOut": "Çıkış",

  // önerilen aksiyon rozeti (teklif motoru). Kod sabit, açıklama çevrilir.
  "ui.badge.action.SAVE": "SAVE · elde tut",
  "ui.badge.action.WINBACK": "WINBACK · geri kazan",
  "ui.badge.action.NUDGE": "NUDGE · 2. para yatırma",
  "ui.badge.action.CONVERT": "CONVERT · ilk para yatırma",
  "ui.badge.action.NURTURE": "NURTURE · büyüt",
  "ui.badge.action.MONITOR": "MONITOR · oyuncu artıda (inceleme)",
  "ui.badge.action.observe": "izle",
  "ui.freshness.badge": "veriler {ts} kadar",
  "ui.freshness.hint": "Veriler şu ana kadar yüklendi: para — {money}, oyun — {game}.",

};
