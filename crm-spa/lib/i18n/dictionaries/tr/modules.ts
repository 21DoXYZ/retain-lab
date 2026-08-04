// TODO: тексты согласовать с Василием (оригинал — Retivo_модули_демо.html, недоступен)
/**
 * tr · домен «modules». Partial: пропущенный/пустой ключ рендерит ru-значение.
 */
import type { Messages } from "../ru";

export const modules: Partial<Messages> = {
  // ── sütun başlıkları ──────────────────────────────────────────────────
  "modules.header.about": "Bu ekran kimin için ve neden",
  "modules.header.chair": "Kimin derdi",
  "modules.header.pain": "Dert",
  "modules.header.action": "Bu ekrandaki aksiyon",

  // ── 1. Trafik ve affiliate ────────────────────────────────────────────
  "modules.traffic.chair": "Affiliate departmanı lideri / medya buyer",
  "modules.traffic.pain": "Bütçe nereye gidiyor: hangi kaynaklar oyuncu, hangileri fraud ve zarar getiriyor",
  "modules.traffic.action": "Kaynak için karar: ölçekle · izle · kapat",

  // ── 2. VIP radar ──────────────────────────────────────────────────────
  "modules.vip.chair": "VIP yöneticisi / retention lideri",
  "modules.vip.pain": "Balinalar kasanın aslan payını getiriyor ama sessizce kaybediliyor",
  "modules.vip.action": "Risk altındaki balinayı bul ve o gitmeden ilgilenmeye başla",

  // ── 3. Bonus ekonomisi ────────────────────────────────────────────────
  "modules.bonuseco.chair": "CMO / bonus yöneticisi",
  "modules.bonuseco.pain": "Bonuslar körlemesine dağıtılıyor: paraya ne döndüğü bilinmiyor",
  "modules.bonuseco.action": "Bonus P&L'ini gör ve geri dönmeyeni kapat",

  // ── 4. Risk ve fraud ──────────────────────────────────────────────────
  "modules.risk.chair": "Risk sorumlusu / finans",
  "modules.risk.pain": "Manuel silmeler, depozitsiz çekimler ve suistimal ancak sonradan ortaya çıkıyor",
  "modules.risk.action": "Bayrak akışını incele ve kayıplardan önce açıkları kapat",

  // ── 5. Retention otomasyonu (çekirdek) ────────────────────────────────
  "modules.core.chair": "Retention yöneticisi / çağrı merkezi",
  "modules.core.pain": "Oyuncular temaslar arasında kayboluyor: zamanında tutacak kimse ve araç yok",
  "modules.core.action": "Görev kuyruğunu al ve doğru oyuncuya şimdi nokta atışı dokun",

  // ── 6. Analitik ───────────────────────────────────────────────────────
  "modules.analytics.chair": "Ürün / yönetim",
  "modules.analytics.pain": "Rakamlar ekranlara dağılmış durumda, bütünün resmi yok",
  "modules.analytics.action": "Trendlerle karşılaştır ve huninin nerede sarktığını bul",

  // ── 7. Veri / API ─────────────────────────────────────────────────────
  "modules.data.chair": "Entegratör / casino tech lead",
  "modules.data.pain": "Sistemin hangi veriyi aldığı ve neyin eksik olduğu belirsiz",
  "modules.data.action": "Şemayı, anahtarları ve entegrasyon durumunu kontrol et",
} satisfies Partial<Messages>;
