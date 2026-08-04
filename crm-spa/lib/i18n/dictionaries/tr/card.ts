/**
 * tr · домен «card». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const card: Partial<Messages> = {
  // CardHeader.tsx
  "card.header.playerLabel": "Oyuncu",
  "card.header.noDeposit": "· para yatırma yok",
  "card.header.alsoWith": "ayrıca şununla:",
  "card.header.backToList": "← listeye dön",
  "card.header.kpi.bets": "Bahis",
  "card.header.kpi.turnover": "Ciro ₺",
  "card.header.kpi.net": "Net ₺",
  "card.header.kpi.ggr": "GGR ₺",
  "card.header.kpi.deposits": "Para yatırma",
  "card.header.kpi.recency": "Son aktivite",
  "card.header.daysShort": "{n}g",

  // CallBlock.tsx
  "card.call.title": "Arama",
  "card.call.phoneLabel": "Telefon:",
  "card.call.phoneHiddenHint": "(gizli — yalnızca arama düğmesiyle)",
  "card.call.phoneUnavailable": "Telefon rolünüz için görüntülenemiyor",
  "card.call.callButton": "📞 Ara",
  "card.call.todayHintLead": "Bugün saat {time}'te arayan",
  "card.call.todayHintTrail":
    "— {outcome}. Aynı oyuncuyu tekrar aramamak için önce kontrol edin.",
  "card.call.journalTitle": "Arama günlüğü",
  "card.call.emptyTitle": "Henüz arama yok",
  "card.call.emptyDescription": "Oyuncuyla iletişime geçmek için «Ara»ya tıklayın.",
  "card.call.confirmTitle": "Bugün zaten arandı",
  "card.call.confirmAnyway": "Yine de ara",
  "card.call.confirmLead": "Bu oyuncuyla bugün zaten temasa geçti:",
  "card.call.confirmTrail": "({outcome}). Tekrar aransın mı?",
  "card.call.confirmFallback": "Bu oyuncuyla bugün zaten temasa geçildi. Tekrar aransın mı?",
  "card.call.originateError": "Arama başlatılamadı.",
  "card.call.saveError": "Kaydetme hatası.",

  // access.ts — CallOutcome labels
  "card.outcome.answered": "Cevaplandı",
  "card.outcome.noAnswer": "Cevap yok",
  "card.outcome.busy": "Meşgul",
  "card.outcome.wrongNumber": "Yanlış numara",

  // access.ts — CallResult labels
  "card.result.interested": "İlgileniyor",
  "card.result.offerDeclined": "Teklif uygun değildi",
  "card.result.callbackRequested": "Geri aranmasını istedi",
  "card.result.refused": "Reddetti",

  // OutcomeModal.tsx
  "card.outcomeModal.title": "Arama sonucu",
  "card.outcomeModal.dialedNumber": "Aranan numara:",
  "card.outcomeModal.step1": "1. Arama nasıl geçti",
  "card.outcomeModal.step2": "2. Görüşme sonucu",
  "card.outcomeModal.noAnswerNote": "Oyuncu kuyrukta kalır — bir sonraki aramayı planlamanızı öneririz.",
  "card.outcomeModal.genericNote": "Sonuç günlüğe kaydedilecek.",

  // NotesBlock.tsx
  "card.notes.title": "📝 Notlar",
  "card.notes.hint": "oyuncu geçmişi — yazar adlarıyla",
  "card.notes.placeholder": "Ne konuşuldu, anlaşmalar, teklife tepki…",
  "card.notes.addButton": "Not ekle",
  "card.notes.emptyTitle": "Henüz not yok",
  "card.notes.emptyDescription": "Yukarıdan ilk notu ekleyin.",
  "card.notes.editedSuffix": " · düzenlendi",
  "card.notes.editButton": "Düzenle",
  "card.notes.deleteButton": "Sil",
  "card.notes.linkedOfferPrefix": "→ teklif:",
  "card.notes.tagLinkedOfferPrefix": "teklife bağlantı:",
  "card.notes.noActiveOffer": "aktif teklif belirlenmedi — etiket bağlantısız",
  "card.notes.emptyContent": "Not metnini girin.",
  "card.notes.editWindowExpired": "Düzenleme süresi (15 dakika) doldu.",

  // access.ts — NoteTag labels (chips)
  "card.tag.offerDeclined": "Teklif uygun değildi",
  "card.tag.otherOffer": "Başka teklif önerildi",
  "card.tag.callback": "Geri aranmasını istedi",
  "card.tag.negative": "Olumsuz",
  "card.tag.returned": "Geri döndü",

  // OfferBlock.tsx
  "card.offer.title": "✍️ Oyuncuya teklif",
  "card.offer.subtitle": "sistem önerdi — departman onaylar veya düzenler",
  "card.offer.notePlaceholder": "operatör notu (isteğe bağlı)",
  "card.offer.approveButton": "✅ Onayla",
  "card.offer.editButton": "✏️ Düzenlemeyi kaydet",
  "card.offer.sendButton": "📨 Gönder",
  "card.offer.declineButton": "❌ Reddet",
  "card.offer.savedSuffix": "{label} · karar kaydedildi",

  // RecommendationStrip.tsx
  "card.recommendation.title": "🎯 Önerilen aksiyon",
  "card.recommendation.subtitle": "teklif motoru · kime/ne zaman/hangi bonus",
  "card.recommendation.action": "Aksiyon",
  "card.recommendation.bonus": "Önerilen bonus",
  "card.recommendation.when": "Ne zaman",
  "card.recommendation.churnRisk": "Kayıp riski (30g)",
  "card.recommendation.secondDepositProb": "P(2. para yatırma, 30g)",
  "card.recommendation.priorityNote":
    "öncelik = değer × kayıp riski · teslim kanalı — veri yok",

  // ctx-momentum banner (board ctx, player_board.py:1435-1438; ±avg_bet*20 ölü bölge).
  "card.momentum.contextTitle": "🎯 Oyun bağlamı",
  "card.momentum.down":
    "🔻 Düşüşte (kayıp serisi / negatif son net) → şimdi kayıp bonusu / cashback uygun, oyuncu hüsrana kapılmadan.",
  "card.momentum.up":
    "🔺 Yükselişte (son zamanlarda kârda) → kazanç dalgasında para yatırmaya yönlendir ya da favori oyunda free spin.",
  "card.momentum.flat": "➖ Sabit seyir — ana teklifle devam edin.",

  // RecordingPlayer.tsx
  "card.recording.unavailable": "Kayıt kullanılamıyor.",
  "card.recording.playButton": "▶ Dinle",

  // ScheduleBlock.tsx
  "card.schedule.status.planned": "planlandı",
  "card.schedule.status.done": "tamamlandı",
  "card.schedule.status.overdue": "gecikti",
  "card.schedule.status.missed": "kaçırıldı",
  "card.schedule.title": "Sonraki aramayı planla",
  "card.schedule.nudgeHint": "Oyuncu cevap vermedi ve kuyrukta kalıyor — bir sonraki temas için plan yapın.",
  "card.schedule.suggestionPrefix": "Genelde aktif:",
  "card.schedule.applySuggestion": "Bu zaman dilimini kullan",
  "card.schedule.autoComment": "Oyuncu aktivitesine göre otomatik zaman dilimi",
  "card.schedule.missingDateTime": "Tarih ve saat belirtin.",
  "card.schedule.dateTimeAriaLabel": "Tarih ve saat",
  "card.schedule.commentPlaceholder": "Yorum (örn. «cuma akşamı uygun»)",
  "card.schedule.submitButton": "Planla",
  "card.schedule.upcomingTitle": "Planlanan temaslar",
  "card.schedule.emptyTitle": "Planlanmış arama yok",
  "card.schedule.bySystem": "sistem tarafından önerildi",
  "card.schedule.suggestionAround": "{day}, saat {hour}:00 civarı",

  // Shared across player-card blocks (author name / generic errors)
  "card.common.you": "Siz",
  "card.common.operatorFallback": "Operatör …{id}",
  "card.common.error": "Hata.",
  "card.common.loadError": "Veri yüklenemedi.",

  // data.ts — CardDataError copy
  "card.error.rlsDenied":
    "Yetersiz yetki: bu oyuncu sizin bölgenizde değil (size atanmadı). İşlem erişim politikası tarafından reddedildi.",
  "card.error.operationalLoadFailed": "Operasyonel veriler yüklenemedi.",
  "card.error.noteSaveFailed": "Not kaydedilemedi.",
  "card.error.noteEditFailed": "Not düzenlenemedi.",
  "card.error.noteDeleteFailed": "Not silinemedi.",
  "card.error.callOutcomeSaveFailed": "Arama sonucu kaydedilemedi.",
  "card.error.scheduleSaveFailed": "Arama planlanamadı.",
  "card.error.recordingNotFound": "Bu aramanın kaydı yok.",
  "card.error.recordingUnavailable": "Kayıt kullanılamıyor ({status}).",

  // ── KPI kutucuğu ipuçları (board SCARD_TIP, player_board.py:1305-1320) ─────
  "card.tip.scard.bets": "Bahis sayısı (bet + freespins_bet).",
  "card.tip.scard.turnover": "Ciro = Σ bahis.",
  "card.tip.scard.net": "Oyuncu net = kazançlar − bahisler. − = kaybetti (oyuncu bakışı).",
  "card.tip.scard.ggr": "Kasino GGR = bahisler − kazançlar = −net. Oyundan kasino geliri (bonuslardan önce).",
  "card.tip.scard.deposits": "Tamamlanan para yatırma sayısı.",
  "card.tip.scard.recency": "Son bahisten bu yana gün.",
  "card.tip.scard.tier": "1. hafta yatırımına göre kademe: A<1k · B<3k · C<10k · D≥10k.",
  "card.tip.scard.depWeek1": "FTD'den itibaren ilk 7 gündeki yatırımların Σ (LTV modeli özelliği).",
  "card.tip.scard.forecastD90": "1. hafta davranışına göre 90. güne kadar yatırım toplamının ML tahmini.",
  "card.tip.scard.rangeD90": "Kantil tahmini: P10–P90 — dürüst dağılım (balinalar).",
  "card.tip.scard.headroom": "Headroom = max(0, D90 tahmini − halihazırda yatırılan). 0 = tahmin zaten aşıldı.",
  "card.tip.scard.current": "Mevcut kademe = son yatırımın numarası.",
  "card.tip.scard.pNextPersonal": "Kişisel P(30 günde sonraki yatırım), ML (herhangi kademe).",
  "card.tip.scard.pNextBase": "Bu kademenin tüm tabandaki ortalama dönüşümü. Yalnızca #10'a kadar hesaplanır (sonrası «—»).",
  "card.tip.scard.target": "Sonraki kademe = yatırım #(N+1).",

  // ── Alan .fld ipuçları (board CARD_TIP, player_board.py:1254-1303) ─────────
  "card.tip.field.vip_level":
    "VIP seviyesi (kasino kuralları), TRY cinsinden kümülatif başarılı yatırımlara göre: Regular <100, Silver ≥100, Gold ≥50k, Platinum ≥150k, Diamond ≥500k, Royal ≥1M. ≥ Silver için en az bir yatırım ≥ 100 TRY gerekir.",
  "card.tip.field.account_type":
    "Hesap tipi. normal = gerçek oyuncu; test_or_service / service / blocked — gerçek değil (modellerde hariç tutulur).",
  "card.tip.field.status": "Kaynaktan hesap durumu.",
  "card.tip.field.country": "Ülke (country_iso_estimated'a göre tahmin).",
  "card.tip.field.reg_date": "Kayıt tarihi.",
  "card.tip.field.tenure_days": "Hesap yaşı = kayıttan bu yana gün.",
  "card.tip.field.affiliate_type": "Affiliate hesap tipi (classic vb.).",
  "card.tip.field.ftd_amount": "İlk yatırım tutarı (FTD).",
  "card.tip.field.balance": "Bakiye — dışa aktarma anındaki anlık görüntü (canlı değil).",
  "card.tip.field.bonus_balance": "Bonus bakiyesi — dışa aktarma anındaki anlık görüntü.",
  "card.tip.field.activity_status": "Kaynaktan aktivite durumu.",
  "card.tip.field.dep_count": "Tamamlanan yatırım sayısı (deposit + manual_deposit, status=completed).",
  "card.tip.field.dep_sum":
    "Yatırımlar manuel DAHİL (manual=bonus) — modeller için davranışsal alan. Gerçek nakit → «yatırdı (nakit)».",
  "card.tip.field.cash_deposits":
    "Nakit yatırımlar (kasino spec): type=deposit üzerinden Σ, başarılı. manual_deposit HARİÇ. Bord ile mutabık.",
  "card.tip.field.withdrawals_abs":
    "Çekimler (spec): type=withdrawal üzerinden Σ ABS(amount), başarılı. manual_withdrawal HARİÇ.",
  "card.tip.field.net_cash": "Net kasa = nakit yatırımlar − çekimler (kasino spec).",
  "card.tip.field.bonus_cost":
    "Bonus cost = bonus/manual_bonus/freespin üzerinden Σ ABS(amount) (başarılı, bonus_conversion hariç).",
  "card.tip.field.dep_failed": "Başarısız yatırım sayısı (rejected / failed).",
  "card.tip.field.wd_count": "Tamamlanan çekim sayısı.",
  "card.tip.field.wd_sum": "Tamamlanan çekimlerin toplamı = Σ amount.",
  "card.tip.field.wd_rejected": "Reddedilen çekim sayısı.",
  "card.tip.field.bonus_count": "Bonus tahsis sayısı.",
  "card.tip.field.bonus_sum": "Verilen bonusların toplamı.",
  "card.tip.field.primary_payment_method": "Birincil ödeme yöntemi (campaign etiketleri olmadan).",
  "card.tip.field.deposit_recency_days": "Son yatırımdan bu yana gün.",
  "card.tip.field.bets": "Bahis sayısı (bet + freespins_bet).",
  "card.tip.field.turnover": "Ciro = Σ bet_amount. Oyuncunun toplam yatırdığı bahis.",
  "card.tip.field.wins_sum": "Kazançlar = Σ win_amount. Oyuncunun oyunda kazandığı.",
  "card.tip.field.net": "Oyuncu net = kazançlar − bahisler. + kârda / − kaybetti (OYUNCU tarafından).",
  "card.tip.field.ggr": "Kasino GGR = bahisler − kazançlar = −net. Oyundan kasino geliri (bonuslar düşülmeden önce).",
  "card.tip.field.avg_bet": "Ortalama bahis = avg(bet_amount).",
  "card.tip.field.max_bet": "Maksimum bahis.",
  "card.tip.field.distinct_games": "Kaç farklı oyun = uniqExact(game_uuid).",
  "card.tip.field.active_days": "Oyun oynanan gün = uniqExact(bahis tarihi).",
  "card.tip.field.recency_days": "Son bahisten bu yana gün = dateDiff(son bahis, bugün).",
  "card.tip.field.primary_provider": "Bahis sayısına göre birincil sağlayıcı (agregatör).",
  "card.tip.field.freespin_ratio": "Free spin bahis oranı = freespins_bets / bets.",
  "card.tip.field.night_share": "Gece oyun oranı (İstanbul saatiyle < 6) = night_bets / bets.",
  "card.tip.field.bets_per_active_day": "Yoğunluk = bahis / aktif gün.",
  "card.tip.field.activation_lag_days": "Aktivasyon hızı = kayıt ile ilk bahis arası gün.",
  "card.tip.field.favourite_game": "En çok bahis yapılan oyun (ana oyun).",
  "card.tip.field.favourite_game_bets": "Ana oyundaki bahis sayısı.",
  "card.tip.field.game_concentration": "Konsantrasyon = ana oyundaki bahis oranı.",
  "card.tip.field.stuck_game": "Oyuncunun geri dönmesi en uzun süren oyun.",
  "card.tip.field.stuck_game_days": "Bu oyuna dönüşe kadar gün.",
  "card.tip.field.oneshot_games": "Tek günden sonra bırakılan oyun sayısı.",

  // Скрипт перед глазами при звонке (ScriptPeek)
  "card.call.scriptButton": "📋 Senaryo",

  // Рекомендация «когда звонить» (модуль анализа + retry-правило)
  "card.schedule.rec.retry": "{hours} sa sonra tekrar ara — geçen sefer ulaşılamadı",
  "card.schedule.rec.bestTime": "En iyi zaman: {day} ~{hour} (oyuncunun en aktif olduğu saat)",
  "card.schedule.rec.apply": "Kullan",
  "card.call.viaButtonOnly": "yalnızca düğmeyle arama (numara gizli)",
  // ── сессия 17.07: доперевод (карточка/vip-risk/аффилиаты/скрипты) ────────
  "card.momentum.liveLabel": "⚡ oyuncuda şu an ne oluyor — son oyun oturumlarının momentumu",
  "card.offer.hint": "Bu bir karar günlüğüdür: metin ve durum kaydedilir, sistem üzerine yazmaz. Canlı öneri yukarıda, «Önerilen aksiyon» bloğunda.",
  "card.offer.staleNotice": "⚠ Sistem şimdi başka bir şey öneriyor: «{name}»",
  "card.offer.useCurrent": "güncel öneriyi koy",

  "card.handoff.button": "WhatsApp ata",
  "card.handoff.title": "Oyuncuyu devret",
  "card.handoff.hint": "Oyuncu kime devredilsin (WhatsApp yöneticisi veya birim şefi). Oyuncu onun kuyruğuna geçer.",
  "card.handoff.pick": "— alıcı —",
  "card.handoff.cancel": "İptal",
  "card.handoff.confirm": "Devret",
  "card.handoff.done": "Devredildi: {name}",
};
