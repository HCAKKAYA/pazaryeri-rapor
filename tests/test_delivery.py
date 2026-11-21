import email
import smtplib
from datetime import date
from email import policy

import pytest

from cli import slugify
from rapor import mailer, pdf
from rapor.alerts import Alert
from rapor.fmt import num, tl
from rapor.metrics import Period
from rapor.narrative import Narrative

CUR = Period(date(2026, 11, 9), date(2026, 11, 15), 134713.0, 20000.0, 70000.0, 17811.0, 493, 700, 50, 10)
PREV = Period(date(2026, 11, 2), date(2026, 11, 8), 149000.0, 22000.0, 76000.0, 19627.0, 465, 760, 40, 8)
ALERTS = [Alert("kritik", "Kablosuz Kulaklık: stokta yok", "ayrıntı"), Alert("bilgi", "X: maliyet bilinmiyor", "b")]
STORY = Narrative(ozet="Kısa özet.", oneriler=[{"baslik": "Stok", "aciklama": "Yenileyin."}], kaynak="yapay zeka")


def test_rounding_is_stable():
    assert num(11497.4999999) == num(11497.5000001) == "11.498"
    assert tl(-0.2) == "0 ₺"
    assert tl(-296.4) == "−296 ₺"


def test_slugify():
    assert slugify("Örnek Mağaza") == "ornek-magaza"
    assert slugify("  Çiçek & Şeker Ltd. ") == "cicek-seker-ltd"
    assert slugify("!!!") == "magaza"


def _pdf(tmp_path):
    p = tmp_path / "rapor.pdf"
    p.write_bytes(b"%PDF-1.4 test")
    return p


def test_build_message(tmp_path):
    msg = mailer.build("Örnek Mağaza", ["a@ornek.com", "b@ornek.com"], CUR, PREV, STORY, ALERTS, _pdf(tmp_path), "rapor@ornek.com")
    assert "1 kritik uyarı" in msg["Subject"] and "Örnek Mağaza" in msg["Subject"]
    assert msg["To"] == "a@ornek.com, b@ornek.com"
    parsed = email.message_from_bytes(bytes(msg), policy=policy.default)
    html = parsed.get_body(("html",)).get_content()
    text = parsed.get_body(("plain",)).get_content()
    assert "Kısa özet." in html and "Stok" in html
    assert "maliyet bilinmiyor" not in html        # bilgi seviyesi e-postaya girmez
    assert "Kablosuz Kulaklık" in text
    att = [p for p in parsed.iter_attachments()]
    assert len(att) == 1 and att[0].get_filename() == "rapor.pdf" and att[0].get_content()[:4] == b"%PDF"


@pytest.mark.parametrize("bad", [[], ["yanlis"], ["a@b.com", "c@"]])
def test_bad_recipients(bad):
    with pytest.raises(mailer.MailError):
        mailer.build("M", bad, CUR, PREV, STORY, ALERTS, None)


def test_rule_story_hides_recommendations(tmp_path):
    rule = Narrative(ozet="Kural özeti.", oneriler=[{"baslik": "GİZLİ", "aciklama": ""}], kaynak="kural")
    msg = mailer.build("M", ["a@b.com"], CUR, PREV, rule, ALERTS, None)
    assert "GİZLİ" not in bytes(msg).decode("utf-8", "ignore")


class FakeSMTP:
    instances = []

    def __init__(self, host, port, timeout=None, **kw):
        self.host, self.port, self.log = host, port, []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self, context=None):
        self.log.append("starttls")

    def login(self, user, password):
        if password == "yanlis":
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        self.log.append(("login", user))

    def send_message(self, msg):
        self.log.append(("send", msg["To"]))


def test_send_uses_starttls_and_login(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    msg = mailer.build("M", ["a@b.com"], CUR, PREV, STORY, ALERTS, None)
    mailer.send(msg, mailer.SmtpConfig("smtp.ornek.com", 587, "u@ornek.com", "p", "u@ornek.com"))
    s = FakeSMTP.instances[-1]
    assert s.log == ["starttls", ("login", "u@ornek.com"), ("send", "a@b.com")]


def test_send_auth_error_is_explained(monkeypatch):
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    msg = mailer.build("M", ["a@b.com"], CUR, PREV, STORY, ALERTS, None)
    with pytest.raises(mailer.MailError, match="uygulama şifresi"):
        mailer.send(msg, mailer.SmtpConfig("h", 587, "u", "yanlis", "u@x.com"))


def test_smtp_config_requires_env(monkeypatch):
    for k in ("SMTP_SUNUCU", "SMTP_KULLANICI", "SMTP_PAROLA"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(mailer.MailError, match="SMTP_SUNUCU"):
        mailer.SmtpConfig.from_env()


def test_html_to_pdf(tmp_path):
    try:
        pdf.find_browser()
    except pdf.PdfError:
        pytest.skip("tarayıcı yok")
    h = tmp_path / "ç ş.html"
    h.write_text("<!doctype html><meta charset='utf-8'><h1>Merhaba ğüşıöç</h1>", encoding="utf-8")
    out = pdf.html_to_pdf(h, tmp_path / "out.pdf")
    assert out.read_bytes()[:4] == b"%PDF"
