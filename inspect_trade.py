"""
/incele komutu: bir işlemin (coin + temas saati) bütün kurallarda nasıl değerlendirildiğini
rakamlarla açıklar. Kural tanımlarını kullanıcının grafikte gördüğüyle eşleştirmek için.

Örnek: /incele AXSUSDT 01.08.2026 02:00   (Türkiye saati)
"""

import html
import re
import time

import numpy as np
import pandas as pd

import config
import live_setups
import strategy as st
import trade_rules as tr
from exchanges import get_klines_range, get_tick_sizes

TZ = "Europe/Istanbul"


def parse(text):
    m = re.search(r"([A-Za-z0-9]+)\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}))?\s+(\d{1,2}):(\d{2})(?:\s+(\d+[mh]))?", text)
    if not m:
        return None
    sym, d, mo, y, h, mi, tf = m.groups()
    sym = sym.upper()
    if not sym.endswith("USDT"):
        sym += "USDT"
    year = int(y) if y else pd.Timestamp.now(tz=TZ).year
    ts = pd.Timestamp(year=year, month=int(mo), day=int(d), hour=int(h), minute=int(mi), tz=TZ)
    return sym, ts, (tf or "15m").lower()


def explain(text):
    """Sadece metin (eski kullanım)."""
    return inspect(text)[0]


def inspect(text, chart_path="/tmp/incele.png"):
    """(açıklama metni, grafik dosyası ya da None)"""
    parsed = parse(text)
    if not parsed:
        return ("Kullanım: /incele AXSUSDT 01.08.2026 02:00 (temas mumunun Türkiye saati, 15dk)\n"
                "5 dakikalık canlı bildirim için sona 5m ekle: /incele AXSUSDT 13.10 22:05 5m\n"
                "Saat olarak EMİR HAZIR mesajındaki temas ya da onay saatini yazabilirsin (en yakın temas bulunur)."), None
    sym, ts_tr, tf = parsed
    tf_ms = config.tf_minutes(tf) * 60_000
    t_ms = int(ts_tr.tz_convert("UTC").value // 10**6)
    df = get_klines_range(sym, tf, t_ms - 600 * tf_ms, t_ms + 40 * tf_ms, yield_live=False, max_wait=60)
    if df is None or df.empty:
        return f"{sym} için veri alınamadı.", None
    df = tr.add_atr(st.add_indicators(df.reset_index(drop=True)))
    hits = np.flatnonzero(df["timestamp"].values == t_ms)
    if len(hits) == 0:
        return f"{sym} {ts_tr:%d.%m.%Y %H:%M} mumu veride yok ({tf} mumun başlangıç saati olmalı).", None
    i = int(hits[0])
    live_setups.apply_rules()
    # Verilen mum temas değilse (ör. EMİR HAZIR mesajının saati yazıldıysa) önceki 6 mumdaki en yakın teması al
    moved = None
    if not st.evaluate_at(df, i):
        for j in range(i - 1, max(0, i - 7), -1):
            if st.evaluate_at(df, j):
                moved, i = i, j
                ts_tr = pd.Timestamp(int(df["timestamp"].values[j]), unit="ms", tz="UTC").tz_convert(TZ)
                break
    # Fiyat adımı: önce canlı taramanın elindeki liste (Binance'e fazladan istek atmamak için)
    tick = live_setups._state["ticks"].get(sym)
    if tick is None:
        try:
            tick = get_tick_sizes().get(sym, 0.0)
        except Exception:
            tick = 0.0
    H, L, C, O = (df[c].values for c in ("High", "Low", "Close", "Open"))
    fmt = lambda k: pd.Timestamp(int(df["timestamp"].values[k]), unit="ms", tz="UTC").tz_convert(TZ).strftime("%d.%m %H:%M")
    p8 = lambda x: f"{x:.8g}"
    ok = lambda b: "✅" if b else "❌"

    d = st.diagnose(df, i)
    side = d.get("side")
    lines = [f"🔍 <b>{html.escape(sym)} {tf} {ts_tr:%d.%m.%Y %H:%M} TR</b>"
             + (f" (yazdığın saatte temas yoktu, en yakın temas mumu bu)" if moved is not None else ""),
             f"Temas mumu: A {p8(O[i])} Y {p8(H[i])} D {p8(L[i])} K {p8(C[i])} | EMA20 {p8(df['EMA20'].values[i])} | Stoch {df['Stoch_K'].values[i]:.1f}",
             "", "<b>Temel şartlar</b>"]
    for key, label in [("trend", "Net trend"), ("pivot_recent", "Tepe/dip son 30 mumda"),
                       ("body_break", "Gövde kapanışlı kırılım"), ("first_touch", "EMA20'ye ilk temas"),
                       ("clean_pullback", "En fazla 2 ters mum"), ("touch", "İğne EMA20'ye değdi"),
                       ("stoch", "Stoch şartı")]:
        if key in d:
            lines.append(f"{ok(d[key])} {label}")
    if not side:
        return "\n".join(lines + ["", "Trend yok, diğer kurallar kontrol edilmedi."]), None

    long = side == "LONG"
    lines += ["", f"<b>Kurallar ({side})</b>"]
    lines.append(f"{ok(tr.touch_closes_right_side(df, i, side))} Temas mumu EMA20'nin doğru tarafında kapattı")
    body = abs(C[i] - O[i]); wick = (min(O[i], C[i]) - L[i]) if long else (H[i] - max(O[i], C[i]))
    lines.append(f"{ok(wick >= body and wick > 0)} 5) Fitil temas: iğne {p8(wick)} / gövde {p8(body)}")
    lines.append(f"{ok(tr.prior_touch_ok(df, i, side))} 2) Trend teyidi (önceden EMA20 teması)")
    n_touch = tr.pivot_touches(df, i, side)
    lines.append(f"{ok(n_touch < 3)} 4) Temiz tepe/dip: seviyeye {n_touch} mum dokunmuş (3+ ise kötü)")
    lines.append(f"{ok(tr.pivot_wick_ok(df, i, side) if tr.PIVOT_WICK_MAX else True)} 6) Tepe/dip mumunun iğnesi ≤ 2 gövde")
    tail, ewick, tbody, tatr = tr.touch_tail(df, i, side)
    lines.append(f"{ok(tail <= ewick)} 10) (testte) Ters iğne {p8(tail)} | EMA tarafı iğne {p8(ewick)} | "
                 f"gövde {p8(tbody)} | {tail / tatr:.2f} ATR")
    hour_utc = (int(df["timestamp"].values[i]) // 3_600_000) % 24
    lines.append(f"{ok(not (0 <= hour_utc < 4))} 03:00-07:00 TR dışında")

    sd = tr.structure_details(df, i, side, "wick")
    # (yalın, -si hali, düzeltme ucunun -i hali)
    peak = ("tepe", "tepesi") if long else ("dip", "dibi")
    pull = "dibi" if long else "tepesi"
    lines += ["", "<b>8) Yapı (önceki düzeltme)</b>",
              f"Son {peak[0]} (p): {fmt(sd['p'])} → {p8(H[sd['p']] if long else L[sd['p']])}"]
    if sd["q"] is None:
        lines.append(f"Önceki salınım {peak[1]} bulunamadı → kural uygulanmadı")
    else:
        lines.append(f"Önceki salınım {peak[1]} (q): {fmt(sd['q'])} → {p8(H[sd['q']] if long else L[sd['q']])}")
        lines.append(f"Önceki düzeltmenin {pull}: {fmt(sd['prior_idx'])} → {p8(sd['prior'])}")
        lines.append(f"Şimdiki düzeltmenin {pull}: {fmt(sd['cur_idx'])} → {p8(sd['cur'])}")
        lines.append(f"{ok(sd['ok'])} Yapı {'sağlam' if sd['ok'] else 'BOZUK (önceki düzeltme kırılmış)'}")

    sup = tr.support_details(df, i, side, n=3, need=2, wick_body=0.5, wick_atr=tr.SUPPORT_WICK_ATR)
    abl = "Tepeden" if long else "Dipten"
    lines += ["", f"<b>9) {abl} sonraki mumlar (testte)</b>"]
    if not sup["rows"]:
        lines.append(f"{peak[0].capitalize()} ile temas arasında mum yok")
    for k, row in enumerate(sup["rows"], 1):
        ratio = row["wick"] / row["body"] if row["body"] > 0 else float("inf")
        lines.append(f"{'🟡' if row['ok'] else '⚪'} {k}. mum {fmt(row['bar'])}: {'alt' if not long else 'üst'} iğne {p8(row['wick'])}, "
                     f"gövde {p8(row['body'])} (iğne/gövde {ratio:.1f}, {row['wick'] / row['atr']:.2f} ATR)")
    first2 = sup["rows"][:2]
    v_full = len(first2) == 2 and all(rw["wick"] >= rw["body"] and rw["wick"] >= tr.SUPPORT_WICK_ATR * rw["atr"] for rw in first2)
    v_half = len(first2) == 2 and all(rw["ok"] for rw in first2)
    v_3 = sup["count"] >= 2
    word = "destek" if not long else "direnç"
    lines.append(f"İlk 2 mum iğneli (iğne ≥ gövde): {'evet → ' + word if v_full else 'hayır'}")
    lines.append(f"İlk 2 mum iğneli (iğne ≥ ½ gövde): {'evet → ' + word if v_half else 'hayır'}")
    lines.append(f"3 mumun 2'si iğneli (iğne ≥ ½ gövde): {'evet → ' + word if v_3 else 'hayır'}")

    mode = "reclaim" if any(w in text.lower() for w in ("dönüş", "donus")) else None
    r = tr.simulate(df, i, side, tick, mode=mode)
    if mode:
        lines += ["", "<b>Dönüş varyasyonuyla değerlendirildi</b>"]
    elif r.get("mode") == "reclaim":
        lines += ["", "<b>Dönüş varyasyonu</b> (temas mumu EMA20'nin öbür tarafında kapattı)"]
    try:
        from backtest import STATUS_TR
        status_tr = STATUS_TR.get(r["status"], r["status"])
    except Exception:
        status_tr = r["status"]
    lines += ["", f"<b>Canlı ayarla sonuç:</b> {html.escape(status_tr)}"]
    if "entry" in r:
        lines.append(f"Onay {fmt(r['confirm'])}, giriş {p8(r['entry'])}, stop {p8(r['stop'])}, TP {p8(r['tp'])}")
    if "room_r" in r:
        lines.append(f"7) Önceki {'tepeye' if long else 'dibe'} mesafe: {r['room_r']:.2f}R")
    f = tr.trend_features(df, i, side, entry=r.get("entry"), risk=r.get("risk"))
    lines += ["", "<b>Temiz trend ölçüleri (testte)</b>",
              f"Bacak: {fmt(f['_s'])} → {fmt(f['_p'])}, {f['bacak_mum']} mum, {f['bacak_atr']:.1f} ATR",
              f"Gövde oranı {f['bacak_govde']:.2f} (1 = hepsi iğnesiz düz gövde) · ters mum %{100 * f['ters_mum']:.0f} · "
              f"en büyük mumun bacaktaki payı %{100 * f['tek_mum']:.0f}",
              f"EMA20–EMA100 açıklığı {f['ema_acilim']:.1f} ATR · EMA20 eğimi {f['ema_egim']:.2f} ATR/2 saat · "
              f"trend yaşı {f['trend_yasi']} mum",
              f"Düzeltme: bacağın %{100 * f['duzeltme']:.0f} kadarı geri verildi, {f['duzeltme_mum']} mum"]
    if "onu_r" in f:
        lines.append(f"Girişten önceki {'tepeye' if long else 'dibe'} mesafe: {f['onu_r']:.2f}R")
    lines.append(f"Son 12 mum iğne oranı %{100 * f['igne_orani']:.0f} (düzeltmede {('%' + format(100 * f['duz_igne'], '.0f')) if f['duz_igne'] == f['duz_igne'] else '-'}) · "
                 f"temas gövdesi {f['temas_govde_atr']:.2f} ATR · {'tepe' if long else 'dip'} bandında mum: "
                 f"0.5 ATR {f['pivot_bant_05']}, 1 ATR {f['pivot_bant_1']}")
    t = tr.TEMIZ_TEST
    lines.append(f"{ok(tr.clean_trend_ok(f, t))} Testteki 'temiz trend' şartı (gövde oranı ≥ {t['LEG_BODY_MIN']:g}, "
                 f"bacak ≥ {t['LEG_ATR_MIN']:g} ATR, en büyük mum ≤ %{100 * t['SPIKE_MAX']:.0f}, "
                 f"EMA açıklığı ≥ {t['EMA_FAN_MIN']:g} ATR)")
    a = tr.ADAY_TEST
    lines.append(f"Aday kurallar: {ok(f['ters_mum'] <= a['LEG_COUNTER_MAX'] + 1e-9)} bacakta ters mum ≤ "
                 f"%{100 * a['LEG_COUNTER_MAX']:.0f} · {ok(f['duzeltme_mum'] >= a['PULLBACK_MIN_BARS'])} düzeltme ≥ "
                 f"{a['PULLBACK_MIN_BARS']} mum · {ok(f['bacak_atr'] < a['LEG_ATR_MAX'])} bacak < {a['LEG_ATR_MAX']:g} ATR")
    lines += ["", f"Grafikte farklı görüyorsan (ör. önceki düzeltmenin {pull} hangi mum olmalı) saatini yaz, tanımı ona göre düzeltelim."]
    path = None
    try:
        import charts  # matplotlib sadece burada yüklenir
        title = f"{sym}  {tf}  {side}   temas {ts_tr:%d.%m.%Y %H:%M} TR   sonuç: {status_tr}"
        if sd.get("q") is not None:
            title += "   yapı: " + ("sağlam" if sd["ok"] else "BOZUK")
        charts.draw_inspect(df, i, side, r, sd, title, chart_path,
                            wick_bars=[rw["bar"] for rw in sup["rows"] if rw["ok"]])
        path = chart_path
    except Exception as e:
        lines.append(f"(Grafik çizilemedi: {type(e).__name__}: {e})")
    return "\n".join(lines), path
