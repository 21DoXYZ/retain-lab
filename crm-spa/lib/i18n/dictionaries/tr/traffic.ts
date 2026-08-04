// "Kaynak kararları" ekranı + Trafik modülü "Kanallar" sekmesi (W2-T2/T5). Anahtarlar "traffic.*".
export const traffic = {
  // ── "Kaynak kararları" ekranı (W2-T2) ──
  "traffic.verdicts.title": "Kaynak kararları",
  "traffic.verdicts.lead":
    "5. gün kohort kalite tahmini: hangi kaynaklar değerli oyuncu, hangileri fraud getiriyor. Kaynak kararı — büyüt · izle · kapat.",
  "traffic.verdicts.pill.asOf": "veri tarihi {date}",
  "traffic.verdicts.pill.median": "medyan LTV D90: {v}",

  "traffic.verdicts.tab.source": "Kaynaklar",
  "traffic.verdicts.tab.affiliate": "Affiliate'ler",

  "traffic.verdicts.days.label": "Kohort penceresi",
  "traffic.verdicts.days.opt": "{n}g",

  // tablo sütunları (şartname §3.1)
  "traffic.verdicts.col.source": "Kaynak",
  "traffic.verdicts.col.affiliate": "Affiliate",
  "traffic.verdicts.col.players": "Oyuncu (7g)",
  "traffic.verdicts.col.playersTitle": "Penceredeki kayıtlar (parantez içinde — son 7 gün)",
  "traffic.verdicts.col.ftd": "FTD",
  "traffic.verdicts.col.ftdTitle": "İlk yatırımı yapan oyuncular",
  "traffic.verdicts.col.deposits": "Yatırımlar",
  "traffic.verdicts.col.depositsTitle": "Kohort yatırım toplamı (nakit, kazino şartnamesi)",
  "traffic.verdicts.col.predSum": "LTV D90 tahmini, Σ",
  "traffic.verdicts.col.predSumTitle": "Skorlanan oyuncular için toplam 90 günlük yatırım tahmini",
  "traffic.verdicts.col.predAvg": "oyuncu başına",
  "traffic.verdicts.col.predAvgTitle": "Skorlanan oyuncu başına ortalama LTV D90 tahmini",
  "traffic.verdicts.col.confidence": "Güven",
  "traffic.verdicts.col.verdict": "Karar",

  // kararlar
  "traffic.verdicts.verdict.scale": "büyüt",
  "traffic.verdicts.verdict.watch": "izle",
  "traffic.verdicts.verdict.disable": "kapat",
  "traffic.verdicts.verdict.maturing": "olgunlaşıyor · karar {n}g içinde",
  "traffic.verdicts.verdict.maturingSmall": "olgunlaşıyor · yetersiz veri",

  // güven
  "traffic.verdicts.conf.high": "yüksek",
  "traffic.verdicts.conf.mid": "orta",
  "traffic.verdicts.conf.low": "düşük",

  // açıklama / nasıl okunur
  "traffic.verdicts.legend.label": "Nasıl okunur:",
  "traffic.verdicts.legend.scale": "tahmin medyanın belirgin üstünde ve FTD oranı taban değerin altında değil — daha fazla ver",
  "traffic.verdicts.legend.watch": "normal aralıkta — izlemeye devam et",
  "traffic.verdicts.legend.disable": "oyuncular oyunları yeniyor (GGR < 0) veya tahmin medyanın yarısı — kapat",
  "traffic.verdicts.legend.maturing": "kohort 5 günden genç ya da 10 oyuncudan az — karar için erken",
  "traffic.verdicts.legend.draft": "Eşikler taslaktır — Vasiliy ile mutabakat gerekir.",

  // durumlar
  "traffic.verdicts.empty.title": "Pencerede yeni kayıt yok",
  "traffic.verdicts.empty.desc": "Seçilen pencerede kohort yok — aralığı genişletin veya yeni kayıtları bekleyin.",
  "traffic.verdicts.error.title": "Kararlar yüklenemedi",
  "traffic.verdicts.error.desc": "Analitik arka uç bağlantısını kontrol edip tekrar deneyin.",
} satisfies Record<string, string>;
