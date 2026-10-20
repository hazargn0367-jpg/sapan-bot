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
CLUSTER_MAX = 10        # aynı mumda bu kadar coin aynı yönde temas verirse girme (toplu hareket); 20.10 18:06: 5 → 10 (7 dönemde 6/7 iyi, +37R)
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
    # EMA_FAN_MIN=2.0 denendi (15.10): 5m Tem-Eki +20.3R ama Nis-Tem -23.3R → tutmadı; 15m'de de karışık. Kullanılmıyor.
    QUIET_UTC=(0, 0),           # 03-07 TR saat filtresi kaldırıldı (kullanıcı 15.10 04:14 "yarın kaldırırsın"): kaldırınca
                                # eklenen işlemler Nis-Eki +7.2R (38 işlem, TP %32), Eki-Nis -1.2R (38 işlem) → 12 ayda +6R
    # Grafik örneklerinden (RESOLV, NIL; kullanıcı 15.10). 3 dönem (Nis-Eki 26 / Eki-Nis / Nis-Eki 25), canlı +22.5 / +27.5 /
    # -19.0 → ikisi birden +27.1 / +32.3 / -1.5 (18 ay +31.0 → +57.9R, işlem ~%30 az). Ayrı ayrı da 3 dönemde iyi.
    WICKY_MAX=0.58,             # temastan önceki 12 mumda iğne oranı > %58 ise girme (git-gel yapan piyasa)
    PIVOT_BAND2_ATR=1.0, PIVOT_BAND2_MAX=5,   # dip/tepenin 1 ATR yakınında ≥5 mum varsa girme (dipte/tepede taban)
    # Kullanıcı 15.10 (ETHFI örneği): derin geri kapanışta erken çıkma. 3 dönem: +26.8 / +32.3 / -1.6 → +36.2 / +39.1 / +12.0
    # (18 ay +57.5 → +87.3R; 0.5 ATR eşiği de 3'ünde iyi: +81.2)
    EARLY_EXIT_MAX_ATR=0.35,    # mum dolumun 0.35 ATR'den derin gerisinde kapatırsa erken çıkış yok, stop / TP beklenir
    # Kullanıcı 15.10 (CARV örneği): kural 2'deki önceki temas, fiyat EMA20'den 1.5 ATR ayrıldıktan sonra olmalı.
    # 3 dönem: +36.5 / +37.0 / +13.0 → +45.1 / +41.0 / +17.2 (18 ay +86.4 → +103.4R, düşüş 17.7 → 11.7R, işlem ~%28 az)
    PRIOR_TOUCH_SEP_ATR=1.5,
    # Kullanıcı 16.10 12:40 "mantıklıysa yükle". 5 dönem (Nis 24-Eki 26): ikisi birlikte 31 iş elenir, -14.4R, 5/5 dönem
    # eksi (-1.8 / -5.3 / -3.7 / -2.5 / -1.0); TP %31.6 → %33.8, ayda ~1 işlem az, ~+0.5R/ay.
    BODY_AVG_MAX_ATR=0.8,       # temastan önceki 12 mumun ortalama gövdesi ≥ 0.8 ATR ise girme (sert sallanma)
    CORR_BARS_MAX=10,           # tepeden temasa ≥ 10 mum (yavaş, uzun düzeltme) ise girme (SUI 27.09 örneği)
)
MODE_TR = {"classic": "klasik", "reclaim": "dönüş"}
# Bildirimlerde 1R kaç dolar (kullanıcı 15.10: "1R'ım 1 dolar olacak"). Backtest raporları 25$ ile kalır.
ALERT_RISK_USD = float(os.environ.get("ALERT_RISK_USD", os.environ.get("AUTO_RISK_USD", "15")))  # 15.10 14:24: 15$ · 20.10 11:43: 20$ · 20.10 18:06: 15$

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
        (("trend teyidi" + (f" (EMA20'den {tr.PRIOR_TOUCH_SEP_ATR:g} ATR ayrıldıktan sonra)" if tr.PRIOR_TOUCH_SEP_ATR > 0 else ""))
         if tr.REQUIRE_PRIOR_TOUCH else None),
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
        f"EMA20-EMA100 ≥ {tr.EMA_FAN_MIN:g} ATR" if tr.EMA_FAN_MIN > 0 else None,
        f"iğneli git-gel yok (iğne ≤ %{100 * tr.WICKY_MAX:.0f})" if tr.WICKY_MAX > 0 else None,
        f"sert sallanma yok (12 mum ort. gövde < {tr.BODY_AVG_MAX_ATR:g} ATR)" if tr.BODY_AVG_MAX_ATR > 0 else None,
        f"düzeltme {tr.CORR_BARS_MAX} mumdan kısa" if tr.CORR_BARS_MAX > 0 else None,
        (f"dip/tepe tabanı yok ({tr.PIVOT_BAND2_ATR:g} ATR bantta ≤ {tr.PIVOT_BAND2_MAX - 1} mum)"
         if tr.PIVOT_BAND2_ATR > 0 else None),
        (f"erken çıkış uyarısı (giriş mumu / sonraki mum girişin gerisinde kapatırsa)"
         if tr.FAILED_ENTRY_BARS == 2 else (f"erken çıkış uyarısı ({tr.FAILED_ENTRY_BARS} mum)" if tr.FAILED_ENTRY_BARS else None)),
        (f"derin geri kapanışta (> {tr.EARLY_EXIT_MAX_ATR:g} ATR) erken çıkış yok, stop beklenir"
         if tr.FAILED_ENTRY_BARS and tr.EARLY_EXIT_MAX_ATR > 0 else None),
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
                f = feed()
                if f is not None:
                    f.set_symbols(syms)
                log.info("Setup taraması: %d coin", len(syms))
        except Exception as e:
            log.error("Coin listesi alınamadı: %s", e)
    return _state["symbols"]


_kcache = {}          # coin -> son ~500 KAPANMIŞ mum: her taramada sadece yeni mumlar eklenir
INCREMENTAL_LIMIT = 40   # 40 mum = Binance'te 1 ağırlık (499 mum = 2): taramanın yükü yarıya iner
USE_WS = os.environ.get("LIVE_WS", "1") != "0"   # 20.10 22:17: kapanmış mumlar WebSocket'ten (REST ağırlığı yok); LIVE_WS=0 kapatır
_feed = None
_ws_stats = {"ws": 0, "rest": 0, "full": 0, "check_ok": 0, "check_bad": 0, "check_last": ""}


def feed():
    """WebSocket mum akışı (ilk çağrıda kurulur)."""
    global _feed
    if not USE_WS:
        return None
    if _feed is None:
        import ws_klines
        _feed = ws_klines.KlineFeed(LIVE_TF)
    return _feed


def _closed_only(df, want_last):
    return df[df["timestamp"] <= want_last].reset_index(drop=True) if df is not None else None


def fetch_candles(symbol):
    """Son KLINE_KEEP KAPANMIŞ mum. Bellekte varsa eksik mumlar önce WebSocket akışından eklenir (istek yok);
    akışta eksik / boşluk varsa son 40 mum REST'ten (1 ağırlık), bellekte yoksa ya da çok eskiyse tamamı REST'ten."""
    old = _kcache.get(symbol)
    step = TF_SEC * 1000
    want_last = (int(time.time() * 1000) // step - 1) * step   # son kapanmış mumun açılış zamanı
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
                _ws_stats["ws"] += 1
                return df
        if _state.get("ws_only"):
            return None   # REST engeli: akışta olmayan coin bu taramada atlanır
        if want_last - last < (INCREMENTAL_LIMIT - 5) * step:
            new = _closed_only(get_klines(symbol, LIVE_TF, limit=INCREMENTAL_LIMIT), want_last)
            if new is None:
                return None
            df = (pd.concat([old, new]).drop_duplicates("timestamp", keep="last")
                  .sort_values("timestamp").tail(KLINE_KEEP).reset_index(drop=True))
            _kcache[symbol] = df
            _ws_stats["rest"] += 1
            return df
    if _state.get("ws_only"):
        return None
    df = _closed_only(get_klines(symbol, LIVE_TF), want_last)
    if df is None:
        return None
    _kcache[symbol] = df
    _ws_stats["full"] += 1
    return df


def _ws_check(symbols):
    """Her taramada rastgele bir coinin WebSocket'ten gelen son mumu REST ile karşılaştırılır (1 ağırlık)."""
    import random
    f = feed()
    if f is None or not symbols:
        return
    step = TF_SEC * 1000
    want_last = (int(time.time() * 1000) // step - 1) * step
    sym = random.choice(list(symbols))
    rows = [r for r in f.closed_after(sym, want_last - step) if r[0] == want_last]
    if not rows:
        return
    rest = get_klines(sym, LIVE_TF, limit=3)
    if rest is None:
        return
    m = rest[rest["timestamp"] == want_last]
    if m.empty:
        return
    a = rows[0][1:]
    b = tuple(float(m[c].iloc[0]) for c in ("Open", "High", "Low", "Close"))
    ok = all(abs(x - y) <= 1e-9 * max(1.0, abs(y)) for x, y in zip(a, b))
    _ws_stats["check_ok" if ok else "check_bad"] += 1
    if not ok:
        _ws_stats["check_last"] = f"{sym} {fmt(want_last)} WS {a} / REST {b}"
        log.warning("WebSocket mumu REST ile uyuşmuyor: %s", _ws_stats["check_last"])


def closed_candles(symbol):
    df = fetch_candles(symbol)
    if df is None or len(df) < 250:
        return None
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
    try:   # otomatik işlemdeki risk çarpanı (son 24 saatte kapanan işlemler): bildirimde de aynı risk gösterilir
        import autotrade
        m, mtot, mn = autotrade.risk_mult()
        mnote = f" ({autotrade.mult_text(m, mtot, mn)})"
    except Exception:
        m, mnote = 1.0, ""
    risk_usd = ALERT_RISK_USD * m
    qty = risk_usd / risk if risk else 0
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
        f"{risk_usd:g}$ risk için{mnote}: ~{notional:,.0f} USDT pozisyon ({qty:.6g} adet)\n\n"
        f"{steps}\n"
        f"Emir {fmt(valid_until, '%H:%M')}'e kadar geçerli. Girişten önce fiyat onay mumunun "
        f"{'dibini' if side == 'LONG' else 'tepesini'} kırarsa iptal.\n"
        + (f"Giriş mumu ya da sonraki mum girişin {'altında' if side == 'LONG' else 'üstünde'} kapatırsa "
           f"⚠️ ERKEN ÇIK mesajı gelir: o an piyasa emriyle kapat"
           + (f"; ama kapanış {p(r['entry'] - tr.EARLY_EXIT_MAX_ATR * r['atr'] if side == 'LONG' else r['entry'] + tr.EARLY_EXIT_MAX_ATR * r['atr'])}"
              f" seviyesinin {'altındaysa' if side == 'LONG' else 'üstündeyse'} çıkılmaz, stop / TP beklenir"
              if tr.EARLY_EXIT_MAX_ATR > 0 and r.get("atr") else "")
           + ".\n" if tr.FAILED_ENTRY_BARS else "") +
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
            try:
                import autotrade
                auto = autotrade.managed(symbol, key[1])
            except Exception:
                auto = False
            todo = "Otomatik işlem pozisyonu kapatıyor." if auto else "Pozisyonu şimdi piyasa emriyle kapat."
            lines.append(f"⚠️ <b>ERKEN ÇIK</b>: {fmt(ts[r['exit_bar']])} mumu girişin {under} kapattı ({p(r['exit'])}), "
                         f"kırılım tutmadı. {todo}\n"
                         f"Bu kapanıştan çıkışla: <b>{r['r_net']:+.2f}R ({r['r_net'] * ALERT_RISK_USD:+.2f}$)</b>")
        elif status in STATUS_MSG and status != "open":
            line = STATUS_MSG[status]
            if status in ("win", "loss", "be"):
                line += f": {p(r['exit'])}  →  <b>{r['r_net']:+.2f}R ({r['r_net'] * ALERT_RISK_USD:+.2f}$)</b>"
            lines.append(line)
        if lines:
            emoji = "🟢" if info["side"] == "LONG" else "🔴"
            send_message(f"{emoji} <b>{info['side']} {html.escape(symbol)}</b> (temas {fmt(key[1])})\n" + "\n".join(lines))
        info["status"] = status
        try:
            import autotrade
            autotrade.on_signal(symbol, key[1], status, r)
        except Exception as e:
            log.exception("Otomatik işlem hatası: %s", e)
        try:
            journal.set_result(symbol, key[1], status, r.get("r_net") if status in ("win", "loss", "be") else None)
        except Exception as e:
            log.error("Günlüğe yazılamadı: %s", e)
        if status in FINAL:
            _active.pop(key)


def run_cycle():
    apply_rules()
    wait = exchanges.blocked_for()
    _state["ws_only"] = False
    if wait > 120:
        f = _feed
        if f is not None and f.healthy() and _state["symbols"]:
            # Binance REST engeli sürerken WebSocket akışı çalışıyor: tarama REST'siz (sadece akıştaki mumlarla) yapılır.
            # Otomatik işlem emirleri REST ister, engel kalkana kadar konamayabilir; bildirim yine gider.
            _state["ws_only"] = True
            _stats["last_error"] = (f"{fmt(time.time() * 1000, '%H:%M')} Binance REST engeli (~{wait / 60:.0f} dk): tarama "
                                    f"sadece WebSocket verisiyle yapıldı")
            log.warning("Binance engeli sürüyor (%d sn), tarama sadece WebSocket verisiyle", wait)
        else:
            # Binance IP'yi engellemiş: istek atmak engeli uzatır, bu tarama atlanır
            _stats["last_error"] = (f"{fmt(time.time() * 1000, '%H:%M')} Binance engeli: tarama atlandı "
                                    f"(~{wait / 60:.0f} dk daha)")
            log.warning("Binance engeli sürüyor (%d sn), tarama atlandı", wait)
            return
    if not _state.get("probed") and not _state["ws_only"]:
        _state["probed"] = True
        exchanges.probe_weight()
        if exchanges.blocked_for() > 120:
            _stats["last_error"] = f"{fmt(time.time() * 1000, '%H:%M')} Binance engeli: tarama atlandı"
            return
    symbols = _state["symbols"] if _state["ws_only"] else refresh_universe()
    if not symbols:
        return
    t0 = time.time()
    for k in ("ws", "rest", "full"):
        _ws_stats[k] = 0
    f = feed()
    if f is not None:
        f.set_symbols(symbols)   # akış kopmuş / hiç kurulmamışsa (coin listesi aynı kalsa da) ilk taramada kurulur
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
        try:
            import autotrade
            autotrade.on_setup(symbol, side, r["entry"], r["stop"], r["tp"], touch_ts, LIVE_TF)
        except Exception as e:
            log.exception("Otomatik işlem hatası: %s", e)
        sent += 1
        busy += 1
    if limit_skipped:
        send_message(f"⏸ Zaten {MAX_OPEN} işlem açık/giriş bekliyor, yeni setup bildirilmedi: "
                     + ", ".join(html.escape(x) for x in limit_skipped))
    ok = sum(1 for r in results if r[1] is not None)
    try:
        if not _state.get("ws_only"):
            _ws_check(symbols)
    except Exception as e:
        log.debug("WebSocket kontrolü yapılamadı: %s", e)
    _stats.update(cycles=_stats["cycles"] + 1, last_run=time.time(), scanned=len(todo), ok=ok,
                  touches=sum(counts.values()), ready=len(candidates), cluster=cluster_skipped,
                  sent=sent, secs=time.time() - t0, total_sent=_stats["total_sent"] + sent)
    if sent:
        _stats["last_sent"] = time.time()
    log.info("Setup taraması bitti: %d/%d coin, %d temas, %d aday, %d yeni emir, %d takipte, %.0f sn "
             "(mumlar: WebSocket %d, REST %d, tam %d)",
             ok, len(todo), sum(counts.values()), len(candidates), sent, len(_active), time.time() - t0,
             _ws_stats["ws"], _ws_stats["rest"], _ws_stats["full"])


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
    f = _feed
    if f is not None:
        lines.append(f"📡 WebSocket: {f.status()} · son tarama mumları WS {_ws_stats['ws']} / REST {_ws_stats['rest']}"
                     f" / tam {_ws_stats['full']} · REST kontrolü {_ws_stats['check_ok']} uyumlu"
                     + (f", {_ws_stats['check_bad']} UYUMSUZ ({html.escape(_ws_stats['check_last'])})" if _ws_stats["check_bad"] else ""))
        if f.last_error:
            lines.append(f"   son WebSocket hatası: {html.escape(f.last_error)}")
    elif not USE_WS:
        lines.append("📡 WebSocket kapalı (LIVE_WS=0), mumlar REST'ten")
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
        _stats["last_error"] = f"{fmt(time.time() * 1000, '%H:%M')} {type(e).__name__}: {e}"[:200]
    finally:
        _stats["running_since"] = None
