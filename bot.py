"""
Keskin Nişancı Trend & Kırılım Botu - ana döngü.

Dosyalar:
  config.py    -> ayarlar (token'lar Render Environment'tan gelir)
  strategy.py  -> sinyal kuralları (sadece mantık)
  exchanges.py -> Binance vadeli veri çekme
  telegram.py  -> mesaj gönderme ve mesaj metni
  bot.py       -> bunları birleştiren döngü (ana dosya)
  commands.py  -> Telegram komutları (/backtest)
  backtest.py  -> geçmiş veride strateji testi
"""

import os
import sys

# Çok iş parçacıklı Python'da glibc bellek arenaları RAM'i şişirir; 2 ile sınırla.
# Ayar süreç başlarken okunduğu için gerekirse bir kez kendini yeniden başlatır.
if os.environ.get("MALLOC_ARENA_MAX") != "2":
    os.environ["MALLOC_ARENA_MAX"] = "2"
    os.execv(sys.executable, [sys.executable] + sys.argv)

import html
import logging
import shutil
import signal
import threading
import time

import commands
import config
from commands import start_listener
import live_setups
import memwatch
from exchanges import get_symbols as fetch_symbols, get_klines
from strategy import check_signal
from telegram import format_signal, send_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

# Aynı sinyali iki kez göndermemek için: (zaman dilimi, coin) -> son sinyal kimliği
last_signal = {}

_symbols = []
_symbols_time = 0.0


def get_symbols():
    """Coin listesini saatte bir yeniler (her turda çekmez)."""
    global _symbols, _symbols_time
    if not _symbols or time.time() - _symbols_time > config.SYMBOL_REFRESH_SECONDS:
        fresh = fetch_symbols()
        if fresh:
            _symbols, _symbols_time = fresh, time.time()
            log.info("Coin listesi güncellendi: %d Binance vadeli parite", len(_symbols))
    return _symbols


def scan():
    if not config.TOUCH_ALERTS:
        return
    symbols = get_symbols()
    if not symbols:
        log.warning("Coin listesi alınamadı, bekleniyor...")
        return

    for tf_label, api_interval in config.TIMEFRAMES:
        log.info("%d parite %s grafikte taranıyor...", len(symbols), tf_label)
        found = 0
        for symbol in symbols:
            try:
                df = get_klines(symbol, api_interval)
                sig = check_signal(df)
            except Exception as e:
                log.error("%s %s işlenirken hata: %s", symbol, tf_label, e)
                continue
            if not sig:
                continue

            signal_id = f"{sig['pivot_idx']}_{sig['timestamp']}"
            key = (tf_label, symbol)
            if last_signal.get(key) == signal_id:
                continue

            if send_message(format_signal(symbol, tf_label, sig)):
                last_signal[key] = signal_id
                found += 1
                log.info("SİNYAL: %s %s %s @ %s", sig["side"], symbol, tf_label, sig["price"])
        log.info("%s taraması bitti, %d yeni sinyal.", tf_label, found)


def setup_loop():
    """EMİR HAZIR taraması kendi iş parçacığında: temas taraması uzun sürse bile
    mum kapanış penceresini kaçırmaz."""
    while True:
        if config.SETUP_ALERTS:
            try:
                live_setups.maybe_run()
            except Exception as e:
                log.exception("Setup döngüsü hatası: %s", e)
        time.sleep(5)


def _on_sigterm(signum, frame):
    """Render yeni sürümü açınca eskisini SIGTERM ile kapatır. Eski bot o arada bir backtest
    başlatmışsa (komut eski bota düşmüşse) backtest de ölür: kullanıcıya haber ver."""
    proc = commands.backtest_proc()
    if proc is not None and proc.poll() is None:
        proc.terminate()
        send_message("⚠️ Bot güncellendi, bu sırada çalışan backtest yarıda kaldı. "
                     "Yeni bot açıldıktan 1-2 dk sonra tekrar başlat (/durum ile kontrol et).")
    log.info("SIGTERM alındı, bot kapanıyor")
    sys.exit(0)


def main():
    log.info("Keskin Nişancı Trend & Kırılım Botu Devrede...")
    signal.signal(signal.SIGTERM, _on_sigterm)
    shutil.rmtree("/tmp/bt_cache", ignore_errors=True)  # eski sürümün veri önbelleği
    prev = memwatch.previous_run_note()
    durum = "açık" if config.TOUCH_ALERTS else "kapalı"
    setup = "açık" if config.SETUP_ALERTS else "kapalı"
    import autotrade
    try:
        oto = autotrade.status_text().split("\n")[0]
    except Exception as e:
        oto = f"🤖 Otomatik işlem: durum okunamadı ({html.escape(str(e))[:100]})"
    send_message(f"✅ Bot başladı\n"
                 f"🏷 Sürüm: {html.escape(config.version_text())}\n"
                 f"📋 Emir bildirimleri: {setup} (hacmi en yüksek {live_setups.UNIVERSE} coin, {live_setups.LIVE_TF})\n"
                 f"Kurallar: {live_setups.rules_summary()}\n"
                 f"🔔 Temas bildirimleri: {durum}\n"
                 f"{oto}\n"
                 + (f"🧠 {prev}\n" if prev else "")
                 + "Komutlar: /oto aç|kapat  /ip  /sinyal aç|kapat  /bildirim aç|kapat  /backtest  /durum  /iptal  /incele")
    start_listener()
    memwatch.start(commands.backtest_proc, send_message)
    autotrade.start(send_message)
    threading.Thread(target=setup_loop, daemon=True).start()
    while True:
        if config.TOUCH_ALERTS:
            try:
                scan()
            except Exception as e:
                log.exception("Tarama hatası: %s", e)
        time.sleep(config.SCAN_SLEEP)


if __name__ == "__main__":
    main()
