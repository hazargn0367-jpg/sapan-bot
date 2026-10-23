"""
Telegram komutları (bot arka planda dinler):
  /oto            -> otomatik işlem durumu (bakiye, açık işlemler, bugünkü R)
  /oto aç | kapat -> Binance'te otomatik işlemi aç / kapat (1R = AUTO_RISK_USD, varsayılan 15$)
  /ip             -> botun internet çıkış IP'si (Binance API izin listesine eklenecek)
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
  /backtest 30 tp -> erken çıkış (2 mum) ile TP 1:1.5 / 2.2 / 3 / 4 / 5 + işlemlerin stop olmadan önce kaç R gittiği
  /backtest 90 temiz -> TP ile stop olan işlemler arasındaki farklar (bacak, EMA açılımı, önceki tepeye mesafe...)
                        + temiz trend filtreleri karşılaştırması ('dönüş temiz' yazılırsa dönüş varyasyonuyla)
  /backtest 180 dönüş temiz -> DÖNÜŞ varyasyonu 6 ay: temiz trend filtreleri + aday kurallar + TP/stop fark analizi
  /backtest 30 canlı erken 2 sene önce -> canlı ayar + erken çıkış (2 mum), 2 yıl önceki 30 gün, bütün işlemler PDF
  /backtest 180 yeniden seri -> erken çıkıştan sonraki 1. mumda (ya da 2 mum içinde) giriş seviyesi yeniden geçilirse tekrar gir, bugünkü kurallar (+ "yeniden seri 3 sene önce")
  /backtest 180 kilit seri -> TP 2.2'de kapatmak yerine stop +1.8 / +1.5R'ye (kâr kilidi), hedef 3 / 4 / 5R (+ "kilit eski seri")
  /backtest 180 hedef seri -> onay mumu büyükse (gövde ≥ 0.5 / 0.65 ATR) TP 2.5 / 3, diğerleri 2.2
  /backtest 180 hedef eski seri -> aynı test hiç bakılmamış 2 eski dönemde (önceki5 + önceki6, 2023-2024); "eski" her testte çalışır
  /backtest 180 toplu -> toplu sinyal sınırı 5 (canlı) / 8 / 10 / kapalı; grafikler: 10 coin sınırının canlıya göre EKLEDİĞİ işlemler (+ "seri", "eski seri")
  /backtest 180 kırılım seri -> ayrı sinyal: tepe/dip kırılımı sonrası seviyeye geri testte giriş (sadece / canlı + kırılım varyasyonları) (+ "kırılım eski seri")
  /backtest 180 üst seri -> 15dk sinyalde 1s / 4s trend onayı şartı (canlı · 1s · 1s hafif · 4s · 4s hafif · ikisi) (+ "üst eski seri")
  /backtest 180 ikinci seri -> tepeden sonra 2. / 3. EMA20 temasına da izin (işlem sayısı artar mı, R düşer mi) (+ "ikinci eski seri"; CSV'de temas_no)
  /backtest 180 ema seri -> temas EMA50 / EMA100 + yapı kuralları (kural 8 ve son salınım tepesi/dibi; iğne/kapanış); tek dönem `ema` grafikler EMA50 (son salınım, iğne), `ema yüz` EMA100 (+ "ema eski seri")
  /backtest 180 analiz seri -> sadece canlı ayar, 5 dönem; CSV'de hacim ölçüleri (hac_bacak, hac_duz, hac_oran, hac_onay ...). İlk çalıştırma veriyi hacimle yeniden indirir (uzun sürer)
  /backtest 180 açık seri -> − kural 4 / en fazla 3-4 işlem / ikisi birlikte (işlem sayısı); "açık seri 3 sene önce", "açık kayık seri"
  /backtest 180 sade seri -> kural 4 / 1R yer / kural 6 / kural 1 birlikte kalkar (işlem sayısı); "sade seri 3 sene önce", "sade kayık seri"
  /backtest 180 sağlam seri -> sağlamlık süzgeci: canlı kurallar tek tek kalkar + temel; aynı test "sağlam seri 3 sene önce", "sağlam kayık seri", "sağlam mexc seri"
  /backtest 180 kayık seri -> aynı kurallar 5 / 10 dk kaydırılmış 15dk mumlarda; ayrı ayrı ve üçü birlikte (en fazla 2 / 4 işlem). Veri 5dk (ilk çalıştırma uzun)
  /backtest 180 yaş seri -> trend yaşı ≥ 60 / 76 / 100 mum (genç trende girme), ≥76 + erken çıkışsız, sadece erken çıkışsız (+ "yaş seri 3 sene önce" = 2021-2023)
  /backtest 180 ilk seri -> kural 2 (trend teyidi) sadece dönüşte / sadece klasikte / hiç uygulanmaz (+ "ilk eski seri")
  /backtest 180 çoklu seri -> aynı kurallar 15dk + 30dk / 1s birlikte (toplam en fazla 2 / 3 işlem, coinde tek işlem); sadece 30dk (+ "çoklu eski seri")
  /backtest 180 geri seri -> giriş tetiklenmeden fiyat onay mumunun ortasına / üst 1/3'üne / 3/4'üne geri gelirse emir iptal (+ "geri eski seri")
  /backtest 180 limit seri -> dönüşte TP 3; onaydan sonra limit giriş (onay ortası / üst 1/3, TP aynı fiyat ya da 2.2 × yeni risk, 4 mum bekleme, erken çıkışsız) (+ "limit eski seri")
  /backtest 180 fitil seri -> kapanışta stop (sert stop 1.5 / 2R), 1.5R'de stop +0.5R, 1R'de stop -0.5R (+ "fitil eski seri")
  /backtest 180 orta seri -> büyük onay mumunda (≥ 1 / 0.7 / 1.3 ATR) stop onay mumunun ortasında; stop en fazla 1 ATR (+ "orta eski seri")
  /backtest 180 aria -> canlı ayar, grafikler sadece ARIA benzeri işlemlerden (pompa tepe ≥ 4 ATR + iğneli düzeltme): 15 TP + 15 stop + hepsi PDF (+ "önceki")
  /backtest 180 çıkış seri -> erken çıkış: canlı (2 mum, 0.35) / yok / 1 mum / derin eşik 0.2 / 0.5 ATR (+ "çıkış eski seri")
  /backtest 180 hemen seri -> onay mumunu beklemeden giriş (temas mumunun tepesi kırılınca) (+ "hemen eski seri")
  /backtest 180 geniş seri -> stop payı 0.3 (canlı) / 0.45 / 0.6 / 0.8 ATR ve stop temas mumunun dibinde (+ "geniş eski seri")
  /backtest 180 pay seri -> stop payı 0.3 (canlı) / 0.15 / 0 / 0 + erken çıkış yok (+ "pay eski seri" = 2 eski dönem)
  /backtest 180 çizgi seri -> dönüş mumu EMA20'nin en az 0.1 / 0.2 / 0.3 ATR ötesinde kapatmalı (tam çizgide kapatan dönüş yok)
  /backtest 180 temel seri -> herhangi bir karşılaştırma testinin sonuna "seri" yazılırsa 5 dönem arka arkaya çalışır, sonunda özet
  /backtest 180 temel -> temas tanımının temel ayarları: stoch 40/60 · stoch yok · ters mum 3/4 · tepe 45 mum · tolerans %0.15
  /backtest 180 dalga -> temastan önceki 12 mum büyük gövdeyle sürekli yön değiştiriyorsa girme (AXL örneği)
  /backtest 180 başla seri -> kural 2: teyit teması EMA20>EMA50 olduğu andan sayılır (EMA100 beklenmez), kalkış 1.5 / 1 ATR (+ "3 sene önce", "kayık")
  /backtest 180 iki mum -> 2 mumlu temas her sıra (dip 1. ya da 2. mumda), iki mum EMA20'de döner, onay iki mumun en tepesinin üstü
  /backtest 180 trend -> ikinci strateji adayı: trend takibi (Donchian kırılımı 20/50/100, en likit 30-60 coin, günlük/4s)
  /backtest 180 forex -> canlı kurallar forex / altın / endeks / petrolde (Dukascopy, 39 enstrüman), 15dk · 30dk · 1s · 2s · 4s ayrı, canlı + kurallarsız (+ "forex seri")
  /backtest 180 mexc -> canlı kurallar MEXC'teki bütün USDT vadeli coinlerde (~1000): bütün / Binance'te de olanlar / sadece MEXC'te olanlar (+ "mexc seri"; komisyon API %0.08)
  /backtest 180 bybit -> canlı kurallar Bybit'teki bütün USDT vadeli coinlerde; Binance'te olmayanlar ayrı (yeni işlemler)
  /backtest 180 bybit gelişim -> herhangi bir test Bybit verisiyle (canlı botun Binance coinlerinde, aynı coinler başka borsa verisi)
  /backtest 180 gelişim önceki3 -> 15.10'da eklenen kurallar sırayla, hiç bakılmamış dönemde (önceki4 = bir öncesi)
  /backtest 180 esnet önceki3 -> önünde yer / kural 5 esnetmeleri; önceki3 = 3 dönem önceki 180 gün (hiç bakılmamış)
  /backtest 180 artır -> işlem sayısını artırma: canlı kurallar tek tek kaldırılır / gevşetilir (11 ayar)
  /backtest 180 toplu -> toplu sinyal eşiği 5 / 8 / 10 coin / kapalı / kapalı + en fazla 5 işlem (şimdiki canlı sistem)
  /backtest 180 teyit -> kural 2 (trend teyidi) düzeltmesi: önceki temas, fiyat EMA20'den 0.5 / 1 / 1.5 ATR ayrıldıktan sonra
  /backtest 180 gemini -> Gemini kodundaki şartlar: EMA100 > EMA200 ve son 4 / 8 mumda 24 saatin zirvesi
  /backtest 180 giriş -> girişi onay ucundan 0.1 / 0.2 ATR öteye al (stopla birlikte de), şimdiki canlı sistemle
  /backtest 180 stop -> stop payı 0.15 / 0, stop en fazla 1 / 1.2 ATR, derin geri kapanışta erken çıkış yok (0.35 / 0.5 ATR)
  /backtest 180 dilim 30m -> yeni canlı ayar 30m'de (iki yeni kurallı / kuralsız); 5m için /backtest 90 dilim 5m
  /backtest 180 eleme -> iğne oranı ≤ %58 ve dip/tepe 1 ATR bandında ≤ 4 mum (ayrı + birlikte); önceki, önceki2 ile 3 dönem
  /backtest 180 grafik -> grafik örnekleri: iğneli git-gel mumlar, temiz dip/tepe bandı, dönüşte büyük temas mumu (ayrı ayrı)
  /backtest 180 kapanış -> erken çıkış zararı: kapanışla giriş (sahte kırılım mumuna girme) ve ilk 2 mumda 0.3R erken stop
  /backtest 180 gevşet -> canlı 15m ayardan eski kurallar (1, 2, 4, 5, 6) ve 03-07 saat filtresi tek tek kaldırılır (daha çok işlem)
  /backtest 180 yatay -> şimdiki canlı sistem + 4 / 8 / 12 saatte sonuç yoksa stop girişe + zigzag düzeltme yok
  /backtest 180 yer -> önünde en az 1R yer (+ EMA açıklığı 2 / 1.5 ATR), onay ≤ 2 + stop ≥%0.5 + erken çıkış; 5m: /backtest 90 yer 5m
  /backtest 180 renk -> erken çıkış sadece ters renkli mumda (LONG'da kırmızı kapanış); 5m için /backtest 90 renk 5m
  /backtest 30 komisyon 5m -> onay ≤ 2. mum tabanında TP 2.5 ve en az %0.5 stop (komisyon payı küçülsün)
  /backtest 30 sivri 5m -> onay en geç 2. mumda + sivri tepe (2 dev mumla yapılan tepe) yok, erken çıkış üstüne
  /backtest 180 başabaş -> şimdiki canlı sistemle fiyat 1R / 1.5R / 2R kâra gelince stopu girişe çekme
  /backtest 180 örnek -> PDF örneklerinden kurallar (dip tabanı, önünde yer, büyük onay mumu, temas mumu) erken çıkış üstüne
  /backtest 180 erken -> giriş mumu girişin gerisinde kapatırsa çık (1 / 2 mum) + BTC'ye benzerlik filtresi, ay ay + PDF
  /backtest 180 btc -> BTC'ye benzer hareket eden coinlere girmeme filtresi (canlı ayar, 0.8 / 0.6 / 0.4) + fark analizi
  /backtest 180 tarama -> orijinal ve canlı kurallar 15dk / 30dk / 1s / 4s'te, büyük / orta / küçük coinlerde ayrı ayrı
                          kazanma oranı (dönemin iki yarısı ayrı), TP 1:2
  /backtest 90 aday önceki2 -> iki dönemde tutan aday kurallar (bacakta ters mum az, düzeltme ≥ 5 mum, bacak < 4 ATR),
                               önceki2 = iki dönem önceki 90 gün (hiç bakmadığımız dönem)
  /backtest 90 dönüş kural -> dönüş varyasyonu + zaman stopu (8 saat) / kural 11 (temiz yükseliş) / kural 7, ay ay
  /backtest 14 dönüş -> dönüş varyasyonu: temas EMA20'nin öbür tarafında kapatır, sonraki mum geri alır, ondan sonraki onay
  /backtest 30 canlı 5m -> canlı ayarın aynısı (klasik + dönüş birlikte, 5 dakikalık grafik)
  /backtest 90 canlı -> canlı bildirimlerdeki ayarın aynısı, tüm işlemlerin grafikleri PDF
  /backtest 90 dip -> canlı ayar + önceki tepe/dibe mesafe (0.5/1/1.5/2.2R), ay ay
  /backtest 90 yapı -> kural 7 (önünde yer) ve kural 8 (yapı bozulmamış), ay ay + grafik PDF
  /backtest 7 canlı 5m -> canlı ayar 5 dakikalık grafikte (sona 5m yazılırsa her test 5m'de çalışır)
  /backtest 30 iğne 5m -> kural 10 (temas mumunun ters iğnesi) ve kural 7 (önünde yer)
  /backtest 90 destek -> kural 9 (dip/tepeden sonra iğneli mumlar = destek/direnç), ay ay + grafik PDF
  (varsayılan: hacmi en yüksek 500 coin, canlı bildirimlerle aynı; 'tüm' yazılırsa hepsi)
  /durum          -> backtest ilerlemesi + canlı tarama + günlük (Girdim/Girmedim sonuçları)
  /incele AXSUSDT 01.08.2026 02:00 -> bir işlemin tüm kurallardaki değerlendirmesi + grafik (TR saati, 15m)
  /incele AXSUSDT 13.10 22:05 5m  -> 5 dakikalık canlı bildirimi incele
  /iptal          -> çalışan backtest'i durdurur
  /bildirim aç | kapat -> EMA20 temas bildirimleri
  /sinyal aç | kapat -> kurallara uyan setup'larda EMİR HAZIR bildirimleri
  /temas -> son 15dk ve 30dk taramasındaki EMA20 temasları ve neden işleme dönmedikleri
  /otuz aç | kapat -> 30dk bildirimleri (aynı kurallar, otomatik işlem yok, karar senin)
Sadece TELEGRAM_CHAT_ID'deki sohbetten gelen komutlar kabul edilir.
"""

import html
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
    yil = re.search(r"(\d+)\s*(yıl|yil|sene)", text.lower())   # "2 sene önce": dönemi o kadar yıl geriye kaydır
    clean = re.sub(r"\b(5m|15m|30m|5dk|5 dk)\b|son2|[öo]nceki[234]|\d+\s*(yıl|yil|sene)", " ", text.lower())
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
    if yil:
        args += ["--ago", str(int(yil.group(1)) * 365)]
    elif re.search(r"\beski\b", low):
        args += ["--ago", str(5 * days)]   # hiç bakılmamış eski dönemler: önceki5 (+ seride önceki6)
    elif "önceki4" in low or "onceki4" in low:
        args += ["--ago", str(4 * days)]   # dört dönem önce (5. bağımsız dönem)
    elif "önceki3" in low or "onceki3" in low:
        args += ["--ago", str(3 * days)]   # üç dönem önce (4. bağımsız dönem)
    elif "önceki2" in low or "onceki2" in low:
        args += ["--ago", str(2 * days)]   # iki dönem önce (3. bağımsız dönem)
    elif "önceki" in low or "onceki" in low:
        args += ["--ago", str(days)]
    donus = any(w in low for w in ("dönüş", "donus", "dönus", "varyasyon"))
    bybit_mode = "bybit" in low
    mexc_mode = "mexc" in low
    if bybit_mode:
        args += ["--exchange", "bybit"]
    elif mexc_mode:
        args += ["--exchange", "mexc"]   # (yorum yukarıda)
    elif re.search(r"\bforex\b|\bfx\b", low):
        args += ["--exchange", "fx"]   # 23.10: forex / metal / endeks (Dukascopy), 15dk-4s   # 23.10: MEXC'teki bütün USDT vadeli coinler (veri MEXC'ten, kaydedilmez)   # veri Bybit'ten; başka set yazılmadıysa "bybit" seti (yeni / ortak coinler)
    if re.search(r"\bkontrol\b", low):
        args += ["--compare", "kontrol"]   # 16.10 canlıya alınan gövde + düzeltme kuralı kontrolü
    elif re.search(r"\byeniden\b", low):
        args += ["--compare", "yeniden"]   # erken çıkıştan sonra yeniden giriş (16.10 23:29)
    elif re.search(r"\bkilit\b", low):
        args += ["--compare", "kilit"]   # 2.2R'de stop kâra (+1.8 / +1.5R), hedef 3 / 4 / 5R (16.10 22:59)
    elif re.search(r"\bhedef\b", low):
        args += ["--compare", "hedef"]   # onay mumu büyükse TP 2.5 / 3 (16.10 22:09)
    elif re.search(r"\b[çc]izgi\b", low):
        args += ["--compare", "cizgi"]   # dönüş mumu EMA20'den en az 0.1 / 0.2 / 0.3 ATR ötede kapatmalı (ESP 30.08)
    elif re.search(r"\banaliz\b", low):
        args += ["--compare", "analiz"]   # sadece canlı ayar, CSV ölçüleri için (seri ile 5 dönem)
    elif re.search(r"\btemel\b", low):
        args += ["--compare", "temel"]   # temas sinyalinin temel ayarları (stoch, ters mum, tepe yakınlığı, tolerans)
    elif "dalga" in low:
        args += ["--compare", "dalga"]   # dalgalı bölge (renk değişimi + büyük gövde) filtresi
    elif re.search(r"iki\s*mum", low):
        args += ["--compare", "ikimum2"]   # 2 mumlu temas her sıra (16.10 02:07; ilk test: ikimum, sadece 2. mum dipte)
    elif re.search(r"\btrend\b", low) and "teyit" not in low:
        args += ["--trend"]   # ikinci strateji adayı: trend takibi (Donchian kırılımı)
    elif any(w in low for w in ("gelişim", "gelisim")):
        args += ["--compare", "gelisim"]   # bugün eklenen kurallar sırayla (dönem dışı sınama)
    elif "esnet" in low:
        args += ["--compare", "esnet"]   # artır testinden çıkan esnetmeler; önceki3 = hiç bakılmamış dönem
    elif any(w in low for w in ("artır", "artir", "arttır", "arttir")):
        args += ["--compare", "artir"]   # işlem sayısını artırma: canlı kurallar tek tek gevşetilir
    elif any(w in low for w in ("gevşet", "gevset", "gevşe")):
        args += ["--compare", "gevset"]
    elif re.search(r"\ba[cç][ıi]k\b", low):   # 23.10 17:23: − kural 4 ve/veya en fazla 3 / 4 işlem; "kayık" ile kaydırılmış mumlarda
        args += ["--compare", "acik_k" if re.search(r"\bkay[ıi]k\b", low) else "acik"]
    elif re.search(r"\bsade\b", low):   # 23.10: kural 4 / 1R yer / kural 6 / kural 1 birlikte kalkar; "kayık" ile kaydırılmış mumlarda
        args += ["--compare", "gevsek_k" if re.search(r"\bkay[ıi]k\b", low) else "gevsek"]
    elif re.search(r"\bsa[gğ]lam\b", low):   # 23.10: sağlamlık süzgeci (kurallar tek tek kalkar); "kayık" ile kaydırılmış mumlarda
        args += ["--compare", "saglam_k" if re.search(r"\bkay[ıi]k\b", low) else "saglam"]
    elif re.search(r"\bkay[ıi]k\b", low):   # 23.10: 5 / 10 dk kaydırılmış 15dk mumlar (işlem sayısı)
        args += ["--compare", "kayik"]
    elif re.search(r"\bya[şs]\b", low):   # 23.10: trend yaşı (genç trende girme) + erken çıkışsız
        args += ["--compare", "yas"]
    elif re.search(r"\bba[sş]la\b", low):   # 24.10: kural 2'de trend başlangıcı EMA20>EMA50 (EMA100 beklenmez); "kayık" ile kaydırılmış mumlarda
        args += ["--compare", "basla_k" if re.search(r"\bkay[ıi]k\b", low) else "basla"]
    elif re.search(r"\bilk\b", low):   # 23.10: teyitsiz ilk temas: kural 2 sadece dönüşte / klasikte / hiç yok
        args += ["--compare", "teyit2"]
    elif "teyit" in low:
        args += ["--compare", "teyit"]
    elif "gemini" in low:
        args += ["--compare", "gemini"]
    elif re.search(r"\bgiri[şs]\b", low):
        args += ["--compare", "giris"]
    elif re.search(r"k[ıi]r[ıi]l[ıi]m", low):   # 20.10: kırılım + geri test sinyali
        args += ["--compare", "kirilim"]
    elif re.search(r"\b[üu]st\b", low):   # 20.10: 1s / 4s trend onayı
        args += ["--compare", "ust"]
    elif re.search(r"\bikinci\b", low):   # 20.10: 2. / 3. EMA20 temasına da izin
        args += ["--compare", "ikinci"]
    elif re.search(r"\bema\b", low):   # 17.10: temas EMA50 / EMA100 ("yüz": grafikler EMA100 satırından; rakam RR sanılmasın)
        args += ["--compare", "ema100" if re.search(r"y[üu]z", low) else "ema"]
    elif re.search(r"\b[çc]oklu\b", low):   # 22.10: 15dk + 30dk / 1s birlikte (işlem sayısı)
        args += ["--compare", "coklu"]
    elif re.search(r"\bgeri\b", low):   # 22.10: girişten önce onay içine geri gelirse iptal
        args += ["--compare", "geri"]
    elif re.search(r"\blimit\b", low):   # 22.10: dönüşte TP 3 + geri çekilmede limit giriş
        args += ["--compare", "limit"]
    elif re.search(r"\bfitil\b", low):   # 22.10: iğne stoplarına karşı kapanışta stop / kârda stop yaklaştırma
        args += ["--compare", "igne2"]
    elif re.search(r"\borta\b", low):   # 21.10 22:48: büyük onay mumunda stop onay ortasında
        args += ["--compare", "orta"]
    elif re.search(r"\baria\b", low):   # 21.10: ARIA benzeri işlemlerin grafikleri
        args += ["--compare", "aria"]
    elif re.search(r"\b[çc][ıi]k[ıi][şs]\b", low):   # 21.10 00:21: erken çıkış yeniden (bugünkü kurallarla)
        args += ["--compare", "cikis"]
    elif re.search(r"\bhemen\b", low):   # 20.10 23:29: onay mumunu beklemeden giriş
        args += ["--compare", "hemen"]
    elif re.search(r"\bgeni[şs]\b", low):   # 20.10 22:17: stop payı 0.45 / 0.6 / 0.8 ATR + temas dibi
        args += ["--compare", "pay2"]
    elif re.search(r"\bpay\b", low):
        args += ["--compare", "pay"]   # 17.10 12:02: stop payı 0.3 / 0.15 / 0 / 0 + erken çıkış yok
    elif re.search(r"\bstop\b", low):
        args += ["--compare", "stop"]
    elif re.search(r"\bdilim\b", low):
        args += ["--compare", "dilim"]
    elif re.search(r"\beleme\b", low):
        args += ["--compare", "grafik2"]
    elif re.search(r"\bgrafik\b", low):
        args += ["--compare", "grafik"]
    elif any(w in low for w in ("kapanış", "kapanis", "kapaniş", "kapanıs")):
        args += ["--compare", "kapanis"]
    elif "yatay" in low:
        args += ["--compare", "yatay2"]   # 15.10 17:21: şimdiki canlı sistemle (eski set: yatay)
    elif re.search(r"\byer\b", low):
        args += ["--compare", "yer"]
    elif "renk" in low:
        args += ["--compare", "renk"]
    elif "komisyon" in low:
        args += ["--compare", "komisyon"]
    elif "sivri" in low:
        args += ["--compare", "sivri"]
    elif any(w in low for w in ("başabaş", "basabas", "başabas", "basabaş")):
        args += ["--compare", "basabas2"]   # 15.10 15:19: şimdiki canlı sistemle (eski set: basabas)
    elif ("canlı" in low or "canli" in low) and "erken" in low:
        args += ["--preset", "canli_erken"]
    elif any(w in low for w in ("örnek", "ornek", "pdf")):
        args += ["--compare", "ornek"]
    elif "erken" in low:
        args += ["--compare", "erken"]
    elif any(w in low for w in ("btc", "bitcoin", "korelasyon")):
        args += ["--compare", "btc"]
    elif "tarama" in low:
        args += ["--compare", "tarama", "--tf", "15m,30m,1h,4h"]
        tf_m = None   # zaman dilimleri taramanın kendisi
    elif any(w in low for w in ("temiz", "fark", "aday")) and donus:
        args += ["--compare", "temiz_donus"]   # dönüş: temiz trend + adaylar tek testte
    elif "aday" in low:
        args += ["--compare", "aday"]
    elif "temiz" in low:
        args += ["--compare", "temiz_donus" if donus else "temiz"]
    elif "iğne" in low or "igne" in low:
        args += ["--compare", "igne"]
    elif "toplu" in low:
        args += ["--compare", "toplu2"]   # 15.10 19:15: şimdiki canlı sistemle (eski set: toplu)
    elif "destek" in low:
        args += ["--compare", "destek"]
    elif "yapı" in low or "yapi" in low:
        args += ["--compare", "yapi"]
    elif re.search(r"\bdip\b", low):
        args += ["--compare", "dip"]
    elif any(w in low for w in ("dönüş", "donus", "dönus", "varyasyon")):
        if any(w in low for w in ("kural", "hepsi", "karşılaştır", "karsilastir")):
            args += ["--compare", "donus"]
        else:
            args += ["--preset", "donus"]
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
    if re.search(r"\bseri\b", low) and "--compare" in args:
        # 5 dönem arka arkaya (bugün, önceki ... önceki4) + sonunda özet; "eski seri": önceki5 + önceki6
        args += ["--seri", "2" if re.search(r"\beski\b", low) else "5"]
    if bybit_mode and "--compare" not in args and "--preset" not in args:
        args += ["--compare", "bybit"]
    if mexc_mode and "--compare" not in args and "--preset" not in args:
        args += ["--compare", "borsa"]
    if "fx" in args and "--compare" not in args and "--preset" not in args:
        args += ["--compare", "forex"]
    if re.search(r"\bseri\b", low) and "--compare" in args and "--seri" not in args:
        args += ["--seri", "2" if re.search(r"\beski\b", low) else "5"]
    if "fark" in low:
        args += ["--fark"]   # TP / stop arasındaki farkların ayrıntılı analizi (uzun mesaj), sadece istenince
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
            progress = html.escape(lines[-1].split(" INFO ")[-1].split(" ERROR ")[-1][:300], quote=False)
    except OSError:
        pass
    if running:
        return (f"⏳ Backtest çalışıyor ({html.escape(_bt_cmd, quote=False)})"
                + (f": {progress}" if progress else ", veri çekiliyor..."))
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
            return "⚠️ Son backtest hatayla kapandı:\n" + html.escape("\n".join(tail)[-900:], quote=False)
        return "✅ Son backtest bitti." + (f"\nSon satır: {progress}" if progress else "")
    return "Çalışan backtest yok. Başlatmak için: /backtest"


def _on_button(cq):
    """EMİR HAZIR altındaki "Girdim / Girmedim" düğmesi."""
    import journal
    from telegram import answer_callback, decision_buttons, edit_buttons
    msg = cq.get("message") or {}
    chat_id = (msg.get("chat") or {}).get("id")
    if str(chat_id) != str(config.TELEGRAM_CHAT_ID):
        return
    data = cq.get("data") or ""
    kind, _, key = data.partition("|")
    decision = {"g": "girdim", "n": "girmedim"}.get(kind)
    if not decision or not key:
        answer_callback(cq["id"])
        return
    s = journal.set_decision(key, decision)
    if s is None:
        answer_callback(cq["id"], "Bu bildirim günlükte yok")
        return
    answer_callback(cq["id"], "Kaydedildi: " + ("Girdim" if decision == "girdim" else "Girmedim"))
    edit_buttons(chat_id, msg.get("message_id"), decision_buttons(key, decision))


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
            params = {"timeout": 30, "allowed_updates": '["message", "callback_query"]'}
            if offset is not None:
                params["offset"] = offset
            updates = requests.get(url, params=params, timeout=40).json().get("result", [])
            for u in updates:
                offset = u["update_id"] + 1
                if u.get("callback_query"):
                    _on_button(u["callback_query"])
                    continue
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
                    import journal
                    import autotrade
                    try:
                        oto = autotrade.status_text().split("\n")[0]
                    except Exception as e:
                        oto = f"🤖 Otomatik işlem: durum okunamadı ({html.escape(str(e))[:100]})"
                    import live_alt
                    send_message(f"{status_text()}\n\n{live_setups.status_text()}\nEmir bildirimleri: {sig}\n{oto}"
                                 f"\n{live_alt.status_text()}"
                                 f"\n\n{journal.summary()}"
                                 f"\n\n{exchanges.status_line()}\n\n{memwatch.status_line()}"
                                 f"\n\n🏷 Sürüm: {html.escape(config.version_text(), quote=False)}")
                elif text.lower().startswith("/temas"):
                    import live_setups
                    import live_alt
                    send_message(live_setups.touch_list_text(f"Son temaslar {live_setups.LIVE_TF}", live_setups.TF_MIN,
                                                             live_setups._stats.get("touch_list"), live_setups._active))
                    send_message(live_setups.touch_list_text(f"Son temaslar {live_alt.TF}", live_alt.TF_MIN,
                                                             live_alt._stats.get("touch_list"), live_alt._active))
                elif text.lower().startswith("/otuz"):
                    import live_alt
                    low = text.lower()
                    if "kapa" in low:
                        live_alt.ENABLED = False
                    elif "aç" in low or "ac" in low:
                        live_alt.ENABLED = True
                    send_message(f"🔔 {live_alt.TF_MIN}dk bildirimleri (otomatik işlem yok) "
                                 + ("açık" if live_alt.ENABLED else "kapalı") + ". (Bot yeniden başlarsa açık başlar.)")
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
                elif text.lower().split()[0].split("@")[0] == "/ip":   # /iptal ile karışmasın
                    import autotrade
                    send_message(autotrade.ip_text())
                elif text.lower().startswith("/oto"):
                    import autotrade
                    try:
                        send_message(autotrade.command(text))
                    except Exception as e:
                        send_message(f"⚠️ /oto hatası: {html.escape(str(e))[:300]}")
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
