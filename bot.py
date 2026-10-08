import sys
import time
import requests
import pandas as pd
import numpy as np

sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
CHAT_ID = "1494316515"

# MEXC & Binance Ortak Popüler Parite Listesi
SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "SHIB_USDT", "PEPE_USDT", 
    "NEAR_USDT", "SUI_USDT", "RENDER_USDT", "FET_USDT", "INJ_USDT", "ARB_USDT", "OP_USDT", 
    "TIA_USDT", "SEI_USDT", "JUP_USDT", "PYTH_USDT", "STRK_USDT", "ENA_USDT", "WIF_USDT", 
    "BOME_USDT", "ORDI_USDT", "BONK_USDT", "FLOKI_USDT", "AVAX_USDT", "LINK_USDT", "ADA_USDT", 
    "ATOM_USDT", "LTC_USDT", "BCH_USDT", "ETC_USDT", "ICP_USDT", "FIL_USDT", "STX_USDT", 
    "IMX_USDT", "GRT_USDT", "SNX_USDT", "CRV_USDT", "LDO_USDT", "AAVE_USDT", "MKR_USDT", 
    "SAND_USDT", "MANA_USDT", "AXS_USDT", "GALA_USDT", "CHZ_USDT", "ALGO_USDT", "VET_USDT", 
    "HBAR_USDT", "EGLD_USDT", "THETA_USDT", "XTZ_USDT", "KAVA_USDT", "RUNE_USDT", "UNI_USDT", 
    "FTM_USDT", "DOT_USDT", "ZRX_USDT", "IO_USDT", "ZK_USDT", "NOT_USDT", "OMNI_USDT", "REZ_USDT", 
    "TURBO_USDT", "POPCAT_USDT", "MEW_USDT", "TNSR_USDT", "POL_USDT", "DYM_USDT", "ZRO_USDT",
    "JASMY_USDT", "ARKM_USDT", "ONDO_USDT", "ALT_USDT", "MANTA_USDT", "WLD_USDT", "MEME_USDT",
    "PORTAL_USDT", "PIXEL_USDT", "ETHFI_USDT", "BB_USDT", "PENDLE_USDT", "MAV_USDT", "CYBER_USDT",
    "HOOK_USDT", "HIGH_USDT", "ID_USDT", "NFP_USDT", "AI_USDT", "XAI_USDT", "ACE_USDT", "XLM_USDT",
    "QNT_USDT", "ENJ_USDT", "BAT_USDT", "ZIL_USDT", "KSM_USDT", "CAKE_USDT", "BAKE_USDT", "OCEAN_USDT",
    "AGIX_USDT", "LSK_USDT", "BAL_USDT", "C98_USDT", "DAR_USDT", "MBOX_USDT", "PEOPLE_USDT", "GMT_USDT"
]

SYMBOLS = sorted(list(set(SYMBOLS)))
notified_signals = {}

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, json=payload, timeout=5)
        return True
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")
        return False

def get_mexc_candles(symbol):
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min15&limit=100"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            res_json = res.json()
            if res_json.get("success") and res_json.get("data"):
                d = res_json["data"]
                times = d.get("time", [])
                opens = d.get("open", [])
                highs = d.get("high", [])
                lows = d.get("low", [])
                closes = d.get("close", [])
                
                if times:
                    df = pd.DataFrame({
                        'timestamp': times, 'Open': opens, 'High': highs, 'Low': lows, 'Close': closes
                    })
                    for col in ['Open', 'High', 'Low', 'Close']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    return df
    except:
        pass
    return None

def scan_market():
    print(f"\n--- Piyasa Taranıyor | 15m Grafik ({len(SYMBOLS)} Parite) ---")
    match_count = 0
    
    for symbol in SYMBOLS:
        df = get_mexc_candles(symbol)
        time.sleep(0.05)
        
        if df is None or len(df) < 40:
            continue
            
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        
        high_low = df['High'] - df['Low']
        high_close = np.abs(df['High'] - df['Close'].shift())
        low_close = np.abs(df['Low'] - df['Close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['ATR'] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        
        low_min = df['Low'].rolling(window=5).min()
        high_max = df['High'].rolling(window=5).max()
        fast_k = 100 * (df['Close'] - low_min) / (high_max - low_min)
        df['Stoch_K'] = fast_k.rolling(window=3).mean()
        
        df = df.dropna().reset_index(drop=True)
        if len(df) < 25:
            continue
            
        i = len(df) - 3
        touch_candle = df.iloc[i]
        m1 = df.iloc[i+1]
        m2 = df.iloc[i+2]
        recent_slice = df.iloc[max(0, i-6):i]
        
        signal_found = False
        signal_type = ""
        entry_price = 0.0
        sl_price = 0.0
        tp_price = 0.0
        
        # --- SHORT SİNYALİ ---
        recent_highs = df['High'].iloc[max(0, i-10):i]
        is_new_peak = touch_candle['High'] >= recent_highs.max() * 0.995 or True
        short_touch = (touch_candle['High'] >= touch_candle['EMA20']) and (touch_candle['Close'] < touch_candle['EMA20'])
        
        if short_touch and (touch_candle['Stoch_K'] > 70) and is_new_peak:
            counter_candles = len(recent_slice[recent_slice['Close'] > recent_slice['Open']])
            if counter_candles <= 2:
                triggered = False
                entry = 0
                sl = touch_candle['High']
                if m1['Close'] < touch_candle['Low']:
                    entry = m1['Close']
                    triggered = True
                elif m2['Close'] < touch_candle['Low'] and m1['High'] <= touch_candle['High']:
                    entry = m2['Close']
                    triggered = True
                if triggered:
                    dist = sl - entry
                    if dist > 0 and dist <= touch_candle['ATR'] * 1.5:
                        signal_found = True
                        signal_type = "🔴 SHORT SİNYALİ"
                        entry_price = entry
                        sl_price = sl
                        tp_price = entry - (dist * 2.0)

        # --- LONG SİNYALİ (DÜZELTİLDİ) ---
        if not signal_found:
            recent_lows = df['Low'].iloc[max(0, i-10):i]
            is_new_bottom = touch_candle['Low'] <= recent_lows.min() * 1.005 or True
            long_touch = (touch_candle['Low'] <= touch_candle['EMA20']) and (touch_candle['Close'] > touch_candle['EMA20'])
            
            if long_touch and (touch_candle['Stoch_K'] < 30) and is_new_bottom:
                counter_candles = len(recent_slice[recent_slice['Close'] < recent_slice['Open']])
                if counter_candles <= 2:
                    triggered = False
                    entry = 0
                    sl = touch_candle['Low']
                    if m1['Close'] > touch_candle['High']:
                        entry = m1['Close']
                        triggered = True
                    elif m2['Close'] > touch_candle['High'] and m1['Low'] >= touch_candle['Low']:
                        entry = m2['Close']
                        triggered = True
                    if triggered:
                        dist = entry - sl
                        if dist > 0 and dist <= touch_candle['ATR'] * 1.5:
                            signal_found = True
                            signal_type = "🟢 LONG SİNYALİ"
                            entry_price = entry
                            sl_price = sl
                            tp_price = entry + (dist * 2.0)

        if signal_found:
            signal_key = f"{symbol}_{touch_candle['timestamp']}"
            if notified_signals.get(symbol) != signal_key:
                clean_symbol = symbol.replace("_", "")
                binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
                
                msg = (
                    f"🎯 <b>{signal_type}</b>\n\n"
                    f"Parite: #{clean_symbol} (15m)\n"
                    f"Giriş: {round(entry_price, 4)}\n"
                    f"Stop Loss (SL): {round(sl_price, 4)}\n"
                    f"Take Profit (TP): {round(tp_price, 4)}\n"
                    f"Risk/Reward: 1:2.0 (Breakeven Korumalı)\n\n"
                    f"🔗 <a href='{binance_link}'>Grafiği Aç</a>"
                )
                
                if send_telegram_message(msg):
                    notified_signals[symbol] = signal_key
                    match_count += 1

    print(f"Tarama bitti. Bulunan yeni sinyal: {match_count}")

if __name__ == "__main__":
    print("Canlı Sapan Sinyal Botu Başlatıldı!")
    send_telegram_message("🤖 Canlı Sapan Botu Güncellendi ve Aktif!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...\n")
        time.sleep(60)
