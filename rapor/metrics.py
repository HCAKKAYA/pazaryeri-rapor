"""KPI tanımları. Sayıların tamamı burada, SQL ile hesaplanır; sonradan eklenecek
yapay zeka katmanı sayı üretmez, yalnız bu çıktıyı yorumlar.

Tanımlar (gerçek satıcıyla doğrulanacak varsayımlar işaretli):
- Brüt satış: teslim edilen / yoldaki satırların adet x birim fiyatı. İade ve iptal hariç.
- Komisyon: brüt satış x komisyon oranı. İadede komisyon geri döner (varsayım).
- Kargo: sipariş başına bir kez; teslim ve İADE siparişlerinde satıcıya kalır (varsayım).
- Ürün maliyeti: adet x ürün dosyasındaki birim maliyet.
- Net kâr: brüt - komisyon - kargo - maliyet. KDV ve reklam gideri henüz yok.
- İade oranı: iade adet / (teslim + iade adet).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import duckdb
import pandas as pd

_PERIOD_SQL = """
WITH l AS (
    SELECT * FROM lines WHERE day BETWEEN ? AND ?
),
ship AS (
    SELECT order_id, MAX(shipping_fee) AS fee
    FROM l WHERE status IN ('delivered', 'returned')
    GROUP BY order_id
)
SELECT
    COALESCE(SUM(gross)      FILTER (WHERE status = 'delivered'), 0) AS gross,
    COALESCE(SUM(commission) FILTER (WHERE status = 'delivered'), 0) AS commission,
    COALESCE(SUM(cogs)       FILTER (WHERE status = 'delivered'), 0) AS cogs,
    (SELECT COALESCE(SUM(fee), 0) FROM ship)                          AS shipping,
    COUNT(DISTINCT order_id) FILTER (WHERE status = 'delivered')      AS orders,
    COALESCE(SUM(quantity)   FILTER (WHERE status = 'delivered'), 0) AS units,
    COALESCE(SUM(quantity)   FILTER (WHERE status = 'returned'), 0)  AS returned_units,
    COUNT(DISTINCT order_id) FILTER (WHERE status = 'cancelled')      AS cancelled_orders
FROM l
"""


@dataclass
class Period:
    start: date
    end: date
    gross: float
    commission: float
    cogs: float
    shipping: float
    orders: int
    units: float
    returned_units: float
    cancelled_orders: int

    @property
    def net_profit(self) -> float:
        return self.gross - self.commission - self.shipping - self.cogs

    @property
    def margin(self) -> float | None:
        return self.net_profit / self.gross if self.gross else None

    @property
    def avg_basket(self) -> float | None:
        return self.gross / self.orders if self.orders else None

    @property
    def return_rate(self) -> float | None:
        total = self.units + self.returned_units
        return self.returned_units / total if total else None


def week_bounds(iso_week: str) -> tuple[date, date]:
    """'2026-W46' -> (pazartesi, pazar)."""
    y, w = iso_week.split("-W")
    start = date.fromisocalendar(int(y), int(w), 1)
    return start, start + timedelta(days=6)


def latest_full_week(con: duckdb.DuckDBPyConnection) -> str:
    """Verideki son tarihin içinde olduğu hafta pazar günü bitiyorsa onu, değilse bir öncekini döndürür."""
    last = con.execute("SELECT MAX(day) FROM lines").fetchone()[0]
    if last.isoweekday() != 7:
        last = last - timedelta(days=last.isoweekday())
    y, w, _ = last.isocalendar()
    return f"{y}-W{w:02d}"


def period(con: duckdb.DuckDBPyConnection, start: date, end: date) -> Period:
    row = con.execute(_PERIOD_SQL, [start, end]).fetchone()
    return Period(start, end, *row)


def weekly_series(con: duckdb.DuckDBPyConnection, end_week: str, n: int = 8) -> list[Period]:
    start, _ = week_bounds(end_week)
    out = []
    for i in range(n - 1, -1, -1):
        s = start - timedelta(weeks=i)
        out.append(period(con, s, s + timedelta(days=6)))
    return out


def products(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    """Ürün bazında bu dönem ve son 28 günün özeti, stokla birlikte."""
    win_start = end - timedelta(days=27)
    return con.execute("""
        WITH l AS (
            SELECT *,
                   shipping_fee / COUNT(*) OVER (PARTITION BY order_id) AS ship_share
            FROM lines
        ),
        agg AS (
            SELECT
                barcode,
                ANY_VALUE(name) AS name,
                SUM(gross)    FILTER (WHERE status = 'delivered' AND day BETWEEN $s AND $e) AS gross,
                SUM(quantity) FILTER (WHERE status = 'delivered' AND day BETWEEN $s AND $e) AS units,
                SUM(gross - commission - cogs) FILTER (WHERE status = 'delivered' AND day BETWEEN $s AND $e)
                  - COALESCE(SUM(ship_share) FILTER (WHERE status IN ('delivered','returned') AND day BETWEEN $s AND $e), 0)
                  AS net_profit,
                SUM(quantity) FILTER (WHERE status = 'delivered' AND day BETWEEN $w AND $e) AS units_28d,
                SUM(quantity) FILTER (WHERE status = 'returned'  AND day BETWEEN $w AND $e) AS returned_28d,
                SUM(gross - commission - cogs) FILTER (WHERE status = 'delivered' AND day BETWEEN $w AND $e)
                  - COALESCE(SUM(ship_share) FILTER (WHERE status IN ('delivered','returned') AND day BETWEEN $w AND $e), 0)
                  AS net_profit_28d,
                BOOL_OR(cost_missing) AS cost_missing
            FROM l
            GROUP BY barcode
        )
        SELECT a.*, p.stock
        FROM agg a LEFT JOIN products p USING (barcode)
        ORDER BY net_profit DESC NULLS LAST
    """, {"s": start, "e": end, "w": win_start}).df().assign(
        gross=lambda d: d["gross"].fillna(0),
        units=lambda d: d["units"].fillna(0),
        net_profit=lambda d: d["net_profit"].fillna(0),
        units_28d=lambda d: d["units_28d"].fillna(0),
        returned_28d=lambda d: d["returned_28d"].fillna(0),
        net_profit_28d=lambda d: d["net_profit_28d"].fillna(0),
    ).assign(
        return_rate_28d=lambda d: d["returned_28d"] / (d["units_28d"] + d["returned_28d"]).where(lambda x: x > 0),
        stock_days=lambda d: d["stock"] / (d["units_28d"] / 28).where(lambda x: x > 0),
    )


def daily(con: duckdb.DuckDBPyConnection, start: date, end: date) -> pd.DataFrame:
    """Gün gün brüt satış, net kâr ve sipariş. Toplamı period() ile birebir aynıdır:
    kargo, siparişin ilk satırının gününe yazılır."""
    return con.execute("""
        WITH l AS (SELECT * FROM lines WHERE day BETWEEN $s AND $e),
        ship AS (
            SELECT MIN(day) AS day, MAX(shipping_fee) AS fee
            FROM l WHERE status IN ('delivered', 'returned') GROUP BY order_id
        ),
        sday AS (SELECT day, SUM(fee) AS fee FROM ship GROUP BY day),
        g AS (
            SELECT day,
                   SUM(gross) FILTER (WHERE status = 'delivered')                    AS gross,
                   SUM(gross - commission - cogs) FILTER (WHERE status = 'delivered') AS contrib,
                   COUNT(DISTINCT order_id) FILTER (WHERE status = 'delivered')     AS orders
            FROM l GROUP BY day
        ),
        days AS (
            SELECT CAST(range AS DATE) AS day
            FROM range(CAST($s AS TIMESTAMP), CAST($e AS TIMESTAMP) + INTERVAL 1 DAY, INTERVAL 1 DAY)
        )
        SELECT days.day,
               COALESCE(g.gross, 0)                             AS gross,
               COALESCE(g.contrib, 0) - COALESCE(sday.fee, 0)   AS net_profit,
               COALESCE(g.orders, 0)                            AS orders
        FROM days LEFT JOIN g USING (day) LEFT JOIN sday USING (day)
        ORDER BY days.day
    """, {"s": start, "e": end}).df()


def data_bounds(con: duckdb.DuckDBPyConnection) -> tuple[date, date, object]:
    """Verideki ilk gün, son gün ve son siparişin zamanı."""
    return con.execute("SELECT MIN(day), MAX(day), MAX(order_date) FROM lines").fetchone()


def pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)
