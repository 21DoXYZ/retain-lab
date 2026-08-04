"""api/i18n_catalog.py — перевод бордовых КАТАЛОГОВ (метки + значения из SQL).

Борд авторен по-русски; SPA шлёт X-Locale (api/core.req_locale). Переводим на
ГРАНИЦЕ СЕРИАЛИЗАЦИИ по СЛОВАРЮ (ключ = точная русская строка) — это покрывает и
заголовки карточек, и подписи баров/донатов, которые вычисляются прямо в SQL
(multiIf('депозитор',...)), БЕЗ переписывания запросов.

Безопасность: неизвестная строка проходит как есть (рус. фолбэк) — покрытие
наращивается инкрементально, ничего не ломается. Реальные данные (коды
аффилиатов, URL, названия игр) в словаре отсутствуют → не трогаются.

`loc(text, locale)` — одна строка; `loc_deep(obj, locale)` — рекурсивно строковые
ЗНАЧЕНИЯ (ключи dict не трогаем). Применяется в api/*.py-эндпоинтах каталогов.
"""
from __future__ import annotations

from typing import Any

# ключ = русская строка; значение = {'en':..., 'tr':...}. Чисто числовые/₺-диапазоны
# ('≤50', '200-1000₺') языконезависимы — их не включаем.
TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── группы когорт ──
    'A · Время': {'en': 'A · Time', 'tr': 'A · Zaman'},
    'B · Канал': {'en': 'B · Channel', 'tr': 'B · Kanal'},
    'C · Деньги': {'en': 'C · Money', 'tr': 'C · Para'},
    'D · Вовлечённость': {'en': 'D · Engagement', 'tr': 'D · Katılım'},
    'E · Игра': {'en': 'E · Game', 'tr': 'E · Oyun'},
    'F · Цикл': {'en': 'F · Lifecycle', 'tr': 'F · Döngü'},
    'G · Композит': {'en': 'G · Composite', 'tr': 'G · Bileşik'},
    # ── заголовки карточек когорт ──
    'Регистрации по месяцам': {'en': 'Registrations by month', 'tr': 'Aylara göre kayıtlar'},
    'Когорта первой ставки': {'en': 'First-bet cohort', 'tr': 'İlk bahis kohortu'},
    'Депозиторы по месяцу FTD': {'en': 'Depositors by FTD month', 'tr': 'FTD ayına göre yatırımcılar'},
    'Возраст аккаунта': {'en': 'Account age', 'tr': 'Hesap yaşı'},
    'Скорость активации': {'en': 'Activation speed', 'tr': 'Aktivasyon hızı'},
    'Тип аффилиата': {'en': 'Affiliate type', 'tr': 'Ortak tipi'},
    'Топ аффилиатов': {'en': 'Top affiliates', 'tr': 'En iyi ortaklar'},
    'Топ источников': {'en': 'Top sources', 'tr': 'En iyi kaynaklar'},
    'Бонус-кампании': {'en': 'Bonus campaigns', 'tr': 'Bonus kampanyaları'},
    'Депозитор vs нет': {'en': 'Depositor vs not', 'tr': 'Yatırımcı mı değil mi'},
    'Тир FTD': {'en': 'FTD tier', 'tr': 'FTD kademesi'},
    'Кол-во депозитов': {'en': 'Deposits count', 'tr': 'Para yatırma sayısı'},
    'Способ оплаты': {'en': 'Payment method', 'tr': 'Ödeme yöntemi'},
    'Платёжное трение': {'en': 'Payment friction', 'tr': 'Ödeme sürtünmesi'},
    'Поведение выводов': {'en': 'Withdrawal behavior', 'tr': 'Para çekme davranışı'},
    'Состояние баланса': {'en': 'Balance state', 'tr': 'Bakiye durumu'},
    'Активных дней': {'en': 'Active days', 'tr': 'Aktif günler'},
    'Кол-во ставок': {'en': 'Bets count', 'tr': 'Bahis sayısı'},
    'Средняя ставка': {'en': 'Average bet', 'tr': 'Ortalama bahis'},
    'На свои или бонусы': {'en': 'Own money or bonuses', 'tr': 'Kendi parası mı bonus mu'},
    'Интенсивность': {'en': 'Intensity', 'tr': 'Yoğunluk'},
    'Время игры (час)': {'en': 'Play time (hour)', 'tr': 'Oyun saati'},
    'Разнообразие игр': {'en': 'Game variety', 'tr': 'Oyun çeşitliliği'},
    'Хиты vs нишевые': {'en': 'Hits vs niche', 'tr': 'Popüler vs niş'},
    'Провайдер': {'en': 'Provider', 'tr': 'Sağlayıcı'},
    'Топ-12 игр': {'en': 'Top-12 games', 'tr': 'En iyi 12 oyun'},
    'Recency-стадия': {'en': 'Recency stage', 'tr': 'Recency aşaması'},
    'Стадия активации': {'en': 'Activation stage', 'tr': 'Aktivasyon aşaması'},
    'Реактивация': {'en': 'Reactivation', 'tr': 'Yeniden aktivasyon'},
    'RFM-сегменты': {'en': 'RFM segments', 'tr': 'RFM segmentleri'},
    'Канал × удержание': {'en': 'Channel × retention', 'tr': 'Kanal × elde tutma'},
    # ── значения данных из SQL (подписи баров/донатов) ──
    '(нет)': {'en': '(none)', 'tr': '(yok)'},
    'нет': {'en': 'none', 'tr': 'yok'},
    'депозитор': {'en': 'depositor', 'tr': 'yatırımcı'},
    'не депозитор': {'en': 'non-depositor', 'tr': 'yatırımcı değil'},
    '≤7д': {'en': '≤7d', 'tr': '≤7g'},
    '8-30д': {'en': '8-30d', 'tr': '8-30g'},
    '31-90д': {'en': '31-90d', 'tr': '31-90g'},
    '91-180д': {'en': '91-180d', 'tr': '91-180g'},
    '180д+': {'en': '180d+', 'tr': '180g+'},
    'в день рег': {'en': 'reg day', 'tr': 'kayıt günü'},
    '1 день': {'en': '1 day', 'tr': '1 gün'},
    '2-7 дней': {'en': '2-7 days', 'tr': '2-7 gün'},
    '8+ дней': {'en': '8+ days', 'tr': '8+ gün'},
    'не пытался': {'en': 'not tried', 'tr': 'denemedi'},
    'без отказов': {'en': 'no rejects', 'tr': 'ret yok'},
    'много отказов': {'en': 'many rejects', 'tr': 'çok ret'},
    'были отказы': {'en': 'had rejects', 'tr': 'ret vardı'},
    'плюс >1k': {'en': 'plus >1k', 'tr': 'artı >1k'},
    'плюс 0-1k': {'en': 'plus 0-1k', 'tr': 'artı 0-1k'},
    'минус 0-1k': {'en': 'minus 0-1k', 'tr': 'eksi 0-1k'},
    'минус >1k': {'en': 'minus >1k', 'tr': 'eksi >1k'},
    'не выводил': {'en': 'no withdrawals', 'tr': 'çekmedi'},
    'вывод бонусов': {'en': 'bonus withdrawal', 'tr': 'bonus çekimi'},
    'вывел > внёс': {'en': 'withdrew > deposited', 'tr': 'çekti > yatırdı'},
    'вывел < внёс': {'en': 'withdrew < deposited', 'tr': 'çekti < yatırdı'},
    'кэш+бонус': {'en': 'cash+bonus', 'tr': 'nakit+bonus'},
    'только кэш': {'en': 'cash only', 'tr': 'sadece nakit'},
    'только бонус': {'en': 'bonus only', 'tr': 'sadece bonus'},
    'пусто': {'en': 'empty', 'tr': 'boş'},
    '2-3 дня': {'en': '2-3 days', 'tr': '2-3 gün'},
    '4-7 дн': {'en': '4-7 days', 'tr': '4-7 gün'},
    '8-30 дн': {'en': '8-30 days', 'tr': '8-30 gün'},
    '30+ дн': {'en': '30+ days', 'tr': '30+ gün'},
    'только бонусы': {'en': 'bonuses only', 'tr': 'sadece bonus'},
    'только реал': {'en': 'real only', 'tr': 'sadece gerçek'},
    'в осн. бонусы': {'en': 'mostly bonuses', 'tr': 'ağırlıklı bonus'},
    'в осн. реал': {'en': 'mostly real', 'tr': 'ağırlıklı gerçek'},
    '2k+ грайнд': {'en': '2k+ grind', 'tr': '2k+ grind'},
    '1 игра': {'en': '1 game', 'tr': '1 oyun'},
    'только нишевые': {'en': 'niche only', 'tr': 'sadece niş'},
    'только хиты': {'en': 'hits only', 'tr': 'sadece popüler'},
    'смешанно': {'en': 'mixed', 'tr': 'karışık'},
    'активен': {'en': 'active', 'tr': 'aktif'},
    'остывает': {'en': 'cooling', 'tr': 'soğuyor'},
    'под риском': {'en': 'at risk', 'tr': 'risk altında'},
    'спящий': {'en': 'dormant', 'tr': 'uykuda'},
    'отток': {'en': 'churn', 'tr': 'kayıp'},
    'играл': {'en': 'played', 'tr': 'oynadı'},
    'не активирован': {'en': 'not activated', 'tr': 'aktive değil'},
    'верн. 30д+': {'en': 'ret 30d+', 'tr': 'dönüş 30g+'},
    'верн. 14-30д': {'en': 'ret 14-30d', 'tr': 'dönüş 14-30g'},
    'без пауз': {'en': 'no gaps', 'tr': 'aralıksız'},
    '1k₺+ VIP': {'en': '1k₺+ VIP', 'tr': '1k₺+ VIP'},
    # ── RFM: смыслы/действия сегментов ──
    'недавно + часто + много': {'en': 'recent + frequent + high', 'tr': 'yakın + sık + yüksek'},
    'беречь, VIP-программа': {'en': 'protect, VIP program', 'tr': 'koru, VIP programı'},
    'стабильное ядро': {'en': 'stable core', 'tr': 'istikrarlı çekirdek'},
    'апсейл, удержание': {'en': 'upsell, retention', 'tr': 'üst satış, elde tutma'},
    'недавно, мало активности': {'en': 'recent, low activity', 'tr': 'yakın, düşük aktivite'},
    'онбординг': {'en': 'onboarding', 'tr': 'katılım'},
    'ценные, но пропали': {'en': 'valuable but gone', 'tr': 'değerli ama kayıp'},
    '🔴 срочно вернуть': {'en': '🔴 win back urgently', 'tr': '🔴 acilen geri kazan'},
    'были активны, уходят': {'en': 'were active, leaving', 'tr': 'aktifti, gidiyor'},
    'удержание сейчас': {'en': 'retention now', 'tr': 'şimdi elde tut'},
    'давно не играли': {'en': 'inactive for long', 'tr': 'uzun süredir oynamıyor'},
    'win-back или отпустить': {'en': 'win-back or let go', 'tr': 'geri kazan ya da bırak'},
    'средние': {'en': 'mid-tier', 'tr': 'orta seviye'},
    'реактивация': {'en': 'reactivation', 'tr': 'yeniden aktivasyon'},
    '⚪ Не играли (нет RFM)': {'en': '⚪ Never played (no RFM)', 'tr': '⚪ Hiç oynamadı (RFM yok)'},
    'зарегистрированы, но без ставок': {'en': 'registered, no bets', 'tr': 'kayıtlı, bahis yok'},
    'конверсия в игру / 1-й депозит': {'en': 'convert to play / 1st deposit', 'tr': 'oyuna dönüşüm / 1. yatırma'},
    # ── архетипы (персоны + описания) ──
    '🐋 Хайроллер': {'en': '🐋 High-roller', 'tr': '🐋 High-roller'},
    '⚙️ Грайндер': {'en': '⚙️ Grinder', 'tr': '⚙️ Grinder'},
    '🧭 Исследователь': {'en': '🧭 Explorer', 'tr': '🧭 Kaşif'},
    '📌 Моногам': {'en': '📌 Monogamist', 'tr': '📌 Tek oyuncu'},
    '🎁 Бонусник': {'en': '🎁 Bonus-hunter', 'tr': '🎁 Bonus avcısı'},
    '🦉 Ночной': {'en': '🦉 Night owl', 'tr': '🦉 Gece kuşu'},
    '🎰 Казуал': {'en': '🎰 Casual', 'tr': '🎰 Sıradan'},
    '💨 Разовый': {'en': '💨 One-time', 'tr': '💨 Tek seferlik'},
    '💤 Не играл': {'en': '💤 Never played', 'tr': '💤 Hiç oynamadı'},
    'крупные ставки (≥1000 ₺), почти все депозиторы': {'en': 'big bets (≥1000 ₺), almost all depositors', 'tr': 'büyük bahisler (≥1000 ₺), neredeyse hepsi yatırımcı'},
    'молотят объём — 300+ ставок в день, главная ценность': {'en': 'grind volume — 300+ bets/day, top value', 'tr': 'hacim üretir — günde 300+ bahis, en değerli'},
    'пробует много разных игр (10+)': {'en': 'tries many different games (10+)', 'tr': 'çok farklı oyun dener (10+)'},
    'залип на 1–2 играх, возвращается': {'en': 'stuck on 1–2 games, returns', 'tr': '1–2 oyuna takılı, geri döner'},
    'играет в основном на фриспины/бонусы': {'en': 'plays mostly on freespins/bonuses', 'tr': 'çoğunlukla freespin/bonus oynar'},
    'больше половины ставок — ночью': {'en': 'over half of bets at night', 'tr': 'bahislerin yarısından fazlası gece'},
    'нерегулярно, низкая интенсивность': {'en': 'irregular, low intensity', 'tr': 'düzensiz, düşük yoğunluk'},
    'один активный день — пришёл и ушёл': {'en': 'one active day — came and went', 'tr': 'bir aktif gün — geldi ve gitti'},
    'зарегистрировался, но не сделал ни ставки': {'en': 'registered but never bet', 'tr': 'kayıt oldu ama hiç bahis yapmadı'},
    # ── dist: разбор churn + мета ──
    '🟢 Активны + удерживаемы': {'en': '🟢 Active + retainable', 'tr': '🟢 Aktif + elde tutulabilir'},
    '≥2 дня, играл ≤30 дн': {'en': '≥2 days, played ≤30d', 'tr': '≥2 gün, ≤30g oynadı'},
    '← только эти и скорятся на churn': {'en': '← only these are churn-scored', 'tr': '← yalnızca bunlar churn skorlanır'},
    '🔴 Уже ушли': {'en': '🔴 Already gone', 'tr': '🔴 Zaten gitti'},
    'последняя ставка >30 дн назад': {'en': 'last bet >30d ago', 'tr': 'son bahis >30g önce'},
    'не «удерживать», а возвращать (winback)': {'en': 'not "retain" but win back', 'tr': '«elde tutma» değil, geri kazan (winback)'},
    '⚪ Никогда не играли': {'en': '⚪ Never played', 'tr': '⚪ Hiç oynamadı'},
    'нет ни одной ставки': {'en': 'no bets at all', 'tr': 'hiç bahis yok'},
    'удерживать нечего': {'en': 'nothing to retain', 'tr': 'elde tutacak yok'},
    '💨 Разовые': {'en': '💨 One-timers', 'tr': '💨 Tek seferlikler'},
    '1 активный день — пришёл-ушёл': {'en': '1 active day — came and went', 'tr': '1 aktif gün — geldi gitti'},
    'нечего удерживать (исключены по ML_PLAN)': {'en': 'nothing to retain (excluded per ML_PLAN)', 'tr': 'elde tutacak yok (ML_PLAN’a göre hariç)'},
    'Распределения': {'en': 'Distributions', 'tr': 'Dağılımlar'},
    'перцентили и концентрация': {'en': 'percentiles and concentration', 'tr': 'yüzdelikler ve yoğunlaşma'},
    # ── archetypes / funnel: мета и этапы ──
    'Архетипы игроков': {'en': 'Player archetypes', 'tr': 'Oyuncu arketipleri'},
    'похожие по поведению': {'en': 'similar by behavior', 'tr': 'davranışa göre benzer'},
    'Регистрация': {'en': 'Registration', 'tr': 'Kayıt'},
    'Играл хоть раз': {'en': 'Played at least once', 'tr': 'En az bir kez oynadı'},
    'Депозит': {'en': 'Deposit', 'tr': 'Yatırma'},
    'Депозит #1 (FTD)': {'en': 'Deposit #1 (FTD)', 'tr': 'Yatırma #1 (FTD)'},
    'Воронка депозитов': {'en': 'Deposit funnel', 'tr': 'Yatırma hunisi'},
    'где теряем': {'en': 'where we lose', 'tr': 'nerede kaybediyoruz'},
    # ── GGR: вкладки ──
    'Обзор': {'en': 'Overview', 'tr': 'Genel bakış'},
    'Провайдеры': {'en': 'Providers', 'tr': 'Sağlayıcılar'},
    'Игры': {'en': 'Games', 'tr': 'Oyunlar'},
    'Сегменты': {'en': 'Segments', 'tr': 'Segmentler'},
    'Бонусы и расходы': {'en': 'Bonuses & costs', 'tr': 'Bonuslar ve giderler'},
    'Ставки провайдеров': {'en': 'Provider rates', 'tr': 'Sağlayıcı oranları'},
    'Расчёты и выплаты': {'en': 'Settlements & payouts', 'tr': 'Mutabakat ve ödemeler'},
    'Отчёты и экспорт': {'en': 'Reports & export', 'tr': 'Raporlar ve dışa aktarma'},
    # ── GGR: сигналы (заголовки + шаблоны текста с {плейсхолдерами}) ──
    '⚠ Отрицательный GGR': {'en': '⚠ Negative GGR', 'tr': '⚠ Negatif GGR'},
    '🔺 Провайдеры с высоким RTP': {'en': '🔺 High-RTP providers', 'tr': '🔺 Yüksek RTP sağlayıcılar'},
    '🎁 Доля бонусов выше нормы': {'en': '🎁 Bonus share above norm', 'tr': '🎁 Bonus payı normun üstünde'},
    '{n} дн. с отрицательным GGR в периоде (игроки выиграли больше, чем поставили)': {
        'en': '{n} day(s) with negative GGR in the period (players won more than they staked)',
        'tr': 'dönemde {n} gün negatif GGR (oyuncular yatırdığından fazla kazandı)'},
    '{provs} — возврат игрокам выше 85%': {
        'en': '{provs} — payout to players above 85%', 'tr': '{provs} — oyunculara dönüş %85 üzeri'},
    'Расход на бонусы = {bratio}% от GGR (норма ≤ 12%)': {
        'en': 'Bonus spend = {bratio}% of GGR (norm ≤ 12%)',
        'tr': 'Bonus gideri = GGR’nin %{bratio}’i (norm ≤ %12)'},
    # ── GGR: поведенческие сегменты (hint) ──
    'Ставки > Выигрыши': {'en': 'Bets > Wins', 'tr': 'Bahisler > Kazançlar'},
    'Выигрыши > Ставки': {'en': 'Wins > Bets', 'tr': 'Kazançlar > Bahisler'},
    'есть бонус/бонусные ставки': {'en': 'has bonus/bonus bets', 'tr': 'bonus/bonus bahisleri var'},
    # ── GGR: типы бонусов (из SQL BT) ──
    '🎰 Фриспины': {'en': '🎰 Freespins', 'tr': '🎰 Freespinler'},
    '🎁 Бездепозитный': {'en': '🎁 No-deposit', 'tr': '🎁 Depozitosuz'},
    '💸 Кэшбэк': {'en': '💸 Cashback', 'tr': '💸 Cashback'},
    '💰 На депозит': {'en': '💰 On deposit', 'tr': '💰 Yatırıma'},
    '✋ Ручной бонус': {'en': '✋ Manual bonus', 'tr': '✋ Manuel bonus'},
    'Прочие': {'en': 'Other', 'tr': 'Diğer'},
    # ── GGR: waterfall (метки + примечания) ──
    'GGR — валовый доход': {'en': 'GGR — gross revenue', 'tr': 'GGR — brüt gelir'},
    '− Расход на бонусы': {'en': '− Bonus spend', 'tr': '− Bonus gideri'},
    '− Расход на провайдеров': {'en': '− Provider costs', 'tr': '− Sağlayıcı giderleri'},
    '− Расход на аффилиатов': {'en': '− Affiliate costs', 'tr': '− Ortak giderleri'},
    '= NGR — чистый доход': {'en': '= NGR — net revenue', 'tr': '= NGR — net gelir'},
    'Ставки − Выигрыши': {'en': 'Bets − Wins', 'tr': 'Bahisler − Kazançlar'},
    'начислено игрокам': {'en': 'awarded to players', 'tr': 'oyunculara verildi'},
    'остаётся казино': {'en': 'stays with casino', 'tr': 'kasada kalır'},
    # ── аудит списаний: категории (из SQL CAT) ──
    '🧪 тест-операции': {'en': '🧪 test operations', 'tr': '🧪 test işlemleri'},
    'лишний выигрыш (сверх лимита)': {'en': 'excess win (over limit)', 'tr': 'fazla kazanç (limit üstü)'},
    'истёкший бонус': {'en': 'expired bonus', 'tr': 'süresi dolmuş bonus'},
    'бонус без депозита': {'en': 'no-deposit bonus', 'tr': 'depozitosuz bonus'},
    'нарушение правил/промо': {'en': 'rules/promo violation', 'tr': 'kural/promo ihlali'},
    'нечестный выигрыш': {'en': 'unfair win', 'tr': 'haksız kazanç'},
    'прочее': {'en': 'other', 'tr': 'diğer'},
    '(без пометки)': {'en': '(unlabeled)', 'tr': '(etiketsiz)'},
    # ── retention-триангл ──
    'W0 = неделя первого депозита; далее — недели после неё': {
        'en': 'W0 = first-deposit week; then the weeks after it',
        'tr': 'W0 = ilk yatırma haftası; sonra takip eden haftalar'},
    '2-3': {'en': '2-3', 'tr': '2-3'},
    '4-7': {'en': '4-7', 'tr': '4-7'},
    '8-30': {'en': '8-30', 'tr': '8-30'},
    # ── конструктор сегментов: секции полей ──
    'События': {'en': 'Events', 'tr': 'Olaylar'},
    'Профиль': {'en': 'Profile', 'tr': 'Profil'},
    'Привлечение': {'en': 'Acquisition', 'tr': 'Kazanım'},
    'Депозиты': {'en': 'Deposits', 'tr': 'Para yatırma'},
    'Выводы': {'en': 'Withdrawals', 'tr': 'Para çekme'},
    'Финансы / риск': {'en': 'Finance / risk', 'tr': 'Finans / risk'},
    'Игра': {'en': 'Game', 'tr': 'Oyun'},
    'Спорт': {'en': 'Sports', 'tr': 'Spor'},
    'Бонусы и лояльность': {'en': 'Bonuses & loyalty', 'tr': 'Bonuslar ve sadakat'},
    'Жизненный цикл': {'en': 'Lifecycle', 'tr': 'Yaşam döngüsü'},
    'Предиктивные (ML)': {'en': 'Predictive (ML)', 'tr': 'Tahminsel (ML)'},
    'Коммуникации': {'en': 'Communications', 'tr': 'İletişim'},
    'Технические события': {'en': 'Technical events', 'tr': 'Teknik olaylar'},
    'Рефералка': {'en': 'Referrals', 'tr': 'Referanslar'},
    'Исключения / комплаенс': {'en': 'Exclusions / compliance', 'tr': 'Hariç tutma / uyum'},
    # ── мета каталога когорт ──
    'Все когорты': {'en': 'All cohorts', 'tr': 'Tüm kohortlar'},
    '36 срезов': {'en': '36 slices', 'tr': '36 kesit'},
    ('у разных срезов разный знаменатель: общие — по 39 010, '
     'денежные (депозиты/выводы) — только по игрокам с транзакциями (~31 837), '
     'игровые — по игравшим (~27 967). '
     'Сравнивать высоту баров между карточками напрямую нельзя.'): {
        'en': ('slices use different denominators: general — over 39,010, '
               'money (deposits/withdrawals) — only players with transactions (~31,837), '
               'game — only those who played (~27,967). '
               'Bar heights across cards are not directly comparable.'),
        'tr': ('kesitlerin paydası farklı: genel — 39.010 üzerinden, '
               'para (yatırma/çekme) — yalnızca işlemi olan oyuncular (~31.837), '
               'oyun — yalnızca oynayanlar (~27.967). '
               'Kartlar arası bar yükseklikleri doğrudan karşılaştırılamaz.')},
}


def loc(text: Any, locale: str) -> Any:
    """Перевод одной строки по словарю. 'ru'/не-строка/нет ключа → как есть."""
    if locale == 'ru' or not isinstance(text, str):
        return text
    entry = TRANSLATIONS.get(text)
    return entry.get(locale, text) if entry else text


def loc_deep(obj: Any, locale: str) -> Any:
    """Рекурсивно переводит строковые ЗНАЧЕНИЯ (ключи dict не трогаем)."""
    if locale == 'ru':
        return obj
    if isinstance(obj, str):
        return loc(obj, locale)
    if isinstance(obj, list):
        return [loc_deep(x, locale) for x in obj]
    if isinstance(obj, tuple):
        return tuple(loc_deep(x, locale) for x in obj)
    if isinstance(obj, dict):
        return {k: loc_deep(v, locale) for k, v in obj.items()}
    return obj
