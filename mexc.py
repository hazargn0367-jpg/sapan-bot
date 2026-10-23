"""MEXC USDT vadeli (perpetual) herkese açık piyasa verisi: coin listesi, hacim, mumlar. Sadece backtest için
(emir yok, API anahtarı gerekmez). Kullanıcı 23.10 03:21: "en çok coin içeren borsada deneyelim" (MEXC ~1000 vadeli coin).
Arayüz bybit.py ile aynı (top_symbols / norm / klines), backtest --exchange mexc.

API (contract v1, herkese açık): /api/v1/contract/detail (kontratlar), /api/v1/contract/ticker (24 saat), /api/v1/contract/kline/{sym}
(zaman SANİYE, istek başına en fazla 2000 mum, sınır 20 istek / 2 sn)."""
import logging
import re
import threading
import time

import numpy as np
import pandas as pd
import requests

log = logging.getLogger(__name__)

BASES = ["https://contract.mexc.com", "https://api.mexc.com"]
MAX_RPS = 7           # kline sınırı 20 / 2 sn; payı geniş tut
KLINE_LIMIT = 2000
INTERVAL = {"5m": "Min5", "15m": "Min15", "30m": "Min30", "1h": "Min60"}
STATS = {"api_allowed": 0, "api_blocked": 0, "stock": 0, "hidden": 0}

_lock = threading.Lock()
_next_slot = [0.0]
_local = threading.local()
_base = [None]


class MexcError(RuntimeError):
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


def _get(path, params=None, tries=6):
    last = None
    bases = [_base[0]] if _base[0] else BASES
    for k in range(tries):
        for base in bases:
            _wait_slot()
            try:
                r = _session().get(base + path, params=params, timeout=20)
            except requests.RequestException as e:
                last = f"{base}: {type(e).__name__}: {e}"
                continue
            if r.status_code in (403, 451):
                last = f"{base}: HTTP {r.status_code} {r.text[:150]}"
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"{base}: HTTP {r.status_code}"
                time.sleep(3 + 3 * k)
                continue
            try:
                j = r.json()
            except ValueError:
                last = f"{base}: HTTP {r.status_code}, JSON değil: {r.text[:120]}"
                continue
            if j.get("success") is True or j.get("code") == 0:
                _base[0] = base
                return j.get("data")
            if j.get("code") in (510, 429):   # istek sınırı
                last = f"{base}: istek sınırı ({j.get('code')})"
                time.sleep(3 + 3 * k)
                continue
            raise MexcError(f"MEXC {path} hata {j.get('code')}: {j.get('message') or j.get('msg')}")
        time.sleep(1 + k)
    raise MexcError(f"MEXC {path} {tries} denemede alınamadı: {last}")


def instruments():
    """İşlemde olan USDT perpetual kontratlar: {symbol: {"tick", "base", "api"}}. Hisse kontratları ve gizliler hariç."""
    data = None
    for path in ("/api/v1/contract/detail", "/api/v1/contract/detail/country"):
        try:
            data = _get(path)
            if data:
                break
        except MexcError as e:
            log.warning("MEXC %s: %s", path, e)
    if not data:
        raise MexcError("MEXC kontrat listesi alınamadı")
    if isinstance(data, dict):
        data = [data]
    out = {}
    for s in data:
        sym = s.get("symbol", "")
        if s.get("quoteCoin") != "USDT" or s.get("settleCoin", "USDT") != "USDT" or not sym.endswith("_USDT"):
            continue
        if s.get("state", 0) != 0 or s.get("futureType", 1) != 1 or s.get("type", 1) != 1:
            continue
        name = f"{sym} {s.get('displayNameEn', '')} {s.get('conceptPlate', '')}".upper()
        if "STOCK" in name or "XSTOCK" in name:
            STATS["stock"] += 1
            continue
        if s.get("isHidden"):
            STATS["hidden"] += 1
            continue
        api = s.get("apiAllowed")
        STATS["api_allowed" if api is not False else "api_blocked"] += 1
        try:
            tick = float(s.get("priceUnit") or 0)
        except (TypeError, ValueError):
            tick = 0.0
        out[sym] = {"tick": tick, "base": s.get("baseCoin", ""), "api": api}
    return out


def turnover24h():
    data = _get("/api/v1/contract/ticker") or []
    vol = {}
    for t in data if isinstance(data, list) else [data]:
        try:
            vol[t["symbol"]] = float(t.get("amount24") or 0)
        except (KeyError, TypeError, ValueError):
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
    """Borsalar arası eşleştirme: BTC_USDT / 1000PEPE_USDT / PEPEUSDT -> BTC / PEPE."""
    b = symbol.replace("_USDT", "")
    if b.endswith("USDT"):
        b = b[:-4]
    return _MULT.sub("", b) or b


def klines(symbol, start_ms, end_ms, tf="15m"):
    """[start_ms, end_ms) arasındaki mumlar (timestamp ms, Open, High, Low, Close), eskiden yeniye."""
    iv = INTERVAL[tf]
    bar_s = int(tf[:-1]) * 60 * (60 if tf.endswith("h") else 1)
    s = (start_ms // 1000) - (start_ms // 1000) % bar_s
    e_all = end_ms // 1000
    parts = []
    while s < e_all:
        e = min(s + (KLINE_LIMIT - 1) * bar_s, e_all)
        d = _get(f"/api/v1/contract/kline/{symbol}", {"interval": iv, "start": s, "end": e}) or {}
        t = d.get("time") or []
        if t:
            parts.append(np.column_stack([np.asarray(t, dtype=np.float64) * 1000.0,
                                          np.asarray(d["open"], dtype=np.float64), np.asarray(d["high"], dtype=np.float64),
                                          np.asarray(d["low"], dtype=np.float64), np.asarray(d["close"], dtype=np.float64)]))
        s = e + bar_s
    if not parts:
        return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
    a = np.concatenate(parts)
    a = a[np.argsort(a[:, 0], kind="stable")]
    a = a[np.r_[True, np.diff(a[:, 0]) > 0]]
    a = a[(a[:, 0] >= start_ms) & (a[:, 0] < end_ms)]
    return pd.DataFrame({"timestamp": a[:, 0].astype(np.int64), "Open": a[:, 1], "High": a[:, 2],
                         "Low": a[:, 3], "Close": a[:, 4]})
