import io
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from rapor import clean, dashboard, metrics, sample, storage

ROOT = Path(__file__).parent.parent


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
    app = dashboard.create_app(root=tmp_path)
    return TestClient(app), app.state.keys, tmp_path


def test_daily_sums_to_period():
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")
    o, p = ROOT / "sample_data" / "siparisler.xlsx", ROOT / "sample_data" / "urunler.csv"
    if not o.exists():
        pytest.skip("örnek veri yok")
    con = storage.build(":memory:", clean.load_orders(o, cfg, clean.Quality()), clean.load_products(p, cfg))
    s, e = date(2026, 10, 19), date(2026, 11, 15)
    d, per = metrics.daily(con, s, e), metrics.period(con, s, e)
    assert len(d) == 28
    assert d.net_profit.sum() == pytest.approx(per.net_profit, abs=0.05)
    assert d.gross.sum() == pytest.approx(per.gross)
    assert d.orders.sum() == per.orders  # örnek veride her sipariş tek güne ait


def test_wrong_or_missing_key_is_404_for_everything(env):
    c, keys, _ = env
    for url in ["/m/magaza-a", "/m/magaza-a?k=yanlis", "/api/magaza-a/ozet?k=yanlis",
                f"/api/magaza-a/ozet?k={keys['magaza-b']}", f"/m/yok?k={keys['magaza-a']}"]:
        assert c.get(url).status_code == 404, url


def test_page_and_summary(env):
    c, keys, _ = env
    k = keys["magaza-a"]
    page = c.get(f"/m/magaza-a?k={k}")
    assert page.status_code == 200 and "Mağaza A" in page.text and page.headers["referrer-policy"] == "no-referrer"
    j = c.get(f"/api/magaza-a/ozet?k={k}").json()
    assert j["aralik"]["bit"] == "2026-11-15" and j["aralik"]["gun"] == 28
    assert len(j["gunluk"]) == 28 and len(j["urunler"]) == 12
    assert j["kpi"][0]["ad"] == "Net kâr" and j["kpi"][0]["deger"].endswith("₺")
    assert any("stokta yok" in u["baslik"] for u in j["uyarilar"])
    j7 = c.get(f"/api/magaza-a/ozet?k={k}&bas=2026-11-09&bit=2026-11-15").json()
    assert j7["aralik"]["gun"] == 7 and j7["aralik"]["onceki_bas"] == "2026-11-02"
    # Veri dışına taşan tarih kırpılır.
    jx = c.get(f"/api/magaza-a/ozet?k={k}&bas=2026-11-01&bit=2027-01-01").json()
    assert jx["aralik"]["bit"] == "2026-11-15"
    assert c.get(f"/api/magaza-a/ozet?k={k}&bas=2026-11-15&bit=2026-11-01").status_code == 400


def test_store_without_data(env):
    c, keys, _ = env
    r = c.get(f"/api/magaza-b/ozet?k={keys['magaza-b']}")
    assert r.status_code == 404 and "dosya yükleyin" in r.json()["detail"]


def test_bad_upload_keeps_old_data(env):
    c, keys, root = env
    k = keys["magaza-a"]
    before = c.get(f"/api/magaza-a/ozet?k={k}").json()["kpi"][0]["deger"]
    files_before = sorted(p.name for p in (root / "gelen" / "a").iterdir())
    bad = io.BytesIO()
    pd.DataFrame({"Yanlış": [1]}).to_excel(bad, index=False)
    r = c.post(f"/api/magaza-a/yukle?k={k}", data={"tur": "siparis"},
               files={"dosya": ("siparis.xlsx", bad.getvalue())})
    assert r.status_code == 400 and "beklenen sütun" in r.json()["detail"]
    assert sorted(p.name for p in (root / "gelen" / "a").iterdir()) == files_before
    r = c.post(f"/api/magaza-a/yukle?k={k}", data={"tur": "siparis"}, files={"dosya": ("x.csv", b"a;b")})
    assert r.status_code == 400 and ".xlsx" in r.json()["detail"]
    assert c.get(f"/api/magaza-a/ozet?k={k}").json()["kpi"][0]["deger"] == before


def test_good_upload_updates_dashboard(env):
    c, keys, root = env
    k = keys["magaza-a"]
    df = pd.read_excel(root / "gelen" / "a" / "siparisler.xlsx", dtype=object)
    df = df[df["Sipariş Tarihi"].astype(str).str.contains(r"\.(?:09|10)\.2026", na=False)]  # yalnız Eyl-Eki
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    r = c.post(f"/api/magaza-a/yukle?k={k}", data={"tur": "siparis"},
               files={"dosya": ("benim_dosyam.xlsx", buf.getvalue())})
    assert r.status_code == 200 and r.json()["dosya"].startswith("siparis-")
    j = c.get(f"/api/magaza-a/ozet?k={k}").json()
    assert j["veri"]["son_gun"] == "2026-10-31" and j["veri"]["siparis_dosyasi"].startswith("siparis-")
    assert not list((root / "gelen" / "a").glob("yukleniyor-*"))
