import sys
import functools
print = functools.partial(print, flush=True)

import requests
import pandas as pd
import numpy as np
import time
import datetime

SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "AVAX_USDT", "ADA_USDT", "DOT_USDT", "LINK_USDT", 
    "MATIC_USDT", "NEAR_USDT", "APT_USDT", "SUI_USDT", "ARB_USDT", "OP_USDT", "FTM_USDT", 
    "INJ_USDT", "ATOM_USDT", "KAS_USDT", "TIA_USDT", "SEI_USDT", "TON_USDT",
    "DOGE_USDT", "SHIB_USDT", "PEPE_USDT", "WIF_USDT", "BONK_USDT", "FLOKI_USDT", "BOME_USDT", 
    "MEME_USDT", "TURBO_USDT", "POPCAT_USDT", "NEIRO_USDT", "PNUT_USDT", "ACT_USDT", 
    "MOODENG_USDT", "GOAT_USDT",
    "FET_USDT", "RENDER_USDT", "TAO_USDT", "WLD_USDT", "AI_USDT", "NFP_USDT", "ARKM_USDT", 
    "GRT_USDT", "OCEAN_USDT", "AGIX_USDT", "IO_USDT", "AKT_USDT",
    "RUNE_USDT", "AAVE_USDT", "MKR_USDT", "CRV_USDT", "LDO_USDT", "PENDLE_USDT", "ENA_USDT", 
    "JUP_USDT", "PYTH_USDT", "ONDO_USDT", "ZRO_USDT", "OMNI_USDT", "ZK_USDT", "STRK_USDT",
    "SAND_USDT", "MANA_USDT", "GALA_USDT", "AXS_USDT", "IMX_USDT", "PIXEL_USDT", "PORTAL_USDT", 
    "BIGTIME_USDT", "ILV_USDT", "NOT_USDT",
    "ORDI_USDT", "SATS_USDT", "RATS_USDT", "STX_USDT", "CKB_USDT", "BADGER_USDT",
    "DYM_USDT", "ALT_USDT", "MANTA_USDT", "XAI_USDT", "ACE_USDT", "METIS_USDT", "ETHFI_USDT", 
    "MEW_USDT", "REZ_USDT", "BB_USDT", "LISTA_USDT", "BANANA_USDT", 
    "UXLINK_USDT", "CATI_USDT", "HMSTR_USDT", "DOGS_USDT", "EIGEN_USDT", "SCR_USDT", 
    "LUMIA_USDT", "SWELL_USDT", "CETUS_USDT", "COW_USDT", "TROY_USDT",
    "FARTCOIN_USDT", "CHILLGUY_USDT", "DOS_USDT", "SAFE_USDT"
]

SYMBOLS = sorted(list(set(SYMBOLS)))

TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

last_signal_tracker = {
    "15m": {},
    "30m": {}
}

# Canlı mum için mikroskobik tolerans (%0.03)
TOLERANCE_LONG = 1.0003
TOLERANCE_SHORT = 0.9997

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    try:
        requests.post(url, json=payload, timeout=5)
    except Exception as e:
        print(f"Telegram mesajı gönderilemedi: {e}")

def get_latest_data(symbol, interval):
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval={interval}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            res_json = res.json()
            if res_json.get("success") and res_json.get("data"):
                d = res_json["data"]
                df = pd.DataFrame({
                    'timestamp': d.get("time", []),
                    'Open': [float(x) for x in d.get("open", [])],
                    'High': [float(x) for x in d.get("high", [])],
                    'Low': [float(x) for x in d.get("low", [])],
                    'Close': [float(x) for x in d.get("close", [])]
                })
                df = df.reset_index(drop=True)
                return df
    except:
        pass
    return None

def check_signals():
    timeframes = [("15m", "Min15"), ("30m", "Min30")]
    
    for tf_label, api_interval in timeframes:
        print(f"[{datetime.datetime.now()}] {len(SYMBOLS)} parite {tf_label} grafikte taranıyor...")

        for symbol in SYMBOLS:
            df = get_latest_data(symbol, api_interval)
            if df is None or len(df) < 100: continue
                
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['EMA100'] = df['Close'].ewm(span=100, adjust=False).mean()
            
            low_min = df['Low'].rolling(window=5).min()
            high_max = df['High'].rolling(window=5).max()
            denom = (high_max - low_min).replace(0, np.nan)
            raw_k = 100 * (df['Close'] - low_min) / denom
            df['Stoch_K'] = raw_k.rolling(window=3).mean()
            
            c_live = df.iloc[-1]
            
            # Trend Kontrolü (EMA 20 > 50 > 100)
            uptrend = (c_live['EMA20'] > c_live['EMA50']) and (c_live['EMA50'] > c_live['EMA100'])
            downtrend = (c_live['EMA20'] < c_live['EMA50']) and (c_live['EMA50'] < c_live['EMA100'])

            if symbol not in last_signal_tracker[tf_label]:
                last_signal_tracker[tf_label][symbol] = None

            tv_symbol = symbol.replace("_", "")
            tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_symbol}.P"

            current_idx = df.index[-1]
            current_timestamp = c_live['timestamp']

            # LONG KONTROLÜ
            if uptrend:
                # Fiyat EMA20'ye değiyor mu ve Stoch RSI < 30 mu?
                is_touching = (c_live['Low'] <= c_live['EMA20'] * TOLERANCE_LONG) and (c_live['Stoch_K'] < 30)
                
                if is_touching:
                    signal_id = f"{current_idx}_{current_timestamp}"
                    if last_signal_tracker[tf_label][symbol] != signal_id:
                        msg = f"🟢 **EMA20 İLK TEMAS (LONG)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Yükseliş trendinde EMA20'ye temas gerçekleşti!\n\n[TradingView'da Aç]({tv_link})"
                        send_telegram_message(msg)
                        last_signal_tracker[tf_label][symbol] = signal_id

            # SHORT KONTROLÜ
            elif downtrend:
                # Fiyat EMA20'ye değiyor mu ve Stoch RSI > 70 mi?
                is_touching = (c_live['High'] >= c_live['EMA20'] * TOLERANCE_SHORT) and (c_live['Stoch_K'] > 70)
                
                if is_touching:
                    signal_id = f"{current_idx}_{current_timestamp}"
                    if last_signal_tracker[tf_label][symbol] != signal_id:
                        msg = f"🔴 **EMA20 İLK TEMAS (SHORT)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Düşüş trendinde EMA20'ye temas gerçekleşti!\n\n[TradingView'da Aç]({tv_link})"
                        send_telegram_message(msg)
                        last_signal_tracker[tf_label][symbol] = signal_id

    print(f"[{datetime.datetime.now()}] Çift zamanlı (15m & 30m) tarama bitti. Hızlı reaksiyon için 15 saniye bekleniyor...\n")

if __name__ == "__main__":
    print("Doğrudan EMA20 Temas Botu Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print(f"Hata: {e}")
        
        time.sleep(15)
