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
_pool = None  # arşiv indirmeleri için ortak iş parçacığı havuzu (ağ beklemesi: aynı anda çok dosya)
POOL_SIZE = 32


def _download_many(urls):
    global _pool
    with _lock:
        if _pool is None:
            from concurrent.futures import ThreadPoolExecutor
            _pool = ThreadPoolExecutor(max_workers=POOL_SIZE)
    return list(_pool.map(_download, urls))
stats = {"files": 0, "missing": 0, "api_ranges": 0, "skipped_recent": 0, "skipped_lead": 0, "mb": 0.0}


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
        raw = zf.read(zf.namelist()[0])
    head = raw[:1]
    skip = 0 if head.isdigit() else 1  # başlık satırı
    if not raw.strip() or (skip and b"\n" not in raw):
        return np.empty(0, np.int64), np.empty(0, np.int64), np.empty((0, 4))
    d = pd.read_csv(io.BytesIO(raw), header=None, skiprows=skip, usecols=[0, 1, 2, 3, 4, 6],
                    dtype={0: np.int64, 1: np.float64, 2: np.float64, 3: np.float64, 4: np.float64, 6: np.int64})
    ts, ct = d[0].to_numpy(np.int64), d[6].to_numpy(np.int64)
    if len(ts) and ts[0] > 10 ** 14:  # mikrosaniye
        ts, ct = ts // 1000, ct // 1000
    return ts, ct, d[[1, 2, 3, 4]].to_numpy(np.float64)


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


def get_range(symbol, interval, start_ms, end_ms, api_max_wait=None, now_ms=None, api_recent=True):
    """start_ms..end_ms arası kapanmış mumlar (DataFrame: timestamp, Open, High, Low, Close).
    api_recent=False: arşivde henüz olmayan son 1-2 günün mumları için Binance API'ye hiç gidilmez
    (backtest canlı taramayla aynı IP'yi kullanıyor; IP engeli canlı bildirimleri de durduruyordu)."""
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

    first_day = _dt(start_ms - start_ms % DAY_MS)

    def days(d0, d1):
        out, d = [], d0
        while _ms(d) < d1:
            out.append(d)
            d += dt.timedelta(days=1)
        return out

    # 1) tamamlanmış aylar: aylık dosyalar (hepsi aynı anda); bu ay: günlük dosyalar
    months, daily_list = [], []
    m = _dt(start_ms).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    while _ms(m) < arch_end:
        nm = _next_month(m)
        if nm <= this_month:
            months.append((m, nm))
        else:
            daily_list += days(max(m, first_day), arch_end)
        m = nm
    for (m, nm), c in zip(months, _download_many([_monthly_url(symbol, interval, m) for m, _ in months])):
        if c is not None:
            use(c, _ms(m), _ms(nm))
        elif m == prev_month:  # geçen ayın dosyası henüz yayınlanmamış olabilir: günlüklere bak
            daily_list = days(max(m, first_day), min(_ms(nm), arch_end)) + daily_list
        else:
            _add("missing")
    # 2) günlük dosyalar (hepsi aynı anda)
    for d, c in zip(daily_list, _download_many([_daily_url(symbol, interval, d) for d in daily_list])):
        if c is None:
            _add("missing")
        else:
            use(c, _ms(d), _ms(d + dt.timedelta(days=1)))

    # Arşivde olmayan kısımlar API'den (bugün dahil)
    first_covered = min((x for x, _ in covered), default=None)
    for a, b in _gaps(start_ms, end_ms, covered):
        if not api_recent and a >= today0 - DAY_MS:
            _add("skipped_recent")
            continue
        try:
            # API engelliyse hiç deneme (engel uzamasın): hemen aşağıdaki karara düş
            if exchanges.blocked_for() > 60:
                raise exchanges.BinanceBlocked(exchanges.blocked_for())
            df = exchanges.get_klines_range(symbol, interval, a, b, max_wait=api_max_wait, limit=499)
        except exchanges.BinanceBlocked:
            if a >= today0 - DAY_MS:
                _add("skipped_recent")  # sadece son 1-2 günün mumları eksik kalır (dünün dosyası geç yayınlanabilir)
                continue
            if first_covered is None or b <= first_covered:
                _add("skipped_lead")  # arşivde ilk veriden önceki kısım: coin o tarihte büyük ihtimalle listelenmemişti
                continue
            # Ortada boşluk: bu coin atlanır (eksik veriyle yanlış sonuç vermesin), backtest devam eder
            raise RuntimeError(f"{symbol}: arşivde boşluk var ve Binance API engelli, coin atlandı")
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
        txt += f", {s['skipped_recent']} coinde son 1-2 günün mumları yok (arşive henüz eklenmemiş; API kullanılmadı)"
    return txt


# ---------------------------------------------------------------- coin listesi (Binance API engelliyken)
S3_LIST = "https://s3-ap-northeast-1.amazonaws.com/data.binance.vision"


def list_symbols():
    """Arşivde günlük verisi olan bütün USDT vadeli coinler (S3 dizin listesi)."""
    import re
    syms, marker = [], ""
    for _ in range(20):
        params = {"delimiter": "/", "prefix": "data/futures/um/daily/klines/"}
        if marker:
            params["marker"] = marker
        r = exchanges._thread_session().get(S3_LIST, params=params, timeout=30)
        r.raise_for_status()
        found = re.findall(r"<Prefix>data/futures/um/daily/klines/([A-Z0-9_]+)/</Prefix>", r.text)
        syms += found
        if "<IsTruncated>true</IsTruncated>" not in r.text or not found:
            break
        m = re.search(r"<NextMarker>([^<]+)</NextMarker>", r.text)
        marker = m.group(1) if m else f"data/futures/um/daily/klines/{found[-1]}/"
    return sorted({s for s in syms if s.endswith("USDT")})


def _quote_volume(content):
    """Günlük (1d) zip'teki USDT hacmi (8. sütun)."""
    with zipfile.ZipFile(io.BytesIO(content)) as zf:
        text = zf.read(zf.namelist()[0]).decode("utf-8", "ignore")
    for line in text.splitlines():
        p = line.split(",")
        if len(p) > 7 and p[0].strip().isdigit():
            return float(p[7])
    return 0.0


def top_symbols(n):
    """Binance API engelliyken coin listesi: arşivdeki coinlerden dünkü (yoksa önceki gün) USDT hacmine göre ilk n.
    Dün dosyası olmayan coinler (işlemden kalkmış) listeye girmez."""
    syms = list_symbols()
    now = _dt(time.time() * 1000)
    for back in (1, 2):
        day = (now - dt.timedelta(days=back)).replace(hour=0, minute=0, second=0, microsecond=0)
        urls = [_daily_url(s, "1d", day) for s in syms]
        vols = {}
        for s, c in zip(syms, _download_many(urls)):
            if c is not None:
                try:
                    vols[s] = _quote_volume(c)
                except Exception:
                    pass
        if len(vols) >= 0.5 * len(syms):
            break
    ranked = sorted(vols, key=vols.get, reverse=True)
    return ranked[:n] if n else ranked
