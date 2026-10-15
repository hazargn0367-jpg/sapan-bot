"""İkinci strateji adayı: trend takibi (Donchian kırılımı), sadece backtest.
Kullanıcı 16.10 00:54 "kodla" (araştırma: "Catching Crypto Trends", SSRN 5209907 — birden çok Donchian uzunluğu,
oynaklığa göre pozisyon, en likit coinler).

Kurallar (her N için ayrı alt sistem, risk 1/len(N) R):
- Giriş: mum kapanışı önceki N mumun en yükseğinin üstünde → sonraki mumun açılışında LONG (SHORT tersi).
- Stop: giriş - K x ATR(20) (R = bu mesafe). Takip eden stop: girişten beri en yüksek - K x ATR (sadece yukarı gider).
  Stop emri: mum stop seviyesinin altına inerse stopta (açılış zaten altındaysa açılışta) çıkılır.
- Maliyet: taraf başına %0.05 komisyon + %0.02 kayma, günde %0.03 funding (pozisyon büyüklüğü üzerinden).
- Dönem sonunda açık pozisyon son kapanıştan değerlenir (durum "open").
Sonuç R cinsinden (1R = canlıdaki gibi 15$)."""
import logging
import time

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

WARM_DAYS = 130          # 100 günlük Donchian + ATR için ısınma
ATR_N = 20
COST_SIDE = 0.0007       # komisyon %0.05 + kayma %0.02
FUNDING_DAY = 0.0003     # günde ~%0.03 (8 saatte %0.01)
TOP = 60                 # yüklenen coin sayısı (ayarlar 30 / 60 ile süzer)

CONFIGS = [
    dict(ad="Günlük 20/50/100, LONG+SHORT, en likit 30", tf=1440, ns=(20, 50, 100), k=3.0, sides=("LONG", "SHORT"), top=30),
    dict(ad="Günlük 20/50/100, sadece LONG, en likit 30", tf=1440, ns=(20, 50, 100), k=3.0, sides=("LONG",), top=30),
    dict(ad="Günlük 20, LONG+SHORT, en likit 30", tf=1440, ns=(20,), k=3.0, sides=("LONG", "SHORT"), top=30),
    dict(ad="Günlük 20/50/100, LONG+SHORT, en likit 60", tf=1440, ns=(20, 50, 100), k=3.0, sides=("LONG", "SHORT"), top=60),
    dict(ad="4 saatlik 20/50/100, LONG+SHORT, en likit 30", tf=240, ns=(20, 50, 100), k=3.0, sides=("LONG", "SHORT"), top=30),
    dict(ad="Günlük 20/50/100, LONG+SHORT, en likit 30, en fazla 5R açık risk", tf=1440, ns=(20, 50, 100), k=3.0,
         sides=("LONG", "SHORT"), top=30, max_risk=5.0),
]


def atr(h, l, c, n=ATR_N):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(np.abs(h - pc), np.abs(l - pc)))
    return pd.Series(tr).ewm(alpha=1 / n, adjust=False).mean().values


def sim_coin(df, cfg, p0, p1, symbol, rank):
    """Bir coinde bir ayarın bütün işlemleri."""
    T = df["timestamp"].values
    O, H, L, C = (df[c].values for c in ("Open", "High", "Low", "Close"))
    n = len(df)
    A = atr(H, L, C)
    bar_days = cfg["tf"] / 1440
    w = 1.0 / len(cfg["ns"])
    out = []
    for N in cfg["ns"]:
        hh = pd.Series(H).rolling(N).max().shift(1).values   # i. mumdan önceki N mumun en yükseği
        ll = pd.Series(L).rolling(N).min().shift(1).values
        pos = None
        for i in range(max(N, ATR_N) + 2, n):
            if pos is not None:
                side, entry, stop, rdist, ext, ei = pos
                # takip eden stop: bir önceki muma kadarki uç noktadan K x ATR
                if side == "LONG":
                    stop = max(stop, ext - cfg["k"] * A[i - 1])
                    hit = L[i] <= stop
                    px = min(O[i], stop)
                else:
                    stop = min(stop, ext + cfg["k"] * A[i - 1])
                    hit = H[i] >= stop
                    px = max(O[i], stop)
                if hit:
                    out.append(_close(pos, px, i, T, w, bar_days, symbol, rank, N, "stop"))
                    pos = None
                    continue   # aynı mumda yeniden giriş yok
                else:
                    ext = max(ext, H[i]) if side == "LONG" else min(ext, L[i])
                    pos = (side, entry, stop, rdist, ext, ei)
                    continue
            # giriş sinyali: bir önceki mumun kapanışı kırılım; giriş bu mumun açılışında, dönem içinde
            if not (p0 <= T[i] < p1) or np.isnan(hh[i - 1]) or A[i - 1] <= 0:
                continue
            side = None
            if "LONG" in cfg["sides"] and C[i - 1] > hh[i - 1]:
                side = "LONG"
            elif "SHORT" in cfg["sides"] and C[i - 1] < ll[i - 1]:
                side = "SHORT"
            if side is None:
                continue
            entry = O[i]
            rdist = cfg["k"] * A[i - 1]
            if rdist <= 0 or rdist >= entry * 0.9:
                continue
            stop = entry - rdist if side == "LONG" else entry + rdist
            pos = (side, entry, stop, rdist, H[i] if side == "LONG" else L[i], i)
            # giriş mumunda stop (en kötü durum: önce stop)
            if (L[i] <= stop) if side == "LONG" else (H[i] >= stop):
                out.append(_close(pos, stop, i, T, w, bar_days, symbol, rank, N, "stop"))
                pos = None
        if pos is not None:
            out.append(_close(pos, C[n - 1], n - 1, T, w, bar_days, symbol, rank, N, "open"))
    return out


def _close(pos, px, i, T, w, bar_days, symbol, rank, N, how):
    side, entry, stop, rdist, ext, ei = pos
    gross = ((px - entry) if side == "LONG" else (entry - px)) / rdist
    days = max(1, i - ei + 1) * bar_days
    cost = (COST_SIDE * (entry + px) + FUNDING_DAY * days * entry) / rdist
    r = (gross - cost) * w
    return {"coin": symbol, "hacim_sirasi": rank, "N": N, "yon": side, "giris_ts": int(T[ei]), "cikis_ts": int(T[i]),
            "giris": entry, "cikis": px, "stop_mesafe_pct": round(100 * rdist / entry, 2), "gun": round(days, 1),
            "R_brut": round(gross * w, 4), "R_net": round(r, 4), "durum": "open" if how == "open" else
            ("win" if r > 0 else "loss"), "agirlik": w}


def apply_max_risk(rows, max_risk):
    """Giriş sırasıyla: açık risk (ağırlık toplamı) sınırı aşacaksa işlem alınmaz."""
    rows = sorted(rows, key=lambda r: (r["giris_ts"], r["hacim_sirasi"]))
    open_ = []   # (cikis_ts, w)
    kept = []
    for r in rows:
        open_ = [(e, w) for e, w in open_ if e > r["giris_ts"]]
        if sum(w for _, w in open_) + r["agirlik"] > max_risk + 1e-9:
            continue
        open_.append((r["cikis_ts"] if r["durum"] != "open" else 2 ** 62, r["agirlik"]))
        kept.append(r)
    return kept


def summarize(name, rows, p0, days, tz):
    if not rows:
        return f"<b>{name}</b>\n  işlem yok"
    d = pd.DataFrame(rows).sort_values("cikis_ts")
    eq = d["R_net"].cumsum()
    dd = (eq - eq.cummax()).min()
    closed = d[d["durum"] != "open"]
    win = (closed["R_net"] > 0).mean() * 100 if len(closed) else 0
    aw = closed.loc[closed["R_net"] > 0, "R_net"].mean() / closed.loc[closed["R_net"] > 0, "agirlik"].mean() if (closed["R_net"] > 0).any() else 0
    al = closed.loc[closed["R_net"] <= 0, "R_net"].mean() / closed.loc[closed["R_net"] <= 0, "agirlik"].mean() if (closed["R_net"] <= 0).any() else 0
    m = pd.to_datetime(d["giris_ts"], unit="ms", utc=True).dt.tz_convert(tz).dt.strftime("%m.%y")
    monthly = d.groupby(m, sort=False)["R_net"].sum()
    mtxt = " ".join(f"{k}:{v:+.1f}" for k, v in monthly.items())
    tot = d["R_net"].sum()
    return (f"<b>{name}</b>\n  {len(d)} işlem (ayda ~{len(d) / (days / 30):.0f}), kazanan %{win:.0f}, "
            f"ort. kazanç {aw:+.1f}R / kayıp {al:+.1f}R (tam boy), açık {int((d['durum'] == 'open').sum())}\n"
            f"  {'🟢' if tot > 0 else '🔴'} <b>{tot:+.1f}R</b> · en büyük düşüş {dd:.1f}R\n  aylar: {mtxt}")


def run(symbols, args, load, period, send_message, send_document, tz):
    """symbols: hacme göre sıralı (büyükten küçüğe). load(symbol, days, ago) -> 15dk mumlar."""
    import backtest as bt
    t0 = time.time()
    p0, p1 = period(args.days, args.ago)
    syms = [s for s in symbols if not s.startswith(("USDC", "FDUSD", "TUSD", "BUSD"))][:TOP]
    period_txt = (f"{pd.Timestamp(p0, unit='ms', tz='UTC').tz_convert(tz):%d.%m.%Y} – "
                  f"{pd.Timestamp(p1, unit='ms', tz='UTC').tz_convert(tz):%d.%m.%Y} ({args.days} gün)")
    send_message(f"⏳ Trend takibi testi başladı: en likit {len(syms)} coin, {period_txt}, {len(CONFIGS)} ayar. "
                 f"Bitince sonuçlar buraya gelecek.")
    rows = {c["ad"]: [] for c in CONFIGS}
    n_ok = 0
    for k, sym in enumerate(syms):
        rank = k + 1
        try:
            df15 = load(sym, args.days + WARM_DAYS, args.ago)
        except Exception as e:
            log.error("%s verisi alınamadı: %s", sym, e)
            continue
        if df15 is None or len(df15) < 96 * (WARM_DAYS // 2):
            continue
        n_ok += 1
        frames = {}
        for cfg in CONFIGS:
            if rank > cfg["top"]:
                continue
            if cfg["tf"] not in frames:
                frames[cfg["tf"]] = bt.resample_tf(df15, cfg["tf"])
            rows[cfg["ad"]] += sim_coin(frames[cfg["tf"]], cfg, p0, p1, sym, rank)
        del df15, frames
        if (k + 1) % 10 == 0:
            log.info("trend: %d/%d coin bitti (%.1f dk)", k + 1, len(syms), (time.time() - t0) / 60)
    for cfg in CONFIGS:
        if cfg.get("max_risk"):
            rows[cfg["ad"]] = apply_max_risk(rows[cfg["ad"]], cfg["max_risk"])
    msg = [f"📈 <b>TREND TAKİBİ (Donchian kırılımı)</b>", f"{period_txt}, {n_ok} coin, 1R = 15$ "
           f"(komisyon + kayma + funding dahil; 20/50/100 = üç alt sistem, her biri 1/3 R)", ""]
    for cfg in CONFIGS:
        msg.append(summarize(cfg["ad"], rows[cfg["ad"]], p0, args.days, tz))
    msg.append(f"\n⏱ {(time.time() - t0) / 60:.1f} dk")
    report = "\n".join(msg)
    log.info("\n%s", report)
    # Telegram 4096 sınırı
    cur = ""
    for part in report.split("\n\n"):
        if len(cur) + len(part) + 2 > 3800:
            send_message(cur)
            cur = ""
        cur += ("\n\n" if cur else "") + part
    if cur:
        send_message(cur)
    parts = [pd.DataFrame(r).assign(ayar=name) for name, r in rows.items() if r]
    if parts:
        out = pd.concat(parts)
        for c in ("giris_ts", "cikis_ts"):
            out[c.replace("_ts", "_zamani")] = pd.to_datetime(out[c], unit="ms", utc=True).dt.tz_convert(tz).dt.strftime("%d.%m.%Y %H:%M")
        path = f"trend_{time.strftime('%Y%m%d_%H%M')}.csv"
        out.to_csv(path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        send_document(path, "Trend takibi işlemleri ('ayar' sütununa göre filtrele)")
