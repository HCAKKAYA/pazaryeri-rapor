"""Bir mağaza için uçtan uca akış: dosya → rapor → PDF → e-posta."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from . import alerts, clean, mailer, metrics, narrative, pdf, report, storage
from .fmt import tl

ROOT = Path(__file__).resolve().parent.parent
_TR = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")


def slugify(name: str) -> str:
    s = name.translate(_TR).lower()
    return "-".join(filter(None, "".join(c if c.isalnum() else " " for c in s).split())) or "magaza"


def expected_week(today: date) -> str:
    """Bugünden önceki son pazar gününün haftası (pazartesi çalışınca bir önceki hafta;
    pazar günü çalışırsa o hafta henüz bitmediği için yine bir önceki)."""
    last_sunday = today - timedelta(days=today.isoweekday())
    y, w, _ = last_sunday.isocalendar()
    return f"{y}-W{w:02d}"


@dataclass
class Result:
    store: str
    week: str
    html: Path
    pdf: Path | None = None
    eml: Path | None = None
    msg: object = None             # email.message.EmailMessage; gönderilmeden önce saklanır
    sent: bool = False
    notes: list[str] = field(default_factory=list)
    net_profit: float = 0.0
    alert_count: int = 0


def run(store: str, orders_path: Path, products_path: Path, *, week: str | None = None,
        use_ai: bool = True, make_pdf: bool = True, recipients: list[str] | None = None,
        send_cfg: "mailer.SmtpConfig | None" = None, out_dir: Path | None = None,
        db_dir: Path | None = None, sender: str = "rapor@localhost") -> Result:
    """send_cfg verilirse e-posta gönderilir; verilmezse yalnız taslak yazılır."""
    out_dir = out_dir or ROOT / "raporlar"
    db_dir = db_dir or ROOT / "data"
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")

    q = clean.Quality()
    orders = clean.load_orders(Path(orders_path), cfg, q)
    products = clean.load_products(Path(products_path), cfg)
    known = set(products.loc[products["cost"].notna(), "barcode"])
    q.missing_cost = sorted(set(orders.loc[~orders["barcode"].isin(known), "product_name"].dropna()))

    slug = slugify(store)
    con = storage.build(db_dir / f"{slug}.duckdb", orders, products)
    week = week or metrics.latest_full_week(con)
    start, end = metrics.week_bounds(week)
    cur = metrics.period(con, start, end)
    prev = metrics.period(con, start - timedelta(days=7), end - timedelta(days=7))
    series = metrics.weekly_series(con, week, 8)
    prod = metrics.products(con, start, end)
    found = alerts.build(cur, prev, prod)
    con.close()

    facts = narrative.build_facts(week, cur, prev, series, prod, found)
    story = narrative.write(facts, found) if use_ai else narrative.rule_based(facts, found, "yapay zeka kapalı")

    out_dir.mkdir(parents=True, exist_ok=True)
    html_path = out_dir / f"{slug}-{week}.html"
    html_path.write_text(report.render(store, week, cur, prev, series, prod, found, q, story), encoding="utf-8")
    res = Result(store, week, html_path, net_profit=cur.net_profit, alert_count=len(found))
    res.notes.append(f"Yorum: {story.kaynak}" + (f" ({story.not_})" if story.not_ else ""))
    res.notes.append(f"{week}: net kâr {tl(cur.net_profit)}, {len(found)} uyarı -> {html_path}")

    if make_pdf:
        try:
            res.pdf = pdf.html_to_pdf(html_path, html_path.with_suffix(".pdf"))
            res.notes.append(f"PDF -> {res.pdf}")
        except pdf.PdfError as e:
            res.notes.append(f"PDF üretilemedi: {e}")

    if recipients:
        if send_cfg:
            sender = send_cfg.sender
        msg = mailer.build(store, recipients, cur, prev, story, found, res.pdf, sender)
        res.msg = msg
        res.eml = mailer.save_draft(msg, html_path.with_suffix(".eml"))
        res.notes.append(f"E-posta taslağı -> {res.eml}")
        if send_cfg:
            mailer.send(msg, send_cfg)
            res.sent = True
            res.notes.append(f"Gönderildi: {', '.join(recipients)}")
    return res
