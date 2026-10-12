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
    "FARTCOIN_USDT", "CHILLGUY_USDT", "DOS_USDT"
]

SYMBOLS = sorted(list(set(SYMBOLS)))

TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

last_signal_tracker = {
    "15m": {},
    "30m": {}
}

# Borsalar arası farkı tolere etmek için ÇOK HASSAS mıknatıs payı (%0.03)
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
        print(f"[{datetime.datetime.now()}] {len(SYMBOLS)} parite {tf_label} grafikte MİKRO MIKNATIS PAYI (%0.03) ile taranıyor...")

        for symbol in SYMBOLS:
            df = get_latest_data(symbol, api_interval)
            if df is None or len(df) < 180: continue
                
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['EMA100'] = df['Close'].ewm(span=100, adjust=False).mean()
            
            low_min = df['Low'].rolling(window=5).min()
            high_max = df['High'].rolling(window=5).max()
            denom = (high_max - low_min).replace(0, np.nan)
            raw_k = 100 * (df['Close'] - low_min) / denom
            df['Stoch_K'] = raw_k.rolling(window=3).mean()
            
            c_live = df.iloc[-1]
            
            uptrend = (c_live['EMA20'] > c_live['EMA50']) and (c_live['EMA50'] > c_live['EMA100'])
            downtrend = (c_live['EMA20'] < c_live['EMA50']) and (c_live['EMA50'] < c_live['EMA100'])

            if symbol not in last_signal_tracker[tf_label]:
                last_signal_tracker[tf_label][symbol] = None

            tv_symbol = symbol.replace("_", "")
            tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_symbol}.P"

            current_idx = df.index[-1]
            current_timestamp = c_live['timestamp']
            start_idx = max(0, current_idx - 150)
            recent_threshold = current_idx - 30

            # LONG KONTROLÜ
            if uptrend:
                max_high_idx = df['High'].iloc[start_idx : current_idx].idxmax()
                
                if max_high_idx >= recent_threshold:
                    past_start = max(0, start_idx)
                    past_end = max_high_idx - 8
                    
                    if past_end > past_start:
                        historical_peak = df['High'].iloc[past_start : past_end].max()
                        
                        close_start = max(0, max_high_idx - 2)
                        close_end = min(current_idx, max_high_idx + 3)
                        new_peak_closes = df['Close'].iloc[close_start : close_end]
                        
                        is_truly_new_high = (new_peak_closes > historical_peak).any()
                        
                        max_close_idx = df['Close'].iloc[start_idx : current_idx].idxmax()
                        count_start_idx = min(max_high_idx, max_close_idx) + 1
                        
                        touch_end = current_idx - 1 
                        
                        if touch_end >= count_start_idx:
                            no_prior_touch = (df['Low'].iloc[count_start_idx : touch_end + 1] > df['EMA20'].iloc[count_start_idx : touch_end + 1] * TOLERANCE_LONG).all()
                        else:
                            no_prior_touch = True
                            
                        pullback_df = df.iloc[count_start_idx : current_idx + 1]
                        exception_candles = (pullback_df['Close'] > pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        # Canlı mumda toleranslı temas kontrolü
                        is_touching = (c_live['Low'] <= c_live['EMA20'] * TOLERANCE_LONG) and (c_live['Stoch_K'] < 30)
                        
                        if is_truly_new_high and is_touching and no_prior_touch and is_clean_pullback:
                            signal_id = f"{max_high_idx}_{current_timestamp}"
                            if last_signal_tracker[tf_label][symbol] != signal_id:
                                msg = f"🟢 **GERÇEK ZİRVE + ESNEMİŞ İLK TEMAS (LONG)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Zirveden sonra temiz düşüş sağlandı. EMA20'ye (Hassas Mıknatıs %0.03) ilk temas gerçekleşti!\n\n[TradingView'da Aç]({tv_link})"
                                send_telegram_message(msg)
                                last_signal_tracker[tf_label][symbol] = signal_id

            # SHORT KONTROLÜ
            elif downtrend:
                min_low_idx = df['Low'].iloc[start_idx : current_idx].idxmin()
                
                if min_low_idx >= recent_threshold:
                    past_start = max(0, start_idx)
                    past_end = min_low_idx - 8
                    
                    if past_end > past_start:
                        historical_valley = df['Low'].iloc[past_start : past_end].min()
                        
                        close_start = max(0, min_low_idx - 2)
                        close_end = min(current_idx, min_low_idx + 3)
                        new_valley_closes = df['Close'].iloc[close_start : close_end]
                        
                        is_truly_new_low = (new_valley_closes < historical_valley).any()
                        
                        min_close_idx = df['Close'].iloc[start_idx : current_idx].idxmin()
                        count_start_idx = min(min_low_idx, min_close_idx) + 1
                        
                        touch_end = current_idx - 1
                        
                        if touch_end >= count_start_idx:
                            no_prior_touch = (df['High'].iloc[count_start_idx : touch_end + 1] < df['EMA20'].iloc[count_start_idx : touch_end + 1] * TOLERANCE_SHORT).all()
                        else:
                            no_prior_touch = True
                            
                        pullback_df = df.iloc[count_start_idx : current_idx + 1]
                        exception_candles = (pullback_df['Close'] < pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        # Canlı mumda toleranslı temas kontrolü
                        is_touching = (c_live['High'] >= c_live['EMA20'] * TOLERANCE_SHORT) and (c_live['Stoch_K'] > 70)
                        
                        if is_truly_new_low and is_touching and no_prior_touch and is_clean_pullback:
                            signal_id = f"{min_low_idx}_{current_timestamp}"
                            if last_signal_tracker[tf_label][symbol] != signal_id:
                                msg = f"🔴 **GERÇEK DİP + ESNEMİŞ İLK TEMAS (SHORT)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Dipten sonra temiz yükseliş sağlandı. EMA20'ye (Hassas Mıknatıs %0.03) ilk temas gerçekleşti!\n\n[TradingView'da Aç]({tv_link})"
                                send_telegram_message(msg)
                                last_signal_tracker[tf_label][symbol] = signal_id

    print(f"[{datetime.datetime.now()}] Çift zamanlı (15m & 30m) tarama bitti. Hızlı reaksiyon için 15 saniye bekleniyor...\n")

if __name__ == "__main__":
    print("Mikro Hassasiyetli (Hata Engelleyici) İlk Temas Botu Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print(f"Hata: {e}")
        
        time.sleep(15)
