"""Komut satırı.

  python cli.py ornek                       # sentetik veri üretir (sample_data/)
  python cli.py calistir                    # örnek veriyle raporu üretir
  python cli.py calistir --siparis X.xlsx --urun Y.csv --magaza "Mağaza" --hafta 2026-W46
"""
from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

from rapor import alerts, clean, metrics, narrative, report, sample, storage
from rapor.fmt import tl

ROOT = Path(__file__).parent


def cmd_ornek(_args) -> None:
    o, p = sample.generate(ROOT / "sample_data")
    print(f"Örnek veri yazıldı:\n  {o}\n  {p}")


def cmd_calistir(args) -> None:
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")
    orders_path = Path(args.siparis or ROOT / "sample_data" / "siparisler.xlsx")
    products_path = Path(args.urun or ROOT / "sample_data" / "urunler.csv")
    if not orders_path.exists():
        sys.exit(f"Sipariş dosyası yok: {orders_path}  (örnek için önce: python cli.py ornek)")

    q = clean.Quality()
    orders = clean.load_orders(orders_path, cfg, q)
    products = clean.load_products(products_path, cfg)
    known = set(products.loc[products["cost"].notna(), "barcode"])
    q.missing_cost = sorted(set(orders.loc[~orders["barcode"].isin(known), "product_name"].dropna()))

    slug = "".join(c if c.isalnum() else "-" for c in args.magaza.lower()).strip("-")
    con = storage.build(ROOT / "data" / f"{slug}.duckdb", orders, products)

    week = args.hafta or metrics.latest_full_week(con)
    start, end = metrics.week_bounds(week)
    cur = metrics.period(con, start, end)
    prev = metrics.period(con, start - timedelta(days=7), end - timedelta(days=7))
    series = metrics.weekly_series(con, week, 8)
    prod = metrics.products(con, start, end)
    found = alerts.build(cur, prev, prod)

    facts = narrative.build_facts(week, cur, prev, series, prod, found)
    if args.yz_yok:
        story = narrative.rule_based(facts, found, "yapay zeka kapalı (--yz-yok)")
    else:
        story = narrative.write(facts, found)
    print(f"Yorum: {story.kaynak}" + (f" ({story.not_})" if story.not_ else ""))

    html = report.render(args.magaza, week, cur, prev, series, prod, found, q, story)
    out = ROOT / "raporlar" / f"{slug}-{week}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"{week}: net kâr {tl(cur.net_profit)}, {len(found)} uyarı -> {out}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Pazaryeri haftalık rapor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ornek", help="sentetik veri üret").set_defaults(fn=cmd_ornek)
    r = sub.add_parser("calistir", help="rapor üret")
    r.add_argument("--siparis")
    r.add_argument("--urun")
    r.add_argument("--magaza", default="Örnek Mağaza")
    r.add_argument("--hafta", help="ISO hafta, ör. 2026-W46; boşsa verideki son tam hafta")
    r.add_argument("--yz-yok", action="store_true", help="yapay zeka yorumu yerine kural tabanlı özet")
    r.set_defaults(fn=cmd_calistir)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
