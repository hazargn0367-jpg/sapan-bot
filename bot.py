import sys
import time
import requests
import pandas as pd
import numpy as np

# Çıktıların log ekranına gecikmeden anında düşmesini sağlar
sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
CHAT_ID = "1494316515"

# En hacimli 250+ Binance Futures paritesi
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
    "ORCAUSDT", "ACEUSDT", "TIAUSDT", "ONDOUSDT", "POLUSDT", "BOMEUSDT", "SAGAUSDT",
    "TNSRUSDT", "OMUSDT", "REZUSDT", "LISTAUSDT", "ZROUSDT", "BANANAUSDT", "TONUSDT",
    "DOGSUSDT", "NEIROUSDT", "TURBOUSDT", "1000SATSUSDT", "1000RATSUSDT", "1000PEPEUSDT",
    "1000SHIBUSDT", "1000FLOKIUSDT", "1000BONKUSDT", "1000LUNCUSDT", "1000XECUSDT",
    "CHESSUSDT", "COTIUSDT", "DARUSDT", "DENTUSDT", "DGBUSDT", "EDUUSDT", "ELFUSDT",
    "ENSUSDT", "FIROUSDT", "FLUXUSDT", "FTOUSDT", "FXSUSDT", "GLMRUSDT", "GMXUSDT",
    "GNSUSDT", "GOTUSDT", "HIFIUSDT", "HFTUSDT", "ILVUSDT", "IOSTUSDT", "IOTAUSDT",
    "IOTXUSDT", "JASMYUSDT", "JOEUSDT", "KASUSDT", "KEYUSDT", "KLAYUSDT", "KNCUSDT",
    "LINAUSDT", "LITUSDT", "LOOKSUSDT", "LPTUSDT", "LQTYUSDT", "LRCUSDT", "MAGICUSDT",
    "MDTUSDT", "MKRUSDT", "MTLUSDT", "MULTIUSDT", "NEOUSDT", "NKNUSDT", "OGNUSDT",
    "OXTUSDT", "PHBUSDT", "PHAUSDT", "PIVXUSDT", "POLYXUSDT", "PPTUSDT", "QTUMUSDT",
    "RADUSDT", "RAREUSDT", "REEFUSDT", "RENUSDT", "RLCUSDT", "ROSEUSDT", "RSRUSDT",
    "RVNUSDT", "SAFEUSDT", "SCUSDT", "SCRTUSDT", "SKLUSDT", "SLPUSDT", "SOCUSDT",
    "SSVUSDT", "STGUSDT", "STMXUSDT", "STORJUSDT", "STPTUSDT", "STRAXUSDT", "SUPERUSDT",
    "SUSHIUSDT", "SXPUSDT", "SYSUSDT", "TAOUSDT", "TRBUSDT", "TUSDT", "UFTUSDT",
    "UMAUSDT", "UNFIUSDT"
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
        response = requests.post(url, json=payload, timeout=5)
        return response.status_code == 200
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")
        return False

def get_binance_klines(symbol, interval="15m", limit=100):
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
                df['open'] = df['open'].astype(float)
                df['high'] = df['high'].astype(float)
                df['low'] = df['low'].astype(float)
                df['close'] = df['close'].astype(float)
                return df
    except Exception:
        pass
    return None

def scan_market():
    print(f"\n--- Genişletilmiş Piyasa Taranıyor (Toplam Parite: {len(POPULAR_PAIRS)}) ---")
    success_count = 0
    match_count = 0
    
    for symbol in POPULAR_PAIRS:
        df = get_binance_klines(symbol, interval="15m", limit=100)
        time.sleep(0.02)
        
        if df is None or len(df) < 50:
            continue
            
        success_count += 1
        
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        current = df.iloc[-1]
        candle_timestamp = current['timestamp']
        low = current['low']
        high = current['high']
        current_close = current['close']
        
        ema20 = current['ema20']
        ema50 = current['ema50']
        ema100 = current['ema100']
        ema200 = current['ema200']
        
        diff_20_50 = ema20 - ema50
        diff_50_100 = ema50 - ema100
        
        is_bullish_aligned = (ema20 > ema50) and (ema50 > ema100) and (ema100 > ema200)
        is_bearish_aligned = (ema20 < ema50) and (ema50 < ema100) and (ema100 < ema200)
        
        is_bullish_expanded = (diff_20_50 > 0.003) and (diff_50_100 > 0.003)
        is_bearish_expanded = (diff_20_50 < -0.003) and (diff_50_100 < -0.003)
        
        ema20_touch = (low <= ema20 <= high)
        
        recent_candles = df.iloc[-12:-1]
        prev_candles = df.iloc[-35:-12]
        
        # ESKİ SİSTEM: Sadece iğnelere (high/low) bakıyordu.
        # YENİ SİSTEM: Kırılımın iğne değil, KAPANIS (close) ile onaylanmasını zorunlu kıldım.
        previous_max_high = prev_candles["high"].max() # Önceki zirve iğnesi
        previous_min_low = prev_candles["low"].min()   # Önceki dip iğnesi
        
        recent_max_close = recent_candles["close"].max() # Yeni hareketin en yüksek mum kapanışı
        recent_min_close = recent_candles["close"].min() # Yeni hareketin en düşük mum kapanışı
        
        # Bullish: Kapanış, önceki zirvenin fitilini bile geçmiş olmalı (Sağlam HH)
        valid_bullish_breakout = is_bullish_aligned and is_bullish_expanded and (recent_max_close > previous_max_high)
        
        # Bearish: Kapanış, önceki dibin fitilinden bile aşağıda olmalı (Sağlam LL)
        valid_bearish_breakout = is_bearish_aligned and is_bearish_expanded and (recent_min_close < previous_min_low)
        
        if ema20_touch and (valid_bullish_breakout or valid_bearish_breakout):
            signal_key = f"{symbol}_{candle_timestamp}"
            if notified_signals.get(symbol) == signal_key:
                continue
                
            clean_symbol = symbol.replace("_", "")
            binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
            
            if valid_bullish_breakout:
                trend_type = "KATI SAPAN LONG (GÖVDE KAPANIŞLI HH)"
                desc = f"Fiyat önceki tepeyi ({previous_max_high}) GÖVDE ile kırdı ({recent_max_close}) ve EMA20 desteğine çekildi!"
            else:
                trend_type = "KATI SAPAN SHORT (GÖVDE KAPANIŞLI LL)"
                desc = f"Fiyat önceki dibi ({previous_min_low}) GÖVDE ile kırdı ({recent_min_close}) ve EMA20 direncine çekildi!"
                
            message = (
                f"🏹 <b>SAPAN STRATEJİSİ SİNYALİ!</b>\n\n"
                f"Parite: #{clean_symbol} (15m Futures)\n"
                f"Sinyal: {trend_type}\n"
                f"Anlık Fiyat: {current_close}\n\n"
                f"📊 <b>EMA Değerleri:</b>\n"
                f"• EMA 20: {round(ema20, 4)}\n"
                f"• EMA 50: {round(ema50, 4)}\n"
                f"• EMA 100: {round(ema100, 4)}\n"
                f"• EMA 200: {round(ema200, 4)}\n\n"
                f"💡 <b>Açıklama:</b> {desc}\n\n"
                f"🔗 <a href='{binance_link}'>Grafiği Tarayıcıda Aç</a>"
            )
            
            if send_telegram_message(BOT_TOKEN, CHAT_ID, message):
                notified_signals[symbol] = signal_key
                match_count += 1
                
    print(f"Tarama tamamlandı. İşlenen: {success_count} | Sinyal: {match_count}")

if __name__ == "__main__":
    print("Gövde Kapanışlı Sapan Botu başarıyla başlatıldı!")
    send_telegram_message(BOT_TOKEN, CHAT_ID, "🤖 Kapanış Onaylı Sapan Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
