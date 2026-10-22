"""
30 DAKİKALIK SADECE BİLDİRİM (kullanıcı 22.10 04:11 "kodla")

Aynı kurallar (LIVE_RULES) 30dk mumlarda. Otomatik işlem AÇILMAZ: onay mumu kapanınca "🔔 30dk BİLDİRİM" gelir
(giriş / stop / TP, 1R ve 0.5R için pozisyon, grafik, Girdim / Girmedim düğmeleri), sonra giriş / erken çık / TP / stop
mesajları. Karar kullanıcının (grafiği beğenirse elle girer).

Neden sadece bildirim: 7 dönem backtest (`/backtest 180 çoklu`): 15dk + 30dk birlikte 2024-26'da canlıdan iyi (+26R / 30 ay)
ama 2023'te kötü (−13R), toplam +11R / 42 ay ve daha büyük düşüş → otomatiğe alınmadı. Günlükte 30dk ayrı satırda ölçülür.

Veri: 15dk taramadan ayrı önbellek + ayrı WebSocket akışı (kline_30m, REST ağırlığı yok); eksik mumlar REST'ten
(son 40 mum = 1 ağırlık; ilk açılışta tamamı = 2 ağırlık, exchanges'teki dakika sınırına uyar). 15dk taraması bittikten
sonra aynı iş parçacığında çalışır (kurallar aynı, trade_rules ayarları çakışmaz). /otuz aç|kapat.
"""

import html
import logging
import os
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

import config
import journal
import live_setups as ls
import strategy as st
import trade_rules as tr
from exchanges import KLINE_LIMIT as KLINE_KEEP, get_klines
from telegram import decision_buttons, send_message, send_photo

log = logging.getLogger("bot")

TF = os.environ.get("ALT_TF", "30m")
TF_MIN = config.tf_minutes(TF)
TF_SEC = TF_MIN * 60
RECOVER_BARS = 30          # yeniden başlarken son 30 mumdaki (15 saat) bildirilmiş setup'lar takibe geri alınır
ENABLED = os.environ.get("ALT_ALERTS", "1") != "0"

_kcache = {}
_active = {}   # (coin, temas_ts) -> {"side", "status"}
_feed = None
_state = {"last_bucket": None, "recovered": False}
_stats = {"cycles": 0, "last_run": None, "ok": 0, "scanned": 0, "touches": 0, "ready": 0, "cluster": 0,
          "sent": 0, "total_sent": 0, "secs": 0.0, "last_sent": None, "last_error": None,
          "ws": 0, "rest": 0, "full": 0}


def feed():
    global _feed
    if not ls.USE_WS:
        return None
    if _feed is None:
        import ws_klines
        _feed = ws_klines.KlineFeed(TF)
    return _feed


def fetch_candles(symbol):
    """Son KLINE_KEEP kapanmış 30dk mum (live_setups.fetch_candles'ın aynısı, kendi önbelleği ve akışıyla)."""
    old = _kcache.get(symbol)
    step = TF_SEC * 1000
    want_last = (int(time.time() * 1000) // step - 1) * step
    ws_only = ls._state.get("ws_only")
    if old is not None and len(old):
        last = int(old["timestamp"].iloc[-1])
        if last >= want_last:
            return old
        f = feed()
        if f is not None:
            rows = [r for r in f.closed_after(symbol, last) if r[0] <= want_last]
            if (rows and rows[0][0] == last + step and rows[-1][0] == want_last
                    and all(b[0] - a[0] == step for a, b in zip(rows, rows[1:]))):
                add = pd.DataFrame(rows, columns=["timestamp", "Open", "High", "Low", "Close"])
                add["timestamp"] = add["timestamp"].astype(old["timestamp"].dtype)
                df = pd.concat([old, add]).tail(KLINE_KEEP).reset_index(drop=True)
                _kcache[symbol] = df
                _stats["ws"] += 1
                return df
        if ws_only:
            return None
        if want_last - last < (ls.INCREMENTAL_LIMIT - 5) * step:
            new = ls._closed_only(get_klines(symbol, TF, limit=ls.INCREMENTAL_LIMIT), want_last)
            if new is None:
                return None
            df = (pd.concat([old, new]).drop_duplicates("timestamp", keep="last")
                  .sort_values("timestamp").tail(KLINE_KEEP).reset_index(drop=True))
            _kcache[symbol] = df
            _stats["rest"] += 1
            return df
    if ws_only:
        return None
    df = ls._closed_only(get_klines(symbol, TF), want_last)
    if df is None:
        return None
    _kcache[symbol] = df
    _stats["full"] += 1
    return df


def scan_symbol(symbol, keep_df=False, lookback=None):
    df = fetch_candles(symbol)
    if df is None or len(df) < 250:
        return symbol, None, [], [], []
    df = ls.prepare(df)
    n = len(df)
    tick = ls._state["ticks"].get(symbol, 0.0)
    ts = df["timestamp"].values
    touches, ready, recovered = [], [], []
    arr = st.arrays(df)
    for i in range(max(0, n - 1 - (lookback or tr.CONFIRM_WINDOW)), n):
        sig = st.evaluate_at(df, i, arr)
        if not sig:
            continue
        touches.append((int(ts[i]), sig["side"]))
        r = tr.simulate(df, i, sig["side"], tick)
        if r["status"] == "pending" and r.get("confirm") == n - 1 and "entry" in r:
            ready.append((i, sig["side"], r))
        elif lookback and "entry" in r and r["status"] in ("pending", "open") and r["confirm"] < n - 1:
            recovered.append((int(ts[i]), sig["side"], r["status"]))
    if not ready and not keep_df:
        return symbol, False, touches, ready, recovered
    return symbol, df, touches, ready, recovered


def _safe_scan(symbol, keep_df=False, lookback=None):
    try:
        return scan_symbol(symbol, keep_df, lookback)
    except Exception as e:
        log.debug("%s (%s) taranamadı: %s", symbol, TF, e)
        return symbol, None, [], [], []


def _busy_note(symbol):
    """Bu coinde 15dk bildirimi / otomatik işlem varsa uyarı (Binance tek yön: coinde tek pozisyon)."""
    notes = []
    if any(k[0] == symbol and v["status"] in ("pending", "open") for k, v in ls._active.items()):
        notes.append("15dk setup'ı takipte")
    try:
        import autotrade
        if any(x["symbol"] == symbol and x["status"] in ("pending", "open") for x in autotrade.trades().values()):
            notes.append("otomatik işlem açık/bekliyor")
    except Exception:
        pass
    return f"⚠️ Bu coinde {', '.join(notes)}: aynı coinde ikinci pozisyon açılamaz.\n" if notes else ""


def setup_message(symbol, side, r, df):
    ts = df["timestamp"].values
    risk = abs(r["entry"] - r["stop"])
    qty = ls.ALERT_RISK_USD / risk if risk else 0
    notional = qty * r["entry"]
    valid_until = int(ts[r["confirm"]]) + (tr.ENTRY_WINDOW + 1) * TF_SEC * 1000
    tv = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P&interval={TF_MIN}"
    emoji = "🟢" if side == "LONG" else "🔴"
    order = "BUY STOP" if side == "LONG" else "SELL STOP"
    mode = r.get("mode", "classic")
    fmt = ls.fmt
    p = ls.p
    steps = (f"Temas {fmt(ts[r['touch']])}, dönüş {fmt(ts[r['reclaim']])}, onay {fmt(ts[r['confirm']])}"
             if "reclaim" in r else f"Temas {fmt(ts[r['touch']])}, onay {fmt(ts[r['confirm']])}")
    under = "altında" if side == "LONG" else "üstünde"
    early = ""
    if tr.FAILED_ENTRY_BARS:
        early = (f"Giriş mumu ya da sonraki {TF_MIN}dk mumu girişin {under} kapatırsa ⚠️ ERKEN ÇIK mesajı gelir"
                 + (f"; ama kapanış {p(r['entry'] - tr.EARLY_EXIT_MAX_ATR * r['atr'] if side == 'LONG' else r['entry'] + tr.EARLY_EXIT_MAX_ATR * r['atr'])}"
                    f" seviyesinin {'altındaysa' if side == 'LONG' else 'üstündeyse'} çıkılmaz, stop / TP beklenir"
                    if tr.EARLY_EXIT_MAX_ATR > 0 and r.get("atr") else "") + ".\n")
    return (
        f"🔔 <b>{TF_MIN}dk BİLDİRİM</b>  {emoji} <b>{side} {html.escape(symbol)}</b> ({TF}, {ls.MODE_TR.get(mode, mode)})\n"
        f"<i>Otomatik işlem açılmaz, karar senin. Stop/TP emirlerini kendin koy.</i>\n\n"
        f"Giriş ({order}): <code>{p(r['entry'])}</code>\n"
        f"Stop: <code>{p(r['stop'])}</code>  (%{100 * risk / r['entry']:.2f})\n"
        f"TP (1:{tr.RR:g}): <code>{p(r['tp'])}</code>\n"
        f"1R = {ls.ALERT_RISK_USD:g}$: ~{notional:,.0f} USDT ({qty:.6g} adet) · "
        f"0.5R = {ls.ALERT_RISK_USD / 2:g}$: ~{notional / 2:,.0f} USDT ({qty / 2:.6g} adet)\n\n"
        f"{steps}\n"
        f"Emir {fmt(valid_until, '%H:%M')}'e kadar geçerli. Girişten önce fiyat onay mumunun "
        f"{'dibini' if side == 'LONG' else 'tepesini'} kırarsa iptal.\n"
        f"{early}{_busy_note(symbol)}"
        f'<a href="{tv}">TradingView\'da aç ({TF_MIN}dk)</a>'
    )


def send_setup(symbol, side, r, df):
    caption = setup_message(symbol, side, r, df)
    touch_ts = int(df["timestamp"].values[r["touch"]])
    try:
        journal.record_alert(symbol, touch_ts, side, float(r["entry"]), float(r["stop"]), float(r["tp"]),
                             mode=r.get("mode"), tf=TF)
    except Exception as e:
        log.error("Günlüğe yazılamadı: %s", e)
    buttons = decision_buttons(journal.key_of(symbol, touch_ts, TF))
    try:
        import charts
        os.makedirs(ls.CHART_DIR, exist_ok=True)
        ts = df["timestamp"].values
        trade = {
            "_ctx": charts.context(df, r), "coin": symbol, "zaman_dilimi": TF, "yon": side,
            "durum": "pending", "giris": r["entry"], "stop": r["stop"], "tp": r["tp"],
            "varyasyon": ls.MODE_TR.get(r.get("mode", "classic")),
            "temas": ls.fmt(ts[r["touch"]], "%d.%m.%Y %H:%M"),
            "temas_utc": pd.Timestamp(int(ts[r["touch"]]), unit="ms", tz="UTC").strftime("%H:%M"),
        }
        path = f"{ls.CHART_DIR}/{symbol}_{TF}_{int(ts[r['touch']])}.png"
        charts.draw(trade, path=path)
        sent = send_photo(path, caption, buttons)
        try:
            os.remove(path)
        except OSError:
            pass
        if sent:
            return
    except Exception as e:
        log.error("%s (%s) grafik çizilemedi: %s", symbol, TF, e)
    send_message(caption, buttons)


def follow_up(symbol, df):
    ts = df["timestamp"].values
    tick = ls._state["ticks"].get(symbol, 0.0)
    p = ls.p
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
        if info["status"] == "pending" and status in ("win", "loss", "be", "open"):
            lines.append(f"✅ Giriş seviyesi geldi: {p(r.get('fill', r['entry']))} ({ls.fmt(ts[r['entry_bar']])})")
        if status == "be" and r.get("early_exit"):
            under = "altında" if info["side"] == "LONG" else "üstünde"
            lines.append(f"⚠️ <b>ERKEN ÇIK</b>: {ls.fmt(ts[r['exit_bar']])} mumu girişin {under} kapattı ({p(r['exit'])}), "
                         f"kırılım tutmadı. Girdiysen pozisyonu şimdi piyasa emriyle kapat.\n"
                         f"Bu kapanıştan çıkışla: <b>{r['r_net']:+.2f}R ({r['r_net'] * ls.ALERT_RISK_USD:+.2f}$)</b>")
        elif status in ls.STATUS_MSG and status != "open":
            line = ls.STATUS_MSG[status]
            if status in ("win", "loss", "be"):
                line += f": {p(r['exit'])}  →  <b>{r['r_net']:+.2f}R ({r['r_net'] * ls.ALERT_RISK_USD:+.2f}$)</b>"
            lines.append(line)
        if lines:
            emoji = "🟢" if info["side"] == "LONG" else "🔴"
            send_message(f"🔔 {emoji} <b>{info['side']} {html.escape(symbol)}</b> ({TF_MIN}dk, temas {ls.fmt(key[1])})\n"
                         + "\n".join(lines))
        info["status"] = status
        try:
            journal.set_result(symbol, key[1], status, r.get("r_net") if status in ("win", "loss", "be") else None, tf=TF)
        except Exception as e:
            log.error("Günlüğe yazılamadı: %s", e)
        if status in ls.FINAL:
            _active.pop(key)


def run_cycle():
    ls.apply_rules()
    if ls.exchanges.blocked_for() > 120 and not (ls._state.get("ws_only") and _feed is not None and _feed.healthy()):
        _stats["last_error"] = f"{ls.fmt(time.time() * 1000, '%H:%M')} Binance engeli: {TF} taraması atlandı"
        return
    symbols = ls._state["symbols"]
    if not symbols:
        return
    t0 = time.time()
    for k in ("ws", "rest", "full"):
        _stats[k] = 0
    f = feed()
    if f is not None:
        f.set_symbols(symbols)
    for k in [k for k in _kcache if k not in set(symbols)]:
        _kcache.pop(k, None)
    watch = {k[0] for k in _active}
    todo = list(dict.fromkeys(list(symbols) + sorted(watch)))
    recover = None if _state["recovered"] else RECOVER_BARS
    with ThreadPoolExecutor(max_workers=ls.SCAN_THREADS) as ex:
        results = list(ex.map(lambda s: _safe_scan(s, s in watch, recover), todo))

    counts = Counter()
    candidates, rec_list = [], []
    for symbol, df, touches, ready, recovered in results:
        if df is None:
            continue
        counts.update(touches)
        if symbol in watch and df is not False:
            follow_up(symbol, df)
        for i, side, r in ready:
            candidates.append((symbol, side, r, df))
        for touch_ts, side, status in recovered:
            rec_list.append((symbol, touch_ts, side, status))
    if recover:
        _state["recovered"] = True
        back = []
        for symbol, touch_ts, side, status in rec_list:
            if (symbol, touch_ts) in _active or counts[(touch_ts, side)] >= ls.CLUSTER_MAX:
                continue
            _active[(symbol, touch_ts)] = {"side": side, "status": status}
            back.append(f"{'🟢' if side == 'LONG' else '🔴'} {html.escape(symbol)} (temas {ls.fmt(touch_ts)}, "
                        f"{'işlemde' if status == 'open' else 'giriş bekleniyor'})")
        if back:
            send_message(f"♻️ {TF_MIN}dk bildirimleri takibe geri alındı:\n" + "\n".join(back))

    sent = cluster = 0
    for symbol, side, r, df in candidates:
        touch_ts = int(df["timestamp"].values[r["touch"]])
        if (symbol, touch_ts) in _active:
            continue
        if counts[(touch_ts, side)] >= ls.CLUSTER_MAX:
            cluster += 1
            continue
        send_setup(symbol, side, r, df)
        _active[(symbol, touch_ts)] = {"side": side, "status": "pending"}
        sent += 1
    _stats.update(cycles=_stats["cycles"] + 1, last_run=time.time(), scanned=len(todo),
                  ok=sum(1 for x in results if x[1] is not None), touches=sum(counts.values()),
                  ready=len(candidates), cluster=cluster, sent=sent, total_sent=_stats["total_sent"] + sent,
                  secs=time.time() - t0)
    if sent:
        _stats["last_sent"] = time.time()
    log.info("%s bildirim taraması: %d/%d coin, %d temas, %d aday, %d bildirim, %d takipte, %.0f sn "
             "(mumlar: WebSocket %d, REST %d, tam %d)", TF, _stats["ok"], len(todo), _stats["touches"],
             len(candidates), sent, len(_active), _stats["secs"], _stats["ws"], _stats["rest"], _stats["full"])


def maybe_run():
    """Her 30dk mum kapanışından sonra bir kez (15dk taraması aynı iş parçacığında önce biter)."""
    if not ENABLED:
        return
    now = time.time()
    bucket = int(now // TF_SEC)
    sec = now - bucket * TF_SEC
    if sec < 10 or sec > 600 or bucket == _state["last_bucket"]:
        return
    _state["last_bucket"] = bucket
    try:
        run_cycle()
    except Exception as e:
        log.exception("%s bildirim taraması hatası: %s", TF, e)
        _stats["last_error"] = f"{ls.fmt(time.time() * 1000, '%H:%M')} {type(e).__name__}: {e}"[:200]


def status_text():
    if not ENABLED:
        return f"🔔 {TF_MIN}dk bildirim: KAPALI (/otuz aç)"
    if _stats["last_run"] is None:
        return f"🔔 {TF_MIN}dk bildirim (otomatik işlem yok): ilk tarama bir sonraki {TF_MIN}dk kapanışında"
    hhmm = lambda t: pd.Timestamp(t, unit="s", tz="UTC").tz_convert(ls.TZ).strftime("%H:%M")
    s = (f"🔔 <b>{TF_MIN}dk bildirim</b> (otomatik işlem yok): son tarama {hhmm(_stats['last_run'])}, "
         f"{_stats['ok']}/{_stats['scanned']} coin, {_stats['touches']} temas, {_stats['ready']} aday, {_stats['sent']} bildirim "
         f"({_stats['secs']:.0f} sn) · açıldığından beri {_stats['total_sent']} bildirim · takipte {len(_active)}")
    if _feed is not None:
        s += f"\n   📡 {TF} WebSocket: {_feed.status()}"
    if _stats["last_error"]:
        s += f"\n   ⚠️ {html.escape(_stats['last_error'])}"
    return s
