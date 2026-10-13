"""
Telegram komutları (bot arka planda dinler):
  /backtest       -> son 7 günle backtest başlatır
  /backtest 60    -> son 60 günle backtest başlatır
  /durum          -> backtest ilerlemesi
  /iptal          -> çalışan backtest'i durdurur
Sadece TELEGRAM_CHAT_ID'deki sohbetten gelen komutlar kabul edilir.
"""

import logging
import os
import subprocess
import sys
import threading
import time

import requests

import config
from telegram import send_message

log = logging.getLogger("bot")
HERE = os.path.dirname(os.path.abspath(__file__))
_bt_proc = None


def start_backtest(text):
    global _bt_proc
    if _bt_proc is not None and _bt_proc.poll() is None:
        send_message("⏳ Backtest zaten çalışıyor, bitince sonuçlar gelecek.")
        return
    parts = text.split()
    days = 7
    if len(parts) > 1 and parts[1].isdigit():
        days = max(1, min(180, int(parts[1])))
    log_file = open(os.path.join(HERE, "backtest.log"), "w")
    _bt_proc = subprocess.Popen(
        [sys.executable, "-u", "backtest.py", "--days", str(days)],
        cwd=HERE, stdout=log_file, stderr=subprocess.STDOUT,
    )
    log.info("Backtest başlatıldı (%d gün)", days)


def status_text():
    running = _bt_proc is not None and _bt_proc.poll() is None
    progress = ""
    try:
        with open(os.path.join(HERE, "backtest.log"), encoding="utf-8", errors="ignore") as f:
            lines = [ln.strip() for ln in f if "coin bitti" in ln or "ERROR" in ln or "Traceback" in ln]
        if lines:
            progress = lines[-1].split(" INFO ")[-1].split(" ERROR ")[-1]
    except OSError:
        pass
    if running:
        return "⏳ Backtest çalışıyor" + (f": {progress}" if progress else ", veri çekiliyor...")
    if _bt_proc is not None:
        return "✅ Son backtest bitti." + (f"\nSon satır: {progress}" if progress else "")
    return "Çalışan backtest yok. Başlatmak için: /backtest"


def _listen():
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = None
    # Bot kapalıyken gönderilmiş eski komutları atla
    try:
        old = requests.get(url, params={"offset": -1}, timeout=15).json().get("result", [])
        if old:
            offset = old[-1]["update_id"] + 1
    except Exception as e:
        log.error("Telegram komutları okunamadı: %s", e)

    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            updates = requests.get(url, params=params, timeout=40).json().get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                    continue
                text = (msg.get("text") or "").strip()
                if text.lower().startswith("/backtest"):
                    start_backtest(text)
                elif text.lower().startswith("/durum"):
                    send_message(status_text())
                elif text.lower().startswith("/iptal"):
                    if _bt_proc is not None and _bt_proc.poll() is None:
                        _bt_proc.terminate()
                        send_message("🛑 Backtest durduruldu.")
                    else:
                        send_message("Çalışan backtest yok.")
        except Exception as e:
            log.error("Komut dinleme hatası: %s", e)
            time.sleep(5)


def start_listener():
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    threading.Thread(target=_listen, daemon=True).start()
