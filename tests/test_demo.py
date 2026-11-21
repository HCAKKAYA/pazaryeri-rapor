import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from rapor import dashboard, demo

ROOT = Path(__file__).parent.parent


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "mapping.yaml", tmp_path / "config" / "mapping.yaml")
    return tmp_path   # magazalar.yaml YOK: demo onsuz çalışmalı


def test_data_regenerates_only_when_stale(tmp_path):
    f = tmp_path / "demo"
    assert demo.ensure_data(f, today=date(2026, 12, 1)) is True
    assert demo.ensure_data(f, today=date(2026, 12, 1)) is False
    assert demo.ensure_data(f, today=date(2026, 12, 2)) is True
    assert (f / ".demo-bitis").read_text() == "2026-12-01"


def test_demo_flow(root):
    app = dashboard.create_app(root=root, db_path=root / "data" / "panel.db", https=False, demo_mode=True)
    c = TestClient(app)
    page = c.get("/giris")
    assert "Demo'ya gir" in page.text
    r = c.post("/demo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/panel"
    j = c.get("/api/ozet").json()
    assert j["demo"] is True
    assert j["veri"]["son_gun"] == demo.data_end().isoformat()        # veri hep dünkü
    assert any("stokta yok" in u["baslik"] for u in j["uyarilar"])     # desenler son haftada
    r = c.post("/api/yukle", data={"tur": "siparis"}, files={"dosya": ("siparis.xlsx", b"x")})
    assert r.status_code == 403 and "Demo" in r.json()["detail"]


def test_demo_user_cannot_log_in_with_password(root):
    app = dashboard.create_app(root=root, db_path=root / "data" / "panel.db", https=False, demo_mode=True)
    c = TestClient(app)
    r = c.post("/giris", data={"eposta": demo.DEMO_EMAIL, "parola": ""}, follow_redirects=False)
    assert r.headers["location"].startswith("/giris?hata")


def test_demo_endpoint_off_outside_demo(root):
    (root / "config" / "magazalar.yaml").write_text("magazalar: []\n", encoding="utf-8")
    app = dashboard.create_app(root=root, db_path=root / "data" / "panel.db", https=False, demo_mode=False)
    c = TestClient(app)
    assert c.post("/demo").status_code == 404
    assert "Demo'ya gir" not in c.get("/giris").text
