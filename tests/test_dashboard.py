import io
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from rapor import auth, clean, dashboard, metrics, sample, storage

ROOT = Path(__file__).parent.parent
PW = "dogru-parola-123"


@pytest.fixture()
def env(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "mapping.yaml", tmp_path / "config" / "mapping.yaml")
    sample.generate(tmp_path / "gelen" / "a")
    cfg = {"magazalar": [
        {"ad": "Mağaza A", "klasor": "gelen/a", "siparis_desen": "siparis*.xlsx", "urun_desen": "urun*.csv"},
        {"ad": "Mağaza B", "klasor": "gelen/b", "siparis_desen": "siparis*.xlsx", "urun_desen": "urun*.csv"},
    ]}
    (tmp_path / "config" / "magazalar.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    app = dashboard.create_app(root=tmp_path, db_path=tmp_path / "data" / "panel.db", https=False)
    app.state.users.add_user("a@ornek.com", PW, "magaza-a")
    app.state.users.add_user("b@ornek.com", PW, "magaza-b")
    return TestClient(app), tmp_path


def login(c, email="a@ornek.com", pw=PW):
    return c.post("/giris", data={"eposta": email, "parola": pw}, follow_redirects=False)


# ------------------------------------------------------------------ hesap

def test_password_hash_roundtrip():
    h = auth.hash_password("parola-12345")
    assert h.startswith("scrypt$") and "parola" not in h
    assert auth.check_password("parola-12345", h) and not auth.check_password("Parola-12345", h)


def test_short_password_and_duplicate_rejected(tmp_path):
    s = auth.AuthStore(tmp_path / "a.db")
    with pytest.raises(auth.AuthError):
        s.add_user("x@y.com", "kisa", "m")
    s.add_user("x@y.com", "uzun-parola-1", "m")
    with pytest.raises(auth.AuthError):
        s.add_user("X@Y.com", "uzun-parola-2", "m")


def test_session_token_not_stored_in_plain(tmp_path):
    s = auth.AuthStore(tmp_path / "a.db")
    s.add_user("x@y.com", "uzun-parola-1", "m")
    tok = s.login("x@y.com", "uzun-parola-1", "1.1.1.1")
    assert s.user_for(tok).store == "m"
    assert (tmp_path / "a.db").read_bytes().find(tok.encode()) == -1
    s.set_password("x@y.com", "yeni-parola-12")
    assert s.user_for(tok) is None   # parola değişince oturum kapanır


def test_rate_limit(tmp_path):
    s = auth.AuthStore(tmp_path / "a.db")
    s.add_user("x@y.com", "uzun-parola-1", "m")
    for _ in range(auth.MAX_FAILS):
        with pytest.raises(auth.AuthError, match="hatalı"):
            s.login("x@y.com", "yanlis", "2.2.2.2")
    with pytest.raises(auth.AuthError, match="15 dakika"):
        s.login("x@y.com", "uzun-parola-1", "2.2.2.2")   # doğru parola da bekler


# ------------------------------------------------------------------ panel

def test_requires_login(env):
    c, _ = env
    assert c.get("/panel", follow_redirects=False).headers["location"] == "/giris"
    assert c.get("/api/ozet").status_code == 401
    assert c.post("/api/yukle", data={"tur": "siparis"}, files={"dosya": ("s.xlsx", b"x")}).status_code == 401


def test_login_flow_and_headers(env):
    c, _ = env
    bad = login(c, pw="yanlis")
    assert bad.headers["location"] == "/giris?hata=1" and "oturum" not in bad.cookies
    r = login(c)
    assert r.status_code == 303 and r.headers["location"] == "/panel"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    page = c.get("/panel")
    assert page.status_code == 200 and "Mağaza A" in page.text and "a@ornek.com" in page.text
    assert "script-src 'self' https://cdnjs.cloudflare.com" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert c.get("/static/panel.js").status_code == 200
    c.post("/cikis")
    assert c.get("/api/ozet").status_code == 401


def test_secure_cookie_when_https(env, tmp_path):
    _, root = env
    app = dashboard.create_app(root=root, db_path=root / "data" / "panel.db", https=True)
    r = login(TestClient(app, base_url="https://testserver"))
    assert "secure" in r.headers["set-cookie"].lower()
    assert "strict-transport-security" in r.headers


def test_user_sees_only_own_store(env):
    c, _ = env
    login(c, "b@ornek.com")
    r = c.get("/api/ozet")
    assert r.status_code == 404 and "dosya yükleyin" in r.json()["detail"]   # B'nin verisi yok, A'nınki görünmez


def test_cross_site_post_rejected(env):
    c, _ = env
    r = c.post("/giris", data={"eposta": "a@ornek.com", "parola": PW},
               headers={"origin": "https://kotu-site.com"}, follow_redirects=False)
    assert r.status_code == 403


def test_summary(env):
    c, _ = env
    login(c)
    j = c.get("/api/ozet").json()
    assert j["aralik"]["bit"] == "2026-11-15" and j["aralik"]["gun"] == 28
    assert len(j["gunluk"]) == 28 and len(j["urunler"]) == 12
    assert any("stokta yok" in u["baslik"] for u in j["uyarilar"])
    j7 = c.get("/api/ozet?bas=2026-11-09&bit=2026-11-15").json()
    assert j7["aralik"]["gun"] == 7 and j7["aralik"]["onceki_bas"] == "2026-11-02"
    assert c.get("/api/ozet?bas=2026-11-01&bit=2027-01-01").json()["aralik"]["bit"] == "2026-11-15"
    assert c.get("/api/ozet?bas=2026-11-15&bit=2026-11-01").status_code == 400
    # Örnek veri 8 hafta: 8 haftalık dönemin önceki eşi veride yok, değişim gösterilmemeli.
    j56 = c.get("/api/ozet?bas=2026-09-21&bit=2026-11-15").json()
    assert j56["aralik"]["onceki_tam"] is False
    assert all(k["degisim"] is None for k in j56["kpi"]) and j56["kpi"][0]["onceki"] == "veri yok"
    assert not any("Net kâr düştü" in u["baslik"] for u in j56["uyarilar"])
    assert j7["aralik"]["onceki_tam"] is True


def test_daily_sums_to_period(env):
    _, root = env
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")
    a = root / "gelen" / "a"
    con = storage.build(":memory:", clean.load_orders(a / "siparisler.xlsx", cfg, clean.Quality()),
                        clean.load_products(a / "urunler.csv", cfg))
    s, e = date(2026, 10, 19), date(2026, 11, 15)
    d, per = metrics.daily(con, s, e), metrics.period(con, s, e)
    assert len(d) == 28
    assert d.net_profit.sum() == pytest.approx(per.net_profit, abs=0.05)
    assert d.gross.sum() == pytest.approx(per.gross)
    assert d.orders.sum() == per.orders


# ------------------------------------------------------------------ yükleme

def test_bad_upload_keeps_old_data(env):
    c, root = env
    login(c)
    before = c.get("/api/ozet").json()["kpi"][0]["deger"]
    files_before = sorted(p.name for p in (root / "gelen" / "a").iterdir())
    bad = io.BytesIO()
    pd.DataFrame({"Yanlış": [1]}).to_excel(bad, index=False)
    r = c.post("/api/yukle", data={"tur": "siparis"}, files={"dosya": ("siparis.xlsx", bad.getvalue())})
    assert r.status_code == 400
    assert sorted(p.name for p in (root / "gelen" / "a").iterdir()) == files_before
    r = c.post("/api/yukle", data={"tur": "siparis"}, files={"dosya": ("x.csv", b"a;b")})
    assert r.status_code == 400 and ".xlsx" in r.json()["detail"]
    assert c.get("/api/ozet").json()["kpi"][0]["deger"] == before


def test_upload_strips_personal_data(env):
    c, root = env
    login(c)
    df = pd.read_excel(root / "gelen" / "a" / "siparisler.xlsx", dtype=object)
    df = df[df["Sipariş Tarihi"].astype(str).str.contains(r"\.(?:09|10)\.2026", na=False)].copy()
    df["Alıcı Adı"] = "Ayşe Yılmaz"
    df["Telefon"] = "05551112233"
    df["Teslimat Adresi"] = "Örnek Mah. 1. Sok. No:2"
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r = c.post("/api/yukle", data={"tur": "siparis"}, files={"dosya": ("benim_dosyam.xlsx", buf.getvalue())})
    assert r.status_code == 200, r.text
    saved = root / "gelen" / "a" / r.json()["dosya"]
    kept = pd.read_excel(saved, dtype=object)
    assert not {"Alıcı Adı", "Telefon", "Teslimat Adresi"} & set(kept.columns)
    assert "Ayşe" not in saved.read_bytes().decode("latin-1")
    assert not list((root / "gelen" / "a").glob("yukleniyor-*"))
    j = c.get("/api/ozet").json()
    assert j["veri"]["son_gun"] == "2026-10-31" and j["veri"]["siparis_dosyasi"].startswith("siparis-")
