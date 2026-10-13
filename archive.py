"""
Backtest verisi: Binance'in dosya arşivi (data.binance.vision).

Arşivdeki aylık/günlük zip dosyaları Binance API'sinin istek sınırına ve IP engeline tabi değil.
- Tamamlanmış aylar: aylık dosya
- Bu ay (ve henüz yayınlanmamış geçen ay): günlük dosyalar (dünün dosyası bazen geç yayınlanır)
- Bugünün mumları ve arşivde bulunamayan kısımlar: API (en az ağırlıkla, limit 499)
Binance API'si engelliyse sadece son 1-2 günün eksik mumları atlanır (dönem biraz erken biter);
arşivde olmayan daha eski bir kısım API'den de alınamazsa hata verilir (eksik veriyle sonuç çıkmasın).
"""

import datetime as dt
import io
import logging
import threading
import time
import zipfile

import numpy as np
import pandas as pd
import requests

import exchanges

log = logging.getLogger("bot")

BASE = "https://data.binance.vision/data/futures/um"
DAY_MS = 86_400_000

_lock = threading.Lock()
stats = {"files": 0, "missing": 0, "api_ranges": 0, "skipped_recent": 0, "mb": 0.0}


def _add(key, v=1):
    with _lock:
        stats[key] += v


def _ms(d):
    return int(d.timestamp() * 1000)


def _dt(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc)


def parse_zip(content):
    """Arşiv zip'i -> (açılış zamanı, kapanış zamanı, OHLC). Başlık satırı olan/olmayan iki biçim de,
    milisaniye/mikrosaniye zaman damgası da okunur."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", "ignore")
    ts, ct, ohlc = [], [], []
    for line in text.splitlines():
        p = line.split(",")
        if len(p) < 7 or not p[0].strip().isdigit():
            continue  # başlık ya da boş satır
        t, c = int(p[0]), int(p[6])
        if t > 10 ** 14:  # mikrosaniye
            t //= 1000
            c //= 1000
        ts.append(t)
        ct.append(c)
        ohlc.append((float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    return (np.array(ts, dtype=np.int64), np.array(ct, dtype=np.int64),
            np.array(ohlc, dtype=np.float64).reshape(-1, 4))


def _download(url, why=None):
    """Dosyanın içeriği; yoksa (404) ya da 3 denemede alınamazsa None.
    why (liste) verilirse son hatanın kısa açıklaması eklenir."""
    for attempt in range(3):
        try:
            r = exchanges._thread_session().get(url, timeout=30)
        except requests.RequestException as e:
            if why is not None:
                why.append(f"{type(e).__name__}: {str(e)[:120]}")
            time.sleep(1 + attempt)
            continue
        if r.status_code == 404:
            if why is not None:
                why.append("HTTP 404 (dosya yok)")
            return None
        if r.status_code != 200:
            if why is not None:
                why.append(f"HTTP {r.status_code}")
            time.sleep(1 + attempt)
            continue
        _add("mb", len(r.content) / 2 ** 20)
        return r.content
    return None


def probe():
    """Arşive ulaşılabiliyor mu: (True/False, açıklama). Önce BTC'nin geçen ayki aylık dosyası,
    olmazsa 2 gün önceki günlük dosyası denenir."""
    now = _dt(time.time() * 1000)
    last_month = (now.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    why_m, why_d = [], []
    c = _download(_monthly_url("BTCUSDT", "15m", last_month), why_m)
    if c is not None:
        try:
            n = len(parse_zip(c)[0])
            return n > 0, f"aylık dosya {n} mum"
        except Exception as e:
            why_m.append(f"zip okunamadı: {e}")
    c = _download(_daily_url("BTCUSDT", "15m", now - dt.timedelta(days=2)), why_d)
    if c is not None:
        try:
            n = len(parse_zip(c)[0])
            return n > 0, f"aylık dosya yok ({why_m[-1] if why_m else '?'}), günlük var ({n} mum)"
        except Exception as e:
            why_d.append(f"zip okunamadı: {e}")
    return False, f"aylık: {why_m[-1] if why_m else '?'}; günlük: {why_d[-1] if why_d else '?'}"


def _monthly_url(symbol, interval, d):
    return f"{BASE}/monthly/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m}.zip"


def _daily_url(symbol, interval, d):
    return f"{BASE}/daily/klines/{symbol}/{interval}/{symbol}-{interval}-{d:%Y-%m-%d}.zip"


def _next_month(d):
    return (d.replace(day=1) + dt.timedelta(days=32)).replace(day=1)


def _gaps(start, end, covered):
    """[start, end) aralığında dosyalarla kapsanmayan parçalar (komşular birleştirilir)."""
    out, cur = [], start
    for a, b in sorted(covered):
        if b <= cur:
            continue
        if a > cur:
            out.append((cur, min(a, end)))
        cur = max(cur, b)
        if cur >= end:
            break
    if cur < end:
        out.append((cur, end))
    return [(a, b) for a, b in out if b > a]


def get_range(symbol, interval, start_ms, end_ms, api_max_wait=None, now_ms=None):
    """start_ms..end_ms arası kapanmış mumlar (DataFrame: timestamp, Open, High, Low, Close)."""
    now_ms = now_ms or int(time.time() * 1000)
    end_ms = min(end_ms, now_ms)
    today0 = now_ms // DAY_MS * DAY_MS
    this_month = _dt(now_ms).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month = (this_month - dt.timedelta(days=1)).replace(day=1)
    arch_end = min(end_ms, today0)  # bugün her zaman API'den

    parts, covered = [], []

    def use(content, a, b):
        ts, ct, ohlc = parse_zip(content)
        parts.append((ts, ct, ohlc))
        covered.append((a, b))
        _add("files")

    def daily(d0, d1):
        d = d0
        while _ms(d) < d1:
            nd = d + dt.timedelta(days=1)
            c = _download(_daily_url(symbol, interval, d))
            if c is None:
                _add("missing")
            else:
                use(c, _ms(d), _ms(nd))
            d = nd

    m = _dt(start_ms).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while _ms(m) < arch_end:
        nm = _next_month(m)
        if nm <= this_month:  # tamamlanmış ay
            c = _download(_monthly_url(symbol, interval, m))
            if c is not None:
                use(c, _ms(m), _ms(nm))
            elif m == prev_month:  # geçen ayın dosyası henüz yayınlanmamış olabilir: günlüklere bak
                daily(max(m, _dt(start_ms - start_ms % DAY_MS)), min(_ms(nm), arch_end))
            else:
                _add("missing")
        else:  # bu ay: günlük dosyalar (dün dahil)
            daily(max(m, _dt(start_ms - start_ms % DAY_MS)), arch_end)
        m = nm

    # Arşivde olmayan kısımlar API'den (bugün dahil)
    for a, b in _gaps(start_ms, end_ms, covered):
        try:
            df = exchanges.get_klines_range(symbol, interval, a, b, max_wait=api_max_wait, limit=499)
        except exchanges.BinanceBlocked:
            if a >= today0 - DAY_MS:
                _add("skipped_recent")  # sadece son 1-2 günün mumları eksik kalır (dünün dosyası geç yayınlanabilir)
                continue
            raise
        _add("api_ranges")
        if not df.empty:
            ts = df["timestamp"].values.astype(np.int64)
            parts.append((ts, ts + (int(interval.rstrip("m")) * 60_000 - 1 if interval.endswith("m") else 0),
                          df[["Open", "High", "Low", "Close"]].values.astype(np.float64)))

    if not parts:
        return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
    ts = np.concatenate([p[0] for p in parts])
    ct = np.concatenate([p[1] for p in parts])
    ohlc = np.vstack([p[2] for p in parts])
    keep = (ts >= start_ms) & (ts < end_ms) & (ct < now_ms)
    df = pd.DataFrame({"timestamp": ts[keep], "Open": ohlc[keep, 0], "High": ohlc[keep, 1],
                       "Low": ohlc[keep, 2], "Close": ohlc[keep, 3]})
    return df.drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)


def summary():
    s = dict(stats)
    txt = f"Veri: {s['files']} arşiv dosyası ({s['mb']:.0f}MB), {s['api_ranges']} API parçası"
    if s["skipped_recent"]:
        txt += f", {s['skipped_recent']} coinde son 1-2 günün mumları alınamadı (Binance engeli)"
    return txt
