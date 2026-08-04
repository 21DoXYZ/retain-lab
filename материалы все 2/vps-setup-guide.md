# Claude Code + VPS на Beget: домен, сервер, деплой

> **Что получите:** свой проект работает на собственном домене с HTTPS, обновляется при каждом `git push`.
>
> **Длительность:** 60–90 минут
> **Уровень:** начинающий
> **Главный инструмент:** Claude Code (расширение от Anthropic для VS Code)

---

## Зачем свой VPS

**VPS** = чужой компьютер в дата-центре, который вы арендуете за ~11 ₽/день. Включён 24/7, у него белый IP, ставьте что угодно: сайты, ботов, базы данных.

Vercel/Netlify хороши, пока не появилось:
- персональные данные пользователей из РФ (152-ФЗ обязывает хранить в РФ)
- свои базы и долгоживущие процессы
- задачи, которые крутятся дёшево и без лимитов

Beget — российский хостер, дата-центр в СПб. Проходит под закон + дешевле зарубежных.

---

## Что вам понадобится

- **VS Code**
- **Расширение Claude Code** — [Marketplace](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code), установлено и авторизовано
- **GitHub MCP** подключён в Claude Code (если ещё нет — отдельный гид)
- **Аккаунт [beget.com](https://beget.com)**, баланс ~500 ₽
- **Аккаунт GitHub**
- **Любой проект**, который хотите задеплоить (статика, лендинг, Next.js, Astro, Vite — что угодно)

---

## Раздел 0: Покупка домена

> **Делаем первым шагом** — регистрация занимает 1–3 часа, пока настраиваем сервер, домен дойдёт.

1. [beget.com](https://beget.com) → раздел **Домены** → **Регистрация домена**
2. Введите желаемое имя (например, `mysite.ru`). Beget проверит, свободно ли
3. Цена ~199 ₽/год
4. Заполните паспортные данные (требование .ru-зон)
5. **Зарегистрировать**

Дальше параллельно настраиваем VPS — пока возитесь, домен прорегистрируется.

> 💡 **Альтернатива:** Cloudflare Registrar — в 2-3 раза дешевле, но регистрация в US-юрисдикции. Подходит, если домен **не** связан с обработкой ПД из РФ.

---

## Раздел 1: Покупка VPS на Beget

### 1.1 Облако → Виртуальный сервер
Beget → **Облако** → **Создать сервис** → **Виртуальные серверы**.

### 1.2 Конфигурация
- **Тариф:** 1 ядро / 1 GB / 10 GB SSD за ~11 ₽/день — для урока хватит
- **ОС:** Ubuntu 24.04 LTS — стандартная Linux, под неё рассчитаны 90% туториалов

> Списание посуточное. После урока удалите VPS, если не нужен.

### 1.3 Создаём SSH-ключ локально

**SSH-ключ** = пара "замок + ключ":
- Публичный (`*.pub`) — кладём на сервер. Можно показывать кому угодно.
- Приватный — держим у себя. Никому.

Откройте терминал в VS Code (`Ctrl+~` Windows / `Cmd+~` Mac):

**Mac / Linux:**
```bash
ssh-keygen -t ed25519 -C "beget-vps" -f ~/.ssh/beget_vps
```

**Windows (PowerShell):**
```powershell
ssh-keygen -t ed25519 -C "beget-vps" -f "$env:USERPROFILE\.ssh\beget_vps"
```

Passphrase — Enter (без пароля).

> Имя `beget_vps` произвольное, но команды дальше используют его. Хотите своё — подменяйте везде.

Получите два файла:
- `beget_vps` — приватный, многострочный с `BEGIN/END PRIVATE KEY`
- `beget_vps.pub` — публичный, одна строка `ssh-ed25519 AAAA... beget-vps`

> 💡 **Альтернатива:** 1Password / Bitwarden SSH Agent — приватные ключи в менеджере паролей, синхронизация между устройствами.

### 1.4 Добавляем ключ в Beget

Покажите содержимое публичного ключа:

**Mac / Linux:** `cat ~/.ssh/beget_vps.pub`
**Windows:** `Get-Content "$env:USERPROFILE\.ssh\beget_vps.pub"`

Скопируйте строку.

В форме создания VPS, блок **Аутентификация**:
1. Карандашик у поля **Пароль** → сгенерируйте → **сохраните в менеджер паролей** (нужен для первого входа)
2. **Добавить новый SSH-ключ** → вставьте публичный ключ → название (`my-laptop`) → **Применить**

### 1.5 Создаём сервер
1. **Создать** → подождите 2–5 минут
2. Запишите **Публичный IPv4** из карточки сервера

---

## Раздел 2: Первое подключение по SSH

**SSH** = удалённый доступ к терминалу другого компьютера по сети, с шифрованием.

### 2.1 Подключаемся как root

В терминале VS Code:

**Mac / Linux:** `ssh -i ~/.ssh/beget_vps root@ВАШ-IP`
**Windows:** `ssh -i "$env:USERPROFILE\.ssh\beget_vps" root@ВАШ-IP`

При первом входе → `yes` на fingerprint. Если попросит пароль — тот, что сохранили в 1.4.

Видите `root@hostname:~#` — внутри сервера.

### 2.2 Обновляем систему
```bash
apt update && apt upgrade -y
```

---

## Раздел 3: Пользователь deploy + отключаем root

**Главное правило:** не работаем под root. root — гендир с неограниченными правами и без журнала, опечатался → сервер мёртв. deploy с `sudo` имеет те же права, но через дверь с замком (пароль) и журнал.

### 3.1 Создаём пользователя
На сервере под root:
```bash
adduser deploy
```
Задайте пароль (сохраните), на остальные вопросы — Enter.

```bash
usermod -aG sudo deploy
```

### 3.2 Кладём публичный ключ deploy в authorized_keys

**Локально** в новом терминале (читать `.pub` можно сколько угодно раз):

**Mac / Linux:** `cat ~/.ssh/beget_vps.pub`
**Windows:** `Get-Content "$env:USERPROFILE\.ssh\beget_vps.pub"`

Скопируйте строку.

**На сервере под root:**
```bash
mkdir -p /home/deploy/.ssh
nano /home/deploy/.ssh/authorized_keys
```

Вставьте, сохраните: `Ctrl+O` → Enter → `Ctrl+X`.

Выставляем права:
```bash
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh
```

> 💡 **Альтернатива (Mac/Linux):** одной командой локально, без `nano` и `chmod`:
> ```bash
> ssh-copy-id -i ~/.ssh/beget_vps.pub deploy@ВАШ-IP
> ```
> На Windows из коробки `ssh-copy-id` нет.

### 3.3 Проверяем вход под deploy

**Не закрывая root-окно** (страховка), откройте новый терминал:

**Mac / Linux:** `ssh -i ~/.ssh/beget_vps deploy@ВАШ-IP`
**Windows:** `ssh -i "$env:USERPROFILE\.ssh\beget_vps" deploy@ВАШ-IP`

Должно зайти без пароля. Зелёный `deploy@hostname:~$` — отлично.

### 3.4 Проверяем sudo

**sudo** = "выполни как админ". deploy без sudo системного ничего не сделает. С sudo — может, но Linux спросит пароль и запишет в лог.

```bash
sudo whoami
```
Введите пароль deploy → должно вернуть `root`. Права работают.

### 3.5 Отключаем вход под root

**В root-окне:**
```bash
cat <<'EOF' > /etc/ssh/sshd_config.d/99-hardening.conf
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
EOF

systemctl restart ssh
```

После `restart` оба окна (root и deploy) могут отвалиться — это норма для Ubuntu 24.04.

Переподключаемся **как deploy с флагом `-i`**:

**Mac / Linux:** `ssh -i ~/.ssh/beget_vps deploy@ВАШ-IP`
**Windows:** `ssh -i "$env:USERPROFILE\.ssh\beget_vps" deploy@ВАШ-IP`

> Если попадёте на `Permission denied` — забыли `-i`. Без флага SSH пробует пароль, а парольный логин мы только что отключили.

### 3.6 Проверяем что root отключён

`ssh -i ~/.ssh/beget_vps root@ВАШ-IP` → `Permission denied`. Победа.

> **На случай беды:** Beget даёт **веб-консоль** в карточке VPS — это не SSH, работает всегда. Заходите там под root по паролю → удалите hardening: `rm /etc/ssh/sshd_config.d/99-hardening.conf && systemctl restart ssh`.

---

## Раздел 4: Firewall (ufw)

**ufw** = забор вокруг сервера. Закрывает все порты кроме нужных. Боты непрерывно сканируют — лучше отрезать.

Под deploy:
```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw enable
```

Открыли: 22 (SSH), 80 (HTTP), 443 (HTTPS). Остальное снаружи закрыто.

```bash
sudo ufw status verbose
```
— должен быть `active` и три правила.

> ⚠️ **Критично:** `allow OpenSSH` ДО `enable`, иначе мгновенно потеряете доступ.

---

## Раздел 5: fail2ban

**fail2ban** = автоматический вышибала. Кто ломится по SSH с переборами — банит IP на 10 минут. Второй слой защиты после отключения root.

```bash
sudo apt install -y fail2ban
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
sudo fail2ban-client status sshd
```
— `Jail list: sshd` = работает.

---

## Раздел 6: Привязка домена

**DNS** = телефонный справочник интернета: `mysite.ru → 185.X.X.X`. Сейчас домен указывает на дефолт-IP Beget (заглушка). Меняем на IP вашего VPS.

### 6.1 Открываем DNS
Beget → **Домены** → ваш домен → **три точки** → **Редактировать DNS**.

### 6.2 Меняем A-запись для корня
1. Найдите подзону `@.mysite.ru` (или просто `mysite.ru`)
2. **Карандашик** → "Изменение записей подзоны"
3. У строки **A** → карандашик → замените дефолт-IP (`185.158.133.1`) на IP вашего VPS
4. **Сохранить**

### 6.3 То же для www
Подзона `www.mysite.ru` → карандашик → A-запись → IP VPS → сохранить.

Зачем оба: пользователи вводят и `mysite.ru`, и `www.mysite.ru` — оба варианта должны вести к вам.

### 6.4 Проверяем распространение

Обновляется 5–30 минут. Проверка с локальной машины:

**Mac / Linux:** `dig mysite.ru +short`
**Windows:** `nslookup mysite.ru 8.8.8.8`

> На Windows важно `8.8.8.8` — иначе домашний роутер может ответить timeout. `8.8.8.8` это публичный DNS Google, отвечает всегда.

Когда показывает IP вашего VPS — DNS готов.

> 💡 **Альтернатива:** перенести DNS на Cloudflare — обновления секундные, бесплатный CDN/защита. Минус для 152-ФЗ: нужен режим "DNS only" (серое облако), чтобы трафик не шёл через CF.

---

## Раздел 7: Nginx

**Nginx** = веб-сервер. Швейцар перед файлами: принимает HTTP-запрос, смотрит какой домен спросили, отдаёт нужную папку.

### 7.1 Устанавливаем

Под deploy:
```bash
sudo apt install -y nginx
sudo systemctl enable nginx
```

Откройте `http://ВАШ-IP` → "Welcome to nginx!" — работает.

### 7.2 Создаём папку для сайта

> **Имя папки используем во всех трёх местах:** тут, в Nginx-конфиге ниже, в секрете `VPS_PATH` для деплоя. Должны совпадать. Дальше в мануале — `<sitename>`, подставляйте своё (например `mysite`).

```bash
sudo mkdir -p /var/www/<sitename>
sudo chown -R deploy:deploy /var/www/<sitename>
echo '<h1>It works!</h1>' > /var/www/<sitename>/index.html
```

### 7.3 Конфиг Nginx для домена

```bash
sudo tee /etc/nginx/sites-available/<sitename> > /dev/null <<'EOF'
server {
    listen 80;
    server_name mysite.ru www.mysite.ru;

    root /var/www/<sitename>;
    index index.html;

    location / {
        try_files $uri $uri/ =404;
    }
}
EOF
```

Замените `<sitename>` (3 места) и `mysite.ru` (1 место) на свои значения.

> Удобнее заранее в блокноте подменить плейсхолдеры — потом просто вставить.

Активируем + удаляем дефолт:
```bash
sudo ln -s /etc/nginx/sites-available/<sitename> /etc/nginx/sites-enabled/
sudo rm /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

`nginx -t` проверяет синтаксис, `reload` применяет без перезапуска.

### 7.4 Проверяем

`http://mysite.ru` → "It works!".

> 💡 **Альтернатива (мощная):** **Caddy** вместо Nginx + certbot. Caddy сам выпускает и обновляет SSL автоматически — никакого certbot, никаких symlinks. Конфиг для нашего сценария:
> ```caddy
> mysite.ru, www.mysite.ru {
>     root * /var/www/<sitename>
>     file_server
> }
> ```
> Заменяет Разделы 7 и 8 разом. Минус — Nginx распространённее в туториалах, поэтому в курсе он основной. Caddy — на следующий проект.

---

## Раздел 8: HTTPS через Let's Encrypt

**SSL/HTTPS** = шифрование трафика. Без него браузер пишет "Не защищено", не работает половина браузерных API. **Let's Encrypt** = бесплатный SSL, сертификаты на 90 дней. **certbot** = программа, которая ходит к Let's Encrypt и получает сертификат.

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d mysite.ru -d www.mysite.ru
```

Замените `mysite.ru` на свой. Certbot спросит:
- **Email** — для уведомлений
- **Terms** → `A` (accept)
- **Share email** → `N`
- **Redirect HTTP → HTTPS** → `2` (Redirect)

Откройте `https://mysite.ru` → зелёный замочек 🔒.

```bash
sudo certbot renew --dry-run
```
— проверка авто-обновления (cron уже настроен).

---

## Раздел 9: Деплой через GitHub Actions

**GitHub Actions** = автомат внутри GitHub, запускает скрипты при событиях в репо. Настроим: "при `git push` в `main` — забери файлы, через rsync скопируй на VPS".

**rsync** = умная копировалка между машинами. Передаёт только изменения.

### 9.1 Создаём отдельный SSH-ключ для GitHub Actions

Личный `beget_vps` светить в GitHub нельзя. Делаем отдельный, только для канала Actions → VPS.

В терминале VS Code (локально):

**Mac / Linux:**
```bash
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy -N ""
```

**Windows:**
```powershell
ssh-keygen -t ed25519 -C "github-actions-deploy" -f "$env:USERPROFILE\.ssh\github_deploy" -N '""'
```

Без passphrase (`-N ""`) — иначе Actions не сможет ввести пароль.

> 🚨 **Главное правило про ключи:**
> - **Приватный** (`github_deploy`, многострочный с `BEGIN/END`) → попадёт в **GitHub Secrets**
> - **Публичный** (`github_deploy.pub`, одна строка `ssh-ed25519 ...`) → попадёт **на VPS** в `authorized_keys`
>
> Перепутаете — деплой провалится с `error in libcrypto`. **Самая частая ошибка курса.**

### 9.2 Кладём публичный ключ на VPS

**Локально** покажите `.pub`:

**Mac / Linux:** `cat ~/.ssh/github_deploy.pub`
**Windows:** `Get-Content "$env:USERPROFILE\.ssh\github_deploy.pub"`

Скопируйте строку.

**На сервере под deploy:**
```bash
nano ~/.ssh/authorized_keys
```

Добавьте новую строку с публичным ключом — **после** старой, не вместо неё. У вас должно быть две строки: личный `beget_vps.pub` и `github_deploy.pub`. Сохраните.

### 9.3 Просим Claude создать репо и запушить проект с workflow

Откройте свой проект в VS Code (любой — лендинг, Next.js, статика). Если у вас просто архив с шаблоном — киньте zip в папку проекта.

В чате Claude:
```
Через GitHub MCP создай мне ПРИВАТНЫЙ репозиторий <название> в моём аккаунте.

Если в текущей папке есть zip-архив с шаблоном — сначала распакуй его в корень.

Затем добавь в проект файл .github/workflows/deploy.yml:
- Триггер: push в main + workflow_dispatch
- actions/checkout@v5
- Если есть build-шаг (npm run build / vite / next) — добавь его перед rsync
- burnett01/rsync-deployments@7.0.2 со switches "-avzr --delete"
- Все параметры из секретов: SSH_PRIVATE_KEY, VPS_HOST, VPS_USER, VPS_PATH
- path для rsync определи сам по структуре проекта (dist/, build/, public/, корень)

Запушь всё одним коммитом с сообщением "feat: initial commit with deploy".

Покажи структуру проекта и diff workflow перед коммитом.
```

> ⚠️ **Обязательно укажите ПРИВАТНЫЙ репо** — если по умолчанию создастся публичный, ваш код виден всем. Случайно оставленный API-ключ → утёк.

Claude:
1. Распакует архив (если есть)
2. Прочитает `package.json`/конфиги, поймёт стек
3. Создаст `deploy.yml` с правильным `path`
4. Через GitHub MCP создаст приватный репо, запушит всё одним коммитом

### 9.4 Добавляем секреты в репо (через GitHub UI)

Идите в репозиторий → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Нужны 4 секрета:

| Имя | Значение | Пример |
|---|---|---|
| `SSH_PRIVATE_KEY` | Содержимое файла `github_deploy` целиком (с `BEGIN/END`) | многострочный блок |
| `VPS_HOST` | IP VPS, без `http://` и портов | `185.X.X.X` |
| `VPS_USER` | Пользователь на VPS | `deploy` |
| `VPS_PATH` | Папка на VPS, тот же `<sitename>` что в 7.2 (с `/` в конце) | `/var/www/mysite/` |

Получить содержимое приватного ключа:

**Mac / Linux:** `cat ~/.ssh/github_deploy`
**Windows:** `Get-Content "$env:USERPROFILE\.ssh\github_deploy" -Raw`

Скопируйте **со строками `BEGIN`/`END` включительно**.

> 🚨 В `SSH_PRIVATE_KEY` идёт `github_deploy`, **НЕ** `github_deploy.pub`. Перепутать = `error in libcrypto`.

### 9.5 Триггерим первый деплой

В чате Claude:
```
Запусти workflow deploy.yml в репо <user/repo> через workflow_dispatch.
Покажи прогресс.
```

Или внесите любую правку в файл и запушьте — Action подхватит автоматически.

### 9.6 Проверяем результат

Откройте `https://mysite.ru` — должен показаться ваш проект.

Если упал — ставим **`gh` CLI** (GitHub CLI) для удобной диагностики из чата:
- Windows: `winget install GitHub.cli`
- Mac: `brew install gh`

Один раз: `gh auth login` (через браузер).

После — в чате:
```
Через gh CLI покажи логи упавшего шага последнего workflow run в репо <user/repo>.
Объясни ошибку по-русски.
```

> **`gh` CLI ставите ОДИН РАЗ.** Дальше все будущие деплои отслеживаете через Claude в чате — не открывая GitHub.

### Топ-5 типичных ошибок

1. **Перепутаны приватный/публичный ключи** — в `SSH_PRIVATE_KEY` лежит `.pub` вместо `github_deploy`
2. **`error in libcrypto`** — UI GitHub съел переносы строк в ключе. Перезалейте через `gh secret set SSH_PRIVATE_KEY -R USER/REPO < ~/.ssh/github_deploy`
3. **`Permission denied`, в логе `root@`** — забыли указать `VPS_USER=deploy`, или Claude в workflow прописал `remote_user: root`
4. **`mkdir Permission denied`** — папка из `VPS_PATH` не существует / не принадлежит deploy. Перепройдите 7.2
5. **Деплой прошёл, но 404 / дефолт-Nginx** — `VPS_PATH` не совпадает с `root` в Nginx-конфиге. Сверьте

---

## Раздел 10: Устранение проблем

| Проблема | Причина | Решение |
|---|---|---|
| `Permission denied (publickey)` при первом входе | Ключ не тот / не добавлен в Beget | `cat ~/.ssh/beget_vps.pub`, сверить что в Beget вставлен этот |
| `Permission denied` после копирования ключа deploy | Неправильные права на `.ssh` или `authorized_keys` | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys` |
| Потерял доступ после `ufw enable` | Не выполнили `ufw allow OpenSSH` до `enable` | Веб-консоль Beget → `ufw disable` → `allow OpenSSH` → `ufw enable` |
| `Connection timed out` / `refused` | VPS выключен / не тот IP / SSH упал | Проверьте статус в панели Beget, IP в карточке, через веб-консоль `systemctl status ssh` |
| После отключения root — зайти не могу | Hardening-файл сломан или ключ deploy не работает | Веб-консоль → `rm /etc/ssh/sshd_config.d/99-hardening.conf && systemctl restart ssh` |
| Windows: `ssh: command not found` | Старая Windows без OpenSSH | Settings → Apps → Optional Features → Add OpenSSH Client |
| `Bad permissions` на ключ (Windows) | Windows ставит наследуемые права | Свойства → Безопасность → убрать всех кроме своего пользователя |
| `nslookup` показывает старый IP / timeout | DNS не обновился / роутер залип | `nslookup mysite.ru 8.8.8.8` (через Google DNS) или https://dnschecker.org |
| Nginx: `duplicate default server` | Не удалили `sites-enabled/default` | `sudo rm /etc/nginx/sites-enabled/default && sudo systemctl reload nginx` |
| `502 Bad Gateway` через домен | Конфиг ссылается на сервис которого нет | Для статики в конфиге должно быть `root /var/www/...;`, не `proxy_pass` |
| Certbot: `Failed authorization` | DNS ещё не указывает на VPS / 80 порт закрыт | Подождите DNS, проверьте `sudo ufw status` |
| Nginx-конфиг где-то не работает | Опечатка в `<sitename>` или домене | Скопируйте конфиг в Claude, попросите `найди ошибку в конфиге, я ожидаю что домен <X> ведёт на /var/www/<Y>` |
| GitHub Actions: `Permission denied (publickey)` | `github_deploy.pub` не добавлен на VPS | Раздел 9.2 |
| GitHub Actions: `Host key verification failed` | `VPS_HOST` некорректный | Без `http://` и `:22`, чистый IP |
| GitHub Actions: `error in libcrypto` | UI GitHub съел переносы в ключе | `gh secret set SSH_PRIVATE_KEY -R USER/REPO < ~/.ssh/github_deploy` |
| GitHub Actions: `Permission denied`, `root@` в логе | Claude поставил `remote_user: root` по дефолту | Проверьте `.github/workflows/deploy.yml` — `remote_user` должен быть `${{ secrets.VPS_USER }}` |
| GitHub Actions: `permission denied` на `/var/www/...` | Папка не принадлежит deploy / не существует | На VPS: `sudo mkdir -p ПУТЬ && sudo chown -R deploy:deploy ПУТЬ` |
| Деплой прошёл, но `https://домен` отдаёт 404 | `VPS_PATH` не совпадает с Nginx `root` | Сверьте `VPS_PATH` секрет = `root` в `/etc/nginx/sites-available/...` = папка из 7.2 |
| Деплой прошёл, но видно дефолт Nginx | Нет server-блока для домена / не активирован | Раздел 7.3 — конфиг + symlink + удалить default |

---

## Чек-лист готовности

- [ ] Домен зарегистрирован на Beget
- [ ] VPS Ubuntu 24.04 LTS создан
- [ ] SSH-ключ `beget_vps` создан, публичный загружен в Beget
- [ ] Заходит как root по ключу
- [ ] Создан `deploy` с sudo, под deploy заходит без пароля
- [ ] root-логин и пароль отключены через drop-in `99-hardening.conf`
- [ ] ufw активен (22/80/443)
- [ ] fail2ban запущен
- [ ] A-записи домена и www указывают на IP VPS
- [ ] Nginx обслуживает домен по HTTP
- [ ] HTTPS работает, зелёный замочек
- [ ] Создан `github_deploy`, публичный добавлен в `authorized_keys` на VPS
- [ ] Через Claude создан **приватный** репо с проектом и `deploy.yml`
- [ ] 4 секрета добавлены в репо (`SSH_PRIVATE_KEY`, `VPS_HOST`, `VPS_USER`, `VPS_PATH`)
- [ ] При push в main сайт обновляется автоматически
- [ ] `gh` CLI установлен для проверки статусов из чата

---

## Что дальше

VPS теперь — фундамент. На него можно ставить:
- Базы данных (PostgreSQL, Redis)
- Telegram-ботов, очереди, фоновые задачи
- API на Python / Node / Go тем же flow деплоя
- Self-hosted Supabase (следующий урок)
