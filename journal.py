"""
İşlem günlüğü: canlı EMİR HAZIR bildirimleri, kullanıcının "Girdim / Girmedim" kararı ve sonuçları.
Kalıcı diskte (config.data_dir()) JSON olarak tutulur; bot yeniden başlasa da kaybolmaz.
Amaç: botun bütün bildirimleri ile kullanıcının seçtiği işlemlerin sonuçlarını karşılaştırmak.
"""

import json
import os
import threading
import time

import config

_lock = threading.Lock()
TRADED = ("win", "loss", "be")


def _path():
    return os.path.join(config.data_dir(), "journal.json")


def _load():
    try:
        with open(_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"setups": {}}


def _save(data):
    tmp = _path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _path())


def key_of(symbol, touch_ts, tf=None):
    """tf: 15dk (canlı) için None (eski kayıtlarla aynı anahtar); 30dk bildirimleri "…|30m" (22.10)."""
    return f"{symbol}|{int(touch_ts)}" + (f"|{tf}" if tf else "")


def record_alert(symbol, touch_ts, side, entry, stop, tp, mode=None, tf=None):
    with _lock:
        d = _load()
        d["setups"].setdefault(key_of(symbol, touch_ts, tf), {
            "symbol": symbol, "touch": int(touch_ts), "side": side, "entry": entry, "stop": stop, "tp": tp,
            "mode": mode, "tf": tf,
            "sent": time.time(), "decision": None, "status": "pending", "r": None,
        })
        _save(d)


def set_decision(key, decision):
    with _lock:
        d = _load()
        s = d["setups"].get(key)
        if s is None:
            return None
        s["decision"] = decision
        _save(d)
        return s


def set_result(symbol, touch_ts, status, r_net=None, tf=None):
    with _lock:
        d = _load()
        s = d["setups"].get(key_of(symbol, touch_ts, tf))
        if s is None:
            return
        s["status"] = status
        if r_net is not None:
            s["r"] = round(float(r_net), 3)
        _save(d)


def _line(name, items):
    done = [s for s in items if s["status"] in TRADED]
    if not done:
        return f"{name}: henüz sonuçlanan işlem yok"
    wins = sum(s["status"] == "win" for s in done)
    total = sum(s["r"] or 0 for s in done)
    return (f"{name}: {len(done)} işlem, {wins} TP, %{100 * wins / len(done):.0f}, "
            f"<b>{total:+.1f}R ({total * _risk_usd():+.2f}$)</b>")


def _risk_usd():
    import live_setups
    return live_setups.ALERT_RISK_USD


def summary():
    """/durum için: bütün bildirimler ve senin girdiklerin."""
    allitems = list(_load()["setups"].values())
    items = [s for s in allitems if not s.get("tf")]          # 15dk (canlı / otomatik)
    alt = [s for s in allitems if s.get("tf")]                # 30dk sadece bildirim (22.10)
    if not allitems:
        return "📒 Günlük: henüz bildirim yok"
    took = [s for s in items if s["decision"] == "girdim"]
    skipped = [s for s in items if s["decision"] == "girmedim"]
    unmarked = sum(1 for s in allitems if s["decision"] is None)
    lines = [f"📒 <b>Günlük</b> ({len(items)} bildirim" + (f" + {len(alt)} 30dk" if alt else "") + f", {unmarked} işaretlenmemiş)",
             _line("Botun bütün bildirimleri", items),
             _line("Senin girdiklerin", took),
             _line("Girmediklerin", skipped)]
    if alt:
        lines += [_line("30dk bütün bildirimler", alt),
                  _line("30dk senin girdiklerin", [s for s in alt if s["decision"] == "girdim"])]
    return "\n".join(lines)
