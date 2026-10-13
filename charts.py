"""
Backtest işlemlerini TradingView benzeri grafik olarak çizer.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
import pandas as pd  # noqa: E402

BG, GRID, TXT = "#131722", "#2a2e39", "#d1d4dc"
UP, DOWN = "#26a69a", "#ef5350"
EMA_COLORS = {"EMA20": "#f23645", "EMA50": "#ff9800", "EMA100": "#4dd0e1"}
TZ = "Europe/Istanbul"
BARS_BEFORE = 30
BARS_AFTER = 6


def context(df, r):
    """İşlemin etrafındaki mumları saklar (sonradan çizmek için)."""
    lo = max(0, r["touch"] - BARS_BEFORE)
    hi = min(len(df), r.get("exit_bar", r["touch"] + 6) + BARS_AFTER)
    cols = ["timestamp", "Open", "High", "Low", "Close", "EMA20", "EMA50", "EMA100", "Stoch_K"]
    ctx = df.iloc[lo:hi][cols].reset_index(drop=True)
    rel = {k: r[k] - lo for k in ("touch", "confirm", "entry_bar", "exit_bar") if k in r}
    return ctx, rel


def draw(trade, path=None, pdf=None):
    ctx, rel = trade["_ctx"]
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(11, 6.2), sharex=True, gridspec_kw={"height_ratios": [3.2, 1]}
    )
    fig.patch.set_facecolor(BG)
    for a in (ax, ax2):
        a.set_facecolor(BG)
        a.grid(color=GRID, linewidth=0.6)
        a.tick_params(colors=TXT, labelsize=8)
        for s in a.spines.values():
            s.set_color(GRID)
        a.yaxis.tick_right()

    x = range(len(ctx))
    # Mumlar
    for i, c in ctx.iterrows():
        col = UP if c["Close"] >= c["Open"] else DOWN
        ax.vlines(i, c["Low"], c["High"], color=col, linewidth=0.9)
        lo, hi = sorted((c["Open"], c["Close"]))
        ax.add_patch(Rectangle((i - 0.32, lo), 0.64, max(hi - lo, 1e-12), color=col))
    for name, color in EMA_COLORS.items():
        ax.plot(x, ctx[name], color=color, linewidth=1.1, label=name)

    # Pozisyon kutusu (TradingView'daki gibi)
    # Henüz girilmemiş setup'ta kutu onaydan sonraki mumdan başlar, giriş süresi (2 mum) boyunca çizilir
    e0 = rel.get("entry_bar", rel["confirm"] + 1)
    e1 = rel.get("exit_bar", len(ctx) - 1 if "entry_bar" in rel else e0 + 1) + 0.5
    entry, stop, tp = trade["giris"], trade["stop"], trade["tp"]
    ax.add_patch(Rectangle((e0 - 0.5, min(entry, tp)), e1 - e0 + 0.5, abs(tp - entry),
                           color=UP, alpha=0.18))
    ax.add_patch(Rectangle((e0 - 0.5, min(entry, stop)), e1 - e0 + 0.5, abs(entry - stop),
                           color=DOWN, alpha=0.18))
    for y, col, lbl in ((entry, TXT, "Giriş"), (stop, DOWN, "Stop"), (tp, UP, "TP")):
        ax.hlines(y, e0 - 0.5, e1, color=col, linewidth=0.9, linestyles="--")
        ax.text(e1 + 0.2, y, f"{lbl} {y:g}", color=col, fontsize=7.5, va="center")

    # Fiyat eksenini mumlara ve işleme odakla (uzaktaki EMA'lar grafiği sıkıştırmasın)
    y_lo = min(ctx["Low"].min(), stop, tp)
    y_hi = max(ctx["High"].max(), stop, tp)
    rng = y_hi - y_lo
    ax.set_ylim(y_lo - rng * 0.08, y_hi + rng * 0.08)

    # İşaretler
    long = trade["yon"] == "LONG"
    pad = rng * 0.05

    def mark(bar, text, color, below):
        c = ctx.iloc[bar]
        y = c["Low"] - pad if below else c["High"] + pad
        ax.annotate(text, (bar, c["Low"] if below else c["High"]), (bar, y),
                    color=color, fontsize=8, ha="center", va="top" if below else "bottom",
                    fontweight="bold", arrowprops=dict(arrowstyle="-", color=color, lw=0.8))

    mark(rel["touch"], "Temas", "#ffeb3b", below=long)
    mark(rel["confirm"], "Onay", "#ce93d8", below=not long)
    if "exit_bar" in rel:
        col = {"win": UP, "be": "#9e9e9e"}.get(trade["durum"], DOWN)
        ax.plot(rel["exit_bar"], trade["cikis"], marker="X", markersize=9,
                color=col, markeredgecolor="white", markeredgewidth=0.6)

    # Stoch
    ax2.plot(x, ctx["Stoch_K"], color="#2962ff", linewidth=1.1)
    for lvl in (30, 70):
        ax2.axhline(lvl, color=TXT, linewidth=0.6, linestyle="--", alpha=0.6)
    ax2.axvline(rel["touch"], color="#ffeb3b", linewidth=0.7, alpha=0.6)
    ax2.set_ylim(0, 100)
    ax2.text(0.005, 0.85, "Stoch 5 3", transform=ax2.transAxes, color=TXT, fontsize=7.5)

    # Saat etiketleri (Türkiye saati)
    times = pd.to_datetime(ctx["timestamp"], unit="ms", utc=True).dt.tz_convert(TZ)
    step = max(1, len(ctx) // 8)
    ticks = list(range(0, len(ctx), step))
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([times[t].strftime("%d.%m %H:%M") for t in ticks])
    ax.set_xlim(-1, len(ctx) + 6)

    closed = trade["durum"] in ("win", "loss", "be")
    if closed:
        res = {"win": "TP ✓", "be": "BAŞABAŞ"}.get(trade["durum"], "STOP ✗")
        title = (f"{trade['coin']}  {trade['zaman_dilimi']}  {trade['yon']}   {res}   "
                 f"{trade['R_net']:+.2f}R ({trade['dolar']:+.0f}$)   temas: {trade['temas']} TR / {trade['temas_utc']} UTC")
        badge = {"win": ("✓ TP", UP), "be": ("BAŞABAŞ", "#9e9e9e")}.get(trade["durum"], ("✗ STOP", DOWN))
        badge_txt = f"{badge[0]}  {trade['R_net']:+.2f}R"
    else:
        title = (f"{trade['coin']}  {trade['zaman_dilimi']}  {trade['yon']}   "
                 f"temas: {trade['temas']} TR / {trade['temas_utc']} UTC")
        badge_txt, badge = trade.get("etiket", "EMİR HAZIR"), (None, "#2962ff")
    ax.set_title(title, color=TXT, fontsize=10.5, loc="left")
    ax.text(0.99, 0.97, badge_txt, transform=ax.transAxes, ha="right", va="top",
            fontsize=15, fontweight="bold", color="white",
            bbox=dict(boxstyle="round,pad=0.35", facecolor=badge[1], edgecolor="none"))
    ax.legend(loc="upper left", fontsize=7, facecolor=BG, edgecolor=GRID, labelcolor=TXT)
    fig.tight_layout()

    if pdf is not None:
        pdf.savefig(fig, facecolor=BG)
    if path:
        fig.savefig(path, dpi=110, facecolor=BG)
    plt.close(fig)


def make_pdf(trades, path):
    with PdfPages(path) as pdf:
        for t in trades:
            draw(t, pdf=pdf)


def make_samples(trades, folder, n_each=5):
    """Fotoğraf olarak gönderilecek örnekler: en son 5 TP ve 5 stop."""
    wins = [t for t in trades if t["durum"] == "win"][-n_each:]
    losses = [t for t in trades if t["durum"] != "win"][-n_each:]
    paths = []
    for k, t in enumerate(wins + losses):
        p = f"{folder}/islem_{k + 1}.png"
        draw(t, path=p)
        paths.append(p)
    return paths
