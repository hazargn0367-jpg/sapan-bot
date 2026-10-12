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


def _check_long(df, i):
    start = max(0, i - LOOKBACK)
    peak_idx = df["High"].iloc[start:i].idxmax()
    if peak_idx < i - RECENT:
        return None

    past_end = peak_idx - PEAK_GAP
    if past_end <= start:
        return None
    historical_peak = df["High"].iloc[start:past_end].max()

    # Gövde kapanışlı zirve kırılımı
    closes = df["Close"].iloc[max(0, peak_idx - 2): min(i, peak_idx + 3)]
    if not (closes > historical_peak).any():
        return None

    after = peak_idx + 1
    if i - 1 >= after:
        seg = df.iloc[after:i]
        if not (seg["Low"] > seg["EMA20"]).all():
            return None

    pullback = df.iloc[after: i + 1]
    if (pullback["Close"] > pullback["Open"]).sum() > MAX_EXCEPTION_CANDLES:
        return None

    c = df.iloc[i]
    if c["Low"] <= c["EMA20"] * TOLERANCE_LONG and c["Stoch_K"] < STOCH_LONG_MAX:
        return {"side": "LONG", "pivot_idx": int(peak_idx)}
    return None


def _check_short(df, i):
    start = max(0, i - LOOKBACK)
    valley_idx = df["Low"].iloc[start:i].idxmin()
    if valley_idx < i - RECENT:
        return None

    past_end = valley_idx - PEAK_GAP
    if past_end <= start:
        return None
    historical_valley = df["Low"].iloc[start:past_end].min()

    # Gövde kapanışlı dip kırılımı
    closes = df["Close"].iloc[max(0, valley_idx - 2): min(i, valley_idx + 3)]
    if not (closes < historical_valley).any():
        return None

    after = valley_idx + 1
    if i - 1 >= after:
        seg = df.iloc[after:i]
        if not (seg["High"] < seg["EMA20"]).all():
            return None

    pullback = df.iloc[after: i + 1]
    if (pullback["Close"] < pullback["Open"]).sum() > MAX_EXCEPTION_CANDLES:
        return None

    c = df.iloc[i]
    if c["High"] >= c["EMA20"] * TOLERANCE_SHORT and c["Stoch_K"] > STOCH_SHORT_MIN:
        return {"side": "SHORT", "pivot_idx": int(valley_idx)}
    return None


def evaluate_at(df, i):
    """df: add_indicators() uygulanmış, index'i 0..n-1 olan tablo.
    i: kontrol edilecek mumun sırası. Sinyal varsa dict, yoksa None."""
    c = df.iloc[i]
    ema20, ema50, ema100 = c["EMA20"], c["EMA50"], c["EMA100"]

    uptrend = ema20 > ema50 * (1 + EMA_GAP) and ema50 > ema100 * (1 + EMA_GAP)
    downtrend = ema20 < ema50 * (1 - EMA_GAP) and ema50 < ema100 * (1 - EMA_GAP)

    if uptrend:
        sig = _check_long(df, i)
    elif downtrend:
        sig = _check_short(df, i)
    else:
        return None

    if sig:
        sig["price"] = float(c["Close"])
        sig["stoch"] = float(c["Stoch_K"])
        sig["timestamp"] = c["timestamp"]
    return sig


def check_signal(df):
    """Canlı bot için: tablonun SON mumunu kontrol eder."""
    if df is None or len(df) < MIN_CANDLES:
        return None
    df = add_indicators(df.reset_index(drop=True))
    return evaluate_at(df, len(df) - 1)
