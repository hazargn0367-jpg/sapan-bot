import sys
import time
import requests
import numpy as np

# Çıktıların log ekranına gecikmeden anında düşmesini sağlar
sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

def send_telegram_message(message):
    """Telegram üzerinden sinyal gönderir"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.json()
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

def get_common_futures_symbols():
    """Binance ve MEXC'de ortak olan aktif USDT vadeli pariteleri bulur"""
    try:
        print("Binance ve MEXC API'lerinden ortak pariteler çekiliyor...")
        
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
        print(f"Ortak parite tespiti başarılı. Toplam: {len(common_symbols)}")
        return common_symbols
    except Exception as e:
        print(f"Pariteler eşitlenirken hata oluştu: {e}")
        return []

def get_mexc_klines(symbol, interval="1h", limit=50):
    """MEXC altyapısını kullanarak mum verilerini (kline) çeker"""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=5).json()
        if response.get("success") and "data" in response:
            data = response["data"]
            closes = [float(x[4]) for x in data]
            return closes
    except Exception as e:
        # Tekil hataların tüm döngüyü bozmaması için sessizce geçiyoruz
        pass
    return []

def scan_market():
    """Piyasayı tarar ve sinyalleri Telegram'a bildirir"""
    print("\n--- Bot Taranıyor ---")
    pairs = get_common_futures_symbols()
    if not pairs:
        print("Taranacak ortak parite bulunamadı, bekleniyor...")
        return
        
    total_pairs = len(pairs)
    print(f"Toplam {total_pairs} Ortak Parite Tarama İşlemine Alındı.")
    
    signal_count = 0
    
    for index, symbol in enumerate(pairs, 1):
        closes = get_mexc_klines(symbol, interval="1h", limit=50)
        
        # API rate-limit ve takılmaları önlemek için çok kısa bir es veriyoruz
        time.sleep(0.05)
        
        if len(closes) < 20:
            continue
            
        # Basit EMA Trend Kontrolü
        ema_fast = np.mean(closes[-9:])
        ema_slow = np.mean(closes[-21:])
        
        if ema_fast > ema_slow:
            signal_count += 1
            signal_msg = f"🟢 Temiz Sapan Sinyali: {symbol}"
            print(signal_msg)
            send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen: {total_pairs}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖNGÜ ---
if __name__ == "__main__":
    print("Sapan Bot başarıyla başlatıldı ve 7/24 döngüye girdi.")
    send_telegram_message("🤖 Sapan Bot başarıyla başlatıldı ve 7/24 ortak parite taramasına başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
