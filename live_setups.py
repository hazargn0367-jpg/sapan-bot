"""
CANLI SETUP BİLDİRİMLERİ

Her 15 dakikalık mum kapanışında hacmi en yüksek coinleri tarar. Bütün kuralları
geçen bir setup'ta onay mumu kapanır kapanmaz "EMİR HAZIR" bildirimi gönderir
(giriş, stop, TP, pozisyon büyüklüğü, grafik, TradingView linki).
Sonra o setup'ı takip edip giriş / iptal / TP / stop olduğunda haber verir.
İşlem açmaz; kararı kullanıcı verir.

Kurallar backtest'teki "1-6 + toplu" ayarıyla aynıdır (trade_rules.py + strategy.py);
ek olarak 03:00-07:00 (TR) arası temaslar dikkate alınmaz.
"""

import html
import logging
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import charts
import strategy as st
import trade_rules as tr
from exchanges import get_klines, get_tick_sizes, get_top_symbols
from telegram import send_message, send_photo

log = logging.getLogger("bot")

UNIVERSE = 500          # hacme göre ilk kaç coin taransın
CLUSTER_MAX = 5         # aynı mumda bu kadar coin aynı yönde temas verirse girme (toplu hareket)
SCAN_THREADS = 6
TZ = "Europe/Istanbul"
CHART_DIR = "/tmp/live_charts"

# Backtest'teki "1-6 + toplu" ayarı
LIVE_RULES = dict(
    RR=2.0, BE_TRIGGER=0.0, FILTERS=False, MIN_ATR_MULT=0.0,
    WICK_MAX_BODY=1.0,          # 1: onay mumunda uzun ters iğne yok
    REQUIRE_PRIOR_TOUCH=True,   # 2: trend teyidi
    STOP_BUFFER_ATR=0.3,        # 3: stop payı
    CLEAN_PIVOT_MAX=3, CLEAN_PIVOT_ATR=0.3,  # 4: temiz tepe/dip
    TOUCH_WICK_MIN=1.0,         # 5: fitil temas mumu
    PIVOT_WICK_MAX=2.0,         # 6: tepe/dip iğnesi uzun değil
    QUIET_UTC=(0, 4),           # 03:00-07:00 TR arası temaslar dikkate alınmaz
)

FINAL = ("win", "loss", "be", "cancel_confirm", "no_entry")
STATUS_MSG = {
    "open": "✅ GİRİŞ GERÇEKLEŞTİ",
    "win": "🎯 TP OLDU",
    "loss": "🛑 STOP OLDU",
    "be": "⚪ BAŞABAŞ",
    "cancel_confirm": "❌ İPTAL: fiyat girişten önce onay mumunun ucunu kırdı",
    "no_entry": "⌛ İPTAL: 2 mumda girişe gelmedi",
}

_state = {"symbols": [], "symbols_time": 0.0, "ticks": {}, "last_bucket": None}
_active = {}   # (coin, temas_ts) -> {"side", "status", "entry", "stop", "tp"}


def apply_rules():
    for k, v in LIVE_RULES.items():
        setattr(tr, k, v)


def prepare(df):
    df = st.add_indicators(df.reset_index(drop=True))
    return tr.add_atr(df)


def fmt(ts_ms, fmt_str="%d.%m %H:%M"):
    return pd.Timestamp(int(ts_ms), unit="ms", tz="UTC").tz_convert(TZ).strftime(fmt_str)


def p(x):
    return f"{x:.8g}"


def refresh_universe():
    if not _state["symbols"] or time.time() - _state["symbols_time"] > 3600:
        try:
            syms = get_top_symbols(UNIVERSE)
            ticks = get_tick_sizes()
            if syms:
                _state.update(symbols=syms, ticks=ticks, symbols_time=time.time())
                log.info("Setup taraması: %d coin", len(syms))
        except Exception as e:
            log.error("Coin listesi alınamadı: %s", e)
    return _state["symbols"]


def closed_candles(symbol):
    df = get_klines(symbol, "15m")
    if df is None or len(df) < 250:
        return None
    df = df.iloc[:-1]  # son satır hâlâ açık olan mum
    return prepare(df)


def scan_symbol(symbol):
    """Son mumlardaki temasları ve tamamlanan onayları bulur."""
    df = closed_candles(symbol)
    if df is None:
        return symbol, None, [], []
    n = len(df)
    tick = _state["ticks"].get(symbol, 0.0)
    ts = df["timestamp"].values
    touches, ready = [], []
    # Onay temastan sonraki 3 mum içinde gelir: son 4 mumdaki temaslara bak
    for i in range(max(0, n - 1 - tr.CONFIRM_WINDOW), n):
        sig = st.evaluate_at(df, i)
        if not sig:
            continue
        touches.append((int(ts[i]), sig["side"]))
        r = tr.simulate(df, i, sig["side"], tick)
        if r["status"] == "pending" and r.get("confirm") == n - 1 and "entry" in r:
            ready.append((i, sig["side"], r))
    return symbol, df, touches, ready


def setup_message(symbol, side, r, df):
    ts = df["timestamp"].values
    risk = abs(r["entry"] - r["stop"])
    qty = tr.RISK_USD / risk if risk else 0
    notional = qty * r["entry"]
    valid_until = int(ts[r["confirm"]]) + (tr.ENTRY_WINDOW + 1) * 15 * 60 * 1000
    tv = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P&interval=15"
    emoji = "🟢" if side == "LONG" else "🔴"
    order = "BUY STOP" if side == "LONG" else "SELL STOP"
    return (
        f"📋 <b>EMİR HAZIR</b>  {emoji} <b>{side} {html.escape(symbol)}</b> (15m)\n\n"
        f"Giriş ({order}): <code>{p(r['entry'])}</code>\n"
        f"Stop: <code>{p(r['stop'])}</code>  (%{100 * risk / r['entry']:.2f})\n"
        f"TP (1:{tr.RR:g}): <code>{p(r['tp'])}</code>\n"
        f"{tr.RISK_USD:g}$ risk için: ~{notional:,.0f} USDT pozisyon ({qty:.6g} adet)\n\n"
        f"Temas {fmt(ts[r['touch']])}, onay {fmt(ts[r['confirm']])}\n"
        f"Emir {fmt(valid_until, '%H:%M')}'e kadar geçerli. Girişten önce fiyat onay mumunun "
        f"{'dibini' if side == 'LONG' else 'tepesini'} kırarsa iptal.\n"
        f'<a href="{tv}">TradingView\'da aç</a>'
    )


def send_setup(symbol, side, r, df):
    caption = setup_message(symbol, side, r, df)
    try:
        os.makedirs(CHART_DIR, exist_ok=True)
        ts = df["timestamp"].values
        trade = {
            "_ctx": charts.context(df, r), "coin": symbol, "zaman_dilimi": "15m", "yon": side,
            "durum": "pending", "giris": r["entry"], "stop": r["stop"], "tp": r["tp"],
            "temas": fmt(ts[r["touch"]], "%d.%m.%Y %H:%M"),
            "temas_utc": pd.Timestamp(int(ts[r["touch"]]), unit="ms", tz="UTC").strftime("%H:%M"),
        }
        path = f"{CHART_DIR}/{symbol}_{int(ts[r['touch']])}.png"
        charts.draw(trade, path=path)
        if send_photo(path, caption):
            return
    except Exception as e:
        log.error("%s grafik çizilemedi: %s", symbol, e)
    send_message(caption)


def follow_up(symbol, df):
    """Bildirilen setup'ların durumunu güncelle (giriş / iptal / TP / stop)."""
    ts = df["timestamp"].values
    tick = _state["ticks"].get(symbol, 0.0)
    for key in [k for k in _active if k[0] == symbol]:
        info = _active[key]
        hits = np.flatnonzero(ts == key[1])
        if len(hits) == 0:
            _active.pop(key)
            continue
        r = tr.simulate(df, int(hits[0]), info["side"], tick)
        status = r["status"]
        if status == info["status"] or status == "pending":
            continue
        lines = []
        # Aynı mumda hem giriş hem çıkış olduysa ikisini de yaz
        if info["status"] == "pending" and status in ("win", "loss", "be", "open"):
            lines.append(f"✅ Giriş gerçekleşti: {p(r.get('fill', r['entry']))} ({fmt(ts[r['entry_bar']])})")
        if status in STATUS_MSG and status != "open":
            line = STATUS_MSG[status]
            if status in ("win", "loss", "be"):
                line += f": {p(r['exit'])}  →  <b>{r['r_net']:+.2f}R ({r['r_net'] * tr.RISK_USD:+.0f}$)</b>"
            lines.append(line)
        if lines:
            emoji = "🟢" if info["side"] == "LONG" else "🔴"
            send_message(f"{emoji} <b>{info['side']} {html.escape(symbol)}</b> (temas {fmt(key[1])})\n" + "\n".join(lines))
        info["status"] = status
        if status in FINAL:
            _active.pop(key)


def run_cycle():
    apply_rules()
    symbols = refresh_universe()
    if not symbols:
        return
    t0 = time.time()
    watch = {k[0] for k in _active}
    todo = list(dict.fromkeys(list(symbols) + sorted(watch)))
    with ThreadPoolExecutor(max_workers=SCAN_THREADS) as ex:
        results = list(ex.map(lambda s: _safe_scan(s), todo))

    counts = Counter()
    candidates = []
    for symbol, df, touches, ready in results:
        if df is None:
            continue
        counts.update(touches)
        if symbol in watch:
            follow_up(symbol, df)
        for i, side, r in ready:
            candidates.append((symbol, side, r, df))

    sent = 0
    for symbol, side, r, df in candidates:
        touch_ts = int(df["timestamp"].values[r["touch"]])
        if (symbol, touch_ts) in _active:
            continue
        if counts[(touch_ts, side)] >= CLUSTER_MAX:
            log.info("Toplu sinyal, atlandı: %s %s (%d coin)", symbol, side, counts[(touch_ts, side)])
            continue
        send_setup(symbol, side, r, df)
        _active[(symbol, touch_ts)] = {"side": side, "status": "pending"}
        sent += 1
    log.info("Setup taraması bitti: %d coin, %d yeni emir, %d takipte, %.0f sn",
             len(todo), sent, len(_active), time.time() - t0)


def _safe_scan(symbol):
    try:
        return scan_symbol(symbol)
    except Exception as e:
        log.debug("%s taranamadı: %s", symbol, e)
        return symbol, None, [], []


def maybe_run():
    """Her 15 dakikalık mum kapandıktan ~10 sn sonra bir kez çalışır."""
    now = time.time()
    bucket = int(now // 900)
    if now - bucket * 900 < 10 or bucket == _state["last_bucket"]:
        return
    _state["last_bucket"] = bucket
    try:
        run_cycle()
    except Exception as e:
        log.exception("Setup taraması hatası: %s", e)
