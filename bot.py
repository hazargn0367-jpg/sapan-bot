import sys
import time
import requests
import numpy as np

# Çıktıların log ekranına gecikmeden anında düşmesini sağlar
sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

# Doğrudan en popüler ve aktif ortak pariteler (Hızlı ve garantili tarama için)
POPULAR_PAIRS = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", 
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "LTCUSDT", "UNIUSDT", "ATOMUSDT",
    "ETCUSDT", "XLMUSDT", "NEARUSDT", "APTUSDT", "FTMUSDT", "ALGOUSDT", "QNTUSDT",
    "VETUSDT", "ICPUSDT", "FILUSDT", "GRTUSDT", "SANDUSDT", "MANAUSDT", "AXSUSDT",
    "CHZUSDT", "EOSUSDT", "AAVEUSDT", "THETAUSDT", "EGLDUSDT", "XTZUSDT", "CAKEUSDT",
    "CRVUSDT", "SNXUSDT", "ENJUSDT", "BATUSDT", "ZILUSDT", "KSMUSDT", "RUNEUSDT"
]

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

def get_mexc_klines(symbol, interval="1h", limit=50):
    """MEXC altyapısını kullanarak mum verilerini çeker (Alt çizgili format)"""
    # MEXC formatı için USDT önüne alt çizgi ekliyoruz (Örn: BTC_USDT)
    mexc_raw = symbol.replace("USDT", "_USDT")
    url = f"https://contract.mexc.com/api/v1/contract/kline/{mexc_raw}?interval={interval}&limit={limit}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get("success") and "data" in res_json:
                data = res_json["data"]
                closes = []
                for x in data:
                    if isinstance(x, list) and len(x) > 4:
                        closes.append(float(x[4]))
                return closes
    except Exception:
        pass
    return []

def scan_market():
    """Piyasayı tarar ve sinyalleri Telegram'a bildirir"""
    print("\n--- Popüler Pariteler Taranıyor ---")
    total_pairs = len(POPULAR_PAIRS)
    print(f"Toplam {total_pairs} Parite Tarama İşlemine Alındı.")
    
    signal_count = 0
    checked_count = 0
    
    for symbol in POPULAR_PAIRS:
        closes = get_mexc_klines(symbol, interval="1h", limit=50)
        time.sleep(0.05)
        
        if len(closes) < 21:
            continue
            
        checked_count += 1
        
        # Basit EMA Trend Kontrolü
        ema_fast = np.mean(closes[-9:])
        ema_slow = np.mean(closes[-21:])
        
        if ema_fast > ema_slow:
            signal_count += 1
            signal_msg = f"🟢 Sapan Sinyali: {symbol} (Fast: {ema_fast:.4f} > Slow: {ema_slow:.4f})"
            print(signal_msg)
            send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen: {checked_count}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖNGÜ ---
if __name__ == "__main__":
    print("Sapan Bot başarıyla başlatıldı ve 7/24 döngüye girdi.")
    send_telegram_message("🤖 Sapan Bot başarıyla başlatıldı ve 7/24 popüler parite taramasına başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
