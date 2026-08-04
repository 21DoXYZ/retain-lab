#!/usr/bin/env bash
# Закрывает порты локального Supabase от интернета.
#
# ЗАЧЕМ. Локальный стек Supabase CLI рассчитан на ноутбук разработчика: он
# поднимается с ДЕМО-ключами (anon/service_role общеизвестны, лежат в доках
# Supabase) и без TLS. Docker публикует порты в обход ufw, а на этой машине
# ufw вообще выключен (INPUT policy ACCEPT) — то есть без этих правил
# 54321/54322/54323/54324 торчали бы в интернет, и любой мог бы прийти с
# публичным service_role-ключом прямо в CRM-базу (обходя RLS).
#
# ВАЖНО — почему правил ДВА комплекта (IPv4 и IPv6), с разными цепочками:
#
#   IPv4: Supabase-порты имеют DNAT (iptables -t nat -L DOCKER), поэтому внешний
#         пакет форвардится в контейнер и проходит через FORWARD -> DOCKER-USER.
#         Фильтруем там (как kafka_firewall.sh).
#
#   IPv6: DNAT для v6 НЕТ (docker не управляет ip6tables), порт обслуживает
#         userland docker-proxy, слушающий [::]:PORT. Такой трафик идёт в INPUT,
#         а НЕ в FORWARD — правила DOCKER-USER его не видят вообще. У машины есть
#         публичный IPv6, ip6tables INPUT policy = ACCEPT, поэтому без правил ниже
#         Supabase был доступен всему интернету по IPv6 (проверено: соединение
#         на [<public-v6>]:54321 проходило).
#
# (Kafka 19092 этой проблемы не имеет: в compose порт задан явным IPv4-адресом,
#  поэтому docker-proxy не поднимает [::]-сокет.)
#
# По умолчанию доступ ТОЛЬКО с самой машины (localhost и docker-сети).
# Разрешить свой IP:  SUPABASE_ALLOWED_IPS=1.2.3.4,2a02:...  в .env
#
# Запуск:  sudo ./supabase_firewall.sh
# Правила НЕ переживают перезагрузку — вешай на @reboot вместе с kafka_firewall.sh.
set -euo pipefail
cd "$(dirname "$0")"

PORTS="54321 54322 54323 54324 54327 54329"
CHAIN=SB_ALLOWLIST
CHAIN6=SB_ALLOWLIST6
ALLOWED=$(sed -n 's/^SUPABASE_ALLOWED_IPS=//p' .env | tr -d ' ')

if [ "$(id -u)" -ne 0 ]; then echo "нужен root (sudo)"; exit 1; fi

# ─────────────────────────── IPv4: FORWARD -> DOCKER-USER ───────────────────────────
iptables -N "$CHAIN" 2>/dev/null || true
for p in $PORTS; do
  iptables -C DOCKER-USER -p tcp --dport "$p" -j "$CHAIN" 2>/dev/null \
    || iptables -I DOCKER-USER 1 -p tcp --dport "$p" -j "$CHAIN"
done
iptables -F "$CHAIN"
iptables -A "$CHAIN" -s 127.0.0.0/8   -j RETURN
iptables -A "$CHAIN" -s 172.16.0.0/12 -j RETURN

# ─────────────────────────── IPv6: INPUT (docker-proxy) ─────────────────────────────
ip6tables -N "$CHAIN6" 2>/dev/null || true
for p in $PORTS; do
  ip6tables -C INPUT -p tcp --dport "$p" -j "$CHAIN6" 2>/dev/null \
    || ip6tables -I INPUT 1 -p tcp --dport "$p" -j "$CHAIN6"
  # на случай, если docker когда-нибудь включат ip6tables (появится v6-DNAT)
  ip6tables -C DOCKER-USER -p tcp --dport "$p" -j "$CHAIN6" 2>/dev/null \
    || ip6tables -I DOCKER-USER 1 -p tcp --dport "$p" -j "$CHAIN6" 2>/dev/null || true
done
ip6tables -F "$CHAIN6"
ip6tables -A "$CHAIN6" -s ::1/128  -j RETURN
ip6tables -A "$CHAIN6" -s fc00::/7 -j RETURN   # ULA (внутренние docker-сети)

# ─────────────────────────── свои IP из .env ────────────────────────────────────────
if [ -n "$ALLOWED" ]; then
  IFS=',' read -ra IPS <<< "$ALLOWED"
  for ip in "${IPS[@]}"; do
    echo "allow $ip -> Supabase"
    case "$ip" in
      *:*) ip6tables -A "$CHAIN6" -s "$ip" -j RETURN ;;
      *)   iptables  -A "$CHAIN"  -s "$ip" -j RETURN ;;
    esac
  done
fi

# всё остальное — drop (демо-ключи и Studio без пароля наружу не выставляем)
iptables  -A "$CHAIN"  -j DROP
ip6tables -A "$CHAIN6" -j DROP

echo "готово. Порты $PORTS закрыты от интернета (IPv4 + IPv6)."
echo "--- IPv4 ($CHAIN) ---";  iptables  -L "$CHAIN"  -n -v --line-numbers
echo "--- IPv6 ($CHAIN6) ---"; ip6tables -L "$CHAIN6" -n -v --line-numbers
