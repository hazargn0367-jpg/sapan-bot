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


PDF_MAX = 500   # bir PDF'te en fazla bu kadar işlem (fazlası ayrı dosyalara bölünür)


def main(path, name, n_each=15):
    from telegram import send_document, send_message, send_photos
    folder = "/tmp/bt_charts"
    try:
        with open(path, "rb") as f:
            recs = pickle.load(f)
        os.remove(path)
        import charts
        shutil.rmtree(folder, ignore_errors=True)
        os.makedirs(folder, exist_ok=True)
        wins, losses = charts.make_samples(recs, folder, n_each)
        label = f" ({name})" if name else ""
        for kind, paths in (("TP", wins), ("STOP", losses)):
            for k in range(0, len(paths), 10):
                part = paths[k:k + 10]
                send_photos(part, f"{kind} örnekleri{label}: {k + 1}-{k + len(part)} / {len(paths)} "
                                  f"(dönem boyunca eşit aralıklı)")
        log.info("Örnek grafikler gönderildi: %d TP, %d stop", len(wins), len(losses))
        shutil.rmtree(folder, ignore_errors=True)
        # Bütün işlemlerin grafikleri PDF olarak (tarih sırasıyla, ilk sayfalarda numaralı liste)
        recs.sort(key=lambda r: r.get("_touch_ts", 0))
        parts = [recs[k:k + PDF_MAX] for k in range(0, len(recs), PDF_MAX)]
        for no, part in enumerate(parts, 1):
            pdf_path = f"/tmp/bt_grafikler_{no}.pdf"
            charts.make_pdf(part, pdf_path)
            n_win = sum(r["durum"] == "win" for r in part)
            extra = f" (parça {no}/{len(parts)})" if len(parts) > 1 else ""
            send_document(pdf_path, f"Bütün işlemlerin grafikleri{label}{extra}: {len(part)} işlem, {n_win} TP. "
                                    f"İlk sayfalarda numaralı liste, sonra her işlem bir sayfa (tarih sırasıyla).")
            os.remove(pdf_path)
        log.info("PDF gönderildi: %d işlem, %d parça", len(recs), len(parts))
    except Exception as e:
        log.exception("Grafikler oluşturulamadı")
        send_message(f"⚠️ Grafikler oluşturulamadı: {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "")
