"""
BACKTEST - geçmiş Binance vadeli verisinde stratejiyi test eder.

Render > Shell'de çalıştır:
    nohup python backtest.py > backtest.log 2>&1 &

Seçenekler:
    --days 7                       kaç günlük veri (varsayılan 7)
    --symbols NEARUSDT,QNTUSDT     sadece bu coinler (varsayılan: hepsi)
    --tf 15m,30m                   zaman dilimleri (varsayılan: 15m)
    --top 500                      hacme göre ilk 500 coin (0 = hepsi)
    --rr 2.5                       TP = riskin kaç katı (varsayılan 2)
    --be 1                         1R kârda stop girişe (varsayılan kapalı)
    --ago 30                       dönemi 30 gün geriye kaydır (önceki ay)
    --compare [hepsi|yeni|koruma]  ayar setini tek seferde karşılaştır
    --max-open 3 --cluster 5 --btc portföy korumaları
    --no-filters                   ek filtreleri kapat (seans, stop %0.5-3)
    --atr-min 0.875                stop en az 0.875 ATR olsun

Bitince Telegram'a özet mesaj ve tüm setup'ların listesi (CSV) gelir.
"""

import argparse
import html
import logging
import os
import shutil
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import gc

import numpy as np
import pandas as pd

import archive
import bybit
import config
import charts
import live_setups
import strategy as st
import trade_rules as tr
import exchanges
from exchanges import BinanceBlocked, fetch_symbols, get_klines_range, get_tick_sizes, get_top_symbols
from telegram import send_document, send_message, send_photos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

CACHE_DIR = "/tmp/bt_cache"
WARMUP = 300  # ilk mumlarda EMA100 oturmadığı için atlanır
FETCH_THREADS = 16  # aynı anda kaç coinin verisi çekilsin (arşiv dosyaları sınırsız; API kısmı ortak sınıra uyar)
MAX_IN_FLIGHT = 20  # bellekte aynı anda en fazla kaç coinin ham verisi dursun
BAN_WAIT = 600  # Binance IP engeli/sınırı en fazla bu kadar sn sürecekse beklenir, daha uzunsa backtest durur
USE_ARCHIVE = True  # geçmiş veri Binance dosya arşivinden (API sınırı/engeli yok); --api ile kapatılır
EXCHANGE = "binance"  # --exchange bybit: mumlar ve coin listesi Bybit'ten (diske kaydedilmez)
BINANCE_SET = set()   # Bybit testinde canlı botun Binance coinleri (bybit.norm adlarıyla)
DEFAULT_COINS = "all"  # Bybit testinde "coins" anahtarı olmayan ayarlar: bybit seti dışında "binance" (aynı coinler)
TZ = "Europe/Istanbul"

# Senin fotoğraflarla anlattığın örnekler (Türkiye saati, temas mumu)
EXAMPLES = [
    ("NEARUSDT", "15m", "2026-10-10 05:00"),
    ("QNTUSDT", "15m", "2026-10-01 23:00"),
]

STATUS_TR = {
    "no_close": "Temas mumu EMA20'nin yanlış tarafında kapattı",
    "cancel_touch": "Onaydan önce temas mumunun ucu kırıldı",
    "no_confirm": "3 mumda onay gelmedi",
    "atr": "Stop mesafesi 1.5 ATR'den büyük",
    "atr_min": "Stop mesafesi ATR alt sınırının altında",
    "wick": "Onay mumunun ters iğnesi uzun",
    "no_prior_touch": "Trend teyidi yok (önceden EMA20 teması yok)",
    "dirty_pivot": "Son tepe/dip temiz değil (destek/direnç oluşmuş)",
    "touch_body": "Temas mumu fitil mumu değil (gövdeyle değmiş)",
    "quiet": "Temas 03:00-07:00 TR arasında",
    "no_room": "Giriş önceki tepe/dibe çok yakın (önünde yer yok)",
    "structure_break": "Düzeltme önceki düzeltmeyi kırmış (yapı bozuk)",
    "pivot_wick": "Tepe/dip mumunun iğnesi çok uzun",
    "support": "Dip/tepeden sonra iğneli mumlar (destek/direnç oluşmuş)",
    "touch_tail": "Temas mumunun ters iğnesi uzun (EMA20'den dönüş zayıf)",
    "no_close_below": "Temas mumu EMA20'nin öbür tarafında kapatmadı (dönüş varyasyonu)",
    "no_reclaim": "Sonraki mum EMA20'nin doğru tarafında kapatmadı (dönüş varyasyonu)",
    "pivot_leg": "Tepe/dip tek mumluk fırlamayla yapılmış (temiz trend yok)",
    "not_clean": "Trend temiz değil (bacak / EMA açılımı şartı tutmadı)",
    "btc_corr": "Coin BTC'ye çok benzer hareket ediyor (korelasyon)",
    "touch_prev": "Temas mumu önceki mumun dibini (SHORT) / tepesini (LONG) geçti",
    "spike_top": "Sivri tepe: tepe / dip 2 dev mumla yapılmış",
    "skip_btc": "BTC ters yönde (portföy koruması)",
    "skip_cluster": "Aynı mumda çok sayıda sinyal (portföy koruması)",
    "skip_open": "Açık işlem sınırı dolu (portföy koruması)",
    "min_risk": "Stop mesafesi çok dar",
    "max_risk": "Stop mesafesi %3'ten geniş",
    "session": "Temas 00-08 UTC (Asya seansı)",
    "cancel_confirm": "Girişten önce onay mumunun ucu kırıldı",
    "no_entry": "2 mumda girişe gelmedi",
    "chase": "Kapanış girişten çok uzakta (kovalamaca)",
    "wicky": "Temastan önceki mumlar çok iğneli (git-gel)",
    "choppy": "Temastan önceki mumlar büyük gövdeyle sürekli yön değiştiriyor (dalgalı)",
    "big_touch": "Dönüşte temas mumunun gövdesi çok büyük",
    "wide_pivot": "Dip/tepenin 1 ATR yakınında çok mum (taban)",
    "no_ema200": "EMA100 ile EMA200 sıralı değil",
    "zigzag": "Düzeltme zigzag yaparak gelmiş (temiz değil)",
    "no_new_high": "Yakın zamanda yeni zirve/dip yok",
    "win": "TP",
    "loss": "Stop",
    "be": "Başabaş / erken çıkış",
    "open": "Açık (veri bitti)",
    "pending": "Beklemede (veri bitti)",
}

COND_TR = [
    ("trend", "Net trend (EMA20/50/100)"),
    ("pivot_recent", "Tepe/dip son 30 mumda"),
    ("body_break", "Gövde kapanışlı kırılım"),
    ("first_touch", "EMA20'ye ilk temas"),
    ("clean_pullback", "En fazla 2 ters mum"),
    ("touch", "İğne EMA20'ye değdi"),
    ("stoch", "Stoch şartı"),
]


# ---------------------------------------------------------------- veri
def _trim_memory():
    """Python'un bıraktığı ama glibc'nin tuttuğu belleği işletim sistemine geri verir."""
    try:
        import ctypes
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:
        pass


def period(days, ago):
    """Test edilen dönemin başlangıç/bitiş zamanı (ms)."""
    end_ms = int(time.time() * 1000) - ago * 86400 * 1000
    return end_ms - days * 86400 * 1000, end_ms


def clean_cache():
    """Eski sürümlerin /tmp'ye yazdığı veri önbelleğini sil (/tmp bellekte tutuluyorsa RAM yer)."""
    shutil.rmtree(CACHE_DIR, ignore_errors=True)


def _data_dir():
    import config
    return config.data_dir()


KLINE_CACHE = os.path.join(_data_dir(), "kline_cache")

def _universe_path():
    return os.path.join(_data_dir(), "universe.json")


def _save_universe(symbols, ticks):
    try:
        import json
        with open(_universe_path(), "w") as f:
            json.dump({"t": time.time(), "symbols": symbols, "ticks": ticks}, f)
    except (OSError, TypeError):
        pass


def _load_universe():
    """Son başarılı coin listesi (son 3 gün içindeyse)."""
    try:
        import json
        with open(_universe_path()) as f:
            u = json.load(f)
        if time.time() - u["t"] < 3 * 86400:
            return u["symbols"], u["ticks"]
    except (OSError, ValueError, KeyError):
        pass
    return None
  # coin başına mum verisi: sonraki testler sadece yeni mumları çeker
BASE_TF = "15m"  # indirilen veri: 15m (30m bundan üretilir) ya da 5m
BAR_MS = 15 * 60 * 1000


OLD_DAYS = 400  # dönem sonu bundan eskiyse veri diske kaydedilmeden doğrudan arşivden alınır
WARMUP_FACTOR = 1  # 1s/4s testinde EMA100'ün oturması için temel veride WARMUP x (4s / 15dk) mum geriden başlanır


def set_base_tf(tf):
    global BASE_TF, BAR_MS
    BASE_TF = tf
    BAR_MS = int(tf[:-1]) * 60 * 1000


def _fetch_range(symbol, start_ms, end_ms):
    if EXCHANGE == "bybit":
        return bybit.klines(symbol, start_ms, end_ms, BASE_TF)
    if USE_ARCHIVE:
        return archive.get_range(symbol, BASE_TF, start_ms, end_ms, api_max_wait=BAN_WAIT, api_recent=False)
    return get_klines_range(symbol, BASE_TF, start_ms, end_ms, max_wait=BAN_WAIT)


def _cache_path(symbol):
    return os.path.join(KLINE_CACHE, f"{symbol}_{BASE_TF}.npz")


def _to_arr(df):
    if df is None or df.empty:
        return np.empty((0, 5))
    return df[["timestamp", "Open", "High", "Low", "Close"]].to_numpy(dtype=np.float64)


def load_15m(symbol, days, ago=0):
    """Önce diskteki veri; eksik kalan baş/son kısım Binance'ten çekilir ve kayda eklenir.
    Kayıt her zaman kesintisizdir: span = çekilmiş aralık (coin o tarihte yoksa da çekilmiş sayılır)."""
    start_ms, end_ms = period(days, ago)
    start_ms -= WARMUP * BAR_MS * WARMUP_FACTOR
    if EXCHANGE == "bybit" or end_ms < time.time() * 1000 - OLD_DAYS * 86400 * 1000:
        # Çok eski dönem (ör. 2-3 yıl önce): sadece o aylar arşivden indirilir, kayda eklenmez
        # (kayıt kesintisiz tutulduğu için aradaki yılların hepsi indirilip diske yazılırdı)
        df = _fetch_range(symbol, start_ms, end_ms)
        if df is None or df.empty:
            return pd.DataFrame({"timestamp": np.array([], dtype=np.int64), "Open": [], "High": [], "Low": [], "Close": []})
        return df[(df["timestamp"] >= start_ms) & (df["timestamp"] < end_ms)].reset_index(drop=True)
    path = _cache_path(symbol)
    arr = span = None
    try:
        with np.load(path) as z:
            arr, span = z["data"], [int(z["span"][0]), int(z["span"][1])]
    except (OSError, ValueError, KeyError):
        pass
    if arr is None:
        arr, span, changed = _to_arr(_fetch_range(symbol, start_ms, end_ms)), [start_ms, end_ms], True
    else:
        changed = False
        if start_ms < span[0]:  # baş kısım eksik: kayıt başına kadar çek (boşluk kalmasın)
            head = _to_arr(_fetch_range(symbol, start_ms, span[0]))
            arr = np.vstack([head[head[:, 0] < span[0]], arr])
            span[0], changed = start_ms, True
        if end_ms > span[1] + 2 * BAR_MS:  # yeni mumlar
            last = int(arr[-1, 0]) if len(arr) else span[1]
            tail = _to_arr(_fetch_range(symbol, last + 1, end_ms))
            arr = np.vstack([arr, tail[tail[:, 0] > last]])
            span[1], changed = end_ms, True
    if changed:
        _save_cache(path, arr, span)
    sel = arr[(arr[:, 0] >= start_ms) & (arr[:, 0] < end_ms)]
    return pd.DataFrame({"timestamp": sel[:, 0].astype(np.int64), "Open": sel[:, 1], "High": sel[:, 2],
                         "Low": sel[:, 3], "Close": sel[:, 4]})


DISK_MIN_FREE = 150 * 1024 * 1024  # diskte bundan az yer kalırsa veri kaydedilmez (canlı günlük de aynı diskte)
_disk_warned = False


def _save_cache(path, arr, span):
    global _disk_warned
    tmp = f"{path}.{os.getpid()}.tmp.npz"
    try:
        os.makedirs(KLINE_CACHE, exist_ok=True)
        if shutil.disk_usage(KLINE_CACHE).free - arr.nbytes < DISK_MIN_FREE:
            if not _disk_warned:
                log.warning("Diskte yer az, veri kaydedilmiyor (test yine çalışır, sonraki test veriyi tekrar indirir)")
                _disk_warned = True
            return
        np.savez(tmp, data=arr, span=np.array(span, dtype=np.int64))
        os.replace(tmp, path)
    except OSError as e:
        log.warning("Veri diske kaydedilemedi: %s", e)
        try:
            os.remove(tmp)
        except OSError:
            pass


DISK_LOW = 300 * 1024 * 1024  # diskte bundan az boş yer kalınca diğer zaman diliminin verisi silinir


def drop_other_tf_cache():
    """Disk dolmak üzereyse kullanılmayan zaman diliminin (15m testinde 5m) kayıtlı verisini sil.
    Yer varsa ikisi de kalır: 5m ve 15m testleri sırayla çalıştırılınca her seferinde yeniden indirilmesin."""
    other = "_5m.npz" if BASE_TF == "15m" else None
    if not other or not os.path.isdir(KLINE_CACHE):
        return
    try:
        if shutil.disk_usage(KLINE_CACHE).free > DISK_LOW:
            return
    except OSError:
        return
    freed = 0
    for name in os.listdir(KLINE_CACHE):
        if name.endswith(other) or ".tmp.npz" in name:
            p = os.path.join(KLINE_CACHE, name)
            try:
                freed += os.path.getsize(p)
                os.remove(p)
            except OSError:
                pass
    if freed:
        log.info("Kullanılmayan 5m verisi silindi: %.0f MB", freed / 1e6)


def archive_reachable():
    """(ulaşılıyor mu, açıklama)"""
    try:
        return archive.probe()
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def to_30m(df15):
    """15dk mumları Binance'in 30dk mumlarıyla aynı şekilde birleştirir."""
    return resample_tf(df15, 30)


def resample_tf(df15, minutes):
    """Temel mumları (15dk) Binance'in 30dk / 1s / 4s mumlarıyla aynı şekilde birleştirir (UTC 00:00'dan hizalı).
    Eksik parçası olan mum (coin yeni listelenmiş ya da veri boşluğu) atılır."""
    base_min = BAR_MS // 60000
    d = df15.copy()
    d.index = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    g = d.resample(f"{minutes}min", origin="epoch", label="left")
    out = pd.DataFrame({
        "Open": g["Open"].first(), "High": g["High"].max(),
        "Low": g["Low"].min(), "Close": g["Close"].last(), "n": g["Open"].count(),
    })
    out = out[out["n"] == minutes // base_min].drop(columns="n")
    out["timestamp"] = (out.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
    return out.reset_index(drop=True)[["timestamp", "Open", "High", "Low", "Close"]]


def prepare(df):
    df = st.add_indicators(df.reset_index(drop=True))
    return tr.add_atr(df)


def fmt_time(ts_ms):
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").tz_convert(TZ).strftime("%d.%m.%Y %H:%M")


def fmt_utc(ts_ms):
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").strftime("%H:%M")


# ---------------------------------------------------------------- test
def candidate_bars(df):
    """Hızlı ön eleme: sadece trend + temas + stoch tutan mumlar incelenir
    (asıl kontrol yine strategy.evaluate_at ile yapılır)."""
    e20, e50, e100 = df["EMA20"], df["EMA50"], df["EMA100"]
    up = (e20 > e50 * (1 + st.EMA_GAP)) & (e50 > e100 * (1 + st.EMA_GAP))
    down = (e20 < e50 * (1 - st.EMA_GAP)) & (e50 < e100 * (1 - st.EMA_GAP))
    long_c = up & (df["Low"] <= e20 * st.TOLERANCE_LONG) & (df["Stoch_K"] < st.STOCH_LONG_MAX)
    short_c = down & (df["High"] >= e20 * st.TOLERANCE_SHORT) & (df["Stoch_K"] > st.STOCH_SHORT_MIN)
    idx = np.flatnonzero((long_c | short_c).values)
    return idx[idx >= WARMUP]


def find_signals(df):
    """Temas sinyalleri (işlem ayarlarından bağımsız, bir kez hesaplanır)."""
    out = []
    arr = st.arrays(df)
    for i in candidate_bars(df):
        sig = st.evaluate_at(df, i, arr)
        if sig:
            out.append((int(i), sig["side"]))
    return out


TRADED = ("win", "loss", "be", "open")


def run_df(df, symbol, tf, tick, signals=None, with_ctx=True, trades_only=False, status_counter=None):
    """trades_only: sadece işleme dönen setup'lar saklanır (500 coinde on binlerce satır bellek yer);
    status_counter verilirse bütün setup'ların durumları sayılır (rapordaki huni için)."""
    if signals is None:
        signals = find_signals(df)
    rows = []
    next_free = 0
    ts = df["timestamp"].values
    for i, side in signals:
        if i < next_free:
            continue
        r = tr.simulate(df, i, side, tick)
        if status_counter is not None:
            status_counter[r["status"]] += 1
        if trades_only and r["status"] not in TRADED:
            continue
        row = {
            "coin": symbol, "zaman_dilimi": tf, "yon": side,
            "temas": fmt_time(ts[i]), "temas_utc": fmt_utc(ts[i]), "durum": r["status"],
            "_touch_ts": int(ts[i]),
            "sonuc": STATUS_TR[r["status"]],
        }
        if r.get("two_bar"):
            row["iki_mum"] = 1
        if tr.ENTRY_MODE == "both" and "mode" in r:
            row["varyasyon"] = "dönüş" if r["mode"] == "reclaim" else "klasik"
        if "entry" in r:
            row.update(onay=fmt_time(ts[r["confirm"]]), giris=r["entry"], stop=r["stop"],
                       tp=r["tp"], atr=r["atr"], risk_atr=r["risk"] / r["atr"])
        if "entry_bar" in r:
            row.update(giris_zamani=fmt_time(ts[r["entry_bar"]]), _entry_ts=int(ts[r["entry_bar"]]),
                       dolum=r["fill"],
                       risk_yuzde=100 * r["risk"] / r["fill"])
            # Temiz trend ölçüleri (TP / stop karşılaştırması ve CSV için)
            if "BTC_Close" in df.columns:
                k = tr.btc_corr(df, i)
                row["btc_kor"] = round(k, 3) if k == k else None
            row["mfe_r"] = round(tr.mfe_r(df, r, side), 2)
            row["sivri_atr"] = round(tr.spike_top(df, i, side), 2)
            f = tr.trend_features(df, i, side, entry=r["entry"], risk=r["risk"])
            row.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items() if not k.startswith("_")})
            if r["status"] in ("win", "loss", "be"):
                if r.get("early_exit") or r.get("time_exit"):
                    row["cikis_turu"] = "erken çıkış" if r.get("early_exit") else "zaman stopu"
                    if r.get("early_stop"):
                        row["erken_stop"] = 1   # mum içinde erken stop (cikis_turu yine "erken çıkış")
                elif r["status"] == "be":
                    row["cikis_turu"] = "başabaş stop"   # 1R'ye gelip stop girişe çekildikten sonra girişten çıktı
                row.update(cikis_zamani=fmt_time(ts[r["exit_bar"]]), cikis=r["exit"],
                           R_brut=round(r["r_gross"], 3), R_net=round(r["r_net"], 3),
                           dolar=round(r["r_net"] * tr.RISK_USD, 2),
                           _exit_ts=int(ts[r["exit_bar"]]))
                if with_ctx:
                    row["_ctx"] = charts.context(df, r)
                next_free = r["exit_bar"] + 1
            else:
                next_free = len(df)
        rows.append(row)
    return rows


def explain_example(df, symbol, tf, tick, when):
    """Örnek saati hem Türkiye saati hem UTC olarak dener
    (TradingView kriptoda varsayılan olarak UTC gösterir)."""
    out = []
    for tz_name, tz in (("UTC", "UTC"), ("TR saati", TZ)):
        ms = int(pd.Timestamp(when, tz=tz).tz_convert("UTC").value // 10**6)
        hits = np.flatnonzero(df["timestamp"].values == ms)
        if len(hits) == 0:
            out.append(f"• {symbol} {tf} {when} ({tz_name}): bu tarih veride yok")
            continue
        i = int(hits[0])
        d = st.diagnose(df, i)
        ok = [k for k, _ in COND_TR if d.get(k, False)]
        lines = [f"• <b>{symbol} {tf} {when} ({tz_name})</b>"]
        if len(ok) == len(COND_TR):
            r = tr.simulate(df, i, d["side"], tick)
            lines.append(f"   ✅ Tüm temas şartları tuttu → {d['side']}: {STATUS_TR[r['status']]}")
            if "confirm" in r:
                lines.append(f"   Onay {fmt_time(df['timestamp'].iloc[r['confirm']])}, "
                             f"giriş {r['entry']:g}, stop {r['stop']:g}, TP {r['tp']:g}")
        else:
            failed = [label for k, label in COND_TR if k in d and not d[k]]
            lines.append("   ❌ " + ", ".join(failed))
        out.append("\n".join(lines))
    return "\n".join(out)


# ---------------------------------------------------------------- portföy korumaları
def btc_trend_map(df):
    """BTC'nin her 15dk mumu için yönü: +1 (EMA20 > EMA50), -1 (altında)."""
    return dict(zip(df["timestamp"].astype("int64"), np.where(df["EMA20"] > df["EMA50"], 1, -1)))


def apply_portfolio(rows, max_open=0, cluster_max=0, btc=False, btc_map=None, touch_counts=None):
    """Coinler arası kurallar. Elenen işlemlerin durumu skip_* olur.
    Sıra: BTC yönü -> toplu sinyal -> aynı anda açık işlem sınırı.
    touch_counts: (temas zamanı, yön) -> o mumda temas veren coin sayısı. Canlıdaki gibi BÜTÜN temaslar
    sayılır (sadece işleme dönenler değil)."""
    if not (max_open or cluster_max or btc):
        return rows
    from collections import Counter
    import heapq
    counts = touch_counts if touch_counts is not None else Counter((r["_touch_ts"], r["yon"]) for r in rows)
    traded = ("win", "loss", "be", "open")

    def skip(r, status):
        r = dict(r)
        r["durum"], r["sonuc"] = status, STATUS_TR[status]
        for k in ("R_brut", "R_net", "dolar"):
            r.pop(k, None)
        return r

    out = []
    for r in rows:
        if r["durum"] in traded:
            if btc and btc_map:
                d = btc_map.get(r["_touch_ts"])
                if d is not None and d != (1 if r["yon"] == "LONG" else -1):
                    r = skip(r, "skip_btc")
            if r["durum"] in traded and cluster_max and counts[(r["_touch_ts"], r["yon"])] >= cluster_max:
                r = skip(r, "skip_cluster")
        out.append(r)

    if max_open:
        order = sorted((i for i, r in enumerate(out) if r["durum"] in traded),
                       key=lambda i: out[i]["_entry_ts"])
        open_exits = []
        for i in order:
            r = out[i]
            while open_exits and open_exits[0] <= r["_entry_ts"]:
                heapq.heappop(open_exits)
            if len(open_exits) >= max_open:
                out[i] = skip(r, "skip_open")
                continue
            heapq.heappush(open_exits, r.get("_exit_ts", 2**62))
    return out


# ---------------------------------------------------------------- rapor
def stats(trades):
    if trades.empty:
        return None
    t = trades.sort_values("_exit_ts")
    eq = t["R_net"].cumsum()
    dd = (eq - eq.cummax()).min()
    streak = best = 0
    for lost in (t["durum"] == "loss"):
        streak = streak + 1 if lost else 0
        best = max(best, streak)
    return {
        "n": len(t), "wins": int((t["durum"] == "win").sum()),
        "be": int((t["durum"] == "be").sum()),
        "wr": 100 * (t["durum"] == "win").mean(),
        "gross": t["R_brut"].sum(), "net": t["R_net"].sum(),
        "avg": t["R_net"].mean(), "dd": dd, "streak": best,
        "risk_med": t["risk_yuzde"].median(),
    }


def usd(r):
    return f"{r * tr.RISK_USD:+,.0f}$".replace(",", ".")


def line(label, s):
    if not s:
        return f"{label}: işlem yok"
    return (f"{label}: {s['n']} işlem, %{s['wr']:.0f} kazanma, "
            f"{s['net']:+.1f}R ({usd(s['net'])})")


def month_label(touch_ts, p0):
    """Dönem başından itibaren 30 günlük dilim: 1. ay, 2. ay, ..."""
    return int((touch_ts - p0) // (30 * 86400 * 1000)) + 1


def build_report(df_all, period_txt, n_coins, minutes, examples_txt, p0=None, days=30, status_counts=None):
    """Sade rapor: TP / stop / erken çıkış ve kâr-zarar (ayrıntı CSV'de)."""
    trades = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
    mode = {"both": "klasik + dönüş", "reclaim": "dönüş", "classic": "klasik"}.get(tr.ENTRY_MODE, tr.ENTRY_MODE)
    msg = [f"📊 <b>BACKTEST SONUCU</b> (TP 1:{tr.RR:g}, {mode})",
           f"{period_txt}, {n_coins} coin, 1R = {tr.RISK_USD:g}$ (komisyon dahil)", ""]
    if trades.empty:
        return "\n".join(msg + ["Hiç işlem oluşmadı."])
    msg.append(tp_stop_line(trades))
    if "varyasyon" in trades:
        for v in ("klasik", "dönüş"):
            tv = trades[trades["varyasyon"] == v]
            if not tv.empty:
                msg += ["", f"<b>{v.capitalize()}</b>", "  " + tp_stop_line(tv)]
    return "\n".join(msg)


def build_report_detailed(df_all, period_txt, n_coins, minutes, examples_txt, p0=None, days=30, status_counts=None):
    trades = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
    s = stats(trades)
    funnel = df_all["durum"].value_counts().to_dict() if not df_all.empty else {}
    if status_counts is not None:  # işleme dönmeyen setup'lar saklanmadı: sayıları buradan
        funnel = {**{k: v for k, v in status_counts.items() if k not in TRADED}, **funnel}
    n_setups = sum(funnel.values())

    def c(*keys):
        return int(sum(funnel.get(k, 0) for k in keys))

    be_txt = f", başabaş +{tr.BE_TRIGGER:g}R" if tr.BE_TRIGGER > 0 else ""
    f_txt = ", filtreli" if tr.FILTERS else ", filtresiz"
    if tr.TOUCH_WICK_MIN > 0 and tr.REQUIRE_PRIOR_TOUCH:
        f_txt = ", canlı ayar: 6 kural + toplu + 03-07 yok"
    if tr.ENTRY_MODE == "reclaim":
        f_txt = ", DÖNÜŞ VARYASYONU: temas EMA20'nin öbür tarafında kapatır, sonraki mum geri alır, sonraki onay"
    if tr.ENTRY_MODE == "both":
        f_txt = ", CANLI AYAR: KLASİK + DÖNÜŞ birlikte (6 kural + toplu + 03-07 yok + en fazla 2 işlem)"
    msg = [f"📊 <b>BACKTEST SONUCU (TP 1:{tr.RR:g}{be_txt}{f_txt})</b>",
           f"{period_txt}, {n_coins} coin ({minutes:.0f} dk sürdü)", ""]
    msg.append("<b>Huni</b>")
    msg.append(f"Temas sinyali: {n_setups}")
    if tr.ENTRY_MODE == "reclaim":
        msg.append(f"  ↳ Temas mumu EMA20'nin öbür tarafında kapatmadı: {c('no_close_below')}")
        msg.append(f"  ↳ Sonraki mum EMA20'yi geri almadı: {c('no_reclaim')}")
    elif tr.ENTRY_MODE == "both":
        msg.append(f"  ↳ Dönüş: sonraki mum EMA20'yi geri almadı: {c('no_reclaim')}")
    else:
        msg.append(f"  ↳ EMA20 yanlış tarafta kapanış: {c('no_close')}")
    msg.append(f"  ↳ Onaydan önce iptal: {c('cancel_touch')}")
    msg.append(f"  ↳ Onay mumu dönüş mumunun ucunu geçmedi: {c('no_confirm')}" if tr.ENTRY_MODE == "reclaim"
               else f"  ↳ Onay yok (klasik 3 mumda / dönüşte onay mumu): {c('no_confirm')}" if tr.ENTRY_MODE == "both"
               else f"  ↳ 3 mumda onay yok: {c('no_confirm')}")
    msg.append(f"  ↳ ATR filtresine takıldı: {c('atr')}")
    if tr.MIN_ATR_MULT > 0:
        msg.append(f"  ↳ Stop {tr.MIN_ATR_MULT:g} ATR'den kısa: {c('atr_min')}")
    if tr.REQUIRE_PRIOR_TOUCH:
        msg.append(f"  ↳ Trend teyidi yok: {c('no_prior_touch')}")
    if tr.WICK_MAX_BODY > 0:
        msg.append(f"  ↳ Onay mumunda uzun iğne: {c('wick')}")
    if tr.CLEAN_PIVOT_MAX > 0:
        msg.append(f"  ↳ Tepe/dip temiz değil: {c('dirty_pivot')}")
    if tr.QUIET_UTC[0] < tr.QUIET_UTC[1]:
        msg.append(f"  ↳ Sessiz saatler (TR {tr.QUIET_UTC[0] + 3:02d}:00-{tr.QUIET_UTC[1] + 3:02d}:00): {c('quiet')}")
    if tr.TOUCH_WICK_MIN > 0:
        msg.append(f"  ↳ Temas mumu fitil değil: {c('touch_body')}")
    if tr.STRUCTURE_BREAK:
        msg.append(f"  ↳ Yapı bozuk (önceki düzeltme kırılmış): {c('structure_break')}")
    if tr.ROOM_MIN_R > 0:
        msg.append(f"  ↳ Önceki tepe/dibe {tr.ROOM_MIN_R:g}R'den yakın: {c('no_room')}")
    if tr.PIVOT_WICK_MAX > 0:
        msg.append(f"  ↳ Tepe/dip iğnesi uzun: {c('pivot_wick')}")
    if tr.clean_trend_active():
        msg.append(f"  ↳ Trend temiz değil: {c('not_clean')}")
    if tr.BTC_CORR_MAX > 0:
        msg.append(f"  ↳ BTC'ye benzer hareket (≥ {tr.BTC_CORR_MAX:g}): {c('btc_corr')}")
    min_pct = tr.MIN_RISK_PCT if tr.FILTERS else tr.BASE_MIN_RISK_PCT
    if tr.FILTERS:
        msg.append(f"  ↳ Asya seansı (00-08 UTC): {c('session')}")
    msg.append(f"  ↳ Stop %{min_pct:g}'ten dar: {c('min_risk')}")
    if tr.FILTERS:
        msg.append(f"  ↳ Stop %{tr.MAX_RISK_PCT:g}'ten geniş: {c('max_risk')}")
    msg.append(f"  ↳ Girişten önce iptal: {c('cancel_confirm')}")
    msg.append(f"  ↳ 2 mumda girişe gelmedi: {c('no_entry')}")
    if c("chase"):
        msg.append(f"  ↳ Kapanış girişten çok uzakta: {c('chase')}")
    if c("skip_btc", "skip_cluster", "skip_open"):
        msg.append(f"  ↳ Portföy koruması: BTC {c('skip_btc')}, toplu sinyal {c('skip_cluster')}, "
                   f"açık işlem sınırı {c('skip_open')}")
    msg.append(f"İşleme girildi: {c('win', 'loss', 'be', 'open')} (açık: {c('open')})")
    msg.append("")
    if s:
        be = 100 / (1 + tr.RR)
        msg.append("<b>Sonuç</b>")
        bep = f" | Başabaş: {s['be']}" if tr.BE_TRIGGER > 0 else ""
        msg.append(f"İşlem: {s['n']} | TP: {s['wins']} | Stop: {s['n'] - s['wins'] - s['be']}{bep}")
        msg.append(f"Kazanma oranı: %{s['wr']:.1f} (1:{tr.RR:g} için başabaş ~%{be:.0f})")
        msg.append(f"1R = {tr.RISK_USD:g}$")
        msg.append(f"Toplam (komisyonsuz): {s['gross']:+.1f}R ({usd(s['gross'])})")
        msg.append(f"Toplam (komisyonlu): <b>{s['net']:+.1f}R ({usd(s['net'])})</b>")
        msg.append(f"İşlem başı ortalama: {s['avg']:+.2f}R ({usd(s['avg'])})")
        msg.append(f"En büyük düşüş: {s['dd']:.1f}R ({usd(s['dd'])})")
        msg.append(f"En uzun stop serisi: {s['streak']}")
        msg.append(f"Ortalama stop mesafesi: %{s['risk_med']:.2f}")
        msg.append("")
        for tf in sorted(trades["zaman_dilimi"].unique()):
            msg.append(line(tf, stats(trades[trades["zaman_dilimi"] == tf])))
        for side in ("LONG", "SHORT"):
            msg.append(line(side, stats(trades[trades["yon"] == side])))
        if "varyasyon" in trades:
            for v in ("klasik", "dönüş"):
                msg.append(line(v.capitalize(), stats(trades[trades["varyasyon"] == v])))
        if p0 is not None and days > 30:
            msg += ["", "<b>Ay ay</b>"]
            months = trades["_touch_ts"].apply(lambda t: month_label(t, p0))
            for m in range(1, (days + 29) // 30 + 1):
                a = pd.Timestamp(p0 + (m - 1) * 30 * 86400000, unit="ms", tz="UTC").tz_convert(TZ)
                b = pd.Timestamp(min(p0 + m * 30 * 86400000, p0 + days * 86400000), unit="ms", tz="UTC").tz_convert(TZ)
                msg.append(line(f"{m}. ay ({a:%d.%m}–{b:%d.%m})", stats(trades[months == m])))
    else:
        msg.append("Hiç işlem oluşmadı.")
    if examples_txt:
        msg += ["", "<b>Senin örneklerin</b>"] + examples_txt
    return "\n".join(msg)


# Her ayar: varsayılanların üzerine yazılan değerler. "ad" raporda görünür.
PARAM_KEYS = ["RR", "BE_TRIGGER", "FILTERS", "MIN_ATR_MULT", "WICK_MAX_BODY",
              "REQUIRE_PRIOR_TOUCH", "STOP_BUFFER_ATR", "CLEAN_PIVOT_MAX", "CLEAN_PIVOT_ATR",
              "TOUCH_WICK_MIN", "PIVOT_WICK_MAX", "QUIET_UTC", "ROOM_MIN_R", "STRUCTURE_BREAK",
              "SUPPORT_N", "SUPPORT_MIN", "SUPPORT_WICK_BODY", "SUPPORT_WICK_ATR",
              "TOUCH_TAIL_MAX", "TOUCH_TAIL_REF", "ENTRY_MODE", "PIVOT_LEG_MIN", "TIME_STOP_BARS",
              "LEG_BODY_MIN", "LEG_ATR_MIN", "SPIKE_MAX", "EMA_FAN_MIN",
              "LEG_COUNTER_MAX", "PULLBACK_MIN_BARS", "LEG_ATR_MAX", "BTC_CORR_MAX", "BTC_CORR_BARS",
              "FAILED_ENTRY_BARS", "TOUCH_PREV_EXTREME", "ATR_MAX_MULT", "CONFIRM_WINDOW", "SPIKE_TOP_ATR",
              "BASE_MIN_RISK_PCT", "FAILED_ENTRY_RED", "TIME_STOP_LOCK_R",
              "EARLY_STOP_R", "EARLY_STOP_BARS", "CLOSE_ENTRY", "CLOSE_ENTRY_MAX_R", "CLOSE_ENTRY_KEEP_TP",
              "WICKY_MAX", "WICKY_BARS", "RECLAIM_BODY_MAX_ATR", "PIVOT_BAND2_ATR", "PIVOT_BAND2_MAX",
              "STOP_MAX_ATR", "EARLY_EXIT_MAX_ATR", "ENTRY_BUFFER_ATR",
              "EMA200_ORDER", "NEW_HIGH_BARS", "NEW_HIGH_LOOKBACK",
              "ZIGZAG_MAX", "ZIGZAG_MIN_BARS", "PRIOR_TOUCH_SEP_ATR",
              "ROOM_RELAX_R", "ROOM_RELAX_WICKY", "ROOM_RELAX_RISK_ATR", "TOUCH_WICK_ROOM_R", "TWO_BAR_TOUCH", "TWO_BAR_BODY_ATR", "TWO_BAR_ANY",
              "CHOP_BARS", "CHOP_FLIPS_MIN", "CHOP_BODY_ATR"]
DEFAULTS = {k: getattr(tr, k) for k in PARAM_KEYS}


def _sig_key(cfg):
    """Ayarın temas (sinyal) tanımı farkı: strategy.py sabitlerinin üzerine yazılanlar ("sig")."""
    return tuple(sorted((cfg.get("sig") or {}).items()))


class _st_override:
    """strategy.py sabitlerini geçici değiştirir (sadece sinyal bulma sırasında)."""
    def __init__(self, sig):
        self.sig = dict(sig)

    def __enter__(self):
        self.old = {k: getattr(st, k) for k in self.sig}
        for k, v in self.sig.items():
            setattr(st, k, v)

    def __exit__(self, *a):
        for k, v in self.old.items():
            setattr(st, k, v)


class _SkipBinance(Exception):
    """Bybit testinde Binance coin bilgisi bloğu atlanır."""


def C(ad, **kw):
    return {"ad": ad, **kw}


COMPARE_SETS = {
    "hepsi": [
        C("1:2 (filtresiz)", FILTERS=False), C("1:2"), C("1:2 + başabaş 1R", BE_TRIGGER=1.0),
        C("1:2.5", RR=2.5), C("1:2.5 + başabaş 1R", RR=2.5, BE_TRIGGER=1.0),
        C("1:3", RR=3.0), C("1:3 + başabaş 1R", RR=3.0, BE_TRIGGER=1.0),
        C("1:2 + en az 0.875 ATR", MIN_ATR_MULT=0.875),
        C("1:2 + başabaş 1R + en az 0.875 ATR", BE_TRIGGER=1.0, MIN_ATR_MULT=0.875),
    ],
    # Grafik incelemesinden gelen kurallar; hepsi 1:2, eski saat/stop filtreleri kapalı
    "yeni": [
        C("Taban (senin ilk kuralların)", FILTERS=False),
        C("+ iğne ≤ 1 gövde", FILTERS=False, WICK_MAX_BODY=1.0),
        C("+ iğne ≤ 0.5 gövde", FILTERS=False, WICK_MAX_BODY=0.5),
        C("+ trend teyidi", FILTERS=False, REQUIRE_PRIOR_TOUCH=True),
        C("+ stop payı 0.2 ATR", FILTERS=False, STOP_BUFFER_ATR=0.2),
        C("Hepsi: iğne≤1, trend, pay 0.1", FILTERS=False, WICK_MAX_BODY=1.0, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.1),
        C("Hepsi: iğne≤1, trend, pay 0.2", FILTERS=False, WICK_MAX_BODY=1.0, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.2),
        C("Hepsi: iğne≤1, trend, pay 0.3", FILTERS=False, WICK_MAX_BODY=1.0, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.3),
        C("Hepsi: iğne≤0.5, trend, pay 0.2", FILTERS=False, WICK_MAX_BODY=0.5, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.2),
    ],
}
_NEW = dict(FILTERS=False, WICK_MAX_BODY=1.0, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.2)
COMPARE_SETS["koruma"] = [
    C("Taban", FILTERS=False),
    C("Taban + en fazla 3 açık", FILTERS=False, max_open=3),
    C("Taban + en fazla 5 açık", FILTERS=False, max_open=5),
    C("Taban + toplu sinyal (5+) yok", FILTERS=False, cluster_max=5),
    C("Taban + BTC yönü", FILTERS=False, btc=True),
    C("Taban + BTC + en fazla 3", FILTERS=False, btc=True, max_open=3),
    C("Yeni kurallar", **_NEW),
    C("Yeni kurallar + BTC + en fazla 3", **_NEW, btc=True, max_open=3),
    C("Yeni + toplu + BTC + en fazla 3", **_NEW, cluster_max=5, btc=True, max_open=3),
]
_NEW3 = dict(FILTERS=False, WICK_MAX_BODY=1.0, REQUIRE_PRIOR_TOUCH=True, STOP_BUFFER_ATR=0.3)
_CLEAN = dict(CLEAN_PIVOT_MAX=3, CLEAN_PIVOT_ATR=0.3)
COMPARE_SETS["son"] = [
    C("Taban", FILTERS=False),
    C("Kurallar 1-3 (iğne, trend, pay 0.3)", **_NEW3),
    C("1-3 + temiz dip (0.3 ATR)", **_NEW3, **_CLEAN),
    C("1-3 + temiz dip (0.5 ATR)", **_NEW3, CLEAN_PIVOT_MAX=3, CLEAN_PIVOT_ATR=0.5),
    C("1-4 + BTC yönü", **_NEW3, **_CLEAN, btc=True),
    C("1-4 + en fazla 3 açık", **_NEW3, **_CLEAN, max_open=3),
    C("1-4 + BTC + en fazla 3", **_NEW3, **_CLEAN, btc=True, max_open=3),
    C("1-4 + toplu sinyal yok", **_NEW3, **_CLEAN, cluster_max=5),
    C("1-4 + toplu + BTC + en fazla 3", **_NEW3, **_CLEAN, cluster_max=5, btc=True, max_open=3),
    C("1-4 (1:2.5)", **_NEW3, **_CLEAN, RR=2.5),
    C("1-4 + BTC + en fazla 3 (1:2.5)", **_NEW3, **_CLEAN, RR=2.5, btc=True, max_open=3),
    C("1-4 + toplu + BTC + en fazla 3 (1:2.5)", **_NEW3, **_CLEAN, RR=2.5, cluster_max=5, btc=True, max_open=3),
]
_R14 = dict(**_NEW3, **_CLEAN)
COMPARE_SETS["son2"] = [
    C("Taban", FILTERS=False),
    C("1-4 + toplu (önceki en iyi)", **_R14, cluster_max=5),
    C("+ fitil temas (5)", **_R14, cluster_max=5, TOUCH_WICK_MIN=1.0),
    C("+ tepe iğnesi ≤ 2 gövde (6)", **_R14, cluster_max=5, PIVOT_WICK_MAX=2.0),
    C("+ tepe iğnesi ≤ 1.5 gövde (6)", **_R14, cluster_max=5, PIVOT_WICK_MAX=1.5),
    C("1-6 + toplu", **_R14, cluster_max=5, TOUCH_WICK_MIN=1.0, PIVOT_WICK_MAX=2.0),
    C("1-6 + toplu + en fazla 3", **_R14, cluster_max=5, TOUCH_WICK_MIN=1.0, PIVOT_WICK_MAX=2.0, max_open=3),
    C("1-6 + toplu + en fazla 3 (1:2.5)", **_R14, cluster_max=5, TOUCH_WICK_MIN=1.0, PIVOT_WICK_MAX=2.0, max_open=3, RR=2.5),
]
_R16 = dict(**_R14, TOUCH_WICK_MIN=1.0, PIVOT_WICK_MAX=2.0)
COMPARE_SETS["saat"] = [
    C("Taban", FILTERS=False),
    C("Taban + 03-07 TR yok", FILTERS=False, QUIET_UTC=(0, 4)),
    C("1-6 + toplu", **_R16, cluster_max=5),
    C("1-6 + toplu + 03-07 TR yok (canlıdaki)", **_R16, cluster_max=5, QUIET_UTC=(0, 4)),
]
_LIVE = dict(**_R16, cluster_max=5, QUIET_UTC=(0, 4))
COMPARE_SETS["tp_eski"] = [
    C("Canlı kurallar 1:2", **_LIVE, RR=2.0),
    C("Canlı kurallar 1:2.2 (canlıdaki)", **_LIVE, RR=2.2),
    C("Canlı kurallar 1:2.5", **_LIVE, RR=2.5),
    C("Canlı kurallar 1:1.5", **_LIVE, RR=1.5),
]
# Karşılaştırma setleri klasik sistemde sabit (canlı 14.10'dan beri klasik + dönüş; o: --preset canli)
_LIVE_NOW = dict(live_setups.LIVE_RULES_14_10, ENTRY_MODE="classic", cluster_max=live_setups.CLUSTER_MAX,
                 max_open=live_setups.MAX_OPEN)
COMPARE_SETS["dip"] = [
    C("Canlı ayar (1:2.2)", **_LIVE_NOW),
    C("+ önünde en az 0.5R yer", **_LIVE_NOW, ROOM_MIN_R=0.5),
    C("+ önünde en az 1R yer", **_LIVE_NOW, ROOM_MIN_R=1.0),
    C("+ önünde en az 1.5R yer", **_LIVE_NOW, ROOM_MIN_R=1.5),
    C("+ önünde TP kadar yer (2.2R)", **_LIVE_NOW, ROOM_MIN_R=2.2),
]
COMPARE_SETS["yapi"] = [
    C("Canlı ayar (1:2.2)", **_LIVE_NOW),
    C("+ 7: önünde 1R yer", **_LIVE_NOW, ROOM_MIN_R=1.0),
    C("+ 8: yapı bozulmamış (iğne)", **_LIVE_NOW, STRUCTURE_BREAK="wick"),
    C("+ 8: yapı bozulmamış (kapanış)", **_LIVE_NOW, STRUCTURE_BREAK="close"),
    C("+ 7 (0.5R) + 8 (iğne)", **_LIVE_NOW, ROOM_MIN_R=0.5, STRUCTURE_BREAK="wick"),
    C("+ 7 (1R) + 8 (iğne)", **_LIVE_NOW, ROOM_MIN_R=1.0, STRUCTURE_BREAK="wick"),
]
_S9 = dict(SUPPORT_N=2, SUPPORT_MIN=2, SUPPORT_WICK_BODY=0.5)
COMPARE_SETS["destek"] = [
    C("Canlı ayar (1:2.2)", **_LIVE_NOW),
    C("+ 9: dip/tepeden sonraki 2 mum iğneli (iğne ≥ gövde)", **_LIVE_NOW, **dict(_S9, SUPPORT_WICK_BODY=1.0)),
    C("+ 9: dip/tepeden sonraki 2 mum iğneli (iğne ≥ ½ gövde)", **_LIVE_NOW, **_S9),
    C("+ 9: sonraki 3 mumun 2'si iğneli (iğne ≥ ½ gövde)", **_LIVE_NOW, **dict(_S9, SUPPORT_N=3)),
    C("+ 7 (1R) + 8", **_LIVE_NOW, ROOM_MIN_R=1.0, STRUCTURE_BREAK="wick"),
    C("+ 7 (1R) + 8 + 9 (½ gövde)", **_LIVE_NOW, ROOM_MIN_R=1.0, STRUCTURE_BREAK="wick", **_S9),
]
COMPARE_SETS["igne"] = [
    C("Canlı ayar (1:2.2)", **_LIVE_NOW),
    C("+ 10: ters iğne ≤ EMA tarafındaki iğne", **_LIVE_NOW, TOUCH_TAIL_MAX=1.0, TOUCH_TAIL_REF="wick"),
    C("+ 10: ters iğne ≤ EMA iğnesinin yarısı", **_LIVE_NOW, TOUCH_TAIL_MAX=0.5, TOUCH_TAIL_REF="wick"),
    C("+ 10: ters iğne ≤ 0.3 ATR", **_LIVE_NOW, TOUCH_TAIL_MAX=0.3, TOUCH_TAIL_REF="atr"),
    C("+ 7: önünde en az 1R yer", **_LIVE_NOW, ROOM_MIN_R=1.0),
    C("+ 7 (1R) + 10 (≤ EMA iğnesi)", **_LIVE_NOW, ROOM_MIN_R=1.0, TOUCH_TAIL_MAX=1.0, TOUCH_TAIL_REF="wick"),
]
_DONUS = dict(_LIVE_NOW, ENTRY_MODE="reclaim")
COMPARE_SETS["donus"] = [
    C("Dönüş varyasyonu", **_DONUS),
    C("+ 8 saatte sonuç yoksa stop girişe", **_DONUS, TIME_STOP_BARS=32),
    C("+ 11: tepe en az 2 mumla yapılmış", **_DONUS, PIVOT_LEG_MIN=2),
    C("+ 11: tepe en az 3 mumla yapılmış", **_DONUS, PIVOT_LEG_MIN=3),
    C("+ 7: önünde en az 1R yer", **_DONUS, ROOM_MIN_R=1.0),
    C("+ 8 saat + 11 (2 mum) + 7 (1R)", **_DONUS, TIME_STOP_BARS=32, PIVOT_LEG_MIN=2, ROOM_MIN_R=1.0),
]
# Temiz trend: kullanıcının 10/10 dediği işlemler (HOME, TWT): bacak büyük gövdeli mumlarla, az iğne, ters mum yok
_TEMIZ = dict(tr.TEMIZ_TEST)


def _temiz_set(base):
    t = _TEMIZ
    return [
        C("Dönüş varyasyonu" if base.get("ENTRY_MODE") == "reclaim" else "Temel ayar", **base),
        C(f"+ temiz bacak (gövde oranı ≥ {t['LEG_BODY_MIN']:g})", **base, LEG_BODY_MIN=t["LEG_BODY_MIN"]),
        C(f"+ güçlü bacak (≥ {t['LEG_ATR_MIN']:g} ATR)", **base, LEG_ATR_MIN=t["LEG_ATR_MIN"]),
        C(f"+ tek mumluk fırlama yok (en büyük gövde ≤ bacağın %{100 * t['SPIKE_MAX']:.0f}'si)", **base,
          SPIKE_MAX=t["SPIKE_MAX"]),
        C(f"+ EMA'lar açılmış (EMA20–100 ≥ {t['EMA_FAN_MIN']:g} ATR)", **base, EMA_FAN_MIN=t["EMA_FAN_MIN"]),
        C("+ temiz trend (dördü birlikte)", **base, **_TEMIZ),
        C("+ temiz trend + önünde 1R yer", **base, **_TEMIZ, ROOM_MIN_R=1.0),
    ]


COMPARE_SETS["temiz"] = _temiz_set(_LIVE_NOW)
# İki dönemde (Nisan-Temmuz, Temmuz-Ekim) aynı yönde çıkan adaylar; eşikler sabit, 3. dönemde (önceki2) sınanır
_A = tr.ADAY_TEST
COMPARE_SETS["aday"] = [
    C("Canlı ayar", **_LIVE_NOW),
    C(f"+ bacakta ters mum ≤ %{100 * _A['LEG_COUNTER_MAX']:.0f}", **_LIVE_NOW, LEG_COUNTER_MAX=_A["LEG_COUNTER_MAX"]),
    C(f"+ düzeltme en az {_A['PULLBACK_MIN_BARS']} mum", **_LIVE_NOW, PULLBACK_MIN_BARS=_A["PULLBACK_MIN_BARS"]),
    C(f"+ bacak {_A['LEG_ATR_MAX']:g} ATR'den kısa", **_LIVE_NOW, LEG_ATR_MAX=_A["LEG_ATR_MAX"]),
    C("+ ters mum + düzeltme", **_LIVE_NOW, LEG_COUNTER_MAX=_A["LEG_COUNTER_MAX"],
      PULLBACK_MIN_BARS=_A["PULLBACK_MIN_BARS"]),
    C("+ üçü birlikte", **_LIVE_NOW, **_A),
]
# Dönüş varyasyonu ayrı test: temiz trend filtreleri + klasikte iki dönemde tutan adaylar (hepsi tek testte)
COMPARE_SETS["temiz_donus"] = _temiz_set(_DONUS) + [
    C(f"+ bacakta ters mum ≤ %{100 * _A['LEG_COUNTER_MAX']:.0f}", **_DONUS, LEG_COUNTER_MAX=_A["LEG_COUNTER_MAX"]),
    C(f"+ düzeltme en az {_A['PULLBACK_MIN_BARS']} mum", **_DONUS, PULLBACK_MIN_BARS=_A["PULLBACK_MIN_BARS"]),
    C(f"+ bacak {_A['LEG_ATR_MAX']:g} ATR'den kısa", **_DONUS, LEG_ATR_MAX=_A["LEG_ATR_MAX"]),
]
_LIVE_NO_CLUSTER = dict(live_setups.LIVE_RULES_14_10, ENTRY_MODE="classic")
# BTC'ye benzerlik filtresi (kullanıcı, 14.10): coin BTC gibi hareket ediyorsa girme. Canlı ayar = klasik + dönüş
_CANLI = dict(live_setups.LIVE_RULES_14_10, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)
COMPARE_SETS["btc"] = [
    C("Canlı ayar (klasik + dönüş)", **_CANLI),
    C("+ BTC'ye benzerlik < 0.8 (son 24 saat)", **_CANLI, BTC_CORR_MAX=0.8),
    C("+ BTC'ye benzerlik < 0.6 (son 24 saat)", **_CANLI, BTC_CORR_MAX=0.6),
    C("+ BTC'ye benzerlik < 0.4 (son 24 saat)", **_CANLI, BTC_CORR_MAX=0.4),
    C("+ BTC'ye benzerlik < 0.6 (son 12 saat)", **_CANLI, BTC_CORR_MAX=0.6, BTC_CORR_BARS=48),
]
# Erken çıkış (giriş mumu girişin gerisinde kapatırsa çık) + BTC'ye benzerlik, tek testte (kullanıcı, 14.10)
COMPARE_SETS["erken"] = [
    C("Canlı ayar (klasik + dönüş)", **_CANLI),
    C("+ giriş mumu girişin gerisinde kapatırsa çık", **_CANLI, FAILED_ENTRY_BARS=1),
    C("+ ilk 2 mumdan biri girişin gerisinde kapatırsa çık", **_CANLI, FAILED_ENTRY_BARS=2),
    C("+ BTC'ye benzerlik < 0.8", **_CANLI, BTC_CORR_MAX=0.8),
    C("+ BTC'ye benzerlik < 0.6", **_CANLI, BTC_CORR_MAX=0.6),
    C("+ BTC'ye benzerlik < 0.4", **_CANLI, BTC_CORR_MAX=0.4),
    C("+ giriş mumu çıkışı + BTC < 0.6", **_CANLI, FAILED_ENTRY_BARS=1, BTC_CORR_MAX=0.6),
]
# TP mesafesi (kullanıcı, 14.10 23:14: "erken çıkışlar çok R yiyor, işlemler ortalama kaç R gidiyor, TP'yi ona göre artıralım")
# Taban: canlı ayar + erken çıkış (2 mum). Raporun sonunda fiyatın stop olmadan önce en fazla kaç R gittiği (MFE) dağılımı.
_EB0 = dict(_CANLI, FAILED_ENTRY_BARS=2)
COMPARE_SETS["tp"] = [
    C("Erken çıkış (2 mum), TP 1:1.5", **dict(_EB0, RR=1.5)),
    C("Erken çıkış (2 mum), TP 1:2.2 (şu anki)", **_EB0),
    C("Erken çıkış (2 mum), TP 1:3", **dict(_EB0, RR=3.0)),
    C("Erken çıkış (2 mum), TP 1:4", **dict(_EB0, RR=4.0)),
    C("Erken çıkış (2 mum), TP 1:5", **dict(_EB0, RR=5.0)),
    C("Erken çıkış yok, TP 1:3", **dict(_CANLI, RR=3.0)),
]
# Başabaş (kullanıcı, 15.10 00:32): TP testinde stop olan 14 işlemin 7'si önce 1R+ kâra gitmişti. Fiyat 1R'ye gelince
# stop girişe çekilir (bir sonraki mumdan itibaren). Eski taban sistemde (erken çıkışsız) başabaş kötüleştirmişti.
# 180 gün TP testinde (18.04-14.10) TP 4 +36.5R, TP 2.2 +12.8R (7 ayın 5'inde daha iyi ama eşleşik fark gürültü içinde)
# → TP 4 de bu sette, önceki dönemde de sınansın.
COMPARE_SETS["basabas"] = [
    C("Erken çıkış (2 mum), TP 1:2.2 (şu anki)", **_EB0),
    C("TP 1:2.2 + 1R'de stop girişe", **dict(_EB0, BE_TRIGGER=1.0)),
    C("TP 1:2.2 + 1.5R'de stop girişe", **dict(_EB0, BE_TRIGGER=1.5)),
    C("TP 1:4", **dict(_EB0, RR=4.0)),
    C("TP 1:4 + 1R'de stop girişe", **dict(_EB0, RR=4.0, BE_TRIGGER=1.0)),
    C("TP 1:4 + 2R'de stop girişe", **dict(_EB0, RR=4.0, BE_TRIGGER=2.0)),
]
# 5m PDF incelemesi (kullanıcı, 15.10 01:13-01:14): SQDUSDT 05.10 00:50 LONG (düz giderken 2 dev mumla yapılan
# tepe, erken çıkış -0.13R) → sivri tepeye girme; SHORT 07.10 21:50 (onay temastan sonra 3. mumda, -0.24R) →
# onay en geç 2. mumda gelmeli (CONFIRM_WINDOW 3 → 2; dönüşte onay zaten 2. mumda).
COMPARE_SETS["sivri"] = [
    C("Canlı ayar + erken çıkış (2 mum)", **_EB0),
    C("+ onay en geç 2. mumda", **dict(_EB0, CONFIRM_WINDOW=2)),
    C("+ sivri tepe yok (2 mum ≥ 3 ATR)", **dict(_EB0, SPIKE_TOP_ATR=3.0)),
    C("+ sivri tepe yok (2 mum ≥ 4 ATR)", **dict(_EB0, SPIKE_TOP_ATR=4.0)),
    C("+ onay ≤ 2. mum + sivri tepe yok (3 ATR)", **dict(_EB0, CONFIRM_WINDOW=2, SPIKE_TOP_ATR=3.0)),
]
# Komisyon (kullanıcı, 15.10 01:23: "2.2 değil 2.5 yapsak komisyonu çıkarırız"). 5m'de komisyon 0.15R/iş; stopu %0.5'ten
# dar işlemlerde 0.21-0.28R. CSV tahmini: stop <%0.5 olanlar Eyl-Eki +1.5R, Ağu-Eyl -19.2R. TP 2.5 (MFE'den tahmin)
# 4 dönemin 2'sinde iyi, 2'sinde kötü. Taban: onay en geç 2. mumda (5m'de iki ayda da kötü olanları eliyor).
_EB2 = dict(_EB0, CONFIRM_WINDOW=2)
COMPARE_SETS["komisyon"] = [
    C("Canlı + erken çıkış + onay ≤ 2. mum", **_EB2),
    C("+ TP 1:2.5", **dict(_EB2, RR=2.5)),
    C("+ stop en az %0.5", **dict(_EB2, BASE_MIN_RISK_PCT=0.5)),
    C("+ stop en az %0.5 + TP 1:2.5", **dict(_EB2, BASE_MIN_RISK_PCT=0.5, RR=2.5)),
    C("+ stop en az %0.5 + sivri tepe yok (3 ATR)", **dict(_EB2, BASE_MIN_RISK_PCT=0.5, SPIKE_TOP_ATR=3.0)),
]
# Erken çıkışta mum rengi (kullanıcı, 15.10 01:57, ZETAUSDT 13.09 13:55 5m: giriş sonrası mum iğne atıp girişin 0.15R
# altında ama YEŞİL kapattı, erken çıkıldı, fiyat sonra 10R gitti). "Kırmızı kapatırsa çıkmalı." 15m ve 5m'de denenir.
_EB5 = dict(_EB0, CONFIRM_WINDOW=2, BASE_MIN_RISK_PCT=0.5)
COMPARE_SETS["renk"] = [
    C("Erken çıkış (2 mum)", **_EB0),
    C("Erken çıkış sadece ters renkli mumda", **dict(_EB0, FAILED_ENTRY_RED=True)),
    C("Onay ≤ 2. mum + stop ≥%0.5 + erken çıkış", **_EB5),
    C("Onay ≤ 2. mum + stop ≥%0.5 + erken çıkış sadece ters renkli mumda", **dict(_EB5, FAILED_ENTRY_RED=True)),
    # Kullanıcı (15.10 01:59-02:00, BANKUSDT 5m 14.09 13:35 LONG: "ne temiz tepe ne düzeltme, temas mumu kötü, giriş
    # tepenin hizası; kaç kere attım"). Önünde yer kuralı (ROOM_MIN_R, STABLE örneğinden) 'örnek' setindeydi ama hiç
    # çalıştırılmadı. BANK: tepeye 0.56R, EMA açıklığı 1.82 ATR; erken çıkışsız testlerde stop oldu (-1.04R).
    C("Onay ≤ 2 + stop ≥%0.5 + önünde en az 1R yer", **dict(_EB5, ROOM_MIN_R=1.0)),
    C("Onay ≤ 2 + stop ≥%0.5 + EMA açıklığı ≥ 2 ATR", **dict(_EB5, EMA_FAN_MIN=2.0)),
    C("Onay ≤ 2 + stop ≥%0.5 + 1R yer + EMA ≥ 2 ATR + ters renkte erken çıkış",
      **dict(_EB5, ROOM_MIN_R=1.0, EMA_FAN_MIN=2.0, FAILED_ENTRY_RED=True)),
]
# renk testi sonucu (15.10 02:2x): ters renk kuralı 5m ve 15m'de kötü (bırakıldı). 15m 12 ay: onay≤2+stop≥%0.5+1R yer
# +48.6R (kaymayla +36.2, en kötü ay -3.3; iki dönemde de 3'ten iyi), EMA≥2 ATR +24.1 / +14.3 (karışık). 5m 90 gün:
# EMA≥2 üç ayda da iyi (+15.7), 1R yer 2/3 ay (+6.2). Renksiz birleşim ve yumuşak EMA eşiği denenir.
_EBY = dict(_EB5, ROOM_MIN_R=1.0)
COMPARE_SETS["yer"] = [
    C("Onay ≤ 2 + stop ≥%0.5 + erken çıkış", **_EB5),
    C("+ önünde en az 1R yer", **_EBY),
    C("+ 1R yer + EMA açıklığı ≥ 2 ATR", **dict(_EBY, EMA_FAN_MIN=2.0)),
    C("+ 1R yer + EMA açıklığı ≥ 1.5 ATR", **dict(_EBY, EMA_FAN_MIN=1.5)),
]
# Yatay giden işlem (kullanıcı 15.10 03:50, SLXUSDT 14.10 23:00 SHORT: "girerdim ama saatlerce kalmazdım; aşırı yataya
# bağlarsa girişe gelince stop etsin, ufak kârda bile çıkabilir"). Taban = canlı 15m ayar (_EBY). 15m: 8 mum = 2 saat.
COMPARE_SETS["yatay"] = [
    C("Canlı ayar (onay ≤2 + stop ≥%0.5 + 1R yer + erken çıkış)", **_EBY),
    C("+ 2 saatte sonuç yoksa stop girişe", **dict(_EBY, TIME_STOP_BARS=8)),
    C("+ 4 saatte sonuç yoksa stop girişe", **dict(_EBY, TIME_STOP_BARS=16)),
    C("+ 8 saatte sonuç yoksa stop girişe", **dict(_EBY, TIME_STOP_BARS=32)),
    C("+ 4 saatte sonuç yoksa stop girişin 0.2R kârına", **dict(_EBY, TIME_STOP_BARS=16, TIME_STOP_LOCK_R=0.2)),
]
# İşlem sayısını artırma (kullanıcı 15.10 04:03: "erken çıkışlar hariç ayda ~10 işlem, çok az; işlem ve kazancı artırırsak
# 10R'ye ulaşırım"). Toplu sinyale takılanlar CSV'den (mfe + erken çıkış) tahminle eksi: Nis-Eki -24.9R, Eki-Nis -13.7R →
# o filtre kalıyor. Eski 6 kuraldan ve saat filtresinden biri tek tek kaldırılır: eklenen işlemler artıdaysa toplam R artar.
COMPARE_SETS["gevset"] = [
    C("Canlı ayar", **_EBY),
    C("- kural 1: onay iğnesi ≤ gövde", **dict(_EBY, WICK_MAX_BODY=0.0)),
    C("- kural 2: trend teyidi (önceki temas)", **dict(_EBY, REQUIRE_PRIOR_TOUCH=False)),
    C("- kural 4: temiz tepe/dip", **dict(_EBY, CLEAN_PIVOT_MAX=0)),
    C("- kural 5: fitil temas", **dict(_EBY, TOUCH_WICK_MIN=0.0)),
    C("- kural 6: tepe iğnesi ≤ 2 gövde", **dict(_EBY, PIVOT_WICK_MAX=0.0)),
    C("- 03-07 TR saat filtresi", **dict(_EBY, QUIET_UTC=(0, 0))),
]
# Erken çıkış zararı (kullanıcı 15.10 04:2x: "erken çıkışlar 0.3-0.6R yiyor; ölç biç mantıklı yol bul"). 12 ay ölçüm:
# 224 erken çıkış -74R (fiyat -54 + komisyon -20), 157'si giriş mumunun kendisinde (sahte kırılım). Derin kapanış az
# (0.3R erken stop en fazla +5.5 / +5.8R). Giriş filtreleri (stop ≤ 1.3 ATR, önünde ≥ 1.5R yer, sivri tepe) iki dönemde
# tutarlı değil: çıkardıkları işlemler toplamda artı. Asıl deneme: sahte kırılım mumuna girmemek (kapanışla giriş).
COMPARE_SETS["kapanis"] = [
    C("Canlı ayar (giriş seviyesine değince stop emriyle)", **_EBY),
    C("+ ilk 2 mumda 0.3R erken stop (mum içinde)", **dict(_EBY, EARLY_STOP_R=0.3)),
    C("Kapanışla giriş (mum girişin ötesinde kapatınca)", **dict(_EBY, CLOSE_ENTRY=True)),
    C("Kapanışla giriş, kapanış girişten ≤ 0.5R uzaksa", **dict(_EBY, CLOSE_ENTRY=True, CLOSE_ENTRY_MAX_R=0.5)),
    C("Kapanışla giriş, TP aynı fiyatta kalır", **dict(_EBY, CLOSE_ENTRY=True, CLOSE_ENTRY_KEEP_TP=True)),
    C("Kapanışla giriş, erken çıkış yok", **dict(_EBY, CLOSE_ENTRY=True, FAILED_ENTRY_BARS=0)),
]
# kapanış sonucu (15.10 04:40, Nis-Eki): canlı +17.2 · 0.3R erken stop +12.3 · kapanışla giriş +6.9 (sahte kırılımın 66
# işlemi -21.4R elendi ama kalan 135 işlem +38.5 → +6.9: giriş yukarıdan, stop %0.98 → %1.28) → hepsi red.
# Grafik örnekleri (kullanıcı 15.10 04:37, "yükle" 10:13; ayrı ayrı test). Taban = yeni canlı ayar (03-07 filtresi yok).
# RESOLVUSDT 20.08 02:15 LONG dönüş -1.16R: çok iğneli git-gel mumlar · NILUSDT 25.08 19:15 SHORT -1.09R: temiz dip yok
# (dipte taban), düzeltme kötü · ESPUSDT 30.08 11:30 SHORT dönüş erken -0.37R: temas mumu gövdesi çok büyük.
# CSV'de igne_orani / duz_igne / temas_govde_atr / pivot_bant_05 / pivot_bant_1 sütunları: eşikler CSV'den de taranır.
_CANLI15 = dict(_EBY, QUIET_UTC=(0, 0))
COMPARE_SETS["grafik"] = [
    C("Canlı ayar (03-07 filtresi yok)", **_CANLI15),
    C("+ iğneli git-gel yok (son 12 mum iğne oranı ≤ %60)", **dict(_CANLI15, WICKY_MAX=0.60)),
    C("+ iğneli git-gel yok (≤ %55)", **dict(_CANLI15, WICKY_MAX=0.55)),
    C("+ temiz dip/tepe: 0.5 ATR bantta ≤ 2 mum", **dict(_CANLI15, CLEAN_PIVOT_ATR=0.5)),
    C("+ temiz dip/tepe: 1 ATR bantta ≤ 4 mum", **dict(_CANLI15, CLEAN_PIVOT_ATR=1.0, CLEAN_PIVOT_MAX=5)),
    C("+ dönüşte temas gövdesi ≤ 1 ATR", **dict(_CANLI15, RECLAIM_BODY_MAX_ATR=1.0)),
    C("+ dönüşte temas gövdesi ≤ 0.7 ATR", **dict(_CANLI15, RECLAIM_BODY_MAX_ATR=0.7)),
]
# grafik sonucu (15.10, 3 dönem: Nis-Eki 26 / Eki-Nis / Nis-Eki 25): taban +22.1 / +27.5 / -20.8. Hiçbir ayar 3'ünde iyi
# değil, ama CSV'de 1.-2. dönemden seçilen iki eşik 3. dönemde de tuttu (12 mum iğne >0.58; kural 4 kalarak 1 ATR bantta
# ≥5 mum). Kullanıcı 11:46 "kodla" (/backtest 180 eleme): gerçek ayar olarak (portföy etkisiyle) 3 dönemde. 5. ayar: biraz gevşek eşikler
# (sonuç eşiğe çok hassassa şanstır).
COMPARE_SETS["grafik2"] = [
    C("Canlı ayar", **_CANLI15),
    C("+ iğne oranı ≤ %58", **dict(_CANLI15, WICKY_MAX=0.58)),
    C("+ dip/tepe 1 ATR bandında ≤ 4 mum", **dict(_CANLI15, PIVOT_BAND2_ATR=1.0, PIVOT_BAND2_MAX=5)),
    C("+ ikisi birden", **dict(_CANLI15, WICKY_MAX=0.58, PIVOT_BAND2_ATR=1.0, PIVOT_BAND2_MAX=5)),
    C("+ ikisi birden, gevşek (iğne ≤ %60, bantta ≤ 5 mum)",
      **dict(_CANLI15, WICKY_MAX=0.60, PIVOT_BAND2_ATR=1.0, PIVOT_BAND2_MAX=6)),
]
# Stop yeri ve erken çıkış esnetme (kullanıcı 15.10 13:41-13:43, "kodla"). Taban = yeni canlı ayar (_YENI, aşağıda).
# 18 ay CSV: erken çıkışta mum dolumun >0.35 ATR gerisinde kapattıysa %30'u sonra TP (tutsaydık +9.0 / +8.2 / +12.9R),
# sığ kapanışlarda %12-19 (erken çıkış doğru). Stop yerinin etkisi CSV'den ölçülemez (aleyhe gidiş yok) → test.
_YENI = dict(live_setups.LIVE_RULES, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)
COMPARE_SETS["stop"] = [
    C("Canlı ayar", **_YENI),
    C("+ stop payı 0.15 ATR (0.3 yerine)", **dict(_YENI, STOP_BUFFER_ATR=0.15)),
    C("+ stop payı yok (onay mumunun dibi)", **dict(_YENI, STOP_BUFFER_ATR=0.0)),
    C("+ stop en fazla 1 ATR uzakta", **dict(_YENI, STOP_MAX_ATR=1.0)),
    C("+ stop en fazla 1.2 ATR uzakta", **dict(_YENI, STOP_MAX_ATR=1.2)),
    C("+ derin kapanışta (> 0.35 ATR) erken çıkış yok", **dict(_YENI, EARLY_EXIT_MAX_ATR=0.35)),
    C("+ derin kapanışta (> 0.5 ATR) erken çıkış yok", **dict(_YENI, EARLY_EXIT_MAX_ATR=0.5)),
]
# Başabaş yeniden (kullanıcı 15.10 15:19 "kodla deneyelim"): sabahki test (eski sistem) iki dönemde kötüydü (1R BE -31.5 /
# -11.4: 31 stop kurtarıp 29 TP'yi girişten çıkarıyordu). Şimdiki canlı sistemle (iki kural + derin kapanışta erken çıkış
# yok) 1R / 1.5R / 2R'de stop girişe. BE_TRIGGER: o seviyeye gelen mumdan SONRAKİ mumdan itibaren stop = dolum.
_CANLI_SON = dict(live_setups.LIVE_RULES, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)
# Başabaş sonucu (15.10 15:29, Nis-Eki 26): canlı +36.5 · 1R -14.0 · 1.5R -1.7 · 2R 0 → red.
# Giriş yeri (kullanıcı 15.10 15:32 "giriş yerini biraz yükseltsek, stopu da"): giriş onay ucundan +0.1 / +0.2 ATR ötede;
# 4-5: stop da aynı kadar yukarıda (stop payı 0.3 → 0.2 / 0.1 ATR), risk aynı kalır.
COMPARE_SETS["giris"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ giriş 0.1 ATR ötede", **dict(_CANLI_SON, ENTRY_BUFFER_ATR=0.1)),
    C("+ giriş 0.2 ATR ötede", **dict(_CANLI_SON, ENTRY_BUFFER_ATR=0.2)),
    C("+ giriş ve stop 0.1 ATR yukarı (risk aynı)", **dict(_CANLI_SON, ENTRY_BUFFER_ATR=0.1, STOP_BUFFER_ATR=0.2)),
    C("+ giriş ve stop 0.2 ATR yukarı (risk aynı)", **dict(_CANLI_SON, ENTRY_BUFFER_ATR=0.2, STOP_BUFFER_ATR=0.1)),
]
# Gemini kodu (kullanıcı 15.10 17:04-17:07): rapor uydurma (kodda TP/stop yok) ama iki şartı bizde yok: EMA100 > EMA200
# ve "temastan önceki 4 mumda son ~24 saatin (92 mum) zirvesi". 8 mumluk sürüm de (bizde düzeltme ortanca 4 mum).
COMPARE_SETS["gemini"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ EMA100 > EMA200 sıralı", **dict(_CANLI_SON, EMA200_ORDER=True)),
    C("+ son 4 mumda 24 saatin zirvesi", **dict(_CANLI_SON, NEW_HIGH_BARS=4)),
    C("+ son 8 mumda 24 saatin zirvesi", **dict(_CANLI_SON, NEW_HIGH_BARS=8)),
    C("+ EMA200 + son 4 mumda zirve (ikisi)", **dict(_CANLI_SON, EMA200_ORDER=True, NEW_HIGH_BARS=4)),
]
# Gemini sonucu (15.10 17:16, Nis-Eki 26): canlı +36.5 · EMA200 -9.1 · son 4 mum -12.3 · son 8 mum +1.2 · ikisi -16.8 → red.
# Yatay yeniden (kullanıcı 15.10 17:20 MAGMAUSDT 02.10 20:30: +1.36R'ye gidip 14 saat yatay, sonra stop): şimdiki sistemle
# 4 / 8 / 12 saatte TP/stop olmadıysa stop girişe (fiyat girişin gerisindeyse o mumun açılışında çık). 15m: 16/32/48 mum.
COMPARE_SETS["yatay2"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ 4 saatte sonuç yoksa stop girişe", **dict(_CANLI_SON, TIME_STOP_BARS=16)),
    C("+ 8 saatte sonuç yoksa stop girişe", **dict(_CANLI_SON, TIME_STOP_BARS=32)),
    C("+ 12 saatte sonuç yoksa stop girişe", **dict(_CANLI_SON, TIME_STOP_BARS=48)),
    # Zigzag düzeltme (kullanıcı 15.10 17:22-17:24, AXLUSDT 04.10 01:15: "tepeden sonra zigzag yaparak inmiş", "yatayın
    # içinde olsun"). Düzeltmede (≥3 mum) trend yönlü mum oranı > eşik ise girme. CSV'de duz_zigzag, duz_donus.
    C("+ zigzag düzeltme yok (ters mum > %50)", **dict(_CANLI_SON, ZIGZAG_MAX=0.5)),
    C("+ zigzag düzeltme yok (ters mum > %34)", **dict(_CANLI_SON, ZIGZAG_MAX=0.34)),
]
# Yatay+zigzag sonucu (15.10 17:31, Nis-Eki 26): canlı +36.5 · 4s -10.0 · 8s -1.6 · 12s +1.7 (1 işlem) · zigzag >%50 -1.0
# · >%34 -0.4 (AXL düz_zigzag 0.25 yakalanmadı) → red, önceki dönemler çalıştırılmadı.
# Kural 2 düzeltmesi (kullanıcı 15.10 17:28-17:32, CARVUSDT 05.10 07:45): kalkış = fiyat EMA20'den X ATR ayrıldığı ilk mum.
COMPARE_SETS["teyit"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ kural 2: kalkış 0.5 ATR ayrılınca", **dict(_CANLI_SON, PRIOR_TOUCH_SEP_ATR=0.5)),
    C("+ kural 2: kalkış 1 ATR ayrılınca", **dict(_CANLI_SON, PRIOR_TOUCH_SEP_ATR=1.0)),
    C("+ kural 2: kalkış 1.5 ATR ayrılınca", **dict(_CANLI_SON, PRIOR_TOUCH_SEP_ATR=1.5)),
]
# Toplu sinyal eşiği şimdiki canlı sistemle (kullanıcı 15.10 19:14 "kodla"). 18 ayda en fazla 2 işlem sınırı hiç işlem
# engellemedi; toplu filtre 87 / 183 / 122 kurulum eledi (tahmini -16.5 / +9.9 / -7.8). Eski "toplu" seti 14.10 kurallarıyla.
COMPARE_SETS["toplu2"] = [
    C("Canlı ayar (aynı mumda 5+ coin varsa girme, en fazla 2 işlem)", **_CANLI_SON),
    C("Toplu sinyal sınırı 8 coin", **dict(_CANLI_SON, cluster_max=8)),
    C("Toplu sinyal sınırı 10 coin", **dict(_CANLI_SON, cluster_max=10)),
    C("Toplu sinyal filtresi kapalı (en fazla 2 işlem)", **dict(_CANLI_SON, cluster_max=0)),
    C("Toplu sinyal filtresi kapalı + en fazla 5 işlem", **dict(_CANLI_SON, cluster_max=0, max_open=5)),
]
# İşlem sayısını artırma taraması (kullanıcı 15.10 21:10 "17 işlem çok az, artırmanın yolunu bul"). 30m / 5m / 1h, daha
# çok coin, toplu filtre kapalı, en fazla 5 işlem zaten denendi (hepsi red). Burada şimdiki canlı sistemden her kural tek tek
# kaldırılıyor / gevşetiliyor: hangisi kâr kaybettirmeden işlem ekliyor (3 dönemde de artı ise o kural gevşetilir).
COMPARE_SETS["artir"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("- kural 1: onay mumu iğnesi ≤ gövde", **dict(_CANLI_SON, WICK_MAX_BODY=0.0)),
    C("- kural 2: trend teyidi (önceki temas)", **dict(_CANLI_SON, REQUIRE_PRIOR_TOUCH=False)),
    C("- kural 4: temiz tepe/dip", **dict(_CANLI_SON, CLEAN_PIVOT_MAX=0)),
    C("- kural 5: fitil temas", **dict(_CANLI_SON, TOUCH_WICK_MIN=0.0)),
    C("- kural 6: tepe/dip iğnesi ≤ 2 gövde", **dict(_CANLI_SON, PIVOT_WICK_MAX=0.0)),
    C("- iğneli git-gel (≤ %58)", **dict(_CANLI_SON, WICKY_MAX=0.0)),
    C("- dip/tepe tabanı (1 ATR bantta ≥5 mum)", **dict(_CANLI_SON, PIVOT_BAND2_ATR=0.0)),
    C("onay 3. muma kadar (şimdi 2)", **dict(_CANLI_SON, CONFIRM_WINDOW=3)),
    C("stop en az %0.3 (şimdi %0.5)", **dict(_CANLI_SON, BASE_MIN_RISK_PCT=0.3)),
    C("önünde en az 0.5R yer (şimdi 1R)", **dict(_CANLI_SON, ROOM_MIN_R=0.5)),
]
# Artır testinden (3 dönem) kural tek tek kaldırılınca hiçbiri 3 dönemde de artı değil. Eklenen işlemlerin içinde 3 dönemde
# de artı olan alt gruplar (veri madenciliği, eşikler hassas → ezber riski): önünde 0.5R yer, stop ≥ 1.5 ATR ise
# (46 iş +7.5 / +3.5 / +1.5) ya da iğne oranı ≤ %45 ise (30 iş +5.7 / +4.6 / +2.5); kural 5'e uymayan temas, önünde ≥ 1.5R
# yer varsa (60 iş -1.6 / +5.2 / +9.6, sınırda). Asıl karar: hiç bakılmamış 4. dönem (önceki3 = Eki 24-Nis 25).
_Y05 = dict(ROOM_RELAX_R=0.5)
COMPARE_SETS["esnet"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("önünde 0.5R yer yeter: stop ≥ 1.5 ATR ise", **dict(_CANLI_SON, **_Y05, ROOM_RELAX_RISK_ATR=1.5)),
    C("önünde 0.5R yer yeter: iğne oranı ≤ %45 ise", **dict(_CANLI_SON, **_Y05, ROOM_RELAX_WICKY=0.45)),
    C("kural 5: fitilsiz temasa önünde ≥ 1.5R yer varsa gir", **dict(_CANLI_SON, TOUCH_WICK_ROOM_R=1.5)),
    C("ilk ikisi birlikte", **dict(_CANLI_SON, **_Y05, ROOM_RELAX_RISK_ATR=1.5, ROOM_RELAX_WICKY=0.45)),
    C("üçü birlikte", **dict(_CANLI_SON, **_Y05, ROOM_RELAX_RISK_ATR=1.5, ROOM_RELAX_WICKY=0.45, TOUCH_WICK_ROOM_R=1.5)),
]
# Dönem dışı sınama (15.10 22:0x): önceki3 (Eki 24-Nis 25, hiç bakılmamış) canlı ayar 49 iş -0.5R. Bugün eklenen
# kurallar dönem dışında da işe yarıyor mu? Kurallar eklendikleri sırayla. `/backtest 180 gelişim önceki3` (+ önceki4).
_SABAH = dict(_CANLI_SON, QUIET_UTC=(0, 4), WICKY_MAX=0.0, PIVOT_BAND2_ATR=0.0, EARLY_EXIT_MAX_ATR=0.0,
              PRIOR_TOUCH_SEP_ATR=0.0)
COMPARE_SETS["gelisim"] = [
    C("15.10 sabahki canlı (03-07 filtresi var)", **_SABAH),
    C("+ 03-07 filtresi kaldırıldı", **dict(_SABAH, QUIET_UTC=(0, 0))),
    C("+ iğneli git-gel + dip/tepe tabanı", **dict(_SABAH, QUIET_UTC=(0, 0), WICKY_MAX=_CANLI_SON["WICKY_MAX"],
                                                   PIVOT_BAND2_ATR=_CANLI_SON["PIVOT_BAND2_ATR"])),
    C("+ derin geri kapanışta erken çıkılmaz", **dict(_CANLI_SON, PRIOR_TOUCH_SEP_ATR=0.0)),
    C("+ trend teyidi 1.5 ATR (şimdiki canlı)", **_CANLI_SON),
    C("şimdiki canlı + 0.5R yer (stop ≥ 1.5 ATR / iğne ≤ %45)",
      **dict(_CANLI_SON, ROOM_RELAX_R=0.5, ROOM_RELAX_RISK_ATR=1.5, ROOM_RELAX_WICKY=0.45)),
]
# Bybit'teki bütün USDT vadeli coinler (kullanıcı 15.10 23:06). Aynı canlı kurallar; "coins": hangi coinler.
# Binance'te de olan coinler aynı sinyali verir (fiyatlar aynı) → yeni işlem sadece "new" grubundan gelir.
# `/backtest 180 bybit` (+ önceki ...). Veri Bybit API'den, diske kaydedilmez (her test yeniden indirir).
COMPARE_SETS["bybit"] = [
    C("Bybit'teki bütün coinler", **_CANLI_SON, coins="all"),
    C("Sadece canlı botun Binance coinleri (aynı sinyaller)", **_CANLI_SON, coins="binance"),
    C("Sadece Binance'te olmayan coinler (YENİ işlemler)", **_CANLI_SON, coins="new"),
]
# 2 mumlu temas (kullanıcı 16.10 01:36, örnek 09.10 12:30): temastan sonraki mum dibi kırsa da EMA20'ye değip doğru
# tarafta kapattıysa iptal yerine iki mum birlikte temas; onay iki mumun en tepesinin üstünde kapanış.
# `/backtest 180 iki mum` (+ önceki ... önceki4), Bybit verisiyle: `/backtest 180 iki mum bybit`.
COMPARE_SETS["ikimum"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ 2 mumlu temas, gövdeler ≤ 0.3 ATR", **dict(_CANLI_SON, TWO_BAR_TOUCH=True, TWO_BAR_BODY_ATR=0.3)),
    C("+ 2 mumlu temas, gövdeler ≤ 0.5 ATR", **dict(_CANLI_SON, TWO_BAR_TOUCH=True, TWO_BAR_BODY_ATR=0.5)),
    C("+ 2 mumlu temas, gövde sınırı yok", **dict(_CANLI_SON, TWO_BAR_TOUCH=True)),
]
# 2 mumlu temas her sırada (kullanıcı 16.10 02:07 "kodla"): dip 1. ya da 2. mumda olabilir; iki mum EMA20'ye değip
# doğru tarafta kapatır, onay iki mumun en tepesinin üstünde kapanış (bekleme 2. mumdan sonra 2 mum).
# İlk test (sadece 2. mum dipte): 5 dönem toplam +1.5 / +1.6 / +2.2R, 30 ayda 15-24 işlem.
COMPARE_SETS["ikimum2"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ 2 mumlu temas her sıra, gövdeler ≤ 0.3 ATR", **dict(_CANLI_SON, TWO_BAR_ANY=True, TWO_BAR_BODY_ATR=0.3)),
    C("+ 2 mumlu temas her sıra, gövdeler ≤ 0.5 ATR", **dict(_CANLI_SON, TWO_BAR_ANY=True, TWO_BAR_BODY_ATR=0.5)),
    C("+ 2 mumlu temas her sıra, gövde sınırı yok", **dict(_CANLI_SON, TWO_BAR_ANY=True)),
]
# Dalgalı bölge (kullanıcı 16.10 04:08, AXL 04.10 01:15 "düzeltme berbat, asla girmem"): temastan önceki 12 mumda renk
# değişimi sayısı + ortalama gövde/ATR. CSV'de dalga_donus, dalga_govde (eşikler sonradan CSV'den de taranır).
# `/backtest 180 dalga` (+ önceki ... önceki4).
COMPARE_SETS["dalga"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("+ dalgalı yok: ≥7 renk değişimi ve gövde ≥0.5 ATR", **dict(_CANLI_SON, CHOP_FLIPS_MIN=7, CHOP_BODY_ATR=0.5)),
    C("+ dalgalı yok: ≥6 renk değişimi ve gövde ≥0.6 ATR", **dict(_CANLI_SON, CHOP_FLIPS_MIN=6, CHOP_BODY_ATR=0.6)),
    C("+ dalgalı yok: ≥7 renk değişimi (gövde serbest)", **dict(_CANLI_SON, CHOP_FLIPS_MIN=7)),
]
# Temas (sinyal) tanımının hiç test edilmemiş temel ayarları (16.10 gece incelemesi, kullanıcı "kaçırdığımız bir şey var
# mı, işlem sayısı"): Stoch eşiği, düzeltmedeki ters mum sayısı, tepenin yakınlığı, EMA20 temas toleransı. Bunlar
# sistemin satıcısından gelen sabitler (strategy.py); temas sinyalini belirledikleri için işlem sayısını doğrudan
# etkiler. "sig": sadece sinyal bulunurken strategy sabitlerinin üzerine yazılır; toplu sinyal sayımı da o tanımla.
COMPARE_SETS["temel"] = [
    C("Canlı ayar", **_CANLI_SON),
    C("Stoch eşiği 40 / 60 (şimdi 30 / 70)", **_CANLI_SON, sig={"STOCH_LONG_MAX": 40, "STOCH_SHORT_MIN": 60}),
    C("Stoch şartı yok", **_CANLI_SON, sig={"STOCH_LONG_MAX": 101, "STOCH_SHORT_MIN": -1}),
    C("Düzeltmede en fazla 3 ters mum (şimdi 2)", **_CANLI_SON, sig={"MAX_EXCEPTION_CANDLES": 3}),
    C("Düzeltmede en fazla 4 ters mum", **_CANLI_SON, sig={"MAX_EXCEPTION_CANDLES": 4}),
    C("Tepe en fazla 45 mum önce (şimdi 30)", **_CANLI_SON, sig={"RECENT": 45}),
    C("EMA20 temas toleransı %0.15 (şimdi %0.03)", **_CANLI_SON, sig={"TOLERANCE_LONG": 1.0015, "TOLERANCE_SHORT": 0.9985}),
]
COMPARE_SETS["basabas2"] = [
    C("Canlı ayar (başabaş yok)", **_CANLI_SON),
    C("+ 1R kârda stop girişe", **dict(_CANLI_SON, BE_TRIGGER=1.0)),
    C("+ 1.5R kârda stop girişe", **dict(_CANLI_SON, BE_TRIGGER=1.5)),
    C("+ 2R kârda stop girişe", **dict(_CANLI_SON, BE_TRIGGER=2.0)),
]
# 5m / 30m yeni kurallarla (kullanıcı 15.10 13:21 "hazırla"). Eski 5m (-3R / 6 ay) ve 30m (-3.5R / 12 ay) testleri iğne +
# dip/tepe tabanı kuralları yokken yapıldı. Aynı zaman diliminde ve dönemde kurallı / kuralsız. /backtest 180 dilim 30m,
# /backtest 90 dilim 5m (+ önceki). 15m'de: kuralsız +22.5 / +27.5 / -19.0, kurallı +27.1 / +32.3 / -1.5.
COMPARE_SETS["dilim"] = [
    C("Yeni canlı ayar (iğne ≤ %58 + dip/tepe tabanı yok)", **_YENI),
    C("Bu sabahki ayar (iki kural yok)", **dict(_YENI, WICKY_MAX=0.0, PIVOT_BAND2_ATR=0.0)),
]
# PDF örneklerinden gelen kurallar (kullanıcı, 14.10 22:3x), iki dönemde doğrulanan erken çıkış (2 mum) üstüne:
# STABLE 09.12.2025 10:45 (dip taban yapmış, giriş dibe 0.36R), ACE 17.04.2026 16:30 (onay mumu çok büyük, tepenin
# hizasında), XMR 19.03.2026 02:45 (temas mumunun dibi önceki mumun dibinin altında)
_EB = dict(_CANLI, FAILED_ENTRY_BARS=2)
COMPARE_SETS["ornek"] = [
    C("Canlı ayar + erken çıkış (2 mum)", **_EB),
    C("+ dip/tepe tabanı: 0.5 ATR bant", **dict(_EB, CLEAN_PIVOT_ATR=0.5)),
    C("+ dip/tepe tabanı: 1 ATR bant", **dict(_EB, CLEAN_PIVOT_ATR=1.0)),
    C("+ önünde en az 0.5R yer", **dict(_EB, ROOM_MIN_R=0.5)),
    C("+ önünde en az 1R yer", **dict(_EB, ROOM_MIN_R=1.0)),
    C("+ onay mumu en fazla 1.2 ATR", **dict(_EB, ATR_MAX_MULT=1.2)),
    C("+ onay mumu en fazla 1 ATR", **dict(_EB, ATR_MAX_MULT=1.0)),
    C("+ temas mumu önceki mumun ucunu geçmesin", **dict(_EB, TOUCH_PREV_EXTREME=True)),
    C("+ hepsi (0.5 ATR bant, 0.5R yer, onay ≤ 1.2 ATR, temas kuralı)",
      **dict(_EB, CLEAN_PIVOT_ATR=0.5, ROOM_MIN_R=0.5, ATR_MAX_MULT=1.2, TOUCH_PREV_EXTREME=True)),
]
# Zaman dilimi / coin büyüklüğü taraması: TP 1:2, aynı anda işlem sınırı ve toplu filtre yok (sistemin kendisi ölçülür)
COMPARE_SETS["tarama"] = [
    C("Orijinal kurallar (taban)", FILTERS=False, RR=2.0),
    C("Canlı kurallar (6 kural + 03-07 yok, klasik)", **dict(live_setups.LIVE_RULES_14_10, ENTRY_MODE="classic", RR=2.0)),
]
COMPARE_SETS["toplu"] = [
    C("Canlı ayar (aynı mumda 5+ coin varsa girme)", **_LIVE_NOW),
    C("Toplu sinyal sınırı 8 coin", **_LIVE_NO_CLUSTER, cluster_max=8),
    C("Toplu sinyal sınırı 12 coin", **_LIVE_NO_CLUSTER, cluster_max=12),
    C("Toplu sinyal filtresi kapalı", **_LIVE_NO_CLUSTER),
]
CHART_CFG = {"hepsi": 0, "yeni": 6, "koruma": 5, "son": 6, "son2": 6, "saat": 3, "tp": 1, "dip": 2, "yapi": 4,
             "destek": 2, "toplu": 3, "igne": 1, "donus": 5,
             "temiz": 5, "temiz_donus": 5, "aday": 4, "tarama": None, "btc": 2, "erken": 1, "ornek": 8, "tp": None, "basabas": None, "sivri": 4, "komisyon": None, "renk": None, "yer": None, "yatay": None, "gevset": None, "kapanis": None, "grafik": None, "grafik2": None, "dilim": None, "stop": None, "basabas2": None, "giris": None, "gemini": None, "yatay2": None, "teyit": None, "toplu2": None, "artir": None, "esnet": None, "gelisim": None, "bybit": None, "ikimum": None, "ikimum2": None, "dalga": None, "temel": None}  # grafikleri çizilecek ayar (listedeki sırası)


def apply_cfg(cfg):
    for k in PARAM_KEYS:
        setattr(tr, k, cfg.get(k, DEFAULTS[k]))


def cfg_name(cfg):
    return cfg["ad"]


# Kullanıcının grafikten gösterdiği örnek işlemler (TR saati): hangi ayarda ne olduğu raporda gösterilir
CHECK_TRADES = [
    ("NILUSDT", "31.07.2026 23:30", "girmezdim: dipten sonra 2 iğneli mum (destek)"),
    ("TRUTHUSDT", "02.10.2026 10:45", "dönüş: tepeye yakın, saatlerce yatay (zaman stopu)"),
    ("VIRTUALUSDT", "05.10.2026 09:30", "dönüş: tepe tek mumda, temiz trend yok"),
    ("HOLOUSDT", "12.10.2026 07:00", "dönüş: giriş önceki tepenin dibinde (kural 7)"),
    ("HOMEUSDT", "18.09.2026 20:15", "dönüş: 10/10 temiz trend (TP)"),
    ("BSVUSDT", "15.09.2026 19:45", "giriş sadece iğneyle, sonraki mum stop (erken çıkış)"),
    ("STABLEUSDT", "09.12.2025 10:45", "dip taban yapmış, giriş dibe yakın"),
    ("ACEUSDT", "17.04.2026 16:30", "onay mumu çok büyük, tepenin hizasında"),
    ("XMRUSDT", "19.03.2026 02:45", "temas mumunun dibi önceki mumun altında"),
    ("TWTUSDT", "15.08.2026 16:45", "dönüş: 10/10 temiz trend (TP)"),
    ("AXSUSDT", "01.08.2026 02:00", "girmezdim (yapı)"),
    ("ADAUSDT", "01.08.2026 13:30", "iyi işlem"),
]
SHORT_STATUS = {"win": "TP", "loss": "STOP", "be": "BAŞABAŞ/ERKEN", "structure_break": "elendi(yapı)", "support": "elendi(destek)",
                "touch_tail": "elendi(ters iğne)", "not_clean": "elendi(temiz değil)", "btc_corr": "elendi(BTC'ye benzer)", "spike_top": "elendi(sivri tepe)",
                "no_room": "elendi(yer)", "open": "açık"}


SWEEP_GROUPS = [("tümü", 1, 10**9), ("ilk 50", 1, 50), ("51-150", 51, 150), ("151+", 151, 10**9)]
TF_TR = {"15m": "15dk", "30m": "30dk", "1h": "1 saat", "4h": "4 saat"}


def build_sweep(frames, tfs, period_txt, p0, days):
    """Zaman dilimi x coin büyüklüğü tablosu: kazanma oranı dönemin iki yarısında ayrı ayrı.
    ✅ = iki yarıda da %40 ve üstü (her yarıda en az 20 işlem)."""
    half = p0 + days * 86400000 // 2
    a = pd.Timestamp(p0, unit="ms", tz="UTC").tz_convert(TZ)
    m = pd.Timestamp(half, unit="ms", tz="UTC").tz_convert(TZ)
    msgs = []
    for name, d in frames.items():
        lines = [f"🔭 <b>TARAMA: {html.escape(name)}</b>",
                 f"{period_txt}, TP 1:2, aynı anda işlem sınırı ve toplu sinyal filtresi yok.",
                 f"Kazanma oranı: tümü (1. yarı {a:%d.%m}– / 2. yarı {m:%d.%m}–) · işlem başı R (komisyonlu)",
                 "✅ = iki yarıda da %40+ (her yarıda en az 20 işlem)", ""]
        t = d[d["durum"].isin(["win", "loss", "be"])] if not d.empty else d
        for tf in tfs:
            tt = t[t["zaman_dilimi"] == tf] if not t.empty else t
            lines.append(f"<b>{TF_TR.get(tf, tf)}</b>")
            for label, lo, hi in SWEEP_GROUPS:
                g = tt[(tt["hacim_sirasi"] >= lo) & (tt["hacim_sirasi"] <= hi)] if not tt.empty else tt
                if g.empty:
                    lines.append(f"  {label}: işlem yok")
                    continue
                h1, h2 = g[g["_touch_ts"] < half], g[g["_touch_ts"] >= half]
                wr = lambda x: 100 * (x["durum"] == "win").mean() if len(x) else float("nan")
                ok = len(h1) >= 20 and len(h2) >= 20 and wr(h1) >= 40 and wr(h2) >= 40
                lines.append(f"  {'✅ ' if ok else ''}{label}: {len(g)} işlem %{wr(g):.0f} "
                             f"(%{wr(h1):.0f} / %{wr(h2):.0f}) · {g['R_net'].mean():+.2f}R")
        msgs.append("\n".join(lines))
    return msgs


def tp_stop_line(t):
    """Sade sonuç: TP / stop / erken çıkış sayıları ve kâr-zarar (R ve $). t: sonuçlanan işlemler."""
    if t is None or t.empty:
        return "işlem yok"
    wins = int((t["durum"] == "win").sum())
    stops = int((t["durum"] == "loss").sum())
    early = int((t["cikis_turu"] == "erken çıkış").sum()) if "cikis_turu" in t else 0
    other = int((t["durum"] == "be").sum()) - early
    net = float(t["R_net"].sum())
    parts = [f"✅ TP {wins}", f"❌ Stop {stops}"]
    if early:
        parts.append(f"↩️ Erken çıkış {early}")
    if other:
        parts.append(f"⚪ Başabaş {other}")
    return " · ".join(parts) + f"\n  {'🟢' if net > 0 else '🔴'} <b>{net:+.1f}R ({usd(net)})</b>"


def mfe_summary(d, name):
    """Fiyatın stop olmadan önce lehte gittiği en uzak nokta (R) dağılımı."""
    t = d[d["durum"].isin(["win", "loss", "be"])] if not d.empty and "mfe_r" in d else None
    if t is None or t.empty:
        return ""
    m = pd.to_numeric(t["mfe_r"], errors="coerce").dropna()
    if m.empty:
        return ""
    pct = lambda x: f"%{100 * (m >= x).mean():.0f}"
    return (f"📏 <b>İşlemler stop olmadan önce en fazla kaç R gitti?</b> ({html.escape(name, quote=False)}, {len(m)} işlem)\n"
            f"1R+: {pct(1)} · 1.5R+: {pct(1.5)} · 2R+: {pct(2)} · 2.2R+: {pct(2.2)}\n"
            f"3R+: {pct(3)} · 4R+: {pct(4)} · 5R+: {pct(5)}\n"
            f"Ortanca: {m.median():.1f}R · Hiç 0.5R'ye bile gitmeyen: %{100 * (m < 0.5).mean():.0f}")


def build_compare(results, period_txt, n_coins, minutes, p0=None, days=30):
    msg = ["📊 <b>KARŞILAŞTIRMA</b>", f"{period_txt}, {n_coins} coin, 1R = {tr.RISK_USD:g}$ (komisyon dahil)", ""]
    best, best_net = None, None
    for name, df_all in results.items():
        t = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
        if not t.empty and (best_net is None or t["R_net"].sum() > best_net):
            best, best_net = name, t["R_net"].sum()
    for no, (name, df_all) in enumerate(results.items(), 1):
        t = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
        star = " ⭐" if name == best else ""
        msg.append(f"<b>{no}) {html.escape(name, quote=False)}</b>{star}")
        msg.append("  " + tp_stop_line(t))
    return "\n".join(msg)


def _old_examples(results):
    checks = []
    for coin, when, note in CHECK_TRADES:
        cells = []
        for no, (name, d) in enumerate(results.items(), 1):
            if d.empty:
                continue
            hit = d[(d["coin"] == coin) & (d["temas"] == when)]
            if not hit.empty:
                st_ = hit["durum"].iloc[0]
                cells.append(f"{no}) {SHORT_STATUS.get(st_, 'elendi')}")
            else:
                cells.append(f"{no}) elendi")  # karşılaştırmada sadece işlemler saklanır
        if cells and any("elendi" not in c for c in cells):
            checks.append(f"• {coin} {when} ({note})\n   " + "  ".join(cells))
    return checks


# TP ile stop olan işlemleri ayıran ölçüler: (sütun, ad, ondalık)
FARK_OLCULER = [
    ("btc_kor", "BTC'ye benzerlik (son 24 saat, 1 = birebir BTC gibi)", 2),
    ("onu_r", "Önceki tepe/dibe mesafe (R)", 2),
    ("bacak_govde", "Bacağın gövde oranı (1 = hepsi iğnesiz düz gövde)", 2),
    ("bacak_atr", "Bacak boyu (ATR)", 1),
    ("tek_mum", "En büyük mumun bacaktaki payı", 2),
    ("ters_mum", "Bacaktaki ters mum oranı", 2),
    ("bacak_mum", "Bacak kaç mum", 0),
    ("ema_acilim", "EMA20–EMA100 açıklığı (ATR)", 1),
    ("ema_egim", "EMA20 eğimi (son 2 saat, ATR)", 2),
    ("trend_yasi", "Trend yaşı (EMA'lar kaç mumdur sıralı, en fazla 300)", 0),
    ("duzeltme", "Düzeltme derinliği (bacağın ne kadarı geri verildi)", 2),
    ("duzeltme_mum", "Düzeltme kaç mum sürdü", 0),
    ("risk_atr", "Stop mesafesi (ATR)", 2),
]


def build_fark(rows, p0, days, title):
    """TP olan işlemlerle stop olanlar arasındaki farklar: her ölçüde işlemler 3 eşit gruba bölünür,
    grupların TP oranı ve işlem başı R'si karşılaştırılır. Mesaj parçaları listesi döner."""
    d = pd.DataFrame(rows)
    if d.empty or "durum" not in d:
        return ["🔬 Fark analizi: işlem yok."]
    d = d[d["durum"].isin(["win", "loss", "be"])]
    n = len(d)
    if n < 30:
        return [f"🔬 Fark analizi için işlem çok az ({n}). Daha uzun dönemle dene (ör. /backtest 90 temiz)."]
    # Tek bir boşluklu (gap) mumun -10R'lik kaybı bütün grubu belirlemesin diye R -3 ile +3 arasına sınırlanır
    wins, losses, R = d["durum"] == "win", d["durum"] == "loss", d["R_net"].astype(float).clip(-3, 3)
    noise = 2 * R.std() * (2 / (n / 3)) ** 0.5   # iki grup ortalaması arasındaki farkın ~2 standart hatası
    n_months = (days + 29) // 30
    months = d["_touch_ts"].apply(lambda t: month_label(t, p0)) if p0 is not None and n_months > 1 else None
    fmt = lambda v, nd: f"{v:.{nd}f}"
    blocks = []
    for col, label, nd in FARK_OLCULER:
        if col not in d:
            continue
        x = pd.to_numeric(d[col], errors="coerce")
        ok = x.notna()
        if ok.sum() < 30:
            continue
        xs, Rs, ws = x[ok], R[ok], wins[ok]
        grp = pd.qcut(xs.rank(method="first"), 3, labels=False)
        parts = []
        for k in range(3):
            m = grp == k
            parts.append((xs[m].min(), xs[m].max(), int(m.sum()), 100 * ws[m].mean(), Rs[m].mean()))
        spread = parts[2][4] - parts[0][4]
        same = tot = 0
        if months is not None:
            lo_cut, hi_cut = parts[0][1], parts[2][0]
            mo = months[ok]
            for k in range(1, n_months + 1):
                lo_r, hi_r = Rs[(mo == k) & (xs <= lo_cut)], Rs[(mo == k) & (xs >= hi_cut)]
                if len(lo_r) >= 5 and len(hi_r) >= 5:
                    tot += 1
                    same += int((hi_r.mean() - lo_r.mean()) * spread > 0)
        strong = abs(spread) >= noise
        mark = "✅" if strong and tot and same == tot else ("🟡" if strong or (tot and same == tot) else "⚪")
        better = "yüksek" if spread > 0 else "düşük"
        lines = [f"{mark} <b>{label}</b>",
                 f"TP'lerde {fmt(xs[ws].median(), nd)}, stoplarda {fmt(xs[losses[ok]].median(), nd)} (ortanca)"]
        for name, (a, b, cnt, wr, avg) in zip(("düşük", "orta", "yüksek"), parts):
            lines.append(f"  {name} ({fmt(a, nd)}…{fmt(b, nd)}): {cnt} işlem, %{wr:.0f} TP, {avg:+.2f}R")
        cons = f", ay ay: {same}/{tot} ayda aynı yönde" if tot else ""
        lines.append(f"  ➜ {better} grup daha iyi ({abs(spread):.2f}R fark{cons})")
        blocks.append((abs(spread) / noise if noise > 0 else 0, "\n".join(lines)))
    blocks.sort(key=lambda b: -b[0])
    head = (f"🔬 <b>TP ile STOP olan işlemler arasındaki farklar</b>\n"
            f"{html.escape(title)}: {n} işlem ({int(wins.sum())} TP, {int(losses.sum())} stop"
            f"{', ' + str(n - int(wins.sum()) - int(losses.sum())) + ' başabaş' if n > wins.sum() + losses.sum() else ''}). "
            f"Örnek çok olsun diye aynı anda işlem sınırı uygulanmadı.\n"
            f"Her ölçüde işlemler 3 eşit gruba bölündü (düşük / orta / yüksek), en belirgin farklar üstte. "
            f"Gruplar arasında ~{noise:.2f}R'den küçük fark şans eseri olabilir.\n"
            f"✅ fark büyük ve her ay aynı yönde · 🟡 ikisinden biri · ⚪ şans olabilir")
    msgs, cur = [], head
    for _, b in blocks:
        if len(cur) + len(b) + 2 > 3800:
            msgs.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    msgs.append(cur)
    return msgs


def send_samples(recs, name, n_each=15):
    """Dönem boyunca eşit aralıklı 15 TP ve 15 stop grafiği (10'arlı albümler) + bütün işlemler PDF.
    Grafikler temiz bir süreçte çizilir: bu süreç sample_charts.py'ye dönüşür (os.execv), veri işlerken tutulan
    bellek bırakılır. Bu yüzden en son adım olarak çağrılır; execv başarılı olursa geri dönmez."""
    import pickle
    import sys
    path = f"/tmp/bt_samples_{os.getpid()}.pkl"
    try:
        with open(path, "wb") as f:
            pickle.dump(recs, f, protocol=pickle.HIGHEST_PROTOCOL)
        log.info("Grafikler ayrı süreçte çizilecek (%d işlem)", len(recs))
        for h in logging.getLogger().handlers:
            h.flush()
        sys.stdout.flush()
        sys.stderr.flush()
        here = os.path.dirname(os.path.abspath(__file__))
        os.execv(sys.executable, [sys.executable, "-u", os.path.join(here, "sample_charts.py"), path, name or ""])
    except (OSError, pickle.PicklingError) as e:
        log.warning("Grafik süreci başlatılamadı (%s), burada çiziliyor", e)
        try:
            os.remove(path)
        except OSError:
            pass
    gc.collect()
    _trim_memory()  # matplotlib yüklenmeden önce boşalan belleği geri ver
    folder = "/tmp/bt_charts"
    shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(folder, exist_ok=True)
    wins, losses = charts.make_samples(recs, folder, n_each)
    label = f" ({name})" if name else ""
    for kind, paths in (("TP", wins), ("STOP", losses)):
        for k in range(0, len(paths), 10):
            part = paths[k:k + 10]
            send_photos(part, f"{kind} örnekleri{label}: {k + 1}-{k + len(part)} / {len(paths)} "
                              f"(dönem boyunca eşit aralıklı)")
    shutil.rmtree(folder, ignore_errors=True)


# ---------------------------------------------------------------- ana
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--rr", type=float, default=None)
    ap.add_argument("--preset", default=None, help="canli: canlı bildirimlerdeki ayarın aynısı")
    ap.add_argument("--be", type=float, default=0.0, help="başabaş tetik (R), 0 = kapalı")
    ap.add_argument("--ago", type=int, default=0, help="dönemi kaç gün geriye kaydır (önceki ay için = days)")
    ap.add_argument("--compare", nargs="?", const="hepsi", default=None,
                    help="ayar setini karşılaştır: hepsi | yeni")
    ap.add_argument("--no-filters", action="store_true", help="ek filtreleri kapat (seans, stop %%0.5-3)")
    ap.add_argument("--atr-min", type=float, default=0.0, help="stop en az kaç ATR (0 = kapalı)")
    ap.add_argument("--wick", type=float, default=0.0, help="onay iğnesi en fazla kaç gövde (0 = kapalı)")
    ap.add_argument("--prior-touch", action="store_true", help="trend teyidi: önceden EMA20 teması")
    ap.add_argument("--stop-buf", type=float, default=0.0, help="stop payı (ATR)")
    ap.add_argument("--top", type=int, default=None, help="hacme göre ilk kaç coin (0 = hepsi; Binance 500, Bybit hepsi)")
    ap.add_argument("--trend", action="store_true", help="trend takibi (Donchian kırılımı) testi")
    ap.add_argument("--exchange", default="binance", choices=["binance", "bybit"], help="veri kaynağı borsa")
    ap.add_argument("--coins", default=None, choices=["all", "binance", "new"],
                    help="Bybit testinde hangi coinler (varsayılan: bybit setinde ayara göre, diğerlerinde binance)")
    ap.add_argument("--max-open", type=int, default=0, help="aynı anda en fazla açık işlem (0 = sınırsız)")
    ap.add_argument("--cluster", type=int, default=0, help="aynı mumda bu kadar sinyal varsa girme (0 = kapalı)")
    ap.add_argument("--btc", action="store_true", help="BTC yön filtresi")
    ap.add_argument("--api", action="store_true", help="veriyi arşiv yerine sadece Binance API'den çek")
    ap.add_argument("--fark", action="store_true", help="TP ile stop olan işlemler arasındaki farkları ölç (ilk ayar)")
    args = ap.parse_args()
    global EXCHANGE, DEFAULT_COINS
    EXCHANGE = args.exchange
    DEFAULT_COINS = args.coins or ("binance" if EXCHANGE == "bybit" and args.compare != "bybit" else "all")
    if args.top is None:
        args.top = 0 if EXCHANGE == "bybit" else 500
    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]
    if "5m" in tfs:
        tfs = ["5m"]  # 5 dakikalık test tek başına çalışır
        set_base_tf("5m")
    global WARMUP_FACTOR
    WARMUP_FACTOR = max(1, max(config.tf_minutes(t) for t in tfs) // (BAR_MS // 60000))
    if args.compare:
        configs = COMPARE_SETS[args.compare]
        chart_idx = CHART_CFG.get(args.compare, 0)
    elif args.preset == "donus":
        import live_setups
        rules = dict(live_setups.LIVE_RULES, ENTRY_MODE="reclaim")
        if args.rr is not None:
            rules["RR"] = args.rr
        configs = [C("dönüş varyasyonu", **rules, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)]
        chart_idx = 0
    elif args.preset == "canli_erken":
        import live_setups
        rules = dict(live_setups.LIVE_RULES, FAILED_ENTRY_BARS=2)
        if args.rr is not None:
            rules["RR"] = args.rr
        configs = [C("canlı ayar + erken çıkış (2 mum)", **rules, cluster_max=live_setups.CLUSTER_MAX,
                     max_open=live_setups.MAX_OPEN)]
        chart_idx = 0
    elif args.preset == "canli":
        import live_setups
        rules = dict(live_setups.LIVE_RULES)
        if args.rr is not None:
            rules["RR"] = args.rr
        configs = [C("canlı ayar", **rules, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)]
        chart_idx = 0
    else:
        configs = [C("tekli", RR=2.0 if args.rr is None else args.rr, BE_TRIGGER=args.be, FILTERS=not args.no_filters,
                     MIN_ATR_MULT=args.atr_min, WICK_MAX_BODY=args.wick,
                     REQUIRE_PRIOR_TOUCH=args.prior_touch, STOP_BUFFER_ATR=args.stop_buf,
                     max_open=args.max_open, cluster_max=args.cluster, btc=args.btc)]
        chart_idx = 0
    apply_cfg(configs[0])
    p0, p1 = period(args.days, args.ago)
    period_txt = (f"{pd.Timestamp(p0, unit='ms', tz='UTC').tz_convert(TZ):%d.%m.%Y} – "
                  f"{pd.Timestamp(p1, unit='ms', tz='UTC').tz_convert(TZ):%d.%m.%Y} ({args.days} gün)")
    if BASE_TF == "5m":
        period_txt += ", 5 dakikalık grafik"

    t0 = time.time()
    clean_cache()
    drop_other_tf_cache()
    global USE_ARCHIVE
    exchanges.WEIGHT_SOFT_LIMIT = exchanges.BACKTEST_SOFT_LIMIT  # canlı taramaya pay bırak
    if EXCHANGE == "bybit":
        USE_ARCHIVE = False
        tr.FEE_TAKER, tr.FEE_MAKER = 0.00055, 0.0002   # Bybit temel vadeli komisyon (taker %0.055, maker %0.02)
        symbols, ticks = bybit.top_symbols(args.top)
        bn = None
        try:
            bn = get_top_symbols(live_setups.UNIVERSE if hasattr(live_setups, "UNIVERSE") else 500, max_wait=60)
        except Exception as e:
            log.warning("Binance coin listesi alınamadı (%s), son kayıttan", e)
            uni = _load_universe()
            bn = uni[0][:500] if uni else None
        if not bn:
            raise RuntimeError("Binance coin listesi alınamadı: hangi coinin yeni olduğu ayrılamıyor")
        BINANCE_SET.update(bybit.norm(x) for x in bn)
        n_new = sum(1 for x in symbols if bybit.norm(x) not in BINANCE_SET)
        source = (f"Bybit API ({len(symbols)} USDT vadeli coin; {len(symbols) - n_new} tanesi canlı botun Binance "
                  f"listesinde de var, {n_new} tanesi yeni). Komisyon Bybit: %0.055 / %0.02")
        need = {cfg.get("coins", DEFAULT_COINS) for cfg in configs}
        if need == {"binance"}:   # sadece ortak coinler: diğerlerinin verisi indirilmez (toplu sinyal de bunlardan sayılır)
            symbols = [x for x in symbols if bybit.norm(x) in BINANCE_SET]
        elif need == {"new"}:
            symbols = [x for x in symbols if bybit.norm(x) not in BINANCE_SET]
        if args.compare != "bybit":
            source += {"binance": ". Test edilen: sadece canlı botun Binance coinleri (aynı coinler, Bybit verisi)",
                       "new": ". Test edilen: sadece Binance'te olmayan coinler",
                       "all": ". Test edilen: bütün Bybit coinleri"}[DEFAULT_COINS]
        log.info("Veri kaynağı: %s", source)
    elif args.api:
        USE_ARCHIVE, source = False, "Binance API (--api)"
    else:
        ok, why = archive_reachable()
        USE_ARCHIVE = ok
        source = (f"Binance arşivi ({why})" if ok else f"Binance API, arşive ulaşılamadı: {why}")
    if EXCHANGE != "bybit":
        log.info("Veri kaynağı: %s", source)
        ticks, symbols = {}, [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    try:
        if EXCHANGE == "bybit":
            raise _SkipBinance
        for attempt in range(3):
            try:
                ticks = get_tick_sizes(max_wait=60)
                break
            except BinanceBlocked:
                raise
            except Exception as e:
                log.warning("Tık büyüklükleri alınamadı (%d. deneme): %s", attempt + 1, e)
                time.sleep(10)
        if not ticks:
            raise RuntimeError("Binance'ten coin bilgileri alınamadı (3 deneme)")
        if not symbols:
            symbols = get_top_symbols(args.top, max_wait=60) if args.top > 0 else fetch_symbols(60)
        _save_universe(symbols, ticks)
    except _SkipBinance:
        pass
    except BinanceBlocked as e:
        # Binance API engelli: coin listesi önceki kayıttan ya da arşivden; bugünün mumları alınamaz
        if not USE_ARCHIVE:
            raise
        uni = _load_universe()
        if uni and (not args.top or len(uni[0]) >= args.top):
            symbols = symbols or uni[0][:args.top or None]
            ticks = uni[1]
            how = "son kaydedilen coin listesi"
        else:
            symbols = symbols or archive.top_symbols(args.top)
            how = "coin listesi arşivden (dünkü hacme göre), fiyat adımı yok"
        source += f". Binance API engelli ({int(e.seconds // 60)} dk): {how}, bugünün mumları yok"
        log.warning("Binance API engelli, %s", how)
    if not symbols:
        raise RuntimeError("Coin listesi alınamadı")
    if args.trend:   # ikinci strateji adayı: trend takibi (ayrı simülasyon, trend_bt.py)
        import trend_bt
        trend_bt.run(symbols, args, load_15m, period, send_message, send_document, TZ)
        return
    log.info("Backtest başlıyor: %d coin, %d gün, %s, %d ayar", len(symbols), args.days, tfs, len(configs))
    what = (f"{len(configs)} farklı ayar karşılaştırılacak" if args.compare else
            f"TP 1:{tr.RR:g}" + (f", başabaş {tr.BE_TRIGGER:g}R" if tr.BE_TRIGGER > 0 else ""))
    universe = f"hacmi en yüksek {len(symbols)} coin" if args.top > 0 and not args.symbols else f"{len(symbols)} coin"
    send_message(f"⏳ Backtest başladı: {universe}, {period_txt}, {what}. "
                 f"Bitince sonuçlar buraya gelecek.\nVeri: {html.escape(source)}")

    def fetch(symbol):
        try:
            return load_15m(symbol, args.days, args.ago)
        except BinanceBlocked:
            raise  # engel uzun sürecek: bütün backtest durur (eksik coinle yanlış sonuç vermesin)
        except Exception as e:
            log.error("%s verisi alınamadı: %s", symbol, e)
            return None

    results = {cfg["ad"]: [] for cfg in configs}
    rank = {sym: k + 1 for k, sym in enumerate(symbols)}  # 24 saatlik hacim sırası (1 = en büyük)
    from collections import Counter
    status_counts = Counter()   # tekli testte bütün setup'ların durumları (huni)
    from collections import defaultdict
    touch_by = defaultdict(Counter)   # sinyal tanımı -> (mum, yön) -> temas veren coin sayısı (toplu sinyal filtresi)
    touch_counts = touch_by[()]       # canlı tanım
    n_ok = 0
    btc_map = None
    examples_txt = []
    def process(n, symbol, df15):
        nonlocal btc_map, n_ok
        try:
            if df15 is None or len(df15) < WARMUP + 50:
                return
            n_ok += 1
            tick = ticks.get(symbol, 0.0)
            for tf in tfs:
                df = prepare(df15 if tf == BASE_TF else resample_tf(df15, config.tf_minutes(tf)))
                if tf in btc_close and symbol != "BTCUSDT":
                    df["BTC_Close"] = btc_close[tf].reindex(df["timestamp"].values).values
                if symbol == "BTCUSDT" and tf == BASE_TF:
                    btc_map = btc_trend_map(df)
                ts_ = df["timestamp"].values
                sigsets = {}
                for key in [()] + [_sig_key(c) for c in configs]:
                    if key in sigsets:
                        continue
                    with _st_override(key):
                        sg = [(i, sd) for i, sd in find_signals(df) if ts_[i] >= p0]  # ısınma payındaki temaslar sayılmaz
                    sigsets[key] = sg
                    touch_by[key].update((int(ts_[i]), side) for i, side in sg)
                signals = sigsets[()]
                on_bn = bybit.norm(symbol) in BINANCE_SET if EXCHANGE == "bybit" else True
                for ci, cfg in enumerate(configs):
                    only = cfg.get("coins", DEFAULT_COINS)
                    if (only == "binance" and not on_bn) or (only == "new" and on_bn):
                        continue
                    apply_cfg(cfg)
                    new = run_df(df, symbol, tf, tick, sigsets[_sig_key(cfg)],
                                 with_ctx=(ci == chart_idx), trades_only=True,
                                 status_counter=None if args.compare else status_counts)
                    for r in new:
                        r["hacim_sirasi"] = rank.get(symbol, 0)
                        if EXCHANGE == "bybit":
                            r["binance_da"] = int(on_bn)
                    results[cfg["ad"]] += new
                if not args.compare:
                    for ex_sym, ex_tf, ex_when in EXAMPLES:
                        if ex_sym == symbol and ex_tf == tf:
                            examples_txt.append(explain_example(df, symbol, tf, tick, ex_when))
                del df
        except Exception as e:
            log.error("%s atlandı: %s", symbol, e)
        if n % 25 == 0:
            _trim_memory()
            el = time.time() - t0
            log.info("%d/%d coin bitti (%.1f dk, kalan ~%.1f dk)", n, len(symbols),
                     el / 60, el / n * (len(symbols) - n) / 60)

    # BTC kapanışları (BTC'ye benzerlik ölçüsü/filtresi için): her coinin tablosuna zaman damgasıyla eşlenir
    btc_close = {}
    try:
        b15 = load_15m("BTCUSDT", args.days, args.ago)
        for tf in tfs:
            b = b15 if tf == BASE_TF else resample_tf(b15, config.tf_minutes(tf))
            btc_close[tf] = pd.Series(b["Close"].values, index=b["timestamp"].values)
        del b15
    except BinanceBlocked:
        raise
    except Exception as e:
        log.warning("BTC verisi alınamadı, BTC'ye benzerlik ölçülmeyecek: %s", e)

    # Aynı anda en fazla MAX_IN_FLIGHT coinin verisi bellekte: işlenen veri hemen bırakılır
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as ex:
        queue = list(symbols)
        pending = {}
        n = 0
        while queue or pending:
            while queue and len(pending) < MAX_IN_FLIGHT:
                sym = queue.pop(0)
                pending[ex.submit(fetch, sym)] = sym
            done, _ = wait(list(pending), return_when=FIRST_COMPLETED)
            for fut in done:
                symbol = pending.pop(fut)
                df15 = fut.result()
                del fut
                n += 1
                process(n, symbol, df15)
                del df15
            del done
            gc.collect(0)

    if btc_map is None and any(cfg.get("btc") for cfg in configs):
        try:
            btc_map = btc_trend_map(prepare(load_15m("BTCUSDT", args.days, args.ago)))
        except Exception as e:
            log.error("BTC verisi alınamadı, BTC filtresi uygulanmayacak: %s", e)
    fark_msgs = []
    if args.fark:
        cfg0 = configs[0]
        rows0 = apply_portfolio(results[cfg0["ad"]], 0, cfg0.get("cluster_max", 0), cfg0.get("btc", False), btc_map,
                                touch_counts=touch_counts)
        title = ("Dönüş varyasyonu" if cfg0.get("ENTRY_MODE") == "reclaim" else "Canlı kurallar") + \
                (", toplu sinyal filtresi açık" if cfg0.get("cluster_max") else "")
        try:
            fark_msgs = build_fark(rows0, p0, args.days, title)
        except Exception as e:
            log.exception("Fark analizi yapılamadı")
            fark_msgs = [f"⚠️ Fark analizi yapılamadı: {type(e).__name__}: {e}"]
        del rows0
    for cfg in configs:
        results[cfg["ad"]] = apply_portfolio(results[cfg["ad"]], cfg.get("max_open", 0),
                                             cfg.get("cluster_max", 0), cfg.get("btc", False), btc_map,
                                             touch_counts=touch_by[_sig_key(cfg)])
    minutes = (time.time() - t0) / 60
    coins_txt = f"{n_ok}/{len(symbols)}" if n_ok < len(symbols) else f"{len(symbols)}"
    if n_ok == 0:
        raise RuntimeError(f"Hiçbir coinin verisi alınamadı ({len(symbols)} coin denendi)")
    if args.compare:
        frames_all = {cfg: pd.DataFrame(rows) for cfg, rows in results.items()}
        report = build_compare(frames_all, period_txt, coins_txt, minutes, p0=p0, days=args.days)
        if args.compare == "tp":
            ms = mfe_summary(frames_all[configs[1]["ad"]], configs[1]["ad"])
            if ms:
                report += "\n\n" + ms
        if args.compare == "tarama":
            fark_msgs = build_sweep(frames_all, tfs, period_txt, p0, args.days) + fark_msgs
        log.info("\n%s\n%s", report, archive.summary() if USE_ARCHIVE else source)
        send_message(report)
        for m in fark_msgs:
            send_message(m)
        parts = [d.assign(ayar=name) for name, d in frames_all.items() if not d.empty]
        if parts:
            out = pd.concat(parts)
            path = f"karsilastirma_{time.strftime('%Y%m%d_%H%M')}.csv"
            out.drop(columns=[c for c in out.columns if c.startswith("_")]).to_csv(
                path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
            send_document(path, "Tüm ayarların işlemleri ('ayar' sütununa göre filtrele)")
        if chart_idx is None:  # tarama: binlerce işlem, grafik yok
            return
        chart_name = configs[chart_idx]["ad"]
        d = frames_all[chart_name]
        if not d.empty:
            recs = d[d["durum"].isin(["win", "loss", "be"])].sort_values("_touch_ts").to_dict("records")
            if recs:
                for rec in recs:
                    rec["_ay"] = month_label(rec["_touch_ts"], p0)
                try:
                    apply_cfg(configs[chart_idx])
                    send_samples(recs, chart_name)
                except Exception as e:
                    log.exception("Grafikler oluşturulamadı: %s", e)
        return

    apply_cfg(configs[0])
    rows = results[configs[0]["ad"]]
    df_all = pd.DataFrame(rows)
    report = build_report(df_all, period_txt, coins_txt, minutes, examples_txt, p0=p0, days=args.days,
                          status_counts=status_counts)
    log.info("\n%s\n%s", report, archive.summary() if USE_ARCHIVE else source)
    send_message(report)
    for m in fark_msgs:
        send_message(m)

    if not df_all.empty:
        path = f"backtest_{time.strftime('%Y%m%d_%H%M')}.csv"
        df_all.drop(columns=[c for c in df_all.columns if c.startswith("_")]).to_csv(
            path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        send_document(path, "İşleme dönen setup'lar (Excel/Sheets ile açılır)")

        trades = df_all[df_all["durum"].isin(["win", "loss", "be"])].sort_values("_touch_ts")
        recs = trades.to_dict("records")
        for rec in recs:
            rec["_ay"] = month_label(rec["_touch_ts"], p0)
        if recs:
            try:
                send_samples(recs, "")
            except Exception as e:
                log.exception("Grafikler oluşturulamadı: %s", e)
                send_message(f"⚠️ Grafikler oluşturulamadı: {e}")


if __name__ == "__main__":
    try:
        main()
    except BinanceBlocked as e:
        log.error("Backtest durdu: %s", e)
        send_message(f"⛔ Backtest durdu: {e}. Engel bitince tekrar başlat (/durum'da Binance satırına bak).")
        raise SystemExit(3)
    except Exception as e:
        log.exception("Backtest hata verdi")
        send_message(f"⚠️ Backtest hata verdi: {type(e).__name__}: {e}")
        raise
