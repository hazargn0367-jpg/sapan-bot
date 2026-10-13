"""
Bellek takibi (Render planı 512MB).

- Her 10 sn: botun, backtest'in ve kapsayıcının (Render'ın ölçtüğü) bellek kullanımı.
- Toplam sınıra yaklaşırsa backtest durdurulur: canlı bildirim botu hiç kapanmasın.
- Bot tek başına şişerse Telegram'a uyarı (sebebini bulmak için).
- Ölçümler 5 dk'da bir log'a, en yüksek değer /durum'a yazılır.
- Son ölçüm /tmp'ye yazılır; bot yeniden başlarsa önceki çalışmanın son ölçümü açılış mesajına eklenir.
"""

import json
import logging
import os
import threading
import time

log = logging.getLogger("bot")

LIMIT_MB = int(os.environ.get("MEMORY_LIMIT_MB", "512"))
BACKTEST_STOP_MB = LIMIT_MB * 0.85   # toplam bu seviyeyi geçerse backtest durdurulur
BOT_WARN_MB = LIMIT_MB * 0.6         # bot tek başına bunu geçerse uyarı
INTERVAL = 10
STATE_FILE = "/tmp/sapan_mem.json"

_peak = {"used": 0.0, "bot": 0.0, "bt": 0.0, "at": None}
_last = {}
_warned_at = 0.0


def rss_mb(pid):
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) / 1024
    except (OSError, ValueError):
        pass
    return 0.0


def _read_stat(path):
    out = {}
    with open(path) as f:
        for line in f:
            k, v = line.split()
            out[k] = int(v) / 2**20
    return out


def cgroup_mb():
    """Kapsayıcının bellek kullanımı (MB). anon = programların kendi belleği,
    file = disk önbelleği (gerekirse boşaltılır), shmem = bellekteki dosyalar (/tmp bellekteyse).
    Değer bizim kapsayıcıya ait görünmüyorsa (sınırın çok üstü) None döner."""
    cg = _cgroup_raw()
    if cg is None or cg["total"] > LIMIT_MB * 4:
        return None
    return cg


def _cgroup_raw():
    try:  # cgroup v2
        with open("/sys/fs/cgroup/memory.current") as f:
            total = int(f.read()) / 2**20
        st = _read_stat("/sys/fs/cgroup/memory.stat")
        return {"total": total, "anon": st.get("anon", 0.0), "file": st.get("file", 0.0),
                "shmem": st.get("shmem", 0.0)}
    except (OSError, ValueError):
        pass
    try:  # cgroup v1
        with open("/sys/fs/cgroup/memory/memory.usage_in_bytes") as f:
            total = int(f.read()) / 2**20
        st = _read_stat("/sys/fs/cgroup/memory/memory.stat")
        return {"total": total, "anon": st.get("total_rss", st.get("rss", 0.0)),
                "file": st.get("total_cache", st.get("cache", 0.0)),
                "shmem": st.get("total_shmem", st.get("shmem", 0.0))}
    except (OSError, ValueError):
        return None


def sample(child=None):
    bot = rss_mb(os.getpid())
    bt = rss_mb(child.pid) if child is not None and child.poll() is None else 0.0
    cg = cgroup_mb()
    # Gerçekten geri alınamayan kısım: programlar + bellekteki dosyalar. Okunamazsa süreçlerin toplamı.
    used = max(bot + bt, cg["anon"] + cg["shmem"]) if cg else bot + bt
    s = {"t": time.time(), "bot": bot, "bt": bt, "used": used, "cg": cg}
    _last.clear()
    _last.update(s)
    if used > _peak["used"]:
        _peak.update(used=used, bot=bot, bt=bt, at=s["t"])
    return s


def _hhmm(t):
    return time.strftime("%H:%M", time.gmtime(t + 3 * 3600))  # TR saati (UTC+3)


def describe(s):
    txt = f"bot {s['bot']:.0f}MB, backtest {s['bt']:.0f}MB, toplam {s['used']:.0f}/{LIMIT_MB}MB"
    cg = s.get("cg")
    if cg:
        txt += f" (kapsayıcı {cg['total']:.0f}MB: program {cg['anon']:.0f}, önbellek {cg['file']:.0f}, bellekte dosya {cg['shmem']:.0f})"
    return txt


def status_line():
    """/durum için tek satır."""
    if not _last:
        return "🧠 Bellek: henüz ölçülmedi"
    line = f"🧠 Bellek: {describe(_last)}"
    if _peak["at"]:
        line += (f"\nEn yüksek {_peak['used']:.0f}MB ({_hhmm(_peak['at'])}; bot {_peak['bot']:.0f}, "
                 f"backtest {_peak['bt']:.0f})")
    return line


def previous_run_note():
    """Bot yeniden başladıysa önceki çalışmanın son bellek ölçümü (çökme sebebini anlamak için)."""
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return ""
    if time.time() - s.get("t", 0) > 900:
        return ""
    note = f"Önceki çalışmanın son ölçümü ({_hhmm(s['t'])}): {describe(s)}"
    if s.get("peak"):
        note += f", en yüksek {s['peak']:.0f}MB"
    return note


def _save(s):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(dict(s, peak=_peak["used"]), f)
    except OSError:
        pass


def _loop(get_child, notify):
    global _warned_at
    last_log = 0.0
    while True:
        try:
            child = get_child()
            s = sample(child)
            _save(s)
            if child is not None and child.poll() is None and s["used"] > BACKTEST_STOP_MB:
                child.terminate()
                log.warning("Bellek sınırına yaklaşıldı, backtest durduruldu: %s", describe(s))
                notify(f"⚠️ Bellek sınıra yaklaştı ({describe(s)}). Bot kapanmasın diye backtest durduruldu. "
                       "Daha kısa dönemle tekrar deneyebilirsin.")
            if s["bot"] > BOT_WARN_MB and time.time() - _warned_at > 3600:
                _warned_at = time.time()
                log.warning("Bot belleği yüksek: %s", describe(s))
                notify(f"⚠️ Botun belleği yüksek: {describe(s)}")
            if time.time() - last_log > 300:
                last_log = time.time()
                log.info("Bellek: %s", describe(s))
        except Exception as e:
            log.error("Bellek ölçümü hatası: %s", e)
        time.sleep(INTERVAL)


def start(get_child, notify):
    threading.Thread(target=_loop, args=(get_child, notify), daemon=True).start()
