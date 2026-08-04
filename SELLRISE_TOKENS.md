# Дизайн-токены Sellrise (референс для дашборда)

> Извлечено из `Sellrise-Front-End` (Tailwind CSS, отдельный сторонний репозиторий
> github.com/YanuarN/Sellrise-Front-End — в наш git НЕ включён). Здесь — только токены
> дизайна, которым следует дашборд (`player_board.py`). Палитра дашборда им соответствует 1:1.

## Палитра

| Роль | Tailwind | HEX | Переменная в борде |
|---|---|---|---|
| **Primary (CTA, ссылки)** | `blue-600` | `#2563eb` | `--primary` |
| Primary hover/dark | `blue-700` | `#1d4ed8` | `--primary-d` |
| Primary light | `blue-500` | `#3b82f6` | `--sun5` |
| Accent-фон | `blue-50` | `#eff6ff` | `--cream` |
| Accent-рамка | `blue-100` | `#dbeafe` | `--beige` |
| Поверхность (app bg) | `slate-50` | `#f8fafc` | `--surface` |
| Карточки | `white` | `#ffffff` | `--canvas` |
| Текст основной | `slate-800` | `#1e293b` | `--ink` |
| Текст вторичный | `slate-700` | `#334155` | `--slate` |
| Текст приглушённый | `slate-500` | `#64748b` | `--steel` |
| Текст тихий | `slate-400` | `#94a3b8` | `--stone` / `--muted` |
| Рамка тонкая | `slate-100` | `#f1f5f9` | `--hair` |
| Рамка | `gray-200` | `#e5e7eb` | `--hair2` |
| Позитив | `green-700` | `#15803d` (борд: `#1f9d57`) | `.pos` |
| Негатив | `red-600` | `#dc2626` | `.neg` |

## Типографика

- **Основной шрифт:** системный sans (Tailwind `font-sans`):
  `-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif`
- **Моноширинный** (числа/ID): системный mono (Tailwind `font-mono`):
  `ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace`
- Никаких веб-шрифтов (Inter/Fraunces убраны) — как в Sellrise, всё системное (быстро, офлайн).

## Компоненты

- **Карточка:** `background:#fff` · `border:1px solid #e2e8f0` (slate-200) · `border-radius:12px`
  (Tailwind `rounded-xl`) · тень `0 10px 30px rgba(0,0,0,.12)`.
- **Радиусы:** карточки 12px · кнопки/инпуты 8px · пилюли 999px.
- **Кнопка primary:** фон `#2563eb`, текст белый, radius 8px.

## Статус соответствия

✅ Цвета, карточки, радиусы дашборда **уже совпадают** с Sellrise (1:1).
✅ Шрифты переведены на системные (как в Sellrise) — `player_board.py`, коммит со ссылкой на этот файл.
