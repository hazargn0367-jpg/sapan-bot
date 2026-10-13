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
    if "_no" in trade:
        title = f"#{trade['_no']}  " + (f"[{trade['_ay']}. ay]  " if "_ay" in trade else "") + title
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


def draw_inspect(df, i, side, r, sd, title, path):
    """/incele grafiği: temas, onay, giriş/stop/TP ve kural 8'in kullandığı noktalar
    (önceki salınım q, son tepe/dip p, önceki ve şimdiki düzeltmenin ucu)."""
    long = side == "LONG"
    first = min(k for k in (sd.get("q"), sd["p"], i - 40) if k is not None)
    lo = max(0, first - 8)
    hi = min(len(df), max(i + 12, r.get("exit_bar", 0) + 4))
    ctx = df.iloc[lo:hi].reset_index(drop=True)
    n = len(ctx)
    fig, (ax, ax2) = plt.subplots(2, 1, figsize=(max(11, min(18, n / 9)), 6.8), sharex=True,
                                  gridspec_kw={"height_ratios": [3.4, 1]})
    fig.patch.set_facecolor(BG)
    for a in (ax, ax2):
        a.set_facecolor(BG)
        a.grid(color=GRID, linewidth=0.6)
        a.tick_params(colors=TXT, labelsize=8)
        for s in a.spines.values():
            s.set_color(GRID)
        a.yaxis.tick_right()
    for k, c in ctx.iterrows():
        col = UP if c["Close"] >= c["Open"] else DOWN
        ax.vlines(k, c["Low"], c["High"], color=col, linewidth=0.8)
        b0, b1 = sorted((c["Open"], c["Close"]))
        ax.add_patch(Rectangle((k - 0.32, b0), 0.64, max(b1 - b0, 1e-12), color=col))
    for name, color in EMA_COLORS.items():
        ax.plot(range(n), ctx[name], color=color, linewidth=1.1, label=name)

    y_lo, y_hi = ctx["Low"].min(), ctx["High"].max()
    if "entry" in r:
        y_lo, y_hi = min(y_lo, r["stop"], r["tp"]), max(y_hi, r["stop"], r["tp"])
    rng = y_hi - y_lo
    ax.set_ylim(y_lo - rng * 0.1, y_hi + rng * 0.1)
    pad = rng * 0.05

    used = {}

    def mark(bar, text, color, below):
        b = bar - lo
        if not 0 <= b < n:
            return
        c = ctx.iloc[b]
        y0 = c["Low"] if below else c["High"]
        k = used.get((b, below), 0)  # aynı mumda ikinci etiket üst üste binmesin
        used[(b, below)] = k + 1
        off = pad * (1 + 0.9 * k)
        ax.annotate(text, (b, y0), (b, y0 - off if below else y0 + off), color=color, fontsize=8,
                    ha="center", va="top" if below else "bottom", fontweight="bold",
                    arrowprops=dict(arrowstyle="-", color=color, lw=0.8))

    # Kural 8 noktaları
    peak_word = "tepe" if long else "dip"
    pull_word = "dibi" if long else "tepesi"
    mark(sd["p"], f"p: son {peak_word}", "#ffffff", below=not long)
    if sd.get("q") is not None:
        mark(sd["q"], f"q: önceki salınım {peak_word}", "#90caf9", below=not long)
        y = sd["prior"]
        ax.hlines(y, sd["prior_idx"] - lo, n - 1, color="#ff9800", linewidth=1.0, linestyles="--")
        ax.text(n - 0.5, y, f"önceki düzeltme {pull_word} {y:.8g}", color="#ff9800", fontsize=7.5, va="center")
        mark(sd["prior_idx"], "önceki düzeltme", "#ff9800", below=long)
        mark(sd["cur_idx"], "şimdiki düzeltme", "#ffeb3b" if sd["ok"] else DOWN, below=long)

    mark(i, "Temas", "#ffeb3b", below=long)
    if "confirm" in r:
        mark(r["confirm"], "Onay", "#ce93d8", below=not long)
    if "entry" in r:
        e0 = r.get("entry_bar", r["confirm"] + 1) - lo
        e1 = r.get("exit_bar", r["confirm"] + 3) - lo + 0.5
        for y, col, lbl in ((r["entry"], TXT, "Giriş"), (r["stop"], DOWN, "Stop"), (r["tp"], UP, "TP")):
            ax.hlines(y, e0 - 0.5, e1, color=col, linewidth=0.9, linestyles="--")
            ax.text(e1 + 0.2, y, f"{lbl} {y:.8g}", color=col, fontsize=7.5, va="center")
        if "exit_bar" in r:
            col = {"win": UP, "be": "#9e9e9e"}.get(r["status"], DOWN)
            ax.plot(r["exit_bar"] - lo, r["exit"], marker="X", markersize=9, color=col,
                    markeredgecolor="white", markeredgewidth=0.6)

    ax2.plot(range(n), ctx["Stoch_K"], color="#2962ff", linewidth=1.1)
    for lvl in (30, 70):
        ax2.axhline(lvl, color=TXT, linewidth=0.6, linestyle="--", alpha=0.6)
    ax2.axvline(i - lo, color="#ffeb3b", linewidth=0.7, alpha=0.6)
    ax2.set_ylim(0, 100)
    ax2.text(0.005, 0.85, "Stoch 5 3", transform=ax2.transAxes, color=TXT, fontsize=7.5)
    times = pd.to_datetime(ctx["timestamp"], unit="ms", utc=True).dt.tz_convert(TZ)
    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    ax2.set_xticks(ticks)
    ax2.set_xticklabels([times[t].strftime("%d.%m %H:%M") for t in ticks])
    ax.set_xlim(-1, n + max(8, n * 0.12))
    ax.set_title(title, color=TXT, fontsize=10.5, loc="left")
    ax.legend(loc="upper left", fontsize=7, facecolor=BG, edgecolor=GRID, labelcolor=TXT)
    fig.tight_layout()
    fig.savefig(path, dpi=110, facecolor=BG)
    plt.close(fig)


def _index_pages(trades, pdf, per_page=26):
    """PDF'in başına numaralı işlem listesi."""
    rows = []
    for t in trades:
        res = {"win": "TP", "be": "BAŞABAŞ"}.get(t["durum"], "STOP")
        rows.append([f"#{t['_no']}", f"{t['_ay']}. ay" if "_ay" in t else "", t["coin"], t["yon"],
                     f"{t['temas']} TR", f"{t['temas_utc']} UTC", res, f"{t['R_net']:+.2f}R", f"{t['dolar']:+.0f}$"])
    total = sum(t["R_net"] for t in trades)
    wins = sum(t["durum"] == "win" for t in trades)
    for start in range(0, len(rows), per_page):
        fig, ax = plt.subplots(figsize=(11, 8.5))
        fig.patch.set_facecolor(BG)
        ax.axis("off")
        if start == 0:
            ax.set_title(f"İşlem listesi: {len(trades)} işlem, {wins} TP, toplam {total:+.1f}R",
                         color=TXT, fontsize=13, loc="left")
        chunk = rows[start:start + per_page]
        table = ax.table(cellText=chunk, colLabels=["No", "Ay", "Coin", "Yön", "Temas", "", "Sonuç", "R", "$"],
                         loc="upper left", cellLoc="left", colLoc="left")
        table.auto_set_font_size(False)
        table.set_fontsize(11)
        table.auto_set_column_width(col=list(range(9)))
        table.scale(1.15, 1.5)
        for (r, c), cell in table.get_celld().items():
            cell.set_edgecolor(GRID)
            cell.set_facecolor(BG if r else "#1e222d")
            txt = cell.get_text()
            txt.set_color(TXT)
            if r and c in (6, 7, 8):
                txt.set_color({"TP": UP, "STOP": DOWN}.get(chunk[r - 1][6], "#9e9e9e"))
        pdf.savefig(fig, facecolor=BG)
        plt.close(fig)


def make_pdf(trades, path):
    trades = [dict(t, _no=k + 1) for k, t in enumerate(trades)]
    with PdfPages(path) as pdf:
        _index_pages(trades, pdf)
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
