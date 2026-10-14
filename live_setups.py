"""
CANLI SETUP BİLDİRİMLERİ

Her mum kapanışında (LIVE_TF, varsayılan 15m) hacmi en yüksek coinleri tarar. Bütün kuralları
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

import config
import strategy as st
import trade_rules as tr
import exchanges
from exchanges import KLINE_LIMIT as KLINE_KEEP, get_klines, get_tick_sizes, get_top_symbols
import journal
from telegram import decision_buttons, send_message, send_photo

log = logging.getLogger("bot")

UNIVERSE = 500          # hacme göre ilk kaç coin taransın
CLUSTER_MAX = 5         # aynı mumda bu kadar coin aynı yönde temas verirse girme (toplu hareket)
MAX_OPEN = 2            # aynı anda en fazla bu kadar işlem (giriş bekleyen + açık); doluysa yeni EMİR HAZIR gönderilmez
SCAN_THREADS = 6
RECOVER_BARS = 60   # yeniden başlarken son 60 mumdaki (5m'de 5 saat) bildirilmiş setup'lar takibe geri alınır
LIVE_TF = config.LIVE_TF                 # canlı tarama zaman dilimi (varsayılan 15m)
TF_MIN = config.tf_minutes(LIVE_TF)
TF_SEC = TF_MIN * 60
TZ = "Europe/Istanbul"
CHART_DIR = "/tmp/live_charts"

# 14.10'daki canlı ayar (backtest karşılaştırma setleri bunun üzerine kurulu, değişmesin)
LIVE_RULES_14_10 = dict(
    RR=2.2,                     # komisyon sonrası kazanç ~2R olsun diye 1:2.2
    BE_TRIGGER=0.0, FILTERS=False, MIN_ATR_MULT=0.0,
    WICK_MAX_BODY=1.0,          # 1: onay mumunda uzun ters iğne yok
    REQUIRE_PRIOR_TOUCH=True,   # 2: trend teyidi
    STOP_BUFFER_ATR=0.3,        # 3: stop payı
    CLEAN_PIVOT_MAX=3, CLEAN_PIVOT_ATR=0.3,  # 4: temiz tepe/dip
    TOUCH_WICK_MIN=1.0,         # 5: fitil temas mumu
    PIVOT_WICK_MAX=2.0,         # 6: tepe/dip iğnesi uzun değil
    QUIET_UTC=(0, 4),           # 03:00-07:00 TR arası temaslar dikkate alınmaz
    ENTRY_MODE="both",          # klasik + dönüş varyasyonu birlikte (14.10): temas mumu EMA20'nin öbür tarafında
                                # kapatırsa dönüş (sonraki mum geri alır, ondan sonraki onay), doğru tarafında kapatırsa klasik
)
# 15.10 02:44 kullanıcı: "hangisi daha iyiyse onu yükle". 15m 12 ay (iki dönem): onay ≤ 2. mum + stop ≥ %0.5 +
# önünde en az 1R yer + erken çıkış (2 mum) → +48.6R (kaymayla +36.2), en kötü ay -3.3R, ~31 işlem/ay.
# 5m'nin en iyisi 3 ayda kaymayla +4.2R (ayda 1.4R) → canlı 15m.
LIVE_RULES = dict(
    LIVE_RULES_14_10,
    CONFIRM_WINDOW=2,           # onay temastan sonra en geç 2. mumda (dönüşte zaten 2. mum)
    BASE_MIN_RISK_PCT=0.5,      # stop en az %0.5 (daha darında komisyon + kayma R'nin büyük kısmını yiyor)
    ROOM_MIN_R=1.0,             # giriş ile önceki tepe (LONG) / dip (SHORT) arası en az 1R ("tepenin hizasından girme")
    FAILED_ENTRY_BARS=2,        # erken çıkış: giriş mumu ya da sonraki mum girişin gerisinde kapatırsa "ERKEN ÇIK" bildirimi
)
MODE_TR = {"classic": "klasik", "reclaim": "dönüş"}

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
        f"aynı anda en fazla {MAX_OPEN} işlem" if MAX_OPEN else None,
        (f"{tr.QUIET_UTC[0] + 3:02d}-{tr.QUIET_UTC[1] + 3:02d} TR yok"
         if tr.QUIET_UTC[0] < tr.QUIET_UTC[1] else None),
        f"onay en geç {tr.CONFIRM_WINDOW}. mumda" if tr.CONFIRM_WINDOW < 3 else None,
        f"stop ≥ %{tr.BASE_MIN_RISK_PCT:g}" if not tr.FILTERS and tr.BASE_MIN_RISK_PCT > 0.3 else None,
        f"önünde ≥ {tr.ROOM_MIN_R:g}R yer" if tr.ROOM_MIN_R > 0 else None,
        (f"erken çıkış uyarısı (giriş mumu / sonraki mum girişin gerisinde kapatırsa)"
         if tr.FAILED_ENTRY_BARS == 2 else (f"erken çıkış uyarısı ({tr.FAILED_ENTRY_BARS} mum)" if tr.FAILED_ENTRY_BARS else None)),
        "⚠️ ESKİ FİLTRELER AÇIK" if tr.FILTERS else None,
        "klasik + dönüş varyasyonu" if tr.ENTRY_MODE == "both" else ("dönüş varyasyonu" if tr.ENTRY_MODE == "reclaim" else None),
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
            syms = get_top_symbols(UNIVERSE, max_wait=120)
            ticks = get_tick_sizes(max_wait=120)
            if syms:
                _state.update(symbols=syms, ticks=ticks, symbols_time=time.time())
                try:  # backtest Binance engelliyken bu listeyi kullanır
                    import json
                    with open(os.path.join(config.data_dir(), "universe.json"), "w") as f:
                        json.dump({"t": time.time(), "symbols": syms, "ticks": ticks}, f)
                except OSError:
                    pass
                for k in [k for k in _kcache if k not in set(syms)]:
                    _kcache.pop(k, None)
                log.info("Setup taraması: %d coin", len(syms))
        except Exception as e:
            log.error("Coin listesi alınamadı: %s", e)
    return _state["symbols"]


_kcache = {}          # coin -> son ~500 mum (açık mum dahil): her taramada sadece yeni mumlar çekilir
INCREMENTAL_LIMIT = 40   # 40 mum = Binance'te 1 ağırlık (499 mum = 2): taramanın yükü yarıya iner


def fetch_candles(symbol):
    """Son KLINE_LIMIT mum. Bellekte varsa sadece son 40 mum çekilip eklenir (açık mum her seferinde yenilenir)."""
    old = _kcache.get(symbol)
    step = TF_SEC * 1000
    if old is not None and len(old) and (time.time() * 1000 - int(old["timestamp"].iloc[-1])) < (INCREMENTAL_LIMIT - 5) * step:
        new = get_klines(symbol, LIVE_TF, limit=INCREMENTAL_LIMIT)
        if new is None:
            return None
        df = (pd.concat([old, new]).drop_duplicates("timestamp", keep="last")
              .sort_values("timestamp").tail(KLINE_KEEP).reset_index(drop=True))
    else:
        df = get_klines(symbol, LIVE_TF)
        if df is None:
            return None
    _kcache[symbol] = df
    return df


def closed_candles(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 250:
        return None
    df = df.iloc[:-1]  # son satır hâlâ açık olan mum
    return prepare(df)


def scan_symbol(symbol, keep_df=False, lookback=None):
    """Son mumlardaki temasları ve tamamlanan onayları bulur.
    Veri sadece onay adayı varsa ya da coin takipteyse geri döner (bellek).
    lookback verilirse (bot yeniden başladığında) son lookback mumdaki, daha önce bildirilmiş olması gereken
    ve hâlâ sürmekte olan (giriş bekleyen / işlemde) setup'lar da döner: (temas zamanı, yön, durum)."""
    df = closed_candles(symbol)
    if df is None:
        return symbol, None, [], [], []
    n = len(df)
    tick = _state["ticks"].get(symbol, 0.0)
    ts = df["timestamp"].values
    touches, ready, recovered = [], [], []
    arr = st.arrays(df)
    # Onay temastan sonraki 3 mum içinde gelir: son 4 mumdaki temaslara bak
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
        return symbol, False, touches, ready, recovered   # False = veri alındı ama saklanmadı
    return symbol, df, touches, ready, recovered


def setup_message(symbol, side, r, df):
    ts = df["timestamp"].values
    risk = abs(r["entry"] - r["stop"])
    qty = tr.RISK_USD / risk if risk else 0
    notional = qty * r["entry"]
    valid_until = int(ts[r["confirm"]]) + (tr.ENTRY_WINDOW + 1) * TF_SEC * 1000
    tv = f"https://www.tradingview.com/chart/?symbol=BINANCE:{symbol}.P&interval={TF_MIN}"
    emoji = "🟢" if side == "LONG" else "🔴"
    order = "BUY STOP" if side == "LONG" else "SELL STOP"
    mode = r.get("mode", "classic")
    steps = (f"Temas {fmt(ts[r['touch']])}, dönüş {fmt(ts[r['reclaim']])}, onay {fmt(ts[r['confirm']])}"
             if "reclaim" in r else f"Temas {fmt(ts[r['touch']])}, onay {fmt(ts[r['confirm']])}")
    return (
        f"📋 <b>EMİR HAZIR</b>  {emoji} <b>{side} {html.escape(symbol)}</b> ({LIVE_TF}, {MODE_TR.get(mode, mode)})\n\n"
        f"Giriş ({order}): <code>{p(r['entry'])}</code>\n"
        f"Stop: <code>{p(r['stop'])}</code>  (%{100 * risk / r['entry']:.2f})\n"
        f"TP (1:{tr.RR:g}): <code>{p(r['tp'])}</code>\n"
        f"{tr.RISK_USD:g}$ risk için: ~{notional:,.0f} USDT pozisyon ({qty:.6g} adet)\n\n"
        f"{steps}\n"
        f"Emir {fmt(valid_until, '%H:%M')}'e kadar geçerli. Girişten önce fiyat onay mumunun "
        f"{'dibini' if side == 'LONG' else 'tepesini'} kırarsa iptal.\n"
        + (f"Giriş mumu ya da sonraki mum girişin {'altında' if side == 'LONG' else 'üstünde'} kapatırsa "
           f"⚠️ ERKEN ÇIK mesajı gelir: o an piyasa emriyle kapat.\n" if tr.FAILED_ENTRY_BARS else "") +
        f'<a href="{tv}">TradingView\'da aç</a>'
    )


def send_setup(symbol, side, r, df):
    caption = setup_message(symbol, side, r, df)
    touch_ts = int(df["timestamp"].values[r["touch"]])
    try:
        journal.record_alert(symbol, touch_ts, side, float(r["entry"]), float(r["stop"]), float(r["tp"]),
                             mode=r.get("mode"))
    except Exception as e:
        log.error("Günlüğe yazılamadı: %s", e)
    buttons = decision_buttons(journal.key_of(symbol, touch_ts))
    try:
        import charts  # matplotlib sadece bildirim çizerken yüklenir (bellek)
        os.makedirs(CHART_DIR, exist_ok=True)
        ts = df["timestamp"].values
        trade = {
            "_ctx": charts.context(df, r), "coin": symbol, "zaman_dilimi": LIVE_TF, "yon": side,
            "durum": "pending", "giris": r["entry"], "stop": r["stop"], "tp": r["tp"],
            "varyasyon": MODE_TR.get(r.get("mode", "classic")),
            "temas": fmt(ts[r["touch"]], "%d.%m.%Y %H:%M"),
            "temas_utc": pd.Timestamp(int(ts[r["touch"]]), unit="ms", tz="UTC").strftime("%H:%M"),
        }
        path = f"{CHART_DIR}/{symbol}_{int(ts[r['touch']])}.png"
        charts.draw(trade, path=path)
        sent = send_photo(path, caption, buttons)
        try:
            os.remove(path)
        except OSError:
            pass
        if sent:
            return
    except Exception as e:
        log.error("%s grafik çizilemedi: %s", symbol, e)
    send_message(caption, buttons)


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
        if status == "be" and r.get("early_exit"):
            under = "altında" if info["side"] == "LONG" else "üstünde"
            lines.append(f"⚠️ <b>ERKEN ÇIK</b>: {fmt(ts[r['exit_bar']])} mumu girişin {under} kapattı ({p(r['exit'])}), "
                         f"kırılım tutmadı. Pozisyonu şimdi piyasa emriyle kapat.\n"
                         f"Bu kapanıştan çıkışla: <b>{r['r_net']:+.2f}R ({r['r_net'] * tr.RISK_USD:+.0f}$)</b>")
        elif status in STATUS_MSG and status != "open":
            line = STATUS_MSG[status]
            if status in ("win", "loss", "be"):
                line += f": {p(r['exit'])}  →  <b>{r['r_net']:+.2f}R ({r['r_net'] * tr.RISK_USD:+.0f}$)</b>"
            lines.append(line)
        if lines:
            emoji = "🟢" if info["side"] == "LONG" else "🔴"
            send_message(f"{emoji} <b>{info['side']} {html.escape(symbol)}</b> (temas {fmt(key[1])})\n" + "\n".join(lines))
        info["status"] = status
        try:
            journal.set_result(symbol, key[1], status, r.get("r_net") if status in ("win", "loss", "be") else None)
        except Exception as e:
            log.error("Günlüğe yazılamadı: %s", e)
        if status in FINAL:
            _active.pop(key)


def run_cycle():
    apply_rules()
    wait = exchanges.blocked_for()
    if wait > 120:
        # Binance IP'yi engellemiş: istek atmak engeli uzatır, bu tarama atlanır
        _stats["last_error"] = (f"{time.strftime('%H:%M')} Binance engeli: tarama atlandı "
                                f"(~{wait / 60:.0f} dk daha)")
        log.warning("Binance engeli sürüyor (%d sn), tarama atlandı", wait)
        return
    if not _state.get("probed"):
        _state["probed"] = True
        exchanges.probe_weight()
        if exchanges.blocked_for() > 120:
            _stats["last_error"] = f"{time.strftime('%H:%M')} Binance engeli: tarama atlandı"
            return
    symbols = refresh_universe()
    if not symbols:
        return
    t0 = time.time()
    watch = {k[0] for k in _active}
    todo = list(dict.fromkeys(list(symbols) + sorted(watch)))
    # Bot yeniden başladıysa ilk taramada son saatlerdeki bildirilmiş setup'lar takibe geri alınır
    recover = None if _state.get("recovered") else RECOVER_BARS
    with ThreadPoolExecutor(max_workers=SCAN_THREADS) as ex:
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
            if (symbol, touch_ts) in _active or counts[(touch_ts, side)] >= CLUSTER_MAX:
                continue  # toplu sinyalde zaten bildirilmemişti
            _active[(symbol, touch_ts)] = {"side": side, "status": status}
            back.append(f"{'🟢' if side == 'LONG' else '🔴'} {html.escape(symbol)} (temas {fmt(touch_ts)}, "
                        f"{'işlemde' if status == 'open' else 'giriş bekleniyor'})")
        if back:
            log.info("Yeniden başlatma: %d setup takibe geri alındı", len(back))
            send_message("♻️ Bot yeniden başladı, önceki bildirimler takibe geri alındı "
                         "(giriş / TP / stop mesajları gelmeye devam edecek):\n" + "\n".join(back))

    sent = 0
    cluster_skipped = 0
    busy = sum(1 for v in _active.values() if v["status"] in ("pending", "open"))
    limit_skipped = []
    for symbol, side, r, df in candidates:
        touch_ts = int(df["timestamp"].values[r["touch"]])
        if (symbol, touch_ts) in _active:
            continue
        if counts[(touch_ts, side)] >= CLUSTER_MAX:
            log.info("Toplu sinyal, atlandı: %s %s (%d coin)", symbol, side, counts[(touch_ts, side)])
            cluster_skipped += 1
            continue
        if MAX_OPEN and busy >= MAX_OPEN:
            log.info("Açık işlem sınırı (%d), atlandı: %s %s", MAX_OPEN, symbol, side)
            limit_skipped.append(f"{symbol} {side}")
            continue
        send_setup(symbol, side, r, df)
        _active[(symbol, touch_ts)] = {"side": side, "status": "pending"}
        sent += 1
        busy += 1
    if limit_skipped:
        send_message(f"⏸ Zaten {MAX_OPEN} işlem açık/giriş bekliyor, yeni setup bildirilmedi: "
                     + ", ".join(html.escape(x) for x in limit_skipped))
    ok = sum(1 for r in results if r[1] is not None)
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
        nxt = (int(time.time() // TF_SEC) + 1) * TF_SEC + 10
        return (f"📋 Canlı tarama ({LIVE_TF}): ilk tarama {hhmm(nxt)}'de yapılacak (her {TF_MIN} dk'lık mum kapanışında)."
                + running)
    up_h = (time.time() - _stats["started"]) / 3600
    lines = [
        f"📋 <b>Canlı tarama {LIVE_TF}</b> (bot {up_h:.1f} saattir açık, {_stats['cycles']} tarama)",
        f"Son tarama {hhmm(_stats['last_run'])}: {_stats['ok']}/{_stats['scanned']} coin, "
        f"{_stats['touches']} temas, {_stats['ready']} onay adayı, {_stats['sent']} bildirim ({_stats['secs']:.0f} sn)",
        f"Açıldığından beri gönderilen EMİR HAZIR: {_stats['total_sent']}"
        + (f" (son: {hhmm(_stats['last_sent'])})" if _stats["last_sent"] else ""),
        f"Takipteki setup: {len(_active)} (en fazla {MAX_OPEN})",
    ]
    if running:
        lines.append(running.strip())
    if _stats["last_error"]:
        lines.append(f"⚠️ Son hata: {_stats['last_error']}")
    return "\n".join(lines)


def _safe_scan(symbol, keep_df=False, lookback=None):
    try:
        return scan_symbol(symbol, keep_df, lookback)
    except Exception as e:
        log.debug("%s taranamadı: %s", symbol, e)
        return symbol, None, [], [], []


def maybe_run():
    """Her mum (LIVE_TF) kapandıktan ~10 sn sonra bir kez çalışır.
    Sadece kapanıştan sonraki ilk 60 sn içinde başlar (backtest o sırada Binance'e yol verir);
    bot çeyreğin ortasında açılırsa ilk tarama bir sonraki kapanışta yapılır."""
    now = time.time()
    bucket = int(now // TF_SEC)
    sec = now - bucket * TF_SEC
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
