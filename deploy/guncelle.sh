#!/bin/bash
# GitHub'daki main dalında yeni commit varsa çeker ve botu yeniden başlatır (Render'daki otomatik yüklemenin aynısı).
set -e
cd /opt/sapan-bot
runuser -u bot -- git fetch -q origin main
LOCAL=$(runuser -u bot -- git rev-parse HEAD)
REMOTE=$(runuser -u bot -- git rev-parse origin/main)
[ "$LOCAL" = "$REMOTE" ] && exit 0
REQ_OLD=$(runuser -u bot -- git show HEAD:requirements.txt | sha1sum)
runuser -u bot -- git reset -q --hard origin/main
REQ_NEW=$(sha1sum < requirements.txt)
if [ "$REQ_OLD" != "$REQ_NEW" ]; then
  runuser -u bot -- /opt/sapan-bot/venv/bin/pip install -q -r requirements.txt
fi
chmod +x deploy/*.sh
systemctl restart sapan-bot
echo "Güncellendi: ${LOCAL:0:7} -> ${REMOTE:0:7}"
