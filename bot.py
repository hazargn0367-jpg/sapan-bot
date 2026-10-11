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
                return df
    except:
        pass
    return None

def check_signals():
    timeframes = [("15m", "Min15"), ("30m", "Min30")]
    
    for tf_label, api_interval in timeframes:
        print(f"[{datetime.datetime.now()}] {len(SYMBOLS)} parite {tf_label} grafikte DİNAMİK İĞNE REDDİ ile taranıyor...")

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

            # LONG KONTROLÜ
            if uptrend:
                # Son 40 mum içindeki en yüksek kapanışı ve onun grafikteki net pozisyonunu bul
                recent_closes = df['Close'].iloc[-40:-1]
                max_close_val = np.max(recent_closes.values)
                max_close_pos = np.argmax(recent_closes.values) 
                abs_max_close_pos = len(df) - 40 + max_close_pos # Grafikteki gerçek indeksi
                
                # Geçmiş tepeyi, bulduğumuz en yüksek kapanıştan en az 8 mum öncesine kadar ara
                past_highs = df['High'].iloc[-120 : abs_max_close_pos - 8]
                
                if len(past_highs) > 0:
                    historical_peak = past_highs.max()
                    # Yeni gövde kapanışı, eski iğnenin tam olarak üstünde mi?
                    is_truly_new_high = max_close_val > historical_peak
                else:
                    is_truly_new_high = False
                    
                is_touching = (c_live['Low'] <= c_live['EMA20']) and (c_live['Stoch_K'] < 30)
                
                if is_truly_new_high and is_touching:
                    if not in_touch_status[tf_label][symbol]:
                        msg = f"🟢 **DİNAMİK KIRILIM + ANLIK TEMAS (LONG)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Önceki zirvenin iğne ucu, GÖVDE ile net şekilde aşıldı. Şu anki hareketli mum EMA20'ye ilk temasını gerçekleştirdi!\n\n[TradingView Grafiği Aç]({tv_link})"
                        send_telegram_message(msg)
                        in_touch_status[tf_label][symbol] = True
                else:
                    if not is_touching:
                        in_touch_status[tf_label][symbol] = False

            # SHORT KONTROLÜ
            elif downtrend:
                # Son 40 mum içindeki en düşük kapanışı ve onun grafikteki net pozisyonunu bul
                recent_closes = df['Close'].iloc[-40:-1]
                min_close_val = np.min(recent_closes.values)
                min_close_pos = np.argmin(recent_closes.values)
                abs_min_close_pos = len(df) - 40 + min_close_pos # Grafikteki gerçek indeksi
                
                # Geçmiş dip seviyesini, bulduğumuz en düşük kapanıştan en az 8 mum öncesine kadar ara
                past_lows = df['Low'].iloc[-120 : abs_min_close_pos - 8]
                
                if len(past_lows) > 0:
                    historical_valley = past_lows.min()
                    # Yeni gövde kapanışı, eski iğnenin tam olarak altında mı?
                    is_truly_new_low = min_close_val < historical_valley
                else:
                    is_truly_new_low = False
                    
                is_touching = (c_live['High'] >= c_live['EMA20']) and (c_live['Stoch_K'] > 70)
                
                if is_truly_new_low and is_touching:
                    if not in_touch_status[tf_label][symbol]:
                        msg = f"🔴 **DİNAMİK KIRILIM + ANLIK TEMAS (SHORT)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `{tf_label}`\nFiyat: `{c_live['Close']}`\nStoch RSI: `{c_live['Stoch_K']:.2f}`\nDurum: Önceki dibin iğne ucu, GÖVDE ile net şekilde kırıldı. Şu anki hareketli mum EMA20'ye ilk temasını gerçekleştirdi!\n\n[TradingView Grafiği Aç]({tv_link})"
                        send_telegram_message(msg)
                        in_touch_status[tf_label][symbol] = True
                else:
                    if not is_touching:
                        in_touch_status[tf_label][symbol] = False

    print(f"[{datetime.datetime.now()}] Çift zamanlı (15m & 30m) tarama bitti. Hızlı reaksiyon için 15 saniye bekleniyor...\n")

if __name__ == "__main__":
    print("Dinamik MSB & Anlık Temas Bildirimli Bot (15m & 30m) Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print(f"Hata: {e}")
        
        time.sleep(15)
