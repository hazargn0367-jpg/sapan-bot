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
        
        ema20 = current['ema20']
        ema50 = current['ema50']
        ema100 = current['ema100']
        ema200 = current['ema200']
        
        is_bullish_aligned = (ema20 > ema50) and (ema50 > ema100) and (ema100 > ema200)
        is_bearish_aligned = (ema20 < ema50) and (ema50 < ema100) and (ema100 < ema200)
        
        diff_20_50 = ema20 - ema50
        diff_50_100 = ema50 - ema100
        is_bullish_expanded = (diff_20_50 > 0.003) and (diff_50_100 > 0.003)
        is_bearish_expanded = (diff_20_50 < -0.003) and (diff_50_100 < -0.003)
        
        ema20_touch = (current['low'] <= ema20 <= current['high'])
        
        if not ema20_touch:
            continue
            
        # GERÇEK SWING (DALGA) ANALİZİ
        history = df.iloc[-40:-1].copy()
        
        # Yerel dip tespiti: Bir mumun düşük değeri, önceki 2 ve sonraki 1 mumdan düşükse yerel diptir.
        history['is_swing_low'] = (history['low'] < history['low'].shift(1)) & \
                                  (history['low'] < history['low'].shift(2)) & \
                                  (history['low'] < history['low'].shift(-1))
                                  
        # Yerel tepe tespiti
        history['is_swing_high'] = (history['high'] > history['high'].shift(1)) & \
                                   (history['high'] > history['high'].shift(2)) & \
                                   (history['high'] > history['high'].shift(-1))
                                   
        swing_lows = history[history['is_swing_low']]
        swing_highs = history[history['is_swing_high']]
        
        valid_bullish_breakout = False
        desc_long = ""
        
        if is_bullish_aligned and is_bullish_expanded and not swing_highs.empty:
            last_sh = swing_highs.iloc[-1]
            if len(swing_highs) >= 2:
                prev_sh = swing_highs.iloc[-2]
                # Son tepenin GÖVDESİ, önceki tepenin FİTİLİNİ geçmek ZORUNDA
                if last_sh['close'] > prev_sh['high']:
                    valid_bullish_breakout = True
                    desc_long = f"Fiyat önceki tepeyi ({prev_sh['high']}) GÖVDE ile kırdı ({last_sh['close']}) ve EMA20'ye çekildi."
            else:
                prev_high = history.loc[:last_sh.name - 1, 'high'].max()
                if pd.notna(prev_high) and last_sh['close'] > prev_high:
                    valid_bullish_breakout = True
                    desc_long = f"Fiyat uzun süreli tepeyi ({prev_high}) GÖVDE ile kırdı ({last_sh['close']}) ve EMA20'ye çekildi."

        valid_bearish_breakout = False
        desc_short = ""
        
        if is_bearish_aligned and is_bearish_expanded and not swing_lows.empty:
            last_sl = swing_lows.iloc[-1]
            if len(swing_lows) >= 2:
                prev_sl = swing_lows.iloc[-2]
                # Son dibin GÖVDESİ, önceki dibin FİTİLİNİ aşağı kırmak ZORUNDA (TAO destek senaryosunu eler)
                if last_sl['close'] < prev_sl['low']:
                    valid_bearish_breakout = True
                    desc_short = f"Fiyat önceki dibi ({prev_sl['low']}) GÖVDE ile aşağı kırdı ({last_sl['close']}) ve EMA20'ye tepki verdi."
            else:
                prev_low = history.loc[:last_sl.name - 1, 'low'].min()
                if pd.notna(prev_low) and last_sl['close'] < prev_low:
                    valid_bearish_breakout = True
                    desc_short = f"Fiyat uzun süreli dibi ({prev_low}) GÖVDE ile aşağı kırdı ({last_sl['close']}) ve EMA20'ye tepki verdi."
        
        if valid_bullish_breakout or valid_bearish_breakout:
            signal_key = f"{symbol}_{candle_timestamp}"
            if notified_signals.get(symbol) == signal_key:
                continue
                
            clean_symbol = symbol.replace("_", "")
            binance_link = f"https://www.binance.com/tr/futures/{clean_symbol}"
            
            if valid_bullish_breakout:
                trend_type = "🟢 KUSURSUZ SAPAN LONG (GÖVDE ONAYLI HH)"
                desc = desc_long
            else:
                trend_type = "🔴 KUSURSUZ SAPAN SHORT (GÖVDE ONAYLI LL)"
                desc = desc_short
                
            message = (
                f"🎯 <b>SAPAN STRATEJİSİ SİNYALİ!</b>\n\n"
                f"Parite: #{clean_symbol} (15m Futures)\n"
                f"Sinyal: {trend_type}\n"
                f"Anlık Fiyat: {current['close']}\n\n"
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
    print("Gövde Kapanışlı Kusursuz Sapan Botu başarıyla başlatıldı!")
    send_telegram_message(BOT_TOKEN, CHAT_ID, "🤖 Kapanış Onaylı Kusursuz Sapan Botu aktif ve taramaya başladı!")
    
    while True:
        try:
            scan_market()
        except Exception as e:
            print(f"Ana döngü hatası: {e}")
        
        print("Yeni tarama için 60 saniye bekleniyor...")
        time.sleep(60)
