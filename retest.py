"""Kırılım + geri test sinyali (kullanıcı 20.10 "kodla", sadece backtest).

LONG (SHORT'ta tersi):
  1. Salınım tepesi: H[p], önceki ve sonraki RT_K mumun hepsinden yüksek (tepe RT_K mum sonra kesinleşir, ileriye bakma yok).
  2. Kırılım mumu b: tepeden sonra seviyenin ÜSTÜNDE kapatan ilk mum (p'den en fazla RT_BREAK_MAX mum sonra); b'de
     EMA20 > EMA50 > EMA100 (strategy.EMA_GAP payıyla) ve kapanış EMA20'nin üstünde; gövde ≥ RT_BODY_ATR ATR.
  3. Uzantı: kırılımdan sonra fiyat seviyenin en az RT_EXT ATR üstüne çıkar (gerçek kopuş).
  4. Geri test r: kırılımdan sonra en geç RT_MAX mum içinde dibi seviyenin RT_TOL ATR yakınına (ya da altına) inen ilk mum;
     kırılımdan geri teste kadar hiçbir mum seviyenin altında KAPATMAZ (kapatırsa kırılım bozuldu, sinyal yok).
  5. Onay / giriş / stop / TP / erken çıkış: EMA20 sistemiyle aynı (trade_rules sabitleri): geri test mumundan sonra en geç
     CONFIRM_WINDOW mumda geri test mumunun tepesinin üstünde kapanış (önce dibinin altına inerse iptal); giriş onay tepesi + 1 tick,
     stop min(geri test dibi, onay dibi) - STOP_BUFFER_ATR; TP RR; ATR / risk % sınırları; FAILED_ENTRY_BARS erken çıkış.
  RT_ROOM > 0: giriş ile kırılım sonrası tepe arası en az RT_ROOM R (giriş tepeyi geçtiyse engel yok).
Sabitler strategy.py'de (RETEST, RT_*) ki backtest "sig" ile değiştirebilsin.
"""
import numpy as np
import pandas as pd

import strategy as st
import trade_rules as tr


def find(df):
    """[(r, side, level, b)] geri test mumları (zaman sırasıyla)."""
    O = df["Open"].values
    H = df["High"].values
    L = df["Low"].values
    C = df["Close"].values
    A = df["ATR"].values
    e20, e50, e100 = df["EMA20"].values, df["EMA50"].values, df["EMA100"].values
    if "EMA20_REAL" in df.columns:
        e20 = df["EMA20_REAL"].values
    n = len(df)
    K = int(st.RT_K)
    g = st.EMA_GAP
    out = {}
    for long in (True, False):
        X = H if long else L
        xs = pd.Series(X)
        ext_w = xs.rolling(2 * K + 1, center=True).max() if long else xs.rolling(2 * K + 1, center=True).min()
        prev_w = xs.shift(1).rolling(K).max() if long else xs.shift(1).rolling(K).min()
        # salınım: penceredeki en uç değer ve solundaki K mumun hepsinden kesin büyük (eşit tepelerde ilki)
        piv = (xs == ext_w) & ((xs > prev_w) if long else (xs < prev_w))
        for p in np.flatnonzero(piv.values):
            if p < K or p > n - K - 2:
                continue
            level = X[p]
            b = None
            for j in range(p + 1, min(n, p + 1 + st.RT_BREAK_MAX)):
                if (C[j] > level) if long else (C[j] < level):
                    b = j
                    break
            if b is None or b <= p + K:
                continue
            a = A[b]
            if not a > 0:
                continue
            if long:
                trend = e20[b] > e50[b] * (1 + g) and e50[b] > e100[b] * (1 + g) and C[b] > e20[b]
            else:
                trend = e20[b] < e50[b] * (1 - g) and e50[b] < e100[b] * (1 - g) and C[b] < e20[b]
            if not trend or abs(C[b] - O[b]) < st.RT_BODY_ATR * a:
                continue
            ext = False
            for r in range(b + 1, min(n, b + 1 + st.RT_MAX)):
                if (C[r] < level) if long else (C[r] > level):
                    break   # kırılım bozuldu
                touch = (L[r] <= level + st.RT_TOL * a) if long else (H[r] >= level - st.RT_TOL * a)
                if ext and touch:
                    key = (r, "LONG" if long else "SHORT")
                    # aynı mumda iki seviye: daha önemli olanı (LONG'da yüksek seviye) tut
                    if key not in out or (level > out[key][2] if long else level < out[key][2]):
                        out[key] = (r, key[1], float(level), b)
                    break
                if (H[r] >= level + st.RT_EXT * a) if long else (L[r] <= level - st.RT_EXT * a):
                    ext = True
    return sorted(out.values())


def simulate(df, r, side, level, b, tick):
    O = df["Open"].values
    H = df["High"].values
    L = df["Low"].values
    C = df["Close"].values
    A = df["ATR"].values
    n = len(df)
    long = side == "LONG"
    res = {"side": side, "touch": r, "mode": "retest", "level": level, "break_bar": b}
    lo, hi = L[r], H[r]
    conf = None
    for j in range(r + 1, r + 1 + tr.CONFIRM_WINDOW):
        if j >= n:
            res["status"] = "pending"
            return res
        if (L[j] < lo) if long else (H[j] > hi):
            res["status"] = "cancel_touch"
            return res
        if (C[j] > hi) if long else (C[j] < lo):
            conf = j
            break
    if conf is None:
        res["status"] = "no_confirm"
        return res
    if tr.WICK_MAX_BODY > 0:
        body = abs(C[conf] - O[conf])
        wick = (H[conf] - max(O[conf], C[conf])) if long else (min(O[conf], C[conf]) - L[conf])
        if wick > tr.WICK_MAX_BODY * body:
            res.update(confirm=conf, status="wick")
            return res
    a = A[conf]
    buf = tr.STOP_BUFFER_ATR * a
    if long:
        entry, stop = H[conf] + tick, min(L[r], L[conf]) - tick - buf
    else:
        entry, stop = L[conf] - tick, max(H[r], H[conf]) + tick + buf
    risk = abs(entry - stop)
    base_risk = risk - buf
    rr = tr.RR
    tp = entry + rr * risk if long else entry - rr * risk
    res.update(confirm=conf, entry=entry, stop=stop, tp=tp, risk=risk, atr=a, rr=rr)
    if base_risk > tr.ATR_MAX_MULT * a:
        res["status"] = "atr"
        return res
    risk_pct = 100 * risk / entry
    if risk_pct < tr.BASE_MIN_RISK_PCT:
        res["status"] = "min_risk"
        return res
    if risk_pct > tr.MAX_RISK_PCT:
        res["status"] = "max_risk"
        return res
    if st.RT_ROOM > 0:
        top = H[b:r + 1].max() if long else L[b:r + 1].min()
        room = (top - entry) if long else (entry - top)
        res["room_r"] = room / risk
        if 0 <= room < st.RT_ROOM * risk:
            res["status"] = "no_room"
            return res

    k_in = None
    for k in range(conf + 1, conf + 1 + tr.ENTRY_WINDOW):
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

    def close_trade(bar, price, status):
        res.update(exit_bar=bar, exit=price, status=status)
        gross = (price - fill) / risk if long else (fill - price) / risk
        fees = (fill * tr.FEE_TAKER + price * (tr.FEE_MAKER if status == "win" else tr.FEE_TAKER)) / risk
        res.update(r_gross=gross, r_net=gross - fees)
        return res

    early_off = [False]

    def failed(bar):
        ok = not early_off[0] and tr.FAILED_ENTRY_BARS > 0 and bar - k_in < tr.FAILED_ENTRY_BARS and \
            ((C[bar] < entry) if long else (C[bar] > entry))
        if ok and tr.EARLY_EXIT_MAX_ATR > 0 and ((fill - C[bar]) if long else (C[bar] - fill)) > tr.EARLY_EXIT_MAX_ATR * a:
            early_off[0] = True
            return False
        return ok

    if (H[k_in] >= tp) if long else (L[k_in] <= tp):
        return close_trade(k_in, tp, "win")
    if failed(k_in):
        res["early_exit"] = True
        return close_trade(k_in, C[k_in], "be")
    for m in range(k_in + 1, n):
        if (L[m] <= stop) if long else (H[m] >= stop):
            return close_trade(m, min(stop, O[m]) if long else max(stop, O[m]), "loss")
        if (H[m] >= tp) if long else (L[m] <= tp):
            return close_trade(m, tp, "win")
        if failed(m):
            res["early_exit"] = True
            return close_trade(m, C[m], "be")
    res["status"] = "open"
    return res
