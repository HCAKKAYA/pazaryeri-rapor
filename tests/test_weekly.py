import json
import shutil
from datetime import date
from pathlib import Path

import pytest
import yaml

from rapor import mailer, pipeline, sample, weekly

ROOT = Path(__file__).parent.parent


@pytest.mark.parametrize("today, want", [
    (date(2026, 11, 16), "2026-W46"),   # pazartesi -> biten hafta
    (date(2026, 11, 21), "2026-W46"),   # cumartesi -> hafta bitmedi, bir önceki
    (date(2026, 11, 22), "2026-W46"),   # pazar -> hafta henüz bitmedi
    (date(2026, 11, 23), "2026-W47"),
    (date(2027, 1, 4), "2026-W53"),     # yıl dönümü
])
def test_expected_week(today, want):
    assert pipeline.expected_week(today) == want


@pytest.fixture()
def root(tmp_path):
    """Gerçek proje dosyalarına dokunmadan geçici bir proje kökü."""
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config" / "mapping.yaml", tmp_path / "config" / "mapping.yaml")
    sample.generate(tmp_path / "gelen" / "a")
    return tmp_path


def _config(root, gonder, alicilar=("a@ornek.com",), extra=None):
    stores = [{"ad": "Mağaza A", "klasor": "gelen/a", "siparis_desen": "siparis*.xlsx",
               "urun_desen": "urun*.csv", "alicilar": list(alicilar), "gonder": gonder}]
    stores += extra or []
    cfg = {"smtp": {"sunucu": "smtp.ornek.com", "port": 587, "kullanici": "u@ornek.com"}, "magazalar": stores}
    p = root / "config" / "magazalar.yaml"
    p.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return p


@pytest.fixture()
def sent(monkeypatch):
    """SMTP yerine gönderilenleri listeye yazar; parola kasası yerine sabit parola."""
    box = []
    monkeypatch.setattr(mailer, "send", lambda msg, cfg: box.append((msg["To"], msg["Subject"], cfg.sender)))
    monkeypatch.setattr(mailer, "get_password", lambda user: "parola")
    monkeypatch.setattr(pipeline.pdf, "html_to_pdf", lambda h, p: (_ for _ in ()).throw(pipeline.pdf.PdfError("testte yok")))
    return box


def _run(root, cfgp, today, **kw):
    return weekly.run_all(cfgp, today=today, use_ai=False, root=root, **kw)


def test_sends_once_per_week(root, sent):
    cfgp = _config(root, gonder=True)
    r1 = _run(root, cfgp, date(2026, 11, 16))
    assert [x["durum"] for x in r1] == ["gonderildi"] and len(sent) == 1
    assert sent[0][0] == "a@ornek.com" and sent[0][2] == "u@ornek.com"
    r2 = _run(root, cfgp, date(2026, 11, 17))
    assert r2[0]["durum"] == "atlandi" and "daha önce" in r2[0]["ayrinti"] and len(sent) == 1
    assert json.loads((root / "data" / "gonderilenler.json").read_text(encoding="utf-8")) == {"magaza-a": ["2026-W46"]}


def test_stale_data_is_not_sent(root, sent):
    cfgp = _config(root, gonder=True)
    r = _run(root, cfgp, date(2026, 11, 23))   # beklenen W47, dosya W46'da bitiyor
    assert r[0]["durum"] == "atlandi" and "güncel değil" in r[0]["ayrinti"] and sent == []


def test_stale_data_does_not_call_ai(root, sent, monkeypatch):
    """Gönderilmeyecek rapor için model çağrılmaz (boşuna API harcaması olmasın)."""
    calls = []
    monkeypatch.setattr(pipeline.narrative, "write", lambda *a, **k: calls.append(1))
    cfgp = _config(root, gonder=True)
    r = weekly.run_all(cfgp, today=date(2026, 11, 23), use_ai=True, root=root)
    assert r[0]["durum"] == "atlandi" and calls == [] and sent == []


def test_fresh_data_still_uses_ai(root, sent, monkeypatch):
    calls = []
    real_rule_based = pipeline.narrative.rule_based

    def fake_write(facts, found):
        calls.append(1)
        return real_rule_based(facts, found, "test")

    monkeypatch.setattr(pipeline.narrative, "write", fake_write)
    cfgp = _config(root, gonder=True)
    r = weekly.run_all(cfgp, today=date(2026, 11, 16), use_ai=True, root=root)
    assert r[0]["durum"] == "gonderildi" and calls == [1]


def test_gonder_false_only_drafts(root, sent):
    cfgp = _config(root, gonder=False)
    r = _run(root, cfgp, date(2026, 11, 16))
    assert r[0]["durum"] == "taslak" and sent == []
    assert (root / "raporlar" / "magaza-a-2026-W46.eml").exists()


def test_dry_run_never_sends(root, sent):
    cfgp = _config(root, gonder=True)
    r = _run(root, cfgp, date(2026, 11, 16), dry_run=True)
    assert r[0]["durum"] == "taslak" and sent == []


def test_one_failure_does_not_stop_others(root, sent):
    broken = {"ad": "Bozuk", "klasor": "gelen/bozuk", "siparis_desen": "*.xlsx", "urun_desen": "*.csv",
              "alicilar": ["b@ornek.com"], "gonder": True}
    (root / "gelen" / "bozuk").mkdir(parents=True)
    (root / "gelen" / "bozuk" / "s.xlsx").write_bytes(b"bu excel degil")
    (root / "gelen" / "bozuk" / "u.csv").write_text("a;b\n1;2\n", encoding="utf-8")
    empty = {"ad": "Boş", "klasor": "gelen/yok", "alicilar": [], "gonder": False}
    cfgp = _config(root, gonder=True, extra=[broken, empty])
    r = {x["magaza"]: x["durum"] for x in _run(root, cfgp, date(2026, 11, 16))}
    assert r == {"Mağaza A": "gonderildi", "Bozuk": "hata", "Boş": "atlandi"}


def test_missing_password_is_an_error_not_a_crash(root, sent, monkeypatch):
    monkeypatch.setattr(mailer, "get_password", lambda user: None)
    cfgp = _config(root, gonder=True)
    r = _run(root, cfgp, date(2026, 11, 16))
    assert r[0]["durum"] == "hata" and "sifre-kaydet" in r[0]["ayrinti"] and sent == []
