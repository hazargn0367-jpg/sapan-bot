"""
OTOMATİK İŞLEM (Binance USDⓈ-M vadeli)

Canlı taramanın EMİR HAZIR verdiği setup'ları kullanıcının Binance hesabında açar ve yönetir.
Kullanıcı isteği (15.10 02:52): "en iyi sistemle Binance otomatik işlem, 1R = 1 dolar".
15.10 14:24: "1R 15 dolar olsun; kaldıracı arttır, önemli olan 1R'ın 15 olması". Kaldıraç işlem başına seçilir:
likidasyon fiyatı stopun en az 1.5 katı uzakta kalacak en yüksek kaldıraç (coinin sınırı ve AUTO_LEVERAGE ile sınırlı),
böylece marjin küçük kalır ama pozisyon stoptan önce likide olmaz.

Akış (her setup için):
  1. EMİR HAZIR → girişe borsada STOP_MARKET (algo emri) konur. Miktar = risk / |giriş - stop|; risk = AUTO_RISK_USD ×
     çarpan (son 24 saatte kapanan otomatik işlemler artıda 2x, ekside 0.5x, yoksa 1x; 17.10).
     Fiyat girişi çoktan geçtiyse (emir hemen tetiklenecekse) ve 0.3R'den fazla kaçmadıysa piyasa emriyle girilir.
  2. Pozisyon açılınca (her ~5 sn kontrol) hemen borsaya stop (STOP_MARKET, reduceOnly) ve TP (LIMIT, reduceOnly)
     konur. Bot ya da bağlantı çökse bile pozisyon borsadaki stop/TP ile korunur.
     Stop konamazsa pozisyon hemen piyasa emriyle kapatılır (korumasız pozisyon bırakılmaz).
  3. Onay mumunun ucu kırılırsa / giriş penceresi dolarsa (canlı takip bunu mum kapanışında görür) giriş emri silinir.
  4. Erken çıkış (giriş mumu ya da sonraki mum girişin gerisinde kapatırsa) → piyasa emriyle kapatılır, stop/TP silinir.
  5. Pozisyon kapanınca (TP / stop / elle) kalan emir silinir, gerçek kâr-zarar (komisyon dahil) R olarak bildirilir.

Güvenlik:
  - API anahtarı sadece Render Environment'ta (BINANCE_API_KEY / BINANCE_API_SECRET). Para çekme yetkisi KAPALI olmalı.
  - Otomatik işlem kapalı başlar; /oto aç ile açılır (durum kalıcı diskte).
  - İzole marjin, işlem başı otomatik kaldıraç (en fazla AUTO_LEVERAGE); tek işlemde en fazla AUTO_MAX_NOTIONAL USDT
    pozisyon.
  - Aynı anda en fazla AUTO_MAX_OPEN işlem; gün içinde -AUTO_DAILY_LOSS_R R olursa o gün yeni işlem açılmaz.
  - Coinde bizim olmayan bir pozisyon varsa o coine girilmez; bilinmeyen pozisyonlara dokunulmaz.
"""

import hashlib
import hmac
import html
import json
import logging
import math
import os
import threading
import time
from decimal import ROUND_DOWN, Decimal
from urllib.parse import urlencode

import requests

import config
import exchanges

log = logging.getLogger("bot")

API_KEY = os.environ.get("BINANCE_API_KEY", "").strip()
API_SECRET = os.environ.get("BINANCE_API_SECRET", "").strip()
RISK_USD = float(os.environ.get("AUTO_RISK_USD", "15"))         # 1R = kaç dolar (otomatik işlemde); 20.10 11:43: 15 → 20 · 20.10 18:06: 20 → 15 (toplu 10 coin denemesi, 1 ay)
LEVERAGE = int(os.environ.get("AUTO_LEVERAGE", "50"))             # en yüksek kaldıraç (işlem başı otomatik seçilir)
MAX_NOTIONAL = float(os.environ.get("AUTO_MAX_NOTIONAL", "4000"))  # tek işlemde en büyük pozisyon (USDT); stop ≥ %0.5
                                                                    # olduğu için 15$ riskte en fazla ~3000
LIQ_BUFFER = 1.5          # likidasyon mesafesi en az stop mesafesinin bu katı (kaldıraç seçiminde)
MAX_OPEN = int(os.environ.get("AUTO_MAX_OPEN", "2"))
DAILY_LOSS_R = float(os.environ.get("AUTO_DAILY_LOSS_R", "5"))
LATE_MAX_R = 0.3          # fiyat girişi en fazla bu kadar R geçmişse piyasa emriyle girilir, fazlasıysa girilmez
POLL_SEC = 5
# Kullanıcı 17.10 00:34 "yükle": işlem riski, son 24 saatte kapanan otomatik işlemlerin R toplamına göre (rejim sürekliliği:
# sistem yeni kazandıysa sıradaki işlem çok daha iyi). 9 dönem backtest (54 ay, 2021-2026): artıda 2x / ekside 0.5x / kapanan
# yoksa 1x → 9/9 dönem eşit ya da daha iyi, ayda ~+1R (son yıl +2.4R), en büyük düşüş 16.3R → 14.3R. Kapatmak için Render
# Environment'ta AUTO_MOMENTUM_UP=1 ve AUTO_MOMENTUM_DOWN=1.
MOMENTUM_HOURS = float(os.environ.get("AUTO_MOMENTUM_HOURS", "24"))
MOMENTUM_UP = float(os.environ.get("AUTO_MOMENTUM_UP", "3.0"))   # 20.10 11:43 kullanıcı: 2x → 3x (18 ay simülasyon: 3x/0.5x ayda 9.1R, düşüş aynı)
MOMENTUM_DOWN = float(os.environ.get("AUTO_MOMENTUM_DOWN", "0.5"))
TZ_OFFSET = 3 * 3600      # gün sınırı TR saatine göre

_lock = threading.RLock()
_send = None              # telegram.send_message (bot.py verir; testte değiştirilebilir)


def _say(text):
    log.info("OTO: %s", text.replace("\n", " | "))
    if _send:
        try:
            _send("🤖 <b>OTO</b> " + text)
        except Exception as e:  # mesaj gitmese de işlem yönetimi sürmeli
            log.error("OTO mesajı gönderilemedi: %s", e)


# ------------------------------------------------------------------ Binance istemcisi
class BinanceError(RuntimeError):
    def __init__(self, code, msg, status=None):
        self.code, self.msg, self.status = code, msg, status
        super().__init__(f"Binance {code}: {msg}")


class BinanceAPI:
    """İmzalı USDⓈ-M istekleri. Koşullu emirler (STOP_MARKET vb.) 2025-12-09'dan beri /fapi/v1/algoOrder'dan."""

    def __init__(self, key, secret, base=exchanges.BASE_URL):
        self.key, self.secret, self.base = key, secret, base
        self.session = requests.Session()
        self.offset = 0
        self.offset_at = 0.0

    def _sync(self):
        res = self.session.get(f"{self.base}/fapi/v1/time", timeout=5)
        self.offset = int(res.json()["serverTime"]) - int(time.time() * 1000)
        self.offset_at = time.time()

    def request(self, method, path, params=None, signed=True, _retry=True, base=None):
        wait = exchanges.blocked_for()
        if wait > 0:
            raise BinanceError(-418, f"Binance IP engeli sürüyor (~{int(wait)} sn)")
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = {"X-MBX-APIKEY": self.key}
        if signed:
            if time.time() - self.offset_at > 1800:
                self._sync()
            params["timestamp"] = int(time.time() * 1000) + self.offset
            params["recvWindow"] = 5000
            qs = urlencode(params)
            sig = hmac.new(self.secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
            url = f"{base or self.base}{path}?{qs}&signature={sig}"
        else:
            url = f"{base or self.base}{path}" + (f"?{urlencode(params)}" if params else "")
        res = self.session.request(method, url, headers=headers, timeout=10)
        if res.status_code in (418, 429):
            try:
                secs = int(res.headers.get("Retry-After", "60") or 60)
            except ValueError:
                secs = 60
            exchanges._pause_all(secs, f"Binance {'IP engeli (418)' if res.status_code == 418 else 'istek sınırı (429)'}")
        try:
            data = res.json()
        except ValueError:
            data = {"code": res.status_code, "msg": res.text[:200]}
        if res.status_code >= 400:
            code = data.get("code", res.status_code) if isinstance(data, dict) else res.status_code
            if code == -1021 and _retry:  # saat farkı
                self._sync()
                return self.request(method, path, params={k: v for k, v in params.items()
                                                          if k not in ("timestamp", "recvWindow")},
                                    signed=signed, _retry=False, base=base)
            raise BinanceError(code, data.get("msg", "") if isinstance(data, dict) else str(data), res.status_code)
        return data

    # --- bilgi
    def restrictions(self):
        """Anahtarın yetkileri: ipRestrict, enableFutures, enableWithdrawals ... (spot API, sadece okuma)."""
        return self.request("GET", "/sapi/v1/account/apiRestrictions", base="https://api.binance.com")

    def exchange_info(self):
        return self.request("GET", "/fapi/v1/exchangeInfo", signed=False)

    def dual_side(self):
        return bool(self.request("GET", "/fapi/v1/positionSide/dual").get("dualSidePosition"))

    def usdt_balance(self):
        for b in self.request("GET", "/fapi/v2/balance"):
            if b.get("asset") == "USDT":
                return float(b.get("availableBalance", 0)), float(b.get("balance", 0))
        return 0.0, 0.0

    def positions(self, symbol=None):
        """[{symbol, positionAmt (işaretli), entryPrice, positionSide}] — sadece sıfır olmayanlar."""
        rows = self.request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        return [r for r in rows if abs(float(r.get("positionAmt", 0))) > 0]

    def price(self, symbol):
        return float(self.request("GET", "/fapi/v1/ticker/price", {"symbol": symbol}, signed=False)["price"])

    # --- ayar
    def set_leverage(self, symbol, lev):
        return self.request("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": lev})

    def leverage_bracket(self, symbol):
        return self.request("GET", "/fapi/v1/leverageBracket", {"symbol": symbol})

    def set_isolated(self, symbol):
        try:
            return self.request("POST", "/fapi/v1/marginType", {"symbol": symbol, "marginType": "ISOLATED"})
        except BinanceError as e:
            if e.code in (-4046,):  # zaten izole
                return None
            raise

    # --- emirler
    def new_algo(self, **p):
        return self.request("POST", "/fapi/v1/algoOrder", dict(algoType="CONDITIONAL", **p))

    def cancel_algo(self, symbol, cid):
        return self.request("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "clientAlgoId": cid})

    def new_order(self, **p):
        return self.request("POST", "/fapi/v1/order", p)

    def cancel_order(self, symbol, cid):
        return self.request("DELETE", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": cid})

    def get_order(self, symbol, cid):
        return self.request("GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": cid})

    def user_trades(self, symbol, start_ms):
        return self.request("GET", "/fapi/v1/userTrades", {"symbol": symbol, "startTime": int(start_ms), "limit": 100})


api = BinanceAPI(API_KEY, API_SECRET) if API_KEY and API_SECRET else None


# ------------------------------------------------------------------ kalıcı durum
def _path(name):
    return os.path.join(config.data_dir(), name)


def _load(name, default):
    try:
        with open(_path(name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _save(name, data):
    tmp = _path(name) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, _path(name))


def state():
    return _load("auto_state.json", {"enabled": False, "days": {}})


def _set_state(**kw):
    s = state()
    s.update(kw)
    _save("auto_state.json", s)
    return s


def trades():
    return _load("auto_trades.json", {})


def _save_trades(t):
    _save("auto_trades.json", t)


def risk_mult(extra=None, now=None):
    """Sıradaki işlemin risk çarpanı: son MOMENTUM_HOURS saatte kapanan otomatik işlemlerin (her biri kendi riskine göre)
    R toplamı > 0 → MOMENTUM_UP, < 0 → MOMENTUM_DOWN, kapanan yoksa 1. Dönüş: (çarpan, R toplamı ya da None, işlem sayısı).
    extra: henüz kaydedilmemiş (az önce kapanan) kayıtlar."""
    now = time.time() if now is None else now
    recs = dict(trades())
    for x in extra or []:
        recs[x.get("key", id(x))] = x
    rs = [float(x["r"]) for x in recs.values()
          if x.get("status") == "closed" and x.get("closed") and x.get("r") is not None
          and now - float(x["closed"]) <= MOMENTUM_HOURS * 3600]
    if not rs:
        return 1.0, None, 0
    tot = sum(rs)
    return (MOMENTUM_UP if tot > 0 else MOMENTUM_DOWN if tot < 0 else 1.0), tot, len(rs)


def mult_text(m, tot, n):
    if tot is None:
        return f"son {MOMENTUM_HOURS:g} saatte kapanan işlem yok → {m:g}x"
    return f"son {MOMENTUM_HOURS:g} saatte kapanan {n} işlem {tot:+.2f}R → {m:g}x"


def _today():
    return time.strftime("%Y-%m-%d", time.gmtime(time.time() + TZ_OFFSET))


def _add_day_r(r):
    s = state()
    d = s.setdefault("days", {})
    d[_today()] = round(d.get(_today(), 0.0) + r, 3)
    for k in sorted(d)[:-30]:
        d.pop(k)
    _save("auto_state.json", s)
    return d[_today()]


def enabled():
    return bool(state().get("enabled"))


# ------------------------------------------------------------------ sembol kuralları
_info = {"t": 0.0, "symbols": {}, "dual": None}


def _filters(symbol):
    if time.time() - _info["t"] > 3600 or symbol not in _info["symbols"]:
        out = {}
        for s in api.exchange_info().get("symbols", []):
            f = {x["filterType"]: x for x in s.get("filters", [])}
            out[s["symbol"]] = {
                "tick": Decimal(f.get("PRICE_FILTER", {}).get("tickSize", "0.0001")),
                "step": Decimal(f.get("LOT_SIZE", {}).get("stepSize", "1")),
                "min_qty": Decimal(f.get("LOT_SIZE", {}).get("minQty", "0")),
                "mstep": Decimal(f.get("MARKET_LOT_SIZE", {}).get("stepSize", f.get("LOT_SIZE", {}).get("stepSize", "1"))),
                "min_notional": float(f.get("MIN_NOTIONAL", {}).get("notional", 5)),
            }
        _info.update(t=time.time(), symbols=out)
    return _info["symbols"].get(symbol)


def _dual():
    if _info["dual"] is None:
        _info["dual"] = api.dual_side()
    return _info["dual"]


def _q(x, step):
    """Miktarı adıma aşağı yuvarla, Binance'in istediği yazımla (string)."""
    v = (Decimal(str(x)) / step).to_integral_value(rounding=ROUND_DOWN) * step
    return format(v.normalize(), "f") if v != 0 else "0"


def _px(x, tick):
    v = (Decimal(str(x)) / tick).to_integral_value() * tick
    return format(v.normalize(), "f")


def _side_params(side, closing):
    """Yön ve tek yön / çift yön (hedge) moduna göre emir parametreleri."""
    buy = (side == "LONG") != closing
    p = {"side": "BUY" if buy else "SELL"}
    if _dual():
        p["positionSide"] = side
    elif closing:
        p["reduceOnly"] = "true"
    return p


def _our_position(symbol, side):
    for pos in api.positions(symbol):
        amt = float(pos["positionAmt"])
        ps = pos.get("positionSide", "BOTH")
        if ps in ("BOTH", side) and ((amt > 0) if side == "LONG" else (amt < 0)):
            return abs(amt), float(pos.get("entryPrice", 0))
    return 0.0, 0.0


def _fmt(x):
    return f"{x:.8g}"


# ------------------------------------------------------------------ canlı taramadan gelen olaylar
def managed(symbol, touch_ts):
    """Bu setup otomatik işlemde mi (giriş bekliyor / açık)?"""
    rec = trades().get(f"{symbol}|{int(touch_ts)}")
    return rec is not None and rec["status"] in ("pending", "open")


def ready():
    return api is not None and enabled()


def on_setup(symbol, side, entry, stop, tp, touch_ts, tf):  # noqa: C901
    """EMİR HAZIR gönderildi: otomatik işlem açıksa girişe stop emri koy."""
    if not ready():
        return
    key = f"{symbol}|{int(touch_ts)}"
    with _lock:
        try:
            _open_setup(key, symbol, side, float(entry), float(stop), float(tp), tf, touch_ts)
        except BinanceError as e:
            log.warning("OTO giriş emri reddedildi: %s", e)
            hint = (f"\nBüyük ihtimalle IP izni: Binance API'ye <code>{public_ip()}</code> IP'sini ekle (/ip)."
                    if e.code == -2015 else "")
            _say(f"⚠️ {html.escape(symbol)} {side}: giriş emri konamadı ({html.escape(str(e))[:200]}){hint}")
        except Exception as e:
            log.exception("OTO giriş emri hatası")
            _say(f"⚠️ {html.escape(symbol)} {side}: Binance cevap vermedi ({html.escape(str(e))[:120]}). Emir borsaya "
                 f"ulaşmış olabilir; bot takip ediyor, giriş olursa stop/TP konacak, olmazsa süre dolunca silinecek.")


def _pick_leverage(symbol, notional, stop_frac):
    """Likidasyon stopun LIQ_BUFFER katından daha uzakta kalacak en yüksek kaldıraç (coinin o pozisyon büyüklüğündeki
    sınırı ve LEVERAGE ile sınırlı). İzole marjinde likidasyon mesafesi ≈ 1/kaldıraç - bakım marjini oranı."""
    max_lev, mmr = LEVERAGE, 0.01
    try:
        b = api.leverage_bracket(symbol)
        if isinstance(b, list):
            b = next((x for x in b if x.get("symbol") == symbol), b[0] if b else {})
        for x in b.get("brackets", []):
            if float(x.get("notionalFloor", 0)) <= notional < float(x.get("notionalCap", float("inf"))):
                max_lev = min(max_lev, int(x["initialLeverage"]))
                mmr = float(x.get("maintMarginRatio", mmr))
                break
    except Exception as e:
        log.warning("OTO %s kaldıraç sınırı alınamadı (%s), en fazla 20x varsayılıyor", symbol, e)
        max_lev = min(max_lev, 20)
    safe = int(1.0 / (LIQ_BUFFER * stop_frac + mmr))
    return max(1, min(max_lev, safe))


def size_plan(symbol, entry, stop, risk_usd):
    """Bildirimler için (22.10 kullanıcı: "kaç x kaç dolar"): risk_usd riskte adet (Binance adımına yuvarlı), pozisyon
    (USDT), otomatik işlemdeki kuralla kaldıraç (likidasyon stopun 1.5 katı ötede) ve izole marjin. Hata olursa None."""
    risk = abs(entry - stop)
    if risk <= 0 or entry <= 0:
        return None
    qty = risk_usd / risk * (1 + 1e-9)   # 44.999.. / 0.01 → 4499 olmasın
    try:
        f = _filters(symbol)
        if f is not None:
            qty = float(_q(qty, f["step"]))
    except Exception as e:
        log.debug("%s adım bilgisi alınamadı: %s", symbol, e)
    if qty <= 0:
        return None
    notional = qty * entry
    lev = _pick_leverage(symbol, notional, risk / entry)
    return qty, notional, lev, notional / lev


def _open_setup(key, symbol, side, entry, stop, tp, tf, touch_ts):
    t = trades()
    if key in t:
        return
    active = [x for x in t.values() if x["status"] in ("pending", "open")]
    if len(active) >= MAX_OPEN:
        _say(f"{html.escape(symbol)} {side}: zaten {len(active)} otomatik işlem var, girilmedi")
        return
    day_r = state().get("days", {}).get(_today(), 0.0)
    if day_r <= -DAILY_LOSS_R:
        _say(f"{html.escape(symbol)} {side}: bugün {day_r:+.2f}R (sınır -{DAILY_LOSS_R:g}R), yarına kadar yeni işlem yok")
        return
    if any(x["symbol"] == symbol for x in active) or api.positions(symbol):
        _say(f"{html.escape(symbol)}: bu coinde zaten pozisyon/emir var, girilmedi")
        return
    f = _filters(symbol)
    if f is None:
        _say(f"{html.escape(symbol)}: Binance'te bulunamadı, girilmedi")
        return
    risk = abs(entry - stop)
    if risk <= 0:
        return
    mult, mtot, mn = risk_mult()
    plan, why, avail = None, "", None
    # Çarpan > 1 iken pozisyon sınırı ya da bakiye yetmezse normal riskle (1x) girilir
    for m in [mult] + ([1.0] if mult > 1.0 else []):
        risk_usd = round(RISK_USD * m, 4)
        qty = Decimal(_q(risk_usd / risk, f["step"]))
        notional = float(qty) * entry
        cap = MAX_NOTIONAL * max(1.0, m)
        if qty < f["min_qty"] or notional < f["min_notional"]:
            why = f"{risk_usd:g}$ risk için pozisyon çok küçük ({notional:.1f} USDT, en az {f['min_notional']:g})"
            continue
        if notional > cap:
            why = f"pozisyon {notional:.0f} USDT, sınır {cap:g}"
            continue
        lev = _pick_leverage(symbol, notional, risk / entry)
        if avail is None:
            avail, _ = api.usdt_balance()
        if avail < notional / lev * 1.2:
            why = f"bakiye yetersiz (kullanılabilir {avail:.2f} USDT, gereken ~{notional / lev * 1.2:.2f} {lev}x ile)"
            continue
        plan = (m, risk_usd, qty, notional, lev)
        break
    if plan is None:
        _say(f"{html.escape(symbol)}: {why}, girilmedi")
        return
    m, risk_usd, qty, notional, lev = plan
    risk_note = f"risk {risk_usd:g}$ ({mult_text(mult, mtot, mn)}"
    risk_note += (f"; {why} → 1x)" if m != mult else ")")
    try:
        api.set_isolated(symbol)
    except BinanceError as e:
        log.warning("OTO %s izole marjin ayarlanamadı: %s", symbol, e)
    for cand in [lev] + [x for x in (25, 20, 10, 5) if x < lev]:
        try:
            api.set_leverage(symbol, cand)
            lev = cand
            break
        except BinanceError as e:
            log.warning("OTO %s %dx kaldıraç ayarlanamadı: %s", symbol, cand, e)
    else:
        _say(f"⚠️ {html.escape(symbol)}: kaldıraç ayarlanamadı, girilmedi")
        return
    if avail < notional / lev * 1.2:
        _say(f"{html.escape(symbol)}: bakiye yetersiz ({lev}x ile gereken ~{notional / lev * 1.2:.2f}), girilmedi")
        return

    base = f"{symbol[:18]}{int(touch_ts) // 1000 % 10**9}"
    rec = {"key": key, "symbol": symbol, "side": side, "entry": entry, "stop": stop, "tp": tp, "tf": tf,
           "qty": format(qty.normalize(), "f"), "status": "pending", "created": time.time(),
           "entry_cid": f"se{base}", "sl_cid": f"ss{base}", "tp_cid": f"st{base}",
           "entry_algo": None, "sl_algo": None, "tp_order": None, "fill": None, "opened": None, "lev": lev,
           "risk_usd": risk_usd, "risk_mult": m}
    # Emir gönderilmeden ÖNCE kaydedilir: cevap gelmeden bağlantı koparsa bile izleme döngüsü pozisyonu bulup korur
    t[key] = rec
    _save_trades(t)
    trig = _px(entry, f["tick"])
    try:
        api.new_algo(symbol=symbol, type="STOP_MARKET", triggerPrice=trig, quantity=rec["qty"],
                     workingType="CONTRACT_PRICE", clientAlgoId=rec["entry_cid"], **_side_params(side, closing=False))
        rec["entry_algo"] = rec["entry_cid"]
        how = f"{'BUY' if side == 'LONG' else 'SELL'} STOP {trig}"
    except BinanceError as e:
        if e.code != -2021:  # -2021: emir hemen tetiklenirdi (fiyat girişi geçmiş)
            rec["status"] = "failed"
            _save_trades(t)
            raise
        px = api.price(symbol)
        late = ((px - entry) if side == "LONG" else (entry - px)) / risk
        if late > LATE_MAX_R:
            rec["status"] = "skipped"
            _save_trades(t)
            _say(f"{html.escape(symbol)} {side}: fiyat girişi {late:.2f}R geçmiş ({_fmt(px)}), girilmedi")
            return
        api.new_order(symbol=symbol, type="MARKET", quantity=_q(float(qty), f["mstep"]), **_side_params(side, closing=False))
        how = f"fiyat girişi geçmişti, piyasa emriyle ({_fmt(px)})"
    _save_trades(t)
    _say(f"{'🟢' if side == 'LONG' else '🔴'} <b>{side} {html.escape(symbol)}</b> ({tf}): giriş emri kondu: {how}, "
         f"{rec['qty']} adet (~{notional:,.0f} USDT, {lev}x izole, marjin ~{notional / lev:,.0f} USDT), {risk_note}.\n"
         f"Stop {_fmt(stop)} / TP {_fmt(tp)} giriş dolunca borsaya konacak.")


def on_signal(symbol, touch_ts, status, r=None):
    """Canlı takip (mum kapanışında) setup'ın durumunu değiştirdi."""
    if api is None:
        return
    key = f"{symbol}|{int(touch_ts)}"
    with _lock:
        t = trades()
        rec = t.get(key)
        if rec is None or rec["status"] not in ("pending", "open"):
            return
        try:
            if status in ("cancel_confirm", "no_entry"):
                _cancel_entry(rec, "onay mumunun ucu kırıldı" if status == "cancel_confirm" else "2 mumda girişe gelmedi")
            elif status == "be" and r is not None and r.get("early_exit"):
                _early_exit(rec)
        except Exception as e:
            log.exception("OTO olay hatası")
            _say(f"⚠️ {html.escape(symbol)}: {html.escape(str(e))[:200]}")
        t[key] = rec
        _save_trades(t)


def _cancel_entry(rec, why):
    sym, side = rec["symbol"], rec["side"]
    if rec["status"] == "pending":
        qty, _ = _our_position(sym, side)
        if qty > 0:   # canlı mum verisi iptal dedi ama giriş borsada dolmuş: borsadaki gerçek pozisyon yönetilir
            _protect(rec, qty)
            return
        try:
            api.cancel_algo(sym, rec["entry_cid"])
        except BinanceError as e:
            log.info("OTO giriş emri silinemedi (zaten yok olabilir): %s", e)
        qty, _ = _our_position(sym, side)
        if qty > 0:
            _protect(rec, qty)
            return
        rec["status"] = "canceled"
        _say(f"{html.escape(sym)} {side}: giriş emri silindi ({why})")


def _early_exit(rec):
    sym, side = rec["symbol"], rec["side"]
    qty, _ = _our_position(sym, side)
    if qty <= 0:
        if rec["status"] == "pending":
            _cancel_entry(rec, "erken çıkış koşulu, giriş dolmamış")
        return
    f = _filters(sym)
    api.new_order(symbol=sym, type="MARKET", quantity=_q(qty, f["mstep"]), **_side_params(side, closing=True))
    _cleanup_orders(rec)
    rec["exit_kind"] = "erken çıkış"
    _finish(rec)


def _cleanup_orders(rec):
    sym = rec["symbol"]
    for kind, fn in (("sl_cid", api.cancel_algo), ("tp_cid", api.cancel_order), ("entry_cid", api.cancel_algo)):
        cid = rec.get(kind)
        if cid:
            try:
                fn(sym, cid)
            except BinanceError as e:
                log.info("OTO %s %s silinemedi (zaten yok olabilir): %s", sym, kind, e)


def _dup(e):
    return e.code in (-4116, -4015) or "duplicate" in (e.msg or "").lower()


def _protect(rec, qty):
    """Giriş doldu: borsaya stop ve TP koy (eksik olanı; her döngüde tekrar denenir).
    Stop kesin reddedilirse pozisyon hemen kapatılır; bağlantı hatasında sonraki döngüde yeniden denenir."""
    sym, side = rec["symbol"], rec["side"]
    f = _filters(sym)
    first = rec["status"] == "pending"
    if first:
        _, fill = _our_position(sym, side)
        rec.update(status="open", fill=fill, opened=time.time(), qty=_q(qty, f["step"]))
    if not rec.get("sl_algo"):
        try:
            api.new_algo(symbol=sym, type="STOP_MARKET", triggerPrice=_px(rec["stop"], f["tick"]), quantity=rec["qty"],
                         workingType="CONTRACT_PRICE", clientAlgoId=rec["sl_cid"], **_side_params(side, closing=True))
            rec["sl_algo"] = rec["sl_cid"]
        except BinanceError as e:
            if _dup(e):
                rec["sl_algo"] = rec["sl_cid"]
            else:
                api.new_order(symbol=sym, type="MARKET", quantity=_q(qty, f["mstep"]), **_side_params(side, closing=True))
                _cleanup_orders(rec)
                rec["exit_kind"] = "stop konamadı, hemen kapatıldı"
                _finish(rec)
                _say(f"⚠️ {html.escape(sym)}: stop emri konamadı ({html.escape(str(e))[:150]}), "
                     f"pozisyon güvenlik için kapatıldı")
                return
    tp_txt = f"TP {_fmt(rec['tp'])} (limit)"
    if not rec.get("tp_order") and rec.get("tp_tries", 0) < 5:
        try:
            api.new_order(symbol=sym, type="LIMIT", timeInForce="GTC", price=_px(rec["tp"], f["tick"]),
                          quantity=rec["qty"], newClientOrderId=rec["tp_cid"], **_side_params(side, closing=True))
            rec["tp_order"] = rec["tp_cid"]
        except BinanceError as e:
            if _dup(e):
                rec["tp_order"] = rec["tp_cid"]
            else:
                rec["tp_tries"] = rec.get("tp_tries", 0) + 1
                tp_txt = f"⚠️ TP konamadı ({html.escape(str(e))[:120]}), stop borsada duruyor"
                if not first:
                    _say(f"{html.escape(sym)}: {tp_txt}")
    if first:
        _say(f"{'🟢' if side == 'LONG' else '🔴'} <b>{side} {html.escape(sym)}</b>: giriş doldu {_fmt(rec['fill'])}, "
             f"{rec['qty']} adet. Borsaya stop {_fmt(rec['stop'])} ve {tp_txt} kondu.")


def _resize(rec, qty):
    """Pozisyon miktarı değişti (kullanıcı elle ekleme / azaltma yaptı, 21.10): stop ve TP bütün pozisyona taşınır.
    Fiyatlar aynı kalır; risk (R hesabı) yeni miktar ve ortalama girişe göre güncellenir. Önce yeni stop konur, sonra eskisi
    silinir (pozisyon hiç stopsuz kalmaz); TP önce silinir sonra konur (iki reduceOnly limit toplamı pozisyonu aşmasın)."""
    sym, side = rec["symbol"], rec["side"]
    f = _filters(sym)
    newq = _q(qty, f["step"])
    _, avg = _our_position(sym, side)
    n = int(rec.get("resize_n", 0)) + 1
    old_q = rec["qty"]
    sl_cid = f"{rec['sl_cid'].split('r')[0] if 'r' in rec['sl_cid'][2:] else rec['sl_cid']}r{n}"
    tp_cid = f"{rec['tp_cid'].split('r')[0] if 'r' in rec['tp_cid'][2:] else rec['tp_cid']}r{n}"
    try:
        api.new_algo(symbol=sym, type="STOP_MARKET", triggerPrice=_px(rec["stop"], f["tick"]), quantity=newq,
                     workingType="CONTRACT_PRICE", clientAlgoId=sl_cid, **_side_params(side, closing=True))
    except BinanceError as e:
        if not _dup(e):
            rec["resize_fail"] = rec.get("resize_fail", 0) + 1
            if rec["resize_fail"] in (1, 5):
                _say(f"⚠️ {html.escape(sym)}: pozisyon {old_q} → {newq} adet oldu ama yeni stop konamadı "
                     f"({html.escape(str(e))[:150]}). Eklenen kısmı Binance'te elle koru (TP/SL → tüm pozisyon).")
            return
    old_sl = rec.get("sl_algo") or rec["sl_cid"]
    try:
        api.cancel_algo(sym, old_sl)
    except BinanceError as e:
        log.info("OTO %s eski stop silinemedi (zaten yok olabilir): %s", sym, e)
    rec.update(sl_cid=sl_cid, sl_algo=sl_cid)
    old_tp = rec.get("tp_order") or rec["tp_cid"]
    try:
        api.cancel_order(sym, old_tp)
    except BinanceError as e:
        log.info("OTO %s eski TP silinemedi (zaten yok olabilir): %s", sym, e)
    rec.update(tp_cid=tp_cid, tp_order=None, tp_tries=0, qty=newq, resize_n=n, resize_fail=0)
    if avg > 0:
        rec["fill"] = avg
        rec["risk_usd"] = round(float(newq) * abs(avg - float(rec["stop"])), 4)
    tp_txt = f"TP {_fmt(rec['tp'])}"
    try:
        api.new_order(symbol=sym, type="LIMIT", timeInForce="GTC", price=_px(rec["tp"], f["tick"]),
                      quantity=newq, newClientOrderId=tp_cid, **_side_params(side, closing=True))
        rec["tp_order"] = tp_cid
    except BinanceError as e:
        if _dup(e):
            rec["tp_order"] = tp_cid
        else:
            rec["tp_tries"] = 1   # sonraki döngülerde _protect yeniden dener
            tp_txt = f"⚠️ TP konamadı ({html.escape(str(e))[:100]}), tekrar denenecek"
    _say(f"🔁 {html.escape(sym)} {side}: pozisyon {old_q} → {newq} adet (ortalama giriş {_fmt(rec['fill'])}). "
         f"Stop {_fmt(rec['stop'])} ve {tp_txt} bütün pozisyona taşındı. Bu işlemin riski artık ~{rec['risk_usd']:.2f}$.")


def _finish(rec):
    """Pozisyon kapandı: gerçek kâr-zararı (komisyon dahil) hesapla, bildir."""
    sym = rec["symbol"]
    pnl, fee = 0.0, 0.0
    try:
        since = rec["created"] * 1000 - 2000   # aynı coinde aynı anda tek işlem: giriş emrinden sonraki dolumlar bu işlemin
        bnb = None
        for tr_ in api.user_trades(sym, since):
            pnl += float(tr_.get("realizedPnl", 0))
            c = float(tr_.get("commission", 0))
            asset = tr_.get("commissionAsset", "USDT")
            if asset == "USDT":
                fee += c
            elif asset == "BNB":
                bnb = bnb or api.price("BNBUSDT")
                fee += c * bnb
    except Exception as e:
        log.warning("OTO %s kâr-zarar okunamadı: %s", sym, e)
    net = pnl - fee
    risk_usd = float(rec.get("risk_usd", 1.0))   # 15.10 14:24'ten önceki kayıtlar 1$ riskle açıldı
    r = net / risk_usd if risk_usd else 0.0      # işlemin kendi riskine göre R (risk çarpanı bunu toplar)
    rec.update(status="closed", closed=time.time(), pnl=round(net, 4), r=round(r, 3))
    day = _add_day_r(net / RISK_USD if RISK_USD else r)   # günlük sınır dolar bazında (1R = RISK_USD)
    kind = rec.get("exit_kind", "kapandı")
    emoji = {"TP": "🎯", "stop": "🛑", "erken çıkış": "⚠️"}.get(kind, "⚪")
    nm, ntot, nn = risk_mult(extra=[rec])
    # Mesajdaki R, "Bugün toplam" ile aynı birimde: 1R = RISK_USD (20.10 düzeltmesi: 0.5x riskli işlemde TP "+2R" görünüyordu,
    # oysa 15$ ölçüsünde ~+1R). İşlemin kendi riskine göre R (rec["r"], momentum kuralı bunu kullanır) yanında not olarak yazılır.
    r_unit = net / RISK_USD if RISK_USD else r
    own = (f"; işlemin kendi riskine göre {r:+.2f}R" if abs(risk_usd - RISK_USD) > 1e-9 else "")
    _say(f"{emoji} <b>{rec['side']} {html.escape(sym)}</b>: {kind} → <b>{r_unit:+.2f}R ({net:+.2f}$)</b> "
         f"(risk {risk_usd:g}$ = {risk_usd / RISK_USD if RISK_USD else 1:g}x{own}, komisyon {fee:.3f}$). "
         f"Bugün toplam {day:+.2f}R ({day * RISK_USD:+.2f}$).\n"
         f"Sıradaki işlemin riski: {RISK_USD * nm:g}$ ({mult_text(nm, ntot, nn)}).")
    if day <= -DAILY_LOSS_R:
        _say(f"⛔ Bugün {day:+.2f}R: günlük zarar sınırı (-{DAILY_LOSS_R:g}R) doldu, yarına kadar yeni işlem açılmayacak.")


# ------------------------------------------------------------------ izleme döngüsü
def check_once():
    """Bekleyen girişler doldu mu, açık pozisyonlar kapandı mı (her POLL_SEC saniyede)."""
    if api is None:
        return
    with _lock:
        t = trades()
        changed = False
        for key, rec in t.items():
            if rec["status"] not in ("pending", "open"):
                continue
            try:
                sym, side = rec["symbol"], rec["side"]
                qty, _ = _our_position(sym, side)
                if rec["status"] == "pending":
                    if qty > 0:
                        changed = True
                        _protect(rec, qty)
                    elif time.time() - rec["created"] > 4 * config.tf_minutes(rec.get("tf", "15m")) * 60 + 120:
                        _cancel_entry(rec, "giriş penceresi doldu")   # canlı takip kaçırırsa yedek
                        changed = True
                elif qty > 0 and rec.get("sl_algo") and rec["qty"] != _q(qty, _filters(sym)["step"]):
                    changed = True
                    _resize(rec, qty)       # kullanıcı elle ekleme / azaltma yaptı: stop ve TP bütün pozisyona
                elif qty > 0 and (not rec.get("sl_algo") or (not rec.get("tp_order") and rec.get("tp_tries", 0) < 5)):
                    changed = True
                    _protect(rec, qty)      # önceki deneme bağlantı hatasıyla yarım kaldı
                elif qty <= 0:
                    kind = "stop"
                    if rec.get("tp_order"):
                        try:
                            if api.get_order(sym, rec["tp_cid"]).get("status") == "FILLED":
                                kind = "TP"
                        except BinanceError:
                            pass
                    _cleanup_orders(rec)
                    rec["exit_kind"] = kind
                    _finish(rec)
                    changed = True
            except BinanceError as e:
                if e.code == -418:
                    break   # IP engeli: borsadaki stop/TP pozisyonu korur, engel bitince devam
                log.warning("OTO kontrol hatası %s: %s", key, e)
            except Exception as e:
                log.exception("OTO kontrol hatası %s: %s", key, e)
        if changed:
            _save_trades(t)   # hata olsa bile yarım kalan adımlar kaydedilir, sonraki döngü tamamlar


def _loop():
    while True:
        try:
            if any(x["status"] in ("pending", "open") for x in trades().values()):
                check_once()
        except Exception as e:
            log.exception("OTO döngü hatası: %s", e)
        time.sleep(POLL_SEC)


def start(send_message):
    global _send
    _send = send_message
    threading.Thread(target=_ip_loop, daemon=True).start()
    if api is None:
        return
    threading.Thread(target=_loop, daemon=True).start()


# ------------------------------------------------------------------ çıkış IP'si
# Render'ın çıkış IP'leri paylaşılan /24 aralıkları (Frankfurt: 74.220.51.0/24, 74.220.59.0/24); Binance IP izni sadece
# tek tek IP kabul ediyor ve IP kısıtlaması olmadan Futures yetkili anahtarı siliyor. Bu yüzden botun gerçekte
# kullandığı IP izlenir; yeni bir IP görülürse kullanıcıya "Binance'e ekle" diye haber verilir.
IP_URLS = ("https://api.ipify.org", "https://checkip.amazonaws.com", "https://ifconfig.me/ip")
IP_CHECK_SEC = 600


def public_ip():
    import re
    for u in IP_URLS:
        try:
            ip = requests.get(u, timeout=5).text.strip()
            if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", ip):
                return ip
        except requests.RequestException:
            continue
    return None


def seen_ips():
    return _load("ip_seen.json", {})


def _note_ip(ip):
    """IP'yi kaydet; daha önce görülmemişse True."""
    seen = seen_ips()
    new = ip not in seen
    seen.setdefault(ip, time.time())
    _save("ip_seen.json", seen)
    return new


def _ip_loop():
    first = True
    while True:
        try:
            ip = public_ip()
            if ip:
                had = bool(seen_ips())
                new = _note_ip(ip)
                # IP genelde yeniden başlatmada değişir: ilk kontrolde de (daha önce IP kaydı varsa) uyar (17.10 düzeltmesi)
                if new and (had or not first) and api is not None:
                    _say(f"⚠️ Botun internet çıkış IP'si değişti: <code>{ip}</code>\n"
                         f"Otomatik işlem için Binance → API Management → Edit restrictions → trusted IPs listesine "
                         f"bu IP'yi ekle (eskileri silme). Tüm görülen IP'ler: /ip")
        except Exception as e:
            log.debug("IP kontrolü: %s", e)
        first = False
        time.sleep(IP_CHECK_SEC)


def ip_text():
    ip = public_ip()
    if ip:
        _note_ip(ip)
    seen = seen_ips()
    others = [x for x in sorted(seen, key=seen.get) if x != ip]
    return (f"🌐 Botun şu anki internet çıkış IP'si: <code>{ip or 'bulunamadı'}</code>\n"
            "Binance → API Management → Edit restrictions → <b>Restrict access to trusted IPs only</b> → bu IP'yi ekle → "
            "sonra <b>Enable Futures</b>'ı işaretle → Save.\n"
            + (f"Daha önce görülen IP'ler (hepsi listede olmalı): " + ", ".join(f"<code>{x}</code>" for x in others)
               if others else "Şimdiye kadar başka IP görülmedi.")
            + "\nRender IP'yi değiştirirse bot yeni IP'yi buraya yazar.")


# ------------------------------------------------------------------ Telegram /oto
def _perm_check():
    """(sorun listesi, açıklama satırı). Sorun varsa otomatik işlem açılmaz."""
    try:
        r = api.restrictions()
    except Exception as e:
        return [], f"Anahtar yetkileri okunamadı ({html.escape(str(e))[:120]})"
    bad = []
    if not r.get("enableFutures"):
        bad.append("Enable Futures kapalı (Binance → Edit restrictions → Enable Futures işaretle)")
    if r.get("enableWithdrawals"):
        bad.append("PARA ÇEKME yetkisi AÇIK: güvenlik için kapat (Enable Withdrawals işaretini kaldır)")
    if not r.get("ipRestrict"):
        bad.append("IP kısıtlaması yok (Binance Futures yetkili anahtarı siler; /ip'deki IP'yi ekle)")
    yes = lambda v: "✅" if v else "❌"
    line = (f"Anahtar: Futures {yes(r.get('enableFutures'))} · IP kısıtlı {yes(r.get('ipRestrict'))} · "
            f"para çekme {'⚠️ AÇIK' if r.get('enableWithdrawals') else 'kapalı ✅'}")
    return bad, line


def summary_lines(recs=None, since=None):
    """Kapanmış gerçek otomatik işlemlerin özeti (24.10, kullanıcı: "kâr / stop oranı yazsın"). R = 1R (RISK_USD) ölçüsünde
    gerçek $ / RISK_USD; elle ekleme / elle kapatma dahil (borsadaki gerçek sonuç). TP / erken çıkış kaydından, diğer kapanışlar
    zararlıysa stop, kârlıysa "elle / diğer" sayılır (bot TP emri dolmadan kapanan pozisyonu "stop" diye kaydediyor)."""
    recs = trades() if recs is None else recs
    done = [x for x in recs.values() if x.get("status") == "closed" and x.get("pnl") is not None
            and (since is None or float(x.get("closed", 0)) >= since)]
    if not done:
        return ["📊 Gerçek işlemler: henüz kapanan işlem yok"]
    done.sort(key=lambda x: float(x.get("closed", 0)))

    def kind(x):
        k = x.get("exit_kind", "")
        if k == "TP":
            return "tp"
        if k == "erken çıkış":
            return "early"
        return "stop" if float(x["pnl"]) < 0 else "other"

    def block(xs):
        n = len(xs)
        usd = sum(float(x["pnl"]) for x in xs)
        c = {k: sum(1 for x in xs if kind(x) == k) for k in ("tp", "stop", "early", "other")}
        wins = sum(1 for x in xs if float(x["pnl"]) > 0)
        parts = [f"✅ TP {c['tp']}", f"❌ Stop {c['stop']}", f"↩️ Erken {c['early']}"]
        if c["other"]:
            parts.append(f"✋ Elle/diğer kârda {c['other']}")
        return n, usd, wins, " · ".join(parts)

    first = time.strftime("%d.%m", time.gmtime(float(done[0].get("created", done[0]["closed"])) + TZ_OFFSET))
    n, usd, wins, parts = block(done)
    r = usd / RISK_USD if RISK_USD else 0.0
    lines = [f"📊 <b>Gerçek işlemler</b> (ilk işlem {first}, toplam {n}): {parts}",
             f"  Kazanan {wins}/{n} (%{100 * wins / n:.0f}) · {'🟢' if usd > 0 else '🔴'} <b>{r:+.2f}R ({usd:+.2f}$)</b> · "
             f"işlem başı {r / n:+.2f}R"]
    best = max(done, key=lambda x: float(x["pnl"]))
    worst = min(done, key=lambda x: float(x["pnl"]))
    lines.append(f"  En iyi {html.escape(best['symbol'])} {float(best['pnl']):+.2f}$ · "
                 f"en kötü {html.escape(worst['symbol'])} {float(worst['pnl']):+.2f}$")
    groups = {}
    for x in done:
        m = float(x.get("risk_mult", 1.0) or 1.0)
        groups.setdefault(m, []).append(x)
    if len(groups) > 1 or 1.0 not in groups:
        g = []
        for m in sorted(groups, reverse=True):
            xs = groups[m]
            u = sum(float(x["pnl"]) for x in xs)
            g.append(f"{m:g}x: {len(xs)} işlem {u:+.2f}$")
        lines.append("  Risk çarpanına göre: " + " · ".join(g))
    added = [x for x in done if float(x.get("risk_usd", 0)) > RISK_USD * float(x.get("risk_mult", 1.0) or 1.0) * 1.05]
    if added:
        u = sum(float(x["pnl"]) for x in added)
        lines.append(f"  Elle ekleme yapılanlar: {len(added)} işlem {u:+.2f}$")
    return lines


def status_text():
    if api is None:
        return ("🤖 Otomatik işlem: <b>kurulmamış</b>. Render → Environment'a BINANCE_API_KEY ve "
                "BINANCE_API_SECRET eklenmeli (para çekme yetkisi KAPALI, sadece Reading + Futures).")
    s = state()
    lines = [f"🤖 Otomatik işlem: <b>{'AÇIK' if s.get('enabled') else 'KAPALI'}</b> "
             f"(1R = {RISK_USD:g}$, izole, kaldıraç işlem başı otomatik en fazla {LEVERAGE}x, en fazla {MAX_OPEN} işlem, "
             f"günlük sınır -{DAILY_LOSS_R:g}R = -{DAILY_LOSS_R * RISK_USD:g}$)"]
    try:
        with _lock:
            avail, total = api.usdt_balance()
        lines.append(f"Bakiye: {total:.2f} USDT (kullanılabilir {avail:.2f})")
        lines.append("Pozisyon modu: " + ("çift yön (hedge)" if _dual() else "tek yön"))
        bad, line = _perm_check()
        lines.append(line)
        lines.extend(f"⚠️ {b}" for b in bad)
    except BinanceError as e:
        lines.append(f"⚠️ Binance'e bağlanılamadı: {html.escape(str(e))[:200]}")
        if e.code == -2015:
            lines.append(f"→ Anahtar, IP ya da yetki sorunu. Botun IP'si: <code>{public_ip()}</code> (Binance'te izinli "
                         f"IP listesinde olmalı, Enable Futures işaretli olmalı). Ayrıntı: /ip")
    except Exception as e:
        lines.append(f"⚠️ Binance'e bağlanılamadı: {html.escape(str(e))[:200]}")
    act = [x for x in trades().values() if x["status"] in ("pending", "open")]
    for x in act:
        lines.append(f"• {x['side']} {html.escape(x['symbol'])}: "
                     + ("giriş bekliyor" if x["status"] == "pending" else f"açık ({_fmt(x['fill'] or 0)})"))
    days = s.get("days", {})
    lines.append(f"Bugün: {days.get(_today(), 0.0):+.2f}R · Son 30 gün: {sum(days.values()):+.2f}R")
    try:
        lines.extend(summary_lines())
    except Exception as e:   # özet bozulsa da /oto çalışsın
        log.warning("OTO özet hatası: %s", e)
    m, tot, n = risk_mult()
    lines.append(f"Sıradaki işlemin riski: {RISK_USD * m:g}$ ({mult_text(m, tot, n)}; artıda {MOMENTUM_UP:g}x, "
                 f"ekside {MOMENTUM_DOWN:g}x)")
    return "\n".join(lines)


def command(text):
    low = text.lower()
    if "aç" in low or " ac" in low or low.endswith("ac"):
        if api is None:
            return status_text()
        try:
            avail, total = api.usdt_balance()
        except Exception as e:
            return f"⚠️ Binance'e bağlanılamadı, açılmadı: {html.escape(str(e))[:200]}"
        bad, line = _perm_check()
        if bad:
            return "🤖 Otomatik işlem <b>AÇILMADI</b>:\n" + "\n".join(f"⚠️ {b}" for b in bad) + f"\n{line}"
        _set_state(enabled=True)
        return (f"🤖 Otomatik işlem <b>AÇILDI</b>. Bakiye {total:.2f} USDT. Bundan sonraki EMİR HAZIR'larda "
                f"{RISK_USD:g}$ riskle işlem açılacak (son {MOMENTUM_HOURS:g} saatte kapanan işlemler artıdaysa "
                f"{RISK_USD * MOMENTUM_UP:g}$, ekside {RISK_USD * MOMENTUM_DOWN:g}$). Durdurmak için /oto kapat")
    if "kapa" in low:
        _set_state(enabled=False)
        act = [x for x in trades().values() if x["status"] in ("pending", "open")]
        extra = (f"\nAçık/bekleyen {len(act)} işlem borsadaki stop/TP ile yönetilmeye devam ediyor; istersen Binance'ten "
                 f"elle kapat.") if act else ""
        return "🤖 Otomatik işlem <b>KAPATILDI</b>, yeni işlem açılmayacak." + extra
    return status_text()
