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

def get_binance_klines(symbol, interval="1h", limit=250):
    """Binance Futures API üzerinden detaylı mum verilerini çeker"""
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
    """Piyasayı tarar ve EMA 20-50-100-200 trendi üstünde EMA 20'ye düzeltme (temas) anını yakalar"""
    print("\n--- EMA Trend & Pullback (EMA 20 Temas) Taranıyor ---")
    total_pairs = len(POPULAR_PAIRS)
    print(f"Toplam {total_pairs} Parite Tarama İşlemine Alındı.")
    
    signal_count = 0
    checked_count = 0
    
    for symbol in POPULAR_PAIRS:
        df = get_binance_klines(symbol, interval="1h", limit=250)
        time.sleep(0.02)
        
        if df is None or len(df) < 210:
            continue
            
        checked_count += 1
        
        # 20, 50, 100, 200 EMA Hesaplamaları
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
        df['ema100'] = df['close'].ewm(span=100, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        
        current = df.iloc[-1]
        prev = df.iloc[-2]
        
        # 1. Paralel Yükseliş Trendi Şartı (20 > 50 > 100 > 200)
        is_bullish_trend = (
            (current['ema20'] > current['ema50']) and 
            (current['ema50'] > current['ema100']) and 
            (current['ema100'] > current['ema200']) and
            (prev['ema20'] > prev['ema50']) # Trendin devam ettiğini doğrulamak için
        )
        
        if not is_bullish_trend:
            continue
            
        # 2. Düzeltme (Pullback) ve EMA 20'ye Değme Şartı
        # Mumun en düşük seviyesi (low) EMA 20'ye değmiş veya hafifçe içine girmiş olmalı
        # (Yani low <= ema20 ve high >= ema20)
        touched_ema20 = (current['low'] <= current['ema20']) and (current['high'] >= current['ema20'])
        
        if touched_ema20:
            signal_count += 1
            signal_msg = (
                f"🎯 **EMA 20 DÜZELTME (PULLBACK) SİNYALİ** 🎯\n"
                f"Parite: `{symbol}`\n"
                f"Fiyat (Low): `{current['low']}`\n"
                f"EMA 20: `{current['ema20']:.4f}`\n"
                f"Trend: 20 > 50 > 100 > 200 (Paralel Yükseliş)"
            )
            print(signal_msg)
            send_telegram_message(signal_msg)
            
    print(f"Tarama bitti. İşlenen: {checked_count}/{total_pairs} | Sinyal: {signal_count}")

# --- 7/24 ÇALIŞAN ANA DÖNGÜ ---
if __name__ == "__main__":
    print("EMA Trend Pullback Botu başarıyla başlatıldı!")
    send_telegram_message("🤖 EMA Trend Pullback Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
