"""
Binance vadeli (USDT-M perpetual) veri çekme.

Bütün istekler tek bir yoldan (_get) geçer:
- Binance dakikalık ağırlık sınırı (2400) IP başınadır. Bot ve backtest ayrı programlar olduğu için
  "bekle" zamanı /tmp'deki bir dosyada ortak tutulur: biri sınıra takılınca ikisi de bekler.
- 429 (istek sınırı) ve 418 (IP geçici engeli) gelirse Binance'in söylediği süre (Retry-After) kadar
  HİÇ istek atılmaz. Engel sürerken istek atmaya devam etmek engeli uzatır.
- Engel uzun sürecekse BinanceBlocked hatası verilir (backtest 0 coinle "bitti" demesin, canlı tarama
  saatlerce takılmasın).
"""

import logging
import os
import threading
import time

import numpy as np
import pandas as pd
import requests

log = logging.getLogger("bot")

BASE_URL = "https://fapi.binance.com"
KLINE_LIMIT = 499  # Binance'te 100-499 arası mum = 2 ağırlık (rate limit dostu)
WEIGHT_LIMIT = 2400
WEIGHT_SOFT_LIMIT = 2000  # buna yaklaşınca dakika dolana kadar beklenir (canlı bota pay kalır)
PAUSE_FILE = "/tmp/binance_pause"
LIVE_SCAN_WINDOW = 120  # her 15dk'lık mum kapanışından sonraki 120 sn canlı taramaya ayrılır


class BinanceBlocked(RuntimeError):
    """Binance istekleri uzun süre bekletiliyor (IP engeli ya da istek sınırı)."""

    def __init__(self, seconds, reason=""):
        self.seconds = seconds
        mins = max(1, int(round(seconds / 60)))
        super().__init__(f"Binance bu sunucunun IP'sini geçici olarak engelledi / sınırladı, "
                         f"yaklaşık {mins} dk sürecek{(' (' + reason + ')') if reason else ''}")


_local = threading.local()
_pause_lock = threading.Lock()
_pause_until = 0.0
_status = {"weight": None, "weight_at": None, "last_block": None, "last_block_at": None, "requests": 0}


def _thread_session():
    if not hasattr(_local, "session"):
        _local.session = requests.Session()
    return _local.session


# ---------------------------------------------------------------- ortak bekleme
def _file_pause():
    try:
        with open(PAUSE_FILE) as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def pause_until():
    """Bu program ya da diğeri (bot/backtest) için Binance'e istek atılmayacak son an."""
    return max(_pause_until, _file_pause())


def blocked_for():
    """Kaç saniye daha istek atılmayacak (0 = serbest)."""
    return max(0.0, pause_until() - time.time())


def _set_pause(until, reason, warn=True):
    global _pause_until
    with _pause_lock:
        if until > _pause_until:
            _pause_until = until
            (log.warning if warn else log.info)("%s: Binance istekleri %d sn bekletiliyor", reason, int(until - time.time()))
        try:
            if until > _file_pause():
                tmp = f"{PAUSE_FILE}.{os.getpid()}"
                with open(tmp, "w") as f:
                    f.write(str(until))
                os.replace(tmp, PAUSE_FILE)
        except OSError:
            pass


def _pause_all(seconds, reason):
    _set_pause(time.time() + seconds, reason)


def _wait_pause(max_wait=None):
    delay = blocked_for()
    if delay <= 0:
        return
    if max_wait is not None and delay > max_wait:
        raise BinanceBlocked(delay, _status["last_block"] or "")
    time.sleep(delay)


def _wait_if_paused(max_wait=None):
    """Sadece backtest kullanır: sınıra yaklaşıldıysa ya da canlı tarama zamanıysa
    (15dk'lık mum kapanışından sonraki ilk 120 sn) bekler."""
    _wait_pause(max_wait)
    sec = time.time() % 900
    if sec < LIVE_SCAN_WINDOW:
        time.sleep(LIVE_SCAN_WINDOW - sec)


def _throttle(res):
    """Dakikalık ağırlık (IP'nin toplamı) sınıra yaklaşınca dakika dolana kadar herkes bekler."""
    try:
        used = int(res.headers.get("X-MBX-USED-WEIGHT-1M", "0") or 0)
    except ValueError:
        return
    if used:
        _status.update(weight=used, weight_at=time.time())
    if used > WEIGHT_SOFT_LIMIT:
        _set_pause(time.time() + (61 - time.gmtime().tm_sec), f"İstek sınırına yaklaşıldı ({used})", warn=False)


def _get(path, params=None, timeout=15, max_wait=None, live_window=False):
    """Binance'e GET. 418/429'da Retry-After kadar herkes bekler; bekleme max_wait'ten uzunsa
    BinanceBlocked. live_window=True: backtest canlı taramanın penceresinde bekler."""
    for attempt in range(3):
        if live_window:
            _wait_if_paused(max_wait)
        else:
            _wait_pause(max_wait)
        res = _thread_session().get(f"{BASE_URL}{path}", params=params, timeout=timeout)
        _status["requests"] += 1
        if res.status_code in (418, 429):
            try:
                secs = int(res.headers.get("Retry-After", "60") or 60)
            except ValueError:
                secs = 60
            reason = "IP engeli (418)" if res.status_code == 418 else "istek sınırı (429)"
            _status.update(last_block=reason, last_block_at=time.time())
            _pause_all(secs, f"Binance {reason}")
            continue
        res.raise_for_status()
        _throttle(res)
        return res
    raise BinanceBlocked(blocked_for(), _status["last_block"] or "")


def status_line():
    """/durum için Binance bağlantı durumu."""
    hhmm = lambda t: time.strftime("%H:%M", time.gmtime(t + 3 * 3600))
    wait = blocked_for()
    if wait > 70:
        line = f"⛔ Binance: istekler {hhmm(time.time() + wait)}'e kadar bekletiliyor ({_status['last_block'] or 'sınır'})"
    else:
        line = "🔗 Binance: erişim normal"
    if _status["weight"] is not None:
        line += f"\nSon görülen IP kullanımı {_status['weight']}/{WEIGHT_LIMIT} ({hhmm(_status['weight_at'])})"
    if _status["last_block_at"]:
        line += f"\nSon engel: {_status['last_block']} {hhmm(_status['last_block_at'])}"
    return line


def probe_weight():
    """Tek hafif istek (ağırlık 1) ile IP'nin şu anki dakikalık kullanımını ölçer.
    Bizim tarama yokken kullanım yüksekse IP'yi başka uygulamalar da kullanıyor demektir."""
    if blocked_for() > 0:
        return None
    try:
        res = _get("/fapi/v1/time", timeout=5, max_wait=0)
        return int(res.headers.get("X-MBX-USED-WEIGHT-1M", "0") or 0)
    except Exception:
        return None


# ---------------------------------------------------------------- veri
def fetch_symbols(max_wait=None):
    """İşlemde olan tüm USDT vadeli (perpetual) coinler. Hata olursa hata verir."""
    res = _get("/fapi/v1/exchangeInfo", timeout=15, max_wait=max_wait)
    return sorted(
        s["symbol"]
        for s in res.json().get("symbols", [])
        if s.get("quoteAsset") == "USDT"
        and s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
    )


def get_symbols():
    """fetch_symbols, hata olursa boş liste (temas taraması için)."""
    try:
        return fetch_symbols(max_wait=60)
    except Exception as e:
        log.error("Binance coin listesi alınamadı: %s", e)
        return []


def get_top_symbols(n, max_wait=None):
    """24 saatlik USDT hacmine göre en büyük n vadeli coin (sadece işlemdekiler)."""
    tradable = set(fetch_symbols(max_wait))
    res = _get("/fapi/v1/ticker/24hr", timeout=20, max_wait=max_wait)
    rows = [r for r in res.json() if r.get("symbol") in tradable]
    rows.sort(key=lambda r: float(r.get("quoteVolume") or 0), reverse=True)
    return [r["symbol"] for r in rows[:n]]


def get_tick_sizes(max_wait=None):
    """Her coinin en küçük fiyat adımı ("1 tık"), örn. {"BTCUSDT": 0.1}."""
    res = _get("/fapi/v1/exchangeInfo", timeout=15, max_wait=max_wait)
    ticks = {}
    for s in res.json().get("symbols", []):
        for f in s.get("filters", []):
            if f.get("filterType") == "PRICE_FILTER":
                ticks[s["symbol"]] = float(f["tickSize"])
    return ticks


def get_klines_range(symbol, interval, start_ms, end_ms, yield_live=True, max_wait=None):
    """Geçmiş mum verisi (sadece kapanmış mumlar), sayfa sayfa çeker.
    Her sayfa hemen sayı dizisine çevrilir (ham JSON listeleri coin başına ~8MB tutuyordu)."""
    parts = []
    cursor = start_ms
    while cursor < end_ms:
        res = _get("/fapi/v1/klines",
                   params={"symbol": symbol, "interval": interval,
                           "startTime": cursor, "endTime": end_ms, "limit": 1000},
                   timeout=20, max_wait=max_wait, live_window=yield_live)
        batch = res.json()
        if not batch:
            break
        n_batch = len(batch)
        cursor = int(batch[-1][0]) + 1
        parts.append((np.array([k[0] for k in batch], dtype=np.int64),
                      np.array([k[6] for k in batch], dtype=np.int64),
                      np.array([k[1:5] for k in batch], dtype=np.float64)))
        del batch, res
        if n_batch < 1000:
            break

    if not parts:
        return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
    ts = np.concatenate([p[0] for p in parts])
    close_time = np.concatenate([p[1] for p in parts])
    ohlc = np.vstack([p[2] for p in parts])
    keep = close_time < int(time.time() * 1000)  # açık mumu at
    return pd.DataFrame({
        "timestamp": ts[keep], "Open": ohlc[keep, 0], "High": ohlc[keep, 1],
        "Low": ohlc[keep, 2], "Close": ohlc[keep, 3],
    }).drop_duplicates("timestamp").reset_index(drop=True)


def get_klines(symbol, interval, max_wait=120):
    """Binance vadeli mum verisi (canlı tarama). Son satır şu an açık olan (canlı) mumdur.
    Binance uzun süre engelliyse beklemez, None döner (tarama saatlerce takılmasın)."""
    try:
        res = _get("/fapi/v1/klines", params={"symbol": symbol, "interval": interval, "limit": KLINE_LIMIT},
                   timeout=10, max_wait=max_wait)
        rows = res.json()
    except Exception as e:
        log.debug("%s %s verisi alınamadı: %s", symbol, interval, e)
        return None
    if not rows:
        return None
    return pd.DataFrame({
        "timestamp": [int(k[0]) for k in rows],
        "Open": [float(k[1]) for k in rows],
        "High": [float(k[2]) for k in rows],
        "Low": [float(k[3]) for k in rows],
        "Close": [float(k[4]) for k in rows],
    })
