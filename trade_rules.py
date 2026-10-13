"""
İŞLEM KURALLARI (temas uyarısından sonrası)

LONG (SHORT tam tersi):
 1. Temas mumu: strategy.py'deki tüm şartlar + EMA20'nin ÜSTÜNDE kapanış
 2. Onay: Sonraki 3 mum içinde, temas mumunun tepesinin üstünde kapatan ilk mum.
    O ana kadar (onay mumu dahil) hiçbir mum temas mumunun dibinin altına inmez.
 3. Giriş: onay mumunun tepesi + 1 tık   |   Stop: onay mumunun dibi - 1 tık
 4. ATR(14, RMA) filtresi: giriş-stop mesafesi <= 1.5 x ATR (onay mumundaki ATR)
    Giriş-stop mesafesi fiyatın %0.5'i ile %3'ü arasında olmalı (filtresiz: en az %0.3)
 4b. Temas mumu 00:00-08:00 UTC arasındaysa işlem yok (filtreli modda)
 5. Giriş emri onay mumundan sonraki 2 mum geçerli. Girişten önce fiyat onay
    mumunun dibinin altına inerse iptal.
 6. TP: riskin 2 katı (1:2)
 7. (İsteğe bağlı) Başabaş: +1R'ye gelince stop giriş seviyesine çekilir

Mum içinde hangi hareketin önce olduğu bilinmediği durumlarda TEMKİNLİ davranılır:
 - Aynı mum hem onay dibinin altına inip hem girişe değerse -> işlem yok
 - Aynı mum hem stopa hem TP'ye değerse -> stop sayılır
"""

import numpy as np
import pandas as pd

import strategy as st

# ---- Parametreler ----
CONFIRM_WINDOW = 3     # temastan sonra onay için beklenecek mum
ENTRY_WINDOW = 2       # onaydan sonra girişin gerçekleşmesi için beklenecek mum
ATR_PERIOD = 14
ATR_MAX_MULT = 1.5     # giriş-stop mesafesi en fazla bu kadar ATR
MIN_ATR_MULT = 0.0     # >0 ise giriş-stop mesafesi en az bu kadar ATR (örn. 0.875: ATR 40 -> en az 35)
BASE_MIN_RISK_PCT = 0.3  # filtresiz modda en dar stop (%)

# ---- Ek filtreler (30 günlük analizden; FILTERS=False ile kapatılır) ----
FILTERS = True
MIN_RISK_PCT = 0.5       # stop mesafesi en az %0.5 (daha darında komisyon riskin %15-22'si)
MAX_RISK_PCT = 3.0       # stop mesafesi en fazla %3 (daha genişi aşırı oynak/pump coinler)
SESSION_START_UTC = 8    # temas mumu 00:00-08:00 UTC (03:00-11:00 TR) arasındaysa işlem yok

# ---- Grafik incelemesinden gelen kurallar (varsayılan kapalı, backtest'te açılır) ----
WICK_MAX_BODY = 0.0          # >0: onay mumunun ters iğnesi (LONG'da üst) gövdenin bu katından uzunsa işlem yok
REQUIRE_PRIOR_TOUCH = False  # trend başladıktan sonra, tepeden önce en az bir EMA20 teması olmalı
STOP_BUFFER_ATR = 0.0        # stop onay mumunun ucundan bu kadar ATR daha uzağa konur
CLEAN_PIVOT_MAX = 0          # >0: son tepe/dip seviyesine bu kadar veya daha fazla mum dokunduysa (destek/direnç) işlem yok
CLEAN_PIVOT_ATR = 0.3        # "seviyeye dokundu" sayılma mesafesi (ATR)
CLEAN_PIVOT_BEFORE = 5       # tepeden/dipten kaç mum öncesinden itibaren sayılsın
TOUCH_WICK_MIN = 0.0         # >0: temas mumunun EMA20'ye doğru iğnesi en az gövdenin bu katı olmalı (fitil mum)
PIVOT_WICK_MAX = 0.0         # >0: tepe (LONG) / dip (SHORT) mumunun o yöndeki iğnesi gövdenin bu katından uzunsa işlem yok
QUIET_UTC = (0, 0)           # (başlangıç, bitiş) UTC saat: temas bu aralıktaysa işlem yok. (0, 4) = 03:00-07:00 TR
ROOM_MIN_R = 0.0             # >0: giriş ile önceki tepe (LONG) / dip (SHORT) arası en az bu kadar R olmalı (önünde yer)
STRUCTURE_BREAK = ""         # "wick" / "close": şu anki düzeltme önceki düzeltmenin dibini (LONG) / tepesini (SHORT) kırdıysa işlem yok
RR = 2.0               # hedef: riskin kaç katı
BE_TRIGGER = 0.0       # >0 ise: fiyat bu kadar R kâra gelince stop girişe çekilir (0 = kapalı)
RISK_USD = 25.0        # 1R = kaç dolar (işlem başı risk)
FEE_TAKER = 0.0005     # Binance vadeli piyasa emri komisyonu (%0.05)
FEE_MAKER = 0.0002     # Binance vadeli limit emri komisyonu (%0.02)


def add_atr(df):
    """TradingView'daki ATR 14 RMA ile aynı yöntem."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    return df


def prior_touch_ok(df, i, side):
    """Trend teyidi: trend başladıktan ve fiyat EMA20'den ayrıldıktan sonra,
    son tepeden (LONG) / dipten (SHORT) önce en az bir kez EMA20'ye temas edilmiş mi?"""
    long = side == "LONG"
    E20, E50, E100 = df["EMA20"].values, df["EMA50"].values, df["EMA100"].values
    H, L = df["High"].values, df["Low"].values

    def aligned(j):
        return (E20[j] > E50[j] > E100[j]) if long else (E20[j] < E50[j] < E100[j])

    # Trendin başladığı mum: dizilimin kesintisiz sürdüğü en eski mum
    s = i
    while s - 1 >= max(0, i - 600) and aligned(s - 1):
        s -= 1
    # Kalkış: fiyatın EMA20'den tamamen ayrıldığı ilk mum (kesişme anındaki temaslar sayılmaz)
    k = s
    while k < i and not ((L[k] > E20[k]) if long else (H[k] < E20[k])):
        k += 1
    # Son tepe/dip (strategy.py ile aynı tanım)
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    for m in range(k + 1, pivot):
        if (L[m] <= E20[m] * st.TOLERANCE_LONG) if long else (H[m] >= E20[m] * st.TOLERANCE_SHORT):
            return True
    return False


def pivot_touches(df, i, side):
    """Son tepeye (LONG) / dibe (SHORT) yakın uç veren mum sayısı.
    Çok mum aynı seviyeye dokunduysa orada direnç/destek oluşmuş demektir."""
    long = side == "LONG"
    H, L, A = df["High"].values, df["Low"].values, df["ATR"].values
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    tol = CLEAN_PIVOT_ATR * A[pivot]
    lo = max(0, pivot - CLEAN_PIVOT_BEFORE)
    if long:
        return int((H[lo:i] >= H[pivot] - tol).sum())
    return int((L[lo:i] <= L[pivot] + tol).sum())


def candle_parts(o, h, l, c):
    """(gövde, üst iğne, alt iğne)"""
    return abs(c - o), h - max(o, c), min(o, c) - l


def touch_is_wick_candle(df, i, side):
    """Kural 5: EMA20'ye iğneyle değen, gövdesi küçük temas mumu."""
    body, up, down = candle_parts(*df[["Open", "High", "Low", "Close"]].values[i])
    wick = down if side == "LONG" else up
    return wick >= TOUCH_WICK_MIN * body and wick > 0


def pivot_wick_ok(df, i, side):
    """Kural 6: son tepe (LONG) / dip (SHORT) mumunda o yöne çok uzun iğne olmamalı."""
    long = side == "LONG"
    H, L = df["High"].values, df["Low"].values
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    body, up, down = candle_parts(*df[["Open", "High", "Low", "Close"]].values[pivot])
    wick = up if long else down
    return wick <= PIVOT_WICK_MAX * body


def structure_ok(df, i, side, mode="wick"):
    """Kural 8: yükselen dip (LONG) / alçalan tepe (SHORT) yapısı bozulmamış olmalı.
    LONG: önceki tepe (q) ile son tepe (p) arasındaki düzeltmenin dibi = önceki dip.
    Son tepeden sonraki düzeltme (temasa kadar) bu dibin altına inmişse yapı bozulmuştur."""
    long = side == "LONG"
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    start = max(0, i - st.LOOKBACK)
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    past_end = p - st.PEAK_GAP
    if past_end <= start or p + 1 > i:
        return True
    if long:
        q = start + int(np.argmax(H[start:past_end]))
        prior = L[q:p].min()
        cur = (L if mode == "wick" else C)[p + 1:i + 1].min()
        return cur >= prior
    q = start + int(np.argmin(L[start:past_end]))
    prior = H[q:p].max()
    cur = (H if mode == "wick" else C)[p + 1:i + 1].max()
    return cur <= prior


def touch_closes_right_side(df, i, side):
    c = df.iloc[i]
    return c["Close"] > c["EMA20"] if side == "LONG" else c["Close"] < c["EMA20"]


def simulate(df, i, side, tick):
    """i: temas mumu. Sonucu sözlük olarak döner.
    status: session | quiet | no_close | touch_body | no_prior_touch | structure_break | dirty_pivot | pivot_wick | cancel_touch | no_confirm | wick | atr | atr_min |
            min_risk | max_risk | no_room | cancel_confirm |
            no_entry | win | loss | be | open | pending"""
    O = df["Open"].values
    H = df["High"].values
    L = df["Low"].values
    C = df["Close"].values
    A = df["ATR"].values
    n = len(df)
    long = side == "LONG"
    res = {"side": side, "touch": i}

    if FILTERS and "timestamp" in df.columns:
        hour_utc = (int(df["timestamp"].values[i]) // 3_600_000) % 24
        if hour_utc < SESSION_START_UTC:
            res["status"] = "session"
            return res

    if QUIET_UTC[0] < QUIET_UTC[1] and "timestamp" in df.columns:
        hour_utc = (int(df["timestamp"].values[i]) // 3_600_000) % 24
        if QUIET_UTC[0] <= hour_utc < QUIET_UTC[1]:
            res["status"] = "quiet"
            return res

    if not touch_closes_right_side(df, i, side):
        res["status"] = "no_close"
        return res

    if TOUCH_WICK_MIN > 0 and not touch_is_wick_candle(df, i, side):
        res["status"] = "touch_body"
        return res
    if REQUIRE_PRIOR_TOUCH and not prior_touch_ok(df, i, side):
        res["status"] = "no_prior_touch"
        return res
    if STRUCTURE_BREAK and not structure_ok(df, i, side, STRUCTURE_BREAK):
        res["status"] = "structure_break"
        return res
    if CLEAN_PIVOT_MAX > 0 and pivot_touches(df, i, side) >= CLEAN_PIVOT_MAX:
        res["status"] = "dirty_pivot"
        return res
    if PIVOT_WICK_MAX > 0 and not pivot_wick_ok(df, i, side):
        res["status"] = "pivot_wick"
        return res

    # --- Onay ---
    conf = None
    for j in range(i + 1, i + 1 + CONFIRM_WINDOW):
        if j >= n:
            res["status"] = "pending"
            return res
        if (L[j] < L[i]) if long else (H[j] > H[i]):
            res["status"] = "cancel_touch"
            return res
        if (C[j] > H[i]) if long else (C[j] < L[i]):
            conf = j
            break
    if conf is None:
        res["status"] = "no_confirm"
        return res

    if WICK_MAX_BODY > 0:
        body = abs(C[conf] - O[conf])
        wick = (H[conf] - max(O[conf], C[conf])) if long else (min(O[conf], C[conf]) - L[conf])
        if wick > WICK_MAX_BODY * body:
            res.update(confirm=conf, status="wick")
            return res

    buf = STOP_BUFFER_ATR * A[conf]
    if long:
        entry, stop = H[conf] + tick, L[conf] - tick - buf
    else:
        entry, stop = L[conf] - tick, H[conf] + tick + buf
    risk = abs(entry - stop)
    base_risk = risk - buf  # ATR sınırları stop payı eklenmeden önceki mesafeye uygulanır
    tp = entry + RR * risk if long else entry - RR * risk
    res.update(confirm=conf, entry=entry, stop=stop, tp=tp, risk=risk, atr=A[conf])

    if base_risk > ATR_MAX_MULT * A[conf]:
        res["status"] = "atr"
        return res
    if MIN_ATR_MULT > 0 and base_risk < MIN_ATR_MULT * A[conf]:
        res["status"] = "atr_min"
        return res
    risk_pct = 100 * risk / entry
    if risk_pct < (MIN_RISK_PCT if FILTERS else BASE_MIN_RISK_PCT):
        res["status"] = "min_risk"
        return res
    if FILTERS and risk_pct > MAX_RISK_PCT:
        res["status"] = "max_risk"
        return res
    if ROOM_MIN_R > 0:
        start = max(0, i - st.LOOKBACK)
        level = H[start:i].max() if long else L[start:i].min()   # önceki tepe / dip
        room = (level - entry) if long else (entry - level)
        res["room_r"] = room / risk
        # Giriş seviyeyi zaten geçtiyse (room < 0) önünde engel yok sayılır
        if 0 <= room < ROOM_MIN_R * risk:
            res["status"] = "no_room"
            return res

    # --- Giriş ---
    k_in = None
    for k in range(conf + 1, conf + 1 + ENTRY_WINDOW):
        if k >= n:
            res["status"] = "pending"
            return res
        if (L[k] < L[conf]) if long else (H[k] > H[conf]):
            res["status"] = "cancel_confirm"
            return res
        if (H[k] >= entry) if long else (L[k] <= entry):
            k_in = k
            break
    if k_in is None:
        res["status"] = "no_entry"
        return res

    fill = max(entry, O[k_in]) if long else min(entry, O[k_in])
    res.update(entry_bar=k_in, fill=fill)

    # --- Çıkış ---
    def close_trade(bar, price, status):
        res.update(exit_bar=bar, exit=price, status=status)
        gross = (price - fill) / risk if long else (fill - price) / risk
        fees = (fill * FEE_TAKER + price * (FEE_MAKER if status == "win" else FEE_TAKER)) / risk
        res.update(r_gross=gross, r_net=gross - fees)
        return res

    # Başabaş: fiyat +BE_TRIGGER R'ye gelince stop girişe çekilir (sonraki mumdan itibaren)
    be_level = (fill + BE_TRIGGER * risk) if long else (fill - BE_TRIGGER * risk)
    cur_stop, be_on = stop, False

    def reached_be(bar):
        return BE_TRIGGER > 0 and ((H[bar] >= be_level) if long else (L[bar] <= be_level))

    # Giriş mumunda TP (stop bu mumda olamaz: olsaydı giriş iptal edilirdi)
    if (H[k_in] >= tp) if long else (L[k_in] <= tp):
        return close_trade(k_in, tp, "win")
    if reached_be(k_in):
        cur_stop, be_on = fill, True

    for m in range(k_in + 1, n):
        hit_stop = (L[m] <= cur_stop) if long else (H[m] >= cur_stop)
        hit_tp = (H[m] >= tp) if long else (L[m] <= tp)
        if hit_stop:
            price = min(cur_stop, O[m]) if long else max(cur_stop, O[m])
            return close_trade(m, price, "be" if be_on else "loss")
        if hit_tp:
            return close_trade(m, tp, "win")
        if not be_on and reached_be(m):
            cur_stop, be_on = fill, True

    res["status"] = "open"
    return res
