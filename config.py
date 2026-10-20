"""
Genel ayarlar. Gizli bilgiler (token vs.) KODA YAZILMAZ,
Render > Environment kısmından ortam değişkeni olarak verilir.
"""

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# (Telegram'da görünen ad, Binance API aralık adı)
TIMEFRAMES = [("15m", "15m")]
# Canlı EMİR HAZIR taramasının zaman dilimi ("5m", "15m", ...). Render Environment'ta LIVE_TF ile değiştirilebilir.
LIVE_TF = os.environ.get("LIVE_TF", "15m")


# Yüklenen sürüm: açılış mesajında ve /durum'da görünür (yeni kod devreye girdi mi anlaşılsın diye)
VERSION = "20.10 18:10 · CANLI 15m + OTOMATİK İŞLEM 1R=15$ · toplu sinyal sınırı 10 coin · risk son 24 saate göre (kârda 3x = 45$ / ekside 0.5x = 7.5$ / yoksa 15$)"
GIT_COMMIT = os.environ.get("RENDER_GIT_COMMIT", "")[:7]


def version_text():
    return VERSION + (f" [{GIT_COMMIT}]" if GIT_COMMIT else "")


def data_dir():
    """Render'da kalıcı disk takılıysa (/var/data) orası, yoksa /tmp (her yüklemede silinir)."""
    for d in (os.environ.get("DATA_DIR", ""), "/var/data"):
        if d and os.path.isdir(d) and os.access(d, os.W_OK):
            return d
    return "/tmp"


def tf_minutes(tf):
    return int(tf[:-1]) * (60 if tf.endswith("h") else 1)

# Taramalar arası bekleme (saniye)
SCAN_SLEEP = int(os.environ.get("SCAN_SLEEP", "15"))

# Ortak coin listesi kaç saniyede bir yenilensin (her turda çekmeye gerek yok)
SYMBOL_REFRESH_SECONDS = int(os.environ.get("SYMBOL_REFRESH_SECONDS", "3600"))

# EMA20 temas bildirimleri (Telegram'dan /bildirim aç | kapat ile değiştirilebilir)
TOUCH_ALERTS = os.environ.get("TOUCH_ALERTS", "0") == "1"

# Kurallara uyan setup'larda onay mumu kapanınca "EMİR HAZIR" bildirimi (/sinyal aç | kapat)
SETUP_ALERTS = os.environ.get("SETUP_ALERTS", "1") == "1"
