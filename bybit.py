"""Bybit USDT vadeli (linear perpetual) herkese açık piyasa verisi: coin listesi, hacim, 15dk mumlar.
Sadece backtest için (emir yok, API anahtarı gerekmez). Bybit v5 REST API.
Kullanıcı 15.10 23:06: "Bybit'teki bütün coinlere göre bir backtest yapalım" (Binance'te olmayan coinler yeni işlem
getirir mi)."""
import logging
import re
import threading
import time

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

BASE = "https://api.bybit.com"
MAX_RPS = 15          # saniyede en fazla istek (Bybit sınırı IP başına 5 sn'de 600; payı geniş tut)
KLINE_LIMIT = 1000    # Bybit'in tek istekte verdiği en fazla mum
INTERVAL = {"15m": "15", "5m": "5", "30m": "30", "1h": "60"}

_lock = threading.Lock()
_next_slot = [0.0]
_local = threading.local()


class BybitError(RuntimeError):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = "sapan-bot-backtest"
        _local.s = s
    return s


def _wait_slot():
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot[0])
        _next_slot[0] = slot + 1.0 / MAX_RPS
    if slot > now:
        time.sleep(slot - now)


def _get(path, params, tries=6):
    last = None
    for k in range(tries):
        _wait_slot()
        try:
            r = _session().get(BASE + path, params=params, timeout=20)
        except requests.RequestException as e:
            last = f"{type(e).__name__}: {e}"
            time.sleep(2 + 2 * k)
            continue
        if r.status_code in (403, 451):
            # CloudFront bölge engeli vb.: beklemek işe yaramaz
            raise BybitError(f"Bybit API erişimi engelli (HTTP {r.status_code}): {r.text[:200]}")
        if r.status_code == 429 or r.status_code >= 500:
            last = f"HTTP {r.status_code}"
            time.sleep(3 + 3 * k)
            continue
        try:
            j = r.json()
        except ValueError:
            last = f"HTTP {r.status_code}, JSON değil: {r.text[:120]}"
            time.sleep(2 + 2 * k)
            continue
        code = j.get("retCode")
        if code == 0:
            return j.get("result") or {}
        if code == 10006:  # istek sınırı
            last = "istek sınırı (10006)"
            time.sleep(3 + 3 * k)
            continue
        raise BybitError(f"Bybit {path} hata {code}: {j.get('retMsg')}")
    raise BybitError(f"Bybit {path} {tries} denemede alınamadı: {last}")


def instruments():
    """İşlemde olan USDT linear perpetual kontratlar: {symbol: {"tick": float, "launch": ms, "base": str}}"""
    out, cursor = {}, ""
    for _ in range(20):
        res = _get("/v5/market/instruments-info", {"category": "linear", "limit": 1000, "cursor": cursor})
        for s in res.get("list", []):
            if s.get("quoteCoin") != "USDT" or s.get("contractType") != "LinearPerpetual" or s.get("status") != "Trading":
                continue
            try:
                tick = float(s["priceFilter"]["tickSize"])
            except (KeyError, TypeError, ValueError):
                tick = 0.0
            out[s["symbol"]] = {"tick": tick, "launch": int(s.get("launchTime") or 0), "base": s.get("baseCoin", "")}
        cursor = res.get("nextPageCursor") or ""
        if not cursor:
            break
    return out


def turnover24h():
    res = _get("/v5/market/tickers", {"category": "linear"})
    vol = {}
    for t in res.get("list", []):
        try:
            vol[t["symbol"]] = float(t.get("turnover24h") or 0)
        except (TypeError, ValueError):
            pass
    return vol


def top_symbols(n=0):
    """(semboller hacme göre büyükten küçüğe, {sembol: fiyat adımı}). n=0: hepsi."""
    inst = instruments()
    vol = turnover24h()
    syms = sorted(inst, key=lambda s: vol.get(s, 0.0), reverse=True)
    if n:
        syms = syms[:n]
    return syms, {s: inst[s]["tick"] for s in inst}


_MULT = re.compile(r"^(1000000|100000|10000|1000|1M)(?=[A-Z])|(1000000|10000|1000)$")


def norm(symbol):
    """Borsalar arası eşleştirme için coin adı: 1000PEPEUSDT / PEPEUSDT / SHIB1000USDT -> PEPE / SHIB."""
    b = symbol[:-4] if symbol.endswith("USDT") else symbol
    return _MULT.sub("", b) or b


def klines(symbol, start_ms, end_ms, tf="15m"):
    """[start_ms, end_ms) arasındaki mumlar (timestamp, Open, High, Low, Close), eskiden yeniye."""
    iv = INTERVAL[tf]
    bar = int(iv) * 60 * 1000
    rows = []
    s = start_ms - start_ms % bar
    while s < end_ms:
        e = min(s + KLINE_LIMIT * bar, end_ms) - 1
        res = _get("/v5/market/kline", {"category": "linear", "symbol": symbol, "interval": iv,
                                         "start": s, "end": e, "limit": KLINE_LIMIT})
        lst = res.get("list") or []
        rows.extend(lst)
        s = e + 1
    if not rows:
        return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
    a = np.array([[float(x) for x in r[:5]] for r in rows], dtype=np.float64)
    a = a[np.argsort(a[:, 0], kind="stable")]
    a = a[np.r_[True, np.diff(a[:, 0]) > 0]]          # tekrar eden mumlar
    a = a[(a[:, 0] >= start_ms) & (a[:, 0] < end_ms)]
    return pd.DataFrame({"timestamp": a[:, 0].astype(np.int64), "Open": a[:, 1], "High": a[:, 2],
                         "Low": a[:, 3], "Close": a[:, 4]})
