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
    RR=2.2,                     # komisyon sonrası kazanç ~2R olsun diye 1:2.2
    BE_TRIGGER=0.0, FILTERS=False, MIN_ATR_MULT=0.0,
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
_stats = {"started": time.time(), "cycles": 0, "last_run": None, "scanned": 0, "ok": 0, "touches": 0,
          "ready": 0, "cluster": 0, "sent": 0, "secs": 0.0, "total_sent": 0, "last_sent": None,
          "last_error": None, "running_since": None}
_active = {}   # (coin, temas_ts) -> {"side", "status", "entry", "stop", "tp"}


def apply_rules():
    for k, v in LIVE_RULES.items():
        setattr(tr, k, v)


def rules_summary():
    """Şu an gerçekten uygulanan kuralların kısa özeti (açılış mesajı için)."""
    apply_rules()
    parts = [
        f"TP 1:{tr.RR:g}",
        "onay iğnesi ≤ gövde" if tr.WICK_MAX_BODY else None,
        "trend teyidi" if tr.REQUIRE_PRIOR_TOUCH else None,
        f"stop payı {tr.STOP_BUFFER_ATR:g} ATR" if tr.STOP_BUFFER_ATR else None,
        "temiz tepe/dip" if tr.CLEAN_PIVOT_MAX else None,
        "fitil temas" if tr.TOUCH_WICK_MIN else None,
        f"tepe iğnesi ≤ {tr.PIVOT_WICK_MAX:g} gövde" if tr.PIVOT_WICK_MAX else None,
        f"toplu sinyal ≥{CLUSTER_MAX} yok",
        (f"{tr.QUIET_UTC[0] + 3:02d}-{tr.QUIET_UTC[1] + 3:02d} TR yok"
         if tr.QUIET_UTC[0] < tr.QUIET_UTC[1] else None),
        "⚠️ ESKİ FİLTRELER AÇIK" if tr.FILTERS else None,
    ]
    return ", ".join(p for p in parts if p)


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
    cluster_skipped = 0
    for symbol, side, r, df in candidates:
        touch_ts = int(df["timestamp"].values[r["touch"]])
        if (symbol, touch_ts) in _active:
            continue
        if counts[(touch_ts, side)] >= CLUSTER_MAX:
            log.info("Toplu sinyal, atlandı: %s %s (%d coin)", symbol, side, counts[(touch_ts, side)])
            cluster_skipped += 1
            continue
        send_setup(symbol, side, r, df)
        _active[(symbol, touch_ts)] = {"side": side, "status": "pending"}
        sent += 1
    ok = sum(1 for _, df, _, _ in results if df is not None)
    _stats.update(cycles=_stats["cycles"] + 1, last_run=time.time(), scanned=len(todo), ok=ok,
                  touches=sum(counts.values()), ready=len(candidates), cluster=cluster_skipped,
                  sent=sent, secs=time.time() - t0, total_sent=_stats["total_sent"] + sent)
    if sent:
        _stats["last_sent"] = time.time()
    log.info("Setup taraması bitti: %d/%d coin, %d temas, %d aday, %d yeni emir, %d takipte, %.0f sn",
             ok, len(todo), sum(counts.values()), len(candidates), sent, len(_active), time.time() - t0)


def status_text():
    """/durum için canlı tarama özeti."""
    hhmm = lambda t: pd.Timestamp(t, unit="s", tz="UTC").tz_convert(TZ).strftime("%H:%M")
    running = ""
    if _stats["running_since"]:
        running = f"\n⏳ Şu an tarama sürüyor ({time.time() - _stats['running_since']:.0f} sn)"
    if _stats["last_run"] is None:
        nxt = (int(time.time() // 900) + 1) * 900 + 10
        return (f"📋 Canlı tarama: ilk tarama {hhmm(nxt)}'de yapılacak (her 15 dk'lık mum kapanışında)."
                + running)
    up_h = (time.time() - _stats["started"]) / 3600
    lines = [
        f"📋 <b>Canlı tarama</b> (bot {up_h:.1f} saattir açık, {_stats['cycles']} tarama)",
        f"Son tarama {hhmm(_stats['last_run'])}: {_stats['ok']}/{_stats['scanned']} coin, "
        f"{_stats['touches']} temas, {_stats['ready']} onay adayı, {_stats['sent']} bildirim ({_stats['secs']:.0f} sn)",
        f"Açıldığından beri gönderilen EMİR HAZIR: {_stats['total_sent']}"
        + (f" (son: {hhmm(_stats['last_sent'])})" if _stats["last_sent"] else ""),
        f"Takipteki setup: {len(_active)}",
    ]
    if running:
        lines.append(running.strip())
    if _stats["last_error"]:
        lines.append(f"⚠️ Son hata: {_stats['last_error']}")
    return "\n".join(lines)


def _safe_scan(symbol):
    try:
        return scan_symbol(symbol)
    except Exception as e:
        log.debug("%s taranamadı: %s", symbol, e)
        return symbol, None, [], []


def maybe_run():
    """Her 15 dakikalık mum kapandıktan ~10 sn sonra bir kez çalışır.
    Sadece kapanıştan sonraki ilk 60 sn içinde başlar (backtest o sırada Binance'e yol verir);
    bot çeyreğin ortasında açılırsa ilk tarama bir sonraki kapanışta yapılır."""
    now = time.time()
    bucket = int(now // 900)
    sec = now - bucket * 900
    if sec < 10 or sec > 60 or bucket == _state["last_bucket"]:
        return
    _state["last_bucket"] = bucket
    _stats["running_since"] = time.time()
    try:
        run_cycle()
    except Exception as e:
        log.exception("Setup taraması hatası: %s", e)
        _stats["last_error"] = f"{time.strftime('%H:%M')} {type(e).__name__}: {e}"[:200]
    finally:
        _stats["running_since"] = None
