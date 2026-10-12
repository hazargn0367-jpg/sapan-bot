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


def get_tick_sizes():
    """Her coinin en küçük fiyat adımı ("1 tık"), örn. {"BTCUSDT": 0.1}."""
    res = _session.get(f"{BASE_URL}/fapi/v1/exchangeInfo", timeout=10)
    res.raise_for_status()
    ticks = {}
    for s in res.json().get("symbols", []):
        for f in s.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                ticks[s["symbol"]] = float(f["tickSize"])
    return ticks


def _throttle(res):
    """Binance dakikalık istek ağırlığı sınırına (2400) yaklaşınca yavaşla.
    Canlı bot da aynı sınırı kullandığı için pay bırakılır."""
    used = int(res.headers.get("X-MBX-USED-WEIGHT-1M", "0") or 0)
    if used > 1500:
        wait = 61 - time.gmtime().tm_sec
        log.info("İstek sınırına yaklaşıldı (%d), %d sn bekleniyor", used, wait)
        time.sleep(wait)


def get_klines_range(symbol, interval, start_ms, end_ms):
    """Geçmiş mum verisi (sadece kapanmış mumlar), sayfa sayfa çeker."""
    rows = []
    cursor = start_ms
    while cursor < end_ms:
        for attempt in range(3):
            res = _session.get(
                f"{BASE_URL}/fapi/v1/klines",
                params={"symbol": symbol, "interval": interval,
                        "startTime": cursor, "endTime": end_ms, "limit": 1000},
                timeout=20,
            )
            if res.status_code in (418, 429):
                wait = int(res.headers.get("Retry-After", "60"))
                log.warning("Binance istek sınırı, %d sn bekleniyor", wait)
                time.sleep(wait)
                continue
            res.raise_for_status()
            break
        else:
            raise RuntimeError(f"{symbol} verisi alınamadı")
        _throttle(res)
        batch = res.json()
        if not batch:
            break
        rows.extend(batch)
        cursor = int(batch[-1][0]) + 1
        if len(batch) < 1000:
            break

    now_ms = int(time.time() * 1000)
    rows = [k for k in rows if int(k[6]) < now_ms]  # açık mumu at
    return pd.DataFrame({
        "timestamp": [int(k[0]) for k in rows],
        "Open": [float(k[1]) for k in rows],
        "High": [float(k[2]) for k in rows],
        "Low": [float(k[3]) for k in rows],
        "Close": [float(k[4]) for k in rows],
    }).drop_duplicates("timestamp").reset_index(drop=True)


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
