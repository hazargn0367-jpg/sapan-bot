"""Forex / metal / endeks / petrol geçmiş verisi (Dukascopy ücretsiz datafeed). Sadece backtest (kullanıcı 23.10 16:30
"forexte de backtest yapalım, 15dk / 30dk / 1s / 2s / 4s"). Arayüz bybit.py / mexc.py ile aynı: top_symbols / norm / klines.

Kaynak: https://datafeed.dukascopy.com/datafeed/{SEMBOL}/{YIL}/{AY-1:02d}/{GÜN:02d}/BID_candles_min_1.bi5 — günlük 1 dakikalık
BID mumları, LZMA sıkıştırılmış; kayıt başına 24 bayt big-endian: gün başından saniye (uint32), açılış, kapanış, en düşük,
en yüksek (int32, fiyat × ölçek), hacim (float32). Fiyat ölçeği önemsiz: bütün hesaplar oran (yüzde, ATR, R) → fiyatlar ham
tamsayı birimde tutulur, fiyat adımı 1. Hafta sonu / tatil dosyaları boş. 1 dk mumlar 15 dk'ya burada çevrilir.
Önbellek: DATA_DIR/fx_cache/{SEMBOL}_{YYYY-MM}.npz (geçmiş aylar değişmez, ikinci test indirmez)."""
import datetime as _dt
import logging
import lzma
import os
import struct
import threading
import time

import numpy as np
import pandas as pd
import requests

import config

log = logging.getLogger(__name__)

BASE = "https://datafeed.dukascopy.com/datafeed"
MAX_RPS = 12
_lock = threading.Lock()
_next_slot = [0.0]
_local = threading.local()
STATS = {"files": 0, "empty": 0, "cached_months": 0, "errors": 0, "swapped": 0}

FX = ["EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD",
      "EURGBP", "EURJPY", "EURCHF", "EURAUD", "EURCAD", "EURNZD",
      "GBPJPY", "GBPCHF", "GBPAUD", "GBPCAD", "GBPNZD",
      "AUDJPY", "AUDCHF", "AUDCAD", "AUDNZD", "CADJPY", "CADCHF", "CHFJPY", "NZDJPY", "NZDCHF", "NZDCAD"]
METAL = ["XAUUSD", "XAGUSD"]
INDEX = ["USA500IDXUSD", "USATECHIDXUSD", "USA30IDXUSD", "DEUIDXEUR", "GBRIDXGBP", "JPNIDXJPY", "FRAIDXEUR"]
OIL = ["LIGHTCMDUSD", "BRENTCMDUSD"]
GROUP = {**{s: "forex" for s in FX}, **{s: "metal" for s in METAL}, **{s: "endeks" for s in INDEX},
         **{s: "petrol" for s in OIL}}


class FxError(RuntimeError):
    pass


def _session():
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = "Mozilla/5.0 (sapan-bot-backtest)"
        _local.s = s
    return s


def _wait_slot():
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot[0])
        _next_slot[0] = slot + 1.0 / MAX_RPS
    if slot > now:
        time.sleep(slot - now)


def _day_file(symbol, day):
    """Bir günün 1 dk mumları: ndarray (n, 5) [ms, açılış, en yüksek, en düşük, kapanış] ya da boş."""
    url = f"{BASE}/{symbol}/{day.year}/{day.month - 1:02d}/{day.day:02d}/BID_candles_min_1.bi5"
    raw = None
    for k in range(5):
        _wait_slot()
        try:
            r = _session().get(url, timeout=30)
        except requests.RequestException as e:
            time.sleep(2 + 2 * k)
            last = str(e)
            continue
        if r.status_code == 404:
            return np.empty((0, 5))
        if r.status_code != 200:
            last = f"HTTP {r.status_code}"
            time.sleep(2 + 3 * k)
            continue
        raw = r.content
        break
    else:
        STATS["errors"] += 1
        log.warning("Dukascopy %s %s alınamadı: %s", symbol, day, last)
        return np.empty((0, 5))
    STATS["files"] += 1
    if not raw:
        STATS["empty"] += 1
        return np.empty((0, 5))
    try:
        data = lzma.decompress(raw)
    except lzma.LZMAError:
        STATS["errors"] += 1
        return np.empty((0, 5))
    n = len(data) // 24
    if n == 0:
        STATS["empty"] += 1
        return np.empty((0, 5))
    rec = np.frombuffer(data[:n * 24], dtype=np.dtype([("t", ">u4"), ("a", ">i4"), ("b", ">i4"), ("c", ">i4"),
                                                       ("d", ">i4"), ("v", ">f4")]))
    t0 = int(_dt.datetime(day.year, day.month, day.day, tzinfo=_dt.timezone.utc).timestamp() * 1000)
    ts = t0 + rec["t"].astype(np.int64) * 1000
    o, c, lo, hi = (rec[x].astype(np.float64) for x in ("a", "b", "c", "d"))
    # Belgelenen sıra: açılış, kapanış, en düşük, en yüksek. Tutmuyorsa (en yüksek < gövde) açılış, en yüksek, en düşük, kapanış dene
    if np.mean(hi >= np.maximum(o, c)) < 0.99 or np.mean(lo <= np.minimum(o, c)) < 0.99:
        o2, h2, l2, c2 = rec["a"].astype(np.float64), rec["b"].astype(np.float64), rec["c"].astype(np.float64), rec["d"].astype(np.float64)
        if np.mean(h2 >= np.maximum(o2, c2)) >= 0.99 and np.mean(l2 <= np.minimum(o2, c2)) >= 0.99:
            o, hi, lo, c = o2, h2, l2, c2
            STATS["swapped"] += 1
    keep = (o > 0) & (hi > 0) & (lo > 0) & (c > 0)
    return np.column_stack([ts, o, hi, lo, c])[keep]


def _to_tf(m1, minutes):
    """1 dk mumlardan UTC hizalı N dk mumlar (eksik dakikalı mumlar da tutulur: forex'te sessiz dakikalarda mum yoktur)."""
    if not len(m1):
        return np.empty((0, 5))
    step = minutes * 60_000
    b = (m1[:, 0] // step).astype(np.int64)
    idx = np.r_[0, np.flatnonzero(np.diff(b)) + 1]
    ends = np.r_[idx[1:], len(m1)]
    out = np.empty((len(idx), 5))
    out[:, 0] = b[idx] * step
    out[:, 1] = m1[idx, 1]
    out[:, 2] = np.maximum.reduceat(m1[:, 2], idx)
    out[:, 3] = np.minimum.reduceat(m1[:, 3], idx)
    out[:, 4] = m1[ends - 1, 4]
    return out


def _cache_dir():
    d = os.path.join(config.data_dir(), "fx_cache")
    os.makedirs(d, exist_ok=True)
    return d


def _month(symbol, y, m):
    """Bir ayın 15 dk mumları (önbellekten ya da indirerek). Bu ay önbelleğe yazılmaz (henüz bitmedi)."""
    path = os.path.join(_cache_dir(), f"{symbol}_{y:04d}-{m:02d}.npz")
    today = _dt.datetime.now(_dt.timezone.utc).date()
    done = (y, m) < (today.year, today.month)
    if done and os.path.exists(path):
        try:
            with np.load(path) as z:
                STATS["cached_months"] += 1
                return z["a"]
        except (OSError, ValueError, KeyError):
            pass
    day = _dt.date(y, m, 1)
    parts = []
    while day.month == m and day <= today:
        if day.weekday() != 5:   # cumartesi her zaman boş
            parts.append(_day_file(symbol, day))
        day += _dt.timedelta(days=1)
    m1 = np.concatenate(parts) if parts else np.empty((0, 5))
    a = _to_tf(m1, 15)
    if done:
        try:
            np.savez_compressed(path, a=a)
        except OSError as e:
            log.warning("fx önbelleğe yazılamadı: %s", e)
    return a


def top_symbols(n=0):
    syms = FX + METAL + INDEX + OIL
    return (syms[:n] if n else syms), {s: 1.0 for s in syms}


def norm(symbol):
    return symbol


def klines(symbol, start_ms, end_ms, tf="15m"):
    """[start_ms, end_ms) 15 dk mumlar (timestamp, Open, High, Low, Close). Sadece 15m üretilir; üst dilimler backtest'te."""
    if symbol not in GROUP or tf != "15m":
        return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
    s = _dt.datetime.fromtimestamp(start_ms / 1000, _dt.timezone.utc)
    e = _dt.datetime.fromtimestamp(end_ms / 1000, _dt.timezone.utc)
    y, m = s.year, s.month
    parts = []
    while (y, m) <= (e.year, e.month):
        parts.append(_month(symbol, y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    a = np.concatenate(parts) if parts else np.empty((0, 5))
    a = a[(a[:, 0] >= start_ms) & (a[:, 0] < end_ms)]
    return pd.DataFrame({"timestamp": a[:, 0].astype(np.int64), "Open": a[:, 1], "High": a[:, 2],
                         "Low": a[:, 3], "Close": a[:, 4]})
