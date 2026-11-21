"""Satıcı paneli: seçilen döneme göre KPI, günlük grafik, ürün tablosu, uyarılar,
ve satıcının yeni dışa aktarım dosyasını kendisinin yüklemesi.

Veri "anlık" değildir: en son yüklenen dosya kadar günceldir. Panel bunu açıkça gösterir.

Erişim: her mağazanın gizli bir bağlantısı vardır (/m/<mağaza>?k=<anahtar>). Bu bir
prototip erişimidir, kullanıcı girişi değildir; internete açmadan önce gerçek giriş,
HTTPS ve oturum yönetimi gerekir. Varsayılan olarak yalnız bu bilgisayardan erişilir.
"""
from __future__ import annotations

import hmac
import json
import secrets
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse

from . import alerts as alerts_mod
from . import clean, metrics, pipeline, storage, weekly
from .fmt import num, pct, tl

ROOT = pipeline.ROOT
MAX_UPLOAD = 25 * 1024 * 1024
TEMPLATE = Path(__file__).parent / "templates" / "panel.html"


# ---------------------------------------------------------------- erişim anahtarları

def load_keys(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def ensure_keys(slugs: list[str], path: Path) -> dict:
    keys = load_keys(path)
    changed = False
    for s in slugs:
        if s not in keys:
            keys[s] = secrets.token_urlsafe(18)
            changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(keys, indent=1), encoding="utf-8")
    return keys


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
        self.con = storage.build(":memory:", orders, products)
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

    cur = metrics.period(con, start, end)
    prev = metrics.period(con, pstart, pend)
    prod = metrics.products(con, start, end)
    found = alerts_mod.build(cur, prev, prod)
    days = metrics.daily(con, start, end)

    def kpi(label, value, prev_value, fmt, change=True):
        ch = metrics.pct_change(value, prev_value) if change else None
        return {"ad": label, "deger": fmt(value), "onceki": fmt(prev_value),
                "degisim": pct(ch, sign=True) if ch is not None else None,
                "yon": None if ch is None else ("up" if ch > 0 else "down" if ch < 0 else "flat")}

    o, p = store.files
    return {
        "magaza": store.name,
        "aralik": {"bas": start.isoformat(), "bit": end.isoformat(), "gun": length,
                   "onceki_bas": pstart.isoformat(), "onceki_bit": pend.isoformat()},
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
            "net": round(float(r.net_profit), 2),
            "iade": None if r.return_rate_28d != r.return_rate_28d else round(float(r.return_rate_28d), 4),
            "stok": None if r.stock != r.stock or r.stock is None else float(r.stock),
            "gun_yeter": None if r.stock_days != r.stock_days else round(float(r.stock_days), 1),
        } for r in prod.itertuples()],
        "uyarilar": [{"seviye": a.level, "etiket": a.label, "baslik": a.title, "ayrinti": a.detail} for a in found],
    }


# ---------------------------------------------------------------- uygulama

def create_app(config_path: Path | None = None, keys_path: Path | None = None, root: Path = ROOT) -> FastAPI:
    cfg = yaml.safe_load((config_path or root / "config" / "magazalar.yaml").read_text(encoding="utf-8")) or {}
    mapping = clean.load_mapping(root / "config" / "mapping.yaml")
    stores: dict[str, Store] = {}
    for m in cfg.get("magazalar", []):
        folder = Path(m["klasor"]) if Path(m["klasor"]).is_absolute() else root / m["klasor"]
        s = Store(m["ad"], pipeline.slugify(m["ad"]), folder,
                  m.get("siparis_desen", "siparis*.xlsx"), m.get("urun_desen", "urun*.csv"))
        stores[s.slug] = s
    keys = ensure_keys(list(stores), keys_path or root / "data" / "panel_anahtarlari.json")

    app = FastAPI(title="Pazaryeri paneli", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.stores, app.state.keys = stores, keys

    def auth(slug: str, k: str | None) -> Store:
        store = stores.get(slug)
        # Mağaza yoksa da anahtar yanlışsa da aynı yanıt: hangi mağazaların var olduğu sızmasın.
        if not store or not k or not hmac.compare_digest(k, keys.get(slug, "")):
            raise HTTPException(404, "Bulunamadı")
        return store

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse("<p style='font-family:sans-serif'>Mağaza bağlantınızla girin.</p>")

    @app.get("/m/{slug}", response_class=HTMLResponse)
    def page(slug: str, k: str | None = Query(None)):
        store = auth(slug, k)
        html = TEMPLATE.read_text(encoding="utf-8").replace("{{MAGAZA}}", store.name)
        return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

    @app.get("/api/{slug}/ozet")
    def api_summary(slug: str, k: str | None = Query(None), bas: date | None = None, bit: date | None = None):
        store = auth(slug, k)
        with store.lock:
            store.refresh(mapping)
            return summary(store, bas, bit)

    @app.post("/api/{slug}/yukle")
    async def upload(slug: str, k: str | None = Query(None), tur: str = Form(...), dosya: UploadFile = File(...)):
        store = auth(slug, k)
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
        # Geçici ad desene uymaz ("yukleniyor-" ile başlar), yarım dosya hiçbir zaman okunmaz.
        tmp = store.folder / f"yukleniyor-{target.name}"
        tmp.write_bytes(data)
        try:
            # Dosya okunamıyorsa klasöre girmesin; eski veri bozulmasın.
            if tur == "siparis":
                q = clean.Quality()
                df = clean.load_orders(tmp, mapping, q)
                info = f"{q.rows_used} sipariş satırı okundu."
            else:
                df = clean.load_products(tmp, mapping)
                info = f"{len(df)} ürün okundu."
            if df.empty:
                raise ValueError("dosyada kullanılabilir satır yok")
        except Exception as e:
            tmp.unlink(missing_ok=True)
            raise HTTPException(400, f"Dosya okunamadı: {e}")
        tmp.replace(target)
        with store.lock:
            store._sig = None
        return {"tamam": True, "mesaj": f"Yüklendi. {info}", "dosya": target.name}

    return app


def links(app: FastAPI, host: str, port: int) -> list[str]:
    return [f"http://{host}:{port}/m/{slug}?k={app.state.keys[slug]}" for slug in app.state.stores]
