import json
from types import SimpleNamespace

import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient

from rapor import dashboard, degerlendirme, soru


@pytest.fixture(scope="module")
def con():
    return degerlendirme.eval_connection()


def _resp(payload, stop="end_turn"):
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return SimpleNamespace(stop_reason=stop, content=[SimpleNamespace(type="text", text=text)])


class Fake:
    """Sırayla hazır yanıt döndüren sahte Claude istemcisi."""
    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


def sql(q, ok=True, why="sorgu"):
    return _resp({"cevaplanabilir": ok, "sql": q, "aciklama": why})


def answer(text):
    return _resp({"cevap": text})


# ------------------------------------------------------------------ güvenlik

@pytest.mark.parametrize("q", [
    "DROP VIEW satis", "SELECT 1; DROP VIEW satis", "DELETE FROM orders", "SELECT * FROM read_csv('x.csv')",
    "ATTACH 'x.db'", "SELECT 1 -- yorum", "/* x */ SELECT 1", "PRAGMA database_list", "COPY satis TO 'x.csv'", "",
])
def test_guard_rejects(q):
    with pytest.raises(soru.GuardError):
        soru.guard(q)


def test_guard_allows_select_and_strings():
    assert soru.guard("SELECT 'drop' AS x;") == "SELECT 'drop' AS x"
    assert soru.guard("with a as (select 1) select * from a").startswith("with")


def test_sandbox_blocks_files_and_settings(con):
    with pytest.raises(Exception):
        con.execute("SELECT * FROM read_csv('config/mapping.yaml')")
    with pytest.raises(Exception):
        con.execute("SET enable_external_access = true")


def test_satis_view_matches_metrics(con):
    # Asistanın gördüğü görünüm, panelin hesaplarıyla aynı sayıyı vermeli.
    from datetime import date
    from rapor import metrics
    got = con.execute("SELECT SUM(net_kar) FROM satis WHERE tarih BETWEEN '2026-11-09' AND '2026-11-15'").fetchone()[0]
    assert got == pytest.approx(metrics.period(con, date(2026, 11, 9), date(2026, 11, 15)).net_profit)


# ------------------------------------------------------------------ akış

def test_ask_ok_with_verified_answer(con):
    c = soru.ask("Bu hafta net kâr?", con, client=Fake(
        sql("SELECT SUM(net_kar) AS net_kar FROM satis WHERE tarih BETWEEN DATE '2026-11-09' AND DATE '2026-11-15'"),
        answer("Bu hafta net kârınız 26.902 ₺.")))
    assert c.durum == "ok" and c.satirlar == [["26.902 ₺"]] and c.cevap.startswith("Bu hafta")


def test_invented_number_in_answer_is_dropped(con):
    c = soru.ask("Toplam ciro?", con, client=Fake(
        sql("SELECT SUM(brut_satis) AS ciro FROM satis"), answer("Ciro yaklaşık 1,2 milyon ₺.")))
    assert c.durum == "ok" and c.cevap == "" and c.satirlar   # tablo var, uydurma cevap yok


def test_retry_after_sql_error(con):
    f = Fake(sql("SELECT SUM(olmayan_sutun) FROM satis"), sql("SELECT COUNT(*) AS siparis_sayisi FROM satis"), answer("Tamam."))
    c = soru.ask("Kaç satır?", con, client=f)
    assert c.durum == "ok" and c.deneme == 2
    assert "olmayan_sutun" in f.calls[1]["messages"][-1]["content"]


def test_dangerous_sql_never_runs(con):
    before = con.execute("SELECT COUNT(*) FROM satis").fetchone()
    c = soru.ask("Sil", con, client=Fake(sql("DROP VIEW satis"), sql("DELETE FROM orders")))
    assert c.durum == "hata" and con.execute("SELECT COUNT(*) FROM satis").fetchone() == before


def test_unanswerable(con):
    c = soru.ask("Reklama ne harcadım?", con, client=Fake(sql("", ok=False, why="Veride reklam gideri yok.")))
    assert c.durum == "cevaplanamaz" and "reklam" in c.aciklama


def test_request_shape(con):
    f = Fake(sql("SELECT 1 AS adet"), answer("1"))
    soru.ask("x", con, client=f)
    first = f.calls[0]
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["output_config"]["format"]["type"] == "json_schema"
    assert "15.11.2026" in first["messages"][0]["content"]     # göreli tarihler için verinin son günü


def test_no_key_falls_back_cleanly(con, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    err = TypeError("Could not resolve authentication method. Expected one of api_key")
    f = Fake()
    f.beta.messages.create = lambda **kw: (_ for _ in ()).throw(err)
    assert soru.ask("x", con, client=f).hata == "API anahtarı tanımlı değil"


# ------------------------------------------------------------------ değerlendirme

def test_compare_rules():
    ref = pd.DataFrame({"urun": ["A", "B"], "v": [0.25, 10.0]})
    assert degerlendirme.compare(ref, pd.DataFrame({"x": [10.0, 25.0], "u": ["B", "A"]}), ordered=False)[0]
    assert not degerlendirme.compare(ref, pd.DataFrame({"x": [10.0, 25.0], "u": ["B", "A"]}), ordered=True)[0]
    assert not degerlendirme.compare(ref, ref.head(1), ordered=False)[0]
    assert degerlendirme.compare(ref, ref.assign(ek=1), ordered=True)[0]          # fazladan sütun serbest


def test_harness_with_reference_answers():
    """Modeli referans SQL'i yazan bir sahteyle değiştirince değerlendirme %100 vermeli."""
    items = yaml.safe_load(degerlendirme.QUESTIONS.read_text(encoding="utf-8"))
    by_q = {it["soru"]: it for it in items}

    class Oracle:
        def __init__(self):
            self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

        def _create(self, **kw):
            if kw["system"] == soru.ANSWER_SYSTEM:
                return answer("Sonuç tabloda.")
            q = kw["messages"][0]["content"].split("Soru: ", 1)[1]
            it = by_q[q]
            if it.get("beklenen") == "cevaplanamaz":
                return sql("", ok=False, why="veride yok")
            return sql(it["sql"])

    res = degerlendirme.run(client=Oracle(), progress=lambda *_: None)
    assert len(res) == len(items) and all(r.gecti for r in res), [r for r in res if not r.gecti]


# ------------------------------------------------------------------ panel API

def test_api_sor(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path
    root = Path(__file__).parent.parent
    (tmp_path / "config").mkdir()
    shutil.copy(root / "config" / "mapping.yaml", tmp_path / "config" / "mapping.yaml")
    app = dashboard.create_app(root=tmp_path, db_path=tmp_path / "p.db", https=False, demo_mode=True)
    c = TestClient(app)
    c.post("/demo")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert c.get("/api/ozet").json()["soru_acik"] is False
    assert c.post("/api/sor", data={"soru": "x"}).status_code == 503

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(soru, "ask", lambda q, con, client=None: soru.Cevap(soru=q, durum="ok", cevap="tamam"))
    r = c.post("/api/sor", data={"soru": "Toplam ciro?"})
    assert r.status_code == 200 and r.json()["cevap"] == "tamam"
    for _ in range(29):
        c.post("/api/sor", data={"soru": "x"})
    assert c.post("/api/sor", data={"soru": "x"}).status_code == 429
