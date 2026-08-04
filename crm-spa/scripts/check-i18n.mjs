#!/usr/bin/env node
/**
 * Проверка локалей: ключ есть во всех трёх языках и не содержит чужой язык.
 * Пункт приёмки из ТЗ по копирайту («в CI — проверка "ключ есть во всех трёх языках"»).
 *
 * Ловит два класса регрессий, которые видит живой клиент:
 *   1) ключ пропал в одном языке   -> пользователь видит сырой ключ или чужой текст;
 *   2) в русской локали кириллицы нет, а латиница/турецкий есть -> англ/тур текст в RU UI.
 *
 * Исключения (ALLOW_NO_CYRILLIC) — то, что по-русски и пишется латиницей:
 * бренды (Telegram, WhatsApp), аббревиатуры (VIP, RFM, GGR, NGR), единицы,
 * плейсхолдеры ({n} ₺) и имена языков в переключателе (они намеренно эндонимы).
 *
 * Запуск:  node scripts/check-i18n.mjs
 */
import { readdirSync, readFileSync, existsSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const BASE = join(ROOT, 'lib/i18n/dictionaries');
const LANGS = ['ru', 'en', 'tr'];

// Аббревиатуры и бренды, которые по-русски пишутся латиницей. Список важен:
// без него проверка кричит на GGR/VIP/ID и её начинают игнорировать.
const ABBR = new Set([
  'ggr','ngr','vip','rfm','ltv','id','cpa','rs','ftd','sd','arpu','net','roi','ml','ai',
  'email','telegram','whatsapp','clickhouse','csv','xlsx','api','sms','crm','kpi','uuid',
  'headroom','tier','a/b','b2b','usd','try','eur',
]);

// Ключи-исключения: там латиница уместна по смыслу.
const ALLOW = [
  /^calls\.transcript\.lang/,        // переключатель языка — эндонимы («Русский», «English»)
  /^automation\.chains\.channel\./,  // бренды каналов
  /^admin\.dept\./,
  /csvFile$/,                         // имена файлов выгрузки
  /\.col\.[a-z]/i,                    // короткие заголовки колонок
  /^segmentation\.rfm\.accent$/,      // расшифровка аббревиатуры RFM (Recency/Frequency/Monetary)
  /^reports\.field\.bonus_cost_ratio$/, // «Bonus cost» — канонический термин Василия (как GGR)
];

const CYR = /[А-Яа-яЁё]/;

/** Похоже ли на настоящую фразу на чужом языке (а не на ярлык/аббревиатуру). */
function looksForeignPhrase(v) {
  const words = v.match(/[A-Za-zğüşöçıİĞÜŞÖÇ]{3,}/g) || [];
  const meaningful = words.filter((w) => !ABBR.has(w.toLowerCase()));
  // фраза = два и более значимых латинских слова; либо явное имя поля БД (snake_case)
  return meaningful.length >= 2 || /[a-z]+_[a-z]+/.test(v);
}

function load(lang) {
  const out = {};
  const dir = join(BASE, lang);
  if (!existsSync(dir)) return out;
  for (const f of readdirSync(dir)) {
    const src = readFileSync(join(dir, f), 'utf8');
    const re = /["']([a-zA-Z0-9_.\-]+)["']\s*:\s*(`(?:[^`\\]|\\.)*`|"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g;
    let m;
    while ((m = re.exec(src))) out[m[1]] = { value: m[2].slice(1, -1), file: f };
  }
  return out;
}

const dict = Object.fromEntries(LANGS.map((l) => [l, load(l)]));
const all = new Set(LANGS.flatMap((l) => Object.keys(dict[l])));
const errors = [];

for (const key of all) {
  for (const lang of LANGS) {
    if (!dict[lang][key]) errors.push(`нет ключа в ${lang}: ${key}`);
  }
  const ru = dict.ru[key]?.value;
  if (ru && !CYR.test(ru) && looksForeignPhrase(ru) && !ALLOW.some((rx) => rx.test(key))) {
    errors.push(`русская локаль без кириллицы: ${key} = ${JSON.stringify(ru.slice(0, 60))}`);
  }
  const tr = dict.tr[key]?.value;
  if (tr && CYR.test(tr) && !ALLOW.some((rx) => rx.test(key))) {
    errors.push(`кириллица в турецкой локали: ${key} = ${JSON.stringify(tr.slice(0, 60))}`);
  }
}

console.log(`i18n: ${all.size} ключей × ${LANGS.length} языка`);
if (errors.length) {
  console.error(`\n✗ проблем: ${errors.length}\n`);
  errors.slice(0, 40).forEach((e) => console.error('  ' + e));
  if (errors.length > 40) console.error(`  … и ещё ${errors.length - 40}`);
  process.exit(1);
}
console.log('✓ все ключи на месте, чужого языка в локалях нет');
