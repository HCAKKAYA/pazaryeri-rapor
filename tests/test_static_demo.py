import json
from datetime import date

from rapor import static_demo


def test_build_static_site(tmp_path):
    out = tmp_path / "site"
    static_demo.build(out, today=date(2026, 12, 1), make_pdf=False)
    for name in ("index.html", "panel.js", "rapor.html", ".nojekyll"):
        assert (out / name).exists(), name
    html = (out / "index.html").read_text(encoding="utf-8")
    assert 'data-statik="1"' in html and "/cikis" not in html and "{{" not in html
    assert 'href="rapor.html"' in html          # PDF yokken HTML rapora bağlanır
    for days in static_demo.PRESETS:
        j = json.loads((out / "veri" / f"ozet-{days}.json").read_text(encoding="utf-8"))
        assert j["demo"] is True
        assert j["aralik"]["gun"] == days and j["aralik"]["bit"] == "2026-11-30"
        assert len(j["gunluk"]) == days and j["kpi"][0]["ad"] == "Net kâr"
        assert j["aralik"]["onceki_tam"] is True   # demo, en uzun dönemin önceki eşini de kapsar
    seven = json.loads((out / "veri" / "ozet-7.json").read_text(encoding="utf-8"))
    assert any("stokta yok" in u["baslik"] for u in seven["uyarilar"])


def test_panel_js_uses_relative_static_paths():
    from rapor import dashboard
    js = (dashboard.STATIC / "panel.js").read_text(encoding="utf-8")
    assert "veri/ozet-${state.days}.json" in js   # başında / yok: Pages alt dizinde çalışır
