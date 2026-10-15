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
