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

# Hafıza 15m ve 30m olarak güncellendi
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
        res = requests.get(url
