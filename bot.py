import sys
import time
import requests
import pandas as pd
import numpy as np

# Çıktıların log ekranına gecikmeden anında düşmesini sağlar
sys.stdout.reconfigure(line_buffering=True)

# --- TELEGRAM AYARLARI ---
TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

# En hacimli 100 parite
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
    "XAIUSDT", "ALTUSDT"
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

def get_binance_klines(symbol, interval="15m", limit=250):
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
    """15m periyotta trend, düzeltme ve EMA 20 temaslarını iki yönlü tarar"""
    print("\n--- 15m Çift Yönlü EMA 20 Pullback Taranıyor ---")
    total_pairs = len(POPULAR_PAIRS)
    print(f"Toplam {total_pairs} Parite Tarama İşlemine Alındı.")
    
    signal_count = 0
    checked_count = 0
    
    for symbol in POPULAR_PAIRS:
        df = get_binance_klines(symbol, interval="15m", limit=250)
        time.sleep(0.02)
        
        if df is None or len(df) < 210:
            continue
            
        checked_count += 1
        
        # EMA Hesaplamaları
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        current = df.iloc[-1]
        ema_val = current['ema20']
        
        # --- 1. YÜKSELİŞ (LONG) TRENDİ & PULLBACK ---
        is_bullish_trend = (
            (current['ema20'] > current['ema50']) and 
            (current['ema50'] > current['ema100']) and 
            (current['ema100'] > current['ema200'])
        )
        
        if is_bullish_trend:
            recent_high = df['high'].iloc[-6:-1].max()
            if current['close'] < recent_high:
                # EMA 20 Temas Kontrolü (Low seviyesi EMA 20'ye değiyor)
                if (current['low'] <= ema_val * 1.002) and (current['high'] >= ema_val * 0.998):
                    signal_count += 1
                    signal_msg = (
                        f"🟢 **15m YÜKSELİŞ (LONG) EMA 20 TEMAS** 🟢\n"
                        f"Parite: `{symbol}`\n"
                        f"Mum Düşük (Low): `{current['low']}`\n"
                        f"EMA 20: `{ema_val:.4f}`\n"
                        f"Durum: Boğa trendinde tepe sonrası düzeltme!"
                    )
                    print(signal_msg)
                    send_telegram_message(signal_msg)
                    continue

        # --- 2. DÜŞÜŞ (SHORT) TRENDİ & PULLBACK ---
        is_bearish_trend = (
            (current['ema20'] < current['ema50']) and 
            (current['ema50'] < current['ema100']) and 
            (current['ema100'] < current['ema200'])
        )
        
        if is_bearish_trend:
            recent_low = df['low'].iloc[-6:-1].min()
            if current['close'] > recent_low:
                # EMA 20 Temas Kontrolü (High seviyesi EMA 20'ye değiyor)
                if (current['high'] >= ema_val * 0.998) and (current['low'] <= ema_val * 1.002):
                    signal_count += 1
                    signal_msg = (
                        f"🔴 **15m DÜŞÜŞ (SHORT) EMA 20 TEMAS** 🔴\n"
                        f"Parite: `{symbol}`\n"
                        f"Mum Yüksek (High): `{current['high']}`\n"
                        f"EMA 20: `{ema_val:.4f}`\n"
                        f"Durum: Ayı trendinde dip sonrası tepki!"
                    )
                    print(signal_msg)
                    send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen: {checked_count}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖNGÜ ---
if __name__ == "__main__":
    print("15m Çift Yönlü Pullback Botu başarıyla başlatıldı!")
    send_telegram_message("🤖 15m Çift Yönlü Pullback Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
