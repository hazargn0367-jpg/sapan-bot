import sys
import functools
print = functools.partial(print, flush=True)

import requests
import pandas as pd
import numpy as np
import time
import datetime

SYMBOLS = [
    "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT", "AVAX_USDT", 
    "LINK_USDT", "NEAR_USDT", "SUI_USDT", "RENDER_USDT", "FET_USDT", "INJ_USDT", "ARB_USDT", 
    "OP_USDT", "TIA_USDT", "SEI_USDT", "JUP_USDT", "PYTH_USDT", "STRK_USDT", "ENA_USDT", 
    "WIF_USDT", "PEPE_USDT", "SHIB_USDT", "BOME_USDT", "ORDI_USDT", "BONK_USDT", "FLOKI_USDT", 
    "ATOM_USDT", "LTC_USDT", "BCH_USDT", "ETC_USDT", "ICP_USDT", "FIL_USDT", "STX_USDT", 
    "IMX_USDT", "GRT_USDT", "SNX_USDT", "CRV_USDT", "LDO_USDT", "AAVE_USDT", "MKR_USDT", 
    "SAND_USDT", "MANA_USDT", "AXS_USDT", "GALA_USDT", "CHZ_USDT", "ALGO_USDT", "VET_USDT", 
    "HBAR_USDT", "EGLD_USDT", "THETA_USDT", "XTZ_USDT", "KAVA_USDT", "RUNE_USDT", "UNI_USDT", 
    "FTM_USDT", "DOT_USDT", "ONDO_USDT", "WLD_USDT", "PORTAL_USDT", "PENDLE_USDT", "TNSR_USDT", 
    "ZRO_USDT", "DYM_USDT", "POL_USDT", "MEW_USDT", "POPCAT_USDT", "TURBO_USDT", "REZ_USDT", 
    "OMNI_USDT", "NOT_USDT", "ZK_USDT", "IO_USDT", "ZRX_USDT", "BB_USDT", "REI_USDT", 
    "BICO_USDT", "GLMR_USDT", "NFP_USDT", "AI_USDT", "XAI_USDT", "MAV_USDT", "CYBER_USDT", 
    "HIFI_USDT", "ARK_USDT", "BSV_USDT", "EOS_USDT", "TRX_USDT", "XLM_USDT", "QNT_USDT", 
    "FLOW_USDT", "GMT_USDT", "APE_USDT", "BLUR_USDT", "MAGIC_USDT", "HIGH_USDT", "JOE_USDT", 
    "GMX_USDT", "LQTY_USDT", "SSV_USDT", "CFX_USDT", "ACH_USDT", "AGIX_USDT", "OCEAN_USDT", 
    "COTI_USDT", "CTSI_USDT", "DGB_USDT", "KAS_USDT", "MEME_USDT", "SATS_USDT", "RATS_USDT", 
    "POLYX_USDT", "CKB_USDT", "PORT3_USDT", "SLERF_USDT", "BENDOG_USDT", "WUF_USDT", "MOG_USDT", 
    "NEIRO_USDT", "CATI_USDT", "DOGS_USDT", "HMSTR_USDT", "EIGEN_USDT", "SCR_USDT", "GOAT_USDT", 
    "PNUT_USDT", "ACT_USDT", "HIPPO_USDT", "MOODENG_USDT", "ANIME_USDT", "PENGU_USDT", "TRUMP_USDT", 
    "MELANIA_USDT", "SPLUS_USDT", "ZETA_USDT", "ACE_USDT", "ALT_USDT", "PIXEL_USDT", 
    "SAGA_USDT", "LISTA_USDT", "BANANA_USDT", "TON_USDT", "SENT_USDT", "MAJOR_USDT", 
    "PUNDIX_USDT", "STG_USDT", "HIVE_USDT", "COW_USDT", "LUCE_USDT", "USUAL_USDT", 
    "VIRTUAL_USDT", "SPX_USDT", "AI16Z_USDT", "FARTCOIN_USDT", "CHILLGUY_USDT"
]

SYMBOLS = sorted(list(set(SYMBOLS)))

TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

in_touch_status = {
    "15m": {},
    "30m": {}
}

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
        print(f"[{datetime.datetime.now()}] {len(SYMBOLS)} parite {tf_label} grafikte TEMİZ DÜZELTME filtresiyle taranıyor...")

        for symbol in SYMBOLS:
            df = get_latest_data(symbol, api_interval)
            if df is None or len(df) < 150: continue
                
            df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
            df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
            df['EMA100'] = df['Close'].ewm(span=100, adjust=False).mean()
            df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
            
            low_min = df['Low'].rolling(window=5).min()
            high_max = df['High'].rolling(window=5).max()
            denom = (high_max - low_min).replace(0, np.nan)
            raw_k = 100 * (df['Close'] - low_min) / denom
            df['Stoch_K'] = raw_k.rolling(window=3).mean()
            
            c_live = df.iloc[-1]
            
            uptrend = (c_live['EMA20'] > c_live['EMA50'] * 1.001) and \
                      (c_live['EMA50'] > c_live['EMA100'] * 1.001) and (c_live['EMA100'] > c_live['EMA200'] * 1.001)
                      
            downtrend = (c_live['EMA20'] < c_live['EMA50'] * 0.999) and \
                        (c_live['EMA50'] < c_live['EMA100'] * 0.999) and (c_live['EMA100'] < c_live['EMA200'] * 0.999)

            if symbol not in in_touch_status[tf_label]:
                in_touch_status[tf_label][symbol] = False

            tv_symbol = symbol.replace("_", "")
            tv_link = f"https://www.tradingview.com/chart/?symbol=BINANCE:{tv_symbol}.P"

            current_idx = df.index[-1]
            start_idx = max(0, current_idx - 80)
            recent_threshold = current_idx - 25

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
                        
                        touch_start = max_high_idx + 1
                        touch_end = current_idx
                        if touch_end > touch_start:
                            no_prior_touch = (df['Low'].iloc[touch_start : touch_end] > df['EMA20'].iloc[touch_start : touch_end]).all()
                        else:
                            no_prior_touch = True
                            
                        # TEMİZ DÜZELTME KONTROLÜ: Yeni tepeden güncel muma kadar en fazla 2 yeşil muma izin ver
                        pullback_df = df.iloc[touch_start : current_idx + 1]
                        exception_candles = (pullback_df['Close'] > pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        is_touching = (c_live['Low'] <= c_live['EMA20']) and (c_live['Stoch_K'] < 30)
                        
                        if is_truly_new_high and is_touching and no_prior_touch and is_clean_pullback:
                            if not in_touch_status[tf_label][symbol]:
                                msg = f"🟢 **TEMİZ DÜZELTME + İLK TEMAS (LONG)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Zirveden sonra temiz bir düşüş dalgasıyla (en fazla {exception_candles} istisna mum) EMA20'ye ilk temas geldi!\n\n[TradingView Grafiği Aç]({tv_link})"
                                send_telegram_message(msg)
                                in_touch_status[tf_label][symbol] = True
                        else:
                            if not is_touching:
                                in_touch_status[tf_label][symbol] = False

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
                        
                        touch_start = min_low_idx + 1
                        touch_end = current_idx
                        if touch_end > touch_start:
                            no_prior_touch = (df['High'].iloc[touch_start : touch_end] < df['EMA20'].iloc[touch_start : touch_end]).all()
                        else:
                            no_prior_touch = True
                            
                        # TEMİZ DÜZELTME KONTROLÜ: Yeni dipten güncel muma kadar en fazla 2 kırmızı muma izin ver
                        pullback_df = df.iloc[touch_start : current_idx + 1]
                        exception_candles = (pullback_df['Close'] < pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        is_touching = (c_live['High'] >= c_live['EMA20']) and (c_live['Stoch_K'] > 70)
                        
                        if is_truly_new_low and is_touching and no_prior_touch and is_clean_pullback:
                            if not in_touch_status[tf_label][symbol]:
                                msg = f"🔴 **TEMİZ DÜZELTME + İLK TEMAS (SHORT)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Dipten sonra temiz bir yükseliş dalgasıyla (en fazla {exception_candles} istisna mum) EMA20'ye ilk temas geldi!\n\n[TradingView Grafiği Aç]({tv_link})"
                                send_telegram_message(msg)
                                in_touch_status[tf_label][symbol] = True
                        else:
                            if not is_touching:
                                in_touch_status[tf_label][symbol] = False

    print(f"[{datetime.datetime.now()}] Çift zamanlı (15m & 30m) tarama bitti. Hızlı reaksiyon için 15 saniye bekleniyor...\n")

if __name__ == "__main__":
    print("Mutlak Yapı & Temiz Düzeltme Botu (15m & 30m) Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print(f"Hata: {e}")
        
        time.sleep(15)
