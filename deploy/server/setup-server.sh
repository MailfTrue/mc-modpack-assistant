#!/usr/bin/env bash
# Настройка сервера Ubuntu (24.04) под Minecraft + brain. Идемпотентно: повторный запуск ничего не ломает
# и меняет только то, что отличается. Сервер Minecraft НИКОГДА не перезапускает: изменения его службы
# применятся при следующем перезапуске.
#
# Запуск от обычного пользователя с sudo (под ним будут работать сервер и brain):
#   первый раз (репозитория на сервере ещё нет):
#     ssh user@host 'bash -s -- --domain mc.example.com --memory 7G' < deploy/server/setup-server.sh
#   потом:
#     ~/mc-modpack-assistant/deploy/server/setup-server.sh            # всё
#     ~/mc-modpack-assistant/deploy/server/setup-server.sh --configs  # только конфиги и службы (без apt)
#
# Настройки сохраняются в ~/.config/minecraft-host.env (DOMAIN, MEMORY, REPO_URL).
# Раскладка: ~/server — сервер, ~/mc-modpack-assistant — репозиторий, ~/bin — mc, mc-start, mc-update.
set -euo pipefail

HOST_ENV="$HOME/.config/minecraft-host.env"
REPO="$HOME/mc-modpack-assistant"
SERVER="$HOME/server"
TRAEFIK_VERSION="v3.7.14"
SWAP_SIZE="4G"

DOMAIN="" MEMORY="" REPO_URL=""
[ -f "$HOST_ENV" ] && . "$HOST_ENV"
configs_only=false
while [ $# -gt 0 ]; do
  case "$1" in
    --domain) DOMAIN="$2"; shift 2 ;;
    --memory) MEMORY="$2"; shift 2 ;;
    --repo) REPO_URL="$2"; shift 2 ;;
    --configs) configs_only=true; shift ;;
    *) echo "неизвестный параметр: $1" >&2; exit 2 ;;
  esac
done
MEMORY="${MEMORY:-7G}"
REPO_URL="${REPO_URL:-https://github.com/MailfTrue/mc-modpack-assistant.git}"
mkdir -p "$HOME/.config" "$HOME/bin"
chmod 700 "$HOME/.config"
printf 'DOMAIN=%q\nMEMORY=%q\nREPO_URL=%q\n' "$DOMAIN" "$MEMORY" "$REPO_URL" > "$HOST_ENV"

say() { printf '== %s\n' "$*"; }
# install_file <путь> <режим> [sudo]: содержимое со stdin; пишет, только если изменилось. 0 — изменён.
install_file() {
  local path="$1" mode="$2" as="${3:-}" tmp
  tmp=$(mktemp)
  cat > "$tmp"
  if $as cmp -s "$tmp" "$path" 2>/dev/null; then
    rm -f "$tmp"
    return 1
  fi
  $as install -D -m "$mode" "$tmp" "$path"
  rm -f "$tmp"
  echo "  обновлён $path"
  return 0
}

# ---------- пакеты, swap, инструменты ----------
if [ "$configs_only" = false ]; then
  say "пакеты"
  need=()
  for pkg in openjdk-17-jre-headless python3 git curl ufw; do
    dpkg -s "$pkg" >/dev/null 2>&1 || need+=("$pkg")
  done
  if [ ${#need[@]} -gt 0 ]; then
    sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq "${need[@]}" >/dev/null
    echo "  установлены: ${need[*]}"
  fi

  say "swap"
  if ! swapon --show | grep -q .; then
    sudo fallocate -l "$SWAP_SIZE" /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    echo "  создан /swapfile $SWAP_SIZE"
  fi
  echo 'vm.swappiness=10' | install_file /etc/sysctl.d/99-swap.conf 644 sudo && sudo sysctl -q -p /etc/sysctl.d/99-swap.conf || true

  say "uv и Claude Code"
  [ -x "$HOME/.local/bin/uv" ] || curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
  [ -x "$HOME/.local/bin/claude" ] || curl -fsSL https://claude.ai/install.sh | bash >/dev/null 2>&1
  "$HOME/.local/bin/uv" --version
  "$HOME/.local/bin/claude" --version

  say "репозиторий"
  [ -d "$REPO/.git" ] || git clone -q "$REPO_URL" "$REPO"
  (cd "$REPO/brain" && "$HOME/.local/bin/uv" sync -q --frozen)
  git -C "$REPO" log --oneline -1

  say "Traefik $TRAEFIK_VERSION"
  if [ -n "$DOMAIN" ] && ! /usr/local/bin/traefik version 2>/dev/null | grep -q "${TRAEFIK_VERSION#v}"; then
    tmp=$(mktemp -d)
    base="https://github.com/traefik/traefik/releases/download/$TRAEFIK_VERSION"
    curl -fsSL -o "$tmp/traefik.tgz" "$base/traefik_${TRAEFIK_VERSION}_linux_amd64.tar.gz"
    expected=$(curl -fsSL "$base/traefik_${TRAEFIK_VERSION}_checksums.txt" | grep "_linux_amd64.tar.gz" | cut -d' ' -f1)
    echo "$expected  $tmp/traefik.tgz" | sha256sum -c --quiet -
    tar xzf "$tmp/traefik.tgz" -C "$tmp" traefik
    sudo install -m 755 "$tmp/traefik" /usr/local/bin/traefik
    rm -rf "$tmp"
    echo "  установлен"
  fi
fi

# ---------- скрипты ----------
say "скрипты в ~/bin"
install_file "$HOME/bin/mc" 755 < "$REPO/deploy/mc" || true
install_file "$HOME/bin/mc-update" 755 < "$REPO/deploy/mc-update" || true
install_file "$HOME/bin/mc-start" 755 <<EOF || true
#!/bin/bash
# Запуск сервера Minecraft (служба minecraft). Создан setup-server.sh — правь параметры там.
cd "$SERVER"
# Токен подписки Claude (claude setup-token) и прочие секреты для brain.
set -a; [ -f "$HOME/.config/minecraft.env" ] && . "$HOME/.config/minecraft.env"; set +a
exec java -Xms$MEMORY -Xmx$MEMORY -XX:+UseG1GC -XX:+ParallelRefProcEnabled -XX:MaxGCPauseMillis=200 \\
  -XX:+UnlockExperimentalVMOptions -XX:+DisableExplicitGC -XX:+AlwaysPreTouch \\
  -XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20 \\
  -XX:InitiatingHeapOccupancyPercent=15 -Dlog4j2.formatMsgNoLookups=true \\
  -Dfile.encoding=UTF-8 -Dsun.stdout.encoding=UTF-8 -Dsun.stderr.encoding=UTF-8 \\
  -jar fabric-server-launcher.jar nogui
EOF

# ---------- службы ----------
say "службы systemd"
units_changed=false
minecraft_changed=false
status_changed=false
traefik_changed=false

if install_file /etc/systemd/system/minecraft.service 644 sudo <<EOF; then units_changed=true; minecraft_changed=true; fi
[Unit]
Description=Minecraft server
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$SERVER
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
Environment=LANG=C.UTF-8
ExecStart=$HOME/bin/mc-start
# SIGTERM только Java: сервер сам сохранит мир и остановит brain; остальное добьётся по таймауту.
KillMode=mixed
KillSignal=SIGTERM
SuccessExitStatus=143
TimeoutStopSec=180
Restart=on-failure
RestartSec=30
# Вывод сервера дублирует logs/latest.log
StandardOutput=null
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

if install_file /etc/systemd/system/mc-status.service 644 sudo <<EOF; then units_changed=true; status_changed=true; fi
[Unit]
Description=Public Minecraft status page
After=network-online.target

[Service]
User=$USER
Environment=SERVER_DIR=$SERVER
Environment=STATUS_LISTEN=127.0.0.1:8080
ExecStart=/usr/bin/python3 $REPO/deploy/status/status.py
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=read-only
PrivateTmp=true
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

if [ -n "$DOMAIN" ]; then
  id traefik >/dev/null 2>&1 || sudo useradd --system --no-create-home --shell /usr/sbin/nologin traefik
  sudo install -d -o traefik -g traefik -m 700 /var/lib/traefik
  [ -f /var/lib/traefik/acme.json ] || sudo install -o traefik -g traefik -m 600 /dev/null /var/lib/traefik/acme.json

  if install_file /etc/systemd/system/traefik.service 644 sudo <<'EOF'; then units_changed=true; traefik_changed=true; fi
[Unit]
Description=Traefik reverse proxy
After=network-online.target
Wants=network-online.target

[Service]
User=traefik
Group=traefik
ExecStart=/usr/local/bin/traefik --configFile=/etc/traefik/traefik.yml
AmbientCapabilities=CAP_NET_BIND_SERVICE
CapabilityBoundingSet=CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/traefik
PrivateTmp=true
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

  if install_file /etc/traefik/traefik.yml 644 sudo <<'EOF'; then traefik_changed=true; fi
entryPoints:
  web:
    address: ":80"
  websecure:
    address: ":443"
    http:
      tls:
        certResolver: le
certificatesResolvers:
  le:
    acme:
      storage: /var/lib/traefik/acme.json
      httpChallenge:
        entryPoint: web
providers:
  file:
    directory: /etc/traefik/dynamic
    watch: true
log:
  level: INFO
EOF

  # Маршруты Traefik перечитывает сам (watch), перезапуск не нужен.
  install_file /etc/traefik/dynamic/status.yml 644 sudo <<EOF || true
http:
  routers:
    status:
      rule: Host(\`$DOMAIN\`)
      entryPoints: [websecure]
      service: status
      middlewares: [security]
    status-http:
      rule: Host(\`$DOMAIN\`)
      entryPoints: [web]
      service: status
      middlewares: [to-https]
    # Заход по голому IP — без сертификата, просто страница по http.
    status-ip:
      rule: PathPrefix(\`/\`)
      priority: 1
      entryPoints: [web]
      service: status
  middlewares:
    to-https:
      redirectScheme:
        scheme: https
        permanent: true
    security:
      headers:
        stsSeconds: 31536000
        contentTypeNosniff: true
        referrerPolicy: strict-origin-when-cross-origin
  services:
    status:
      loadBalancer:
        servers:
          - url: http://127.0.0.1:8080
EOF
fi

[ "$units_changed" = true ] && sudo systemctl daemon-reload
sudo systemctl enable -q minecraft mc-status
if [ "$status_changed" = true ] || ! systemctl is-active -q mc-status; then
  sudo systemctl restart mc-status && echo "  mc-status перезапущен"
fi
if [ -n "$DOMAIN" ]; then
  sudo systemctl enable -q traefik
  if [ "$traefik_changed" = true ] || ! systemctl is-active -q traefik; then
    sudo systemctl restart traefik && echo "  traefik перезапущен"
  fi
fi
if systemctl is-active -q minecraft; then
  [ "$minecraft_changed" = true ] && echo "  minecraft.service изменён — применится при следующем перезапуске сервера"
elif [ -f "$SERVER/fabric-server-launcher.jar" ]; then
  echo "  сервер Minecraft не запущен: sudo systemctl start minecraft"
else
  echo "  папки сервера $SERVER ещё нет — скопируй туда сервер и запусти: sudo systemctl start minecraft"
fi

# ---------- система ----------
say "система"
# Автообновления Ubuntu не должны перезапускать сервер посреди игры.
install_file /etc/needrestart/conf.d/50-minecraft.conf 644 sudo <<'EOF' || true
# Не перезапускать сервер Minecraft автоматически после обновлений пакетов.
$nrconf{override_rc}{qr(^minecraft\.service$)} = 0;
EOF
# Пользовательские службы (systemd-run --user) живут и после выхода из ssh.
loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes || sudo loginctl enable-linger "$USER"
if [ "$configs_only" = false ]; then
  for rule in OpenSSH 25565/tcp 80/tcp 443/tcp; do sudo ufw allow "$rule" >/dev/null; done
  sudo ufw status | grep -q "Status: active" || { sudo ufw --force enable >/dev/null; echo "  ufw включён"; }
fi

# ---------- что осталось сделать руками ----------
say "проверка секретов"
grep -qs '^CLAUDE_CODE_OAUTH_TOKEN=' "$HOME/.config/minecraft.env" \
  || echo "  нет токена Claude: на своём ПК 'claude setup-token', затем строка CLAUDE_CODE_OAUTH_TOKEN=… в ~/.config/minecraft.env (chmod 600)"
if [ -f "$SERVER/server.properties" ]; then
  grep -q '^enable-rcon=true' "$SERVER/server.properties" \
    || echo "  RCON выключен (нужен mc и mc-update): enable-rcon=true, rcon.password=<случайный> в server.properties"
  python3 -c 'import json, sys; sys.exit(not (json.load(open(sys.argv[1])).get("telegram") or {}).get("token"))' \
    "$SERVER/config/modpack-bridge.json" 2>/dev/null \
    || echo "  нет токена Telegram: telegram.token в $SERVER/config/modpack-bridge.json"
fi
say "готово"
