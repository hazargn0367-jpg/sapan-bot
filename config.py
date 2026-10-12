"""
Genel ayarlar. Gizli bilgiler (token vs.) KODA YAZILMAZ,
Render > Environment kısmından ortam değişkeni olarak verilir.
"""

import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# (Telegram'da görünen ad, MEXC API aralık adı)
TIMEFRAMES = [("15m", "Min15"), ("30m", "Min30")]

# Taramalar arası bekleme (saniye)
SCAN_SLEEP = int(os.environ.get("SCAN_SLEEP", "15"))

# Ortak coin listesi kaç saniyede bir yenilensin (her turda çekmeye gerek yok)
SYMBOL_REFRESH_SECONDS = int(os.environ.get("SYMBOL_REFRESH_SECONDS", "3600"))
