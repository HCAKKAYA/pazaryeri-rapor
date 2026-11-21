"""Haftalık raporu e-postaya çevirir ve (istenirse) SMTP ile gönderir.

Varsayılan davranış GÖNDERMEK DEĞİL: e-posta `.eml` taslak dosyası olarak yazılır,
Outlook/Thunderbird ile açılıp kontrol edilebilir. Gerçek gönderim yalnız
`--gonder` verildiğinde ve SMTP ayarları ortam değişkenlerinde tanımlıysa yapılır:

  SMTP_SUNUCU   ör. smtp.gmail.com
  SMTP_PORT     587 (STARTTLS, varsayılan) ya da 465 (SSL)
  SMTP_KULLANICI
  SMTP_PAROLA   Gmail'de normal parola değil "uygulama şifresi"
  SMTP_GONDEREN isteğe bağlı; yoksa SMTP_KULLANICI

Parola koda ya da dosyaya yazılmaz.
"""
from __future__ import annotations

import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .fmt import pct, tl
from .metrics import Period, pct_change

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)
_env.globals.update(tl=tl, pct=pct)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailError(RuntimeError):
    pass


@dataclass
class SmtpConfig:
    host: str
    port: int
    user: str
    password: str
    sender: str

    @classmethod
    def from_env(cls) -> "SmtpConfig":
        missing = [k for k in ("SMTP_SUNUCU", "SMTP_KULLANICI", "SMTP_PAROLA") if not os.environ.get(k)]
        if missing:
            raise MailError("SMTP ayarı eksik: " + ", ".join(missing))
        user = os.environ["SMTP_KULLANICI"]
        return cls(
            host=os.environ["SMTP_SUNUCU"],
            port=int(os.environ.get("SMTP_PORT", "587")),
            user=user,
            password=os.environ["SMTP_PAROLA"],
            sender=os.environ.get("SMTP_GONDEREN", user),
        )


def subject_for(store: str, cur: Period, prev: Period, alerts) -> str:
    ch = pct(pct_change(cur.net_profit, prev.net_profit), sign=True)
    crit = sum(1 for a in alerts if a.level == "kritik")
    tail = f" · {crit} kritik uyarı" if crit else ""
    return f"{store} haftalık rapor {cur.start:%d.%m}–{cur.end:%d.%m}: net kâr {tl(cur.net_profit)} ({ch}){tail}"


def _plain(store, cur, prev, narrative, alerts) -> str:
    lines = [f"{store} · {cur.start:%d.%m}–{cur.end:%d.%m.%Y}", "",
             f"Net kâr: {tl(cur.net_profit)} (geçen hafta {tl(prev.net_profit)})", "", narrative.ozet, ""]
    if narrative.kaynak == "yapay zeka":
        lines += [f"{i}. {o['baslik']} {o['aciklama']}" for i, o in enumerate(narrative.oneriler, 1)] + [""]
    crit = [a for a in alerts if a.level != "bilgi"]
    if crit:
        lines.append("Bakılması gerekenler:")
        lines += [f"- [{a.label}] {a.title} — {a.detail}" for a in crit]
        lines.append("")
    lines.append("Grafikler ve ürün tablosu ekteki PDF'te.")
    return "\n".join(lines)


def build(store: str, recipients: list[str], cur: Period, prev: Period, narrative, alerts,
          pdf_path: Path | None, sender: str = "rapor@localhost") -> EmailMessage:
    bad = [r for r in recipients if not _EMAIL.match(r)]
    if not recipients or bad:
        raise MailError(f"Geçersiz alıcı: {bad or '(boş)'}")

    subject = subject_for(store, cur, prev, alerts)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((f"{store} rapor", sender))
    msg["To"] = ", ".join(recipients)
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1])
    msg.set_content(_plain(store, cur, prev, narrative, alerts))
    html = _env.get_template("eposta.html.j2").render(
        subject=subject, store=store, cur=cur, prev=prev, narrative=narrative,
        alerts=alerts, ch_net=pct_change(cur.net_profit, prev.net_profit),
    )
    msg.add_alternative(html, subtype="html")
    if pdf_path:
        pdf_path = Path(pdf_path)
        msg.add_attachment(pdf_path.read_bytes(), maintype="application", subtype="pdf",
                           filename=pdf_path.name)
    return msg


def save_draft(msg: EmailMessage, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(msg))
    return path


def send(msg: EmailMessage, cfg: SmtpConfig, timeout: int = 30) -> None:
    ctx = ssl.create_default_context()
    try:
        if cfg.port == 465:
            with smtplib.SMTP_SSL(cfg.host, cfg.port, context=ctx, timeout=timeout) as s:
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg.host, cfg.port, timeout=timeout) as s:
                s.starttls(context=ctx)
                s.login(cfg.user, cfg.password)
                s.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise MailError("SMTP girişi reddedildi (Gmail'de uygulama şifresi gerekir)") from e
    except (smtplib.SMTPException, OSError) as e:
        raise MailError(f"E-posta gönderilemedi: {e}") from e
