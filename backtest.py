"""
BACKTEST - geçmiş Binance vadeli verisinde stratejiyi test eder.

Render > Shell'de çalıştır:
    nohup python backtest.py > backtest.log 2>&1 &

Seçenekler:
    --days 7                       kaç günlük veri (varsayılan 7)
    --symbols NEARUSDT,QNTUSDT     sadece bu coinler (varsayılan: hepsi)
    --tf 15m,30m                   zaman dilimleri (varsayılan: 15m)
    --rr 2.5                       TP = riskin kaç katı (varsayılan 2)
    --be 1                         1R kârda stop girişe (varsayılan kapalı)
    --ago 30                       dönemi 30 gün geriye kaydır (önceki ay)
    --compare                      6 TP/başabaş ayarını tek seferde karşılaştır

Bitince Telegram'a özet mesaj ve tüm setup'ların listesi (CSV) gelir.
"""

import argparse
import logging
import os
import pickle
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

import charts
import strategy as st
import trade_rules as tr
from exchanges import get_klines_range, get_symbols, get_tick_sizes
from telegram import send_document, send_message, send_photos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

CACHE_DIR = "/tmp/bt_cache"
WARMUP = 300  # ilk mumlarda EMA100 oturmadığı için atlanır
FETCH_THREADS = 4  # aynı anda kaç coinin verisi çekilsin
TZ = "Europe/Istanbul"

# Senin fotoğraflarla anlattığın örnekler (Türkiye saati, temas mumu)
EXAMPLES = [
    ("NEARUSDT", "15m", "2026-10-10 05:00"),
    ("QNTUSDT", "15m", "2026-10-01 23:00"),
]

STATUS_TR = {
    "no_close": "Temas mumu EMA20'nin yanlış tarafında kapattı",
    "cancel_touch": "Onaydan önce temas mumunun ucu kırıldı",
    "no_confirm": "3 mumda onay gelmedi",
    "atr": "Stop mesafesi 1.5 ATR'den büyük",
    "min_risk": "Stop mesafesi %0.3'ten küçük",
    "cancel_confirm": "Girişten önce onay mumunun ucu kırıldı",
    "no_entry": "2 mumda girişe gelmedi",
    "win": "TP",
    "loss": "Stop",
    "be": "Başabaş (girişte stop)",
    "open": "Açık (veri bitti)",
    "pending": "Beklemede (veri bitti)",
}

COND_TR = [
    ("trend", "Net trend (EMA20/50/100)"),
    ("pivot_recent", "Tepe/dip son 30 mumda"),
    ("body_break", "Gövde kapanışlı kırılım"),
    ("first_touch", "EMA20'ye ilk temas"),
    ("clean_pullback", "En fazla 2 ters mum"),
    ("touch", "İğne EMA20'ye değdi"),
    ("stoch", "Stoch şartı"),
]


# ---------------------------------------------------------------- veri
def period(days, ago):
    """Test edilen dönemin başlangıç/bitiş zamanı (ms)."""
    end_ms = int(time.time() * 1000) - ago * 86400 * 1000
    return end_ms - days * 86400 * 1000, end_ms


def load_15m(symbol, days, ago=0):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{days}_{ago}_{time.strftime('%Y%m%d%H')}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    start_ms, end_ms = period(days, ago)
    start_ms -= WARMUP * 15 * 60 * 1000
    df = get_klines_range(symbol, "15m", start_ms, end_ms)
    with open(path, "wb") as f:
        pickle.dump(df, f)
    return df


def to_30m(df15):
    """15dk mumları Binance'in 30dk mumlarıyla aynı şekilde birleştirir."""
    d = df15.copy()
    d.index = pd.to_datetime(d["timestamp"], unit="ms", utc=True)
    g = d.resample("30min", origin="epoch", label="left")
    out = pd.DataFrame({
        "Open": g["Open"].first(), "High": g["High"].max(),
        "Low": g["Low"].min(), "Close": g["Close"].last(), "n": g["Open"].count(),
    })
    out = out[out["n"] == 2].drop(columns="n")
    out["timestamp"] = (out.index - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(milliseconds=1)
    return out.reset_index(drop=True)[["timestamp", "Open", "High", "Low", "Close"]]


def prepare(df):
    df = st.add_indicators(df.reset_index(drop=True))
    return tr.add_atr(df)


def fmt_time(ts_ms):
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").tz_convert(TZ).strftime("%d.%m.%Y %H:%M")


def fmt_utc(ts_ms):
    return pd.Timestamp(ts_ms, unit="ms", tz="UTC").strftime("%H:%M")


# ---------------------------------------------------------------- test
def candidate_bars(df):
    """Hızlı ön eleme: sadece trend + temas + stoch tutan mumlar incelenir
    (asıl kontrol yine strategy.evaluate_at ile yapılır)."""
    e20, e50, e100 = df["EMA20"], df["EMA50"], df["EMA100"]
    up = (e20 > e50 * (1 + st.EMA_GAP)) & (e50 > e100 * (1 + st.EMA_GAP))
    down = (e20 < e50 * (1 - st.EMA_GAP)) & (e50 < e100 * (1 - st.EMA_GAP))
    long_c = up & (df["Low"] <= e20 * st.TOLERANCE_LONG) & (df["Stoch_K"] < st.STOCH_LONG_MAX)
    short_c = down & (df["High"] >= e20 * st.TOLERANCE_SHORT) & (df["Stoch_K"] > st.STOCH_SHORT_MIN)
    idx = np.flatnonzero((long_c | short_c).values)
    return idx[idx >= WARMUP]


def find_signals(df):
    """Temas sinyalleri (işlem ayarlarından bağımsız, bir kez hesaplanır)."""
    out = []
    for i in candidate_bars(df):
        sig = st.evaluate_at(df, i)
        if sig:
            out.append((int(i), sig["side"]))
    return out


def run_df(df, symbol, tf, tick, signals=None, with_ctx=True):
    if signals is None:
        signals = find_signals(df)
    rows = []
    next_free = 0
    ts = df["timestamp"].values
    for i, side in signals:
        if i < next_free:
            continue
        r = tr.simulate(df, i, side, tick)
        row = {
            "coin": symbol, "zaman_dilimi": tf, "yon": side,
            "temas": fmt_time(ts[i]), "temas_utc": fmt_utc(ts[i]), "durum": r["status"],
            "sonuc": STATUS_TR[r["status"]],
        }
        if "confirm" in r:
            row.update(onay=fmt_time(ts[r["confirm"]]), giris=r["entry"], stop=r["stop"],
                       tp=r["tp"], atr=r["atr"], risk_atr=r["risk"] / r["atr"])
        if "entry_bar" in r:
            row.update(giris_zamani=fmt_time(ts[r["entry_bar"]]), dolum=r["fill"],
                       risk_yuzde=100 * r["risk"] / r["fill"])
            if r["status"] in ("win", "loss", "be"):
                row.update(cikis_zamani=fmt_time(ts[r["exit_bar"]]), cikis=r["exit"],
                           R_brut=round(r["r_gross"], 3), R_net=round(r["r_net"], 3),
                           dolar=round(r["r_net"] * tr.RISK_USD, 2),
                           _exit_ts=int(ts[r["exit_bar"]]))
                if with_ctx:
                    row["_ctx"] = charts.context(df, r)
                next_free = r["exit_bar"] + 1
            else:
                next_free = len(df)
        rows.append(row)
    return rows


def explain_example(df, symbol, tf, tick, when):
    """Örnek saati hem Türkiye saati hem UTC olarak dener
    (TradingView kriptoda varsayılan olarak UTC gösterir)."""
    out = []
    for tz_name, tz in (("UTC", "UTC"), ("TR saati", TZ)):
        ms = int(pd.Timestamp(when, tz=tz).tz_convert("UTC").value // 10**6)
        hits = np.flatnonzero(df["timestamp"].values == ms)
        if len(hits) == 0:
            out.append(f"• {symbol} {tf} {when} ({tz_name}): bu tarih veride yok")
            continue
        i = int(hits[0])
        d = st.diagnose(df, i)
        ok = [k for k, _ in COND_TR if d.get(k, False)]
        lines = [f"• <b>{symbol} {tf} {when} ({tz_name})</b>"]
        if len(ok) == len(COND_TR):
            r = tr.simulate(df, i, d["side"], tick)
            lines.append(f"   ✅ Tüm temas şartları tuttu → {d['side']}: {STATUS_TR[r['status']]}")
            if "confirm" in r:
                lines.append(f"   Onay {fmt_time(df['timestamp'].iloc[r['confirm']])}, "
                             f"giriş {r['entry']:g}, stop {r['stop']:g}, TP {r['tp']:g}")
        else:
            failed = [label for k, label in COND_TR if k in d and not d[k]]
            lines.append("   ❌ " + ", ".join(failed))
        out.append("\n".join(lines))
    return "\n".join(out)


# ---------------------------------------------------------------- rapor
def stats(trades):
    if trades.empty:
        return None
    t = trades.sort_values("_exit_ts")
    eq = t["R_net"].cumsum()
    dd = (eq - eq.cummax()).min()
    streak = best = 0
    for lost in (t["durum"] == "loss"):
        streak = streak + 1 if lost else 0
        best = max(best, streak)
    return {
        "n": len(t), "wins": int((t["durum"] == "win").sum()),
        "be": int((t["durum"] == "be").sum()),
        "wr": 100 * (t["durum"] == "win").mean(),
        "gross": t["R_brut"].sum(), "net": t["R_net"].sum(),
        "avg": t["R_net"].mean(), "dd": dd, "streak": best,
        "risk_med": t["risk_yuzde"].median(),
    }


def usd(r):
    return f"{r * tr.RISK_USD:+,.0f}$".replace(",", ".")


def line(label, s):
    if not s:
        return f"{label}: işlem yok"
    return (f"{label}: {s['n']} işlem, %{s['wr']:.0f} kazanma, "
            f"{s['net']:+.1f}R ({usd(s['net'])})")


def build_report(df_all, period_txt, n_coins, minutes, examples_txt):
    trades = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
    s = stats(trades)
    funnel = df_all["durum"].value_counts() if not df_all.empty else pd.Series(dtype=int)

    def c(*keys):
        return int(sum(funnel.get(k, 0) for k in keys))

    be_txt = f", başabaş +{tr.BE_TRIGGER:g}R" if tr.BE_TRIGGER > 0 else ""
    msg = [f"📊 <b>BACKTEST SONUCU (TP 1:{tr.RR:g}{be_txt})</b>",
           f"{period_txt}, {n_coins} coin ({minutes:.0f} dk sürdü)", ""]
    msg.append("<b>Huni</b>")
    msg.append(f"Temas sinyali: {len(df_all)}")
    msg.append(f"  ↳ EMA20 yanlış tarafta kapanış: {c('no_close')}")
    msg.append(f"  ↳ Onaydan önce iptal: {c('cancel_touch')}")
    msg.append(f"  ↳ 3 mumda onay yok: {c('no_confirm')}")
    msg.append(f"  ↳ ATR filtresine takıldı: {c('atr')}")
    msg.append(f"  ↳ Stop %{tr.MIN_RISK_PCT:g}'ten dar: {c('min_risk')}")
    msg.append(f"  ↳ Girişten önce iptal: {c('cancel_confirm')}")
    msg.append(f"  ↳ 2 mumda girişe gelmedi: {c('no_entry')}")
    msg.append(f"İşleme girildi: {c('win', 'loss', 'be', 'open')} (açık: {c('open')})")
    msg.append("")
    if s:
        be = 100 / (1 + tr.RR)
        msg.append("<b>Sonuç</b>")
        bep = f" | Başabaş: {s['be']}" if tr.BE_TRIGGER > 0 else ""
        msg.append(f"İşlem: {s['n']} | TP: {s['wins']} | Stop: {s['n'] - s['wins'] - s['be']}{bep}")
        msg.append(f"Kazanma oranı: %{s['wr']:.1f} (1:{tr.RR:g} için başabaş ~%{be:.0f})")
        msg.append(f"1R = {tr.RISK_USD:g}$")
        msg.append(f"Toplam (komisyonsuz): {s['gross']:+.1f}R ({usd(s['gross'])})")
        msg.append(f"Toplam (komisyonlu): <b>{s['net']:+.1f}R ({usd(s['net'])})</b>")
        msg.append(f"İşlem başı ortalama: {s['avg']:+.2f}R ({usd(s['avg'])})")
        msg.append(f"En büyük düşüş: {s['dd']:.1f}R ({usd(s['dd'])})")
        msg.append(f"En uzun stop serisi: {s['streak']}")
        msg.append(f"Ortalama stop mesafesi: %{s['risk_med']:.2f}")
        msg.append("")
        for tf in sorted(trades["zaman_dilimi"].unique()):
            msg.append(line(tf, stats(trades[trades["zaman_dilimi"] == tf])))
        for side in ("LONG", "SHORT"):
            msg.append(line(side, stats(trades[trades["yon"] == side])))
    else:
        msg.append("Hiç işlem oluşmadı.")
    if examples_txt:
        msg += ["", "<b>Senin örneklerin</b>"] + examples_txt
    return "\n".join(msg)


COMPARE_CONFIGS = [(2.0, 0.0), (2.0, 1.0), (2.5, 0.0), (2.5, 1.0), (3.0, 0.0), (3.0, 1.0)]


def cfg_name(rr, be):
    return f"1:{rr:g}" + (f" + başabaş {be:g}R" if be > 0 else "")


def build_compare(results, period_txt, n_coins, minutes):
    msg = ["📊 <b>KARŞILAŞTIRMA</b>", f"{period_txt}, {n_coins} coin ({minutes:.0f} dk sürdü)",
           f"1R = {tr.RISK_USD:g}$, komisyon dahil", ""]
    scored = []
    for (rr, be), df_all in results.items():
        t = df_all[df_all["durum"].isin(["win", "loss", "be"])] if not df_all.empty else df_all
        scored.append(((rr, be), stats(t)))
    best = max((x for x in scored if x[1]), key=lambda x: x[1]["net"], default=None)
    for (rr, be), s in scored:
        star = " ⭐" if best and (rr, be) == best[0] else ""
        if not s:
            msg.append(f"<b>{cfg_name(rr, be)}</b>: işlem yok")
            continue
        bep = f", {s['be']} başabaş" if be > 0 else ""
        msg.append(f"<b>{cfg_name(rr, be)}</b>{star}")
        msg.append(f"  {s['n']} işlem, %{s['wr']:.0f} TP{bep}")
        msg.append(f"  <b>{s['net']:+.1f}R ({usd(s['net'])})</b>, düşüş {s['dd']:.1f}R, "
                   f"en uzun stop serisi {s['streak']}")
    return "\n".join(msg)


# ---------------------------------------------------------------- ana
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tf", default="15m")
    ap.add_argument("--rr", type=float, default=tr.RR)
    ap.add_argument("--be", type=float, default=0.0, help="başabaş tetik (R), 0 = kapalı")
    ap.add_argument("--ago", type=int, default=0, help="dönemi kaç gün geriye kaydır (önceki ay için = days)")
    ap.add_argument("--compare", action="store_true", help="tüm TP/başabaş ayarlarını karşılaştır")
    args = ap.parse_args()
    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]
    tr.RR = args.rr
    tr.BE_TRIGGER = args.be
    configs = COMPARE_CONFIGS if args.compare else [(args.rr, args.be)]
    p0, p1 = period(args.days, args.ago)
    period_txt = (f"{pd.Timestamp(p0, unit='ms', tz='UTC').tz_convert(TZ):%d.%m.%Y} – "
                  f"{pd.Timestamp(p1, unit='ms', tz='UTC').tz_convert(TZ):%d.%m.%Y} ({args.days} gün)")

    t0 = time.time()
    ticks = get_tick_sizes()
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or get_symbols())
    log.info("Backtest başlıyor: %d coin, %d gün, %s, %d ayar", len(symbols), args.days, tfs, len(configs))
    what = ("6 farklı TP/başabaş ayarı karşılaştırılacak" if args.compare else
            f"TP 1:{tr.RR:g}" + (f", başabaş +{tr.BE_TRIGGER:g}R" if tr.BE_TRIGGER > 0 else ""))
    send_message(f"⏳ Backtest başladı: {len(symbols)} coin, {period_txt}, {what}. "
                 f"Bitince sonuçlar buraya gelecek.")

    def fetch(symbol):
        try:
            return load_15m(symbol, args.days, args.ago)
        except Exception as e:
            log.error("%s verisi alınamadı: %s", symbol, e)
            return None

    results = {cfg: [] for cfg in configs}
    examples_txt = []
    with ThreadPoolExecutor(max_workers=FETCH_THREADS) as ex:
        futures = {ex.submit(fetch, sym): sym for sym in symbols}
        for n, fut in enumerate(as_completed(futures), 1):
            symbol = futures[fut]
            df15 = fut.result()
            futures[fut] = None
            try:
                if df15 is None or len(df15) < WARMUP + 50:
                    continue
                frames = {"15m": df15, "30m": to_30m(df15)}
                tick = ticks.get(symbol, 0.0)
                for tf in tfs:
                    df = prepare(frames[tf])
                    signals = find_signals(df)
                    for rr, be in configs:
                        tr.RR, tr.BE_TRIGGER = rr, be
                        results[(rr, be)] += run_df(df, symbol, tf, tick, signals,
                                                    with_ctx=not args.compare)
                    if not args.compare:
                        for ex_sym, ex_tf, ex_when in EXAMPLES:
                            if ex_sym == symbol and ex_tf == tf:
                                examples_txt.append(explain_example(df, symbol, tf, tick, ex_when))
            except Exception as e:
                log.error("%s atlandı: %s", symbol, e)
            if n % 25 == 0:
                el = time.time() - t0
                log.info("%d/%d coin bitti (%.1f dk, kalan ~%.1f dk)", n, len(symbols),
                         el / 60, el / n * (len(symbols) - n) / 60)

    minutes = (time.time() - t0) / 60
    if args.compare:
        frames_all = {cfg: pd.DataFrame(rows) for cfg, rows in results.items()}
        report = build_compare(frames_all, period_txt, len(symbols), minutes)
        log.info("\n%s", report)
        send_message(report)
        parts = []
        for (rr, be), d in frames_all.items():
            if not d.empty:
                parts.append(d.assign(ayar=cfg_name(rr, be)))
        if parts:
            out = pd.concat(parts)
            path = f"karsilastirma_{time.strftime('%Y%m%d_%H%M')}.csv"
            out.drop(columns=[c for c in out.columns if c.startswith("_")]).to_csv(
                path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
            send_document(path, "Tüm ayarların işlemleri ('ayar' sütununa göre filtrele)")
        return

    tr.RR, tr.BE_TRIGGER = configs[0]
    rows = results[configs[0]]
    df_all = pd.DataFrame(rows)
    report = build_report(df_all, period_txt, len(symbols), minutes, examples_txt)
    log.info("\n%s", report)
    send_message(report)

    if not df_all.empty:
        path = f"backtest_{time.strftime('%Y%m%d_%H%M')}.csv"
        df_all.drop(columns=[c for c in df_all.columns if c.startswith("_")]).to_csv(
            path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        send_document(path, "Tüm setup'lar ve işlemler (Excel/Sheets ile açılır)")

        trades = df_all[df_all["durum"].isin(["win", "loss", "be"])].sort_values("_exit_ts")
        recs = trades.to_dict("records")
        if recs:
            try:
                folder = "/tmp/bt_charts"
                os.makedirs(folder, exist_ok=True)
                send_photos(charts.make_samples(recs, folder),
                            "Örnek işlemler: son 5 TP ve son 5 stop")
                pdf_recs = recs[-200:]
                pdf_path = f"backtest_grafikler_{time.strftime('%Y%m%d_%H%M')}.pdf"
                charts.make_pdf(pdf_recs, pdf_path)
                note = "" if len(recs) <= 200 else f" (son 200 / toplam {len(recs)})"
                send_document(pdf_path, f"Tüm işlemlerin grafikleri{note}, her sayfada bir işlem")
            except Exception as e:
                log.exception("Grafikler oluşturulamadı: %s", e)
                send_message(f"⚠️ Grafikler oluşturulamadı: {e}")


if __name__ == "__main__":
    main()
