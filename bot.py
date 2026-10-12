import sys
import functools
print = functools.partial(print, flush=True)

import requests
import pandas as pd
import numpy as np
import time
import datetime

TELEGRAM_BOT_TOKEN = "8663767442:AAEFpBh0V1eu5tBrWWc0Ki2EmVdS9f_rHiQ"
TELEGRAM_CHAT_ID = "1494316515"

last_signal_tracker = {
    "15m": {},
    "30m": {}
}

# Borsalar arası fiyat farkı için mikroskobik tolerans (%0.03)
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

def get_binance_symbols():
    url = "https://fapi.binance.com/fapi/v1/exchangeInfo"
    symbols = set()
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            for s in data.get("symbols", []):
                if s.get("quoteAsset") == "USDT" and s.get("contractType") == "PERPETUAL":
                    symbols.add(s.get("baseAsset") + "_USDT")
    except:
        pass
    return symbols

def get_mexc_symbols():
    url = "https://contract.mexc.com/api/v1/contract/detail"
    symbols = set()
    try:
        res = requests.get(url, timeout=10)
        if res.status_code == 200:
            data = res.json()
            if data.get("success") and data.get("data"):
                for item in data["data"]:
                    symbol_str = item.get("symbol", "")
                    if symbol_str.endswith("_USDT"):
                        symbols.add(symbol_str)
    except:
        pass
    return symbols

def get_common_symbols():
    binance_syms = get_binance_symbols()
    mexc_syms = get_mexc_symbols()
    if not binance_syms or not mexc_syms:
        if mexc_syms:
            return sorted(list(mexc_syms))
        return []
    common = binance_syms.intersection(mexc_syms)
    return sorted(list(common))

def get_latest_data(symbol, interval):
    url = "https://contract.mexc.com/api/v1/contract/kline/" + symbol + "?interval=" + interval
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
    symbols = get_common_symbols()
    if not symbols:
        print("Ortak sembol listesi alınamadı, bekleniyor...")
        return

    timeframes = [("15m", "Min15"), ("30m", "Min30")]
    
    for tf_label, api_interval in timeframes:
        print("[" + str(datetime.datetime.now()) + "] " + str(len(symbols)) + " ortak parite " + tf_label + " grafikte KESİN TREND + GÖVDE KIRILIM filtresiyle taranıyor...")

        for symbol in symbols:
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
            
            # Sıkışık piyasaları elemek için EMA'lar arasında net mesafe/paralellik şartı
            ema20 = c_live['EMA20']
            ema50 = c_live['EMA50']
            ema100 = c_live['EMA100']
            
            uptrend = (ema20 > ema50 * 1.001) and (ema50 > ema100 * 1.001)
            downtrend = (ema20 < ema50 * 0.999) and (ema50 < ema100 * 0.999)

            if symbol not in last_signal_tracker[tf_label]:
                last_signal_tracker[tf_label][symbol] = None

            tv_symbol = symbol.replace("_", "")
            tv_link = "https://www.tradingview.com/chart/?symbol=BINANCE:" + tv_symbol + ".P"

            current_idx = df.index[-1]
            current_timestamp = c_live['timestamp']
            start_idx = max(0, current_idx - 150)
            recent_threshold = current_idx - 30

            # LONG KONTROLÜ
            if uptrend:
                max_high_idx = df['High'].iloc[start_idx : current_idx].idxmax()
                
                if max_high_idx >= recent_threshold:
                    past_start = max(0, start_idx)
                    past_end = max_high_idx - 5
                    
                    if past_end > past_start:
                        historical_peak = df['High'].iloc[past_start : past_end].max()
                        
                        # Gövde Kapanışlı Zirve Kırılımı (MSB)
                        close_start = max(0, max_high_idx - 2)
                        close_end = min(current_idx, max_high_idx + 3)
                        new_peak_closes = df['Close'].iloc[close_start : close_end]
                        is_truly_new_high = (new_peak_closes > historical_peak).any()
                        
                        count_start_idx = max_high_idx + 1
                        touch_end = current_idx - 1 
                        
                        if touch_end >= count_start_idx:
                            no_prior_touch = (df['Low'].iloc[count_start_idx : touch_end + 1] > df['EMA20'].iloc[count_start_idx : touch_end + 1]).all()
                        else:
                            no_prior_touch = True
                            
                        pullback_df = df.iloc[count_start_idx : current_idx + 1]
                        exception_candles = (pullback_df['Close'] > pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        is_touching = (c_live['Low'] <= c_live['EMA20'] * TOLERANCE_LONG) and (c_live['Stoch_K'] < 30)
                        
                        if is_truly_new_high and is_touching and no_prior_touch and is_clean_pullback:
                            signal_id = str(max_high_idx) + "_" + str(current_timestamp)
                            if last_signal_tracker[tf_label][symbol] != signal_id:
                                msg = "🟢 **NET TREND + GÖVDE KAPANİŞLI İLK TEMAS (LONG)!**\n\nCoin: `" + symbol + "`\nZaman Dilimi: `" + tf_label + "`\nFiyat: `" + str(c_live['Close']) + "`\nStoch RSI: `" + f"{c_live['Stoch_K']:.2f}" + "`\nDurum: Kusursiz paralel trend, gövdeyle kırılan zirve ve EMA20'ye ilk temas!\n\n[TradingView'da Aç](" + tv_link + ")"
                                send_telegram_message(msg)
                                last_signal_tracker[tf_label][symbol] = signal_id

            # SHORT KONTROLÜ
            elif downtrend:
                min_low_idx = df['Low'].iloc[start_idx : current_idx].idxmin()
                
                if min_low_idx >= recent_threshold:
                    past_start = max(0, start_idx)
                    past_end = min_low_idx - 5
                    
                    if past_end > past_start:
                        historical_valley = df['Low'].iloc[past_start : past_end].min()
                        
                        # Gövde Kapanışlı Dip Kırılımı (MSB)
                        close_start = max(0, min_low_idx - 2)
                        close_end = min(current_idx, min_low_idx + 3)
                        new_valley_closes = df['Close'].iloc[close_start : close_end]
                        is_truly_new_low = (new_valley_closes < historical_valley).any()
                        
                        count_start_idx = min_low_idx + 1
                        touch_end = current_idx - 1
                        
                        if touch_end >= count_start_idx:
                            no_prior_touch = (df['High'].iloc[count_start_idx : touch_end + 1] < df['EMA20'].iloc[count_start_idx : touch_end + 1]).all()
                        else:
                            no_prior_touch = True
                            
                        pullback_df = df.iloc[count_start_idx : current_idx + 1]
                        exception_candles = (pullback_df['Close'] < pullback_df['Open']).sum()
                        is_clean_pullback = exception_candles <= 2
                        
                        is_touching = (c_live['High'] >= c_live['EMA20'] * TOLERANCE_SHORT) and (c_live['Stoch_K'] > 70)
                        
                        if is_truly_new_low and is_touching and no_prior_touch and is_clean_pullback:
                            signal_id = str(min_low_idx) + "_" + str(current_timestamp)
                            if last_signal_tracker[tf_label][symbol] != signal_id:
                                msg = "🔴 **NET TREND + GÖVDE KAPANİŞLI İLK TEMAS (SHORT)!**\n\nCoin: `" + symbol + "`\nZaman Dilimi: `" + tf_label + "`\nFiyat: `" + str(c_live['Close']) + "`\nStoch RSI: `" + f"{c_live['Stoch_K']:.2f}" + "`\nDurum: Kusursiz paralel trend, gövdeyle kırılan dip ve EMA20'ye ilk temas!\n\n[TradingView'da Aç](" + tv_link + ")"
                                send_telegram_message(msg)
                                last_signal_tracker[tf_label][symbol] = signal_id

    print("[" + str(datetime.datetime.now()) + "] Tarama bitti. 15 saniye bekleniyor...\n")

if __name__ == "__main__":
    print("Keskin Nişancı Trend & Kırılım Botu Devrede...")
    while True:
        try:
            check_signals()
        except Exception as e:
            print("Hata: " + str(e))
        
        time.sleep(15)
