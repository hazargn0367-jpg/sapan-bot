"""
Telegram mesaj gönderme.
"""

import html
import logging

import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

log = logging.getLogger("bot")


def send_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram ayarları eksik, mesaj gönderilmedi:\n%s", text)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        if r.status_code != 200:
            log.error("Telegram hatası %s: %s", r.status_code, r.text)
            return False
        return True
    except requests.RequestException as e:
        log.error("Telegram'a ulaşılamadı: %s", e)
        return False


def send_document(path, caption=""):
    """Telegram'a dosya gönderir (örn. backtest işlem listesi)."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log.warning("Telegram ayarları eksik, dosya gönderilmedi: %s", path)
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
    try:
        with open(path, "rb") as f:
            r = requests.post(
                url,
                data={"chat_id": TELEGRAM_CHAT_ID, "caption": caption[:1000]},
                files={"document": f},
                timeout=60,
            )
        if r.status_code != 200:
            log.error("Telegram dosya hatası %s: %s", r.status_code, r.text)
            return False
        return True
    except (requests.RequestException, OSError) as e:
        log.error("Dosya gönderilemedi: %s", e)
        return False


def send_photos(paths, caption=""):
    """En fazla 10 fotoğrafı tek albüm olarak gönderir."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not paths:
        return False
    import json
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    files, media = {}, []
    try:
        for k, p in enumerate(paths[:10]):
            files[f"f{k}"] = open(p, "rb")
            item = {"type": "photo", "media": f"attach://f{k}"}
            if k == 0 and caption:
                item["caption"] = caption[:1000]
            media.append(item)
        r = requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "media": json.dumps(media)},
                          files=files, timeout=120)
        if r.status_code != 200:
            log.error("Telegram fotoğraf hatası %s: %s", r.status_code, r.text)
            return False
        return True
    except (requests.RequestException, OSError) as e:
        log.error("Fotoğraflar gönderilemedi: %s", e)
        return False
    finally:
        for f in files.values():
            f.close()


def format_signal(symbol, tf_label, sig):
    s = html.escape(symbol)
    tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P"
    if sig["side"] == "LONG":
        head = "🟢 <b>NET TREND + GÖVDE KAPANIŞLI İLK TEMAS (LONG)!</b>"
        durum = "Kusursuz paralel trend, gövdeyle kırılan zirve ve EMA20'ye ilk temas!"
    else:
        head = "🔴 <b>NET TREND + GÖVDE KAPANIŞLI İLK TEMAS (SHORT)!</b>"
        durum = "Kusursuz paralel trend, gövdeyle kırılan dip ve EMA20'ye ilk temas!"
    return (
        f"{head}\n\n"
        f"Coin: <code>{s}</code>\n"
        f"Zaman Dilimi: <code>{tf_label}</code>\n"
        f"Fiyat: <code>{sig['price']}</code>\n"
        f"Stoch K: <code>{sig['stoch']:.2f}</code>\n"
        f"Durum: {durum}\n\n"
        f'<a href="{tv_link}">TradingView\'da Aç</a>'
    )
