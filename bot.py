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
    print(f"\n--- Saf Sapan Taranıyor | Parite: {len(POPULAR_PAIRS)} ---")
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
        
        df = df.dropna().reset_index(drop=True)
        if len(df) < 25:
            continue
            
        i = len(df) - 3
        if i < 20:
            continue
            
        touch_candle = df.iloc[i]
        m1 = df.iloc[i+1]
        m2 = df.iloc[i+2]
        candle_timestamp = touch_candle['timestamp']
        
        valid_signal = False
        trend_type = ""
        entry_price = 0.0
        desc = ""
        
        # --- SHORT KOŞULU (Yeni Tepe Sonrası EMA20 Teması) ---
        recent_highs = df['high'].iloc[max(0, i-10):i]
        is_new_peak = touch_candle['high'] >= recent_highs.max() * 0.995 or recent_highs.idxmax() < i - 2
        short_touch = (touch_candle['high'] >= touch_candle['ema20']) and (touch_candle['close'] < touch_candle['ema20'])
        
        if short_touch and is_new_peak:
            triggered = False
            entry = 0
            if m1['close'] < touch_candle['low']:
                entry = m1['close']
                triggered = True
            elif m2['close'] < touch_candle['low'] and m1['high'] <= touch_candle['high']:
                entry = m2['close']
                triggered = True
            
            if triggered:
                valid_signal = True
                trend_type = "SAPAN SHORT SİNYALİ"
                entry_price = entry
                desc = "Yükseliş sonrası yeni tepe yapıldı ve düzeltmeyle EMA20'ye ilk temas geldi."

        # --- LONG KOŞULU (Yeni Dip Sonrası EMA20 Teması) ---
        if not valid_signal:
            recent_lows = df['low'].iloc[max(0, i-10):i]
            is_new_bottom = touch_candle['low'] <= recent_lows.min() * 1.005 or recent_lows.idxmin() < i - 2
            long_touch = (touch_candle['low'] <= touch_candle['ema20']) and (touch_candle['close'] > touch_candle['ema20'])
            
            if long_touch and is_new_bottom:
                triggered = False
                entry = 0
                if m1['close'] > touch_candle['high']:
                    entry = m1['close']
                    triggered = True
                elif m2['close'] > touch_candle['high'] and m1['low'] >= touch_candle['low']:
                    entry = m2['close']
                    triggered = True
                
                if triggered:
                    valid_signal = True
                    trend_type = "SAPAN LONG SİNYALİ"
                    entry_price = entry
                    desc = "Düşüş sonrası yeni dip yapıldı ve düzeltmeyle EMA20'ye ilk temas geldi."

        if valid_signal:
            signal_key = f"{symbol}_{candle_timestamp}"
            if notified_signals.get(symbol) == signal_key:
                continue
                
            clean_symbol = symbol.replace("_", "")
            binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
            
            message = (
                f"🏹 <b>{trend_type}</b>\n\n"
                f"Parite: #{clean_symbol} (15m Futures)\n"
                f"Temas / Giriş Fiyatı: {round(entry_price, 4)}\n\n"
                f"💡 <b>Detay:</b> {desc}\n\n"
                f"🔗 <a href='{binance_link}'>Grafiği Binance'te Aç</a>"
            )
            
            if send_telegram_message(BOT_TOKEN, CHAT_ID, message):
                notified_signals[symbol] = signal_key
                match_count += 1
                
    print(f"Tarama tamamlandı. İşlenen: {success_count} | Sinyal: {match_count}")

if __name__ == "__main__":
    print("Saf Sapan Botu Başlatıldı!")
    send_telegram_message(BOT_TOKEN, CHAT_ID, "🤖 Saf Sapan Sinyal Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
