// Risk ve dolandırıcılık modülünün «Bayrak akışı» ekranı (W2-T3). Anahtarlar "risk.*". tr — ru çevirisi.
export const risk = {
  "risk.flags.title": "Bayrak akışı",
  "risk.flags.lead": "Tek bir «inceleme gerekiyor» kuyruğu — denetim, ortaklar ve bonuslardan gelen sinyaller tek listede.",

  // Başlık rozetleri
  "risk.flags.pill.total": "{n} incelemede",
  "risk.flags.pill.checked": "{mins} dk önce kontrol edildi",
  "risk.flags.pill.checkedNow": "az önce kontrol edildi",

  // Tür kutucukları (tıklama = akışı filtrele)
  "risk.flags.tile.hint": "Tıkla — akışı bu türe göre filtrele",
  "risk.flags.tile.active": "filtre etkin",
  "risk.flags.kind.no_deposit_withdrawal.label": "Yatırımsız çekim",
  "risk.flags.kind.no_deposit_withdrawal.sub": "çekimin < %10 yatırımıyla > 50k ₺ manuel borç",
  "risk.flags.kind.suspicious_operator.label": "Şüpheli operatör",
  "risk.flags.kind.suspicious_operator.sub": "borçların ≥ %40'ı net bir not olmadan",
  "risk.flags.kind.affiliate_players_win.label": "Oyuncular oyunları yeniyor",
  "risk.flags.kind.affiliate_cash_drain.label": "Kasa ekside",
  "risk.flags.kind.affiliate_players_win.sub": "kaynağın gerçek GGR'si negatif",
  "risk.flags.kind.affiliate_cash_drain.sub": "çekimler yatırımları aşıyor",
  "risk.flags.kind.bonus_abuse.label": "Bonus suistimali",
  "risk.flags.kind.bonus_abuse.sub": "freespinlerde kârda olan «🎁 Bonusçu» arketipi",

  // Tablo sütunları
  "risk.flags.col.kind": "Tür",
  "risk.flags.col.entity": "Varlık",
  "risk.flags.col.amount": "Tutar ₺",
  "risk.flags.col.severity": "Önem",
  "risk.flags.col.details": "Ayrıntılar",

  // Varlıklar (kart bağlantıları)
  "risk.flags.entity.player": "Oyuncu #{id}",
  "risk.flags.entity.operator": "Operatör {id}",
  "risk.flags.entity.affiliate": "Kaynak {id}",

  // Türe göre satır ayrıntıları
  "risk.flags.details.no_deposit_withdrawal": "{deposited} ₺ yatırıldı · {ops} işlem",
  "risk.flags.details.suspicious_operator": "belirsiz %{unclear} · {ops} işlem",
  "risk.flags.details.adminBadge": "yönetici/servis",
  "risk.flags.details.affiliate": "{players} oyuncu · FTD {ftd}",
  "risk.flags.details.bonus_abuse": "freespin %{freespin}",

  // Önem (severity)
  "risk.flags.sev.3": "büyük (≥ 100k ₺)",
  "risk.flags.sev.2": "kayda değer (≥ 20k ₺)",
  "risk.flags.sev.1": "küçük",

  // Filtre
  "risk.flags.filter.reset": "Filtreyi sıfırla",

  // Açıklama afişi
  "risk.flags.banner.severity": "Önem: 🔴 büyük (≥ 100k ₺) · 🟡 kayda değer (≥ 20k ₺) · ⚪ küçük.",
  "risk.flags.banner.sources": "Kaynaklar: borç denetimi, ortak kararları, «Bonusçu» arketipi. Akışı filtrelemek için bir kutucuğa tıklayın.",

  // Boş «her şey temiz» (TŞ §4.1) + filtreye göre boş
  "risk.flags.empty.clear.title": "Bayrak yok — her şey temiz",
  "risk.flags.empty.clear.desc": "İncelenecek bir şey yok. Son kontrol {mins} dk önce.",
  "risk.flags.empty.clear.descNow": "İncelenecek bir şey yok. Son kontrol az önce.",
  "risk.flags.empty.kind.title": "Bu türde bayrak yok",
  "risk.flags.empty.kind.desc": "Seçilen tür için şu anda boş. Geri kalanı görmek için filtreyi sıfırlayın.",

  // Rota durumları (loading / error)
  "risk.flags.loading.lead": "İncelenecek sinyaller toplanıyor…",
  "risk.flags.error.title": "Bayrak akışı yüklenemedi",
  "risk.flags.error.desc": "Bağlantıyı kontrol edip tekrar deneyin.",
} satisfies Record<string, string>;
