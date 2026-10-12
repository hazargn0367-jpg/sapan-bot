"""
Binance vadeli (USDT-M perpetual) veri çekme.
"""

import logging
import time

import pandas as pd
import requests

log = logging.getLogger("bot")

BASE_URL = "https://fapi.binance.com"
KLINE_LIMIT = 499  # Binance'te 100-499 arası mum = 2 ağırlık (rate limit dostu)

_session = requests.Session()


def get_symbols():
    """İşlemde olan tüm USDT vadeli (perpetual) coinler, örn. BTCUSDT."""
    try:
        res = _session.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
        res.raise_for_status()
        return sorted(
            s["symbol"]
            for s in res.json().get("symbols", [])
            if s.get("quoteAsset") == "USDT"
            and s.get("contractType") == "PERPETUAL"
            and s.get("status") == "TRADING"
        )
    except Exception as e:
        log.error("Binance coin listesi alınamadı: %s", e)
        return []


def get_klines(symbol, interval):
    """Binance vadeli mum verisi. Son satır şu an açık olan (canlı) mumdur."""
    try:
        res = _session.get(
            f"{BASE_URL}/fapi/v1/klines",
            params={"symbol": symbol, "interval": interval, "limit": KLINE_LIMIT},
            timeout=10,
        )
        if res.status_code in (418, 429):
            wait = int(res.headers.get("Retry-After", "60"))
            log.warning("Binance istek sınırı aşıldı, %s sn bekleniyor", wait)
            time.sleep(wait)
            return None
        res.raise_for_status()
        rows = res.json()
        if not rows:
            return None
        return pd.DataFrame({
            "timestamp": [int(k[0]) for k in rows],
            "Open": [float(k[1]) for k in rows],
            "High": [float(k[2]) for k in rows],
            "Low": [float(k[3]) for k in rows],
            "Close": [float(k[4]) for k in rows],
        })
    except Exception as e:
        log.debug("%s %s verisi alınamadı: %s", symbol, interval, e)
        return None
