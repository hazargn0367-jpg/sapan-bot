# Sapan Bot – Proje Notları

Son güncelleme: 13.10.2026 (ilk çalışma gecesi)

## Sistem ne yapıyor
- Render'da (Frankfurt, Background Worker) çalışan Python botu. Veri: Binance USDT-M vadeli.
- **EMİR HAZIR bildirimleri** (`live_setups.py`): Her 15dk mum kapanışında hacmi en yüksek 500 coin taranır.
  Aşağıdaki tüm kuralları geçen setup'ta onay mumu kapanınca Telegram'a giriş/stop/TP, pozisyon
  büyüklüğü, grafik ve TradingView linki gider. Sonra giriş / iptal / TP / stop takip mesajları gelir.
  İşlem açmaz; kullanıcı kendisi karar verip açar.
- EMA20 temas bildirimleri varsayılan kapalı (`/bildirim aç`).
- Backtest Telegram'dan çalışır (`/backtest ...`), sonuç + CSV + grafikler Telegram'a gelir.
- Gizli bilgiler (Telegram token, chat id) Render Environment'ta, kodda yok.

## Temel strateji (kullanıcının ilk kuralları – "Taban")
- Trend: EMA20 > EMA50 > EMA100, aralarında en az %0.1 (SHORT tersi)
- Son 150 mumun tepesi son 30 mum içinde, önceki zirveyi gövde kapanışıyla kırmış
- Tepeden sonra EMA20'ye ilk temas, geri çekilmede en fazla 2 ters mum
- Temas mumu: iğnesi EMA20'ye değer (%0.03 tolerans), EMA20'nin üstünde kapatır; Stoch(5,3) LONG < 30, SHORT > 70
- Onay: sonraki 3 mum içinde temas mumunun tepesinin üstünde kapatan ilk mum; o ana kadar temas dibinin altına inilmez
- Giriş: onay tepesi + 1 tık; Stop: onay dibi − 1 tık; TP: 1:2 (canlıda 1:2.2: komisyon sonrası TP ~+2R, stop ~-1.12R)
- ATR(14, RMA): giriş-stop ≤ 1.5 ATR
- Giriş emri 2 mum geçerli; girişten önce onay dibinin altına inilirse iptal
- Mum içi belirsizlikte temkinli: aynı mumda stop+TP → stop

## Grafik incelemesinden eklenen kurallar (canlı bildirimde hepsi açık)
1. Onay mumunda ters iğne (LONG'da üst) gövdeden uzun olmayacak (`WICK_MAX_BODY=1.0`)
2. Trend teyidi: trend başladıktan ve fiyat EMA20'den ayrıldıktan sonra, tepeden önce en az bir EMA20 teması (`REQUIRE_PRIOR_TOUCH`)
3. Stop payı: stop onay mumunun ucundan 0.3 ATR öteye (`STOP_BUFFER_ATR=0.3`)
4. Temiz tepe/dip: son tepe/dip seviyesine (±0.3 ATR) 3+ mum dokunmuşsa girme (`CLEAN_PIVOT_MAX=3`)
5. Temas mumu fitil mumu: EMA20'ye doğru iğne ≥ gövde (`TOUCH_WICK_MIN=1.0`)
6. Tepe/dip mumunun o yöndeki iğnesi ≤ 2 gövde (`PIVOT_WICK_MAX=2.0`)
7. (test ediliyor, canlıda kapalı) Önünde yer: giriş ile önceki tepe/dip arası en az X R (`ROOM_MIN_R`), `/backtest 90 dip`
8. (test ediliyor, canlıda kapalı) Yapı bozulmamış: son tepeden sonraki düzeltme, son tepeden hemen önceki salınım
   tepesi (3+3 mum) ile son tepe arasındaki düzeltmenin dibini kırmamış olmalı (SHORT tersi) (`STRUCTURE_BREAK` = wick/close).
   İlk sürüm 150 mumun en yükseğini 'önceki tepe' alıyordu, kullanıcının örneklerini (NIL 31.07 23:30, AXS 01.08 02:00) yakalamadı; düzeltildi.
9. (test ediliyor, canlıda kapalı) Destek/direnç iğneleri: son dipten (SHORT) sonraki mumlar dibe doğru iğne bırakarak
   yükseldiyse orada alıcı var, girme (LONG'da tepeden sonra yukarı iğneler). Kullanıcı örneği NIL 31.07 23:30
   ("son dipten sonra 2 mum daha iğneli yükselmiş, destek yapmış"). Ayarlar: SUPPORT_N (kaç mum), SUPPORT_MIN (kaçı iğneli),
   SUPPORT_WICK_BODY (iğne ≥ gövdenin kaç katı), SUPPORT_WICK_ATR (iğne ≥ 0.1 ATR). `/backtest 90 destek`
- Portföy: aynı 15dk mumda 5+ coin aynı yönde temas verirse hiçbirine girme ("toplu sinyal", korelasyon/BTC hareketi)
- Saat: 03:00-07:00 TR (00-04 UTC) arası temaslar dikkate alınmaz (kullanıcı kararı; iki ayda da bu saatler kötüydü).
  6 kuralla birlikte iki ayda test edilecek: `/backtest 30 saat` ve `/backtest 30 saat önceki`

## Test sonuçları (1R = 25$, komisyon dahil: taker %0.05, maker %0.02)
Hacmi en yüksek 200 coin, 15dk, 1:2 (13.10 21:00 sonrası testler 500 coin):

| Ayar | 14.08–13.09 | 13.09–13.10 | Toplam |
|---|---|---|---|
| Taban | -52.5R | +8.9R | -43.6R |
| 1-4 + toplu | -10.5R | -14.1R | -24.6R |
| + fitil temas (5) | -3.6R | -14.4R | -18.1R |
| 1-6 + toplu | -4.8R | -10.9R | -15.6R |

Önemli bulgular:
- **Hiçbir ayar iki ayda birden kârlı değil.** Kurallar kötü ayda zararı azaltıyor ama iyi ayda kârı da azaltıyor (daha az işlem).
- Komisyon büyük etken: ortalama stop ~%0.7 → işlem başı ~0.12R komisyon.
- 1:2.5 / 1:3 ve başabaş stop genelde kötüleştirdi. BTC yön filtresi işe yaramadı. Toplu sinyal filtresi en iyi koruma.
- Saat ve stop-mesafesi filtreleri bir ayda iyi, diğerinde kötü çıktı (aşırı uyum) → kullanılmıyor.
- TradingView kullanıcıda farklı saat diliminde; bot TR ve UTC saatini birlikte yazar.
- Bot, kullanıcının NEARUSDT 10.10 örnek işlemini (14:00 TR, giriş 5.273, stop 5.235) birebir buldu.

- 03:00-07:00 TR filtresi iki ayda da iyileştirdi (canlı ayar: önceki ay -4.4R, son ay -6.4R; toplam -10.8R / 59 işlem).

- 13.10 06:00–12:20 arası canlı bildirimlerde hata: TP düzenlemesi FILTERS=False'u yoruma çevirdi, eski filtreler
  (03-11 TR ve stop %0.5-3) açık kaldı. Düzeltildi; açılış mesajı artık uygulanan kuralları listeler.

- 90 gün canlı ayar (1:2.2, 200 coin): 85 işlem, %23.5, -30.8R. Ay ay: -8.5R / -14.3R / -8.0R. LONG -24.4R, SHORT -6.4R.

- Kural 7 (önünde ≥1R yer), 90 gün: toplam -33R → -20R ama işlem başı aynı (-0.39R): sadece işlem sayısını azaltıyor.

- 13.10 17:42: canlı tarama ile backtest aynı anda Binance istek sınırına takıldı. Düzeltme: canlı tarama sadece
  15dk kapanışından sonraki ilk 60 sn'de başlar ve kendi iş parçacığında çalışır; backtest bu 120 sn'de bekler;
  429/418'de tüm istekler birlikte bekler.

- Kural 8 ikinci sürümde de NIL/AXS'yi yakalamadı. /incele AXS gösterdi ki önceki düzeltmenin dibi olarak salınım tepesi
  mumunun KENDİ dibi alınıyordu (0.837 = şimdiki dip). Düzeltme q'dan sonraki mumlardan başlatıldı (önceki düzeltme dibi 0.839 → bozuk).
- %40'ın sebebi: ilk 7 günlük test iyi haftalara denk geldi (taban haftalık kazanma %30-58 arası değişiyor).

- 13.10 18:4x Render bellek sınırı (512MB) aşıldı. Ölçüm: backtest 345MB + bot ~190MB. Düzeltme: backtest'te aynı anda en fazla
  12 coin verisi, karşılaştırmada sadece işlemler saklanır (→217MB); bot matplotlib'i sadece grafik çizerken yükler (→74MB),
  canlı tarama sadece gereken veriyi tutar; MALLOC_ARENA_MAX=2.
- 19:21'de bir bellek maili daha geldi (mailler tam 40 dk arayla: 18:01, 18:41, 19:21 → Render mailleri muhtemelen
  toplu gönderiyor, olay 18:54 yüklemesinden önce de olmuş olabilir). Ek önlem (memwatch.py): her 10 sn bot + backtest +
  kapsayıcı belleği ölçülür; toplam 435MB'ı geçerse backtest durdurulur (bot kapanmaz); bot tek başına 307MB'ı geçerse
  uyarı; /durum'da bellek satırı; bot yeniden başlarsa önceki çalışmanın son ölçümü açılış mesajında.
  Ayrıca /tmp veri önbelleği kaldırıldı, Binance sayfaları hemen sayı dizisine çevriliyor (gerçek JSON yoluyla ölçüm: 216 → 184MB).
- Kural 8 düzeltilmiş haliyle AXS'yi eliyor, ADA'yı tutuyor. Etkisi küçük: 83 işlemden 5'ini eledi (1 TP, net -2.3R).
  En iyi: 7 (1R) + 8 → 49 işlem, %28.6, -10.3R (işlem başı -0.21R); aylar -4.6 / +1.3 / -7.0.

- 13.10 20:48 ve 21:02: Binance 418 (IP geçici engeli). Backtest coin listesini alamayıp 0 coinle "bitti" dedi.
  Sebep: bot ve backtest ayrı programlar, birinin 429/418 beklemesini diğeri bilmiyordu; coin listesi/tık istekleri hiç
  beklemiyordu. Ayrıca Render'ın çıkış IP'si başka servislerle ortak olabilir (Binance sınırı IP başına).
  Düzeltme: bütün istekler tek yoldan (exchanges._get), bekleme /tmp/binance_pause dosyasında ortak; engel >10 dk ise
  backtest "⛔ durdu" der (0 coinle sonuç vermez), canlı tarama engel sürerken atlanır; /durum'da Binance satırı
  (IP'nin o anki kullanımı: bizim tarama yokken yüksekse IP ortak kullanılıyor).

- 21:25'te 500 coinlik backtest yine 418 aldı (14 dk). Çözüm: backtest geçmiş veriyi Binance dosya arşivinden
  (data.binance.vision, archive.py) çeker: tamamlanmış aylar aylık, bu ay günlük dosya; API'den sadece bugün ve arşivde
  olmayan kısım (coin başına ~1 istek, 2 ağırlık). Sahte arşiv/API ile veri birebir aynı çıktı. Arşive ulaşılamazsa API'ye döner
  (`--api` ile zorla API). Rapor sonunda "Veri: X arşiv dosyası, Y API parçası".

- 14.10 03:36: kullanıcı isteğiyle canlı tarama tekrar 15m (5m backtest iki ayda zararlı). Önceki not: 13.10 21:5x canlı EMİR HAZIR taraması 5 dakikalık grafikte (config.LIVE_TF, Render'da LIVE_TF ile değişir).
  Amaç kârlılık değil, canlı bildirimlerin kurallara uyduğunu daha sık görmek. Kurallar mum sayısıyla tanımlı, aynen geçerli.
  5m'de stoplar dar: %0.3'ten dar stoplu setup'lar elenir, komisyon payı 15m'den büyük. Backtest'ler hâlâ 15m.
  /incele için sona 5m: `/incele COIN 13.10 22:05 5m`.
- /backtest 90 destek (500 coin): canlı 261 işlem %33 -15.1R (işlem başı -0.06R; aylar -9.5/-8.9/+3.4).
  Kural 9 hiçbir varyasyonda işlem başı sonucu iyileştirmedi (elediği işlemler ortalama işlemler) → canlıya eklenmedi.
  500 coinde işlem başı sonuç 200 coinden (-0.31R) çok daha iyi. PDF çizerken bellek 458MB'a çıktı, bekçi durdurdu (PDF gelmedi).

- 22:1x: 500 coin canlı backtest bellek bekçisine takıldı (backtest 326MB). Düzeltmeler: tekli testte de sadece işlemler
  saklanır (huni sayaçla), her 25 coinde malloc_trim. Toplu sinyal filtresi artık backtest'te de canlıdaki gibi BÜTÜN temasları
  sayar (önceden karşılaştırma modunda sadece işleme dönenleri sayıyordu → filtre zayıftı).
- Hız: 15dk verisi /tmp/kline_cache'te (coin başına .npz, kesintisiz aralık); sonraki testler sadece yeni mumları çeker.
  Arşiv Render'da çalışmıyor görünüyor (IP kullanımı ~2000): sebebi artık "Backtest başladı" mesajındaki "Veri:" satırında.
  Backtest API'de dakikada en fazla 1500 ağırlık kullanır (canlı 5dk taramasına pay).

- 14.10 00:5x: canlı bildirimlerin takip listesi (_active) bellekteydi; yükleme/yeniden başlatmada kayboluyordu (OPN'in
  TP/stop mesajı gelmedi). Düzeltme: yeniden başlayınca ilk taramada son 60 mumdaki bildirilmiş ve sürmekte olan setup'lar
  (giriş bekleyen / işlemde) bulunur, toplu sinyal kontrolüyle takibe geri alınır ve "♻️" mesajıyla listelenir.

- 5m canlı ayar, 500 coin: 7 gün 29 işlem %34 -0.5R; 30 gün (14.09–13.10) 130 işlem %35.4 -1.1R (işlem başı -0.01R, brüt +17R,
  komisyon 0.14R/işlem). Haftalar -4.5/-13.0/+15.3/-7.2/+8.1. Toplu sinyalle elenen 141 işlem (89 farklı mum) %40 TP, ~+24.5R:
  5m'de bu ay filtre zarar ettirdi. 15m'de (f324b8b2) elenenler ~-1.4R. Test: `/backtest 30 toplu 5m` ve `/backtest 90 toplu`.

- 14.10 02:16 Binance 103 dk IP engeli (engeller uzuyor). Sebep: 5m canlı tarama 1000 ağırlık/5dk + backtest 1500 → sınır aşılıyor.
  Düzeltme: canlı tarama mumları bellekte tutar, her taramada son 40 mum (1 ağırlık) → ~500/tarama; backtest en fazla 1000/dk;
  yeni açılan bot ilk taramadan önce tek hafif istekle engel kontrolü. Arşiv zip'i pandas C ayrıştırıcıyla (bellek), havuz 12.
- 30 gün 5m toplu karşılaştırma: 5 coin -1.1R (130) | 8: -11.7R (166) | 12: -14.7R (182) | kapalı +16.3R (271; SHORT +21.9R).
  Kapalının kârı birkaç büyük toplu hareketten; tutarsız → değiştirilmedi. 15m 90 gün ve 5m önceki ay testi bekliyor.
- Kullanıcı isteği: aynı anda en fazla 2 işlem (MAX_OPEN=2). Canlıda giriş bekleyen + açık ≥2 ise yeni EMİR HAZIR yok, "⏸" mesajı.
  Backtest canlı ayarında max_open=2 (dolmuş işlemler, girişten çıkışa).

- Kural 10 (testte): temas mumunun ters iğnesi (SHORT'ta alt, LONG'da üst) uzun olmamalı (kullanıcı örneği 28.09 09:00 5m SHORT,
  ayrıca giriş dibe çok yakındı = kural 7). `/backtest 30 iğne 5m`: ≤ EMA iğnesi / ≤ yarısı / ≤ 0.3 ATR / kural 7 (1R) / 7+10.
- Binance API engelliyken backtest: coin listesi son kayıttan (universe.json) ya da arşivden (S3 listesi + dünkü 1d hacim),
  fiyat adımı yoksa 0, bugünün mumları atlanır. Binance'e hiç istek gitmez.

- Hız (14.10 02:4x): asıl yavaşlık hesaplamadaydı. strategy.evaluate_at numpy dizileriyle (pandas satır erişimi yerine),
  trade_rules'ta tablo kopyası yok → evaluate_at 19x hızlı, eski kodla 514 sinyalde birebir aynı sonuç. 5m 30 gün 120 coin
  yerelde 47sn/40 coin → 16sn/120 coin. Arşiv indirme havuzu 32, aynı anda 16 coin. Render'da kalıcı disk /var/data (1GB) eklendi.

- 5m önceki ay (15.08–13.09): 139 işlem %30.2 -29.8R (işlem başı -0.21R, brüt -5.8R). İki ay 5m: ~-31R / 269 işlem.
  Toplu sinyalle elenenler bu ay %19 TP (~-41R kaçınıldı) → filtre kalıyor. 15m 90 gün toplu: kapalı en kötü (-42R).
  Sonuç: mekanik kurallarda avantaj yok. Kullanıcının seçiminin değerini ölçmek için günlük eklendi.
- Günlük (journal.py, kalıcı diskte journal.json): her EMİR HAZIR altında "Girdim / Girmedim" düğmeleri; sonuçlar takipten
  yazılır; /durum'da "botun bütün bildirimleri / senin girdiklerin / girmediklerin" R toplamları.

- Dönüş varyasyonu (kullanıcı, 14.10 03:55): aynı sistem; temas mumu EMA20'ye değip EMA20'nin ÖBÜR tarafında kapatır (LONG'da
  altında), sonraki mum EMA20'nin doğru tarafında kapatır (dönüş), ondan sonraki mum dönüş mumunun tepesinin (LONG) üstünde kapatır
  = onay. Giriş/stop/TP/ATR/diğer kurallar aynı; kural 5 (fitil temas) uygulanmaz. trade_rules.ENTRY_MODE="reclaim",
  `/backtest 14 dönüş` (grafiklerde "Dönüş" mumu işaretli), `/incele COIN tarih saat dönüş`. Klasik mod eski kodla birebir aynı.

- Dönüş 14 gün (500 coin, 15m): 6 işlem, 2 TP, -0.1R. Kullanıcı stopları inceledi: TRUTH 02.10 10:45 (tepeye yakın, saatlerce
  yatay → 7-8 saatte sonuç yoksa stop girişe), VIRTUAL 05.10 09:30 (tepe tek mumda, temiz trend yok), HOLO 12.10 07:00 (giriş
  önceki tepenin dibinde). Eklenenler: TIME_STOP_BARS (32 mum=8 saat; fiyat gerideyse piyasadan çıkış, "be" sayılır),
  kural 11 PIVOT_LEG_MIN (tepe eski zirveyi kırdıktan sonra en az N mumla yapılmış). `/backtest 90 dönüş kural`.
- Dönüş kural 90 gün (17.07–12.10): dönüş 57 işlem %28 -12.4R (-0.22/işlem, klasik -0.20) · +8 saat -13.6R (1 stop
  kurtardı, 1 TP'yi başabaşa çevirdi) · +11 (2 mum) -12.4R · +11 (3 mum) -10.6R (TP oranı %21) · +7 (1R) -4.9R
  (aylar -9.4/+3.6/+0.9) · hepsi -6.6R. Hiçbiri kâra çevirmedi, canlıya bir şey eklenmedi.
- Temiz trend (kullanıcı 14.10 04:21, 10/10 TP örnekleri HOMEUSDT 18.09 20:15, TWTUSDT 15.08 16:45 dönüş): "bu tarz
  mumlu işlemlere öncelik verelim" + "TP'lerle stoplar arasındaki farklar ne". 5 grafikte göze çarpan: stoplarda giriş
  önceki tepenin dibinde (0.1-0.5R yer), TP'lerde 2-3.5R; TP bacakları büyük gövdeli ardışık mumlar, stoplarda iç içe/
  tek mum/EMA'lar yapışık. trade_rules.trend_features: bacak = tepeden önceki son EMA20 temasından tepeye; ölçüler
  bacak_govde (yön gövdeleri / mum boyları), bacak_atr, tek_mum (en büyük gövde / bacak), ters_mum, bacak_mum,
  ema_acilim (EMA20-100 / ATR), ema_egim, trend_yasi, duzeltme, duzeltme_mum, onu_r. Hepsi CSV'de ve /incele'de.
  Filtreler LEG_BODY_MIN / LEG_ATR_MIN / SPIKE_MAX / EMA_FAN_MIN (durum not_clean), test eşikleri TEMIZ_TEST
  (0.4 / 4 ATR / 0.5 / 2 ATR, tahmini). `/backtest 90 temiz` (`dönüş temiz`): karşılaştırma + "fark analizi"
  (her ölçüde işlemler 3 eşit gruba bölünür, TP oranı/R, ay ay aynı yönde mi; R ±3'e kırpılır; max_open yok).
- Temiz (KLASİK, 16.07-14.10): canlı 168 işlem -9.7R · gövde≥0.4 57 işlem +4.1R (aylar -3.2/-1.1/+8.5) · ≥4 ATR -21.6R ·
  tek mum -7.1R · EMA≥2 -10.9R · dördü 27 işlem -0.7R. Fark analizi: hiçbir ölçü şans payını geçmedi, TP/stop ortancaları
  aynı. Temiz önceki (17.04-16.07): canlı 130 işlem +5.0R · dördü 18 işlem +9.4R · EMA≥2 +18.9R (ilk dönemde işe yaramamıştı).
  İki dönemde de aynı yönde (sonradan bakılarak): bacakta ters mum ≤%20 (6 ay 111 işlem +0.10/iş, kalanlar -0.11),
  düzeltme ≥5 mum (157 işlem +0.08, kalanlar -0.15), bacak <4 ATR (76 işlem +0.15). Eşikler sabitlendi: ADAY_TEST,
  `/backtest 90 aday önceki2` (Ocak-Nisan, bakılmamış dönem) ile klasikte sınanabilir.
- Kullanıcı (12:38): temiz testlerini DÖNÜŞ varyasyonunda istiyordu ("ayrı test edicez"), ben klasikte çalıştırdım.
  `/backtest 180 dönüş temiz`: dönüş 6 ay, temiz filtreleri + 3 aday + fark analizi (dönüş işlemleri) tek testte.
- Dönüş temiz 180 gün (17.04-14.10, 500 coin): dönüş 101 işlem %30 -16.2R (-0.16/iş, 6 ayın 2'si artı; klasik aynı
  6 ayda ~-0.02/iş) · gövde≥0.4 37 işlem -5.4R · ≥4 ATR -7.7R · tek mum -15.9R · EMA≥2 72 işlem -3.1R (en iyisi, 2/6 ay) ·
  dördü 12 işlem 3 TP -3.4R · klasik adaylar dönüşte tutmadı: ters mum≤%20 -11.9R, düzeltme≥5 -6.4R, bacak<4 ATR -8.5R.
  Fark analizi (dönüş): hiçbir ölçü şans payını geçmedi. Ölçüler kullanıcının gözüyle uyuşuyor: dördü birlikte HOME'u (TP)
  tutuyor; VIRTUAL (bacak tek kırmızı mum, gövde -0.82), TRUTH (gövde 0.27), HOLO (EMA açıklığı 1.0) eleniyor; TWT (TP) de
  eleniyor (3.3 ATR, gövde 0.31). Ama 6 ayda "temiz" görünen işlemler daha çok kazanmıyor. Canlıya bir şey eklenmedi.
- 14.10 12:53 kullanıcı: "iki varyasyonu birleştir, 5 dklık canlı taramaya al, son 1 aylık backtest". CANLI DEĞİŞTİ:
  LIVE_RULES ENTRY_MODE="both" (temas mumu EMA20'nin doğru tarafında kapatırsa klasik, öbür tarafında kapatırsa dönüş;
  aynı mumda ikisi olamaz, sonuçlar ayrı ayrı çalıştırmanın birleşimiyle birebir aynı), config.LIVE_TF varsayılanı 5m.
  EMİR HAZIR başlığında "(5m, klasik)" / "(5m, dönüş)", dönüşte "Temas, dönüş, onay" saatleri; günlükte "mode".
  Backtest raporunda Klasik / Dönüş satırları, CSV'de varyasyon sütunu, grafik başlığında [klasik]/[dönüş].
  Eski karşılaştırma setleri (_LIVE_NOW) klasikte sabitlendi. Komut: `/backtest 30 canlı 5m`.
- Birleşik 5m 30 gün (14.09-14.10): 186 işlem %34, brüt +15.3R, net -11.2R (komisyon 26.5R = 0.14R/işlem, stop ort.
  %0.68). Klasik 128 işlem %36 +1.2R (brüt +19.0) · dönüş 58 işlem %29 -12.3R (brüt -3.8). 208 işlem toplu sinyal
  filtresine takıldı. Grafik aşamasında bellek 458/512MB → bekçi durdurdu, grafik gelmedi. Düzeltme: grafikler
  sample_charts.py'de temiz süreçte (backtest sonunda os.execv, aynı PID; çizim süreci ~195MB).
- Birleşik 15m 30 gün (14.09-14.10): 62 işlem %32, brüt +2.0R, net -3.1R (komisyon 0.08R/iş, stop ortanca %1.1).
  Klasik 47 işlem +0.4R · dönüş 15 işlem -3.5R · LONG +0.6R, SHORT -3.7R. 5m ile işlem başı aynı (~-0.05/-0.07R),
  5m sadece 3 kat işlem + komisyon. Kullanıcı (17:02): "5 dklığı boşver, backtestlere 15'ten devam". Backtest
  varsayılanı zaten 15m. Canlı hâlâ 5m (klasik + dönüş) — kullanıcı canlı için ayrıca bir şey demedi.

## Çalışma kuralları
- Her yeni kural **iki ayrı ayda** test edilir (`/backtest 30 <set>` ve `/backtest 30 <set> önceki`); sadece ikisinde de iyileştirenler tutulur.
- Gerçek parayla otomatik işlem yok. Önce bildirimlerin canlı sonuçları izlenecek.
- Denenecek: 1 saatlik zaman dilimi (stoplar geniş → komisyon payı küçük).
- TP testi (canlı kurallar, iki ay toplamı, 59 işlem): 1:1.5 -12.2R · 1:2 -13.8R · 1:2.2 -16.9R · 1:2.5 -19.4R.
  Farklar gürültü seviyesinde (aynı ayar ayrı çalıştırmalarda ±3R oynuyor: hacim listesi ve dönem sınırı değişiyor).
  Sorun TP oranı değil, giriş avantajının olmaması. Kullanıcı işlemleri elle seçecek, TP'yi kendisi belirleyebilir.

## Telegram komutları
- `/sinyal aç|kapat` – EMİR HAZIR bildirimleri
- `/bildirim aç|kapat` – EMA20 temas bildirimleri
- `/backtest [gün] [TP] [başabaş] [önceki] [hepsi|yeni|koruma|son|son2|saat|tp] [filtresiz] [tüm]`
- `/backtest 90 canlı` – canlı ayarın aynısı, ay ay sonuç; grafik: dönem boyunca eşit aralıklı 15 TP + 15 stop (PDF kaldırıldı, bellek)
- `/durum`, `/iptal`
- `/incele COIN gg.aa.yyyy SS:DD` – bir işlemin tüm kurallardaki değerlendirmesi + grafik (p, q, önceki düzeltme çizgisi,
  kural 9 iğneli mumlar mavi üçgen)
- `/backtest 90 destek` – kural 9 varyasyonları, ay ay
- `/backtest 180 dönüş temiz` – dönüş varyasyonu: temiz trend + aday filtreleri + TP/stop fark analizi
- `/backtest 90 temiz [önceki]` – aynısı klasik sistemde · `/backtest 90 aday önceki2` – klasikte adaylar, 3. dönem
- `/backtest 30 canlı 5m` – sona 5m yazılırsa test 5 dakikalık grafikte (veri ayrı önbellekte)

## Dosyalar
- `archive.py` backtest verisi (Binance dosya arşivi) · `memwatch.py` bellek bekçisi
- `strategy.py` temas kuralları · `trade_rules.py` onay/giriş/çıkış + 1-6 kurallar
- `live_setups.py` canlı EMİR HAZIR · `backtest.py` testler ve karşılaştırma setleri
- `exchanges.py` Binance · `telegram.py` · `charts.py` · `commands.py` · `bot.py` ana döngü
- 14.10 17:03 kullanıcı: sistemi 3 yıl önce satın almış, satıcı %40-60 kazanma oranı söylüyormuş; "40'ın üstüne
  çıkana kadar backtest". Ölçüt (kullanıcıya söylendi): TP 1:2'de İKİ AYRI DÖNEMDE %40+ (tek dönemde aramak aşırı uyum).
  Şimdiye kadar 3 aylık dönemlerde %33-35; haftalık %30-58 oynuyor. Kullanıcıya sorulan: orijinal sistemin zaman dilimi,
  coinleri, TP/stop yeri, %40-60 hangi TP ile. `/backtest 180 tarama`: taban ve canlı kurallar (klasik, 1:2, portföy
  sınırı yok) 15m/30m/1h/4h x hacim sırası (ilk 50 / 51-150 / 151+), dönemin iki yarısı ayrı; ✅ = iki yarıda %40+
  (her yarıda ≥20 işlem). resample_tf (15m→30m/1h/4h), WARMUP_FACTOR (4s için 50 gün ısınma), dönem başından önceki
  temaslar sayılmaz, satırlarda hacim_sirasi. Taramada grafik/PDF yok.
- TARAMA 180 gün (17.04-14.10, 500 coin, 1:2, portföy sınırı yok), "tümü" satırları (işlem, %TP 1./2. yarı, R/iş):
  Taban: 15m 2455 %34.7 (34/35) -0.09 · 30m 1253 %37.8 (37/39) +0.04 · 1h 608 %37.3 (33/42) +0.05 · 4h 152 %39.5 (41/38) +0.15
  Canlı(klasik): 15m 516 %33.3 -0.11 · 30m 238 %32.8 -0.09 · 1h 115 %41.7 (38/49) +0.20 · 4h 20 %45 +0.33
  ✅ (iki yarıda %40+): taban 30m ilk50 (146, %44), taban 4h 151+ (116, %41), canlı 1h 151+ (76, %46). Coin grubu
  deseni zaman dilimleri arasında tutarsız (1h ilk50 %28) → muhtemelen şans. Zaman dilimi deseni tutarlı: 15m en kötü,
  büyüdükçe iyileşiyor (stop genişliyor, komisyon payı düşüyor: 15m brüt +0.04 net -0.09). Sıradaki: `/backtest 180
  tarama önceki` (Ekim 2025-Nisan 2026, bakılmamış dönem). 1h orada da tutarsa canlı 1h'e alınabilir.
- TARAMA ÖNCEKİ (19.10.2025-17.04.2026, bakılmamış dönem): canlı 1h TUTMADI: 92 işlem %33.7 -0.04R/iş, 6 ayın 4'ü eksi
  (ilk dönemdeki %42/+0.20 şanstı). Canlı 4h 21 işlem %43 +0.26 (iki dönem 41 işlem ~%44, örnek çok küçük).
  Taban 4h 158 işlem %38.6 +0.13 (ilk dönem %39.5 +0.15): iki dönemde de tutan tek şey, ama ince (12 ayda ~310 işlem,
  ayda ~+3.6R, en kötü ay -10.9R). Taban 30m %39 +0.08 (ilk +0.04), aylar çok dalgalı. 15m iki dönemde de eksi.
  Sonuç: 12 ayda hiçbir ayar sürekli %40+ değil; 6 kural 30m/1h'de dönem dışı işe yaramıyor. Kullanıcıya dürüstçe
  söylendi: kısa vadeli (scalp) ve ayda 10R hedefi bu sistemle verilerde yok.
- 14.10 18:55 kullanıcı: "coin BTC'ye benzer gidiyorsa girmeyelim". trade_rules.btc_corr (son 96 mumda log getirilerin
  BTC ile korelasyonu; BTC_Close sütunu backtest'te eklenir, BTC'nin kendisine uygulanmaz), BTC_CORR_MAX filtresi
  (durum btc_corr), CSV/fark analizinde btc_kor. `/backtest 180 btc` (canlı ayar klasik+dönüş, <0.8/<0.6/<0.4, 12 saat).
  Sadece sonraki dalında, YÜKLENMEDİ (kullanıcı PDF örnekleri gönderiyor; birlikte yüklenecek).
- 14.10 18:58 PDF örneği BSVUSDT 15.09 19:45 SHORT: giriş mumu girişe sadece iğneyle değip üstünde kapatmış, sonraki mum
  stop. "Buna girmezdim". Aday kural: (1) kapanışla giriş ya da (2) giriş mumu girişin gerisine kapatırsa kapanışta çık.
  Kullanıcı daha örnek gönderecek, "kodla" deyince yapılacak.
- 14.10 19:02 kullanıcı 2. seçeneği seçti (kapanışla giriş geç kalır). FAILED_ENTRY_BARS: giriş mumu dahil ilk N mumdan
  biri girişin gerisinde kapatırsa o mumun kapanışında çık ("be" durumu, early_exit, CSV'de cikis_turu=erken çıkış,
  grafikte ERKEN ÇIKIŞ). `/backtest 180 erken`: canlı ayar, +erken çıkış 1/2 mum, +BTC <0.8/0.6/0.4, +erken+BTC<0.6;
  PDF erken çıkış (1 mum) ayarından. BTC filtresiyle birlikte yüklendi.
- 14.10 19:12 `/backtest 180 erken` 2 dk'da bellek bekçisine takıldı (backtest 413MB). Sebep bulundu: pandas 3 copy-on-write;
  charts.context'teki dilim (df.iloc[...][cols]) ana tablonun verisini paylaşıyordu, her işlemin grafik bağlamı coinin
  bütün (180 gün) mum tablosunu bellekte tutuyordu (coin başına ~0.4MB birikim). .copy() ile düzeltildi: sahte veride
  200 coinde RSS 151→215MB büyürken düzeltmeden sonra ~143MB sabit. Önceki bellek sorunlarının da (5m 419MB) sebebi bu.
- ERKEN 180 gün (17.04-14.10, 15m, canlı ayar klasik+dönüş, max 2, toplu): canlı 393 işlem %32 -27.0R (1/6 ay artı) ·
  +erken çıkış 1 mum 399 işlem +10.8R (+0.03/iş, 171 erken çıkış ort -0.34R; ~140'ı stop olacaktı ~+108R, ~28'i TP
  olacaktı ~-69R; 6 ayın 5'inde canlıdan iyi, 3/6 artı) · erken 2 mum +12.5R · BTC<0.8 etkisiz · BTC<0.6 -8.2R ·
  BTC<0.4 -2.3R (243 işlem) · erken+BTC<0.6 +15.6R (+0.045/iş). Zarar BTC benzerliği 0.6-0.8'de (51 işlem %25 -0.32R/iş).
  BSV örneği -1.10R → -0.17R. Dönüş erken çıkışla da eksi (-7.7R/99), klasik +18.5R/300. Sıradaki: `/backtest 180 erken önceki`.
- ERKEN ÖNCEKİ (19.10.2025-17.04.2026): canlı 322 işlem -0.9R · erken 1 mum +20.4R · erken 2 mum +32.8R (5/6 ay artı) ·
  BTC<0.8 +3.6 · BTC<0.6 +10.6 · BTC<0.4 -0.7 · erken1+BTC<0.6 +22.6R. İKİ DÖNEMDE DE TUTAN İLK KURAL: erken çıkış.
  12 ay toplam: canlı 715 işlem -27.9R (5/12 ay artı, düşüş -37.6) · erken 1 mum +31.2R (+0.043/iş, 7/12) · erken 2 mum
  +45.2R (+0.061/iş, ayda +3.8R, 8/12 ay artı, en kötü ay -10.3, düşüş -14.3; TP %22, tam stop %16, erken çıkış %62) ·
  BTC<0.6 +2.4R (iki dönemde de canlıdan iyi, küçük) · erken1+BTC<0.6 +38.2R. Kullanıcıya canlıya alma önerildi
  (15m + erken çıkış 2 mum, bot "ÇIK" bildirimi), karar bekleniyor.
- 14.10 22:17 kullanıcı: "çok detay var, TP stop kaç, kâr zarar ne onu göstersin". Raporlar sadeleştirildi:
  karşılaştırmada her ayar için "✅ TP · ❌ Stop · ↩️ Erken çıkış" + kâr/zarar (R ve $); tekli raporda aynısı + klasik/dönüş.
  Huni, aylar, düşüş, örnekler, veri satırı mesajdan çıktı (CSV'de/logda var). Fark analizi sadece "fark" yazılınca.
  Ayar adları Telegram HTML için escape ediliyor ("<" içeren BTC ayarları mesajı bozabiliyordu).
- 14.10 22:27 /durum: canlı 5m tarama 19:25'ten beri Binance IP engelinde (418), 21:31'de yeniden engel (00:33'e kadar);
  IP kullanımı 2017/2400 görülmüş. Sebep: yeniden başlatma sonrası tam veri çekişi (500 coin x 2 ağırlık) + backtest'in
  bugünkü mumlar için API kullanımı + Render IP'si paylaşılıyor olabilir. Düzeltme: backtest son 1-2 gün için API'ye hiç
  gitmez (archive.get_range api_recent=False, test bugünün mumları olmadan çalışır), WEIGHT_SOFT_LIMIT 2000→1200,
  BACKTEST_SOFT_LIMIT 1000→600. Kalıcı çözüm adayı: canlı veriyi WebSocket'ten almak (REST ağırlığı yok).
  Aynı /durum: erken önceki karşılaştırma mesajı Telegram 400 (ayar adındaki "<") ile gelmemişti; 22:19 yüklemesinde
  düzeltildi ama bot 22:27'de hâlâ 20:57'den beri açıktı (o yükleme henüz devreye girmemişti).
- 14.10 22:3x PDF örnekleri: STABLE 09.12.2025 10:45 SHORT dönüş (dip taban yapmış; kural 4'ün 0.3 ATR bandına girmemiş,
  önünde 0.36R), ACE 17.04.2026 16:30 LONG (onay mumu büyük 1.3 ATR, tepenin hizasında, önünde 0.22R), XMR 19.03.2026
  02:45 SHORT (temas mumunun dibi önceki mumun dibinin altında). Yeni: TOUCH_PREV_EXTREME (durum touch_prev), ATR_MAX_MULT
  PARAM_KEYS'e eklendi. `/backtest 180 örnek` (+ önceki): erken çıkış 2 mum üstüne bant 0.5/1 ATR, yer 0.5/1R, onay ≤1.2/1 ATR,
  temas kuralı, hepsi; PDF "hepsi" ayarından.
- 14.10 22:43 kullanıcı: 2 ve 3 yıl önceki birer ayın testi, bütün işlemlerin grafikleri. `--preset canli_erken`
  (canlı ayar + erken çıkış 2 mum), komutta "N sene/yıl önce" → --ago N*365. Dönem sonu 400 günden eskiyse veri diske
  yazılmadan doğrudan arşivden (kayıt kesintisiz tutulduğu için aradaki yıllar indirilirdi). Komutlar:
  `/backtest 30 canlı erken 2 sene önce`, `/backtest 30 canlı erken 3 sene önce`. Coin listesi bugünün ilk 500'ü; o
  tarihte olmayanlar atlanır.
- 14.10 22:46-22:49 kullanıcı iki eski dönem testini, yükleme devreye girmeden çalıştırdı: eski kod "canlı erken 2 sene önce"yi
  erken karşılaştırması + TP 2 olarak okudu, ikisi de 14.09-14.10 çıktı. Artık açılış mesajında ve /durum'da "Sürüm"
  (config.VERSION + Render commit) var: yeni kod devreye girdi mi görülsün. /durum'daki log satırları escape edildi.
  HER YÜKLEMEDE config.VERSION güncellenmeli.
- 14.10 23:1x eski dönemler (canlı + erken 2 mum, 30 gün): Ekim 2024 222 coin 37 işlem (TP 7, stop 5, erken 25) 0.0R,
  48 toplu filtre · Ekim 2023 145 coin 23 işlem (3/2/18) -3.3R, 14 toplu filtre.
- 14.10 23:14 kullanıcı: "erken çıkışlar çok R yiyor; işlemler ortalama kaç R gidiyor, TP'yi ona göre artıralım".
  trade_rules.mfe_r: girişten sonra ilk stopa kadar (TP/erken çıkış yokmuş gibi, en fazla 96 mum) lehte en uzak nokta (R),
  CSV'de mfe_r. COMPARE_SETS["tp"] yeni: erken çıkış 2 mum + TP 1.5/2.2/3/4/5 + erken çıkışsız TP 3; raporun sonunda MFE
  dağılımı (1R+/2R+/3R+… oranları). Eski tp seti tp_eski oldu. `/backtest 30 tp`, doğrulama `/backtest 180 tp` (+ önceki).
- 14.10 23:3x–15.10 00:25 Render arızası ("Builds, deploys, and queued deploys are not starting in all regions", 22:32–
  ~00:25 TR): 8aec1d0 deploy'ları "Building / Awaiting logs"ta kaldı (Events'te hiç "Deploy started" yok). Aynı sırada
  çalışan bot 23:45'ten itibaren api.telegram.org'dan cevap alamadı (getUpdates Read timed out 40 sn, her yeni bağlantıda).
  Kullanıcı Restart service + arıza bitince 8aec1d0 canlıya geçti, Telegram düzeldi. Render notu: ücretli de olsa build
  arızası herkesi etkiler. Öneri (yapılmadı): Telegram 10 dk ulaşılamazsa bot kendini yeniden başlatsın.
- TP testi 30 gün (15.09-14.10, 500 coin, 15m, erken çıkış 2 mum, 66 işlem): TP 1.5 -13.5R · 2.2 -9.1R (10 TP, 14 stop,
  42 erken) · 3 -17.2R · 4 -9.9R · 5 -16.0R · erken çıkışsız TP 3 -14.9R (58 işlem). MFE (stop öncesi en uzak): ortalama
  2.1R ama ortanca 1.0R; 1R+ %52, 1.5R+ %39, 2.2R+ %32, 3R+ %20, 4R+ %17, 5R+ %14. TP büyütmek işe yaramıyor.
  Erken çıkışlar ort -0.36R (toplam -14.9R); 42'sinin 11'i çıkmasa stopsuz 2.2R'ye gidecekti (bu ay ~4R kaybettirdi;
  12 ayda +73R kazandırmıştı). Stop olan 14 işlemin 7'si önce 1R+ kâra gitmiş → başabaş testi.
- 15.10 00:32 kullanıcı: "1R'de stopu girişe çeki ekle, test bitince". COMPARE_SETS["basabas"]: şu anki (erken 2 mum,
  TP 2.2) · +1R'de stop girişe · +1.5R · +1R ve TP 3 · erken çıkışsız +1R. Var olan BE_TRIGGER kullanılır (1R'ye gelen
  mumdan SONRAKİ mumdan itibaren stop = giriş). CSV cikis_turu "başabaş stop". Komut `/backtest 180 başabaş` (+ önceki).
  `/backtest 180 tp` çalışırken yüklenmedi (yükleme botu yeniden başlatır, testi öldürür).
- TP testi 180 gün (18.04-14.10, erken çıkış 2 mum): TP 1.5 402 işlem -9.9R · **2.2 401 işlem +12.8R** (85 TP, 72 stop,
  244 erken; ay ay -0.9/+5.8/+9.4/+7.6/-9.6/+5.6/-5.1) · 3 +20.7R · **4 381 işlem +36.5R** (+0.096/iş; ay ay +1.7/+11.8/
  +18.3/+11.3/-11.2/+12.5/-7.9, 7 ayın 5'inde 2.2'den iyi) · 5 325 işlem +34.5R · erken çıkışsız TP 3 -21.7R.
  Eşleşik (aynı işlemler) fark TP4−TP2.2 +16.2R (±43 gürültü); kalan +7.5R TP 4'te açık işlem sınırı yüzünden atlanan
  20 işlemden (2.2'de -7.5R) → şans payı. MFE (401): ortanca 1.0R, 1R+ %49, 2.2R+ %32, 4R+ %20. Erken çıkmayan 157
  işlemin %54'ü 2.2R'ye, %36'sı 4R'ye gidiyor. Stop olan 72 işlemin 32'si önce 1R+ kâra gitmiş. Erken çıkış 244 işlem
  ort -0.35R (toplam -86.5R), 43'ü çıkmasa 2.2R'ye gidecekti.
- basabas seti güncellendi (yüklenmeden önce): 2.2 · 2.2+1R BE · 2.2+1.5R BE · TP 4 · TP 4+1R BE · TP 4+2R BE.
  `/backtest 180 başabaş` + `/backtest 180 başabaş önceki` hem başabaşı hem TP 4'ü önceki dönemde sınar.
- Başabaş + TP 4 testi (500 coin, 15m, erken çıkış 2 mum), iki dönem (18.04-14.10 / 20.10.2025-17.04.2026):
  şu anki TP 2.2 +12.8R / **+33.0R** (12 ayda +45.8R, 736 işlem, +0.062/iş; ikinci dönem ay ay +4.9/+3.4/+6.1/+6.2/
  +3.2/+11.7/-2.4) · 2.2+1R BE -19.9 / +21.5 (eşleşik -31.5 / -11.4) · 2.2+1.5R BE +0.9 / +24.8 (-11.9 / -8.0) ·
  TP 4 +36.5 / +13.6 (eşleşik +16.2 / -17.7; Kasım -22.4, Şubat -15.8) · TP 4+1R BE -12.7 / +16.0 · TP 4+2R BE
  +23.7 / +23.3 (eşleşik +3.6 / -6.9). Başabaş iki dönemde de kötüleştirdi: 1R'de 31 stop kurtarıyor ama 29 TP'yi
  girişten çıkarıyor (fiyat 1R'den girişe dönüp sonra TP'ye gidiyor). TP 4 tutarsız (bir dönem iyi, bir dönem kötü).
  KARAR: erken çıkış 2 mum + TP 2.2 kalır, başabaş yok. En kötü ay -9.6R (Ağustos), 14 ay parçasının 10'u artı.
- 15.10 01:05 kullanıcı: "işlem sayısı çok az, 5 dklığa alıp 1 aylık backtest". `/backtest 30 canlı erken 5m`
  (15.09-13.10, 5m, canlı ayar + erken çıkış 2 mum = 10 dk): 182 işlem (günde ~6), TP 41 (%23), stop 41, erken 100,
  net +1.8R (+44$), brüt +28.7R, komisyon 26.9R (0.15R/iş; stop ortanca %0.68; stop ≤%0.5 olanlarda 0.23R/iş).
  Klasik 123 işlem +0.3R · dönüş 59 işlem +1.5R. Ay içi en büyük düşüş -20.1R, en kötü hafta -17.0R.
  Aynı ay: 15m erken çıkışla -9.1R (66 işlem), 5m erken çıkışsız -12.2R (184 işlem) → erken çıkış 5m'de de ~+13R.
  MFE ortanca 1.0R (15m ile aynı). Doğrulama: `/backtest 30 canlı erken 5m önceki`.
- 5m önceki ay (16.08-15.09, canlı + erken 2 mum): 211 işlem, TP 40 (%19), stop 42, erken 129, **-19.8R** (-494$), brüt
  +13.5R, komisyon 33.3R (0.16R/iş). Klasik 148 -12.0R · dönüş 63 -7.8R. Max düşüş -21.2R. 5m iki ay toplam -18.0R:
  brüt iki ayda da artı (+28.7 / +13.5) ama komisyon yiyor.
- 15.10 01:13-01:14 kullanıcı 5m PDF'ten: SQDUSDT 05.10 00:50 LONG ("böyle 2 yüksek mumdaki tepelerdeki işlemlere
  girmesin", erken çıkış -0.13R; bacak_mum 1, bacak 6.1 ATR) ve SHORT 07.10 21:50 ("max 2. mumda onay mumu vermezse
  işleme girilmeyecek"; onay temastan sonra 3. mumda, -0.24R).
  CSV'den onay mesafesi (onay - temas): onay 3. mumda gelen klasik işlemler 5m Eyl-Eki 18 işlem -7.1R (TP %6),
  5m Ağu-Eyl 14 işlem -6.9R (hiç TP yok); 15m Nis-Eki 36 işlem +13.6R (TP %31), 15m Eki-Nis 24 işlem -4.1R.
  → 5m'de iki ayda da işe yarıyor, 15m'de karışık. Dönüşte onay zaten 2. mumda.
  Kod: CONFIRM_WINDOW PARAM_KEYS'te; trade_rules.spike_top (tepeyi yapan mum + önceki mumun boyu / tepeden 2 mum
  önceki ATR), SPIKE_TOP_ATR (status spike_top), CSV'de sivri_atr (bütün işlemlerde, eşik sonradan ayarlanabilsin).
  Rastgele veride ortalama ~2 ATR. COMPARE_SETS["sivri"] (5m için): canlı+erken · +onay ≤2. mum · +sivri ≥3 ATR ·
  +sivri ≥4 ATR · ikisi (PDF). Komut `/backtest 30 sivri 5m` (+ önceki).
- Sivri testi 5m (15.09-13.10): taban 182 işlem +1.8R · **onay ≤2. mum 165 işlem +7.6R** · sivri ≥3 ATR 117 işlem +0.3R
  (elenen 66 işlem +0.2R) · sivri ≥4 ATR 151 işlem -4.4R (elenen 32 işlem +4.9R, TP %28) · ikisi 108 işlem +2.7R.
  sivri_atr ortanca 2.5, SQD 10.4. Bu ay sivri tepeler kaybettirmiyor; önceki ay bekleniyor.
- TP 2.5 tahmini (MFE'den; TP olanların kaçı 2.5R'ye de gidiyor): 5m Eyl-Eki +5.2R · 5m Ağu-Eyl -12.9R · 15m Nis-Eki
  +4.2R · 15m Eki-Nis -8.9R. Bir TP'nin stopa dönmesi 3.2R, 2.5'e gitmesi +0.3R → TP'lerin %91'i 2.5'e gitmeli.
- 5m stop mesafesi: <%0.5 olanlar komisyon 0.21-0.28R/iş; Eyl-Eki 62 işlem +1.5R, Ağu-Eyl 66 işlem -19.2R.
  COMPARE_SETS["komisyon"] (5m): onay ≤2 tabanı · +TP 2.5 · +stop ≥%0.5 (BASE_MIN_RISK_PCT, PARAM_KEYS'e eklendi) ·
  ikisi. `/backtest 30 komisyon 5m` (+ önceki). Sivri önceki testi bitmeden yüklenmedi.
- Sivri testi 5m önceki (16.08-15.09): taban -19.8R · onay ≤2 -12.9R (+6.9) · sivri ≥3 -7.9R (+11.9) · sivri ≥4 -9.1R
  (+10.7) · ikisi -5.2R (+14.6). İki ay toplam: taban -18.0 · **onay ≤2 -5.3 (iki ayda da iyi: +5.8 / +6.9)** · sivri ≥3
  -7.6 (-1.5 / +11.9) · sivri ≥4 -13.5 · ikisi -2.5 (+0.9 / +14.6; onay ≤2'nin üstüne sivri: -4.9 / +7.7 → karışık).
  Bu ay sivri ≥6 ATR 12 işlem hiç TP yok -6.7R; önceki ayda 14 işlem 4 TP +3.6R.
- Kullanıcı: "2 ayda fark bu kadar olmamalı" (+1.8 / -19.8). İşlem başı R std 1.14 → 200 işlemlik ayda şans payı ±16R;
  aynı sistemden rastgele aylar %5-%95: -35R … +18R; iki ay arası ≥21R fark %35 olasılıkla. İşlem başı fark 0.1R.
  Ağu-Eyl: TP %19 (Eyl-Eki %23), erken çıkış %61 (%55, ort -0.42R), SHORT -13.1R.
- komisyon setine 5. ayar: onay ≤2 + stop ≥%0.5 + sivri ≥3 ATR.
- Komisyon testi 5m (onay ≤2 tabanı), Eyl-Eki / Ağu-Eyl: taban +7.6 / -12.6 (-5.0) · TP 2.5 +8.9 / -27.9 (-19.0, RED) ·
  **stop ≥%0.5 +3.2 / +4.5 (+7.7; 5m'de iki ayda da artı kalan ilk ayar; komisyon 11-15R/ay, düşüş -19.2 / -9.0;
  106-133 işlem/ay)** · stop ≥%0.5 + TP 2.5 +9.8 / -3.0 · stop ≥%0.5 + sivri -1.9 / +0.8. Stop filtresi tabana göre
  -4.4 / +17.1. Brüt (komisyonsuz) 5m ayda +18…+34R; 15m +6…+19R. Sıradaki: `/backtest 30 komisyon 5m önceki2`
  (17.07-16.08, bakılmamış 3. ay).
- Komisyon testi 5m önceki2 (17.07-16.08, 184 coin): taban (onay ≤2) -18.3R (brüt +9.3) · TP 2.5 -21.5 · stop ≥%0.5
  -10.4R (brüt +0.4!) · stop+TP 2.5 -14.7 · stop+sivri -4.3. 5m stop ≥%0.5 üç ay: +3.2 / +4.5 / -10.4 = -2.7R (Binance);
  BNB+referans +4.5; +%0.02 kayma -9.9; MEXC +20.5; MEXC+kayma +6.2. → 5m 3. ayda tutmadı (brüt ~0).
- Komisyon/kayma senaryoları (CSV'den yeniden hesap; Binance oranlarıyla backtest sonucunu birebir veriyor). 15m erken
  çıkış (TP 2.2) 12 ay: Binance +45.9R · +kayma (%0.02/piyasa emri) +17.4 · BNB+referans +60.1 · BNB+ref+kayma +31.6 ·
  MEXC (%0.02/%0) +92.2 · MEXC+kayma +63.7 (ayda ~5.3R, en kötü ay -7.2, 13 ayın 10'u artı). 15m her senaryoda artı;
  ayda R olarak da 5m'den iyi (5m MEXC+kayma ~2R/ay). Backtest'te kayma YOK → gerçek sonuç daha düşük.
- 15.10 01:54 kullanıcı ZETAUSDT 5m 13.09 13:55 LONG: giriş 14:05 0.03713, 14:10 mumu iğne atıp 0.03709'da (girişin 0.15R
  altında) YEŞİL kapattı → erken çıkış -0.30R; MFE 10.2R (TP gelirdi). "Kırmızı kapatırsa çıkmalı."
  CSV'den: girişin 0-0.2R altında kapatıp çıkanların ~%20'si sonradan TP'ye gidiyor; hepsini tutmak 5 dönemin 4'ünde
  kötü (5m -14/-18/+2, 15m -37/-21). Renk ayrımı CSV'de yok → kod: FAILED_ENTRY_RED (erken çıkış sadece ters renkli
  kapanışta; doji çıkmaz). COMPARE_SETS["renk"]: erken 2 mum · +renk · onay≤2+stop≥%0.5+erken · +renk.
  `/backtest 180 renk` (+ önceki), `/backtest 90 renk 5m` (Tem-Eki, 5m önbellekte).
- 15.10 01:59-02:00 kullanıcı BANKUSDT 5m 14.09 13:35 LONG ("bok gibi, asla girmem: ne temiz tepe ne düzeltme, temas
  mumu kötü; giriş tepenin hizası, bunları kaç kere düzelt diye attım"). Erken çıkışla -0.10R; erken çıkışsız eski
  testlerde 14:35'te stop (-1.04R). Ölçüler: önünde yer 0.56R, EMA açıklığı 1.82 ATR, düzeltme 3 mum, ters mum %33.
  HATA (benim): önünde yer kuralı (ROOM_MIN_R, STABLE örneği 14.10) 'örnek' setindeydi, 5m'ye geçince taşımadım,
  hiç çalışmadı. CSV'den (5m en iyi ayar: onay≤2+stop≥%0.5, elenecek işlemlerin R'si): yer <0.5R -1.7/-2.3/-1.7,
  yer <1R -2.1/+1.2/-7.5, EMA <2 ATR -4.1/-6.0/-8.2 (5m'de üç ayda da kötü; 15m -9.6/+11.2 karışık).
  renk setine eklendi: +1R yer · +EMA ≥2 ATR · hepsi (yer+EMA+renk). Kullanıcı "yüklemeden bekle" dedi.
- renk testi sonuçları (CSV 0033156b 5m 90g, 6119c501 15m Nis-Eki, 0361c2da 15m Eki-Nis):
  5m 90 gün (Tem-Ağu / Ağu-Eyl / Eyl-Eki): erken -37.9 · +renk -52.8 · onay≤2+stop≥%0.5 (3) -8.8/+1.5/+4.6=-2.7 ·
  +renk -12.5 · +1R yer -1.8/+0.8/+7.1=+6.2 · **+EMA≥2 -0.9/+7.8/+8.8=+15.7 (3'e göre üç ayda da iyi)** · hepsi
  (yer+EMA+renk) +4.7/+5.9/+2.9=+13.5 (her ay artı, düşüş -12.8).
  15m 12 ay (Nis-Eki / Eki-Nis): erken +12.8/+33.0=+45.9 (kayma +17.4) · +renk +13.2 · (3) +10.9/+27.3=+38.2 ·
  **(5) +1R yer +17.2/+31.5=+48.6 (kaymayla +36.2; 13 ayın 10'u artı, en kötü ay -3.3, ~31 işlem/ay)** · (6) +EMA
  +24.1/+14.3 (Eki-Nis'te 3'ten -13 kötü) · hepsi +21.3.
  KARAR: ters renk kuralı bırakıldı (her yerde kötü). Yer 1R 15m'de iki dönemde de iyi; EMA 5m'de 3 ayda iyi, 15m'de
  karışık. Yeni set "yer": (3) · +1R yer · +1R yer +EMA≥2 · +1R yer +EMA≥1.5. `/backtest 90 yer 5m`, `/backtest 180 yer`
  (+ önceki).
- 15.10 02:44 kullanıcı: "hangisi daha iyiyse o yükle şimdi". CANLI DEĞİŞTİ (02:50): 15m (config.LIVE_TF varsayılanı;
  Render'da LIVE_TF env varsa o geçer) + LIVE_RULES = LIVE_RULES_14_10 + CONFIRM_WINDOW=2, BASE_MIN_RISK_PCT=0.5,
  ROOM_MIN_R=1.0, FAILED_ENTRY_BARS=2. Erken çıkışta follow_up "⚠️ ERKEN ÇIK" mesajı atar (mum kapanışından ~10 sn
  sonra; aynı mumda giriş + erken çıkış olursa ikisi tek mesajda). EMİR HAZIR'da erken çıkış satırı. Gerekçe: 15m 12 ay
  +48.6R (kaymayla +36.2), en kötü ay -3.3R; 5m en iyisi kaymayla 3 ayda +4.2R. Backtest karşılaştırma setleri
  LIVE_RULES_14_10'a sabitlendi; preset "canli" artık yeni canlı ayar (`/backtest 180 canlı` ≈ renk setindeki 5. ayar).
- 5m "yer" testi 90 gün (Tem-Ağu / Ağu-Eyl / Eyl-Eki): taban -8.8/+1.5/+4.6 · +1R yer -1.8/+0.8/+7.1 · **+1R yer +EMA≥2
  +4.5/+6.6/+9.1 = +20.3R (kaymayla +13.3, her ay artı; düşüş -10.7; ~55 işlem/ay)** · +EMA≥1.5 +5.7.
- 15.10 02:52 kullanıcı: "son sonuçlar bitsin, en iyi sistemle Binance otomatik işlem; 1R = 1 dolar".
  autotrade.py: EMİR HAZIR → girişe STOP_MARKET algo emri (/fapi/v1/algoOrder; 2025-12-09'dan beri koşullu emirler
  orada, triggerPrice); fiyat girişi geçmişse (-2021) ≤0.3R ise piyasa emri. Her 5 sn positionRisk: dolunca stop
  (STOP_MARKET reduceOnly) + TP (LIMIT reduceOnly GTC, maker). Stop konamazsa piyasa ile kapat. Canlı takip
  cancel_confirm/no_entry → giriş emri silinir; erken çıkış → piyasa ile kapat + emirleri sil. Pozisyon 0 olunca TP
  emri FILLED mi bakılır, kalan emir silinir, userTrades'ten (giriş emrinden beri) gerçek kâr-zarar - komisyon (BNB
  ise BNBUSDT fiyatıyla) → R. Güvenlik: /oto aç ile açılır (auto_state.json kalıcı), izole 10x, en fazla 2 işlem,
  tek işlem ≤300 USDT, günlük -5R'de durur, coinde başka pozisyon varsa girmez, hedge modu desteklenir.
  Ortam: BINANCE_API_KEY, BINANCE_API_SECRET (+ isteğe bağlı AUTO_RISK_USD=1, AUTO_LEVERAGE=10, AUTO_MAX_NOTIONAL=300,
  AUTO_MAX_OPEN=2, AUTO_DAILY_LOSS_R=5). Bildirimler 1R = 1$ (ALERT_RISK_USD). Taklit Binance ile test edildi
  (TP +2.09R, stop -1.14R, erken çıkış -0.30R, hedge modu, stop konamazsa kapatma, geç giriş, günlük sınır).
  CANLI: 5m + LIVE_RULES'a EMA_FAN_MIN=2.0 (config.LIVE_TF varsayılanı 5m).
- 5m yer önceki (18.04-17.07): taban -40.2 · +1R yer -23.7 · **+1R yer +EMA≥2 +11.4/-19.9/-14.9 = -23.3R (düşüş -36)** ·
  +EMA≥1.5 -28.3. 5m 6 ay toplam -3R → TUTMADI. 5m'ye geçiş iptal; EMA_FAN_MIN canlıdan çıkarıldı.
  KARAR (15.10 03:10): otomatik işlem ve canlı 15m: onay ≤2 + stop ≥%0.5 + 1R yer + erken çıkış (12 ay +48.6R).
  autotrade sağlamlaştırıldı: emir göndermeden önce kayıt; istemci kimlikleri (se/ss/st + coin + temas sn): cevap
  kaybolursa izleme döngüsü pozisyonu bulup korur, tekrar denemede "duplicate" = konmuş sayılır; stop/TP eksikse her
  döngüde yeniden denenir (TP en fazla 5 kez). Taklit Binance testleri: tek yön + hedge, TP/stop/erken/iptal/SHORT,
  giriş/stop/TP cevabı kaybolması, stop reddi → kapatma.
- 15.10 03:26 Binance API anahtarı oluşturuldu (kullanıcı). Binance: IP kısıtlaması yoksa ve Reading dışında yetki
  açılırsa anahtar SİLİNİR. Render çıkış IP'leri paylaşılan aralıklar (Frankfurt 74.220.51.0/24, 74.220.59.0/24);
  Binance sadece tek IP kabul ediyor. Dedicated IP Render Pro plan ister. Ücretsiz yol: /ip komutu botun gerçek çıkış
  IP'sini gösterir (ipify / checkip.amazonaws / ifconfig.me), ip_seen.json'da tutulur; 10 dk'da bir kontrol, yeni IP
  görülürse (anahtar kuruluysa) Telegram uyarısı. -2015 hatasında IP ipucu. Kalıcı çözüm gerekirse: sabit IP'li
  küçük sunucu (proxy) ya da Render Dedicated IP.
- 15.10 03:37 kullanıcı IP'yi (74.220.51.142) ekledi; /oto bakiye okuyor (225 USDT, tek yön). Futures yetkisi bakiye
  okumakla anlaşılmıyor → /oto ve /oto aç artık /sapi/v1/account/apiRestrictions ile Futures / IP kısıtı / para çekme
  bayraklarını gösteriyor; Futures kapalıysa, IP kısıtı yoksa ya da PARA ÇEKME açıksa /oto aç reddedilir.
- 15.10 03:44 kullanıcı: 30m de test (`/backtest 180 yer 30m` + önceki; bakılacak satır "+ önünde en az 1R yer" = canlı).
- 15.10 03:50 kullanıcı (SLX 14.10 23:00, saatlerce yatay): "girerdim ama saatlerce kalmazdım; aşırı yataya bağlarsa
  girişe gelince stop etsin, ufak kârda bile çıkabilir". TIME_STOP_LOCK_R eklendi (zaman stopunda stop giriş+kilit R;
  fiyat gerisindeyse o mum açılışında çık). COMPARE_SETS["yatay"]: canlı 15m · 2 / 4 / 8 saat stop girişe · 4 saat
  0.2R kâra. `/backtest 180 yatay` (+ önceki). 30m testleri bitince yüklenecek (henüz yüklenmedi).
  Not: hacim sırasına göre canlı 15m ayar: 300-500. coinler Nis-Eki +18.8R, Eki-Nis +5.8R → küçük coin filtresi yok.
- 30m yer Nisan–Ekim (227 coin): taban -11.2R · +1R yer (canlı ayar) 119 işlem TP %15 -14.5R · +EMA≥2 -9.7 · +EMA≥1.5
  -10.5. Aynı dönemde 15m +17.2R → 30m RED, önceki dönem çalıştırılmadı. Canlı/oto sadece 15m.
- Yatay testi 15m (canlı ayar +17.2 / +31.5): 2 saat +7.3 / +31.9 (-9.9 / +0.4) · 4 saat +13.2 / +36.6 (-4.0 / +5.1) ·
  8 saat +16.8 / +33.5 (-0.4 / +2.0) · 4 saat 0.2R kâra +10.7 / +37.2 (-6.5 / +5.7). Hiçbiri iki dönemde de iyi değil
  (Nis-Eki'de hepsi kötü: yatay işlemlerin bir kısmı sonradan TP oluyor) → canlıya eklenmedi.
- 15m canlı ayar ay ay (TP %): Eki +4.5 (40) · Kas +0.4 (19) · Ara +3.1 (24) · Oca +7.0 (24) · Şub +3.1 (19) · Mar +7.4
  (26) · Nis +6.0/+5.0 · May -0.7 (23) · Haz +9.7 (31) · Tem +5.2 (24) · Ağu -3.1 (17) · Eyl +4.4 (22) · Eki -3.3 (14).
- 15.10 04:03 kullanıcı: "erken çıkış hariç ayda ~10 işlem az; işlem + kazanç artarsa 10R". 12 ayda işlem başı ~0.13R →
  10R için ayda ~77 işlem gerekir (şu an ~31). Toplu sinyale takılanlar (CSV'de mfe + erken çıkış bilgisi var; tahminci
  gerçek sonuçları 17.1/17.2 ve 29.8/31.5 tutturuyor): Nis-Eki 165 işlem -24.9R, Eki-Nis 305 işlem -13.7R → filtre kalır.
  COMPARE_SETS["gevset"]: canlı ayardan kural 1 / 2 / 4 / 5 / 6 ve 03-07 saat filtresi tek tek kaldırılır.
  `/backtest 180 gevşet` (+ önceki).
- Gevşetme testi 15m (eklenen işlemlerin R'si, Nis-Eki / Eki-Nis): kural 1 -5.0 / -6.8 · kural 2 -11.4 / +17.4 · kural 4
  -2.9 / -6.3 · kural 5 -4.6 / +10.2 · kural 6 -3.1 / -3.1 · 03-07 saat filtresi +7.2 / -1.2 (38+38 işlem). Kural 1, 4, 6
  kesin kalır; 2 ve 5 tutarsız → kalır. Saat filtresi sınırda; kullanıcı (04:14) "yarın kaldırırsın" → LIVE_RULES'ta
  QUIET_UTC=(0,0) sonraki dalında hazır, YARIN kullanıcının grafik örnekleriyle birlikte yüklenecek (henüz main'de değil).
- Erken çıkış zararı ölçümü (15.10 04:2x, kullanıcı: "erken çıkışlar 0.3-0.6R yiyor, ölç biç"). 12 ay 15m canlı ayar:
  224 erken çıkış -74R = fiyat -54R + komisyon -20R; 157'si giriş mumunun kendisinde (fiyat girişe değip geri kapattı =
  sahte kırılım), 67'si sonraki mumda. Derin kapanış az: X'ten derin kapatan (Nis-Eki / Eki-Nis) 0.3R: 35/37 işlem,
  0.4R: 18/23. Mum içi erken stop en fazla 0.2R +9.8/+10.6 · 0.3R +5.5/+5.8 · 0.4R +2.8/+2.7 kazandırabilir (iğneyle
  stoplanıp TP olacakları kaybetmeden önce). Giriş filtreleri CSV'den (çıkardıkları işlemlerin R'si, Nis-Eki / Eki-Nis):
  stop ≤ 1.3 ATR +11.4 / +4.1 · ≤ 1.4 ATR +10.6 / +0.4 · önünde ≥ 1.5R yer +12.0 / +4.2 · sivri < 3 ATR -0.3 / +8.1 →
  hepsi kârlı işlem de atıyor, tutarlı değil. Asıl kaldıraç sahte kırılım mumuna girmemek.
  Yeni: CLOSE_ENTRY (mum giriş seviyesinin ötesinde kapatınca kapanışta gir; risk = kapanış - stop, TP buna göre),
  CLOSE_ENTRY_MAX_R (kapanış seviyeden bu kadar R uzaksa girme, "chase"), CLOSE_ENTRY_KEEP_TP (TP fiyatı aynı kalır),
  EARLY_STOP_R / EARLY_STOP_BARS (ilk 2 mumda mum içi stop; giriş mumunda kötümser: mum girişin gerisinde kapatıp iğneyle
  seviyeyi geçtiyse tetiklendi sayılır). COMPARE_SETS["kapanis"], `/backtest 180 kapanış` (+ önceki). CSV'de erken_stop
  sütunu. Canlıya geçerse: kapanışla girişte oto işlem mum kapanışında piyasa emri verir (stop emri değil).
- Kapanış testi 15m Nis-Eki (15.10 04:40): canlı +17.2R (201 iş) · +0.3R erken stop +12.3 (iğneyle 14 işlem daha erken
  çıkışa düştü) · kapanışla giriş +6.9 (135 iş; sahte kırılımın 66 işlemi -21.4R elendi ama ortak 135 işlem +38.5 → +6.9:
  giriş yukarıdan, stop ortancası %0.98 → %1.28, erken çıkış ort. -0.33 → -0.48) · ≤0.5R -2.3 · TP aynı -6.4 · erken
  çıkışsız +13.1. Hepsi RED, önceki dönem çalıştırılmadı. Erken çıkış, stop emriyle en iyi fiyattan girmenin bedeli.
- Grafik örnekleri (kullanıcı 15.10 04:37; "bugün bir şey yapma, yarın 'yükle' deyince toplu yap, ayrı ayrı test"):
  RESOLVUSDT 20.08 02:15 LONG dönüş stop -1.16R ("düzeltme temiz görünse de çok iğneli mumlar, git-gel, stopa iğne"),
  NILUSDT 25.08 19:15 SHORT klasik stop -1.09R ("temiz dip yok, düzeltme kötü"; sivri_atr 4.18, düzeltme 10 mum),
  ESPUSDT 30.08 11:30 SHORT dönüş erken -0.37R ("EMA'nın üstünde kapatan temas mumunun gövdesi çok büyük").
  10:13 "yükle": 03-07 saat filtresi canlıdan kaldırıldı (LIVE_RULES QUIET_UTC=(0,0)) + WICKY_MAX/WICKY_BARS (temastan
  önceki 12 mumda 1 - Σgövde/Σboy), RECLAIM_BODY_MAX_ATR (dönüşte temas gövdesi), temiz dip/tepe bandı CLEAN_PIVOT_ATR
  0.5 (≤2 mum) / 1 ATR (≤4 mum; 1 ATR bantta ≤2 neredeyse hepsini eler) (ornek setindeydi, hiç çalıştırılmamıştı). COMPARE_SETS["grafik"], taban = yeni canlı ayar. CSV'de igne_orani,
  duz_igne, temas_govde_atr, pivot_bant_05, pivot_bant_1 → eşikler CSV'den taranabilir. /incele de gösteriyor.
  `/backtest 180 grafik` (+ önceki).
- Grafik testi 15m (taban = 03-07 filtresi yok canlı ayar: Nis-Eki +22.1R 236 iş, Eki-Nis +27.5R 212 iş → 12 ay +49.6R).
  Ayar farkları (Nis-Eki / Eki-Nis): iğne ≤%60 0 / +1.3 · iğne ≤%55 +2.5 / -1.6 · 0.5 ATR bant ≤2 +3.1 / -13.1 · 1 ATR
  bant ≤4 +4.5 / -1.4 · dönüş gövde ≤1 ATR -2.9 / +1.5 · ≤0.7 ATR -4.5 / -0.5 → hiçbiri iki dönemde iyi değil, canlıya yok.
  Örnekler: RESOLV iğne 0.574, düz_iğne 0.70, bant 0.5=4 / 1=5 · NIL iğne 0.609, düz_iğne 0.77, bant 1=6 · ESP gövde 1.76.
  CSV taraması (çıkan işlemlerin R'si): 12 mum iğne >0.58 -3.3 / -6.5 (31/21 iş) ama >0.55 -2.5/+2.6, >0.6 +0.1/-1.3;
  1 ATR bant ≥5 -2.5 / -3.6 (53/45 iş) ama ≥4 -1.6/+7.2, ≥6 +4.6/-8.1 → komşu eşikler tutarsız, büyük ihtimalle şans.
  3. bağımsız dönemde (`/backtest 180 grafik önceki2`, Nis-Eki 2025) bu iki eşik CSV'den sınanacak (yeni kod gerekmez).
- 3. dönem (Nis-Eki 2025, `grafik önceki2`, 262 coin): taban (03-07 filtresi yok canlı ayar) 149 iş TP %15 **-20.8R**, 7 ayın
  6'sı eksi (Tem -9.0, Ağu -6.4; sadece Eyl +5.2). 18 ay toplam +28.8R. Ayar farkları: iğne ≤%60 +0.6 · ≤%55 +2.1 · 0.5
  ATR ≤2 +3.5 · 1 ATR ≤4 (kural 4'ün yerine) +10.0 · dönüş gövde ≤1 -1.3 · ≤0.7 +0.8.
  Önceden seçilen iki eşik 3. dönemde de tuttu (çıkan işlemlerin R'si, 3 dönem): 12 mum iğne >0.58 -3.3 / -6.5 / -2.7 ·
  1 ATR bant ≥5 (kural 4 kalarak, ek filtre) -2.5 / -3.6 / -13.7. İkisi birden (CSV tahmini): +22.1→+26.7 · +27.5→+32.3 ·
  -20.8→-3.2 (18 ay +28.8 → +55.8R, işlemlerin ~1/3'ü çıkar). Gerçek ayar olarak (portföy etkisiyle) 3 dönemde sınanmalı:
  yeni parametre gerekir (kural 4'ün 0.3 ATR bandı kalırken ikinci bant 1 ATR ≥5 mum).
- 11:46 "kodla": PIVOT_BAND2_ATR / PIVOT_BAND2_MAX (kural 4'ün 0.3 ATR bandı kalır, ek olarak dip/tepenin 1 ATR yakınında
  ≥5 mum varsa "wide_pivot") + WICKY_MAX=0.58. COMPARE_SETS["grafik2"]: canlı · iğne ≤%58 · 1 ATR bant ≤4 · ikisi · ikisi
  gevşek (≤%60, ≤5). `/backtest 180 eleme` + önceki + önceki2 (anahtar kelimede rakam olmasın: "grafik2" → --rr 2 oluyordu).
- Eleme testi (gerçek ayar, 3 dönem: Nis-Eki 26 / Eki 25-Nis 26 / Nis-Eki 25):
  canlı +22.5 / +27.5 / -19.0 (18 ay +31.0, 599 iş) · iğne ≤%58 +26.3 / +34.0 / -16.3 (+44.0) · 1 ATR bant ≤4 +25.0 /
  +31.1 / -5.4 (+50.7) · **ikisi birden +27.1 / +32.3 / -1.5 (+57.9, 415 iş, R/iş 0.052 → 0.14)** · gevşek (≤%60, ≤5)
  +16.5 / +33.4 / -10.0 (+39.9). İkisi birden ve ikisi ayrı ayrı 3 dönemde de canlıdan iyi; eşikler 1.-2. dönemden seçilip
  3. dönemde sınandı. Gevşek eşik 1. dönemde kötü → eşik hassas, %58 / ≤4 mum korunmalı. 2025 ortası hâlâ zayıf (ikisiyle
  Haz -6.8, Tem -6.0, Ağu -4.8). LIVE_RULES'a WICKY_MAX=0.58 + PIVOT_BAND2 1 ATR/5 15.10 13:08 "yükle" → canlıda (bildirim + oto işlem).
- 13:21 "hazırla": COMPARE_SETS["dilim"] = yeni canlı ayar (LIVE_RULES) / iki kural kapalı, aynı zaman diliminde.
  `/backtest 180 dilim 30m` (+ önceki), `/backtest 90 dilim 5m` (+ önceki). WICKY_BARS 12 mum (30m'de 6 saat, 5m'de 1 saat).
  Kullanıcının `/backtest 90 canlı önceki` testi çalışıyor olabilir → bitince yüklenecek.
- Dilim testi (yeni canlı ayar / iki kural yok): 30m Nis-Eki 26 +0.2 / -15.3 · 30m Eki-Nis +10.7 / +12.2 → 30m 12 ay
  +10.9 (150 iş) / -3.1 (15m yeni +59.4). 5m Tem-Eki +5.8 / +8.7 (kom 20R) · 5m Nis-Tem -22.9 / -32.5 → 5m 6 ay -17.1 /
  -23.8 (15m aynı dönemler +8.5 +18.7 = +27.2). KARAR: canlı/oto 15m kalır; 5m ve 30m eklenmez. Yeni kurallar 30m ve
  5m'de de toplamda iyileştiriyor (+14.0 / +6.7) → kurallar 15m'ye özgü tesadüf değil.
- 13:41-13:43 kullanıcı: ETHFIUSDT 19.04 04:00 SHORT dönüş erken -0.53R (kapanış dolumun 0.54 ATR gerisinde, mfe 2.49 → TP
  olacaktı), BLURUSDT 19.04 19:00 LONG erken -0.26R (0.29 ATR, mfe 1.17 → TP olmayacaktı; stop %4.4 uzakta) "girerdim,
  erken çıkışı esnetmek lazım" + "stop çok aşağıda, yükseltsek TP kısalır". 18 ay CSV (yeni ayar, 234 erken çıkış):
  derinlik <0.1 ATR %12 TP'ye gidiyor · 0.1-0.2 %19 · 0.2-0.35 %12 · >0.35 ATR %30 (tutsaydık +9.0 / +8.2 / +12.9R).
  Yeni: STOP_MAX_ATR (stop girişe en fazla X ATR; TP de yaklaşır), EARLY_EXIT_MAX_ATR (dolumun X ATR'den derin gerisinde
  kapanışta erken çıkış o işlem için kapanır). COMPARE_SETS["stop"]: canlı · pay 0.15 · pay 0 · stop ≤1 / ≤1.2 ATR ·
  derin erken çıkış yok 0.35 / 0.5. `/backtest 180 stop` + önceki + önceki2.
- Stop testi 3 dönem (Nis-Eki 26 / Eki-Nis / Nis-Eki 25), canlı +26.8 / +32.3 / -1.6 (18 ay +57.5, ay ort 3.7, düşüş 21.7):
  pay 0.15 +18.8 / +27.2 / +4.0 · pay 0 +20.4 / +43.7 / -0.8 · stop ≤1 ATR +31.0 / +19.6 / -7.7 · ≤1.2 ATR +34.5 / +28.6 /
  +4.8 → stop yeri değişiklikleri tutarsız, RED. **Derin kapanışta erken çıkma 0.35 ATR +36.2 / +39.1 / +12.0 (18 ay +87.3,
  ay ort 5.4, son 12 ay 6.8, düşüş 17.7)** · 0.5 ATR +35.9 / +39.2 / +6.1 (+81.2) → 3 dönemde iyi, eşiğe hassas değil.
  LIVE_RULES EARLY_EXIT_MAX_ATR=0.35 sonraki dalında hazır (bildirimde çıkılmayacak kapanış seviyesi yazılıyor), "yükle" bekliyor.
- 14:24 "yükle, 1R 15$ yap" → AskUserQuestion: bakiye ~225 USDT, 15$ = %6.7/işlem, test düşüşü 17.7R ≈ 265$ (bakiyeden
  fazla), en kötü ay -7.4R ≈ -111$ söylendi; kullanıcı: "kaldıracı arttır, önemli olan 1R'ın 15 olması". CANLI:
  EARLY_EXIT_MAX_ATR=0.35 + AUTO_RISK_USD varsayılanı 15 (ALERT_RISK_USD de 15) + işlem başı kaldıraç: likidasyon stopun
  1.5 katından uzak kalacak en yüksek kaldıraç (leverageBracket'tan coin sınırı ve bakım marjini; alınamazsa en fazla 20x;
  geçersizse 25/20/10/5 denenir), AUTO_LEVERAGE en fazla 50, AUTO_MAX_NOTIONAL 4000. Kayıtta risk_usd (eski kayıtlar 1$).
  Stop %1 → 40x marjin ~38$, %4.4 → 13x ~26$, %0.5 → 50x ~60$. Backtest raporları da 1R = 15$.
- 15:19 kullanıcı "1R kârdan sonra girişe gelirse stop girişte" → sabahki sonuç anlatıldı (eski sistemde 1R BE -31.5 /
  -11.4), "kodla deneyelim": COMPARE_SETS["basabas2"] = şimdiki canlı (LIVE_RULES) · +1R / +1.5R / +2R BE.
  `/backtest 180 başabaş` artık bu sete gidiyor (+ önceki + önceki2).
- 15:25 kullanıcı: "PDF'e bak, TP ve stop arasındaki farkları yakala". 82 grafiğe (son 90 gün, son sistem) baktım:
  TP'ler çoğunlukla merdiven gibi düzenli trend (EMA'lar açık; FUSDT, NXPC, ASTR, BANANA...) ve güçlü düşüşte SHORT; stoplar
  çoğunlukla 1-3 dev mumla yapılmış tepe (pompa) sonrası geri çekilme (JUP, SUPER, SUI, TNSR, BEAMX, JOE) ve sert V dönüşü
  sonrası SHORT (HOLO x2, SKR, UNI); 18.09-04.10 arası LONG stop kümesi (14 stop). 18 ay CSV (415 iş, 3 dönem) ile sınandı:
  sivri tepe ≥3.5 ATR çıkan işlemler +1.8 / +13.2 / +0.2 (tutarsız), sivri & genç trend kombinasyonları 2. dönemde hep artı,
  tek mum ≥0.5 -7.0 / +6.1 / -5.3; trend yaşı R/iş farkı tutarlı (yaşlı trend TP %34, genç %26) ama genç trend işlemleri
  toplamda artı (filtre toplam R'yi düşürür); yön, gün, seri-zarar molası tutarsız. Yeni kural bulunamadı.
- Başabaş 2. test (şimdiki sistem, Nis-Eki 26): canlı +36.5 · 1R -14.0 (15 stop kurtarıp 13 TP kaçırıyor) · 1.5R -1.7 · 2R 0
  → red, önceki dönemler çalıştırılmadı. TP 2.5 / 3 (MFE tahmini, 18 ay): -4.4 / +0.7 → TP 2.2 kalır.
- 15:32 "kodla": ENTRY_BUFFER_ATR (giriş onay ucundan X ATR ötede). COMPARE_SETS["giris"]: canlı · giriş +0.1 · +0.2 ·
  giriş+stop 0.1 yukarı (stop payı 0.2) · giriş+stop 0.2 yukarı (stop payı 0.1). `/backtest 180 giriş` (+ önceki, önceki2).
- Giriş yeri testi (Nis-Eki 26): canlı +36.3 · giriş +0.1 ATR +6.8 · +0.2 -0.8 · giriş+stop 0.1 yukarı +11.0 · 0.2 -3.8 →
  red (33 işlem dolmadı, 12'si TP; TP→erken 7, TP→stop 4). Erken çıkışı eski çizgide bırakmak tahmini +19 → yine red.
- 17:04 kullanıcı Gemini raporu (1 hafta canlı, 38 işlem, %63, +%16.4): kodda TP/stop/sonuç takibi yok → rapor uydurma
  (24×2-14 = +34R, %16.4 tutmuyor). Kodun içinde Telegram token'ı açık → kullanıcıya BotFather /revoke söylendi.
  "Kodla": EMA200_ORDER (EMA100 > EMA200 ×1.001), NEW_HIGH_BARS / NEW_HIGH_LOOKBACK (temastan önceki N mumda önceki 92 mumun
  zirvesi). add_atr EMA200 sütunu ekliyor. COMPARE_SETS["gemini"]: canlı · EMA200 · son 4 mum · son 8 mum · EMA200+4.
  `/backtest 180 gemini` (+ önceki, önceki2).
- Gemini testi (Nis-Eki 26): canlı +36.5 · EMA200 +27.4 · son 4 mum +24.2 (R/iş 0.31 ama yarı işlem) · son 8 mum +37.7 ·
  ikisi +19.7 → red. Kullanıcı örnekleri RESOLV 01.10 21:00 (tepe 2 mumu 11.8 ATR, trend 9 mum) ve MAGMA 02.10 20:30 (bacak
  iğneli, 14 saat yatay sonra stop): sivri ≥5/6/8 ATR ve genç trend kombinasyonları 18 ayda başa baş (TP %22 ama toplam
  -2..+5R), iğneli bacak (gövde <0.3) +9.5 / +20.0 / +2.5 → kural yok. "Tamam": COMPARE_SETS["yatay2"] = şimdiki canlı +
  4 / 8 / 12 saatte stop girişe; `/backtest 180 yatay` artık bu sete gidiyor.
- 17:22-17:24 kullanıcı AXLUSDT 04.10 01:15 LONG stop ("tepeden sonra zigzag yaparak inmiş, temiz düzeltme değil"; düz_iğne
  0.31 → iğne kuralı yakalamıyor), "kodla, yatayın içinde olsun": zigzag(df,i,side) = düzeltme mumlarında (tepe+1..temas-1)
  trend yönlü mum oranı + renk değişimi sayısı; ZIGZAG_MAX / ZIGZAG_MIN_BARS=3. yatay2 setine 2 ayar eklendi (> %50, > %34).
  CSV'de duz_zigzag, duz_donus; /incele de gösteriyor.
- 17:28 kullanıcı CARVUSDT 05.10 07:45 LONG erken -0.25R: "yataydan tek dev mumla başlamış, sonra EMA testi yok; test olsa
  girilebilirdi". Kural 2 (prior_touch_ok) yataydaki EMA'ların hafif sıralı olmasıyla trend başlangıcını yatay bölge sanıp
  oradaki temasları sayıyor. ÖNERİ (kodlanmadı, kullanıcı: "önceki testler bitsin buna geçeriz"): kalkış k = fiyatın EMA20'nin
  0.5 / 1 ATR üstüne çıktığı ilk mum (şimdi L > E20), temas k'dan sonra ve tepeden önce olmalı. Yatay testleri bitince.
- Yatay+zigzag (Nis-Eki 26): canlı +36.5 · 4s +26.5 · 8s +34.9 · 12s +38.2 (1 zaman stopu) · zigzag >%50 +35.5 · >%34 +36.1
  (AXL düz_zigzag 0.25 → yakalanmadı) → red. 17:32 "kodla": PRIOR_TOUCH_SEP_ATR (kural 2 kalkışı = fiyat EMA20'den X ATR
  ayrıldığı ilk mum). Sentetik testte yataydan dev mumla başlayan trendde 0 ATR "temas var" (hata), 1 ATR "yok" (doğru).
  COMPARE_SETS["teyit"]: canlı · 0.5 / 1 / 1.5 ATR. CSV'de teyit_05, teyit_1. `/backtest 180 teyit` (+ önceki, önceki2).
- Teyit testi 3 dönem (Nis-Eki 26 / Eki-Nis / Nis-Eki 25): canlı +36.5 / +37.0 / +13.0 (18 ay +86.4, 412 iş, düşüş 17.7, en
  kötü ay -7.4) · 0.5 ATR +32.9 / +38.8 / +15.7 · 1 ATR +35.5 / +40.7 / +20.3 · **1.5 ATR +45.1 / +41.0 / +17.2 (18 ay
  +103.4, 298 iş ~17/ay, ay ort 6.3, eksi ay 3/17, en kötü ay -3.2, düşüş 11.7)**. 2. dönemde eşik büyüdükçe iyileşiyor.
  LIVE_RULES PRIOR_TOUCH_SEP_ATR=1.5 → 15.10 19:01 kullanıcı "kuralı yükleyelim" → canlıda.
- 15.10 akşam: tüm coinler (525) testi +43.2 vs 500 coin +45.1 → 500'de kalındı. Aynı anda en fazla 2 işlem sınırı 18 ayda
  hiç işlem engellemedi (skip_open 0/0/0). Toplu sinyal (≥5) filtresi 87 / 183 / 122 kurulum eledi; tahmini değeri
  -16.5 / +9.9 / -7.8 (toplam -14.4R; erken -0.3, mfe≥2.2 → +2.1, değilse -1.1) → filtre kalıyor. Daha çok coin = filtre
  daha sık devreye giriyor, 525'in fayda etmemesinin sebebi bu.
- 19:14 kullanıcı "işlem sayısını 5 yapıp test etsek" → "kodla": COMPARE_SETS["toplu2"] (şimdiki canlı sistem, 1.5 ATR
  dahil): canlı (toplu 5+, en fazla 2) · toplu 8 · toplu 10 · toplu kapalı · toplu kapalı + en fazla 5 işlem.
  `/backtest 180 toplu` artık bu sete gidiyor (eski set: toplu, 14.10 kuralları). Canlı ayar değişmedi.
- Toplu testi (Nis-Eki 26): canlı (5+) +44.8 (116 iş, düşüş 11.9) · 8 coin +40.2 · 10 coin +44.6 (137 iş) · filtre kapalı
  +33.8 (190 iş, 11 işlem 2 sınırına takıldı) · kapalı + en fazla 5 işlem +33.4 (200 iş, düşüş 12.9). Canlıda elenen 85
  kurulum filtre kapalıyken: 13 TP / 25 stop / 46 erken = -11.4R (tahmin -16.5 idi) → filtre ve 2 işlem sınırı kalıyor,
  önceki dönemler çalıştırılmadı.
- 21:10 kullanıcı: "17 işlem çok az, artırmanın yolunu bul, her şeyi benden bekleme". Önceden denenip reddedilenler: 5m, 30m,
  1h, 525 coin, toplu filtre kapalı / 8 / 10, en fazla 5 işlem, kural 2 0.5/1 ATR. Kendi başıma hazırladım:
  COMPARE_SETS["artir"] = şimdiki canlı sistemden tek tek: - kural 1 / 2 / 4 / 5 / 6, - iğneli git-gel, - dip/tepe tabanı,
  onay 3. mum, stop ≥ %0.3, önünde ≥ 0.5R yer (11 ayar). `/backtest 180 artır` (+ önceki, önceki2). 3 dönemde de kârı
  düşürmeden işlem ekleyen gevşetmeler birlikte ikinci testte denenecek. CSV'deki özelliklerle eşik taraması da yapılabilir.
- Artır 1. dönem (Nis-Eki 26, canlı 115 iş +45.1, düşüş 11.9). Kaldırınca eklenen işlem / R: kural 1 +11 / -1.3 · kural 2
  +125 / -26.0 · kural 4 +6 / +1.4 · kural 5 +36 / -11.8 · **kural 6 +35 / +9.4 (toplam +54.5, düşüş 12.8)** · iğneli
  git-gel +18 / -1.1 · dip/tepe tabanı +31 / -2.4 · onay 3. mum +8 / +0.6 · stop ≥ %0.3 +12 / 0.0 · yer 0.5R +40 / +0.1.
  Analiz: scratchpad/an/artir_an.py. Önceki, önceki2 bekleniyor.
- Artır 2. dönem (Eki 25-Nis 26, canlı 109 iş +43.2, düşüş 5.3). Eklenen işlem / R: kural 1 +6 / -2.4 · kural 2 +119 / +15.0
  · kural 4 +4 / -2.7 · kural 5 +40 / +6.5 · kural 6 +27 / -3.5 (1. dönemde +9.4 → tutarsız) · iğneli +11 / -3.3 · dip/tepe
  tabanı +28 / -0.7 · onay 3. mum +8 / +2.4 · stop %0.3 +8 / -0.9 · yer 0.5R +33 / +7.4. İki dönemde de artı: onay 3. mum
  (+0.6 / +2.4), yer 0.5R (eklenenler +0.1 / +7.4; toplam -2.0 / +7.4).
- Artır 3. dönem (Nis-Eki 25, canlı 75 iş +17.2, düşüş 11.1). Eklenen R: kural 1 -2.7 · kural 2 -5.1 · kural 4 -1.3 · kural 5
  +11.9 · kural 6 -7.0 · iğneli -2.4 · taban -5.2 · onay 3. mum -1.3 · stop %0.3 -2.9 · yer 0.5R -4.1.
  18 AY TOPLAM (eklenen işlem / R): kural 1 24 / -6.5 · kural 2 321 / -16.2 · kural 4 15 / -2.5 · kural 5 108 / +6.6 (-11.8 /
  +6.5 / +11.9 tutarsız) · kural 6 88 / -1.1 · iğneli 36 / -6.9 · taban 78 / -8.3 · onay 3 24 / +1.7 · stop %0.3 27 / -3.8 ·
  yer 0.5R 93 / +3.3. SONUÇ: hiçbir kural 3 dönemde de boşuna işlem kesmiyor.
  Eklenenlerin içinde 3 dönemde artı alt gruplar (scratchpad/an/added_explore.py, room_explore.py; eşikler hassas → ezber
  riski): yer 0.5R + stop ≥ 1.5 ATR 46 iş +12.5 (+7.5/+3.5/+1.5; 1.4 ATR'de bozuluyor) · yer 0.5R + iğne ≤ %45 30 iş +12.8
  (≤ %50'de 3. dönem eksi) · kural 5 + önünde ≥ 1.5R 60 iş +13.2 (-1.6/+5.2/+9.6).
  Kodlandı (varsayılan kapalı): ROOM_RELAX_R / ROOM_RELAX_WICKY / ROOM_RELAX_RISK_ATR, TOUCH_WICK_ROOM_R (kural 5'e uymayan
  temas yer kontrolüne ertelenir). COMPARE_SETS["esnet"] 6 ayar. commands: "esnet", "önceki3" (--ago 3×gün; rakam RR
  sanılmasın diye clean'de). Karar dönemi: önceki3 = Eki 24-Nis 25, hiç bakılmamış → aynı zamanda bugünkü bütün canlı
  kuralların dönem dışı sınaması.
- ESNET ÖNCEKİ3 (Eki 24-Nis 25, hiç bakılmamış, 168 coin): **canlı ayar 49 iş (TP 10 / stop 15 / erken 24) -0.5R**, düşüş
  7.6 → bugünkü sistem dönem dışında başa baş (14.10 notu: Ekim 2024 30 gün eski kurallar da 0.0R). Esnetmeler: A stop ≥ 1.5
  ATR +9 iş +0.3 · B iğne ≤ %45 +5 iş +4.4 · C kural 5 + 1.5R +18 iş -4.5 (RED) · A+B +13 iş +5.7 · üçü +1.2.
  Sonraki adım (kodlandı, sonraki dalında; kullanıcı testleri bitirince yüklenecek): COMPARE_SETS["gelisim"] = 15.10'da
  eklenen kurallar sırayla (sabahki canlı → 03-07 kalktı → iğneli + taban → derin kapanış → 1.5 ATR → + A+B).
  `/backtest 180 gelişim önceki3`, `önceki4` (= --ago 4×gün, Nis-Eki 24). Bugünkü kurallar dönem dışında da işe yarıyor mu.
- GELİŞİM ÖNCEKİ3 (Eki 24-Nis 25): sabahki canlı 113 iş -2.1 (düşüş 16.0, erken 76) → 03-07 kalktı 131 iş -7.3 (Δ -5.2)
  → iğneli + taban 85 iş -2.5 (Δ +4.8) → derin kapanış -1.8 (Δ +0.7) → 1.5 ATR 49 iş -0.5 (Δ +1.3, düşüş 7.6) → + esnet A+B
  62 iş +5.2 (Δ +5.7). Bugünkü kurallar dönem dışında da yön olarak doğru (03-07 kaldırma hariç: dönemler +7.2 / -1.2 /
  -5.2). Sistem bu dönemde her hâliyle başa baş. önceki4 bekleniyor.
- GELİŞİM ÖNCEKİ4 (Nis-Eki 24, 155 coin): sabahki canlı 90 iş -0.4 → 03-07 kalktı -0.9 (Δ -0.6) → iğneli + taban -4.2
  (Δ -3.2) → derin kapanış -3.4 (Δ +0.8) → 1.5 ATR 44 iş +0.6 (Δ +4.0) → + esnet A+B 53 iş -5.0 (Δ -5.6, 15 iş -8.0).
  KARAR ÖZETİ (5 dönem): 1.5 ATR ve derin kapanış her dönemde artı (gerçek). İğneli + taban 4/5 artı. 03-07 kaldırma
  +7.2 / -1.2 / -5.2 / -0.6 (toplam ~0, işlem +3/ay). Esnet A+B önceki3 +5.7 ama önceki4 -5.6 → RED (veri madenciliği
  ezberi). Canlı sistem dönem dışında başa baş: önceki3 -0.5 (49 iş), önceki4 +0.6 (44 iş). İşlem sayısını kârlı artıran
  yol bulunamadı; canlı değişmedi.
- 15.10 22:19 "bak": 2024 neden çalışmadı (5 dönem, canlı ayar işlemleri; scratchpad/an/regime_load.py, eqfilter.py,
  mktcorr.py). 2024: TP oranı ~%20 (2026 ~%37), coinlerin BTC korelasyonu ort. 0.5-0.6 (2026 ~0.3), 155-220 coin.
  Hacim sırasına göre (bugünkü sıra) R, P5/P4/P3/P2/P1: 1-100 -2.6/-1.6/+2.1/+12.5/+2.5 · 401-500 +8.2/+4.2/+2.4/+10.0/
  +18.1 (5 dönemde artı tek grup). Aylık R ile korelasyon: btc_kor -0.39, ema_acilim -0.40, bacak_atr -0.36, sıra +0.35.
  Önceden bilinebilir rejim filtresi aranıp BULUNAMADI (hepsi 5 dönemde tutarsız): son 5/10/20 işlem toplamı, aynı yönde
  son 5/10, son 7/14/30 gün, coinin BTC korelasyonu < 0.5/0.6/0.7, piyasa ort. korelasyonu (3/7/14 gün) < 0.4/0.45/0.5,
  EMA açılımı, bacak ATR. Sonuç: sistem altcoinlerin kendi trendleriyle gittiği dönemde kazanıyor (Eyl 2025'ten beri
  neredeyse her ay artı), BTC ile birlikte hareket edilen dönemde başa baş; bunu önceden ayıran işaret verimizde yok.
- 22:43 kullanıcı: "ay sonuna kadar canlıdaki sistemle devam, grafik incelemeye devam". Canlı değişmedi, risk kuralı
  (2 ay eksi → 1R 10$) eklenmedi. Bundan sonra yeni kural 5 dönemde sınanır: `/backtest 180 X` + önceki + önceki2
  (kural seçimi) + önceki3 + önceki4 (dönem dışı; 2024 verisi, 155-220 coin, daha uzun sürer).
- 23:06 kullanıcı: MEXC araştırması sonrası "Bybit'teki bütün coinlere göre backtest". bybit.py (v5 herkese açık API:
  instruments-info, tickers, kline 1000 mum/istek, saniyede ≤15 istek, 403/451 = bölge engeli → hata mesajı). norm():
  1000PEPE / SHIB1000 / 1MBABYDOGE → PEPE / SHIB / BABYDOGE (borsalar arası eşleştirme). backtest --exchange bybit: coin
  listesi Bybit'in bütün USDT linear perpetual'ları (hacme göre), mumlar diske KAYDEDİLMEZ (her test yeniden indirir,
  ~650 coin x 18 istek ≈ 13 dk), komisyon taker %0.055 / maker %0.02, CSV'de binance_da. COMPARE_SETS["bybit"]:
  bütün coinler / sadece canlı botun Binance (ilk 500) coinleri / sadece Binance'te olmayanlar (yeni işlemler);
  config "coins" anahtarı process()'te filtreler. Toplu sinyal sayımı bütün Bybit coinleri üzerinden.
  `/backtest 180 bybit` (+ önceki, önceki2, önceki3, önceki4). Render'dan Bybit'e erişim denenmedi (bu ortam ulaşamıyor).
- BYBIT 1. DÖNEM (Nis-Eki 26, 790 USDT perp, komisyon %0.055): bütün coinler 135 iş +9.0 · canlı botun Binance coinleri
  (Bybit verisiyle) 91 iş +3.2 (düşüş 11.4) · sadece Bybit'te olanlar 44 iş +5.7 (40 coin; içinde hisse perp'leri var:
  SAMSUNG, AMZN, BABA, EWY, WDC, SKHY...). ÖNEMLİ: aynı coinler aynı dönem Binance verisiyle 115 iş +45.1. Ortak setup
  sadece 34 (29'u aynı sonuç); Binance'e özgü 81 işlem +43.0, Bybit'e özgü 57 işlem +2.2. Kurallar mum ayrıntısına çok
  duyarlı (iğne oranı, gövde, temas) → Binance sonucunun bir kısmı o mumlara özgü şans olabilir (önceki3/4'te de canlı ~0).
  Sonraki: `/backtest 180 bybit gelişim` = gelişim seti Bybit verisiyle, sadece ortak coinler (--coins binance varsayılan;
  diğer coinlerin verisi indirilmez). Hangi kural başka borsanın mumlarında da tutuyor. commands: "bybit" artık sadece
  --exchange ekler, set yazılmadıysa bybit seti.
- BYBIT GELİŞİM (Nis-Eki 26, Bybit verisi, sadece canlı botun Binance coinleri): sabahki canlı 176 iş +0.9 (TP %22) →
  03-07 kalktı +4.7 (Δ +3.8) → iğneli + taban -1.1 (Δ -5.8) → derin kapanış +10.7 (Δ +11.8) → 1.5 ATR 101 iş +5.9
  (Δ -4.8, TP %28) → + esnet A+B +12.6 (Δ +6.7). Aynı coin ve dönemde Binance verisiyle canlı +45.1 (TP ~%37).
  KURAL SAĞLAMLIĞI (Binance 3 dönem + önceki3 + önceki4 + Bybit = 6 görünüm): derin kapanış 6/6 artı (gerçek) · 1.5 ATR
  5/6 · iğneli + taban 4/6 (şüpheli) · 03-07 kaldırma karışık · esnet A+B önceki4'te -5.6 (red).
  Bybit'i yeni coinler için ekleme: ŞİMDİLİK HAYIR (Bybit verisinde sistem zayıf; yeni coinler 6 ayda 44 iş +5.7).
  Not: Bybit mumları daha gürültülü olabilir (fiyat Binance'te oluşuyor) → Bybit testi sistemi cezalandırıyor olabilir;
  ama 2024 (Binance verisi) de ~0 → beklenti backtestten düşük tutulmalı.
- 16.10 00:3x kullanıcı "araştır" (ikinci strateji). Öneri: trend takibi (Donchian kırılımı, birden çok N: 20/50/100 gün,
  takip eden stop, en likit 20-50 coin, 4s/günlük; kaynak: "Catching Crypto Trends" SSRN 5209907, OOS Sharpe >1.5).
  Günlük ters dönüş (küçük coin, likiditeye bağlı), BTC gün içi momentum, funding/OI uçları: zayıf/uygun değil.
  Kullanıcı şüpheli ("kârlıysa herkes yapardı"); yayın sonrası getiri düşüşü ve dayanma zorluğu anlatıldı.
  KODLANMADI, "kodla" bekleniyor. Canlı ay sonuna kadar aynı.
- 16.10 00:54 "kodla": trend_bt.py (ayrı simülasyon). Donchian kırılımı: kapanış önceki N mumun en yükseği/düşüğü dışında →
  sonraki açılışta giriş; stop giriş ∓ 3 ATR(20) = 1R, takip eden stop (uç nokta ∓ 3 ATR, sadece lehte); N = 20/50/100 üç
  alt sistem (her biri 1/3 R); maliyet taraf başına %0.07 (komisyon+kayma) + günde %0.03 funding; dönem sonu açıklar son
  kapanıştan. 6 ayar: günlük 20/50/100 L+S top30 · sadece LONG · günlük 20 · top60 · 4 saatlik · en fazla 5R açık risk.
  En likit 60 coin yüklenir (USDC/FDUSD vb. hariç), 130 gün ısınma. `/backtest 180 trend` (+ önceki ... önceki4).
  backtest --trend → main'de coin listesi alındıktan sonra trend_bt.run. Sahte veride mantık testi: scratchpad trend_unit.py.
- TREND 1. DÖNEM (Nis-Eki 26, bugünkü hacme göre ilk 30/60): ana ayar 380 alt işlem %38 +31.1R düşüş 6.3 · sadece LONG
  +33.5 · N=20 +37.4 · ilk 60 +35.7 · 4 saatlik +41.1 ama düşüş 48.8 (RED) · en fazla 5R açık +7.8 (düşüş 3.8). SHORT'lar
  ~-2R (başa baş). SORUN: QNT 23.09-28.09 73.75→286 tek işlem 3 alt sistemde +21.6R (toplamın 2/3'ü); QNT bugün ilk 30'da
  çünkü yükseldi → seçim yanlılığı. Düzeltme: coin listesi dönem başından önceki 30 günün USDT hacmine göre
  (trend_bt.volume_at: bütün işlemdeki perp'ler, /fapi/v1/klines 1d, k[7]); alınamazsa bugünkü sıra + raporda uyarı.
  1. dönem de bu düzeltmeyle yeniden çalıştırılmalı.
- TREND 1. DÖNEM DÜZELTİLMİŞ (dönem başı hacmine göre; liste: BTC ETH SOL XRP DOGE ... + ARIA EDGE NOM RAVE RIVER SIREN
  STO 币安人生 gibi o anki popüler coinler, QNT yok): ana +1.7R (314 iş, düşüş 7.3) · sadece LONG +4.7 · N=20 +8.1 (düşüş
  14.2) · ilk 60 -6.4 · 4 saatlik +10.3 (düşüş 47.6) · en fazla 5R +3.7. SHORT -3.0. Önceki +31.1R'nin neredeyse tamamı
  seçim yanlılığıydı. Diğer 4 dönem bekleniyor.
- 16.10 01:28 kullanıcı: trend takibini bırak, kendi sistemle (EMA20 geri çekilme) devam. Diğer trend dönemleri
  çalıştırılmadı; trend_bt.py repoda duruyor (canlıyı etkilemiyor, /backtest 180 trend ile çalışır).
- 16.10 01:29 "sisteme eklenecek bir şey var mı bak": 6 görünüm (Binance 5 dönem + Bybit, canlı ayar 493 iş +111.6R;
  scratchpad an/load6.py). Kısmi TP (yarısı 1R'de / 1/3'ü 1R'de / yarısı 1.5R'de) 6'sında da eksi: -49 / -33 / -25R.
  CSV'deki bütün özellikler x eşikler: elenen grup 6'nın ≥5'inde eksi ve toplam ≤ -5R olan YOK. En yakın: bacakta tek mum
  payı > %48 (50 iş, -4.9R, 4/6 eksi, P2 +12.2) → zayıf. Yeni kural ancak henüz ölçülmeyen bir özellikten gelir
  (kullanıcının grafik incelemesi). Kullanıcıya grafik için `/backtest 90 canlı` (bütün işlemler PDF) verildi.
