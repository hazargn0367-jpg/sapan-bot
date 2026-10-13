"""
BACKTEST - geçmiş Binance vadeli verisinde stratejiyi test eder.

Render > Shell'de çalıştır:
    nohup python backtest.py > backtest.log 2>&1 &

Seçenekler:
    --days 30                      kaç günlük veri (varsayılan 30)
    --symbols NEARUSDT,QNTUSDT     sadece bu coinler (varsayılan: hepsi)
    --tf 15m,30m                   zaman dilimleri (varsayılan: 15m)

Bitince Telegram'a özet mesaj ve tüm setup'ların listesi (CSV) gelir.
"""

import argparse
import logging
import os
import pickle
import time

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
    "cancel_confirm": "Girişten önce onay mumunun ucu kırıldı",
    "no_entry": "2 mumda girişe gelmedi",
    "win": "TP",
    "loss": "Stop",
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
def load_15m(symbol, days):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"{symbol}_{days}_{time.strftime('%Y%m%d%H')}.pkl")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return pickle.load(f)
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - days * 86400 * 1000 - WARMUP * 15 * 60 * 1000
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


def run_df(df, symbol, tf, tick):
    rows = []
    next_free = 0
    ts = df["timestamp"].values
    for i in candidate_bars(df):
        if i < next_free:
            continue
        sig = st.evaluate_at(df, i)
        if not sig:
            continue
        r = tr.simulate(df, i, sig["side"], tick)
        row = {
            "coin": symbol, "zaman_dilimi": tf, "yon": sig["side"],
            "temas": fmt_time(ts[i]), "durum": r["status"],
            "sonuc": STATUS_TR[r["status"]],
        }
        if "confirm" in r:
            row.update(onay=fmt_time(ts[r["confirm"]]), giris=r["entry"], stop=r["stop"],
                       tp=r["tp"], atr=r["atr"], risk_atr=r["risk"] / r["atr"])
        if "entry_bar" in r:
            row.update(giris_zamani=fmt_time(ts[r["entry_bar"]]), dolum=r["fill"],
                       risk_yuzde=100 * r["risk"] / r["fill"])
            if r["status"] in ("win", "loss"):
                row.update(cikis_zamani=fmt_time(ts[r["exit_bar"]]), cikis=r["exit"],
                           R_brut=round(r["r_gross"], 3), R_net=round(r["r_net"], 3),
                           dolar=round(r["r_net"] * tr.RISK_USD, 2),
                           _exit_ts=int(ts[r["exit_bar"]]), _ctx=charts.context(df, r))
                next_free = r["exit_bar"] + 1
            else:
                next_free = len(df)
        rows.append(row)
    return rows


def explain_example(df, symbol, tf, tick, when):
    t = pd.Timestamp(when, tz=TZ).tz_convert("UTC")
    ms = int(t.value // 10**6)
    hits = np.flatnonzero(df["timestamp"].values == ms)
    if len(hits) == 0:
        return f"• {symbol} {tf} {when}: bu tarih veride yok"
    i = int(hits[0])
    d = st.diagnose(df, i)
    lines = [f"• <b>{symbol} {tf} {when}</b>"]
    for key, label in COND_TR:
        if key in d:
            lines.append(f"   {'✅' if d[key] else '❌'} {label}")
    if all(d.get(k, False) for k, _ in COND_TR):
        r = tr.simulate(df, i, d["side"], tick)
        lines.append(f"   → {d['side']}: {STATUS_TR[r['status']]}")
        if "confirm" in r:
            lines.append(f"   Onay {fmt_time(df['timestamp'].iloc[r['confirm']])}, "
                         f"giriş {r['entry']:g}, stop {r['stop']:g}, TP {r['tp']:g}")
    return "\n".join(lines)


# ---------------------------------------------------------------- rapor
def stats(trades):
    if trades.empty:
        return None
    t = trades.sort_values("_exit_ts")
    eq = t["R_net"].cumsum()
    dd = (eq - eq.cummax()).min()
    streak = best = 0
    for won in (t["durum"] == "win"):
        streak = 0 if won else streak + 1
        best = max(best, streak)
    return {
        "n": len(t), "wins": int((t["durum"] == "win").sum()),
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


def build_report(df_all, days, n_coins, minutes, examples_txt):
    trades = df_all[df_all["durum"].isin(["win", "loss"])] if not df_all.empty else df_all
    s = stats(trades)
    funnel = df_all["durum"].value_counts() if not df_all.empty else pd.Series(dtype=int)

    def c(*keys):
        return int(sum(funnel.get(k, 0) for k in keys))

    msg = [f"📊 <b>BACKTEST SONUCU</b>",
           f"Son {days} gün, {n_coins} coin ({minutes:.0f} dk sürdü)", ""]
    msg.append("<b>Huni</b>")
    msg.append(f"Temas sinyali: {len(df_all)}")
    msg.append(f"  ↳ EMA20 yanlış tarafta kapanış: {c('no_close')}")
    msg.append(f"  ↳ Onaydan önce iptal: {c('cancel_touch')}")
    msg.append(f"  ↳ 3 mumda onay yok: {c('no_confirm')}")
    msg.append(f"  ↳ ATR filtresine takıldı: {c('atr')}")
    msg.append(f"  ↳ Girişten önce iptal: {c('cancel_confirm')}")
    msg.append(f"  ↳ 2 mumda girişe gelmedi: {c('no_entry')}")
    msg.append(f"İşleme girildi: {c('win', 'loss', 'open')} (açık: {c('open')})")
    msg.append("")
    if s:
        be = 100 / (1 + tr.RR)
        msg.append("<b>Sonuç</b>")
        msg.append(f"İşlem: {s['n']} | TP: {s['wins']} | Stop: {s['n'] - s['wins']}")
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


# ---------------------------------------------------------------- ana
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--tf", default="15m")
    args = ap.parse_args()
    tfs = [t.strip() for t in args.tf.split(",") if t.strip()]

    t0 = time.time()
    ticks = get_tick_sizes()
    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               or get_symbols())
    log.info("Backtest başlıyor: %d coin, %d gün, %s", len(symbols), args.days, tfs)
    send_message(f"⏳ Backtest başladı: {len(symbols)} coin, son {args.days} gün. "
                 f"Bitince sonuçlar buraya gelecek.")

    rows, examples_txt = [], []
    for n, symbol in enumerate(symbols, 1):
        try:
            df15 = load_15m(symbol, args.days)
            if len(df15) < WARMUP + 50:
                continue
            frames = {"15m": df15, "30m": to_30m(df15)}
            for tf in tfs:
                df = prepare(frames[tf])
                rows += run_df(df, symbol, tf, ticks.get(symbol, 0.0))
                for ex_sym, ex_tf, ex_when in EXAMPLES:
                    if ex_sym == symbol and ex_tf == tf:
                        examples_txt.append(explain_example(df, symbol, tf, ticks.get(symbol, 0.0), ex_when))
        except Exception as e:
            log.error("%s atlandı: %s", symbol, e)
        if n % 25 == 0:
            el = time.time() - t0
            log.info("%d/%d coin bitti (%.1f dk, kalan ~%.1f dk)", n, len(symbols),
                     el / 60, el / n * (len(symbols) - n) / 60)

    df_all = pd.DataFrame(rows)
    report = build_report(df_all, args.days, len(symbols), (time.time() - t0) / 60, examples_txt)
    log.info("\n%s", report)
    send_message(report)

    if not df_all.empty:
        path = f"backtest_{time.strftime('%Y%m%d_%H%M')}.csv"
        df_all.drop(columns=[c for c in df_all.columns if c.startswith("_")]).to_csv(
            path, index=False, sep=";", decimal=",", encoding="utf-8-sig")
        send_document(path, "Tüm setup'lar ve işlemler (Excel/Sheets ile açılır)")

        trades = df_all[df_all["durum"].isin(["win", "loss"])].sort_values("_exit_ts")
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
