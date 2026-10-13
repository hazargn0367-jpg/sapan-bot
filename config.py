"""
Genel ayarlar. Gizli bilgiler (token vs.) KODA YAZILMAZ,
Render > Environment kısmından ortam değişkeni olarak verilir.
"""

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# (Telegram'da görünen ad, Binance API aralık adı)
TIMEFRAMES = [("15m", "15m")]

# Taramalar arası bekleme (saniye)
SCAN_SLEEP = int(os.environ.get("SCAN_SLEEP", "15"))

# Ortak coin listesi kaç saniyede bir yenilensin (her turda çekmeye gerek yok)
SYMBOL_REFRESH_SECONDS = int(os.environ.get("SYMBOL_REFRESH_SECONDS", "3600"))

# EMA20 temas bildirimleri (Telegram'dan /bildirim aç | kapat ile değiştirilebilir)
TOUCH_ALERTS = os.environ.get("TOUCH_ALERTS", "0") == "1"

# Kurallara uyan setup'larda onay mumu kapanınca "EMİR HAZIR" bildirimi (/sinyal aç | kapat)
SETUP_ALERTS = os.environ.get("SETUP_ALERTS", "1") == "1"
