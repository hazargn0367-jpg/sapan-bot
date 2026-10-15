"""
İŞLEM KURALLARI (temas uyarısından sonrası)

LONG (SHORT tam tersi):
 1. Temas mumu: strategy.py'deki tüm şartlar + EMA20'nin ÜSTÜNDE kapanış
 2. Onay: Sonraki 3 mum içinde, temas mumunun tepesinin üstünde kapatan ilk mum.
    O ana kadar (onay mumu dahil) hiçbir mum temas mumunun dibinin altına inmez.
 3. Giriş: onay mumunun tepesi + 1 tık   |   Stop: onay mumunun dibi - 1 tık
 4. ATR(14, RMA) filtresi: giriş-stop mesafesi <= 1.5 x ATR (onay mumundaki ATR)
    Giriş-stop mesafesi fiyatın %0.5'i ile %3'ü arasında olmalı (filtresiz: en az %0.3)
 4b. Temas mumu 00:00-08:00 UTC arasındaysa işlem yok (filtreli modda)
 5. Giriş emri onay mumundan sonraki 2 mum geçerli. Girişten önce fiyat onay
    mumunun dibinin altına inerse iptal.
 6. TP: riskin 2 katı (1:2)
 7. (İsteğe bağlı) Başabaş: +1R'ye gelince stop giriş seviyesine çekilir

Mum içinde hangi hareketin önce olduğu bilinmediği durumlarda TEMKİNLİ davranılır:
 - Aynı mum hem onay dibinin altına inip hem girişe değerse -> işlem yok
 - Aynı mum hem stopa hem TP'ye değerse -> stop sayılır
"""

import numpy as np
import pandas as pd

import strategy as st

# ---- Parametreler ----
CONFIRM_WINDOW = 3     # temastan sonra onay için beklenecek mum
ENTRY_WINDOW = 2       # onaydan sonra girişin gerçekleşmesi için beklenecek mum
ATR_PERIOD = 14
ATR_MAX_MULT = 1.5     # giriş-stop mesafesi en fazla bu kadar ATR
MIN_ATR_MULT = 0.0     # >0 ise giriş-stop mesafesi en az bu kadar ATR (örn. 0.875: ATR 40 -> en az 35)
BASE_MIN_RISK_PCT = 0.3  # filtresiz modda en dar stop (%)

# ---- Ek filtreler (30 günlük analizden; FILTERS=False ile kapatılır) ----
FILTERS = True
MIN_RISK_PCT = 0.5       # stop mesafesi en az %0.5 (daha darında komisyon riskin %15-22'si)
MAX_RISK_PCT = 3.0       # stop mesafesi en fazla %3 (daha genişi aşırı oynak/pump coinler)
SESSION_START_UTC = 8    # temas mumu 00:00-08:00 UTC (03:00-11:00 TR) arasındaysa işlem yok

# ---- Grafik incelemesinden gelen kurallar (varsayılan kapalı, backtest'te açılır) ----
WICK_MAX_BODY = 0.0          # >0: onay mumunun ters iğnesi (LONG'da üst) gövdenin bu katından uzunsa işlem yok
REQUIRE_PRIOR_TOUCH = False  # trend başladıktan sonra, tepeden önce en az bir EMA20 teması olmalı
STOP_BUFFER_ATR = 0.0        # stop onay mumunun ucundan bu kadar ATR daha uzağa konur
CLEAN_PIVOT_MAX = 0          # >0: son tepe/dip seviyesine bu kadar veya daha fazla mum dokunduysa (destek/direnç) işlem yok
CLEAN_PIVOT_ATR = 0.3        # "seviyeye dokundu" sayılma mesafesi (ATR)
CLEAN_PIVOT_BEFORE = 5       # tepeden/dipten kaç mum öncesinden itibaren sayılsın
TOUCH_WICK_MIN = 0.0         # >0: temas mumunun EMA20'ye doğru iğnesi en az gövdenin bu katı olmalı (fitil mum)
PIVOT_WICK_MAX = 0.0         # >0: tepe (LONG) / dip (SHORT) mumunun o yöndeki iğnesi gövdenin bu katından uzunsa işlem yok
QUIET_UTC = (0, 0)           # (başlangıç, bitiş) UTC saat: temas bu aralıktaysa işlem yok. (0, 4) = 03:00-07:00 TR
ROOM_MIN_R = 0.0             # >0: giriş ile önceki tepe (LONG) / dip (SHORT) arası en az bu kadar R olmalı (önünde yer)
STRUCTURE_BREAK = ""         # "wick" / "close": şu anki düzeltme önceki düzeltmenin dibini (LONG) / tepesini (SHORT) kırdıysa işlem yok
TOUCH_TAIL_MAX = 0.0         # >0: temas mumunun ters iğnesi (SHORT'ta alt, LONG'da üst) en fazla bu kadar TOUCH_TAIL_REF (kural 10)
TOUCH_TAIL_REF = "wick"      # "wick": EMA20 tarafındaki iğne · "atr": ATR · "body": gövde
SUPPORT_N = 0                # >0: son dipten (SHORT) / tepeden (LONG) sonraki bu kadar mum incelenir (kural 9)
SUPPORT_MIN = 2              # bunların en az bu kadarı dibe (tepeye) doğru iğneliyse destek (direnç) oluşmuş: işlem yok
SUPPORT_WICK_BODY = 1.0      # "iğneli" mum: dibe (tepeye) doğru iğne >= gövdenin bu katı
SUPPORT_WICK_ATR = 0.1       # ve iğne >= bu kadar ATR (minik mumların iğnesi sayılmasın)
PIVOT_LEG_MIN = 0            # >0: tepe (LONG) eski zirveyi kırdıktan sonra en az bu kadar mumla yapılmış olmalı (kural 11,
                             # tek mumluk fırlamayla yapılan tepe = temiz trend yükselişi değil)
TIME_STOP_BARS = 0           # >0: girişten bu kadar mum sonra TP/stop olmadıysa stop girişe çekilir; fiyat girişin
                             # gerisindeyse o mumun açılışında çıkılır (zaman stopu, "be" sayılır)
TIME_STOP_LOCK_R = 0.0       # zaman stopunda stop girişe değil girişin bu kadar R kârına çekilir; fiyat o seviyenin
                             # gerisindeyse o mumun açılışında çıkılır (kullanıcı 15.10: "aşırı yataya bağlarsa girişe
                             # gelince çıksın, hatta ufak kârda bile çıkabilir")
# Temiz trend (testte). Bacak: tepeden (LONG) / dipten (SHORT) önceki son EMA20 temasından tepeye/dibe kadar olan hareket
LEG_BODY_MIN = 0.0           # >0: bacaktaki mumların yön gövdeleri toplamı / mum boyları toplamı en az bu kadar
                             # (1 = hepsi iğnesiz düz gövde, ters mumlar ve iğneler düşürür)
LEG_ATR_MIN = 0.0            # >0: bacak boyu en az bu kadar ATR
SPIKE_MAX = 0.0              # >0: bacaktaki en büyük mum gövdesi bacağın en fazla bu oranı (tek mumluk fırlama değil)
EMA_FAN_MIN = 0.0            # >0: EMA20 ile EMA100 arası en az bu kadar ATR (EMA'lar açılmış, trend oturmuş)
# İki ayrı 90 günde (Nisan-Temmuz, Temmuz-Ekim) aynı yönde çıkan adaylar (14.10, /backtest 90 aday önceki2 ile 3. dönemde test)
LEG_COUNTER_MAX = 1.0        # <1: bacaktaki ters mumların oranı en fazla bu kadar (0.2 = 5 mumda en fazla 1 ters mum)
PULLBACK_MIN_BARS = 0        # >0: tepeden (LONG) / dipten (SHORT) temasa kadar en az bu kadar mum (düzeltme acele değil)
LEG_ATR_MAX = 0.0            # >0: bacak boyu bu kadar ATR'den KISA olmalı (aşırı uzamış hareketten sonraki geri çekilme değil)
TOUCH_PREV_EXTREME = False   # True: temas mumunun dibi (SHORT) önceki mumun dibinin altına inmemeli; LONG'da tepesi önceki
                             # mumun tepesinin üstüne çıkmamalı (kullanıcı, 14.10, XMR 19.03.2026 02:45)
FAILED_ENTRY_BARS = 0        # >0: giriş mumu dahil ilk bu kadar mumdan biri girişin gerisinde kapatırsa (LONG'da altında)
                             # o mumun kapanışında çıkılır: kırılım tutmadı, fiyat girişe sadece iğneyle değdi (kullanıcı,
                             # 14.10, BSV 15.09 19:45). Erken çıkış "be" durumuyla sayılır, res["early_exit"] = True
FAILED_ENTRY_RED = False     # True: erken çıkış sadece girişin gerisinde kapatan mum ters renkliyse (LONG'da kırmızı,
                             # SHORT'ta yeşil). Kullanıcı (15.10 01:57, ZETAUSDT 13.09 13:55): iğne atıp yeşil kapatan mumda çıkma.
# Erken çıkış zararını azaltma (kullanıcı 15.10 04:2x: "erken çıkışlar 0.3-0.6R yiyor, ölç biç mantıklı yol bul"). 12 ay
# 15m canlı ayarda 224 erken çıkış -74R (fiyat -54R + komisyon -20R); 157'si giriş mumunun kendisinde (fiyat girişe değip
# geri kapatmış = sahte kırılım). Derin kapanışlar az: 0.3R erken stop en fazla ~11R/12 ay kazandırabilir.
EARLY_STOP_R = 0.0           # >0: giriş mumu dahil ilk EARLY_STOP_BARS mumda stop girişin bu kadar R gerisinde (mum içinde
EARLY_STOP_BARS = 2          # tetiklenir), sonra asıl stopa döner. Giriş mumunda: kapanış seviyenin gerisindeyse kesin,
                             # mum girişin gerisinde kapatıp iğneyle seviyeyi geçtiyse ya da mum girişin ötesinde açıldıysa
                             # da tetiklendi sayılır (iğne dolumdan sonra varsayılır). "be" + early_exit + early_stop
CLOSE_ENTRY = False          # True: girişe stop emriyle değil, bir mum giriş seviyesinin ötesinde KAPATINCA o mumun
                             # kapanışında girilir (sahte kırılım mumuna girilmez). Risk = kapanış - stop, TP buna göre
CLOSE_ENTRY_MAX_R = 0.0      # >0: kapanış giriş seviyesinden bu kadar R'den uzaksa girme (kovalamaca, durum "chase")
CLOSE_ENTRY_KEEP_TP = False  # True: kapanışla girişte TP fiyatı değişmez (giriş seviyesi + RR·asıl risk)
# Grafik örnekleri (kullanıcı 15.10 04:37): RESOLVUSDT 20.08 02:15 LONG (düzeltme temiz görünse de mumlar çok iğneli,
# coin git-gel yapıyor, stopa iğneyle değdi), NILUSDT 25.08 19:15 SHORT (temiz dip yok: dipte taban, düzeltme kötü),
# ESPUSDT 30.08 11:30 SHORT dönüş (EMA'nın öbür tarafında kapatan temas mumunun gövdesi çok büyük = ters sinyal)
WICKY_MAX = 0.0              # >0: temastan önceki WICKY_BARS mumda iğne oranı (1 - gövdeler toplamı / mum boyları toplamı)
WICKY_BARS = 12              # bundan büyükse girme (git-gel yapan, iğneli piyasa). 15m'de 12 mum = 3 saat
RECLAIM_BODY_MAX_ATR = 0.0   # >0: dönüş varyasyonunda temas mumunun gövdesi bu kadar ATR'den büyükse girme
# Kullanıcı 15.10 13:41-13:43 (ETHFI 19.04 04:00 SHORT erken -0.53R sonra TP; BLUR 19.04 19:00 LONG stop %4.4 uzakta):
# "erken çıkışı esnetmek lazım" + "stop çok aşağıda, biraz yükseltsek TP mesafesi kısalır"
ENTRY_BUFFER_ATR = 0.0       # >0: giriş onay mumunun ucundan bu kadar ATR daha ötede (LONG'da yukarıda): iğneyle değip dönen
                             # sahte kırılımlarda emir dolmaz (kullanıcı 15.10 15:32, stopla birlikte de denenir)
STOP_MAX_ATR = 0.0           # >0: stop girişten bu kadar ATR'den uzaksa girişe bu kadar ATR yaklaştırılır (TP de yaklaşır)
EARLY_EXIT_MAX_ATR = 0.0     # >0: erken çıkış sadece mum dolumun en fazla bu kadar ATR gerisinde kapatırsa; daha derin
                             # kapatırsa erken çıkış o işlem için kapanır (asıl stop / TP beklenir). 18 ay CSV: >0.35 ATR
                             # derin kapanan erken çıkışların %30'u TP'ye gidiyor (sığların %12-19'u)
PIVOT_BAND2_ATR = 0.0        # >0: kural 4'e ek ikinci bant: son tepe/dibin bu kadar ATR yakınına PIVOT_BAND2_MAX ya da daha
PIVOT_BAND2_MAX = 5          # fazla mum uç verdiyse girme (dipte/tepede taban var). 3 dönem CSV: 1 ATR ≥5 mumdaki işlemler
                             # -2.5 / -3.6 / -13.7R. 12 mum iğne >0.58 (WICKY_MAX) -3.3 / -6.5 / -2.7R (15.10)
BTC_CORR_MAX = 0.0           # >0: coinin son BTC_CORR_BARS mumdaki getirileri BTC ile en az bu kadar benzerse (korelasyon)
                             # işlem yok: coin kendi hareketini değil BTC'yi izliyor (kullanıcı, 14.10). BTC'nin kendisine uygulanmaz.
BTC_CORR_BARS = 96           # benzerlik penceresi (15dk'da 96 mum = 24 saat)
SPIKE_TOP_ATR = 0.0          # >0: tepeyi (LONG) / dibi (SHORT) yapan son 2 mumun boyu, tepeden önceki ATR'nin bu
                             # katı ya da fazlasıysa girme (sivri tepe: düz giderken 2 dev mumla yapılan tepe)
ENTRY_MODE = "classic"       # "both": temas mumu EMA20'nin doğru tarafında kapatırsa klasik, öbür tarafında kapatırsa dönüş
                             # "classic": temas EMA20'nin doğru tarafında kapatır, 3 mumda onay
                             # "reclaim" (dönüş varyasyonu): temas EMA20'nin YANLIŞ tarafında kapatır, sonraki mum
                             # EMA20'nin doğru tarafında kapatır, ondan sonraki mum o mumun tepesini (LONG) kapanışla geçer = onay
RR = 2.0               # hedef: riskin kaç katı
BE_TRIGGER = 0.0       # >0 ise: fiyat bu kadar R kâra gelince stop girişe çekilir (0 = kapalı)
RISK_USD = 15.0        # 1R = kaç dolar (backtest raporlarında; 15.10 14:24 canlı/oto 1R = 15$ ile aynı)
FEE_TAKER = 0.0005     # Binance vadeli piyasa emri komisyonu (%0.05)
FEE_MAKER = 0.0002     # Binance vadeli limit emri komisyonu (%0.02)


def add_atr(df):
    """TradingView'daki ATR 14 RMA ile aynı yöntem."""
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [df["High"] - df["Low"], (df["High"] - prev_close).abs(), (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    df["ATR"] = tr.ewm(alpha=1 / ATR_PERIOD, adjust=False).mean()
    return df


def prior_touch_ok(df, i, side):
    """Trend teyidi: trend başladıktan ve fiyat EMA20'den ayrıldıktan sonra,
    son tepeden (LONG) / dipten (SHORT) önce en az bir kez EMA20'ye temas edilmiş mi?"""
    long = side == "LONG"
    E20, E50, E100 = df["EMA20"].values, df["EMA50"].values, df["EMA100"].values
    H, L = df["High"].values, df["Low"].values

    def aligned(j):
        return (E20[j] > E50[j] > E100[j]) if long else (E20[j] < E50[j] < E100[j])

    # Trendin başladığı mum: dizilimin kesintisiz sürdüğü en eski mum
    s = i
    while s - 1 >= max(0, i - 600) and aligned(s - 1):
        s -= 1
    # Kalkış: fiyatın EMA20'den tamamen ayrıldığı ilk mum (kesişme anındaki temaslar sayılmaz)
    k = s
    while k < i and not ((L[k] > E20[k]) if long else (H[k] < E20[k])):
        k += 1
    # Son tepe/dip (strategy.py ile aynı tanım)
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    for m in range(k + 1, pivot):
        if (L[m] <= E20[m] * st.TOLERANCE_LONG) if long else (H[m] >= E20[m] * st.TOLERANCE_SHORT):
            return True
    return False


def pivot_touches(df, i, side, atr_mult=None):
    """Son tepeye (LONG) / dibe (SHORT) yakın uç veren mum sayısı.
    Çok mum aynı seviyeye dokunduysa orada direnç/destek oluşmuş demektir."""
    long = side == "LONG"
    H, L, A = df["High"].values, df["Low"].values, df["ATR"].values
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    tol = (CLEAN_PIVOT_ATR if atr_mult is None else atr_mult) * A[pivot]
    lo = max(0, pivot - CLEAN_PIVOT_BEFORE)
    if long:
        return int((H[lo:i] >= H[pivot] - tol).sum())
    return int((L[lo:i] <= L[pivot] + tol).sum())


def candle_parts(o, h, l, c):
    """(gövde, üst iğne, alt iğne)"""
    return abs(c - o), h - max(o, c), min(o, c) - l


def _ohlc(df, i):
    """i. mumun (açılış, yüksek, düşük, kapanış) değerleri (tabloyu kopyalamadan)."""
    return df["Open"].values[i], df["High"].values[i], df["Low"].values[i], df["Close"].values[i]


def touch_is_wick_candle(df, i, side):
    """Kural 5: EMA20'ye iğneyle değen, gövdesi küçük temas mumu."""
    body, up, down = candle_parts(*_ohlc(df, i))
    wick = down if side == "LONG" else up
    return wick >= TOUCH_WICK_MIN * body and wick > 0


def pivot_wick_ok(df, i, side):
    """Kural 6: son tepe (LONG) / dip (SHORT) mumunda o yöne çok uzun iğne olmamalı."""
    long = side == "LONG"
    H, L = df["High"].values, df["Low"].values
    start = max(0, i - st.LOOKBACK)
    pivot = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    body, up, down = candle_parts(*_ohlc(df, pivot))
    wick = up if long else down
    return wick <= PIVOT_WICK_MAX * body


SWING_K = 3  # salınım tepesi/dibi: iki yanında bu kadar mumdan yüksek (düşük) olan mum


def last_swing_before(H, L, p, lo, long, k=SWING_K):
    """p'den önceki en yakın salınım tepesi (LONG) / dibi (SHORT); yoksa None."""
    for m in range(p - 2, lo + k - 1, -1):
        a, b = m - k, m + k + 1
        if long and H[m] >= H[a:b].max():
            return m
        if not long and L[m] <= L[a:b].min():
            return m
    return None


def structure_details(df, i, side, mode="wick"):
    """Kural 8'in kullandığı noktalar (inceleme için de kullanılır).
    p: son tepe (LONG) / dip (SHORT), q: ondan hemen önceki salınım tepesi/dibi,
    prior: q'dan SONRAKİ mumlarla p arasındaki düzeltmenin ucu, cur: p'den sonraki düzeltmenin ucu (temasa kadar)."""
    long = side == "LONG"
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    start = max(0, i - st.LOOKBACK)
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    out = {"p": p, "q": None, "ok": True}
    if p + 1 > i:
        return out
    q = last_swing_before(H, L, p, start, long)
    out["q"] = q
    if q is None:
        return out
    src = (L if mode == "wick" else C) if long else (H if mode == "wick" else C)
    if long:
        # Düzeltme tepe mumundan SONRA başlar: q mumunun kendi dibi yükselişe aittir
        prior_idx = q + 1 + int(np.argmin(L[q + 1:p]))
        cur_idx = p + 1 + int(np.argmin(src[p + 1:i + 1]))
        out.update(prior_idx=prior_idx, prior=L[prior_idx], cur_idx=cur_idx, cur=src[cur_idx])
        out["ok"] = out["cur"] >= out["prior"]
    else:
        prior_idx = q + 1 + int(np.argmax(H[q + 1:p]))
        cur_idx = p + 1 + int(np.argmax(src[p + 1:i + 1]))
        out.update(prior_idx=prior_idx, prior=H[prior_idx], cur_idx=cur_idx, cur=src[cur_idx])
        out["ok"] = out["cur"] <= out["prior"]
    return out


def structure_ok(df, i, side, mode="wick"):
    """Kural 8: yükselen dip (LONG) / alçalan tepe (SHORT) yapısı bozulmamış olmalı."""
    return structure_details(df, i, side, mode)["ok"]


def support_details(df, i, side, n=None, need=None, wick_body=None, wick_atr=None):
    """Kural 9: son dipten (SHORT) sonra gelen mumlar dibe doğru iğne bırakarak yükseldiyse orada
    alıcı var (destek) demektir; LONG'da tepeden sonra yukarı iğneli mumlar (direnç).
    Temas mumundan önceki mumlara bakılır."""
    n = SUPPORT_N if n is None else n
    need = SUPPORT_MIN if need is None else need
    wick_body = SUPPORT_WICK_BODY if wick_body is None else wick_body
    wick_atr = SUPPORT_WICK_ATR if wick_atr is None else wick_atr
    long = side == "LONG"
    O, H, L, C, A = (df[c].values for c in ("Open", "High", "Low", "Close", "ATR"))
    start = max(0, i - st.LOOKBACK)
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    rows = []
    for m in range(p + 1, min(p + 1 + n, i)):
        body, up, down = candle_parts(O[m], H[m], L[m], C[m])
        wick = up if long else down
        ok = wick > 0 and wick >= wick_body * body and wick >= wick_atr * A[m]
        rows.append({"bar": m, "wick": wick, "body": body, "atr": A[m], "ok": bool(ok)})
    count = sum(r["ok"] for r in rows)
    return {"p": p, "rows": rows, "count": count, "support": n > 0 and count >= need}


def touch_tail(df, i, side):
    """Kural 10 ölçüleri: (ters iğne, EMA tarafı iğne, gövde, ATR)."""
    body, up, down = candle_parts(*_ohlc(df, i))
    long = side == "LONG"
    return (up if long else down), (down if long else up), body, float(df["ATR"].values[i])


def touch_tail_ok(df, i, side, max_mult=None, ref=None):
    """Kural 10: temas mumu EMA20'den güçlü dönmeli; ters yöndeki iğne (SHORT'ta alt) uzun olmamalı."""
    max_mult = TOUCH_TAIL_MAX if max_mult is None else max_mult
    ref = TOUCH_TAIL_REF if ref is None else ref
    tail, wick, body, atr = touch_tail(df, i, side)
    base = {"wick": wick, "atr": atr, "body": body}[ref]
    return tail <= max_mult * base


def pivot_leg(df, i, side):
    """Kural 11: son tepe (LONG) eski zirveyi kapanışla kırdıktan sonra kaç mumda yapıldı.
    1 = tepe, eski zirveyi kıran mumun kendisi (tek mumluk fırlama); 0 = kırılım tepeden sonra geldi."""
    long = side == "LONG"
    H, L, C = df["High"].values, df["Low"].values, df["Close"].values
    start = max(0, i - st.LOOKBACK)
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    past_end = p - st.PEAK_GAP
    if past_end <= start:
        return 0
    old = H[start:past_end].max() if long else L[start:past_end].min()
    seg = C[past_end:p + 1]
    above = np.flatnonzero(seg > old) if long else np.flatnonzero(seg < old)
    if len(above) == 0:
        return 0
    return p - (past_end + int(above[0])) + 1


LEG_LOOK = 60      # bacağın başı (son EMA20 teması) tepeden en fazla bu kadar mum geride aranır
TREND_AGE_MAX = 300


def wickiness(df, a, b):
    """[a, b) mumlarında iğne oranı: 1 - gövdeler toplamı / mum boyları toplamı (0 = hepsi düz gövde, 1 = hepsi iğne)."""
    a = max(0, a)
    if b <= a:
        return float("nan")
    O, H, L, C = (df[c].values[a:b] for c in ("Open", "High", "Low", "Close"))
    rng = float((H - L).sum())
    return 1.0 - float(np.abs(C - O).sum()) / rng if rng > 0 else float("nan")


def trend_features(df, i, side, entry=None, risk=None):
    """Temiz trend ölçüleri (i: temas mumu). TP ile stop olan işlemleri karşılaştırmak ve filtre için.
    Bacak: son tepeden (LONG) / dipten (SHORT) önceki son EMA20 temasından sonraki mumlar, tepe mumu dahil."""
    long = side == "LONG"
    O, H, L, C, A = (df[c].values for c in ("Open", "High", "Low", "Close", "ATR"))
    E20, E50, E100 = (df[c].values for c in ("EMA20", "EMA50", "EMA100"))
    start = max(0, i - st.LOOKBACK)
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    lo = max(start, p - LEG_LOOK)
    s = None
    for m in range(p - 1, lo - 1, -1):
        if (L[m] <= E20[m] * st.TOLERANCE_LONG) if long else (H[m] >= E20[m] * st.TOLERANCE_SHORT):
            s = m
            break
    if s is None:  # bacak EMA20'ye hiç değmeden başlamış: penceredeki en uç dip (LONG) / tepe (SHORT)
        s = lo + int(np.argmin(L[lo:p]) if long else np.argmax(H[lo:p])) if p > lo else max(0, p - 1)
    seg = slice(s + 1, p + 1)
    if long:
        leg = H[p] - L[s:p + 1].min()
        dirb = C[seg] - O[seg]
    else:
        leg = H[s:p + 1].max() - L[p]
        dirb = O[seg] - C[seg]
    rng = float((H[seg] - L[seg]).sum())
    a = float(A[i]) if A[i] > 0 else float("nan")
    sign = 1.0 if long else -1.0
    age, m = 0, i
    while m >= 0 and age < TREND_AGE_MAX and ((E20[m] > E50[m] > E100[m]) if long else (E20[m] < E50[m] < E100[m])):
        age += 1
        m -= 1
    f = {
        "bacak_mum": int(p - s),
        "bacak_atr": leg / a,
        "bacak_govde": float(dirb.sum()) / rng if rng > 0 else 0.0,
        "tek_mum": max(float(dirb.max()), 0.0) / leg if leg > 0 and len(dirb) else 1.0,
        "ters_mum": float((dirb < 0).mean()) if len(dirb) else 0.0,
        "ema_acilim": sign * (E20[i] - E100[i]) / a,
        "ema_egim": sign * (E20[i] - E20[max(0, i - 8)]) / a,
        "trend_yasi": age,
        "duzeltme": ((H[p] - L[i]) if long else (H[i] - L[p])) / leg if leg > 0 else float("nan"),
        "duzeltme_mum": int(i - p),
        "igne_orani": wickiness(df, i - WICKY_BARS, i),           # temastan önceki 12 mum
        "duz_igne": wickiness(df, p + 1, i),                      # tepe/dipten temasa kadar (düzeltme)
        "temas_govde_atr": abs(C[i] - O[i]) / a,
        "pivot_bant_05": pivot_touches(df, i, side, atr_mult=0.5),
        "pivot_bant_1": pivot_touches(df, i, side, atr_mult=1.0),
        "_p": int(p), "_s": int(s),
    }
    if entry is not None and risk:
        f["onu_r"] = ((H[p] - entry) if long else (entry - L[p])) / risk
    return f


# Testteki "temiz trend" eşikleri (/backtest 90 temiz, /incele'de de gösterilir)
TEMIZ_TEST = dict(LEG_BODY_MIN=0.4, LEG_ATR_MIN=4.0, SPIKE_MAX=0.5, EMA_FAN_MIN=2.0)


ADAY_TEST = dict(LEG_COUNTER_MAX=0.2, PULLBACK_MIN_BARS=5, LEG_ATR_MAX=4.0)
_CLEAN_KEYS = ("LEG_BODY_MIN", "LEG_ATR_MIN", "SPIKE_MAX", "EMA_FAN_MIN", "LEG_COUNTER_MAX", "PULLBACK_MIN_BARS",
               "LEG_ATR_MAX")
_CLEAN_OFF = dict(LEG_BODY_MIN=0.0, LEG_ATR_MIN=0.0, SPIKE_MAX=0.0, EMA_FAN_MIN=0.0, LEG_COUNTER_MAX=1.0,
                  PULLBACK_MIN_BARS=0, LEG_ATR_MAX=0.0)


def clean_trend_active():
    g = globals()
    return any(g[k] != _CLEAN_OFF[k] for k in _CLEAN_KEYS)


def clean_trend_ok(f, limits=None):
    """Temiz trend filtreleri. limits verilmezse şu anki ayarlardaki açık olanlar uygulanır
    (limits'te olmayan filtreler kapalı sayılır)."""
    g = dict(_CLEAN_OFF, **limits) if limits else {k: globals()[k] for k in _CLEAN_KEYS}
    if g["LEG_BODY_MIN"] > 0 and f["bacak_govde"] < g["LEG_BODY_MIN"]:
        return False
    if g["LEG_ATR_MIN"] > 0 and not f["bacak_atr"] >= g["LEG_ATR_MIN"]:
        return False
    if g["SPIKE_MAX"] > 0 and f["tek_mum"] > g["SPIKE_MAX"]:
        return False
    if g["EMA_FAN_MIN"] > 0 and not f["ema_acilim"] >= g["EMA_FAN_MIN"]:
        return False
    if g["LEG_COUNTER_MAX"] < 1 and f["ters_mum"] > g["LEG_COUNTER_MAX"] + 1e-9:
        return False
    if g["PULLBACK_MIN_BARS"] > 0 and f["duzeltme_mum"] < g["PULLBACK_MIN_BARS"]:
        return False
    if g["LEG_ATR_MAX"] > 0 and not f["bacak_atr"] < g["LEG_ATR_MAX"]:
        return False
    return True


def spike_top(df, i, side):
    """Sivri tepe ölçüsü: tepeyi (LONG) / dibi (SHORT) yapan mum ile ondan önceki mumun toplam boyu, tepeden 2 mum
    önceki ATR cinsinden (ATR o iki mumdan etkilenmesin diye). Kullanıcı örneği: SQDUSDT 5m 05.10.2026 00:50."""
    long = side == "LONG"
    H, L, A = df["High"].values, df["Low"].values, df["ATR"].values
    start = max(0, i - st.LOOKBACK)
    if i - start < 1:
        return 0.0
    p = start + int(np.argmax(H[start:i]) if long else np.argmin(L[start:i]))
    q = max(0, p - 1)
    a = A[max(0, p - 2)]
    if not a > 0:
        return 0.0
    move = (H[p] - min(L[q], L[p])) if long else (max(H[q], H[p]) - L[p])
    return float(move / a)


def btc_corr(df, i, bars=None):
    """Coinin son `bars` mumdaki getirilerinin BTC getirileriyle korelasyonu (1 = birebir aynı hareket, 0 = ilgisiz).
    Tabloda BTC_Close sütunu yoksa (BTC'nin kendisi ya da BTC verisi alınamadı) NaN."""
    if "BTC_Close" not in df.columns:
        return float("nan")
    bars = BTC_CORR_BARS if bars is None else bars
    lo = i - bars
    if lo < 0:
        return float("nan")
    c = df["Close"].values[lo:i + 1]
    b = df["BTC_Close"].values[lo:i + 1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rc, rb = np.diff(np.log(c)), np.diff(np.log(b))
    ok = np.isfinite(rc) & np.isfinite(rb)
    if ok.sum() < 0.8 * bars or rc[ok].std() == 0 or rb[ok].std() == 0:
        return float("nan")
    return float(np.corrcoef(rc[ok], rb[ok])[0, 1])


def mfe_r(df, res, side, max_bars=96):
    """Girişten sonra, ilk stop (erken çıkış ve TP yokmuş gibi) gelmeden önce fiyatın lehte gittiği en uzak nokta (R).
    En fazla max_bars mum (15dk'da 96 = 24 saat) bakılır. Stop mumunun içindeki uç sayılmaz (önce stop varsayılır)."""
    if "entry_bar" not in res:
        return float("nan")
    H, L = df["High"].values, df["Low"].values
    long = side == "LONG"
    k, fill, stop, risk = res["entry_bar"], res["fill"], res["stop"], res["risk"]
    best = fill if res.get("close_entry") else (H[k] if long else L[k])   # kapanışla girişte mumun ucu dolumdan önce
    for m in range(k + 1, min(len(df), k + 1 + max_bars)):
        if (L[m] <= stop) if long else (H[m] >= stop):
            break
        best = max(best, H[m]) if long else min(best, L[m])
    return ((best - fill) if long else (fill - best)) / risk if risk else float("nan")


def touch_closes_right_side(df, i, side):
    c, e = df["Close"].values[i], df["EMA20"].values[i]
    return c > e if side == "LONG" else c < e


def simulate(df, i, side, tick, mode=None):
    """i: temas mumu. Sonucu sözlük olarak döner. mode: None = ENTRY_MODE ("classic" / "reclaim").
    status: session | quiet | no_close | no_close_below | no_reclaim | touch_body | no_prior_touch | structure_break | dirty_pivot | pivot_wick | support | pivot_leg | not_clean | btc_corr | spike_top | touch_prev | touch_tail | cancel_touch | no_confirm | wick | atr | atr_min |
            min_risk | max_risk | no_room | cancel_confirm |
            no_entry | chase | wicky | big_touch | wide_pivot | win | loss | be | open | pending"""
    O = df["Open"].values
    H = df["High"].values
    L = df["Low"].values
    C = df["Close"].values
    A = df["ATR"].values
    n = len(df)
    long = side == "LONG"
    mode = ENTRY_MODE if mode is None else mode
    res = {"side": side, "touch": i}

    if FILTERS and "timestamp" in df.columns:
        hour_utc = (int(df["timestamp"].values[i]) // 3_600_000) % 24
        if hour_utc < SESSION_START_UTC:
            res["status"] = "session"
            return res

    if QUIET_UTC[0] < QUIET_UTC[1] and "timestamp" in df.columns:
        hour_utc = (int(df["timestamp"].values[i]) // 3_600_000) % 24
        if QUIET_UTC[0] <= hour_utc < QUIET_UTC[1]:
            res["status"] = "quiet"
            return res

    E20 = df["EMA20"].values
    if mode == "both":
        # İki varyasyon birlikte: temas mumunun kapanışı hangisi olduğunu belirler (ikisi aynı mumda olamaz)
        mode = "classic" if touch_closes_right_side(df, i, side) else "reclaim"
    res["mode"] = mode
    if mode == "reclaim":
        # Dönüş varyasyonu: temas mumu EMA20'yi gövdeyle geçip YANLIŞ tarafta kapatmalı
        if (C[i] >= E20[i]) if long else (C[i] <= E20[i]):
            res["status"] = "no_close_below"
            return res
    elif not touch_closes_right_side(df, i, side):
        res["status"] = "no_close"
        return res

    # Kural 5 (fitil temas) dönüş varyasyonunda uygulanmaz: temas mumu zaten EMA20'nin öbür tarafında kapatıyor
    if mode != "reclaim" and TOUCH_WICK_MIN > 0 and not touch_is_wick_candle(df, i, side):
        res["status"] = "touch_body"
        return res
    if TOUCH_TAIL_MAX > 0 and not touch_tail_ok(df, i, side):
        res["status"] = "touch_tail"
        return res
    if TOUCH_PREV_EXTREME and i >= 1 and ((H[i] > H[i - 1]) if long else (L[i] < L[i - 1])):
        res["status"] = "touch_prev"
        return res
    if REQUIRE_PRIOR_TOUCH and not prior_touch_ok(df, i, side):
        res["status"] = "no_prior_touch"
        return res
    if STRUCTURE_BREAK and not structure_ok(df, i, side, STRUCTURE_BREAK):
        res["status"] = "structure_break"
        return res
    if CLEAN_PIVOT_MAX > 0 and pivot_touches(df, i, side) >= CLEAN_PIVOT_MAX:
        res["status"] = "dirty_pivot"
        return res
    if PIVOT_BAND2_ATR > 0 and pivot_touches(df, i, side, atr_mult=PIVOT_BAND2_ATR) >= PIVOT_BAND2_MAX:
        res["status"] = "wide_pivot"
        return res
    if PIVOT_WICK_MAX > 0 and not pivot_wick_ok(df, i, side):
        res["status"] = "pivot_wick"
        return res
    if SUPPORT_N > 0 and support_details(df, i, side)["support"]:
        res["status"] = "support"
        return res
    if PIVOT_LEG_MIN > 0 and pivot_leg(df, i, side) < PIVOT_LEG_MIN:
        res["status"] = "pivot_leg"
        return res
    if clean_trend_active() and not clean_trend_ok(trend_features(df, i, side)):
        res["status"] = "not_clean"
        return res
    if BTC_CORR_MAX > 0:
        k = btc_corr(df, i)
        res["btc_kor"] = k
        if k == k and k >= BTC_CORR_MAX:   # NaN (BTC'nin kendisi / veri yok) filtrelenmez
            res["status"] = "btc_corr"
            return res
    if SPIKE_TOP_ATR > 0 and spike_top(df, i, side) >= SPIKE_TOP_ATR:
        res["status"] = "spike_top"
        return res
    if WICKY_MAX > 0 and wickiness(df, i - WICKY_BARS, i) > WICKY_MAX:
        res["status"] = "wicky"
        return res
    if RECLAIM_BODY_MAX_ATR > 0 and mode == "reclaim" and abs(C[i] - O[i]) > RECLAIM_BODY_MAX_ATR * A[i]:
        res["status"] = "big_touch"
        return res

    # --- Onay ---
    conf = None
    if mode == "reclaim":
        j = i + 1  # dönüş mumu: EMA20'nin doğru tarafında kapatmalı
        if j >= n:
            res["status"] = "pending"
            return res
        if not ((C[j] > E20[j]) if long else (C[j] < E20[j])):
            res["status"] = "no_reclaim"
            return res
        res["reclaim"] = j
        conf = j + 1  # onay: dönüş mumunun tepesini (LONG) / dibini (SHORT) kapanışla geçmeli
        if conf >= n:
            res["status"] = "pending"
            return res
        if not ((C[conf] > H[j]) if long else (C[conf] < L[j])):
            res["status"] = "no_confirm"
            return res
    for j in (range(i + 1, i + 1 + CONFIRM_WINDOW) if conf is None else ()):
        if j >= n:
            res["status"] = "pending"
            return res
        if (L[j] < L[i]) if long else (H[j] > H[i]):
            res["status"] = "cancel_touch"
            return res
        if (C[j] > H[i]) if long else (C[j] < L[i]):
            conf = j
            break
    if conf is None:
        res["status"] = "no_confirm"
        return res

    if WICK_MAX_BODY > 0:
        body = abs(C[conf] - O[conf])
        wick = (H[conf] - max(O[conf], C[conf])) if long else (min(O[conf], C[conf]) - L[conf])
        if wick > WICK_MAX_BODY * body:
            res.update(confirm=conf, status="wick")
            return res

    buf = STOP_BUFFER_ATR * A[conf]
    ebuf = ENTRY_BUFFER_ATR * A[conf]
    if long:
        entry, stop = H[conf] + tick + ebuf, L[conf] - tick - buf
    else:
        entry, stop = L[conf] - tick - ebuf, H[conf] + tick + buf
    risk = abs(entry - stop)
    base_risk = risk - buf - ebuf  # ATR sınırları stop/giriş payları eklenmeden önceki mesafeye uygulanır
    tp = entry + RR * risk if long else entry - RR * risk
    res.update(confirm=conf, entry=entry, stop=stop, tp=tp, risk=risk, atr=A[conf])

    if base_risk > ATR_MAX_MULT * A[conf]:
        res["status"] = "atr"
        return res
    if STOP_MAX_ATR > 0 and risk > STOP_MAX_ATR * A[conf]:
        risk = STOP_MAX_ATR * A[conf]
        stop = entry - risk if long else entry + risk
        tp = entry + RR * risk if long else entry - RR * risk
        res.update(stop=stop, tp=tp, risk=risk, stop_capped=True)
    if MIN_ATR_MULT > 0 and base_risk < MIN_ATR_MULT * A[conf]:
        res["status"] = "atr_min"
        return res
    risk_pct = 100 * risk / entry
    if risk_pct < (MIN_RISK_PCT if FILTERS else BASE_MIN_RISK_PCT):
        res["status"] = "min_risk"
        return res
    if FILTERS and risk_pct > MAX_RISK_PCT:
        res["status"] = "max_risk"
        return res
    if ROOM_MIN_R > 0:
        start = max(0, i - st.LOOKBACK)
        level = H[start:i].max() if long else L[start:i].min()   # önceki tepe / dip
        room = (level - entry) if long else (entry - level)
        res["room_r"] = room / risk
        # Giriş seviyeyi zaten geçtiyse (room < 0) önünde engel yok sayılır
        if 0 <= room < ROOM_MIN_R * risk:
            res["status"] = "no_room"
            return res

    # --- Giriş ---
    k_in = None
    for k in range(conf + 1, conf + 1 + ENTRY_WINDOW):
        if k >= n:
            res["status"] = "pending"
            return res
        if (L[k] < L[conf]) if long else (H[k] > H[conf]):
            res["status"] = "cancel_confirm"
            return res
        if CLOSE_ENTRY:
            if (C[k] > entry) if long else (C[k] < entry):
                k_in = k
                break
        elif (H[k] >= entry) if long else (L[k] <= entry):
            k_in = k
            break
    if k_in is None:
        res["status"] = "no_entry"
        return res

    if CLOSE_ENTRY:
        # Kapanışla giriş: işlem bir sonraki mumdan itibaren yürür
        fill = C[k_in]
        over = (fill - entry) if long else (entry - fill)
        if CLOSE_ENTRY_MAX_R > 0 and over > CLOSE_ENTRY_MAX_R * risk:
            res["status"] = "chase"
            return res
        risk = abs(fill - stop)
        if not CLOSE_ENTRY_KEEP_TP:
            tp = fill + RR * risk if long else fill - RR * risk
        res.update(risk=risk, tp=tp, close_entry=True)
    else:
        fill = max(entry, O[k_in]) if long else min(entry, O[k_in])
    res.update(entry_bar=k_in, fill=fill)

    # --- Çıkış ---
    def close_trade(bar, price, status):
        res.update(exit_bar=bar, exit=price, status=status)
        gross = (price - fill) / risk if long else (fill - price) / risk
        fees = (fill * FEE_TAKER + price * (FEE_MAKER if status == "win" else FEE_TAKER)) / risk
        res.update(r_gross=gross, r_net=gross - fees)
        return res

    # Başabaş: fiyat +BE_TRIGGER R'ye gelince stop girişe çekilir (sonraki mumdan itibaren)
    be_level = (fill + BE_TRIGGER * risk) if long else (fill - BE_TRIGGER * risk)
    cur_stop, be_on = stop, False

    def reached_be(bar):
        return BE_TRIGGER > 0 and ((H[bar] >= be_level) if long else (L[bar] <= be_level))

    early_off = [False]

    def failed(bar):
        # Kırılım tutmadı: mum girişin gerisinde kapattı (giriş sadece iğneyle olmuş)
        ok = not early_off[0] and FAILED_ENTRY_BARS > 0 and bar - k_in < FAILED_ENTRY_BARS and \
            ((C[bar] < entry) if long else (C[bar] > entry)) and \
            (not FAILED_ENTRY_RED or ((C[bar] < O[bar]) if long else (C[bar] > O[bar])))
        if ok and EARLY_EXIT_MAX_ATR > 0 and ((fill - C[bar]) if long else (C[bar] - fill)) > EARLY_EXIT_MAX_ATR * A[conf]:
            early_off[0] = True   # derin geri kapanış: erken çıkma, asıl stop / TP beklenir
            res["early_skipped"] = True
            return False
        return ok

    # Erken stop: ilk EARLY_STOP_BARS mumda girişin EARLY_STOP_R gerisinde
    es_level = (fill - EARLY_STOP_R * risk) if long else (fill + EARLY_STOP_R * risk)

    def early_stop(bar, price):
        res["early_exit"] = res["early_stop"] = True
        return close_trade(bar, price, "be")

    # Kapanışla girişte giriş mumu işlemin parçası değil (dolum kapanışta)
    if not CLOSE_ENTRY:
        # Giriş mumunda TP (stop bu mumda olamaz: olsaydı giriş iptal edilirdi)
        if (H[k_in] >= tp) if long else (L[k_in] <= tp):
            return close_trade(k_in, tp, "win")
        if EARLY_STOP_R > 0 and EARLY_STOP_BARS > 0:
            beyond_close = (C[k_in] < es_level) if long else (C[k_in] > es_level)
            dipped = (L[k_in] <= es_level) if long else (H[k_in] >= es_level)
            bad_close = (C[k_in] < entry) if long else (C[k_in] > entry)
            gap = (O[k_in] >= entry) if long else (O[k_in] <= entry)
            if beyond_close or (dipped and (bad_close or gap)):
                return early_stop(k_in, es_level)
        if failed(k_in):
            res["early_exit"] = True
            return close_trade(k_in, C[k_in], "be")
        if reached_be(k_in):
            cur_stop, be_on = fill, True

    time_moved = False
    for m in range(k_in + 1, n):
        if EARLY_STOP_R > 0 and m - k_in < EARLY_STOP_BARS and ((L[m] <= es_level) if long else (H[m] >= es_level)):
            return early_stop(m, min(es_level, O[m]) if long else max(es_level, O[m]))
        if TIME_STOP_BARS > 0 and not time_moved and m - k_in >= TIME_STOP_BARS:
            # Zaman stopu: süre doldu, stop girişe; fiyat girişin gerisindeyse bu mumun açılışında çık
            time_moved = True
            level = (fill + TIME_STOP_LOCK_R * risk) if long else (fill - TIME_STOP_LOCK_R * risk)
            if (O[m] < level) if long else (O[m] > level):
                res["time_exit"] = True
                return close_trade(m, O[m], "be")
            cur_stop, be_on = level, True
        hit_stop = (L[m] <= cur_stop) if long else (H[m] >= cur_stop)
        hit_tp = (H[m] >= tp) if long else (L[m] <= tp)
        if hit_stop:
            price = min(cur_stop, O[m]) if long else max(cur_stop, O[m])
            return close_trade(m, price, "be" if be_on else "loss")
        if hit_tp:
            return close_trade(m, tp, "win")
        if failed(m):
            res["early_exit"] = True
            return close_trade(m, C[m], "be")
        if not be_on and reached_be(m):
            cur_stop, be_on = fill, True

    res["status"] = "open"
    return res
