import requests
import pandas as pd
import numpy as np
import time
import datetime

SYMBOLS = [
    "BTC_USDT", "ETH_USDT", "SOL_USDT", "XRP_USDT", "DOGE_USDT", "ADA_USDT", "AVAX_USDT", 
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
    "SAGA_USDT", "LISTA_USDT", "BANANA_USDT", "TON_USDT"
]

SYMBOLS = sorted(list(set(SYMBOLS)))

TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

in_touch_status = {}

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

def get_latest_data(symbol):
    url = f"https://contract.mexc.com/api/v1/contract/kline/{symbol}?interval=Min15"
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
    print(f"[{datetime.datetime.now()}] {len(SYMBOLS)} parite gerçek tepe/dip doğrulamasıyla taranıyor...")

    for symbol in SYMBOLS:
        df = get_latest_data(symbol)
        if df is None or len(df) < 200: continue
            
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        df['EMA50'] = df['Close'].ewm(span=50, adjust=False).mean()
        df['EMA100'] = df['Close'].ewm(span=100, adjust=False).mean()
        df['EMA200'] = df['Close'].ewm(span=200, adjust=False).mean()
        
        low_min = df['Low'].rolling(window=5).min()
        high_max = df['High'].rolling(window=5).max()
        denom = (high_max - low_min).replace(0, np.nan)
        raw_k = 100 * (df['Close'] - low_min) / denom
        df['Stoch_K'] = raw_k.rolling(window=3).mean()
        
        c = df.iloc[-2]
        
        uptrend = (c['EMA20'] > c['EMA50'] * 1.001) and \
                  (c['EMA50'] > c['EMA100'] * 1.001) and (c['EMA100'] > c['EMA200'] * 1.001)
                  
        downtrend = (c['EMA20'] < c['EMA50'] * 0.999) and \
                    (c['EMA50'] < c['EMA100'] * 0.999) and (c['EMA100'] < c['EMA200'] * 0.999)

        if symbol not in in_touch_status:
            in_touch_status[symbol] = False

        tv_symbol = symbol.replace("_", "")
        tv_link = f"https://www.tradingview.com/chart/?symbol=MEXC:{tv_symbol}"

        # LONG KONTROLÜ (Gerçek Yeni Zirve Teyitli)
        if uptrend:
            # Son 96 mumun (24 saatin) en yüksek tepesini alıyoruz
            extended_window = df.iloc[-98:-6]
            historical_peak = extended_window['High'].max()
            
            # Son oluşan tepe, geçmişteki o büyük zirveyi MUTLAKA kırmış (aşmış) olmalı
            recent_peak_window = df.iloc[-6:-2]
            current_move_high = recent_peak_window['High'].max()
            
            is_truly_new_high = current_move_high > historical_peak
            
            # EMA20 Teması ve Stoch RSI şartı
            is_touching = (c['Low'] <= c['EMA20']) and (c['Stoch_K'] < 30)
            
            if is_truly_new_high and is_touching:
                if not in_touch_status[symbol]:
                    msg = f"🟢 **GERÇEK YENİ TEPE + İLK TEMAS (LONG)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `15m`\nFiyat: `{c['Close']}`\nStoch RSI: `{c['Stoch_K']:.2f}`\nDurum: Geçmiş zirve kırıldı, temiz düzeltmeyle EMA20'ye ilk temas gerçekleşti!\n\n[TradingView Grafiği Aç]({tv_link})"
                    send_telegram_message(msg)
                    in_touch_status[symbol] = True
            else:
                in_touch_status[symbol] = False

        # SHORT KONTROLÜ (Gerçek Yeni Dip Teyitli)
        elif downtrend:
            extended_window = df.iloc[-98:-6]
            historical_valley = extended_window['Low'].min()
            
            recent_valley_window = df.iloc[-6:-2]
            current_move_low = recent_valley_window['Low'].min()
            
            is_truly_new_low = current_move_low < historical_valley
            
            is_touching = (c['High'] >= c['EMA20']) and (c['Stoch_K'] > 70)
            
            if is_truly_new_low and is_touching:
                if not in_touch_status[symbol]:
                    msg = f"🔴 **GERÇEK YENİ DİP + İLK TEMAS (SHORT)!**\n\nCoin: `{symbol}`\nZaman Dilimi: `15m`\nFiyat: `{c['Close']}`\nStoch RSI: `{c['Stoch_K']:.2f}`\nDurum: Geçmiş dip kırıldı, temiz yükselişle EMA20'ye ilk temas gerçekleşti!\n\n[TradingView Grafiği Aç]({tv_link})"
                    send_telegram_message(msg)
                    in_touch_status[symbol] = True
            else:
                in_touch_status[symbol] = False

if __name__ == "__main__":
    print("Gerçek Zirve Filtreli Sinyal Botu Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print(f"Hata: {e}")
        
        time.sleep(120)
