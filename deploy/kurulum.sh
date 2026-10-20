#!/bin/bash
# Kendi sunucuda (Ubuntu 22.04 / 24.04) kurulum. root olarak, repo /opt/sapan-bot'a klonlandıktan sonra:
#   bash /opt/sapan-bot/deploy/kurulum.sh
set -e
[ "$(id -u)" = "0" ] || { echo "root olarak çalıştır (sudo -i)"; exit 1; }
apt-get update -q
apt-get install -y -q python3 python3-venv python3-pip git
id bot >/dev/null 2>&1 || useradd -r -m -s /usr/sbin/nologin bot
mkdir -p /var/data
chown -R bot:bot /opt/sapan-bot /var/data
cd /opt/sapan-bot
runuser -u bot -- python3 -m venv venv
runuser -u bot -- venv/bin/pip install -q --upgrade pip
runuser -u bot -- venv/bin/pip install -q -r requirements.txt
if [ ! -f /etc/sapan-bot.env ]; then
  cp deploy/ornek.env /etc/sapan-bot.env
  chmod 600 /etc/sapan-bot.env
fi
chmod +x deploy/*.sh
cp deploy/sapan-bot.service deploy/sapan-bot-update.service deploy/sapan-bot-update.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable sapan-bot sapan-bot-update.timer
systemctl start sapan-bot-update.timer
# Saat ayarı (Binance imzalı istekler için saat doğru olmalı)
timedatectl set-ntp true || true
echo
echo "KURULUM TAMAM. Sıradaki adımlar:"
echo "  1) nano /etc/sapan-bot.env   (Render Environment'taki değerleri yapıştır, kaydet: Ctrl+O, Enter, Ctrl+X)"
echo "  2) Render'da botu DURDUR (Suspend) — iki bot aynı anda çalışmasın"
echo "  3) systemctl start sapan-bot"
echo "  4) Telegram: /ip  (çıkan IP'yi Binance API trusted IPs'e ekle), sonra /oto ve /durum"
echo "Kayıt: journalctl -u sapan-bot -f"
