"""Canlı tarama için kapanmış mumlar Binance USDⓈ-M vadeli WebSocket akışından (kullanıcı 20.10 22:17 "kodla").

Neden: canlı tarama her 15 dakikada 500 coin için REST isteği atıyordu (~500 ağırlık). Render'ın çıkış IP'si başka
servislerle paylaşıldığı için Binance zaman zaman IP'yi engelliyor (418); engel sürerken tarama atlanıyordu. WebSocket
akışı REST ağırlığı kullanmaz, engel sırasında da veri gelir.

- Adres: wss://fstream.binance.com/market/stream?streams=<coin>@kline_15m/... (2026-04-23'ten beri kline akışları /market
  yolunda). Bağlantı başına en fazla CHUNK akış; 500 coin = 5 bağlantı.
- Sadece kapanmış mumlar saklanır ("x":true). Açık mum güncellemeleri (saniyede ~4 / coin) JSON'a çevrilmeden atlanır.
- Kopan bağlantı kendiliğinden yeniden bağlanır (5 sn, art arda kopmada en fazla 5 dk bekleme); Binance bağlantıyı 24 saatte
  kapattığı için 23 saatte bir yenilenir. Kaçan mumlar live_setups.fetch_candles'ta REST ile tamamlanır.
- Ek kütüphane yok: küçük bir RFC 6455 istemcisi (ssl + socket) burada.
"""
import base64
import json
import logging
import os
import socket
import ssl
import struct
import threading
import time
from collections import deque
from urllib.parse import urlparse

log = logging.getLogger("bot")

BASE = os.environ.get("BINANCE_WS_BASE", "wss://fstream.binance.com/market/stream?streams=")
CHUNK = 100                 # bağlantı başına akış
KEEP = 64                   # coin başına saklanan kapanmış mum
RENEW_SEC = 23 * 3600       # Binance 24 saatte keser: önce biz yenileriz
READ_TIMEOUT = 300          # bu kadar sn hiç veri gelmezse bağlantı ölü sayılır (Binance 3 dk'da bir ping atar)


class _WSClosed(Exception):
    pass


class _Conn:
    """En küçük WebSocket istemcisi (sadece metin mesajları okur, ping'e pong döner)."""

    def __init__(self, url, timeout=15):
        u = urlparse(url)
        self.host = u.hostname
        port = u.port or (443 if u.scheme == "wss" else 80)
        path = u.path + (("?" + u.query) if u.query else "")
        raw = socket.create_connection((self.host, port), timeout=timeout)
        if u.scheme == "wss":
            ctx = ssl.create_default_context()
            raw = ctx.wrap_socket(raw, server_hostname=self.host)
        self.sock = raw
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET {path} HTTP/1.1\r\nHost: {self.host}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\nUser-Agent: sapan-bot\r\n\r\n")
        self.sock.sendall(req.encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise _WSClosed("el sıkışma sırasında bağlantı kapandı")
            head += chunk
            if len(head) > 65536:
                raise _WSClosed("el sıkışma cevabı çok uzun")
        status, _, rest = head.partition(b"\r\n\r\n")
        first = status.split(b"\r\n", 1)[0].decode(errors="replace")
        if " 101 " not in first + " ":
            raise _WSClosed(f"el sıkışma reddedildi: {first}")
        self.buf = bytearray(rest)
        self.pos = 0
        self.sock.settimeout(READ_TIMEOUT)

    def _read(self, n):
        while len(self.buf) - self.pos < n:
            if self.pos:
                del self.buf[:self.pos]     # tüketilen kısım sadece yeni veri gerektiğinde silinir
                self.pos = 0
            chunk = self.sock.recv(65536)
            if not chunk:
                raise _WSClosed("bağlantı kapandı")
            self.buf += chunk
        out = bytes(self.buf[self.pos:self.pos + n])
        self.pos += n
        return out

    def _send(self, opcode, payload=b""):
        mask = os.urandom(4)
        n = len(payload)
        if n < 126:
            hdr = struct.pack("!BB", 0x80 | opcode, 0x80 | n)
        elif n < 65536:
            hdr = struct.pack("!BBH", 0x80 | opcode, 0x80 | 126, n)
        else:
            hdr = struct.pack("!BBQ", 0x80 | opcode, 0x80 | 127, n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(hdr + mask + masked)

    def recv_text(self):
        """Bir sonraki metin mesajı (str). Ping'lere pong döner; kapanışta _WSClosed."""
        parts = []
        while True:
            b0, b1 = self._read(2)
            fin, opcode = b0 & 0x80, b0 & 0x0F
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack("!H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack("!Q", self._read(8))[0]
            mask = self._read(4) if b1 & 0x80 else None
            data = self._read(n)
            if mask:
                data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
            if opcode == 0x9:        # ping → pong (aynı içerik)
                self._send(0xA, data)
                continue
            if opcode == 0xA:        # pong
                continue
            if opcode == 0x8:        # kapanış
                try:
                    self._send(0x8, data[:2])
                except OSError:
                    pass
                raise _WSClosed("sunucu kapattı" + (f" ({struct.unpack('!H', data[:2])[0]})" if len(data) >= 2 else ""))
            if opcode in (0x1, 0x2, 0x0):
                parts.append(data)
                if fin:
                    return b"".join(parts).decode("utf-8", errors="replace")

    def close(self):
        try:
            self._send(0x8, struct.pack("!H", 1000))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


class KlineFeed:
    """Kapanmış mumların akışı. set_symbols() ile başlar; closed_after() ile okunur."""

    def __init__(self, interval, base=None, chunk=CHUNK):
        self.interval = interval
        self.base = base or BASE
        self.chunk = chunk
        self._lock = threading.Lock()
        self._closed = {}           # COIN -> deque[(t, o, h, l, c)]
        self._symbols = set()
        self._gen = 0
        self._conns = {}            # (gen, idx) -> _Conn
        self.alive = {}             # (nesil, bağlantı) -> son mesaj zamanı (bağlıysa)
        self.last_msg = 0.0
        self.msgs = 0
        self.closed_msgs = 0
        self.reconnects = 0
        self.last_error = ""
        self.started = time.time()

    # --- abonelik
    def set_symbols(self, symbols):
        """Coin listesi değişince (yeni coin geldiyse) bağlantılar yeni listeyle kurulur. Eski coinlerin mumları kalır."""
        syms = {s.upper() for s in symbols}
        if not syms or syms <= self._symbols:
            return False
        merged = syms | self._symbols
        # listeden çıkan coinler bir süre abone kalır (saatlik hacim listesi her seferinde bağlantı yenilemesin); liste
        # %30'dan fazla şişerse sadece güncel liste
        self._symbols = merged if len(merged) <= 1.3 * len(syms) else syms
        self._gen += 1
        gen = self._gen
        for key, c in list(self._conns.items()):
            if key[0] != gen:
                c.close()
        ordered = sorted(self._symbols)
        for k in range(0, len(ordered), self.chunk):
            idx = k // self.chunk
            th = threading.Thread(target=self._run, args=(gen, idx, ordered[k:k + self.chunk]),
                                  daemon=True, name=f"ws-kline-{idx}")
            th.start()
        log.info("WebSocket mum akışı: %d coin, %d bağlantı", len(ordered), (len(ordered) + self.chunk - 1) // self.chunk)
        return True

    def stop(self):
        self._gen += 1
        for c in list(self._conns.values()):
            c.close()
        self._conns.clear()

    # --- bağlantı döngüsü
    def _run(self, gen, idx, part):
        url = self.base + "/".join(f"{s.lower()}@kline_{self.interval}" for s in part)
        backoff = 5
        while gen == self._gen:
            t0 = time.time()
            conn = None
            try:
                conn = _Conn(url)
                self._conns[(gen, idx)] = conn
                self.alive[(gen, idx)] = time.time()
                while gen == self._gen:
                    msg = conn.recv_text()
                    now = time.time()
                    self.alive[(gen, idx)] = now
                    self.last_msg = now
                    self.msgs += 1
                    if '"x":true' in msg:
                        self._on_closed(msg)
                    if now - t0 > RENEW_SEC:
                        break
            except (OSError, _WSClosed, ValueError) as e:
                if gen == self._gen:
                    self.last_error = f"{time.strftime('%H:%M')} {type(e).__name__}: {e}"[:200]
                    log.warning("WebSocket bağlantısı %d koptu: %s", idx, e)
            finally:
                self._conns.pop((gen, idx), None)
                self.alive.pop((gen, idx), None)
                if conn is not None:
                    conn.close()
            if gen != self._gen:
                break
            self.reconnects += 1
            lived = time.time() - t0
            backoff = 5 if lived > 120 else min(backoff * 2, 300)
            time.sleep(backoff)

    def _on_closed(self, msg):
        try:
            d = json.loads(msg)
            k = (d.get("data") or d)["k"]
            if not k.get("x"):
                return
            row = (int(k["t"]), float(k["o"]), float(k["h"]), float(k["l"]), float(k["c"]))
            sym = str(k["s"]).upper()
        except (ValueError, KeyError, TypeError):
            return
        self.closed_msgs += 1
        with self._lock:
            dq = self._closed.get(sym)
            if dq is None:
                dq = self._closed[sym] = deque(maxlen=KEEP)
            if not dq or row[0] > dq[-1][0]:
                dq.append(row)
            elif row[0] == dq[-1][0]:
                dq[-1] = row

    # --- okuma
    def closed_after(self, symbol, ts):
        """ts'den sonra açılmış kapanmış mumlar [(t, o, h, l, c)], zaman sırasıyla."""
        with self._lock:
            dq = self._closed.get(symbol.upper())
            return [r for r in dq if r[0] > ts] if dq else []

    def n_connections(self):
        return (len(self._symbols) + self.chunk - 1) // self.chunk if self._symbols else 0

    def healthy(self, max_silence=60):
        n = self.n_connections()
        now = time.time()
        cur = [t for (g, _), t in list(self.alive.items()) if g == self._gen]
        return n > 0 and len(cur) == n and all(now - t < max_silence for t in cur)

    def status(self):
        n = self.n_connections()
        if not n:
            return "kapalı"
        up = sum(1 for (g, _) in list(self.alive) if g == self._gen)
        ago = time.time() - self.last_msg if self.last_msg else None
        s = f"{up}/{n} bağlantı açık"
        s += f", son mesaj {ago:.0f} sn önce" if ago is not None else ", henüz mesaj yok"
        s += f", yeniden bağlanma {self.reconnects}"
        return s
