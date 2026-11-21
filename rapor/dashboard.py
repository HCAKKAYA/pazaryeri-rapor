"""Satıcı paneli: seçilen döneme göre KPI, günlük grafik, ürün tablosu, uyarılar,
ve satıcının yeni dışa aktarım dosyasını kendisinin yüklemesi.

Veri "anlık" değildir: en son yüklenen dosya kadar günceldir. Panel bunu açıkça gösterir.

Erişim: e-posta ve parolayla giriş (auth.py). Her kullanıcı yalnız kendi mağazasını görür.
İnternette yalnız HTTPS arkasında çalıştırılmalı (PANEL_HTTPS=1 çerezi Secure yapar).
"""
from __future__ import annotations

import os
import secrets
import threading
from html import escape
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import Cookie, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import alerts as alerts_mod
from . import auth, clean, demo, metrics, pipeline, storage, weekly
from .fmt import num, pct, tl

ROOT = pipeline.ROOT
MAX_UPLOAD = 25 * 1024 * 1024
TEMPLATES = Path(__file__).parent / "templates"
STATIC = Path(__file__).parent / "static"
COOKIE = "oturum"


# ---------------------------------------------------------------- mağaza verisi

@dataclass
class Store:
    name: str
    slug: str
    folder: Path
    orders_glob: str
    products_glob: str
    lock: threading.Lock = field(default_factory=threading.Lock)
    _sig: tuple | None = None
    con: object = None
    quality: clean.Quality | None = None
    files: tuple[Path, Path] | None = None
    qcon: object = None            # soru-cevap için ayrı, dış erişimi kapalı bağlantı

    def refresh(self, mapping: dict) -> None:
        """Klasördeki en yeni dosyalar değiştiyse veritabanını yeniden kurar."""
        o = weekly._newest(self.folder, self.orders_glob)
        p = weekly._newest(self.folder, self.products_glob)
        if not o or not p:
            raise HTTPException(404, "Bu mağaza için henüz veri dosyası yok. Panelden dosya yükleyin.")
        sig = (o, o.stat().st_mtime, p, p.stat().st_mtime)
        if sig == self._sig:
            return
        q = clean.Quality()
        orders = clean.load_orders(o, mapping, q)
        products = clean.load_products(p, mapping)
        known = set(products.loc[products["cost"].notna(), "barcode"])
        q.missing_cost = sorted(set(orders.loc[~orders["barcode"].isin(known), "product_name"].dropna()))
        if self.con is not None:
            self.con.close()
        if self.qcon is not None:
            self.qcon.close()
        self.con = storage.build(":memory:", orders, products)
        from . import soru
        self.qcon = soru.sandbox(orders, products)
        self.quality, self.files, self._sig = q, (o, p), sig


def _pattern_name(pattern: str, suffix: str) -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return pattern.replace("*", f"-{stamp}", 1) if "*" in pattern else f"{Path(pattern).stem}-{stamp}{suffix}"


# ---------------------------------------------------------------- yanıt

def summary(store: Store, start: date | None, end: date | None) -> dict:
    con = store.con
    first, last, last_ts = metrics.data_bounds(con)
    end = min(end or last, last)
    start = max(start or end - timedelta(days=27), first)
    if start > end:
        raise HTTPException(400, "Başlangıç tarihi bitişten sonra olamaz.")
    length = (end - start).days + 1
    pstart, pend = start - timedelta(days=length), start - timedelta(days=1)

    # Önceki dönem verinin başlangıcından önceye taşıyorsa karşılaştırma yarım veriyle yapılır
    # ve yanıltır; o durumda değişim gösterilmez.
    prev_ok = pstart >= first
    cur = metrics.period(con, start, end)
    prev = metrics.period(con, pstart, pend)
    prod = metrics.products(con, start, end)
    found = alerts_mod.build(cur, prev if prev_ok else cur, prod)  # eksik önceki dönemle "düşüş" uyarısı üretme
    days = metrics.daily(con, start, end)

    def kpi(label, value, prev_value, fmt, change=True):
        ch = metrics.pct_change(value, prev_value) if (change and prev_ok) else None
        return {"ad": label, "deger": fmt(value), "onceki": fmt(prev_value) if prev_ok else "veri yok",
                "degisim": pct(ch, sign=True) if ch is not None else None,
                "yon": None if ch is None else ("up" if ch > 0 else "down" if ch < 0 else "flat")}

    o, p = store.files
    return {
        "magaza": store.name,
        "aralik": {"bas": start.isoformat(), "bit": end.isoformat(), "gun": length,
                   "onceki_bas": pstart.isoformat(), "onceki_bit": pend.isoformat(), "onceki_tam": prev_ok},
        "veri": {
            "ilk_gun": first.isoformat(), "son_gun": last.isoformat(),
            "son_siparis": last_ts.strftime("%d.%m.%Y %H:%M") if last_ts else None,
            "siparis_dosyasi": o.name,
            "dosya_zamani": datetime.fromtimestamp(o.stat().st_mtime).strftime("%d.%m.%Y %H:%M"),
            "kalite": store.quality.notes(),
        },
        "kpi": [
            kpi("Net kâr", cur.net_profit, prev.net_profit, tl),
            kpi("Brüt satış", cur.gross, prev.gross, tl),
            kpi("Sipariş", cur.orders, prev.orders, num),
            kpi("Sepet ortalaması", cur.avg_basket, prev.avg_basket, tl),
            kpi("Kâr marjı", cur.margin, prev.margin, pct, change=False),
            kpi("İade oranı", cur.return_rate, prev.return_rate, pct, change=False),
        ],
        "gunluk": [{"gun": r.day.isoformat(), "net": round(r.net_profit, 2), "brut": round(r.gross, 2),
                    "siparis": int(r.orders)} for r in days.itertuples()],
        "urunler": [{
            "urun": r.name, "adet": float(r.units), "brut": round(float(r.gross), 2),
            "komisyon": round(float(r.commission), 2), "kargo": round(float(r.shipping), 2),
            "maliyet": round(float(r.cogs), 2), "net": round(float(r.net_profit), 2),
            "marj": None if r.margin != r.margin else round(float(r.margin), 4),
            "adet_basi": None if r.profit_per_unit != r.profit_per_unit else round(float(r.profit_per_unit), 2),
            "iade": None if r.return_rate_28d != r.return_rate_28d else round(float(r.return_rate_28d), 4),
            "stok": None if r.stock != r.stock or r.stock is None else float(r.stock),
            "gun_yeter": None if r.stock_days != r.stock_days else round(float(r.stock_days), 1),
        } for r in prod.itertuples()],
        "urun_toplam": {"brut": round(cur.gross, 2), "komisyon": round(cur.commission, 2),
                        "kargo": round(cur.shipping, 2), "maliyet": round(cur.cogs, 2),
                        "net": round(cur.net_profit, 2), "adet": float(cur.units),
                        "marj": None if cur.margin is None else round(cur.margin, 4)},
        "uyarilar": [{"seviye": a.level, "etiket": a.label, "baslik": a.title, "ayrinti": a.detail} for a in found],
    }


# ---------------------------------------------------------------- KVKK: veri azaltma

def minimize(raw: Path, target: Path, columns: list[str]) -> None:
    """Yüklenen dosyadan yalnız raporun kullandığı sütunları saklar.

    Pazaryeri dışa aktarımlarında müşteri adı, adres, telefon gibi kişisel veriler olabilir;
    bunlar diske hiç yazılmaz (ham dosya silinir).
    """
    df = clean._read_any(raw)
    df = df[[c for c in columns if c in df.columns]]
    if target.suffix.lower() in (".xlsx", ".xls"):
        df.to_excel(target, index=False)
    else:
        df.to_csv(target, index=False, sep=";", encoding="utf-8-sig")


# ---------------------------------------------------------------- uygulama

SECURITY_HEADERS = {
    "Content-Security-Policy": ("default-src 'self'; script-src 'self' https://cdnjs.cloudflare.com; "
                                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; "
                                "frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "same-origin",  # no-referrer olursa tarayıcı formu Origin: null ile yollar
    "Cache-Control": "no-store",
}


def create_app(config_path: Path | None = None, db_path: Path | None = None, root: Path = ROOT,
               https: bool | None = None, demo_mode: bool | None = None) -> FastAPI:
    demo_mode = (os.environ.get("PANEL_DEMO") == "1") if demo_mode is None else demo_mode
    if demo_mode:
        # Demo: tek sentetik mağaza, ayar dosyası gerekmez.
        cfg = {"magazalar": [{"ad": demo.STORE_NAME, "klasor": "gelen/demo"}]}
    else:
        cfg = yaml.safe_load((config_path or root / "config" / "magazalar.yaml").read_text(encoding="utf-8")) or {}
    mapping = clean.load_mapping(root / "config" / "mapping.yaml")
    stores: dict[str, Store] = {}
    for m in cfg.get("magazalar", []):
        folder = Path(m["klasor"]) if Path(m["klasor"]).is_absolute() else root / m["klasor"]
        s = Store(m["ad"], pipeline.slugify(m["ad"]), folder,
                  m.get("siparis_desen", "siparis*.xlsx"), m.get("urun_desen", "urun*.csv"))
        stores[s.slug] = s
    users = auth.AuthStore(db_path or root / "data" / "panel.db")
    secure = (os.environ.get("PANEL_HTTPS") == "1") if https is None else https
    if demo_mode:
        demo.ensure_data(stores[demo.STORE_SLUG].folder)
        if not users.has_user(demo.DEMO_EMAIL):
            # Parolası kimsenin bilmediği rastgele bir değer; girişi yalnız "Demo'ya gir" düğmesi açar.
            users.add_user(demo.DEMO_EMAIL, secrets.token_urlsafe(24), demo.STORE_SLUG)

    app = FastAPI(title="Pazaryeri paneli", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.stores, app.state.users, app.state.demo = stores, users, demo_mode

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        if secure:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000"
        return resp

    def current(token: str | None) -> tuple[auth.User, Store]:
        user = users.user_for(token)
        if not user:
            raise HTTPException(401, "Oturum yok ya da süresi doldu. Yeniden giriş yapın.")
        store = stores.get(user.store)
        if not store:
            raise HTTPException(403, "Bu hesaba bağlı mağaza bulunamadı.")
        return user, store

    def same_origin(request: Request) -> None:
        """Form ve yükleme isteklerinde başka siteden gelen istekleri (CSRF) reddet."""
        origin = request.headers.get("origin")
        if origin and origin.split("://", 1)[-1] != request.headers.get("host"):
            raise HTTPException(403, "İstek reddedildi.")

    def page(name: str, **repl) -> HTMLResponse:
        html = (TEMPLATES / name).read_text(encoding="utf-8")
        for k, v in repl.items():
            html = html.replace("{{" + k + "}}", v)
        return HTMLResponse(html)

    @app.get("/")
    def index(oturum: str | None = Cookie(None)):
        return RedirectResponse("/panel" if users.user_for(oturum) else "/giris", 303)

    @app.get("/giris", response_class=HTMLResponse)
    def login_form(hata: str = ""):
        msg = {"1": "E-posta ya da parola hatalı.", "2": "Çok fazla hatalı deneme. 15 dakika sonra tekrar deneyin.",
               "3": "Oturumunuz kapandı."}.get(hata, "")
        demo_html = ('<form method="post" action="/demo" class="demo"><p>Hesabınız yoksa sentetik verili '
                     'demo mağazaya şifresiz girebilirsiniz.</p><button type="submit" class="ikincil">'
                     "Demo'ya gir</button></form>") if demo_mode else ""
        return page("giris.html", HATA=msg, DEMO=demo_html)

    @app.post("/demo")
    def demo_login(request: Request):
        same_origin(request)
        if not demo_mode:
            raise HTTPException(404, "Bulunamadı")
        token = users.session_for(demo.DEMO_EMAIL, ttl=24 * 3600)
        resp = RedirectResponse("/panel", 303)
        resp.set_cookie(COOKIE, token, max_age=24 * 3600, httponly=True, secure=secure, samesite="lax")
        return resp

    @app.post("/giris")
    def login(request: Request, eposta: str = Form(""), parola: str = Form("")):
        same_origin(request)
        ip = request.client.host if request.client else "?"
        try:
            token = users.login(eposta, parola, ip)
        except auth.AuthError as e:
            return RedirectResponse("/giris?hata=" + ("2" if "15 dakika" in str(e) else "1"), 303)
        resp = RedirectResponse("/panel", 303)
        resp.set_cookie(COOKIE, token, max_age=auth.SESSION_TTL, httponly=True, secure=secure, samesite="lax")
        return resp

    @app.post("/cikis")
    def logout(request: Request, oturum: str | None = Cookie(None)):
        same_origin(request)
        users.logout(oturum)
        resp = RedirectResponse("/giris?hata=3", 303)
        resp.delete_cookie(COOKIE)
        return resp

    @app.get("/panel", response_class=HTMLResponse)
    def panel(oturum: str | None = Cookie(None)):
        user = users.user_for(oturum)
        if not user or user.store not in stores:
            return RedirectResponse("/giris", 303)
        return page("panel.html", MAGAZA=escape(stores[user.store].name), EPOSTA=escape(user.email))

    @app.get("/static/panel.js")
    def static_js():
        return FileResponse(STATIC / "panel.js", media_type="text/javascript")

    @app.get("/api/ozet")
    def api_summary(bas: date | None = None, bit: date | None = None, oturum: str | None = Cookie(None)):
        _, store = current(oturum)
        with store.lock:
            if demo_mode:
                demo.ensure_data(store.folder)
            store.refresh(mapping)
            out = summary(store, bas, bit)
        out["demo"] = demo_mode
        out["soru_acik"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
        return out

    ask_limits: dict[str, list[float]] = {}

    @app.post("/api/sor")
    def api_ask(request: Request, soru_metni: str = Form("", alias="soru"), oturum: str | None = Cookie(None)):
        same_origin(request)
        user, store = current(oturum)
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise HTTPException(503, "Soru sorma özelliği bu kurulumda kapalı (API anahtarı yok).")
        import time as _t
        now = _t.time()
        recent = [t for t in ask_limits.get(user.email, []) if now - t < 3600]
        if len(recent) >= 30:   # kullanıcı başına saatte 30 soru: maliyet ve kötüye kullanım sınırı
            raise HTTPException(429, "Saatlik soru sınırına ulaşıldı. Biraz sonra tekrar deneyin.")
        ask_limits[user.email] = recent + [now]
        from . import soru
        with store.lock:
            store.refresh(mapping)
            qcon = store.qcon
        return soru.ask(soru_metni, qcon).to_dict()

    @app.post("/api/yukle")
    async def upload(request: Request, tur: str = Form(...), dosya: UploadFile = File(...),
                     oturum: str | None = Cookie(None)):
        same_origin(request)
        _, store = current(oturum)
        if demo_mode:
            raise HTTPException(403, "Demo modunda dosya yükleme kapalı.")
        if tur not in ("siparis", "urun"):
            raise HTTPException(400, "Dosya türü siparis ya da urun olmalı.")
        pattern = store.orders_glob if tur == "siparis" else store.products_glob
        want = Path(pattern).suffix.lower()
        got = Path(dosya.filename or "").suffix.lower()
        if got != want:
            raise HTTPException(400, f"Bu alan {want} dosyası bekliyor, gelen: {got or 'uzantısız'}.")
        data = await dosya.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(413, "Dosya 25 MB'tan büyük.")

        store.folder.mkdir(parents=True, exist_ok=True)
        target = store.folder / _pattern_name(pattern, want)
        # Geçici adlar desene uymaz ("yukleniyor-" ile başlar), yarım dosya hiçbir zaman okunmaz.
        raw = store.folder / f"yukleniyor-ham-{target.name}"
        slim = store.folder / f"yukleniyor-{target.name}"
        raw.write_bytes(data)
        try:
            columns = list(mapping["orders" if tur == "siparis" else "products"].values())
            minimize(raw, slim, columns)
            if tur == "siparis":
                q = clean.Quality()
                df = clean.load_orders(slim, mapping, q)
                info = f"{q.rows_used} sipariş satırı okundu."
            else:
                df = clean.load_products(slim, mapping)
                info = f"{len(df)} ürün okundu."
            if df.empty:
                raise ValueError("dosyada kullanılabilir satır yok")
        except Exception as e:
            slim.unlink(missing_ok=True)
            raise HTTPException(400, f"Dosya okunamadı: {e}")
        finally:
            raw.unlink(missing_ok=True)
        slim.replace(target)
        with store.lock:
            store._sig = None
        return {"tamam": True, "mesaj": f"Yüklendi. {info} Yalnız rapor için gereken sütunlar saklandı.",
                "dosya": target.name}

    return app
