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

- 13.10 21:5x: kullanıcı isteği: canlı EMİR HAZIR taraması 5 dakikalık grafikte (config.LIVE_TF, Render'da LIVE_TF ile değişir).
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
- `/backtest 30 canlı 5m` – sona 5m yazılırsa test 5 dakikalık grafikte (veri ayrı önbellekte)

## Dosyalar
- `archive.py` backtest verisi (Binance dosya arşivi) · `memwatch.py` bellek bekçisi
- `strategy.py` temas kuralları · `trade_rules.py` onay/giriş/çıkış + 1-6 kurallar
- `live_setups.py` canlı EMİR HAZIR · `backtest.py` testler ve karşılaştırma setleri
- `exchanges.py` Binance · `telegram.py` · `charts.py` · `commands.py` · `bot.py` ana döngü
