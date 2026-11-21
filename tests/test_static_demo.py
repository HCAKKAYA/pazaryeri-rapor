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


def test_no_key_no_questions_file(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = tmp_path / "site"
    static_demo.build(out, today=date(2026, 12, 1), make_pdf=False)
    assert not (out / "veri" / "sorular.json").exists()      # anahtar yoksa hazır soru yok, kutu gizli


def test_prepared_questions_with_fake_model(tmp_path, monkeypatch):
    """Sahte modelle: başarılı ve cevaplanamaz sorular yayınlanır, hatalı soru yayınlanmaz; anahtar sayfaya girmez."""
    from types import SimpleNamespace

    from rapor import soru

    def resp(d):
        return SimpleNamespace(stop_reason="end_turn", usage=None,
                               content=[SimpleNamespace(type="text", text=json.dumps(d, ensure_ascii=False))])

    class FakeModel:
        def __init__(self):
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

        def create(self, **kw):
            if kw["system"] == soru.ANSWER_SYSTEM:
                return resp({"cevap": "Tablo aşağıda."})
            q = kw["messages"][0]["content"].split("Soru: ", 1)[1]
            if "reklam" in q:
                return resp({"cevaplanabilir": False, "sql": "", "aciklama": "Veride reklam yok."})
            if "İade" in q:
                return resp({"cevaplanabilir": True, "sql": "DROP VIEW satis", "aciklama": "x"})   # hep hatalı
            return resp({"cevaplanabilir": True, "sql": "SELECT SUM(net_kar) AS net_kar FROM satis", "aciklama": "toplam"})

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-gizli-test-anahtari")
    out = tmp_path / "site"
    static_demo.build(out, today=date(2026, 12, 1), make_pdf=False, client=FakeModel())
    j = json.loads((out / "veri" / "sorular.json").read_text(encoding="utf-8"))
    sorular = {x["soru"]: x for x in j["sorular"]}
    assert len(sorular) == len(static_demo.ORNEK_SORULAR) - 1           # hatalı olan atlandı
    assert sorular["Geçen ay reklama ne kadar harcadım?"]["durum"] == "cevaplanamaz"
    assert all(x["durum"] in ("ok", "cevaplanamaz") for x in sorular.values())
    for f in out.rglob("*"):
        if f.is_file():
            assert b"sk-ant-gizli" not in f.read_bytes(), f              # anahtar hiçbir dosyaya sızmadı


def test_panel_js_uses_relative_static_paths():
    from rapor import dashboard
    js = (dashboard.STATIC / "panel.js").read_text(encoding="utf-8")
    assert "veri/ozet-${state.days}.json" in js   # başında / yok: Pages alt dizinde çalışır
