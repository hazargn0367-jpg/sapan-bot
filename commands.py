"""
Telegram komutları (bot arka planda dinler):
  /backtest       -> son 7 günle backtest başlatır
  /backtest 60    -> son 60 günle backtest başlatır
  /backtest 30 2.5 -> 30 gün, TP = riskin 2.5 katı
  /backtest 30 2.5 1 -> + 1R kârda stop girişe (başabaş)
  /backtest 30 önceki -> bir önceki 30 günlük dönem
  /backtest 30 hepsi -> TP/başabaş/filtre ayarlarını tek seferde karşılaştır
  /backtest 30 filtresiz -> ek filtreler kapalı
  /backtest 30 atr -> stop en az 0.875 ATR
  /backtest 30 yeni önceki -> grafik incelemesinden gelen kuralları karşılaştır
  /backtest 30 koruma önceki -> açık işlem sınırı, toplu sinyal ve BTC filtresi karşılaştırması
  /backtest 30 son önceki -> 4 kural + korumalar birlikte
  /backtest 30 son2 önceki -> 6 kural + toplu sinyal filtresi
  /backtest 30 saat önceki -> 03-07 TR saat filtresinin etkisi
  /backtest 30 tp önceki -> canlı kurallarla 1:1.5 / 1:2 / 1:2.2 / 1:2.5
  /backtest 90 canlı -> canlı bildirimlerdeki ayarın aynısı, tüm işlemlerin grafikleri PDF
  /backtest 90 dip -> canlı ayar + önceki tepe/dibe mesafe (0.5/1/1.5/2.2R), ay ay
  /backtest 90 yapı -> kural 7 (önünde yer) ve kural 8 (yapı bozulmamış), ay ay + grafik PDF
  /backtest 7 canlı 5m -> canlı ayar 5 dakikalık grafikte (sona 5m yazılırsa her test 5m'de çalışır)
  /backtest 30 iğne 5m -> kural 10 (temas mumunun ters iğnesi) ve kural 7 (önünde yer)
  /backtest 30 toplu 5m -> toplu sinyal filtresi: 5 / 8 / 12 coin / kapalı karşılaştırması
  /backtest 90 destek -> kural 9 (dip/tepeden sonra iğneli mumlar = destek/direnç), ay ay + grafik PDF
  (varsayılan: hacmi en yüksek 500 coin, canlı bildirimlerle aynı; 'tüm' yazılırsa hepsi)
  /durum          -> backtest ilerlemesi + canlı tarama durumu
  /incele AXSUSDT 01.08.2026 02:00 -> bir işlemin tüm kurallardaki değerlendirmesi + grafik (TR saati, 15m)
  /incele AXSUSDT 13.10 22:05 5m  -> 5 dakikalık canlı bildirimi incele
  /iptal          -> çalışan backtest'i durdurur
  /bildirim aç | kapat -> EMA20 temas bildirimleri
  /sinyal aç | kapat -> kurallara uyan setup'larda EMİR HAZIR bildirimleri
Sadece TELEGRAM_CHAT_ID'deki sohbetten gelen komutlar kabul edilir.
"""

import logging
import os
import re
import subprocess
import sys
import threading
import time

import requests

import config
from telegram import send_message

log = logging.getLogger("bot")
HERE = os.path.dirname(os.path.abspath(__file__))
_bt_proc = None
_bt_cmd = ""   # çalışan / son backtest'in komutu (/durum'da gösterilir)


def start_backtest(text):
    global _bt_proc, _bt_cmd
    if _bt_proc is not None and _bt_proc.poll() is None:
        send_message("⏳ Backtest zaten çalışıyor, bitince sonuçlar gelecek.")
        return
    tf_m = re.search(r"\b(5m|15m|30m|5dk|5 dk)\b", text.lower())
    clean = re.sub(r"\b(5m|15m|30m|5dk|5 dk)\b|son2", " ", text.lower())
    nums = re.findall(r"\d+(?:[.,]\d+)?", clean)
    days = 7
    args = []
    if nums:
        days = max(1, min(180, int(float(nums[0].replace(",", ".")))))
    if len(nums) > 1:
        rr = max(0.5, min(10.0, float(nums[1].replace(",", "."))))
        args = ["--rr", str(rr)]
    if len(nums) > 2:
        be = max(0.0, min(5.0, float(nums[2].replace(",", "."))))
        args += ["--be", str(be)]
    low = text.lower()
    if "önceki" in low or "onceki" in low:
        args += ["--ago", str(days)]
    if "iğne" in low or "igne" in low:
        args += ["--compare", "igne"]
    elif "toplu" in low:
        args += ["--compare", "toplu"]
    elif "destek" in low:
        args += ["--compare", "destek"]
    elif "yapı" in low or "yapi" in low:
        args += ["--compare", "yapi"]
    elif re.search(r"\bdip\b", low):
        args += ["--compare", "dip"]
    elif "canlı" in low or "canli" in low:
        args += ["--preset", "canli"]
    elif re.search(r"\btp\b", low):
        args += ["--compare", "tp"]
    elif "saat" in low:
        args += ["--compare", "saat"]
    elif "son2" in low:
        args += ["--compare", "son2"]
    elif re.search(r"\bson\b", low):
        args += ["--compare", "son"]
    elif "koruma" in low:
        args += ["--compare", "koruma"]
    elif "yeni" in low:
        args += ["--compare", "yeni"]
    elif any(w in low for w in ("hepsi", "karşılaştır", "karsilastir")):
        args += ["--compare", "hepsi"]
    if "filtresiz" in low:
        args += ["--no-filters"]
    if tf_m:
        args += ["--tf", "5m" if tf_m.group(1).startswith("5") else tf_m.group(1)]
    if "tüm" in low or "tum" in low:
        args += ["--top", "0"]
    if "atr" in low:
        args += ["--atr-min", "0.875"]
    _bt_cmd = text.strip()
    log_file = open(os.path.join(HERE, "backtest.log"), "w")
    _bt_proc = subprocess.Popen(
        [sys.executable, "-u", "backtest.py", "--days", str(days)] + args,
        cwd=HERE, stdout=log_file, stderr=subprocess.STDOUT,
    )
    log.info("Backtest başlatıldı (%d gün)", days)


def backtest_proc():
    """Çalışan (ya da son) backtest süreci; bellek takibi kullanır."""
    return _bt_proc


def status_text():
    running = _bt_proc is not None and _bt_proc.poll() is None
    progress = ""
    try:
        with open(os.path.join(HERE, "backtest.log"), encoding="utf-8", errors="ignore") as f:
            lines = [ln.strip() for ln in f if "coin bitti" in ln or "ERROR" in ln or "Traceback" in ln]
        if lines:
            progress = lines[-1].split(" INFO ")[-1].split(" ERROR ")[-1]
    except OSError:
        pass
    if running:
        return (f"⏳ Backtest çalışıyor ({_bt_cmd})" + (f": {progress}" if progress else ", veri çekiliyor..."))
    if _bt_proc is not None:
        if _bt_proc.returncode == -15:
            return "🛑 Son backtest durduruldu (/iptal ya da bellek sınırı)."
        if _bt_proc.returncode == 3:
            return "⛔ Son backtest Binance engeli yüzünden durdu. Engel bitince tekrar başlat."
        if _bt_proc.returncode not in (0, None):
            try:
                with open(os.path.join(HERE, "backtest.log"), encoding="utf-8", errors="ignore") as f:
                    tail = [ln.rstrip() for ln in f if ln.strip()][-3:]
            except OSError:
                tail = []
            return "⚠️ Son backtest hatayla kapandı:\n" + "\n".join(tail)
        return "✅ Son backtest bitti." + (f"\nSon satır: {progress}" if progress else "")
    return "Çalışan backtest yok. Başlatmak için: /backtest"


def _listen():
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/getUpdates"
    offset = None
    # Bot kapalıyken gönderilmiş eski komutları atla
    try:
        old = requests.get(url, params={"offset": -1}, timeout=15).json().get("result", [])
        if old:
            offset = old[-1]["update_id"] + 1
    except Exception as e:
        log.error("Telegram komutları okunamadı: %s", e)

    while True:
        try:
            params = {"timeout": 30}
            if offset is not None:
                params["offset"] = offset
            updates = requests.get(url, params=params, timeout=40).json().get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                if str(msg.get("chat", {}).get("id")) != str(config.TELEGRAM_CHAT_ID):
                    continue
                text = (msg.get("text") or "").strip()
                if text.lower().startswith("/backtest"):
                    start_backtest(text)
                elif text.lower().startswith("/incele"):
                    def _run(t=text):
                        import inspect_trade
                        from telegram import send_photo
                        try:
                            msg, chart = inspect_trade.inspect(t)
                            send_message(msg)
                            if chart:
                                send_photo(chart, "p = son tepe/dip, q = ondan önceki salınım tepesi/dibi, "
                                                  "turuncu çizgi = önceki düzeltmenin ucu (kural 8), "
                                                  "mavi üçgen = dip/tepeden sonraki iğneli mum (kural 9)")
                        except Exception as e:
                            send_message(f"⚠️ İnceleme hatası: {type(e).__name__}: {e}")
                    threading.Thread(target=_run, daemon=True).start()
                elif text.lower().startswith("/durum"):
                    import live_setups
                    import memwatch
                    sig = "açık" if config.SETUP_ALERTS else "KAPALI"
                    import exchanges
                    exchanges.probe_weight()  # IP'nin şu anki Binance kullanımı (1 hafif istek)
                    send_message(f"{status_text()}\n\n{live_setups.status_text()}\nEmir bildirimleri: {sig}"
                                 f"\n\n{exchanges.status_line()}\n\n{memwatch.status_line()}")
                elif text.lower().startswith("/sinyal"):
                    low = text.lower()
                    if "kapa" in low:
                        config.SETUP_ALERTS = False
                    elif "aç" in low or "ac" in low:
                        config.SETUP_ALERTS = True
                    send_message("📋 Emir bildirimleri " + ("açık" if config.SETUP_ALERTS else "kapalı")
                                 + ". (Bot yeniden başlarsa açık başlar.)")
                elif text.lower().startswith("/bildirim"):
                    low = text.lower()
                    if "kapa" in low:
                        config.TOUCH_ALERTS = False
                    elif "aç" in low or "ac" in low:
                        config.TOUCH_ALERTS = True
                    send_message("🔔 Temas bildirimleri " + ("açık" if config.TOUCH_ALERTS else "kapalı")
                                 + ". (Bot yeniden başlarsa kapalı başlar.)")
                elif text.lower().startswith("/iptal"):
                    if _bt_proc is not None and _bt_proc.poll() is None:
                        _bt_proc.terminate()
                        send_message("🛑 Backtest durduruldu.")
                    else:
                        send_message("Çalışan backtest yok.")
        except Exception as e:
            log.error("Komut dinleme hatası: %s", e)
            time.sleep(5)


def start_listener():
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        return
    threading.Thread(target=_listen, daemon=True).start()
