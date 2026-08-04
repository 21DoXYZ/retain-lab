/**
 * tr · домен «segmentation». Partial: пропущенный/пустой ключ рендерит ru-значение.
 *
 * Tam çeviri, taslak değil: müşteri operatörleri Türk, bu onlar için çalışma
 * dili (ТЗ п.7). RFM segment adları (Champions/Loyal/At-Risk/…) ve
 * archetype/cohort adları API'den veri olarak gelir — bu sözlükte yer almaz.
 */
import type { Messages } from "../ru";

export const segmentation: Partial<Messages> = {
  // ── /rfm ──────────────────────────────────────────────────────────────
  "segmentation.rfm.title": "RFM segmentleri",
  "segmentation.rfm.accent": "· Recency · Frequency · Monetary",
  "segmentation.rfm.lead":
    "3 değer ekseninde klasik segmentasyon · 1–5 kentil (Recency skoru ters: yakın zamanlı = 5) → adlandırılmış segmentler · geçmişe dayalı kural, ML değil",
  "segmentation.rfm.card.coverage.label": "RFM kapsamı",
  "segmentation.rfm.card.coverage.sub": "{base} normalden · {never} hiç oynamadı (bahis yok)",
  "segmentation.rfm.card.r.label": "R — Recency (yakınlık)",
  "segmentation.rfm.card.r.sub": "ne kadar önce oynadı · düşük = yüksek skor",
  "segmentation.rfm.card.f.label": "F — Frequency (sıklık)",
  "segmentation.rfm.card.f.sub": "aktif gün sayısı",
  "segmentation.rfm.card.m.label": "M — Monetary (parasal değer)",
  "segmentation.rfm.card.m.sub": "bahis cirosu",
  "segmentation.rfm.chart.title": "Segment büyüklükleri",
  "segmentation.rfm.chart.caption": "RFM segmentine göre oyuncu sayısı",
  "segmentation.rfm.col.segment": "Segment",
  "segmentation.rfm.col.players": "Oyuncu",
  "segmentation.rfm.col.pctBase": "Taban %",
  "segmentation.rfm.col.avgTurn": "Ort. ciro",
  "segmentation.rfm.col.avgRecency": "Ort. recency",
  "segmentation.rfm.col.avgRecencyTitle": "son bahisten bu yana gün sayısı",
  "segmentation.rfm.col.avgDays": "Ort. gün",
  "segmentation.rfm.col.avgDaysTitle": "aktif gün sayısı",
  "segmentation.rfm.col.meaning": "Ne anlama gelir",
  "segmentation.rfm.col.action": "Aksiyon",
  "segmentation.rfm.daySuffix": "g",
  "segmentation.rfm.banner.pre": "RFM, Monetary eksenini (ciro) gerektirdiği için yalnızca",
  "segmentation.rfm.banner.playedWord": "oynayanlar",
  "segmentation.rfm.banner.mid": " için hesaplanır; hiç bahis yapmayanlar aşağıda ayrı bir satırda",
  "segmentation.rfm.banner.convergeTo": " ({base} ile örtüşür)",
  "segmentation.rfm.banner.post":
    ". RFM genel tablo ve kampanyalar içindir; «kime ne verilir» konusunda kesin önceliklendirme için ",
  "segmentation.rfm.banner.deskLink": "Panel",
  "segmentation.rfm.banner.deskTail": " ekranındaki teklif motoruna bakın.",

  // ── /dist ─────────────────────────────────────────────────────────────
  "segmentation.dist.title": "Dağılımlar",
  "segmentation.dist.accent": "· yüzdelikler ve yoğunlaşma",
  "segmentation.dist.lead":
    "değer ve riskin ondalık/yüzdelik dilimlere göre dağılımı — yanıltıcı ortalama yerine yoğunlaşmayı görmek için (balinalar payın çoğunu tutar)",
  "segmentation.dist.card.top10.label": "İlk %10 elinde tutuyor",
  "segmentation.dist.card.top10.sub": "tüm tahmini LTV değerinin",
  "segmentation.dist.card.median.label": "Medyan depozito",
  "segmentation.dist.card.median.sub": "P90 {p90} · P99 {p99}",
  "segmentation.dist.card.max.label": "Maks. depozito",
  "segmentation.dist.card.max.sub": "aralık çok geniş",
  "segmentation.dist.ltvDeciles.title": "Tahmini LTV ondalık dilimleri",
  "segmentation.dist.ltvDeciles.note": "LTV tahmini olan {n} oyuncu (depozito yapanlar) üzerinden · D1 = ilk %10, D10 = alt",
  "segmentation.dist.col.decile": "Dilim",
  "segmentation.dist.col.players": "Oyuncu",
  "segmentation.dist.col.avgLtv": "Ort. LTV",
  "segmentation.dist.col.sum": "Toplam",
  "segmentation.dist.col.pctValue": "Toplam değerin %'si",
  "segmentation.dist.chart.title": "Değer yoğunlaşması",
  "segmentation.dist.chart.caption": "dilime göre toplam tahmini LTV değerinin %'si (D1 = ilk %10)",
  "segmentation.dist.ltvDeciles.help.pre": "📖 ",
  "segmentation.dist.ltvDeciles.help.b1": "Dilim",
  "segmentation.dist.ltvDeciles.help.mid": " = taban 10 eşit %10'luk gruba bölünür. ",
  "segmentation.dist.ltvDeciles.help.b2": "D1 = ilk %10",
  "segmentation.dist.ltvDeciles.help.post":
    " en değerli, D10 = en küçük. «Toplam değerin %'si» sütunu her grubun ne kadar para tuttuğunu gösterir — üst kısmın neredeyse her şeyi tuttuğu görülür (balinalarda yoğunlaşma).",
  "segmentation.dist.churnDeciles.title": "Kayıp riski dilimleri",
  "segmentation.dist.churnDeciles.note": "churn skoru olan {n} aktif oyuncu arasında (tüm taban değil)",
  "segmentation.dist.col.avgRisk": "Ort. risk",
  "segmentation.dist.col.range": "Aralık",
  "segmentation.dist.churnDeciles.help.pre": "📖 ",
  "segmentation.dist.churnDeciles.help.b1": "Nasıl okunur:",
  "segmentation.dist.churnDeciles.help.mid": " aktif oyuncular kayıp riskine göre 10 gruba ayrılır. ",
  "segmentation.dist.churnDeciles.help.b2": "D1 = en düşük risk",
  "segmentation.dist.churnDeciles.help.post":
    " (kalması olası), D10 = en yüksek (ayrılması olası). «Ort. risk» gruptaki ortalama kayıp olasılığıdır.",
  "segmentation.dist.churnWhy.title": "Churn neden tüm tabanda değil — geri kalanlar nerede",
  "segmentation.dist.col.group": "Grup",
  "segmentation.dist.col.whyWhat": "Neden / onlarla ne yapılmalı",
  "segmentation.dist.total": "Toplam",
  "segmentation.dist.wholeBaseNormal": "tüm normal taban",
  "segmentation.dist.churnWhy.help.pre":
    "churn riski yalnızca yaşayanlar için anlamlıdır: ayrılanları geri getir, hiç oynamayanları dönüştür, tek seferlikleri onboard et. İşte bunu ",
  "segmentation.dist.churnWhy.help.link": "Panel",
  "segmentation.dist.churnWhy.help.post": " ekranındaki motor yapar.",
  "segmentation.dist.depositPercentiles.title": "Depozito tutarı yüzdelikleri",
  "segmentation.dist.depositPercentiles.note": "{n} depozito yapan oyuncu üzerinden (dep_count>0)",
  "segmentation.dist.col.percentile": "Yüzdelik",
  "segmentation.dist.col.sumTry": "Tutar ₺",
  "segmentation.dist.banner.pre": "«P90 = 11.000» şu anlama gelir:",
  "segmentation.dist.banner.bold1": "depozito yapanların %90'ı 11.000 ₺'den az yatırdı",
  "segmentation.dist.banner.mid": ", ve yalnızca %10'u daha fazla yatırdı.",
  "segmentation.dist.banner.bold2": "P50 = medyan",
  "segmentation.dist.banner.post":
    "(tipik oyuncu). Üst dilim (P99) orantısız derecede fazlasını elinde tutar — bu yüzden «ortalama» yanıltıcıdır: balinalar onu yukarı çeker.",

  // ── /funnel ───────────────────────────────────────────────────────────
  "segmentation.funnel.title": "Depozito hunisi",
  "segmentation.funnel.accent": "· nerede kaybediyoruz",
  "segmentation.funnel.lead":
    "oyuncunun yolu: kayıt → oynadı → 1. depozito → #2 → … → #10 · en büyük düşüşün nerede olduğu «adım dönüşümü» sütununda görülür",
  "segmentation.funnel.col.stage": "Aşama",
  "segmentation.funnel.col.players": "Oyuncu",
  "segmentation.funnel.col.pctReg": "Kayıt %'si",
  "segmentation.funnel.col.stepConv": "Adım dönüşümü",
  "segmentation.funnel.col.funnelBar": "Huni",
  "segmentation.funnel.chart.title": "Huni",
  "segmentation.funnel.chart.caption": "her aşamadaki oyuncu payı",
  "segmentation.funnel.emptyTitle": "Huni verisi yok",

  // ── /cohorts ──────────────────────────────────────────────────────────
  "segmentation.cohorts.title": "Tüm kohortlar",
  "segmentation.cohorts.defaultSubtitle": "36 kesit",
  "segmentation.cohorts.lead":
    "tabanı gruplara ayırmanın tüm yolları — kampanyalar ve analiz için · panoda bir segmente tıklamak onun oyuncu listesini açar",
  "segmentation.cohorts.loading": "Kesitler yükleniyor…",
  "segmentation.cohorts.noData": "veri yok",
  "segmentation.cohorts.banner.asOf": "Veriler {date} tarihine ait.",
  "segmentation.cohorts.channelsMoved": "Kanal kesitleri taşındı → Kanallar",

  // ── /channels (W2-T5) — "B · Канал" grubu kesitleri, Trafik modülüne taşındı ─
  "segmentation.channels.title": "Kanallar: trafik kesitleri",
  "segmentation.channels.subtitle": "ortak tipi, en iyi kaynaklar, bonus kampanyaları",
  "segmentation.channels.lead":
    "Oyuncular nereden geliyor: ortaklar, kayıt kaynakları, bonus kampanyaları.",
  "segmentation.channels.empty.title": "Kanal kesiti yok",
  "segmentation.channels.empty.desc": "Geçerli veri anında «Kanal» grubu boş.",
  "segmentation.channels.error.desc": "Kanal kesitleri yüklenemedi.",

  // ── /archetypes ───────────────────────────────────────────────────────
  "segmentation.archetypes.title": "Oyuncu arketipleri",
  "segmentation.archetypes.accent": "· davranışa göre benzer",
  "segmentation.archetypes.lead.withCount": "{n} gerçek oyuncu, nasıl ve ne oynadıklarına göre arketiplere ayrıldı",
  "segmentation.archetypes.lead.fallback": "gerçek oyuncular nasıl ve ne oynadıklarına göre arketiplere ayrıldı",
  "segmentation.archetypes.stat.avgBet": "ort. bahis",
  "segmentation.archetypes.stat.activeDays": "akt. gün",
  "segmentation.archetypes.stat.games": "oyun",
  "segmentation.archetypes.stat.depositors": "depozito yapan",
  "segmentation.archetypes.stat.turnover": "ciro",
};
