"""
Backtest örnek grafikleri (15 TP + 15 stop) temiz bir süreçte çizilir.

500 coinin verisini işleyen backtest süreci bitince bellekte ~400MB tutmaya devam eder (Python boşalan belleği
sisteme tam geri vermez); grafik çizimi bunun üstüne binince 512MB sınırına dayanıyordu. Bu yüzden backtest.py
en sonda kendini bu programa çevirir (os.execv: aynı süreç numarası, bellek sıfırdan başlar).
"""

import logging
import os
import pickle
import shutil
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")


def main(path, name, n_each=15):
    from telegram import send_message, send_photos
    folder = "/tmp/bt_charts"
    try:
        with open(path, "rb") as f:
            recs = pickle.load(f)
        os.remove(path)
        import charts
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder, exist_ok=True)
        wins, losses = charts.make_samples(recs, folder, n_each)
        del recs
        label = f" ({name})" if name else ""
        for kind, paths in (("TP", wins), ("STOP", losses)):
            for k in range(0, len(paths), 10):
                part = paths[k:k + 10]
                send_photos(part, f"{kind} örnekleri{label}: {k + 1}-{k + len(part)} / {len(paths)} "
                                  f"(dönem boyunca eşit aralıklı)")
        log.info("Örnek grafikler gönderildi: %d TP, %d stop", len(wins), len(losses))
    except Exception as e:
        log.exception("Grafikler oluşturulamadı")
        send_message(f"⚠️ Grafikler oluşturulamadı: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
