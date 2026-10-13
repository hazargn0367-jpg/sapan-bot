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

import pandas as pd

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


def touch_closes_right_side(df, i, side):
    c = df.iloc[i]
    return c["Close"] > c["EMA20"] if side == "LONG" else c["Close"] < c["EMA20"]


def simulate(df, i, side, tick):
    """i: temas mumu. Sonucu sözlük olarak döner.
    status: session | no_close | cancel_touch | no_confirm | atr | atr_min | min_risk | max_risk | cancel_confirm |
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

    if not touch_closes_right_side(df, i, side):
        res["status"] = "no_close"
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

    if long:
        entry, stop = H[conf] + tick, L[conf] - tick
    else:
        entry, stop = L[conf] - tick, H[conf] + tick
    risk = abs(entry - stop)
    tp = entry + RR * risk if long else entry - RR * risk
    res.update(confirm=conf, entry=entry, stop=stop, tp=tp, risk=risk, atr=A[conf])

    if risk > ATR_MAX_MULT * A[conf]:
        res["status"] = "atr"
        return res
    if MIN_ATR_MULT > 0 and risk < MIN_ATR_MULT * A[conf]:
        res["status"] = "atr_min"
        return res
    risk_pct = 100 * risk / entry
    if risk_pct < (MIN_RISK_PCT if FILTERS else BASE_MIN_RISK_PCT):
        res["status"] = "min_risk"
        return res
    if FILTERS and risk_pct > MAX_RISK_PCT:
        res["status"] = "max_risk"
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
