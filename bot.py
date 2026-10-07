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
    "TNSRUSDT", "OMUSDT", "SUIUSDT", "REZUSDT", "BBUSDT", "NOTUSDT", "IOUSDT",
    "ZKUSDT", "LISTAUSDT", "ZROUSDT", "BANANAUSDT", "RENDERUSDT", "TONUSDT", "DOGSUSDT",
    "NEIROUSDT", "TURBOUSDT", "1000SATSUSDT", "1000RATSUSDT", "1000PEPEUSDT", "1000SHIBUSDT",
    "1000FLOKIUSDT", "1000BONKUSDT", "1000LUNCUSDT", "1000XECUSDT", "CHESSUSDT", "COTIUSDT",
    "DARUSDT", "DENTUSDT", "DGBUSDT", "EDUUSDT", "ELFUSDT", "ENJUSDT", "ENSUSDT",
    "FETUSDT", "FIROUSDT", "FLUXUSDT", "FTOUSDT", "FXSUSDT", "GLMRUSDT", "GMXUSDT",
    "GNSUSDT", "GOTUSDT", "HIFIUSDT", "HFTUSDT", "HIGHUSDT", "HOOKUSDT", "ICPUSDT",
    "IDUSDT", "ILVUSDT", "IMXUSDT", "INJUSDT", "IOSTUSDT", "IOTAUSDT", "IOTXUSDT",
    "JASMYUSDT", "JOEUSDT", "KASUSDT", "KAVAUSDT", "KEYUSDT", "KLAYUSDT", "KNCUSDT",
    "KSMUSDT", "LINAUSDT", "LITUSDT", "LOOKSUSDT", "LPTUSDT", "LQTYUSDT", " LRCUSDT",
    "MAGICUSDT", "MAVUSDT", "MDTUSDT", "MINAUSDT", "MKRUSDT", "MTLUSDT", "MULTIUSDT",
    "NEARUSDT", "NEOUSDT", "NKNUSDT", "OCEANUSDT", "OGNUSDT", "OMUSDT", "OPUSDT",
    "ORDIUSDT", "OXTUSDT", "PENDLEUSDT", "PHBUSDT", "PHAUSDT", "PIVXUSDT", "POLYXUSDT",
    "PPTUSDT", "QNTUSDT", "QTUMUSDT", "RADUSDT", "RAREUSDT", "REEFUSDT", "RENUSDT",
    "RLCUSDT", "ROSEUSDT", "RSRUSDT", "RUNEUSDT", "RVNUSDT", "SAFEUSDT", "SANDUSDT",
    "SCUSDT", "SCRTUSDT", "SKLUSDT", "SLPUSDT", "SNXUSDT", "SOCUSDT", "SSVUSDT",
    "STGUSDT", "STMXUSDT", "STORJUSDT", "STPTUSDT", "STRAXUSDT", "STXUSDT", "SUPERUSDT",
    "SUSHIUSDT", "SXPUSDT", "SYSUSDT", "TAOUSDT", "TRBUSDT", "TUSDT", "UFTUSDT",
    "UMAUSDT", "UNFIUSDT", "OCEANUSDT", "OGNUSDT", "OMUSDT", "OPUSDT", "ORDIUSDT"
]

# Listede olabilecek mükerrer (çift) kayıtları temizleyelim ve benzersiz yapalım
POPULAR_PAIRS = sorted(list(set(POPULAR_PAIRS)))

notified_signals = {}

def send_telegram_message(token, chat_id, message):
    """Telegram üzerinden HTML formatlı sinyal gönderir"""
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
    """Binance Futures API üzerinden 15 dakikalık mum verilerini çeker"""
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
        
        # EMA Hesaplamaları
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
        
        # Fark hesapları ve genişleme filtreleri
        diff_20_50 = ema20 - ema50
        diff_50_100 = ema50 - ema100
        
        is_bullish_aligned = (ema20 > ema50) and (ema50 > ema100) and (ema100 > ema200)
        is_bearish_aligned = (ema20 < ema50) and (ema50 < ema100) and (ema100 < ema200)
        
        is_bullish_expanded = (diff_20_50 > 0.003) and (diff_50_100 > 0.003)
        is_bearish_expanded = (diff_20_50 < -0.003) and (diff_50_100 < -0.003)
        
        # EMA 20 Temas Şartı
        ema20_touch = (low <= ema20 <= high)
        
        # Tepe / Dip Kırılım Analizi
        recent_candles = df.iloc[-12:-1]
        prev_candles = df.iloc[-35:-12]
        
        recent_max_high = recent_candles["high"].max()
        previous_max_high = prev_candles["high"].max()
        
        recent_min_low = recent_candles["low"].min()
        previous_min_low = prev_candles["low"].min()
        
        valid_bullish_breakout = is_bullish_aligned and is_bullish_expanded and (recent_max_high > previous_max_high * 1.004)
        valid_bearish_breakout = is_bearish_aligned and is_bearish_expanded and (recent_min_low < previous_min_low * 0.996)
        
        if ema20_touch and (valid_bullish_breakout or valid_bearish_breakout):
            signal_key = f"{symbol}_{candle_timestamp}"
            if notified_signals.get(symbol) == signal_key:
                continue
                
            clean_symbol = symbol.replace("_", "")
            binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
            
            if valid_bullish_breakout:
                trend_type = "KATI SAPAN LONG (NET HH KIRILIMI)"
                desc = f"Fiyat yeni yüksek tepe ({recent_max_high}) yaptıktan sonra EMA20 desteğine çekildi!"
            else:
                trend_type = "KATI SAPAN SHORT (NET LL KIRILIMI)"
                desc = f"Fiyat yeni düşük dip ({recent_min_low}) yaptıktan sonra EMA20 direncine çekildi!"
                
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
    print("Genişletilmiş Sapan Botu başarıyla başlatıldı!")
    send_telegram_message(BOT_TOKEN, CHAT_ID, "🤖 Genişletilmiş Sapan Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
