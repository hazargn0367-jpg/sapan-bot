import sys
import time
import requests
import pandas as pd
import numpy as np

sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
CHAT_ID = "1494316515"

POPULAR_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", 
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT",
    "ETCUSDT", "XLMUSDT", "NEARUSDT", "APTUSDT", "FTMUSDT", "ALGOUSDT", "QNTUSDT",
    "VETUSDT", "ICPUSDT", "FILUSDT", "GRTUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT",
    "CHZUSDT", "EOSUSDT", "AAVEUSDT", "THETAUSDT", "EGLDUSDT", "XTZUSDT", "CAKEUSDT",
    "CRVUSDT", "SNXUSDT", "ENJUSDT", "BATUSDT", "ZILUSDT", "KSMUSDT", "RUNEUSDT",
    "ARBUSDT", "OPUSDT", "SUIUSDT", "SEIUSDT", "TIAUSDT", "INJUSDT", "RENDERUSDT",
    "FETUSDT", "AGIXUSDT", "OCEANUSDT", "IMXUSDT", "GALAUSDT", "FLOWUSDT", "KAVAUSDT",
    "GMTUSDT", "PEPEUSDT", "SHIBUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT", "BCHUSDT",
    "TRXUSDT", "STXUSDT", "ARUSDT", "MINAUSDT", "RNDRUSDT", "ORDIUSDT", "SATSUSDT",
    "RATSUSDT", "ACEUSDT", "PORTALUSDT", "PIXELUSDT", "STRKUSDT", "ETHFIUSDT", "ENAUSDT",
    "BBUSDT", "NOTUSDT", "IOUSDT", "ZKUSDT", "BLURUSDT", "PENDLEUSDT", "MAVUSDT",
    "CYBERUSDT", "HBARUSDT", "HOOKUSDT", "HIGHUSDT", "IDUSDT", "NFPUSDT", "AIUSDT",
    "XAIUSDT", "ALTUSDT", "JUPUSDT", "PYTHUSDT", "MANTAUSDT", "WLDUSDT", "MEMEUSDT",
    "ORCAUSDT", "TIAUSDT", "ONDOUSDT", "POLUSDT", "BOMEUSDT", "SAGAUSDT",
    "TNSRUSDT", "OMUSDT", "REZUSDT", "LISTAUSDT", "ZROUSDT", "BANANAUSDT", "TONUSDT",
    "DOGSUSDT", "NEIROUSDT", "TURBOUSDT", "1000SATSUSDT", "1000RATSUSDT", "1000PEPEUSDT",
    "1000SHIBUSDT", "1000FLOKIUSDT", "1000BONKUSDT", "1000LUNCUSDT", "1000XECUSDT"
]

POPULAR_PAIRS = sorted(list(set(POPULAR_PAIRS)))
notified_signals = {}

def send_telegram_message(token, chat_id, message):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")
        return False

def get_binance_klines(symbol, interval="15m", limit=120):
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            data = response.json()
            if isinstance(data, list):
                df = pd.DataFrame(data, columns=[
                    'timestamp', 'open', 'high', 'low', 'close', 'volume', 
                    'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_gt_high', 'ignore'
                ])
                for col in ['open', 'high', 'low', 'close']:
                    df[col] = df[col].astype(float)
                return df
    except Exception:
        pass
    return None

def scan_market():
    print(f"\n--- Piyasa Taranıyor | EMA 20-50-100 Trend Filtreli Çift Sapan (Parite: {len(POPULAR_PAIRS)}) ---")
    success_count = 0
    match_count = 0
    
    for symbol in POPULAR_PAIRS:
        df = get_binance_klines(symbol, interval="15m", limit=120)
        time.sleep(0.02)
        
        if df is None or len(df) < 50:
            continue
            
        success_count += 1
        
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
        
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr'] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        
        low_min = df['low'].rolling(window=5).min()
        high_max = df['high'].rolling(window=5).max()
        fast_k = 100 * (df['close'] - low_min) / (high_max - low_min)
        df['stoch_k'] = fast_k.rolling(window=3).mean()
        
        df = df.dropna().reset_index(drop=True)
        if len(df) < 25:
            continue
            
        # --- 1. SİSTEM: SAF EMA20 TEMAS SİSTEMİ (EMA 20-50-100 Paralel Trend Filtreli) ---
        i_saf = len(df) - 3
        if i_saf >= 20:
            touch_saf = df.iloc[i_saf]
            m1_saf = df.iloc[i_saf+1]
            m2_saf = df.iloc[i_saf+2]
            recent_slice_saf = df.iloc[max(0, i_saf-6):i_saf]
            
            # Trend Şartı (EMA20, EMA50, EMA100 paralel sıralı olmalı)
            is_bullish_trend = (touch_saf['ema20'] > touch_saf['ema50']) and (touch_saf['ema50'] > touch_saf['ema100'])
            is_bearish_trend = (touch_saf['ema20'] < touch_saf['ema50']) and (touch_saf['ema50'] < touch_saf['ema100'])
            
            saf_signal = False
            saf_type = ""
            saf_price = 0.0
            
            # Short (Düşüş Trendi + Yeni Tepe + Temas)
            recent_highs_saf = df['high'].iloc[max(0, i_saf-10):i_saf]
            is_new_peak_saf = touch_saf['high'] >= recent_highs_saf.max() * 0.995 or recent_highs_saf.idxmax() < i_saf - 2
            short_touch_saf = (touch_saf['high'] >= touch_saf['ema20']) and (touch_saf['close'] < touch_saf['ema20'])
            
            if is_bearish_trend and short_touch_saf and is_new_peak_saf:
                counter_candles = len(recent_slice_saf[recent_slice_saf['close'] > recent_slice_saf['open']])
                if counter_candles <= 2:
                    if m1_saf['close'] < touch_saf['low'] or (m2_saf['close'] < touch_saf['low'] and m1_saf['high'] <= touch_saf['high']):
                        saf_signal = True
                        saf_type = "SAF EMA20 TEMAS SHORT SİNYALİ"
                        saf_price = touch_saf['close']
            
            # Long (Yükseliş Trendi + Yeni Dip + Temas)
            if not saf_signal:
                recent_lows_saf = df['low'].iloc[max(0, i_saf-10):i_saf]
                is_new_bottom_saf = touch_saf['low'] <= recent_lows_saf.min() * 1.005 or recent_lows_saf.idxmin() < i_saf - 2
                long_touch_saf = (touch_saf['low'] <= touch_saf['ema20']) and (touch_saf['close'] > touch_saf['ema20'])
                
                if is_bullish_trend and long_touch_saf and is_new_bottom_saf:
                    counter_candles = len(recent_slice_saf[recent_slice_saf['close'] < recent_slice_saf['open']])
                    if counter_candles <= 2:
                        if m1_saf['close'] > touch_saf['high'] or (m2_saf['close'] > touch_saf['high'] and m1_saf['low'] >= touch_saf['low']):
                            saf_signal = True
                            saf_type = "SAF EMA20 TEMAS LONG SİNYALİ"
                            saf_price = touch_saf['close']

            if saf_signal:
                key_saf = f"{symbol}_{touch_saf['timestamp']}_saf"
                if notified_signals.get(f"{symbol}_saf") != key_saf:
                    clean_symbol = symbol.replace("_", "")
                    binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
                    msg_saf = (
                        f"🎯 <b>{saf_type}</b>\n\n"
                        f"Parite: #{clean_symbol} (15m)\n"
                        f"Fiyat: {round(saf_price, 4)}\n"
                        f"Açıklama: EMA 20-50-100 paralel trend onaylı saf temas.\n\n"
                        f"🔗 <a href='{binance_link}'>Grafiği Aç</a>"
                    )
                    if send_telegram_message(BOT_TOKEN, CHAT_ID, msg_saf):
                        notified_signals[f"{symbol}_saf"] = key_saf
                        match_count += 1

        # --- 2. SİSTEM: GELİŞMİŞ BACKTEST SAPAN SİSTEMİ (Stoch RSI + ATR) ---
        i_adv = len(df) - 3
        if i_adv >= 20:
            touch_adv = df.iloc[i_adv]
            m1_adv = df.iloc[i_adv+1]
            m2_adv = df.iloc[i_adv+2]
            recent_slice_adv = df.iloc[max(0, i_adv-6):i_adv]
            
            adv_signal = False
            adv_type = ""
            adv_entry = 0.0
            adv_sl = 0.0
            
            # Short
            recent_highs_adv = df['high'].iloc[max(0, i_adv-10):i_adv]
            is_new_peak_adv = touch_adv['high'] >= recent_highs_adv.max() * 0.995 or recent_highs_adv.idxmax() < i_adv - 2
            short_touch_adv = (touch_adv['high'] >= touch_adv['ema20']) and (touch_adv['close'] < touch_adv['ema20'])
            
            if short_touch_adv and (touch_adv['stoch_k'] > 70) and is_new_peak_adv:
                counter_candles = len(recent_slice_adv[recent_slice_adv['close'] > recent_slice_adv['open']])
                if counter_candles <= 2:
                    triggered = False
                    entry = 0
                    sl = touch_adv['high']
                    if m1_adv['close'] < touch_adv['low']:
                        entry = m1_adv['close']
                        triggered = True
                    elif m2_adv['close'] < touch_adv['low'] and m1_adv['high'] <= touch_adv['high']:
                        entry = m2_adv['close']
                        triggered = True
                    if triggered:
                        dist = sl - entry
                        if dist > 0 and dist <= touch_adv['atr'] * 3.0:
                            adv_signal = True
                            adv_type = "GELİŞMİŞ BACKTEST SAPAN SHORT"
                            adv_entry = entry
                            adv_sl = sl

            # Long
            if not adv_signal:
                recent_lows_adv = df['low'].iloc[max(0, i_adv-10):i_adv]
                is_new_bottom_adv = touch_adv['low'] <= recent_lows_adv.min() * 1.005 or recent_lows_adv.idxmin() < i_adv - 2
                long_touch_adv = (touch_adv['low'] <= touch_adv['ema20']) and (touch_adv['close'] > touch_adv['ema20'])
                
                if long_touch_adv and (touch_adv['stoch_k'] < 30) and is_new_bottom_adv:
                    counter_candles = len(recent_slice_adv[recent_slice_adv['close'] < recent_slice_adv['open']])
                    if counter_candles <= 2:
                        triggered = False
                        entry = 0
                        sl = touch_adv['low']
                        if m1_adv['close'] > touch_adv['high']:
                            entry = m1_adv['close']
                            triggered = True
                        elif m2_adv['close'] > touch_adv['high'] and m1_adv['low'] >= touch_adv['low']:
                            entry = m2_adv['close']
                            triggered = True
                        if triggered:
                            dist = entry - sl
                            if dist > 0 and dist <= touch_adv['atr'] * 3.0:
                                adv_signal = True
                                adv_type = "GELİŞMİŞ BACKTEST SAPAN LONG"
                                adv_entry = entry
                                adv_sl = sl

            if adv_signal:
                key_adv = f"{symbol}_{touch_adv['timestamp']}_adv"
                if notified_signals.get(f"{symbol}_adv") != key_adv:
                    clean_symbol = symbol.replace("_", "")
                    binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
                    msg_adv = (
                        f"🚀 <b>{adv_type}</b>\n\n"
                        f"Parite: #{clean_symbol} (15m)\n"
                        f"Giriş: {round(adv_entry, 4)} | SL: {round(adv_sl, 4)}\n"
                        f"Stoch K: {round(touch_adv['stoch_k'], 2)}\n\n"
                        f"🔗 <a href='{binance_link}'>Grafiği Aç</a>"
                    )
                    if send_telegram_message(BOT_TOKEN, CHAT_ID, msg_adv):
                        notified_signals[f"{symbol}_adv"] = key_adv
                        match_count += 1
                
    print(f"Tarama tamamlandı. İşlenen: {success_count} | Sinyal: {match_count}")

if __name__ == "__main__":
    print("EMA 20-50-100 Trend Filtreli Çift Sapan Botu Başlatıldı!")
    send_telegram_message(BOT_TOKEN, CHAT_ID, "🤖 EMA 20-50-100 Trend Filtreli Çift Sapan Botu aktif!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
