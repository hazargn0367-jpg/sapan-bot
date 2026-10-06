import time
import requests
import numpy as np

# --- AYARLAR ---
# Telegram bildirimleri için kendi Telegram Bot Token ve Chat ID'ni buraya yaz
TELEGRAM_BOT_TOKEN = "BURAYA_BOT_TOKEN_YAZ"
TELEGRAM_CHAT_ID = "BURAYA_CHAT_ID_YAZ"

def send_telegram_message(message):
    """Telegram üzerinden sinyal gönderir"""
    if "BURAYA" in TELEGRAM_BOT_TOKEN:
        print(f"[Telegram Simülasyonu]: {message}")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

def get_common_futures_symbols():
    """Binance ve MEXC'de ortak olan aktif USDT vadeli pariteleri bulur"""
    try:
        # 1. Binance'deki aktif vadeli pariteleri çek
        binance_url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        b_resp = requests.get(binance_url, timeout=10).json()
        binance_symbols = {
            s['symbol'] for s in b_resp['symbols'] 
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING'
        }
        
        # 2. MEXC'deki aktif vadeli pariteleri çek
        mexc_url = "https://contract.mexc.com/api/v1/contract/detail"
        m_resp = requests.get(mexc_url, timeout=10).json()
        mexc_symbols = {
            item['symbol'].replace('_', '') for item in m_resp['data'] 
            if item.get('quoteCoin') == 'USDT' and item.get('state') == 0
        }
        
        # 3. İki borsada da ortak olanları kesiştir
        common_symbols = list(binance_symbols.intersection(mexc_symbols))
        common_symbols.sort()
        return common_symbols
    except Exception as e:
        print(f"Pariteler eşitlenirken hata oluştu: {e}")
        return []

def get_mexc_klines(symbol, interval="1h", limit=100):
    """MEXC altyapısını kullanarak mum verilerini (kline) çeker"""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=10).json()
        if response.get("success") and "data" in response:
            data = response["data"]
            # MEXC kline verisi genelde [zaman, açık, yüksek, düşük, kapanış, hacim] şeklindedir
            closes = [float(x[4]) for x in data]
            return closes
    except Exception as e:
        print(f"{symbol} veri çekme hatası: {e}")
    return []

def calculate_ema(data, period):
    """Üstel Hareketli Ortalama (EMA) hesaplar"""
    return np.convolve(data, np.ones(period), 'valid') / period # Basitleştirilmiş EMA/SMA mantığı

def scan_market():
    """Piyasayı tarar ve Sapan sinyallerini arar"""
    print("Bot Taranıyor... Binance ve MEXC ortak pariteleri güncelleniyor.")
    pairs = get_common_futures_symbols()
    total_pairs = len(pairs)
    print(f"Toplam {total_pairs} Ortak Parite Taramaya Dahil Edildi.")
    
    signal_count = 0
    
    for index, symbol in enumerate(pairs, 1):
        closes = get_mexc_klines(symbol, interval="1h", limit=50)
        if len(closes) < 20:
            continue
            
        # Basit EMA Trend Mantığı (Örnek Strateji Kontrolü)
        # Kendi EMA mantığını buraya entegre edebilirsin
        ema_fast = np.mean(closes[-9:])
        ema_slow = np.mean(closes[-21:])
        
        # Sinyal Koşulu Örneği (Örn: Hızlı EMA Yavaş EMA'yı yukarı kestiğinde)
        if ema_fast > ema_slow:
            signal_count += 1
            signal_msg = f"🟢 Temiz Sapan Sinyali: {symbol}"
            print(signal_msg)
            send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen: {total_pairs}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖNGÜ ---
if __name__ == "__main__":
    print("Sapan Bot başarıyla başlatıldı ve 7/24 moda geçti.")
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        # Her tarama bittikten sonra 60 saniye bekleyip tekrar tarar
        print("Yeni tarama için bekleniyor...")
        time.sleep(60)
