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
    "skip_btc": "BTC ters yönde (portföy koruması)",
    "skip_cluster": "Aynı mumda çok sayıda sinyal (portföy koruması)",
    "skip_open": "Açık işlem sınırı dolu (portföy koruması)",
    "min_risk": "Stop mesafesi çok dar",
    "max_risk": "Stop mesafesi %3'ten geniş",
    "session": "Temas 00-08 UTC (Asya seansı)",
    "cancel_confirm": "Girişten önce onay mumunun ucu kırıldı",
    "no_entry": "2 mumda girişe gelmedi",
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
    if end_ms < time.time() * 1000 - OLD_DAYS * 86400 * 1000:
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
            f = tr.trend_features(df, i, side, entry=r["entry"], risk=r["risk"])
            row.update({k: (round(v, 3) if isinstance(v, float) else v) for k, v in f.items() if not k.startswith("_")})
            if r["status"] in ("win", "loss", "be"):
                if r.get("early_exit") or r.get("time_exit"):
                    row["cikis_turu"] = "erken çıkış" if r.get("early_exit") else "zaman stopu"
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
              "FAILED_ENTRY_BARS", "TOUCH_PREV_EXTREME", "ATR_MAX_MULT"]
DEFAULTS = {k: getattr(tr, k) for k in PARAM_KEYS}


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
COMPARE_SETS["tp"] = [
    C("Canlı kurallar 1:2", **_LIVE, RR=2.0),
    C("Canlı kurallar 1:2.2 (canlıdaki)", **_LIVE, RR=2.2),
    C("Canlı kurallar 1:2.5", **_LIVE, RR=2.5),
    C("Canlı kurallar 1:1.5", **_LIVE, RR=1.5),
]
# Karşılaştırma setleri klasik sistemde sabit (canlı 14.10'dan beri klasik + dönüş; o: --preset canli)
_LIVE_NOW = dict(live_setups.LIVE_RULES, ENTRY_MODE="classic", cluster_max=live_setups.CLUSTER_MAX,
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
_LIVE_NO_CLUSTER = dict(live_setups.LIVE_RULES, ENTRY_MODE="classic")
# BTC'ye benzerlik filtresi (kullanıcı, 14.10): coin BTC gibi hareket ediyorsa girme. Canlı ayar = klasik + dönüş
_CANLI = dict(live_setups.LIVE_RULES, cluster_max=live_setups.CLUSTER_MAX, max_open=live_setups.MAX_OPEN)
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
    C("Canlı kurallar (6 kural + 03-07 yok, klasik)", **dict(live_setups.LIVE_RULES, ENTRY_MODE="classic", RR=2.0)),
]
COMPARE_SETS["toplu"] = [
    C("Canlı ayar (aynı mumda 5+ coin varsa girme)", **_LIVE_NOW),
    C("Toplu sinyal sınırı 8 coin", **_LIVE_NO_CLUSTER, cluster_max=8),
    C("Toplu sinyal sınırı 12 coin", **_LIVE_NO_CLUSTER, cluster_max=12),
    C("Toplu sinyal filtresi kapalı", **_LIVE_NO_CLUSTER),
]
CHART_CFG = {"hepsi": 0, "yeni": 6, "koruma": 5, "son": 6, "son2": 6, "saat": 3, "tp": 1, "dip": 2, "yapi": 4,
             "destek": 2, "toplu": 3, "igne": 1, "donus": 5,
             "temiz": 5, "temiz_donus": 5, "aday": 4, "tarama": None, "btc": 2, "erken": 1, "ornek": 8}  # grafikleri çizilecek ayar (listedeki sırası)


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
                "touch_tail": "elendi(ters iğne)", "not_clean": "elendi(temiz değil)", "btc_corr": "elendi(BTC'ye benzer)",
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
    ap.add_argument("--top", type=int, default=500, help="hacme göre ilk kaç coin (0 = hepsi)")
    ap.add_argument("--max-open", type=int, default=0, help="aynı anda en fazla açık işlem (0 = sınırsız)")
    ap.add_argument("--cluster", type=int, default=0, help="aynı mumda bu kadar sinyal varsa girme (0 = kapalı)")
    ap.add_argument("--btc", action="store_true", help="BTC yön filtresi")
    ap.add_argument("--api", action="store_true", help="veriyi arşiv yerine sadece Binance API'den çek")
    ap.add_argument("--fark", action="store_true", help="TP ile stop olan işlemler arasındaki farkları ölç (ilk ayar)")
    args = ap.parse_args()
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
    if args.api:
        USE_ARCHIVE, source = False, "Binance API (--api)"
    else:
        ok, why = archive_reachable()
        USE_ARCHIVE = ok
        source = (f"Binance arşivi ({why})" if ok else f"Binance API, arşive ulaşılamadı: {why}")
    log.info("Veri kaynağı: %s", source)
    ticks, symbols = {}, [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    try:
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
    touch_counts = Counter()    # (mum, yön) -> temas veren coin sayısı (toplu sinyal filtresi, canlıdaki gibi)
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
                signals = [(i, sd) for i, sd in find_signals(df) if ts_[i] >= p0]  # ısınma payındaki temaslar sayılmaz
                touch_counts.update((int(ts_[i]), side) for i, side in signals)
                for ci, cfg in enumerate(configs):
                    apply_cfg(cfg)
                    new = run_df(df, symbol, tf, tick, signals,
                                 with_ctx=(ci == chart_idx), trades_only=True,
                                 status_counter=None if args.compare else status_counts)
                    for r in new:
                        r["hacim_sirasi"] = rank.get(symbol, 0)
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
                                             touch_counts=touch_counts)
    minutes = (time.time() - t0) / 60
    coins_txt = f"{n_ok}/{len(symbols)}" if n_ok < len(symbols) else f"{len(symbols)}"
    if n_ok == 0:
        raise RuntimeError(f"Hiçbir coinin verisi alınamadı ({len(symbols)} coin denendi)")
    if args.compare:
        frames_all = {cfg: pd.DataFrame(rows) for cfg, rows in results.items()}
        report = build_compare(frames_all, period_txt, coins_txt, minutes, p0=p0, days=args.days)
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
