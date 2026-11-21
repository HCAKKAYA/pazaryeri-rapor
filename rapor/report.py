"""Hesaplanmış sayılardan HTML rapor üretir."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import charts
from .alerts import Alert
from .clean import Quality
from .fmt import num, pct, tl
from .metrics import Period, pct_change

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),
)
_env.globals.update(tl=tl, pct=pct, num=num)


def render(store: str, week: str, cur: Period, prev: Period, series: list[Period],
           prod, alerts: list[Alert], q: Quality, narrative=None) -> str:
    ch = SimpleNamespace(
        net_profit=pct_change(cur.net_profit, prev.net_profit),
        gross=pct_change(cur.gross, prev.gross),
        orders=pct_change(cur.orders, prev.orders),
        avg_basket=pct_change(cur.avg_basket, prev.avg_basket),
    )
    return _env.get_template("rapor.html.j2").render(
        store=store, week=week, cur=cur, prev=prev, ch=ch, alerts=alerts, narrative=narrative,
        products=list(prod.itertuples()), q=q, quality=q.notes(),
        chart_weekly=charts.weekly_profit(series),
        chart_products=charts.product_profit(prod),
    )
