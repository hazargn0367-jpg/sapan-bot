"""
STRATEJİ: Net trend + gövde kapanışlı kırılım + EMA20'ye ilk temas

Kurallar (LONG; SHORT tam tersi):
 1. Trend: EMA20 > EMA50 > EMA100 ve aralarında en az %0.1 mesafe
 2. Son 150 mumun en yüksek tepesi, son 30 mum içinde oluşmuş olmalı
 3. Bu tepe, kendinden önceki zirveyi GÖVDE KAPANIŞIYLA kırmış olmalı
 4. Tepeden sonra fiyat EMA20'ye hiç değmemiş olmalı (ilk temas)
 5. Geri çekilmede en fazla 2 ters (yeşil) mum olmalı
 6. Şu anki mumun iğnesi EMA20'ye değiyor (%0.03 tolerans) ve Stoch K < 30

Bu dosya sadece "sinyal var mı?" sorusuna cevap verir.
Telegram, veri çekme vs. burada YOK. Böylece burayı değiştirmek
botun diğer kısımlarını bozamaz. Backtest de aynı fonksiyonu kullanacak.
"""

import numpy as np

# ---- Parametreler (değiştirmek istersen sadece burayı değiştir) ----
EMA_FAST, EMA_MID, EMA_SLOW = 20, 50, 100
EMA_GAP = 0.001            # EMA'lar arası min. mesafe (%0.1)
STOCH_PERIOD, STOCH_SMOOTH = 5, 3
STOCH_LONG_MAX = 30        # LONG için Stoch K bunun altında olmalı
STOCH_SHORT_MIN = 70       # SHORT için Stoch K bunun üstünde olmalı
LOOKBACK = 150             # Tepe/dip aranacak mum sayısı
RECENT = 30                # Tepe/dip en fazla kaç mum önce oluşmuş olabilir
PEAK_GAP = 5               # Önceki zirve, yeni tepeden en az kaç mum önce
MAX_EXCEPTION_CANDLES = 2  # Geri çekilmede izin verilen ters mum sayısı
TOLERANCE_LONG = 1.0003    # EMA20 temas toleransı (%0.03)
TOLERANCE_SHORT = 0.9997
MIN_CANDLES = 180
TOUCH_NTH = 1              # 1 (canlı): tepeden sonra sadece İLK EMA20 teması · 2 / 3: aynı bacakta 2. / 3. temasa da izin (20.10 testi)
TOUCH_EMA = 20             # 20 (canlı) / 50 / 100: temasın aranacağı EMA (sadece backtest testi, 17.10; canlı hep 20)


def add_indicators(df):
    df = df.copy()
    df["EMA20"] = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["EMA50"] = df["Close"].ewm(span=EMA_MID, adjust=False).mean()
    df["EMA100"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()

    low_min = df["Low"].rolling(window=STOCH_PERIOD).min()
    high_max = df["High"].rolling(window=STOCH_PERIOD).max()
    denom = (high_max - low_min).replace(0, np.nan)
    raw_k = 100 * (df["Close"] - low_min) / denom
    df["Stoch_K"] = raw_k.rolling(window=STOCH_SMOOTH).mean()
    return df


COLS = ("Open", "High", "Low", "Close", "EMA20", "EMA50", "EMA100", "Stoch_K", "timestamp", "EMA20_REAL")


def arrays(df):
    """Hız için sütunlar numpy dizisi olarak (kopya yok). Aynı tabloda çok mum incelenecekse bir kez hazırlanır."""
    return {k: df[k].to_numpy() for k in COLS if k in df.columns}


def _variant_ok(a, i, pivot, long):
    """EMA50 / EMA100 temas testi (tablonun EMA20 sütunu temas çizgisini taşır, gerçek EMA20 EMA20_REAL'de; backtest.line_df).
    1) EMA20 > EMA50 > EMA100 sırası temas mumunda değil TEPE/DİP mumunda aranır.
    2) Tepeden temasa kadar daha sığ bir EMA'ya değip kendi tarafında kapatan mum (sıçrama) varsa düzeltme bozulmuştur;
       EMA'yı kapanışla delip geçen mumlar serbest. EMA50 temasında EMA20, EMA100 temasında EMA20 ve EMA50 kontrol edilir."""
    e20, e50, e100 = a["EMA20_REAL"], a["EMA50"], a["EMA100"]
    if long:
        if not (e20[pivot] > e50[pivot] * (1 + EMA_GAP) and e50[pivot] > e100[pivot] * (1 + EMA_GAP)):
            return False
    elif not (e20[pivot] < e50[pivot] * (1 - EMA_GAP) and e50[pivot] < e100[pivot] * (1 - EMA_GAP)):
        return False
    lo, hi = pivot + 1, i
    if hi <= lo:
        return True
    L, H, C = a["Low"][lo:hi], a["High"][lo:hi], a["Close"][lo:hi]
    shallow = [e20[lo:hi]] + ([e50[lo:hi]] if TOUCH_EMA >= 100 else [])
    for e in shallow:
        if long:
            if ((L <= e * TOLERANCE_LONG) & (C > e)).any():
                return False
        elif ((H >= e * TOLERANCE_SHORT) & (C < e)).any():
            return False
    return True


def nth_local_peak(H, L, E20, pivot, i, long):
    """2./3. temas testi: son önceki temastan sonraki yerel tepe (LONG) / dip (SHORT) mumu; önceki temas yoksa tepe/dip mumunun kendisi.
    Düzeltme ters mum sayısı ve yavaş düzeltme ölçüsü bu mumdan başlar."""
    after = pivot + 1
    if i - 1 < after:
        return pivot
    t = (L[after:i] <= E20[after:i]) if long else (H[after:i] >= E20[after:i])
    idx = np.flatnonzero(t)
    if len(idx) == 0:
        return pivot
    e = after + int(idx[-1])
    seg = H[e:i] if long else L[e:i]
    return e + int(np.argmax(seg) if long else np.argmin(seg))


def touch_order(H, L, E20, pivot, i, long):
    """Temas kaçıncı temas: tepeden/dipten sonra EMA20'ye değip ayrılan önceki dönem sayısı + 1 (1 = ilk temas)."""
    after = pivot + 1
    if i - 1 < after:
        return 1
    t = (L[after:i] <= E20[after:i]) if long else (H[after:i] >= E20[after:i])
    idx = np.flatnonzero(t)
    if len(idx) == 0:
        return 1
    return 2 + int(((idx[1:] - idx[:-1]) > 1).sum())


def _nth_start(a, i, pivot, long):
    """TOUCH_NTH > 1: önceki temaslar geçerli mi? Geçerliyse ters mum sayımının başlayacağı mum, değilse None.
    Şartlar: tepeden temasa kadar hiçbir mum EMA20'nin yanlış tarafında kapatmamış, önceki temas dönemi sayısı ≤ TOUCH_NTH-1,
    temas mumu yeni bir temas dönemi başlatıyor (önceki mum EMA20'ye değmemiş)."""
    after = pivot + 1
    if i - 1 < after:
        return pivot
    L, H, C, E20 = a["Low"], a["High"], a["Close"], a["EMA20"]
    wrong = (C[after:i] <= E20[after:i]).any() if long else (C[after:i] >= E20[after:i]).any()
    if wrong:
        return None
    t = (L[after:i] <= E20[after:i]) if long else (H[after:i] >= E20[after:i])
    if t.any() and t[-1]:
        return None
    if touch_order(H, L, E20, pivot, i, long) - 1 > TOUCH_NTH - 1:
        return None
    return nth_local_peak(H, L, E20, pivot, i, long)


def _check_long(a, i):
    H, L, O, C, E20 = a["High"], a["Low"], a["Open"], a["Close"], a["EMA20"]
    start = max(0, i - LOOKBACK)
    peak_idx = start + int(np.argmax(H[start:i]))
    if peak_idx < i - RECENT:
        return None

    past_end = peak_idx - PEAK_GAP
    if past_end <= start:
        return None
    historical_peak = H[start:past_end].max()

    # Gövde kapanışlı zirve kırılımı
    if not (C[max(0, peak_idx - 2): min(i, peak_idx + 3)] > historical_peak).any():
        return None

    after = peak_idx + 1
    cnt0 = after
    if TOUCH_NTH > 1:
        ls = _nth_start(a, i, peak_idx, True)
        if ls is None:
            return None
        cnt0 = ls + 1
    elif i - 1 >= after and not (L[after:i] > E20[after:i]).all():
        return None
    if "EMA20_REAL" in a and not _variant_ok(a, i, peak_idx, True):
        return None

    if int((C[cnt0:i + 1] > O[cnt0:i + 1]).sum()) > MAX_EXCEPTION_CANDLES:
        return None

    if L[i] <= E20[i] * TOLERANCE_LONG and a["Stoch_K"][i] < STOCH_LONG_MAX:
        return {"side": "LONG", "pivot_idx": int(peak_idx)}
    return None


def _check_short(a, i):
    H, L, O, C, E20 = a["High"], a["Low"], a["Open"], a["Close"], a["EMA20"]
    start = max(0, i - LOOKBACK)
    valley_idx = start + int(np.argmin(L[start:i]))
    if valley_idx < i - RECENT:
        return None

    past_end = valley_idx - PEAK_GAP
    if past_end <= start:
        return None
    historical_valley = L[start:past_end].min()

    # Gövde kapanışlı dip kırılımı
    if not (C[max(0, valley_idx - 2): min(i, valley_idx + 3)] < historical_valley).any():
        return None

    after = valley_idx + 1
    cnt0 = after
    if TOUCH_NTH > 1:
        ls = _nth_start(a, i, valley_idx, False)
        if ls is None:
            return None
        cnt0 = ls + 1
    elif i - 1 >= after and not (H[after:i] < E20[after:i]).all():
        return None
    if "EMA20_REAL" in a and not _variant_ok(a, i, valley_idx, False):
        return None

    if int((C[cnt0:i + 1] < O[cnt0:i + 1]).sum()) > MAX_EXCEPTION_CANDLES:
        return None

    if H[i] >= E20[i] * TOLERANCE_SHORT and a["Stoch_K"][i] > STOCH_SHORT_MIN:
        return {"side": "SHORT", "pivot_idx": int(valley_idx)}
    return None


def evaluate_at(df, i, arr=None):
    """df: add_indicators() uygulanmış, index'i 0..n-1 olan tablo.
    i: kontrol edilecek mumun sırası. Sinyal varsa dict, yoksa None.
    arr: arrays(df) (aynı tabloda çok mum incelenirken bir kez hazırlanıp verilir)."""
    a = arr if arr is not None else arrays(df)
    if "EMA20_REAL" in a:   # EMA50 / EMA100 temas testi: trend sırası tepe mumunda aranır (_variant_ok)
        sig = _check_long(a, i) or _check_short(a, i)
        if sig:
            sig["price"] = float(a["Close"][i])
            sig["stoch"] = float(a["Stoch_K"][i])
            sig["timestamp"] = a["timestamp"][i] if "timestamp" in a else None
        return sig
    ema20, ema50, ema100 = a["EMA20"][i], a["EMA50"][i], a["EMA100"][i]

    uptrend = ema20 > ema50 * (1 + EMA_GAP) and ema50 > ema100 * (1 + EMA_GAP)
    downtrend = ema20 < ema50 * (1 - EMA_GAP) and ema50 < ema100 * (1 - EMA_GAP)

    if uptrend:
        sig = _check_long(a, i)
    elif downtrend:
        sig = _check_short(a, i)
    else:
        return None

    if sig:
        sig["price"] = float(a["Close"][i])
        sig["stoch"] = float(a["Stoch_K"][i])
        sig["timestamp"] = a["timestamp"][i] if "timestamp" in a else None
    return sig


def diagnose(df, i):
    """Bir mum için temas şartlarını TEK TEK döner (kontrol ve backtest raporu için).
    Hepsi True ise evaluate_at() sinyal verir."""
    c = df.iloc[i]
    up = c["EMA20"] > c["EMA50"] * (1 + EMA_GAP) and c["EMA50"] > c["EMA100"] * (1 + EMA_GAP)
    down = c["EMA20"] < c["EMA50"] * (1 - EMA_GAP) and c["EMA50"] < c["EMA100"] * (1 - EMA_GAP)
    d = {"trend": bool(up or down), "side": "LONG" if up else ("SHORT" if down else None)}
    if not d["trend"]:
        return d

    start = max(0, i - LOOKBACK)
    if up:
        pivot = df["High"].iloc[start:i].idxmax()
    else:
        pivot = df["Low"].iloc[start:i].idxmin()
    d["pivot_recent"] = bool(pivot >= i - RECENT)
    past_end = pivot - PEAK_GAP
    d["body_break"] = False
    if past_end > start:
        closes = df["Close"].iloc[max(0, pivot - 2): min(i, pivot + 3)]
        if up:
            d["body_break"] = bool((closes > df["High"].iloc[start:past_end].max()).any())
        else:
            d["body_break"] = bool((closes < df["Low"].iloc[start:past_end].min()).any())

    after = pivot + 1
    seg = df.iloc[after:i]
    pullback = df.iloc[after: i + 1]
    if up:
        d["first_touch"] = bool((seg["Low"] > seg["EMA20"]).all())
        d["clean_pullback"] = int((pullback["Close"] > pullback["Open"]).sum()) <= MAX_EXCEPTION_CANDLES
        d["touch"] = bool(c["Low"] <= c["EMA20"] * TOLERANCE_LONG)
        d["stoch"] = bool(c["Stoch_K"] < STOCH_LONG_MAX)
    else:
        d["first_touch"] = bool((seg["High"] < seg["EMA20"]).all())
        d["clean_pullback"] = int((pullback["Close"] < pullback["Open"]).sum()) <= MAX_EXCEPTION_CANDLES
        d["touch"] = bool(c["High"] >= c["EMA20"] * TOLERANCE_SHORT)
        d["stoch"] = bool(c["Stoch_K"] > STOCH_SHORT_MIN)
    return d


def check_signal(df):
    """Canlı bot için: tablonun SON mumunu kontrol eder."""
    if df is None or len(df) < MIN_CANDLES:
        return None
    df = add_indicators(df.reset_index(drop=True))
    return evaluate_at(df, len(df) - 1)
