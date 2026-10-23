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
- 16.10 01:36 kullanıcı (örnek 09.10 12:30, bot zaten girmiş, TP): "2 mumlu temas" varyasyonu; 2. mum dibi kırabilir
  ("2'li mum olsun yeter"). TWO_BAR_TOUCH: temastan sonraki mum temasın dibini kırarsa (SHORT tepesini) iptal yerine,
  kendisi de EMA20'ye değip doğru tarafta kapattıysa iki mum birlikte temas; bölge = iki mumun en dibi / en tepesi,
  onay pencere 2. mumdan sonra yeniden 2 mum, onay = iki mumun en tepesinin üstünde kapanış; dönüşte uygulanmaz.
  CSV'de iki_mum. COMPARE_SETS["ikimum"]: canlı / + 2 mumlu. `/backtest 180 iki mum` (+ önceki ... önceki4, + bybit).
  Not: dibi kırmayan 2. mum zaten eskisi gibi; 2. mumun kendisi de ayrıca temas sinyali olarak değerlendiriliyordu.
- 01:39 kullanıcı: "mumlar bu şekilde olacak, gövdeleri büyük olmayacak". TWO_BAR_BODY_ATR: iki mumun gövdesi en fazla X
  ATR. ikimum seti: canlı · 2 mumlu gövde ≤ 0.3 ATR · ≤ 0.5 ATR · sınırsız. (İlk 2 mumlu commit main'e birleşmiş ama
  gönderilmemişti; gövde şartıyla birlikte yüklendi.)
- 2 MUMLU TEMAS 5 dönem (Nis-Eki 26 / Eki-Nis / Nis-Eki 25 / önceki3 / önceki4), canlıya göre fark: gövde ≤ 0.3 ATR
  -2.3 / +0.7 / +1.9 / +1.0 / +0.2 (toplam +1.5, 15 ek işlem) · ≤ 0.5 ATR -3.6 / +0.3 / +3.7 / +1.0 / +0.2 (+1.6) ·
  sınırsız -1.8 / +0.3 / +2.5 / +1.0 / +0.2 (+2.2, 24 ek işlem). 30 ayda ~20 işlem (ayda <1), etkisi sıfıra yakın →
  canlıya değmez (canlı tarama tarafında da ayrıca kodlanması gerekirdi). Canlı değişmedi.
- 02:07 "kodla": TWO_BAR_ANY (2 mumlu temas her sıra): temastan sonraki mum EMA20'ye değip doğru tarafta kapattıysa
  ve iki gövde küçükse, dip hangisinde olursa olsun iki mum birlikte temas; onay iki mumun en tepesinin üstünde kapanış,
  bekleme 2. mumdan sonra 2 mum. _two_bar_ok() ortak kontrol. COMPARE_SETS["ikimum2"] (gövde ≤ 0.3 / 0.5 / sınırsız);
  "iki mum" komutu artık ikimum2'ye gider.
- 02:08 kullanıcı: onay kaçıncı mumda gelirse daha iyi? 6 görünüm (canlı ayar 493 iş): klasik onay 1. mum 248 iş TP %32
  +0.27R/iş, 6/6 artı (+0.5/+2.5/+12.3/+23.4/+25.6/+3.1) · klasik onay 2. mum 103 iş TP %28 +0.07R/iş (+3.8/-4.0/-0.7/
  +1.9/+7.4/-1.2) · dönüş (hep 2. mum) 142 iş +0.26R/iş · onay 3. mum (artır testi) +0.6/+2.4/-1.3 ~0. Sonuç: 1. mum en
  güçlü; 2. mumu kaldırmak işlem sayısını ~%20 azaltır, toplam kârı az düşürür → değişiklik yok.
- 2 MUMLU HER SIRA 5 dönem (canlıya göre fark): gövde ≤ 0.3 ATR -0.3 / +3.8 / +2.2 / +1.0 / -1.1 (toplam +5.6, 3/5
  artı, 30 ayda ~13 ek işlem; 2 mumlu işlemlerin kendisi 5/5 artı +15.3R ama değiştirdiği klasik işlemler -9.7R) · ≤ 0.5
  -4.3 / -1.1 / +4.6 / +1.2 / -0.3 (+0.1) · sınırsız -13.0 / -6.9 / +0.2 / +1.9 / +3.9 (-13.9). KARAR: canlıya alınmadı
  (4/5 şartını geçmedi, etki ayda ~+0.2R, işlem sayısı aynı). Canlı değişmedi.
- 04:08 kullanıcı AXL 04.10 01:15 tekrar: "düzeltme berbat, asla girmem". Eski zigzag ölçüsü tepeden temasa 5 mum →
  0.25, yakalamadı. 04:10 "kodla": trade_rules.choppiness(df, i): temastan önceki 12 mumda renk değişimi sayısı (doji
  önceki rengi sürdürür) + ortalama gövde/ATR; CHOP_FLIPS_MIN / CHOP_BODY_ATR / CHOP_BARS, durum "choppy". CSV'de
  dalga_donus, dalga_govde. COMPARE_SETS["dalga"]: canlı · ≥7 & gövde ≥0.5 · ≥6 & ≥0.6 · ≥7 gövde serbest.
  `/backtest 180 dalga` (+ önceki ... önceki4). Eşikler CSV'den ayrıca taranacak; AXL/MAGMA/CARV değerlerine bakılacak.
- DALGA 5 dönem (canlıya göre): ≥7 & gövde ≥0.5 -5.2 / 0.0 / +0.2 / +3.4 / +1.4 · ≥6 & ≥0.6 +0.2 / +4.1 / -4.7 / +2.3 /
  -0.4 · ≥7 -5.2 / -0.8 / -2.0 / +1.4 / -0.7 → renk değişimi sayısı RED. AXL dalga_donus 5, gövde 0.67 (yakalanmadı).
  CSV'den (canlı işlemlerin dalga_govde değeri): temastan önceki 12 mumun ort. gövdesi ≥ 0.8 ATR olanlar 26 iş, -8.9R,
  5/5 dönem eksi (-0.7 / -4.1 / -2.7 / -0.3 / -1.0; eşik ilk 3 dönemden seçildi, son 2'de de eksi). ≥0.7: 65 iş -10.0R
  (4/5) · ≥0.85: 11 iş -4.9R (4/5). ADAY: gövde ≥ 0.8 ATR ise girme (+~0.3R/ay, ayda ~1 işlem az). HOME 18.09 0.81.
  Kullanıcının "yükle"sini bekliyor (canlı için ayrı parametre: ortalama gövde sınırı).
- 04:28 HOME 18.09 20:15 dönüş, erken çıkış -0.19R ama mfe 7.5R (TP olacaktı). Sığ kapanışta (< 0.03/0.05/0.1/0.15 ATR)
  erken çıkmasaydık: 0.0 / -6.8 / -13.0 / -11.7R → erken çıkış kalır.
- 04:34 kullanıcı: gövde ≥0.8 kuralını yükleme ("faydası yok"). Canlı değişmedi.
- 16.10 04:38 kullanıcı (yatarken): "en baştan analizleri incele, kaçırdığımız bir şey var mı, kâr ve işlem sayısı, ya da
  güzel bir fikir". İnceleme:
  * HİÇ TEST EDİLMEMİŞ: temas sinyalinin temel ayarları (strategy.py, satıcıdan): Stoch(5,3) LONG < 30 / SHORT > 70,
    düzeltmede en fazla 2 ters mum (MAX_EXCEPTION_CANDLES), tepe en fazla 30 mum önce (RECENT), temas toleransı %0.03,
    EMA_GAP %0.1. Ayrıca tepeden sonraki İLK temas dışında sinyal yok (L[after:i] > E20 şartı). İşlem sayısının asıl
    kaynağı bunlar. Kodlandı: config "sig" (sinyal bulunurken strategy sabitlerinin üzerine yazılır, _st_override),
    sinyal kümesi ve toplu sinyal sayımı (touch_by) ayar başına. COMPARE_SETS["temel"]: canlı · stoch 40/60 · stoch yok ·
    ters mum ≤3 · ≤4 · tepe ≤45 mum · tolerans %0.15. `/backtest 180 temel` (+ önceki ... önceki4). YÜKLENDİ (test).
  * Haftanın günü: tutarlı etki yok (Paz toplam -0.8, 4/6 eksi ama küçük).
  * İşlem kalitesine göre risk (6 görünüm): klasik onay 1. mum 1.5R / 2. mum 0.5R / dönüş 1R → toplam 111.5 → 141.7R
    (+%27, 5/6 görünümde daha iyi), en büyük düşüşler %15-30 artar (getiri/düşüş 11.3 → 12.4). Kodlanmadı; öneri.
  * TP düşürme (kazanma oranı için): eski testte TP 1.5 -9.9 vs 2.2 +12.8 → hayır. Kısmi TP 6/6 eksi → hayır.
- 04:45 kullanıcı: "tek tek çok uzun sürüyor". backtest --seri N: aynı karşılaştırmayı N dönem arka arkaya (ago 0, d, 2d…)
  tek süreçte çalıştırır (main() tekrar çağrılır, SERI_MODE'da grafik yok), her dönemin raporu + CSV'si gelir, sonunda
  seri_summary: her ayarın ilk ayara göre dönem farkları, toplam, artı dönem sayısı, işlem farkı (✅ ≥ n-1 artı ve
  toplam artı). commands: karşılaştırma komutunun sonuna "seri" → --seri 5. Toplam süre aynı, komut tek.
- TEMEL 2 dönem (Nis-Eki 26 / Eki 25-Nis 26; seri kullanıcı isteğiyle yarıda bırakıldı): stoch 40/60 +27/+21 iş
  -16.2 / -6.2 · stoch yok +47/+45 iş -18.0 / +0.9 · ters mum ≤3 -7.1 / -0.3 · ≤4 -5.1 / +0.6 · tepe ≤45 mum etkisiz (0
  iş) · tolerans %0.15 -16.8 / -7.6. Temas tanımının temel ayarları (satıcınınki) doğru; gevşetmek TP oranını %36'dan
  %29-32'ye düşürüyor. RED.
- 05:04 kullanıcı: "onay mumunun dibi EMA20'ye değen ya da çok yakın kapatanların kazanma oranı". CSV'ye yeni ölçüler
  (run_df): onay_uc_ema_atr (onay mumunun dibi - EMA20, ATR; SHORT tepe, işaret ters), onay_kap_ema_atr, giris_ema_atr,
  onay_govde_atr, onay_mum (temastan kaç mum sonra), temas_stoch. COMPARE_SETS["analiz"] = sadece canlı ayar.
  `/backtest 180 analiz seri` (5 dönem, hızlı).
- ANALİZ 5 dönem (canlı ayar 392 iş, yeni CSV ölçüleri): onay mumunun dibi EMA20'ye değmiş (≤0) 156 iş TP %28 +0.13R/iş
  (2024'te -1.3 / -10.1) · çok yakın 0-0.2 ATR 126 iş %35 +0.36 · 0.2-0.5 94 iş %34 +0.35 · >0.5 16 iş. Onay kapanışı EMA20'ye
  < 0.5 ATR: 40 iş %22, -6.9 / +8.9 / -3.0 / +4.3 / -5.8 (eşiğe çok duyarlı: < 0.6 → +23R) → kural yok. Temas stoch LONG < 10:
  23 iş TP %9 -9.8R (4/5 eksi) ama SHORT > 90 simetriği +6.1 → tek yönlü, az işlem → kural yok. Onay gövdesi > 1 ATR 15 iş
  -0.12R/iş. Sonuç: onay mumunun EMA20'ye yakınlığı kazanma oranını belirgin değiştirmiyor.
- 16.10 12:32 kullanıcı SUI 27.09 14:30 LONG stop: "düzeltmeyi çok yavaş, küçük küçük mumlarla yapmış". SUI düzeltme 12 mum,
  gövde 0.48. 5 dönem (analiz CSV): düzeltme ≥ 10 mum 7 iş, 0 TP (6 stop + 1 erken), -6.7R, 4/5 dönem eksi (5.'de yok).
  "Küçük mum" (gövde < 0.45 / 0.5) fark yaratmıyor (artı). Yavaşlık ölçüsü (derinlik ATR / mum) < 0.4: 14 iş -1.2 karışık.
  Gövde ≥ 0.8 ATR ile birlikte: 31 iş elenir, -14.4R, 5/5 dönem eksi (-1.8 / -5.3 / -3.7 / -2.5 / -1.0); kalan 361 iş
  TP %31.6 → %33.8, 99.3 → 113.6R (+%14). Kullanıcının kararı bekleniyor.
- 12:40 kullanıcı "mantıklıysa yükle" → CANLI DEĞİŞTİ: LIVE_RULES += BODY_AVG_MAX_ATR=0.8 (temastan önceki 12 mumun ort.
  gövdesi ≥ 0.8 ATR → "big_bodies"), CORR_BARS_MAX=10 (tepeden/dipten temasa ≥ 10 mum → "slow_corr"; tepe = LOOKBACK içinde
  en yüksek/düşük, trend_features ile aynı). Beklenen: ayda ~1 işlem az, ~+0.5R/ay, TP %31.6 → %33.8. Kontrol:
  `/backtest 180 kontrol seri` (yeni canlı / eski canlı, 5 dönem).
- KONTROL 5 dönem (canlı kodla, `/backtest 180 kontrol seri`, 16.10 09:57-10:06 UTC): yeni canlı − eski canlı = +1.9 / +5.2 /
  +3.7 / +2.6 / +1.0 → 5/5 artı, toplam +14.4R. 31 işlem elendi (-14.3R, içinde sadece 2 TP), eklenen yok. Yeni canlı
  dönem toplamları: 44.9 / 50.4 / 14.5 / -0.1 / 3.8 = 113.5R (30 ay, ~3.8R/ay, 364 işlem ~12/ay). Son 6 ay 106 işlem
  (~17.7/ay) TP %38.7, +44.9R. Analizle birebir tuttu; kural canlıda doğru çalışıyor.
- 16.10 17:22 kullanıcı HYPERUSDT 06.05.2026 04:45 SHORT dönüş erken -0.18R: "girerdim, trend temiz" → mfe 5.3R, tutsaydı
  TP. Erken çıkışlar (5 dönem 131): sonradan TP 29 (dönüşte 37'de 5); tutsaydık ~-51R vs gerçek -28R → erken çıkış kalır.
  Güçlü trend üçte biri (ema_acilim > 3.24): 43 erkenin 13'ü TP (%30), tutmak ≈ -0.14 vs -0.22R/iş, ~+3R / 30 ay → değişiklik yok.
  Dönüş vs klasik (5 dönem): dönüş 106 iş +0.34R/iş, klasik 258 iş +0.30R/iş (dönüş 4/5 dönemde iş başına daha iyi; sadece seyrek).
- 17:26 ESPUSDT 30.08.2026 11:30 SHORT dönüş erken -0.37R (mfe 0.23): "dönüş mumu tam çizgiye kapamış, girmezdim" (15.10'da
  aynı işlem temas gövdesi için örnekti, o kural RED). 17:29 "kodla": RECLAIM_CLOSE_MIN_ATR (dönüş mumu kapanışı EMA20'nin
  doğru tarafında en az X ATR; altı "weak_reclaim"), CSV donus_kap_ema_atr, COMPARE_SETS["cizgi"] canlı / 0.1 / 0.2 / 0.3 ATR.
  `/backtest 180 çizgi seri`. CHECK_TRADES'e ESP eklendi.
- ÇİZGİ 5 dönem (`/backtest 180 çizgi seri`, 16.10 14:45-14:55 UTC; canlı 42.6 / 50.5 / 16.4 / 0.0 / 3.8): fark ≥0.1 ATR
  -1.3 / -2.7 / -6.0 / -0.8 / +3.6 (1/5, -7.2R, -27 iş) · ≥0.2 +0.9 / -6.2 / -8.1 / +1.6 / +1.5 (3/5, -10.3, -46 iş) · ≥0.3
  +0.2 / -14.2 / -8.9 / -1.3 / +3.0 (2/5, -21.2, -68 iş) → RED. CSV (canlı 106 dönüş): kapanış < 0.1 ATR 27 iş 9 TP +7.2R
  (0.05-0.1: 18 iş +8.2R); < 0.05 ATR 9 iş 2 TP -1.0R (karışık, az). ESP 0.029 ATR. Çizgiye yakın kapanan dönüşler kötü değil.
- 16.10 22:01 kullanıcı "TP 2.3 / 2.4 / 2.5 / 3 / 4?" MFE tahmini (yeni canlı, kontrol CSV 5 dönem, TP olanlardan X'e
  gitmeyen stop -1.09 sayıldı): 2.3 +2.3 (4/5) · 2.4 +7.5 (4/5) · 2.5 -8.9 · 2.75 -11.5 · 3 -10.2 · 3.5 -2.7 · 4 -9.2 · 5 -28.5.
  TP olanların %96'sı 2.4'e, %89'u 2.5'e, %78'i 3'e gidiyor. 2.4 → 2.5 uçurumu 8 işlem (şans). Kullanıcı: "kalsın" → TP 2.2.
- 22:08 kullanıcı "işleme göre R hedefini yükseltsek (bazıları 3-4R görmüş)". MFE tahmini, giriş anında bilinen 16 ölçünün
  alt/üst üçte biri × TP 3/4 (64 deneme): en tutarlısı onay mumu gövdesi. Onay gövdesi ≥0.5 ATR (208 iş) TP 2.5 +11.0 (5/5),
  TP 3 +11.8 (3/5) · ≥0.65 (120 iş) TP 2.5 +10.5 (5/5), TP 3 +12.0 (4/5) · ≥0.8 TP 2.5 +5.1 (5/5). SHORT TP 3 +11.0 (3/5,
  zayıf). Küçük onay mumlarında yüksek TP kötü (genel TP 2.5'in eksi çıkma sebebi). 64 denemeden seçildiği için şans riski.
- 22:09 "kodla": TP_BIG_CONF_ATR / TP_BIG_RR (onay gövdesi ≥ X ATR → TP Y; res["rr"], CSV tp_kat). COMPARE_SETS["hedef"]:
  canlı · ≥0.5→2.5 · ≥0.65→2.5 · ≥0.5→3 · ≥0.65→3. commands "eski": --ago 5×gün, seride 2 dönem (önceki5 + önceki6, hiç
  bakılmamış 2023-2024). `/backtest 180 hedef seri` (5 dönem, kuralı bulduğumuz) + `/backtest 180 hedef eski seri` (sınav).
- HEDEF 5 dönem (gerçek backtest, 16.10 19:20-19:32 UTC; canlı 42.8 / 50.2 / 18.5 / 0.0 / 3.8 = 115.3R): fark ≥0.5→2.5
  +0.1 / +5.7 / +3.6 / +0.6 / +1.8 (5/5, +11.8) · ≥0.65→2.5 +3.9 / +4.2 / +2.7 / +0.3 / +0.3 (5/5, +11.4) · ≥0.5→3 -11.9 /
  +7.2 / +9.6 / -2.4 / +4.8 (3/5, +7.3) · ≥0.65→3 -3.8 / +3.2 / +7.2 / +0.8 / +0.8 (4/5, +8.2). MFE tahminiyle uyumlu (TP 2.5
  tutarlı, TP 3 dalgalı). Kural bu dönemlerden bulundu → karar `/backtest 180 hedef eski seri` (önceki5 + önceki6) sonucuna.
- HEDEF ESKİ 2 dönem (sınav, hiç bakılmamış; `hedef eski seri`): önceki5 (Kas 23-Nis 24, 46 coin, 59 iş) canlı -0.5 ·
  önceki6 (May-Eki 23, 33 coin, 36 iş) +6.7. Fark: ≥0.5→2.5 -8.2 / +1.8 · ≥0.65→2.5 -2.1 / +0.9 · ≥0.5→3 -5.7 / +4.8 ·
  ≥0.65→3 -0.1 / +2.4. önceki5'te ≥0.5→2.5: 2.2'ye gidip 2.5'e gitmeyen 3 işlem (EGLD, GRT, CHR) stopa döndü (-9.6R), 5
  işlem +0.3R kazandı. 7 dönem toplam: ≥0.5→2.5 +5.4 (6/7) · ≥0.65→2.5 +10.2 (6/7). Sınavda tutmadı (bir kaçan TP = -3.2R,
  uzayan TP = +0.3R → çok kırılgan). Canlıya alınmadı; TP 2.2 kalır.
- 22:56 kullanıcı "başka kurala göre artırsak". TP yükseltmenin yapısal sorunu: 2.2'ye gelip dönen işlem -3.2R. Öneri: kâr
  kilidi (2.2R'ye gelince stop +1.8 / +1.5R'ye, hedef 3-5R; dönen işlem ~-0.4R). Eski "2R'de stop girişe + TP 4" (eşleşik
  +3.6 / -6.9) stopu 0'a çekiyordu. 22:59 "kodla": BE_LOCK_R (BE_TRIGGER'a gelince stop girişin BE_LOCK_R kârına; 0 = eski
  başabaş), res lock_on / locked_exit, CSV cikis_turu "kâr kilidi", raporda "🔒 Kâr kilidi N". COMPARE_SETS["kilit"]: canlı ·
  2.2→+1.8 hedef 3 · 2.2→+1.8 hedef 4 · 2.2→+1.5 hedef 4 · 2.2→+1.5 hedef 5. Kilit mumu: stop sonraki mumdan geçerli (canlıda
  bot 5 sn'de bir bakıp stop emrini taşıyabilir). `/backtest 180 kilit seri` + `/backtest 180 kilit eski seri` (7 dönem).
- KİLİT 5 dönem (16.10 20:06-20:22 UTC; canlı 39.7 / 48.1 / 20.7 / -0.3 / 4.0 = 112.2R): fark 1.8→3R +3.3 / -6.9 / -5.2 /
  -3.4 / +0.7 (2/5, -11.5) · 1.8→4R +7.8 / -3.8 / -2.5 / -3.9 / +1.9 (2/5, -0.5) · 1.5→4R +11.5 / +1.8 / -4.0 / -2.3 / +0.1
  (3/5, +7.1) · 1.5→5R +14.4 / -2.8 / -6.0 / -2.8 / +4.1 (2/5, +6.9). Artı neredeyse sadece son 6 aydan. 2.2'ye gelen işlemlerin
  yarıdan fazlası 3R'ye gitmeden geri dönüyor (1.8→3R: 40 TP → 18 TP + 22 kilit); kilit çıkışı ort +1.5R (1.8 kilit) / +1.3R
  (1.5 kilit). RED, eski dönem çalıştırılmadı. TP yükseltme yolları (sabit, onay mumuna göre, kâr kilidiyle) bitti → TP 2.2.
- 23:27 kullanıcı "başka yöntem düşün, geçmişi iyice izle". Notların tamamı tarandı; denenmemiş iki yol önerildi:
  (1) İşlem kalitesine göre risk, 7 dönem (5 + eski 2, canlı ayar CSV'leri; scratchpad boyut.py): klasik onay 1. mum 224 iş
  +0.32R/iş · dönüş 137 iş +0.30 · klasik onay 2. mum 98 iş +0.07 (eski 2 dönemde -2.4 / -2.4). 1.5 / 1 / 0.5R → 119.8 →
  151.9R (+32R, 6/7 dönem artı; eski 2 dönem +1.2 / +4.0, fikir 04:38'de 5 dönemden çıkmıştı → sınav geçti), ort. risk ×1.14,
  en büyük düşüş 16.3 → 19.9R (getiri/düşüş 7.35 → 7.63). 1 / 1 / 0.5: 116.3, düşüş 15.5. Kodlanmadı ("yükle" bekliyor).
  (2) Erken çıkıştan sonra yeniden giriş. 23:29 "kodla": simulate → _simulate_core + _reentry (REENTRY_BARS mum içinde
  stopa değmeden giriş seviyesi yeniden geçilirse aynı giriş/stop/TP ile bir kez; aynı mumda giriş+stop → stop; R iki
  bacağın toplamı; REENTRY_EARLY: ikinci bacakta erken çıkış). CSV yeniden_giris, ilk_bacak_R; raporda "🔁 Yeniden giriş".
  COMPARE_SETS["yeniden"]: canlı · 4 mum · 8 mum · 4 mum erken yok · 8 mum erken yok. `/backtest 180 yeniden seri` + eski seri.
- YENİDEN GİRİŞ 5 dönem (16.10 20:38-20:50 UTC; canlı 39.7 / 48.3 / 20.7 / -0.3 / 4.0): fark 4 mum -17.8 / -5.4 / -5.7 /
  +9.0 / -1.8 (1/5, -21.7) · 8 mum -22.9 (1/5) · 4 mum ikincide erken yok -30.9 · 8 mum -32.1. Erken çıkanların ~%85'i 4 mum
  içinde girişi yeniden geçiyor (112 yeniden giriş): 22 TP, 57 stop, ikinci bacak ort -0.20R (erken yoksa -0.28R). Erken
  çıkış sonrası fiyat girişin etrafında dolanıyor; yeniden geçmek devam işareti değil. RED, eski dönem çalıştırılmadı.
  Kullanıcı "1. veya 2. mumda tekrar gelirse": yeniden girişlerin 100/112'si erken çıkıştan hemen sonraki mumda, 9'u 2.
  mumda. Sadece 1. mum: ikinci bacak -14.6R (21 TP / 49 stop, 1/5 artı) · ≤2. mum -22.2R → aynı sonuç, ayrı test gereksiz.
- 23:55 kullanıcı "başka bir şey araştır". 7 dönem canlı ayar (459 iş; scratchpad arastir*.py, momentum.py). DİKKAT: "önceki
  işlem" ölçülerinde işlemin kendisi (giriş mumunda TP / erken çıkış → çıkış = giriş zamanı) sayılmamalı (ilk hesapta bu
  hata sahte sonuç verdi; düzeltildi). Bulgular: aynı coinin önceki işlemi (30 gün) etkisiz (24 iş); temas saati (TR 4'er saat)
  tutarsız (20-24 +0.08R/iş 3/7); girişte açık işlem etkisiz. GÜÇLÜ ADAY: son 24 saatte kapanan (diğer) işlemlerin toplamı
  > 0 → sonraki işlem 73 iş +0.78R/iş TP %52, 7/7 dönem artı; < 0 → 100 iş +0.09 (3/7); yok → 286 iş +0.19. 12 / 36 / 48 saat
  ve aynı yön de aynı yönde (tekdüze). Rejim sürekliliği (sistem altcoin trendlerinde kazanıyor). Eski rejim testleri (son
  5/10/20 işlem, 7/14/30 gün) filtre olarak denenmişti → kısa pencere + boyut olarak yeni. Boyut (42 ay): >0 → 2R toplam
  119.8 → 176.8 (7/7 artı, ort risk 1.16, düşüş 16.3 → 16.5, getiri/düşüş 7.35 → 10.7) · >0 2R / <0 0.5R / yok 1R 172.3
  (7/7, düşüş 14.3, getiri/düşüş 12.0). Kâr P0'da yoğun (+29 / 57). Bu 7 dönemden bulundu → sınav: `/backtest 180 analiz
  4 sene önce` (Nis-Eki 2022) + `5 sene önce` (Nis-Eki 2021); kod gerekmez (3 sene önce önceki6 ile çakışıyor).
- SINAV 2 eski dönem (analiz, canlı ayar): Nis-Eki 2022 42 iş (36 coin) TP 8 -5.2R · Nis-Eki 2021 28 iş (26 coin) TP 5 -4.0R.
  Sistem 2021-2022'de de eksi (2023-2025 başa baş, kâr Eyl 2025'ten beri). Son 24 saat kuralı: ">0" grubunda sadece 1 + 1
  işlem (-1.1 / +2.2) → sınanamadı; "<0" 8 + 1 iş -3.4R (yönü uyumlu). Boyut: >0 2R → 2022 -6.3 (-1.1), 2021 -1.8 (+2.2) ·
  2 / 0.5 / 1 → -4.7 (+0.5), -1.8 (+2.2) → 9 dönemin 9'unda eşit veya daha iyi. Kural kötü rejimde kendiliğinden az devreye
  giriyor (art arda kazanç yok). Kalite boyutu: 2022 +0.1, 2021 -2.8 (k1 -0.36/iş, k2 +0.17) → 9 dönemde 6/9, ZAYIFLADI, önerilmiyor.
- 17.10 00:34 kullanıcı "mantıklı yükle" → CANLI DEĞİŞTİ (otomatik işlem): autotrade.risk_mult(): son MOMENTUM_HOURS (24)
  saatte kapanan otomatik işlemlerin R toplamı (her biri kendi riskine göre, rec["r"]) > 0 → MOMENTUM_UP (2x = 30$), < 0 →
  MOMENTUM_DOWN (0.5x = 7.5$), kapanan yok → 1x (15$). Env ile değişir/kapanır (AUTO_MOMENTUM_UP=1, AUTO_MOMENTUM_DOWN=1).
  2x'te pozisyon sınırı (MAX_NOTIONAL × çarpan) ya da bakiye yetmezse 1x ile girilir (mesajda yazar). rec risk_usd /
  risk_mult; işlem R'si kendi riskine göre, günlük sınır dolar bazında (net / AUTO_RISK_USD). Kapanış mesajında "sıradaki
  işlemin riski", /oto durumunda çarpan, EMİR HAZIR'da aynı risk. Testler: scratchpad ototest/momentum_test.py (+2), lev_test.py.
  Not: 225 USDT bakiyede 2x + dar stop (%0.5, ~6000 USDT, 20x) marjin ~360 → 1x'e düşer.
- 17.10 00:41 /oto: Binance -2015, botun IP'si 74.220.51.152 (15.10'da eklenen 74.220.51.142 idi) → bugünkü yüklemelerden
  birinde Render çıkış IP'si değişti, otomatik işlem o andan beri emir koyamıyor (işlem çıkmadı). Kullanıcıya: /ip'deki
  IP'leri Binance trusted IPs'e ekle, /oto ile kontrol. HATA: _ip_loop ilk kontrolde (yeniden başlatmadan hemen sonra) yeni
  IP'yi sessizce kaydediyordu → uyarı hiç gelmedi. Düzeltildi (daha önce IP kaydı varsa ilk kontrolde de uyar); SADECE
  sonraki dalında, YÜKLENMEDİ (yükleme IP'yi yine değiştirebilir; kullanıcı salıya kadar yazmayacak) → salı yüklenecek.
- 17.10 01:35 kullanıcı: "bu sistem EMA50 ve EMA100 için de geçerli; salı (kota sıfırlanınca) test edelim". YAPILACAK (salı,
  "kodla" beklenecek): aynı kurulum (trend EMA20>50>100, tepe/dip, düzeltme, stoch, temas mumu, onay, giriş/stop/TP 2.2, canlı
  kuralların hepsi) ama temas EMA50'ye / EMA100'e; tepeden sonra o EMA'ya ilk temas. Ayrı varyasyon olarak 5 dönem + eski 2.
  Salı sorulacak: EMA50 temasında fiyat EMA20'nin altına inmiş olacak → trend sıralaması yine şart mı; EMA20 temasıyla aynı
  düzeltmede ikisi de olursa hangisi; dönüş varyasyonu EMA50/100'de de olsun mu.
- 17.10 12:02 kullanıcı EMA50/100 sorularını cevapladı: (1) EMA20>50>100 sırası tepe öncesi/anında şart, temas mumunda aranmaz; (2) EMA20'ye
  değip dönmüşse düzeltme bozulur → ayrı EMA50 sinyali yok, EMA50'ye değene kadar EMA20'deki düzeltme kuralları geçerli;
  (3) klasik + dönüş birlikte. Bu testin kodu "kodla" bekliyor (yorum: normal EMA20 teması = sıçrama = iptal; EMA20'yi kapanışla
  delip geçen mumlar serbest). Önce stop payı testi istendi (EMA20): COMPARE_SETS["pay"] = canlı (pay 0.3) · 0.15 · 0 · 0 + erken
  çıkış yok (FAILED_ENTRY_BARS=0); `/backtest 180 pay seri` + `/backtest 180 pay eski seri` (7 dönem). CHECK_TRADES'e DATAIPUSDT
  17.10 06:30 SHORT (bot erken çıktı, stop onay tepesinde 0.1808 olsa 2R TP). SADECE sonraki dalında, YÜKLENMEDİ.
  Yüklenince: IP uyarısı düzeltmesi de devreye girer, Render çıkış IP'si değişebilir → yükledikten sonra /oto kontrol et,
  /ip'deki yeni IP'yi Binance trusted IPs'e ekle.
- 17.10 12:17 kullanıcı EMA50/100 yorumunu onayladı ("evet") ve "grafikleri de at" dedi. KODLANDI (sadece sonraki dalı, YÜKLENMEDİ):
  strategy.TOUCH_EMA (20 canlı / 50 / 100, "sig" ile), backtest.line_df: tablonun EMA20 sütunu temas çizgisi olur, gerçek EMA20
  EMA20_REAL'de (sığ kopya) → temas mumu, onay, dönüş, kural 5 vb. çizgiye göre çalışır. strategy._variant_ok: (1) EMA20>50>100 sırası
  TEPE/DİP mumunda aranır, (2) tepeden temasa kadar daha sığ EMA'ya değip kendi tarafında kapatan mum (sıçrama) varsa iptal
  (EMA50 temasında EMA20, EMA100 temasında EMA20+EMA50); kapanışla delip geçen mumlar serbest. Kural 2 (trend teyidi) ve bacak
  ölçüleri GERÇEK EMA20'de kalır (trade_rules._real_ema20). Grafikte gerçek EMA20 çizilir. Toplu sinyal sayımı varyasyonun kendi
  temaslarıyla. candidate_bars varyasyonda trend şartı koymaz (strategy kontrol eder).
  Doğrulama: EMA20 modu eski kodla birebir (6 sentetik seri, 191 sinyal + işlem satırları); 40 sentetik seride EMA50 241 / EMA100 17 sinyal,
  bağımsız kural kontrolünde 0 ihlal. COMPARE_SETS["ema"]: canlı · EMA50 · EMA100 · iki "(ek)" satırı (yavaş düzeltme sınırı yok +
  ters mum ≤4; canlı sınırlar derin düzeltmeyi kesebilir diye). Komutlar: `/backtest 180 ema seri` + `/backtest 180 ema eski seri`
  (7 dönem); grafikler için tek dönem `/backtest 180 ema` (EMA50 satırı) ve `/backtest 180 ema yüz` (EMA100 satırı).
- 20.10 10:42 kullanıcı: ilk işlem erken çıkışla zararla kapandı, sıradaki 0.5x riskle (7.5$) girdi, TP oldu ama Telegram "+2R" yazdı.
  Hata değil, gösterim: _finish R'yi işlemin kendi riskine böluyordu (7.5$ → +2.1R), "Bugün toplam" ise 15$'a. Düzeltme: mesajdaki R artık
  1R = RISK_USD (15$) ölçüsünde (+1.06R, +15.9$), 0.5x/2x işlemde "(risk 7.5$ = 0.5x; işlemin kendi riskine göre +2.12R)" notu.
  rec["r"] (kendi riskine göre) değişmedi → momentum kuralı (risk_mult) aynı çalışır. Sahte Binance ile test edildi. SADECE sonraki
  dalında, YÜKLENMEDİ ("yükleme" dedi, 10:45).
- 20.10 10:47 EMA50/100 1. tur sonucu (`/backtest 180 ema`, 21.04-15.10.2026, CSV karsilastirma_20261017_1839): canlı EMA20 108 işlem %37 TP +40.1R ·
  EMA50 61 işlem %9.8 TP -26.2R (7 ayın hepsi ≤0, klasik -14.5 / dönüş -11.7, LONG -9 / SHORT -17) · EMA50 gevşek sınırlarla 73 işlem -26.4R ·
  EMA100 19 işlem 1 TP -10.9R · gevşek 21 işlem -8.9R. MFE ortancası EMA20 1.06R, EMA50 0.74R; 2.2R'ye gidenler %40 / %13 / %16.
  EMA50'de 6 TP çıkma olasılığı (p=%37) ~1/600.000 → şans değil. Brüt (komisyonsuz) da eksi (-20R). Taban kötü.
- 20.10 10:51 kullanıcı: kıyas yapma, amaç EMA50'nin kendi başına EMA20 gibi kârlı olması, başarırsak canlıya; EMA20'nin bütün kuralları geçerli.
  Örnek STOUSDT 27.05.2026 14:00 SHORT dönüş stop -1.11R: "son tepeyi kırmış, trend değişebilir, girilmez". 10:52 "kodla": trade_rules.STRUCTURE_LEVEL
  ("prior" = kural 8, önceki düzeltmenin ucu · "swing" = son tepeden/dipten hemen önceki 3+3 salınım tepesi/dibi kırılmış mı). COMPARE_SETS["ema"]
  yeniden: EMA50 taban · +kural 8 iğne / kapanış · +son salınım iğne / kapanış · EMA100 taban · +kural 8 iğne · +son salınım iğne
  (EMA20 satırı yok). Grafikler: `ema` = EMA50 + son salınım (iğne), `ema yüz` = EMA100 + son salınım (iğne). Kabul ölçütü (kullanıcıya söylendi):
  5 dönemin ≥4'ünde artı, toplam artı, 2 eski dönemde eksiye düşmemek. Sentetik doğrulama: EMA20 modu eski kodla birebir. SADECE sonraki dalında,
  YÜKLENMEDİ. Not: gerçek veriyle STO işleminin kuralla elendiği buradan doğrulanamadı (Binance arşivine erişim yok) → `/incele STOUSDT 27.05.2026 14:00 dönüş` ya da raporda bakılacak.
- 20.10 11:04 EMA50/100 yapı kuralları testi (180 gün, Telegram özeti; kullanıcı durdurdu): taban EMA50 -24.1R (62 iş) · +kural 8 iğne -14.9 (33) ·
  kapanış -21.0 (41) · +son salınım iğne -3.2 (9 iş, 0 TP) · kapanış -4.2 (22) · EMA100 -10.9 (19) · +kural 8 -1.1 (1) · +son salınım 0 işlem.
  Hiçbiri artıya geçmedi, kurallar kötü işlemleri değil işlem sayısını azalttı → EMA50/100 BIRAKILDI.
- 20.10 11:18 stop payı testi (3 dönem CSV: Nis-Eki 25 / Eki 25-Nis 26 / Nis-Eki 26, canlı ayar): pay 0.3 (canlı) +18.2 / +60.5 / +33.4 = +112.1R ·
  0.15 +10.5 / +54.7 / +19.0 = +84.2 · 0 +3.4 / +55.5 / +18.0 = +76.9 · 0 + erken çıkış yok -0.5 / +57.1 / +5.5 = +62.1 (TP 113 ama stop 161 vs 76).
  Canlı 3/3 dönemde en iyi → stop payı 0.3 ve erken çıkış (2 mum) AYNEN KALIR. (5+2 dönemin sadece 3'ü geldi.)
- 20.10 11:20 18 aylık canlı ayar (3 CSV, drop_duplicates): 6.2R/ay (15.4 iş/ay, +0.405R/iş), 5/18 ay ≥10R, 4 negatif, en kötü -3.1 / en iyi +14.0.
  Canlı boyutlandırma (24 saatte kapanan işlemler >0 → 2x, <0 → 0.5x) simülasyonu: 134.3R (7.5R/ay, 7/18 ay ≥10R); 2x / 1x (düşürme yok) 143.3R
  (8.0R/ay); 1.5x/0.5x 118.7R. 10R/ay için ~25 iş/ay (aynı R/iş) ya da R/iş 0.65 gerekir. Kullanıcı: "ayda en az 10R backtest'i yapana kadar denemeliyiz".
  Fikirler: (1) 2./3. temas (işlem sayısı), (2) kırılım-geri test (ayrı sinyal), (3) 1h trend onayı (kalite), (4) boyut 2x/1x.
- 20.10 11:22 "kodla" → (1) 2./3. EMA20 temasına izin: strategy.TOUCH_NTH (1 canlı / 2 / 3, "sig" ile). Önceki temaslarda hiçbir mum EMA20'nin yanlış tarafında
  kapatmaz, önceki temas dönemi sayısı ≤ N-1, temas mumu yeni bir temas dönemi başlatır (önceki mum EMA20'ye değmemiş), ters mum sayımı ve CORR_BARS_MAX
  son önceki temasın yerel tepesinden/dibinden ölçülür (strategy.nth_local_peak). CSV'de temas_no (1 = ilk temas). COMPARE_SETS["ikinci"]: canlı · ≤2 temas · ≤3 temas;
  `/backtest 180 ikinci seri` + `ikinci eski seri`. Kabul: 5 dönemde ≥4 artı, işlem sayısı artar ve toplam R düşmez, eski 2 dönemde eksiye düşmez.
  Doğrulama (sentetik): varsayılan eski kodla birebir; NTH1⊆NTH2⊆NTH3 sinyalleri, bağımsız kural kontrolünde 0 ihlal. SADECE sonraki dalında, YÜKLENMEDİ.
- 20.10 11:37 2./3. EMA20 temas testi (3 dönem CSV, canlı ayar): canlı +17.2 / +60.5 / +33.4 = +111.1R (275 iş) · ≤2 temas +15.6 / +58.8 / +35.6 = +110.0R (298 iş) ·
  ≤3 temas +14.4 / +60.9 / +34.8 = +110.1R. Eklenen 37 işlem (2. temas) +4.6R (+0.125R/iş, canlıda +0.40) → toplam R değişmedi. RED, canlıya alınmadı.
- 20.10 11:41 boyutlandırma simülasyonu (18 ay, 275 iş, 24 saat kuralı; yukarı/aşağı çarpan → toplam R, R/ay, ≥10R ay, maks düşüş): 1/1 111.1, 6.2, 5/18, 10.7R ·
  2/0.5 (canlıydı) 133.3, 7.4, 7/18, 8.9R · 3/0.5 164.4, 9.1, 9/18, 10.0R (getiri/düşüş 16.4 en iyi) · 3/1 173.4, 9.6, 12.4R · 3/1 48 saat 179.1, 14.6R.
  Bakiye 430$ (kullanıcı artırdı, önceden 225$). 11:43 kullanıcı: "3x yapalım, 1R 20 olsun" → CANLI DEĞİŞTİ (yükleme sonrası): AUTO_RISK_USD varsayılanı 20, ALERT_RISK_USD
  (varsayılan AUTO_RISK_USD), trade_rules.RISK_USD 20, AUTO_MOMENTUM_UP varsayılanı 3.0 (aşağı 0.5, pencere 24 saat). Render Environment'ta bu değişkenler tanımlıysa onlar geçer.
  Riskler (430$): normal 20$ (%4.7), 3x 60$ (%14), 0.5x 10$, 2 işlem 3x ikisi stop -120$ (%28), günlük sınır 5R = -100$, testteki en kötü düşüş ~10R = -200$ (%47).
  Backtest raporları artık 1R = 20$.
- 20.10 11:50 "kodla" → (3) 1s / 4s trend onayı testi: trade_rules.HTF_MODE ("" kapalı canlı / "1h" / "1h_w" / "4h" / "4h_w" / "1h4h"), backtest.add_htf (15dk'dan 1s ve 4s mum
  birleştirilir, EMA20/50/100; her 15dk muma o mumun KAPANIŞINDA kapanmış son üst mum eşlenir, ileriye bakma yok; 4s EMA100 için ilk 100 üst mum sinyal vermez, WARMUP_FACTOR 6).
  Tam = EMA20>50>100 (SHORT tersi), hafif = sadece EMA20>EMA50. Sütunlar HTF1 / HTF1W / HTF4 / HTF4W; durum "htf" (CSV: elendi(üst trend)). Sütun yoksa (canlı) filtre yok.
  COMPARE_SETS["ust"]: canlı · 1s · 1s hafif · 4s · 4s hafif · 1s+4s; `/backtest 180 üst seri` + `üst eski seri`. Kabul: 5 dönemde ≥4 artı, toplam R canlıdan yüksek ya da R/iş
  belirgin yüksek, 2 eski dönem eksi değil. Doğrulama (sentetik): HTF kapalı = önceki kodla birebir; kesilmiş veride aynı değerler (ileriye bakma yok); filtre işliyor.
  SADECE sonraki dalında, YÜKLENMEDİ (canlı bot 1s/4s veri çekmiyor; kabul olursa ayrı "kodla" gerekir).
- 20.10 12:14 1s / 4s trend onayı sonucu (`üst seri`, 5 dönem May 24 – Eki 26, canlı ayar): canlı +32.4 / +58.4 / +17.2 / -3.6 / +2.0 = +106.3R (365 iş, 0.29R/iş) ·
  1s +86.3R (296, 0.29) · 1s hafif +107.1R (360, 0.30, canlıyla aynı) · 4s +68.8R (181, 0.38, 3/5 artı) · 4s hafif +76.2R (232, 0.33) · 1s+4s +71.4R (177, 0.40).
  4s işlem başı R'yi artırıyor ama işlemlerin yarısını atıyor, toplam -35R. 1s'in elediği 69 işlem +20R. Son 1 ayın 10 kayıp LONG'unu (-8.3R) 1s hiç elemedi, 4s yarısını.
  RED: 10R/ay hedefine işlem sayısı azaldığı için zarar. Canlıya alınmadı.
- 20.10 12:15 "kodla" → (2) kırılım + geri test (ayrı sinyal, retest.py, sadece backtest): salınım tepesi (iki yanında 5 mumdan uç) → tepeden sonra seviyenin üstünde kapatan
  ilk mum (≤100 mum, EMA20>50>100, kapanış EMA20 üstünde, gövde ≥0.3 ATR) → fiyat seviyeden ≥1 ATR uzaklaşır → ≤24 mum içinde dip seviyenin 0.2 ATR yakınına iner
  (arada seviyenin altında kapanış yok) → onay/giriş/stop/TP/erken çıkış EMA20 sistemiyle aynı (stop = min(geri test dibi, onay dibi) − 0.3 ATR). SHORT tersi.
  EMA20 işlemiyle aynı coinde çakışan geri test girilmez; toplu sinyal + en fazla 2 açık ikisine birlikte. Sabitler strategy.RETEST / RT_* ("sig" ile).
  COMPARE_SETS["kirilim"]: canlı · sadece kırılım · canlı + kırılım · + uzantı ≥2 ATR · + önünde ≥1R yer · + geri test ≤12 mum. `/backtest 180 kırılım seri` + `kırılım eski seri`.
  CSV: varyasyon "kırılım", kirilim (kırılım mumu), seviye. Doğrulama (sentetik): canlı birebir, kesilmiş veride aynı sinyaller (ileriye bakma yok), uçtan uca sahte veriyle çalıştı.
- 20.10 13:01 kırılım + geri test sonucu (`kırılım seri`, 4 dönem geldi Eki 24 – Eki 26): canlı +34.5 / +60.5 / +19.3 / -3.6 = +110.7R (327 iş, 0.34R/iş) ·
  sadece kırılım +66.6R ama 2675 iş, 0.02R/iş (TP %24) · canlı + kırılım +107.3R (2835 iş; kırılım işlemleri 2 açık işlem sınırını doldurup EMA20 işlemlerini 327 → 183'e
  düşürdü, EMA20 kısmı +47.8R) · uzantı ≥2 ATR +93.8R · önünde ≥1R yer +36.5R · geri test ≤12 mum +119.0R (2588 iş, 0.05R/iş, 1 dönemde canlıdan kötü).
  Kırılım SHORT her dönem artı (+16.7 / +14.6 / +43.9 / +12.0, 1497 iş, ~0.06R/iş), LONG -27.7R. İşlem başı R komisyon/kaymaya çok yakın → RED. Canlıya alınmadı.
- 20.10 15:29 kullanıcı "başka bir şey bul". (a) Yoğun rejim ölçüsü (son 24 saatte kapanan BÜTÜN kırılım / bütün canlı kurulumların toplamı,
  kırılım CSV'leri): canlı işlemleri ayırmıyor (kır >0 0.25R/iş, <0 0.35) → mevcut "kendi işlemleri" kuralı en iyisi (>0 0.60R/iş). RED.
  (b) TOPLU SİNYAL FİLTRESİ BUGÜNKÜ KURALLARLA (kırılım seri CSV'lerindeki "Canlı ayar" skip_cluster satırları; R çıkış fiyatından yeniden hesaplandı,
  işlem satırlarında hata ≤0.0005R; scratchpad clus*.py): 5 dönemde 539 kurulum toplu filtreye takılmış, +49.1R. En fazla 2 işlemle yeniden kurulan
  portföy (aynı mumda sıra 30 kez rastgele): filtre kapalı ort. +163…168R (min 152) vs canlı 112.7R, dönemler ~+34 / +76 / +22 / +26 / +7 vs
  +34.5 / +60.5 / +19.3 / -3.6 / +2.0 (4/5 iyi, 1 eşit). 3x/0.5x ile 291.8R vs 184.8R, son 18 ay 11.5 vs 9.7R/ay, ama maks düşüş -20.1 vs -13.6R,
  iş/ay 25.6 vs 12.3. Eklenen 408 işlem +0.12R/iş (TP %27) ve kârın tamamı ~10 büyük günden (en iyi 10 gün hariç -11.7R; gün bootstrap P>0 %95).
  15.10'daki toplu2 testi (o günkü kurallar, Nis-Eki 26) filtre kapalı -11R demişti; bugünkü kurallarla aynı dönem ~0 → değer kurallara/döneme duyarlı.
  ADAY, gerçek testle doğrulanmalı (kod gerekmez, toplu2 seti LIVE_RULES'u kullanıyor): `/backtest 180 toplu seri` + `/backtest 180 toplu eski seri`.
  Kabul olursa canlıda live_setups.CLUSTER_MAX=0; düşüş büyüdüğü için 1R küçültülmeli (430$'da -20R × 20$ = bakiyenin %93'ü).
- 20.10 16:27 TOPLU SERİ (gerçek backtest, 5 dönem May 24 – Eki 26, bugünkü canlı kurallar), sabit risk: canlı (5+) +32.4 / +60.5 / +17.2 / -3.6 / +2.0 = +108.5R (366 iş) ·
  8 coin +116.6R (3/5 iyi) · **10 coin +36.4 / +67.4 / +25.9 / +3.2 / +15.2 = +148.1R (489 iş, 5/5 canlıdan iyi, R/iş 0.30 aynı, TP %34, 1x düşüş 17.1 → 11.9)** ·
  kapalı +157.8R (763 iş, 3/5, R/iş 0.21; CSV yeniden kurulumu ~+165 tahmin etmişti) · kapalı + en fazla 5 +185.1R (4/5, 862 iş).
  3x/0.5x: canlı 171.8R (son 18 ay 8.9R/ay, düşüş 13.6) · 10 coin 222.0R (5/5, son 18 ay 11.1R/ay, 10/18 ay ≥10R, düşüş 15.5, en kötü ay -8.8) · kapalı 289.0 (düşüş 20.6).
  Eşik tekdüze değil (8 < 10) → şans payı var. Karar `/backtest 180 toplu eski seri` (2023-2024) sonucuna; aday: CLUSTER_MAX 10.
- 20.10 17:36 TOPLU ESKİ SERİ (Kas 23-May 24 98 coin / May-Kas 23 48 coin): canlı -0.1 / +3.4 = +3.3R (96 iş, TP %24) · 8 coin +2.5 / +1.0 · 10 coin +4.5 / -3.7 = +0.8R
  (116 iş) · kapalı +3.7 / -9.0 = -5.3R · kapalı + 5 işlem -17.8R. 7 dönem: 10 coin 148.9R vs canlı 111.8R, 6/7 dönem iyi, ama bir eski dönemde eksi (-3.7, canlı +3.4)
  → kabul şartını tam geçmiyor (eski dönem eksi olmasın). Filtre kapalı RED. Karar kullanıcıda.
- 20.10 17:56 kullanıcı: 10 coin işlemlerinin grafikleri (Telegram'daki gibi). CHART_CFG["toplu2"] = 2 (10 coin), CHART_NEW["toplu2"] = 0: grafiklerde sadece
  canlıda olmayan (10 coin sınırının eklediği) işlemler, 15 TP + 15 stop fotoğraf + hepsi PDF. `/backtest 180 toplu` (tek dönem; seride grafik yok). YÜKLENDİ.
- 20.10 18:06 kullanıcı "yükle, 1R'ı 15 yap, 1 ay bakalım, kârlı geçerse yükseltiriz" → CANLI DEĞİŞTİ: live_setups.CLUSTER_MAX 5 → 10 (bildirim + otomatik işlem),
  AUTO_RISK_USD / ALERT_RISK_USD varsayılanı 20 → 15 (3x = 45$, 0.5x = 7.5$, günlük sınır 5R = 75$), trade_rules.RISK_USD 15 (backtest raporları). toplu2 setinin ilk satırı
  artık "Önceki canlı (5+)" (cluster_max=5 sabit); diğer setlerin "canlı" satırları 10 coin. Render Environment'ta AUTO_RISK_USD tanımlıysa o geçer.
  Beklenen (backtest, 1R=15$, 3x/0.5x): son 18 ay ayda ~+167$ (en iyi ~+490$, en kötü ~-133$), ~20 iş/ay, maks düşüş ~-15.5R ≈ -233$. Kasım ortası değerlendirilecek.
- 20.10 21:08 kullanıcı: 1R 15$ kalsın, KASIM ORTASI canlı sonuca göre bakılacak. Plan (önerildi): 1R ≈ bakiyenin %3.5'i (430$ → 15$, 600$ → 20$, 850$ → 30$,
  1.400$ → 50$, 2.900$ → 100$); sadece artı aydan sonra yükselt, bakiye düşerse 1R'yi de düşür, kârın bir kısmını çek. Otomatik % risk kodlanmadı.
  100$ riske geçerken AUTO_MAX_NOTIONAL (4000 × çarpan) dar stoplu işlemleri sınırlar → yükseltilmeli. Backtest 12 ay (10 coin, 3x/0.5x): 15$ +2.448$, düşüş -203$.
- 20.10 21:56 Binance 418 (IP engeli, ~10 dk; bizim kullanım 53-391/2400 → Render'ın paylaşılan çıkış IP'si). 22:17 "kodla": CANLI DEĞİŞTİ: ws_klines.py
  (ek kütüphane yok, ssl+socket ile küçük RFC 6455 istemcisi): wss://fstream.binance.com/market/stream?streams=<coin>@kline_15m (2026-04-23'ten beri kline
  /market yolunda), bağlantı başına 100 coin (500 coin = 5 bağlantı), sadece "x":true (kapanmış) mumlar saklanır (coin başına 64), ping'e pong, kopunca 5 sn
  (art arda kopmada 5 dk'ya kadar) yeniden bağlanma, 23 saatte bir yenileme; yeni coin gelince yeniden abonelik (çıkanlar %30'a kadar abone kalır).
  live_setups.fetch_candles artık sadece KAPANMIŞ mumlar tutar (açık mum zaman damgasıyla atılır): eksik mumlar önce akıştan (istek yok), akışta boşluk varsa
  son 40 mum REST (1 ağırlık), yoksa tam REST. REST engeli sürerken akış sağlıklıysa tarama sadece akışla yapılır (bildirim gider; otomatik işlem emri REST
  ister, engel kalkana kadar "giriş emri konamadı" mesajı gelir). Her taramada rastgele 1 coinin son mumu REST ile karşılaştırılır (/durum: "REST kontrolü N
  uyumlu"). /durum'da "📡 WebSocket" satırı. LIVE_WS=0 (Render env) kapatır. Sahte sunucuyla test: parçalı mesaj, 126 uzunluk, ping/pong, kapanış →
  yeniden bağlanma, abonelik değişimi, 20.000 mesaj 0.05 sn; fetch_candles senaryoları (tam / akış / boşlukta REST / engelde sadece akış).
  Gerçek Binance'e bu ortamdan erişim yok → canlıda ilk saatlerde /durum ile izlenecek.
- 20.10 22:40 stop payı 2 testi (sadece backtest): trade_rules.STOP_AT_TOUCH (stop onay yerine temas mumunun — dönüşte temas..onay — dibinin altında; tepe için tersi).
  COMPARE_SETS["pay2"] (canlı = bugünkü canlı, toplu 10 coin): 0.3 (canlı) · 0.45 · 0.6 · 0.8 ATR · temas dibi + 0.3. `/backtest 180 geniş seri` + `geniş eski seri`.
  Sentetikte temas dibi varyasyonu kurulumların yarısını 1.5 ATR stop sınırına takıyor (beklenen). Canlı birebir aynı (sentetik).
- 20.10 22:58 GENİŞ STOP PAYI sonucu (3 dönem, Nis 25 – Eki 26, canlı = toplu 10 coin): 0.3 (canlı) +38.5 / +66.6 / +25.0 = +130.1R (352 iş, TP %36, 0.37R/iş) ·
  0.45 +121.3R (1/3 iyi) · 0.6 +82.6R · 0.8 +64.7R · temas dibi +43.9R (231 iş, TP %29). En iyi 0.3 ATR (0 → 0.15 → 0.3 artış, sonra düşüş) → RED, değişiklik yok.
- 20.10 23:00 "kodla": HACİM ÖLÇÜLERİ (sadece backtest/CSV, kural yok). Veri artık hacimli: archive.parse_zip 5. sütun (volume), exchanges.get_klines_range
  k[1:6], archive.get_range / load_15m "Volume" sütunu, disk kaydı 6 sütun (CACHE_COLS; 5 sütunlu eski kayıtlar ilk testte BİR KEZ yeniden indirilir → ilk test
  uzun), resample_tf hacmi toplar, Bybit'te hacim NaN. trade_rules.volume_features (bacak başından önceki 96 mumun ortanca hacmine oranla): hac_bacak (s+1..p ort.),
  hac_tepe, hac_duz (p+1..i-1 ort.), hac_duz_max, hac_temas, hac_onay, hac_son20, hac_oran (bacak/düzeltme), hac_duz_ters (düzeltmede düzeltme yönlü mumların hacim
  payı). CSV'ye ve fark analizi listesine eklendi. Canlı birebir (sentetik). Komut: `/backtest 180 analiz seri` (canlı ayar, 5 dönem) → TP/stop karşılaştırması.
- 20.10 23:25 HACİM sonucu (`analiz seri`, canlı ayar 5 dönem May 24 – Eki 26, 495 iş +151.6R): TP / stop / erken çıkış ortancaları neredeyse aynı (hac_oran 1.34 /
  1.25 / 1.38, hac_duz 1.98 / 1.91 / 1.98, hac_onay 1.14 / 1.11 / 1.09). Her ölçünün üçte bir gruplarının HEPSİ artı; eksi grup yok. En büyük fark hac_duz_ters < 0.79
  (0.46 vs 0.23R/iş) ama dönemlerde tutarsız (0.31/0.32 · 0.71/0.43 · 0.45/0.15 · 0.73/-0.19 · 0.06/0.35). bacak/tepe/son20 orta grup en iyi (tekdüze değil → gürültü).
  Sonuç: hacim TP ile stopu ayırmıyor → RED, kural yok. Hacim sütunları CSV'de kalıyor.
- 20.10 23:29 "kodla": ONAY MUMUNU BEKLEMEDEN GİRİŞ testi (sadece backtest): trade_rules.ENTRY_EARLY (1 = klasikte conf = temas mumu: giriş temas tepesi + 1 tık
  stop emri, stop temas dibi - 0.3 ATR, giriş penceresi 2 mum, önce temas dibinin altına inilirse iptal; 2 = dönüşte de conf = dönüş mumu). Erken girişte kural 1
  (onayda ters iğne) uygulanmaz; diğer kurallar (ATR, %0.5, 1R yer, erken çıkış) aynı. ENTRY_WINDOW PARAM_KEYS'e eklendi. COMPARE_SETS["hemen"]: canlı · klasik erken ·
  klasik + dönüş erken · klasik erken + giriş 1 mum. `/backtest 180 hemen seri` + `hemen eski seri`. Canlıya alınırsa canlı tarama değişmeden çalışır (onay = son kapanan
  temas mumu). Sentetik: canlı birebir, giriş = temas tepesi + 1 tık, giriş temastan sonra.
- 20.10 23:56 ONAY BEKLEMEDEN GİRİŞ sonucu (`hemen seri`, 5 dönem May 24 – Eki 26, canlı = toplu 10): canlı +38.6 / +68.6 / +22.8 / +4.3 / +15.2 = +149.5R (494 iş,
  TP %34, 0.30R/iş) · klasik erken +113.7R (1366 iş, TP %26, 0.08R/iş, 1/5 iyi) · klasik + dönüş erken +30.0R (1874 iş, 0.02R/iş, 0/5) · klasik erken giriş 1 mum +79.4R
  (0/5). Onay mumu kapanışı en güçlü filtrelerden biri: kaldırınca işlem ~3 kat, işlem başı R ~1/4. RED, eski seri gereksiz.
  20.10 itibarıyla denenen ve reddedilen: 2./3. temas, 1s/4s trend, kırılım-geri test, toplu filtre kapalı, TP önceki tepe, en fazla 3 işlem, yoğun rejim, geniş stop,
  hacim, erken giriş, LONG/SHORT boyut. Kabul edilen: toplu sınırı 10 coin (canlıda).
- 21.10 00:02 /oto: Binance -1003 "Way too many requests", IP 74.220.51.152 01:30'a kadar (1.5 saat) engelli. Büyük ihtimalle BİZİM backtestlerimiz: hacim için diskteki bütün
  kayıtlar geçersiz sayıldı, analiz seri + hemen seri her coinin arşivden önceki (listelenmeden önceki) kısmını API'ye sordu (önceden kayıt aralığı bunu önlüyordu).
  Düzeltme (sonraki dalında, ENGEL BİTİNCE yüklenecek: engel sürerken yeniden başlatma canlı mum kaydını siler, REST'siz yeniden kurulamaz): archive.get_range ilk arşiv
  dosyasından önceki boşluğu API'ye hiç sormaz (skipped_lead). Engel sırasında canlı tarama WebSocket ile sürüyor (ws_only), otomatik emir konamaz.
- 21.10 00:21 "kodla": erken çıkış yeniden (RONIN 25.04 / SEI 09.05 erken çıkıp mfe ~5R): 10 coin CSV'de 224 erken çıkış -52.4R, %26'sı stopa değmeden 2.2R'ye gidiyor,
  kural olmasa tahmini -60.8R (fayda +8R; 14.10'da çok daha büyüktü). COMPARE_SETS["cikis"]: canlı · erken çıkış yok · 1 mum · derin eşik 0.2 · 0.5 ATR.
  `/backtest 180 çıkış seri` + `çıkış eski seri`. Binance engeli (01:30) bitince arşiv düzeltmesiyle birlikte yüklenecek.
- 21.10 02:06 ERKEN ÇIKIŞ YENİDEN sonucu (`çıkış seri`, 5 dönem, canlı = toplu 10): canlı +37.4 / +68.6 / +25.0 / +4.3 / +15.3 = +150.6R (495 iş, 1x düşüş 12.0, 3x 231.6R
  düşüş 15.5) · erken çıkış yok +139.9R (3/5 iyi ama düşüş 18.0 / 3x 26.2, stop 150 → 277) · 1 mum +146.6R · derin eşik 0.2 +132.9 · 0.5 +136.4. Canlı en iyi toplam ve
  en iyi kazanç/düşüş → DEĞİŞİKLİK YOK. Erken çıkış kârı az artırıyor ama düşüşü belirgin azaltıyor (bugün kuralın asıl değeri bu).
- 21.10 02:37 ikinci uzun engel (03:54'e kadar, ~02:29'da başladı; bizim backtest 02:05'te bitmişti, bot neredeyse istek atmıyordu → paylaşılan IP). Render sabit IP
  Pro plan + 100$/ay. 02:40 kullanıcı: "sürekli 2. yöntemi kullanalım" (kendi sanal sunucu, ~4-6$/ay). Hazırlandı (sonraki dalında): deploy/ (kurulum.sh,
  sapan-bot.service, guncelle.sh + 2 dk'lık timer = main'e gönderince otomatik güncelleme, ornek.env, KURULUM.md). config.GIT_COMMIT Render dışında .git'ten.
  Geçişte Render SUSPEND edilmeli (iki bot aynı anda olmasın), açık işlem yokken. Render diskindeki geçmiş taşınmaz.
- 21.10 15:03 kullanıcı SUPERUSDT (0.5x, 7.5$) işlemine Binance'ten elle EKLEME yaptı (risk ~20$). Sorun: bot stop/TP'yi sabit miktarla (girişteki adet) koyuyordu →
  eklenen kısım stopsuz/TP'siz kalıyordu. "Kodla, güzel bulduklarıma ekleme yapıp R'ı artırabilirim": autotrade._resize: her 5 sn'lik kontrolde pozisyon miktarı kayıttan
  farklıysa yeni stop (bütün miktar, aynı fiyat) konur, sonra eskisi silinir; TP silinip bütün miktarla yeniden konur; rec fill = ortalama giriş, risk_usd = miktar ×
  |ortalama - stop| (R ve 3x/0.5x kuralı gerçek riske göre). Telegram "🔁 ... bütün pozisyona taşındı, risk ~X$". Stop konamazsa eski stop kalır, uyarı (1. ve 5. denemede).
  Sahte Binance testi geçti. Ayrıca açılış mesajı düzeltmesi (kural özeti HTML kaçırma).
- 21.10 17:55 "kodla": ARIA benzeri işlemlerin grafikleri. 7 dönem 10 coin CSV: sivri tepe ≥ 4 ATR + düzeltme iğne oranı ≥ %50 → 64 iş +8.3R (0.13R/iş, TP %28, stop %36;
  dönemler -2.3 / +10.5 / -0.1 / -3.1 / +3.9 / 0 / -0.6) → kural olarak elemek toplamı düşürür. backtest.CHART_FILTER (karşılaştırma setine göre grafik süzgeci),
  COMPARE_SETS["aria"] (sadece canlı), `/backtest 180 aria` → grafikler sadece bu işlemlerden (15 TP + 15 stop + PDF). Kullanıcı grafiklerden ortak özellik arayacak.
  Ayrıca 21.10: SUPER elle ekleme → _resize canlıda çalıştı (risk 19.29$, +37.01$, kendi riskine göre +1.92R).
- 21.10 22:48 "kodla" (PONSUSDT 21.10 19:45 3x stop -47$: fiyat 0.2978'e çıkıp iğneyle stopu aldı; SUPER gibi yakın stop/TP ile TP olacaktı, ikisinde de onay mumu büyük):
  trade_rules.STOP_MID_CONF_ATR (onay mumu tepe-dip ≥ X ATR ise stop onay ortasında ∓ 1 tık, pay yok; TP 2.2 × yeni risk). COMPARE_SETS["orta"]: canlı · ≥1 · ≥0.7 · ≥1.3 ATR ·
  stop en fazla 1 ATR. `/backtest 180 orta seri` + `orta eski seri`. Not: risk küçülünce "stop ≥ %0.5" kuralı bazı işlemleri eleyebilir. Canlı birebir (sentetik).
- 21.10 23:17 ORTA sonucu (`orta seri`, 5 dönem): canlı +37.8 / +69.3 / +26.7 / +3.0 / +15.3 = +152.1R (498 iş, 1x düşüş 10.7) · ≥1 ATR ortada +123.8 (1/5) · ≥0.7 +44.1 (0/5) ·
  ≥1.3 +57.9 / +69.0 / +24.8 / -7.4 / +15.1 = +159.4R (565 iş, sadece 1. dönem iyi, 4 dönem eşit/kötü, düşüş 14.9) · stop ≤ 1 ATR +89.9. RED: fark tek dönemden (SUPER/PONS
  döneminin ayları). Büyük onay mumlu işlemlerde yakın stop TP oranını artırmıyor; iğneyle stop olanlar artıyor. Canlı değişmedi.
- 22.10 01:41 YENİDEN GİRİŞ bugünkü kurallarla (`yeniden seri`, 2 dönem; kullanıcı kalanı iptal etti): canlı +37.8 / +67.2 · 4 mum +22.8 / +61.3 (TP +5/+8, stop +21/+18)
  · 8 mum +21.4 / +61.3 · ikincide erken çıkış yok +18.5 / +63.6. 16.10 ile aynı sonuç → RED. (Yeniden girişlerin ~%90'ı 1. mumda, ayrı 1 mum testi gereksiz.)
- 22.10 01:43 kullanıcı: "bugün kazanabileceğimiz yerde çok kaybettim, atladığımız bir şey var mı". 21.10 günü: ARIA -15.45 · SUPER +37.01 (elle ekleme) · PONS 3x + ekleme ~-70
  (+1.6R gördü, iğne 0.2867 stopu 0.2875 aldı, fiyat geri döndü) · EUL 1x + ekleme ~-15 → bakiye 427 → 363. Sistem tek başına (eklemesiz) ≈ -55$.
  CSV (10 coin, 7 dönem, 605 iş): stop olanların %32'si önce ≥1R (-66.9R), %14'ü ≥1.5R (-28.6R) görmüş · aynı yönde açık işlem varken açılanlar 49 iş +9.2R (sınır gereksiz) ·
  günün aynı yöndeki 2. işlemi 0.18R/iş (artı). HAZIRLANDI (sonraki dalında, yüklenmedi, "kodla/yükle" bekliyor): trade_rules.CLOSE_STOP_HARD_R (kapanışta stop: mum içi sadece
  girişten X R gerideki sert stop, stop seviyesinin ötesinde kapanışta çık), COMPARE_SETS["igne2"]: canlı · kapanışta stop sert 1.5R / 2R · 1.5R'de stop +0.5R · 1R'de stop -0.5R.
  `/backtest 180 fitil seri`. Sentetik: canlı birebir, kapanış/sert stop doğru.
- 22.10 02:25 FİTİL sonucu (`fitil seri`, 5 dönem; canlı +37.8 / +68.3 / +26.7 / +3.0 / +15.3 = +151.1R): kapanışta stop sert 1.5R +147.7 (3/5 daha iyi,
  −3.4R) · sert 2R +142.6 (2/5) · 1.5R'de stop +0.5R +119.8 (0/5) · 1R'de stop −0.5R +131.1 (0/5). Kapanış stopu 12 stopu TP'ye çevirdi (+38.7R) ama
  120 stop kapanışa kadar daha derin kapandı (−42R; 128 işlem 1.1R'den büyük zarar). REDDEDİLDİ (≥4/5 yok); BE/kilitleme yine zararlı. Eski seri gerek yok.
- 22.10 03:17 KENDİ SUNUCUYA TAŞINDI: Hetzner Cloud Helsinki, CPX02 (x86, ~930MB RAM + 2GB swap, 20GB disk, 6.49 €/ay, 25 € ön ödeme),
  Ubuntu 24.04, IP 95.216.214.13 (Binance trusted IP'ye eklendi). /etc/sapan-bot.env MEMORY_LIMIT_MB=700. Render worker SUSPEND.
  Güncelleme: guncelle.sh timer'ı 2 dk'da bir main'e bakar ("yükle" = main'e push, aynen). İlk açılış: oto kapalı geldi → /oto aç; bakiye 300.25;
  momentum geçmişi sıfırdan (1x). Bağlantı: kullanıcı telefonda Termius (root).
- 22.10 03:23 "kodla" (CSV analizi: dönüş R/iş 7 dönemin 6'sında klasikten iyi; onay gövdesi / SHORT / risk ATR eski dönemlerde tutmadı):
  trade_rules.RR_RECLAIM (dönüşte hedef) + LIMIT_ENTRY_FRAC / LIMIT_KEEP_TP / LIMIT_WINDOW / LIMIT_EARLY (_limit_entry: kurulum kuralları asıl
  girişe göre; limit = onay ucu − oran·mum boyu; dolum mumunda stop varsa stop, TP sayılmaz; dolmadan TP fiyatı → "ran"; giriş maker komisyon).
  COMPARE_SETS["limit"]: canlı · dönüş TP 3 · limit orta TP aynı · +4 mum bekle · TP 2.2×yeni risk · üst 1/3 · orta erken çıkışsız.
  `/backtest 180 limit seri` + `limit eski seri`. Sentetik: varsayılanlarla 1127 kurulumda birebir aynı.
- 22.10 03:40 LİMİT sonucu (`limit seri`, ilk 3 dönem Nis 26-Eki 26 / Eki 25-Nis 26 / May 25-Eki 25; yeni sunucuda 3 dönem ~3 dk): canlı +35.6 / +67.2 / +25.7 ·
  dönüşte TP 3 +36.4 / +58.5 / +24.9 (1/3, −8.7R) · limit orta TP aynı −27.9 / +23.4 / −24.6 · +4 mum −24.0 / +31.4 / −27.4 · TP 2.2×yeni −36.6 / +0.8 / −12.6 ·
  üst 1/3 −38.9 / +24.2 / −26.5 · orta erken çıkışsız −26.8 / +27.0 / −15.9. HEPSİ REDDEDİLDİ (her dönemde canlıdan kötü). Geri gelip onay ortasına dolan
  işlemler zayıf (TP %12-20): onaydan sonra hemen kırılım yapan işlemler iyi → stop emriyle giriş doğru. Dönüşte büyük hedef de yok. Eski seri gereksiz.
- 22.10 03:39 "kodla": trade_rules.CANCEL_MID_FRAC / CANCEL_MID_SAME (giriş stop emri tetiklenmeden fiyat onay ucundan oran·mum boyu geri gelirse
  "cancel_mid"; aynı mumda hem geri gelme hem giriş: SAME=False giriş, True iptal). COMPARE_SETS["geri"]: canlı · orta · orta aynı mumda iptal · üst 1/3 · 3/4.
  `/backtest 180 geri seri` + `geri eski seri`. Sentetik: varsayılanla 1127 kurulumda birebir.
- 22.10 03:50 GERİ sonucu (`geri seri`, 4 dönem geldi; canlı +35.6 / +67.2 / +25.7 / +3.0): orta iptal +29.6 / +59.3 / +19.7 / −4.4 (0/4) · üst 1/3 aynı (0/4) ·
  3/4 +30.4 / +61.4 / +26.0 / −1.3 (1/4) · orta + aynı mumda iptal +30.9 / +59.7 / +20.6 / +7.4 (1/4; R/iş 0.39/0.71/0.37/0.17 vs 0.29/0.50/0.26/0.04, düşüş
  hep küçük) AMA ileriye bakıyor (15m mumda önce giriş sonra ortaya düşüşü de siler; canlıda dolmuş emir iptal edilemez). REDDEDİLDİ. İleride: aynı mum sırası
  1 dk mumlarla çözülürse 3. satırın gerçek değeri ölçülebilir (düşük öncelik, toplam yine canlının altında).
- 22.10 03:49 "kodla" (kullanıcı: "işlem sayısını arttırıp TP oranını aynı tutsak iyi kazanırım"): çoklu zaman dilimi testi. Ayarlarda tfs listesi
  (listesi olan sette her ayar kendi dilimlerinde; veri bir kez çekilir, 30dk/1s 15dk'dan üretilir, WARMUP_FACTOR en büyük dilime göre). apply_portfolio:
  toplu sinyal anahtarı (dilim, mum, yön) — her dilimde ayrı; one_per_coin (birden çok dilimde coinde tek işlem, tek yön modu); MAX_OPEN dilimler arası ortak.
  COMPARE_SETS["coklu"]: canlı 15dk · sadece 30dk · 15+30 (2) · 15+30 (3) · 15+1s (2) · 15+30+1s (3). `/backtest 180 çoklu seri` + `çoklu eski seri`.
  Sentetik: tek dilimde sonuç aynı (igne2 mock), 15+30 işlemleri = 15dk + 30dk toplamı. Not: 30/1s'te mum sayılı kurallar (WICKY 12, CORR 10) süre olarak 2x/4x.
- 22.10 04:05 ÇOKLU sonucu (`çoklu seri`, 5 dönem May 24 – Eki 26; R / işlem / TP% / en büyük düşüş R / canlıdan iyi):
  canlı 15dk +37.8 / +67.2 / +25.7 / +3.0 / +13.2 = +146.8 (497, %33, 10.7) · sadece 30dk +5.7 / +1.5 / −2.2 / +13.3 / +10.1 = +28.3 (263, %24, 12.1) ·
  15+30 (2) +41.3 / +68.6 / +18.1 / +16.2 / +23.3 = +167.6 (755, %30, 15.0, 4/5) · **15+30 (3) +43.5 / +69.2 / +22.4 / +15.2 / +23.1 = +173.3 (767, %30, 14.9, 4/5)** ·
  15+1s (2) +154.7 (612, 2/5) · 15+30+1s (3) +183.7 (891, %29, 16.4, 4/5; 1s tek başına 2/5 artı, küçük örnek → güvenilmez).
  30dk eski dönemlerde (2024) 15dk zayıfken artı → çeşitlendirme. Bedeli: R/iş 0.30 → 0.23, düşüş 10.7 → 14.9R. Aday: 15+30 (3). Karar `çoklu eski seri`.
- 22.10 04:10 ÇOKLU ESKİ (Kas 23-May 24, 121 coin / May 23-Kas 23, 81 coin): canlı +4.6 / −5.8 · sadece 30dk −1.5 / −13.4 · 15+30 (3) +2.5 / −19.2
  (düşüş 17.1 / 21.3 vs 14.4 / 12.2) · 15+1s +4.7 / −5.5 · 15+30+1s +2.6 / −18.9. 7 dönem: 15+30 (3) +156.6 vs canlı +145.6 (+11R / 42 ay, 4/7 iyi),
  eski dönemlerde 0/2 ve 2023'te −13.4R ek zarar. KURALA GÖRE REDDEDİLDİ (eski dönemler kötü). 30dk 2024-26'da artı, 2023 ayı piyasasında zararlı.
  1s: 7 dönemde küçük ve tutarsız. Kullanıcıya: canlıya alınmadı; istenirse 30dk sadece bildirim (oto işlem yok) olarak izlenebilir.
- 22.10 04:11 "kodla" → CANLI EKLENDİ: live_alt.py = 30dk SADECE BİLDİRİM (aynı LIVE_RULES, otomatik işlem YOK). Kendi önbelleği + ayrı WebSocket
  (kline_30m, 5 bağlantı daha), REST yedek aynı (40 mum / tam 499). bot.setup_loop'ta 15dk taramasından sonra; her 30dk kapanışından sonra 10-600 sn
  penceresinde bir kez. Mesaj "🔔 30dk BİLDİRİM": giriş/stop/TP, 1R ve 0.5R pozisyon, grafik, Girdim/Girmedim, coinde 15dk setup'ı / oto işlem varsa uyarı;
  takip: giriş / ERKEN ÇIK / TP / stop / iptal ("🔔 … (30dk, temas …)"). Toplu sinyal (≥10) 30dk'da ayrı; MAX_OPEN uygulanmaz (karar kullanıcının).
  Günlük: anahtar "COIN|ts|30m", kayıtta tf; /durum'da "30dk bütün bildirimler / senin girdiklerin" ayrı satır. /otuz aç|kapat (env ALT_ALERTS=0 kapatır).
  Yeniden başlayınca son 30 mumdaki (15 saat) bildirilmiş setup'lar takibe geri alınır. Sahte veriyle test (25 coin, 600 tarama): 7 bildirim, takip mesajları doğru.
- 22.10 04:21 kullanıcı: "15 Kasım'a kadar bakalım, total sonuçlar ne olacak; bakiye 300$". Plan: canlı 15dk oto (1R 15$, momentum 3x/0.5x) + 30dk sadece
  bildirim (elle, sadece 1R / 0.5R, 3x'e ekleme yok). 15.11'de: oto sonuç (/oto son 30 gün), günlük (15dk / 30dk / girdiklerin), ban gelip gelmediği, 1R kararı.
- 22.10 04:33 "kodla": bildirimlerde (15dk EMİR HAZIR + 30dk) pozisyon satırı: "N adet = X USDT → Lx, marjin Y$" (autotrade.size_plan: adet Binance adımına
  aşağı yuvarlı, kaldıraç oto işlemdeki _pick_leverage kuralı: likidasyon stopun 1.5 katı ötede, coinin bracket sınırı). 30dk'da 1R ve 0.5R ayrı satır +
  "önce kaldıracı ayarla (izole), adedi gir, STOP emri, sonra stop/TP". Bracket alınamazsa en fazla 20x.
- 22.10 18:18 "kodla": /temas = son 15dk ve 30dk taramasındaki EMA20 temasları (coin, yön, temas saati, klasik/dönüş) ve durumu: bildirim gönderildi /
  toplu sinyal / onay bekleniyor / onay geldi giriş bekleniyor / "elendi: <sebep>" (reasons.py = backtest.STATUS_TR kopyası). scan_symbol her temasın
  simulate durumunu _touch_log'a yazar (sadece son CONFIRM_WINDOW+1 mum), run_cycle sonunda _stats["touch_list"]. En fazla 40 satır.
- 23.10 02:12 "kodla" (BANKUSDT 19.09 01:15 grafiği: dümdüz çıkıştan sonraki ilk temas kural 2'ye takıldı, sonraki teyitli temas erken çıkış): trade_rules.PRIOR_TOUCH_SKIP
  ("reclaim" / "classic" / "both": kural 2 o varyasyonda uygulanmaz, res no_teyit). COMPARE_SETS["teyit2"]: canlı · dönüşte yok · klasikte yok · hiç yok.
  `/backtest 180 ilk seri` + `ilk eski seri` ("teyit" kelimesi eski teyit setinde). Sentetik: varsayılanla birebir; dönüş + klasik eklenenler = hiç yok.
  Eski bilgi: kural 2'yi kaldırmak 18 ayda +321 işlem −16.2R (artır testi), gevşet −11.4 / +17.4.
- 23.10 02:25 İLK (teyitsiz ilk temas) sonucu (`ilk seri`, 5 dönem May 24 – Eki 26): canlı +40.0 / +72.8 / +20.2 / +4.1 / +13.2 = +150.3 (490 iş) ·
  kural 2 dönüşte yok +125.2 (671 iş, eklenen 183 iş −21R, 2/5) · klasikte yok +103.3 (868 iş, eklenen 385 iş, TP %20, −44R, 2/5) · hiç yok +73.0 (1045 iş, 1/5).
  Teyitsiz ilk temasların TP oranı %8-27 (canlı ~%33). REDDEDİLDİ, kural 2 kalır (önceki artır testiyle aynı sonuç). Eski seri gereksiz.
- 23.10 02:32 kullanıcı: "TP oranı %33 çok düşük, %40-45'e çıkarmalıyız". CSV analizi (7 dönem, 605 iş; scratchpad/tp): TP %32 / stop %31 / erken %37
  (TP/(TP+stop) %50). Erken çıkışsız (mfe ile) TP %41.5, R +145 vs +149, düşüş 14.4 → 19.1R, art arda stop 5 → 14. TP 1.5: %36 / +82R. 45 ölçü / 686 tekli +
  ikili filtre: aynı veride ikili %41-42 TP ama dönem-dışı sınavda (LOPO) TP %35.6, R 149 → 71 (ezber). Tutarlı tek bulgu: trend_yasi (EMA20>50>100 sırası
  kaç mum): <76 mum TP %23-29 R/iş ~0.05 (3 dönemde eksi) · ≥76 %34-42, 0.31-0.53 (6/7 dönem iyi; tekdüze artış). ≥76 + erken çıkışsız TP %48 +138R (aynı veri).
  DİKKAT: ilk denemede 24 saat / coin geçmişi hesabında işlemin kendisi de sayılmıştı (c_t <= g_t, giriş mumunda erken çıkış) → yanlış %42; düzeltildi (c_t < g_t).
- 23.10 02:41 "kodla": trade_rules.TREND_AGE_MIN + trend_age() (status young_trend; reasons'ta Türkçe). COMPARE_SETS["yas"]: canlı · ≥60 · ≥76 · ≥100 ·
  ≥76 + erken çıkışsız · erken çıkışsız. `/backtest 180 yaş seri` + `/backtest 180 yaş seri 3 sene önce` (ago 1095: 2021-2023, hiç bakılmamış). Sentetik birebir.
- 23.10 02:55 YAŞ sonucu (`yaş seri`, 5 dönem; R / işlem / TP% / en büyük düşüş / R÷düşüş): canlı +148.1 / 489 / %33.7 / 10.7 / 13.8 · ≥60 +131.0 / 323 / %37.2 / 7.4 / 17.7
  (3/5 iyi) · ≥76 +105.6 / 245 / %37.1 / 7.7 / 13.7 · ≥100 +89.0 / 172 / %39.5 / 6.0 / 14.8 · ≥76 + erken çıkışsız +107.0 / 244 / %47.5 / 8.9 · erken çıkışsız
  +135.8 / 483 / %42.7 / 15.0. Gerçek backtest CSV tahminiyle birebir (aynı işlemler). TP% ve R/iş artıyor ama toplam düşüyor; ≥60 kazanç/düşüş oranında en iyi
  (aynı düşüşe göre risk ~1.4x → ~+%25). Sınav: `yaş seri 3 sene önce` (2021-2023) bekleniyor.
- 23.10 03:05 YAŞ 3 SENE ÖNCE (hiç bakılmamış 5 dönem May 21 – Eki 23, 37-53 coin): canlı −7.6 / −2.8 / −16.3 / +1.8 / +0.2 = −24.8R (193 iş, TP %18) ·
  ≥60 −11.3 (4/5 iyi) · ≥76 −5.3 (4/5) · ≥100 −5.7 (5/5) · ≥76 + erken çıkışsız −17.3 (2/5) · erken çıkışsız −55.1 (1/5, düşüş 26R). Sistem 2021-23'te eksi.
  10 dönem toplam: canlı +123.3 · ≥60 +119.7 (7/10 iyi, işlem −%34) · ≥76 +100.3 (5/10) · ≥100 +83.3. Boyut (CSV): ≥60 genç 0.5x yaşlı 1.25x +151.7 ama düşüş 16.7 → 20.4
  (kâr/düşüş aynı). SONUÇ: yaş filtresi zararı azaltıyor, TP%/R-iş artıyor, toplam kâr ~aynı, işlem az. ERKEN ÇIKIŞI KALDIRMAK REDDEDİLDİ (dönem dışında çok kötü).
  TP %40-45 hedefi kalıcı şekilde tutmuyor (sadece erken çıkışsızla, o da dönem dışında bozuk). Kullanıcıya seçenek: ≥60 (aynı kâr, az işlem, %37 TP) ya da canlı.
- 23.10 03:09 kullanıcı: "işlem sayısı düşecek ama kâr sabit kalacak, anlamı yok; TP'yi boşver, işlem sayısını artır, ayda en az 10R". Hesap: 10R = ~33 iş/ay × 0.3R
  (şu an ~16). Momentum (10 dönem CSV): 2024-26 ayda 7.6R (sabit 4.9), 2021-23 −0.3R (sabit −0.8). Komisyon ort 0.09R/iş (682 işte 61R).
- 23.10 03:14 "kodla": KAYDIRILMIŞ 15dk MUMLAR. config.tf_offset ("15m+5" = :05/:20/:35/:50 başlangıçlı), backtest.resample_tf(offset_min), set'te "+"lı dilim
  varsa veri 5dk (set_base_tf("5m"), bütün 15dk dizileri 5dk'dan). COMPARE_SETS["kayik"]: normal · +5 · +10 · üçü (2 işlem) · üçü (4 işlem); coinde tek işlem.
  `/backtest 180 kayık seri` (+ `kayık seri 3 sene önce`). Amaç: (1) işlem sayısı, (2) kurallar standart mum saatine ezber mi sınaması.
- 23.10 03:35 KAYIK sonucu (`kayık seri`, 5 dönem, veri 5dk): normal 15dk +37.9 / +74.9 / +22.3 / +4.1 / +13.0 = +152.1 (492 iş, %33.9, 0.31R/iş) ·
  +5 dk kaydırılmış −3.1 (555 iş, %24, −0.01R/iş, düşüş 28.8) · +10 dk +9.3 (561 iş, %23.5, 0.02R/iş) · üçü (2 işlem) +124.5 · üçü (4 işlem) +139.1. REDDEDİLDİ.
  ÖNEMLİ UYARI: aynı kurallar aynı piyasada sadece mum saati kayınca avantaj ~0. İki açıklama: (a) standart 15dk kapanışları gerçekten önemli (kalabalık bu
  mumlara bakıyor), (b) kurallar 30+ test boyunca standart mumlarda seçildiği için backtest avantajı şişmiş (ezber). 2021-23'ün eksi olması (b)'yi destekliyor →
  canlı beklenti backtestin altında tutulmalı (ör. 0.1-0.15R/iş). Ayırt etmek için: 14.10 temel kurallarla (filtresiz) normal / kaydırılmış karşılaştırması.
- 23.10 03:35 "kodla": MEXC TESTİ. mexc.py (bybit.py arayüzü: contract v1 /detail, /ticker amount24, /kline/{sym} saniye, 2000 mum/istek, 7 istek/sn; USDT perpetual,
  state 0, hisse ve gizli kontratlar hariç; apiAllowed sayılır). backtest: ALT_EX {bybit, mexc}, komisyon MEXC API taker %0.08 / maker %0.06. COMPARE_SETS["borsa"]
  (_YENI: bütün / Binance'te de olan / sadece yeni). `/backtest 180 mexc` (+ "mexc seri"; commands'ta mexc + seri düzeltildi, bybit seri de çalışır).
  Düzeltme: Bybit/MEXC testinde Binance coin listesi live_setups yerel import hatası yüzünden hep son kayıttan geliyordu (UnboundLocalError) → _ls.
  Sahte veriyle test: ortak / yeni ayrımı ve binance_da doğru. Gerçek MEXC erişimi sunucudan denenmedi (bu ortamdan ulaşılamıyor).
- 23.10 04:00 MEXC sonucu (Nis-Eki 26, 601 USDT perp; 479 Binance'te de var, 122 yeni; komisyon %0.08/%0.06): bütün −9.0R (187 iş, %25) · Binance coinleri MEXC
  mumlarıyla −15.7R (170 iş, %24, düşüş 23.6; aynı dönem Binance verisiyle +37.9R / 122 iş!) · yeni coinler +4.3R (19 iş, %32, 0.23R/iş; ~3 iş/ay, küçük örnek;
  isim eşleşmeyen birkaç Binance coini de içinde: FILECOIN, ASTR, ETHW). SONUÇ: MEXC eklenmez (az işlem). ASIL BULGU: aynı coinler başka borsanın mumlarında
  avantajsız (Bybit 16.10'da da zayıftı). Kaydırılmış mumlar (~0), Bybit/MEXC verisi (≤0), 2021-23 (eksi) → backtestteki +0.3R/iş büyük ölçüde Binance
  standart 15dk mumlarına ezber. Canlı beklenti düşük (~0-0.1R/iş). Öneri: sağlamlık süzgeci (her kural kaydırılmış mum + MEXC + 2021-23'te de işe yarıyor mu),
  risk düşürme / 3x momentumu kısma, 15.11 canlı sonucu belirleyici.
- 23.10 04:01 "kodla": SAĞLAMLIK SÜZGECİ. COMPARE_SETS["saglam"] = canlı + 11 kural tek tek kaldırılmış (kural 1/2/4/5/6, 1R yer, iğneli, taban, sert sallanma,
  yavaş düzeltme, onay 3 mum) + TEMEL (hepsi kalkmış). "saglam_k" = aynısı +5/+10 dk kaydırılmış mumlarda (en fazla 4 işlem). 4 görünüm:
  `sağlam seri` (Binance) · `sağlam seri 3 sene önce` (2021-23) · `sağlam kayık seri` (5dk veri) · `sağlam mexc seri` (Binance coinleri MEXC mumlarıyla).
  Karar: kuralın elediği işlemler (− kural satırı eksi canlı) çoğu görünümde eksiyse kural kalır, yoksa çıkar.
- 23.10 11:40 SAĞLAM sonucu (3 görünüm; kural kaldırınca canlıya göre R farkı, eklenen işlem): canlı Binance +151.2 (489) · 2021-23 −20.5 (195) · kayık +5.4 (1083).
  kural 1 −19.0 / −2.2 / +14.6 · kural 2 −72.2 / −14.3 / −3.5 (KALIR) · kural 4 −3.0 / +0.9 / +5.0 (etkisiz, +28 iş) · kural 5 −5.9 / −9.9 / +3.9 · kural 6 +21.9 (+159 iş,
  4/5) / −7.8 / −13.3 · 1R yer −1.0 (+200 iş) / −14.5 / +25.4 · iğneli −10.6 / −1.8 / +4.9 · taban −3.3 / −2.8 / −23.8 (KALIR) · sert sallanma −8.7 / −4.3 / −3.8 (KALIR) ·
  yavaş −6.6 / +0.5 / 0 · onay 3 mum +2.9 / −4.1 / −6.1 (kalır) · TEMEL −335.6 / −162.5 / −174.0. Kurallar topluca gerçek (temel her yerde çok eksi), ama kalan
  avantaj sadece Binance 2024-26'da artı. Gevşetme adayları (işlem artırır, kârı az etkiler): kural 4, 1R yer, kural 6. MEXC görünümü bekleniyor.
