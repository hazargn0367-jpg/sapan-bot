"""
İŞLEM KURALLARI (temas uyarısından sonrası)

LONG (SHORT tam tersi):
 1. Temas mumu: strategy.py'deki tüm şartlar + EMA20'nin ÜSTÜNDE kapanış
 2. Onay: Sonraki 3 mum içinde, temas mumunun tepesinin üstünde kapatan ilk mum.
    O ana kadar (onay mumu dahil) hiçbir mum temas mumunun dibinin altına inmez.
 3. Giriş: onay mumunun tepesi + 1 tık   |   Stop: onay mumunun dibi - 1 tık
 4. ATR(14, RMA) filtresi: giriş-stop mesafesi <= 1.5 x ATR (onay mumundaki ATR)
 5. Giriş emri onay mumundan sonraki 2 mum geçerli. Girişten önce fiyat onay
    mumunun dibinin altına inerse iptal.
 6. TP: riskin 2 katı (1:2)

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
RR = 2.0               # hedef: riskin kaç katı
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
    status: no_close | cancel_touch | no_confirm | atr | cancel_confirm |
            no_entry | win | loss | open | pending"""
    O = df["Open"].values
    H = df["High"].values
    L = df["Low"].values
    C = df["Close"].values
    A = df["ATR"].values
    n = len(df)
    long = side == "LONG"
    res = {"side": side, "touch": i}

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
    def close_trade(bar, price, won):
        res.update(exit_bar=bar, exit=price, status="win" if won else "loss")
        gross = (price - fill) / risk if long else (fill - price) / risk
        fees = (fill * FEE_TAKER + price * (FEE_MAKER if won else FEE_TAKER)) / risk
        res.update(r_gross=gross, r_net=gross - fees)
        return res

    # Giriş mumunda TP (stop bu mumda olamaz: olsaydı giriş iptal edilirdi)
    if (H[k_in] >= tp) if long else (L[k_in] <= tp):
        return close_trade(k_in, tp, True)

    for m in range(k_in + 1, n):
        hit_stop = (L[m] <= stop) if long else (H[m] >= stop)
        hit_tp = (H[m] >= tp) if long else (L[m] <= tp)
        if hit_stop:
            price = min(stop, O[m]) if long else max(stop, O[m])
            return close_trade(m, price, False)
        if hit_tp:
            return close_trade(m, tp, True)

    res["status"] = "open"
    return res
