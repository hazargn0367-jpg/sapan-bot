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
    """Binance ve MEXC'de ortak olan aktif vadeli pariteleri bulur"""
    try:
        print("Binance ve MEXC API'lerinden ortak pariteler çekiliyor...")
        
        # 1. Binance vadeli pariteleri
        binance_url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
        b_resp = requests.get(binance_url, timeout=10).json()
        binance_symbols = {
            s['symbol'] for s in b_resp['symbols'] 
            if s['contractType'] == 'PERPETUAL' and s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING'
        }
        
        # 2. MEXC vadeli pariteleri
        mexc_url = "https://contract.mexc.com/api/v1/contract/detail"
        m_resp = requests.get(mexc_url, timeout=10).json()
        
        mexc_dict = {}
        for item in m_resp.get('data', []):
            if item.get('quoteCoin') == 'USDT' and item.get('state') == 0:
                raw_symbol = item['symbol'] # Örn: BTC_USDT
                clean_symbol = raw_symbol.replace('_', '') # Örn: BTCUSDT
                mexc_dict[clean_symbol] = raw_symbol
                
        common_clean = binance_symbols.intersection(set(mexc_dict.keys()))
        
        valid_pairs = []
        for sym in common_clean:
            valid_pairs.append({
                "clean": sym,
                "mexc_raw": mexc_dict[sym]
            })
            
        valid_pairs = sorted(valid_pairs, key=lambda x: x['clean'])
        print(f"Ortak parite tespiti başarılı. Toplam: {len(valid_pairs)}")
        return valid_pairs
    except Exception as e:
        print(f"Pariteler eşitlenirken hata oluştu: {e}")
        return []

def get_mexc_klines(mexc_raw_symbol, interval="1h", limit=50):
    """MEXC kline verisini güvenli şekilde çeker"""
    url = f"https://contract.mexc.com/api/v1/contract/kline/{mexc_raw_symbol}?interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success") and "data" in res_json:
                data = res_json["data"]
                # MEXC futures kline veri yapısı kontrolü (liste içinde liste veya objeler olabilir)
                closes = []
                for x in data:
                    if isinstance(x, list) and len(x) > 4:
                        closes.append(float(x[4]))
                    elif isinstance(x, dict) and 'close' in x:
                        closes.append(float(x['close']))
                return closes
    except Exception:
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
    checked_count = 0
    
    for pair in pairs:
        clean_name = pair["clean"]
        mexc_raw = pair["mexc_raw"]
        
        closes = get_mexc_klines(mexc_raw, interval="1h", limit=50)
        time.sleep(0.04) # Rate limit koruması
        
        if len(closes) < 21:
            continue
            
        checked_count += 1
        
        # EMA Hesaplaması
        ema_fast = np.mean(closes[-9:])
        ema_slow = np.mean(closes[-21:])
        
        # Sapan stratejisi koşulu (Hızlı EMA Yavaş EMA'yı yukarı kestiğinde veya üstündeyken)
        if ema_fast > ema_slow:
            signal_count += 1
            signal_msg = f"🟢 Sapan Sinyali: {clean_name} (Fast EMA: {ema_fast:.4f} > Slow EMA: {ema_slow:.4f})"
            print(signal_msg)
            send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen/Başarılı: {checked_count}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖngÜ ---
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
