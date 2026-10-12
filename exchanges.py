"""
Borsalardan veri çekme (Binance + MEXC vadeli).
"""

import logging

import pandas as pd
import requests

log = logging.getLogger("bot")


def get_binance_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        return {
            s["baseAsset"] + "_USDT"
            for s in res.json().get("symbols", [])
            if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL"
        }
    except Exception as e:
        log.error("Binance coin listesi alınamadı: %s", e)
        return set()


def get_mexc_symbols():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    try:
        res = requests.get(url, timeout=10)
        res.raise_for_status()
        data = res.json()
        if not data.get("success"):
            return set()
        return {
            item["symbol"]
            for item in data.get("data") or []
            if item.get("symbol", "").endswith("_USDT")
        }
    except Exception as e:
        log.error("MEXC coin listesi alınamadı: %s", e)
        return set()


def get_common_symbols():
    """Hem Binance hem MEXC'de olan USDT vadeli coinler.
    Binance'e ulaşılamazsa (eski koddaki gibi) tüm MEXC coinleri kullanılır."""
    binance = get_binance_symbols()
    mexc = get_mexc_symbols()
    if not mexc:
        return []
    if not binance:
        log.warning("Binance listesi yok, tüm MEXC coinleri taranacak (%d adet)", len(mexc))
        return sorted(mexc)
    return sorted(binance & mexc)


def get_klines(symbol, interval):
    """MEXC vadeli mum verisi. Son satır şu an açık olan (canlı) mumdur."""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}"
    try:
        res = requests.get(url, params={"interval": interval}, timeout=5)
        res.raise_for_status()
        js = res.json()
        if not js.get("success") or not js.get("data"):
            return None
        d = js["data"]
        return pd.DataFrame({
            "timestamp": d.get("time", []),
            "Open": [float(x) for x in d.get("open", [])],
            "High": [float(x) for x in d.get("high", [])],
            "Low": [float(x) for x in d.get("low", [])],
            "Close": [float(x) for x in d.get("close", [])],
        })
    except Exception as e:
        log.debug("%s %s verisi alınamadı: %s", symbol, interval, e)
        return None
