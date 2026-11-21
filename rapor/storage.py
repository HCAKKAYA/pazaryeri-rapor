"""Temiz veriyi müşteri başına bir DuckDB dosyasına yazar."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd


def build(db_path: Path | str, orders: pd.DataFrame, products: pd.DataFrame) -> duckdb.DuckDBPyConnection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    con.register("orders_df", orders)
    con.register("products_df", products)
    con.execute("CREATE OR REPLACE TABLE orders AS SELECT * FROM orders_df")
    con.execute("CREATE OR REPLACE TABLE products AS SELECT * FROM products_df")
    con.unregister("orders_df")
    con.unregister("products_df")
    # Her satır için hesaplanmış tutarlar tek yerde tanımlanır; tüm KPI'lar buradan okur.
    con.execute("""
        CREATE OR REPLACE VIEW lines AS
        SELECT
            o.*,
            CAST(o.order_date AS DATE)                       AS day,
            o.quantity * o.unit_price                        AS gross,
            o.quantity * o.unit_price * o.commission_rate    AS commission,
            o.quantity * COALESCE(p.cost, 0)                 AS cogs,
            p.cost IS NULL                                   AS cost_missing,
            COALESCE(p.product_name, o.product_name)         AS name
        FROM orders o
        LEFT JOIN products p USING (barcode)
    """)
    # Soru-cevap asistanı (soru.py) için Türkçe ve "toplanabilir" görünümler. Her satırda kâr
    # kalemleri hazır: SUM(net_kar) her dönem ve her kırılım için metrics.period() ile aynıdır.
    # Model iş kuralını (kargo sipariş başına, iadede komisyon döner...) yeniden kurmak zorunda kalmaz.
    con.execute("""
        CREATE OR REPLACE VIEW satis AS
        WITH l AS (
            SELECT *,
                   CASE WHEN status IN ('delivered', 'returned')
                        THEN shipping_fee / COUNT(*) FILTER (WHERE status IN ('delivered', 'returned'))
                                                     OVER (PARTITION BY order_id)
                        ELSE 0 END AS ship_share
            FROM lines
        )
        SELECT
            day                                                      AS tarih,
            order_id                                                 AS siparis_no,
            barcode                                                  AS barkod,
            name                                                     AS urun,
            CASE status WHEN 'delivered' THEN 'teslim' WHEN 'returned' THEN 'iade' ELSE 'iptal' END AS durum,
            quantity                                                 AS adet,
            unit_price                                               AS birim_fiyat,
            commission_rate                                          AS komisyon_orani,
            CASE WHEN status = 'delivered' THEN gross ELSE 0 END      AS brut_satis,
            CASE WHEN status = 'delivered' THEN commission ELSE 0 END AS komisyon,
            CASE WHEN status = 'delivered' THEN cogs ELSE 0 END       AS urun_maliyeti,
            ship_share                                               AS kargo,
            CASE WHEN status = 'delivered' THEN gross - commission - cogs ELSE 0 END - ship_share AS net_kar
        FROM l
    """)
    con.execute("""
        CREATE OR REPLACE VIEW urunler AS
        SELECT barcode AS barkod, product_name AS urun, cost AS birim_maliyet, stock AS stok FROM products
    """)
    return con
