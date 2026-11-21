from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from rapor import alerts, clean, metrics, sample, storage
from rapor.fmt import pct, tl

ROOT = Path(__file__).parent.parent
CFG = clean.load_mapping(ROOT / "config" / "mapping.yaml")


@pytest.mark.parametrize("raw, expected", [
    ("1.234,56", 1234.56), ("₺1.234,56", 1234.56), ("149,90", 149.9), ("1.234", 1234.0),
    ("12.5", 12.5), (99, 99.0), ("", None), (None, None), ("abc", None), ("1.234.567", 1234567.0),
])
def test_parse_tr_number(raw, expected):
    assert clean.parse_tr_number(raw) == expected


@pytest.mark.parametrize("raw, expected", [("%18", 0.18), ("18", 0.18), (0.18, 0.18), ("%12,5", 0.125)])
def test_parse_rate(raw, expected):
    assert clean.parse_rate(raw) == pytest.approx(expected)


def test_formats():
    assert tl(1234.6) == "1.235 ₺"
    assert tl(-296) == "−296 ₺"
    assert pct(-0.142, sign=True) == "−%14,2"


def _write(tmp_path, rows, products):
    o = tmp_path / "o.csv"
    p = tmp_path / "p.csv"
    pd.DataFrame(rows).to_csv(o, sep=";", index=False)
    pd.DataFrame(products).to_csv(p, sep=";", index=False)
    return o, p


def _row(no, day, barcode, qty, price, status, comm="%10", ship="10,00"):
    return {"Sipariş No": no, "Sipariş Tarihi": day, "Barkod": barcode, "Ürün Adı": barcode,
            "Adet": qty, "Birim Fiyat": price, "Komisyon Oranı": comm, "Kargo Ücreti": ship, "Durum": status}


def test_net_profit_by_hand(tmp_path):
    # 09.11.2026 haftası (2026-W46). Elle hesap:
    # A: 2 x 100 = 200 brüt, komisyon 20, maliyet 2 x 50 = 100, kargo 10
    # B: iade -> brüt yok, kargo 10 satıcıda kalır
    # C: iptal -> hiçbir şey
    rows = [
        _row("1", "10.11.2026 10:00", "A", 2, "100,00", "Teslim Edildi"),
        _row("1", "10.11.2026 10:00", "A", 2, "100,00", "Teslim Edildi"),  # çift satır
        _row("2", "11.11.2026 12:00", "A", 1, "100,00", "İade Edildi"),
        _row("3", "12.11.2026 12:00", "A", 1, "100,00", "İptal Edildi"),
        _row("4", "12.11.2026 12:00", "A", 1, "100,00", "Kayıp"),          # tanınmayan durum
        _row("", "", "", None, None, None),                                 # boş satır
    ]
    o, p = _write(tmp_path, rows, [{"Barkod": "A", "Ürün Adı": "A", "Birim Maliyet": "50,00", "Stok": 5}])
    q = clean.Quality()
    orders = clean.load_orders(o, CFG, q)
    con = storage.build(":memory:", orders, clean.load_products(p, CFG))

    cur = metrics.period(con, date(2026, 11, 9), date(2026, 11, 15))
    assert cur.gross == 200
    assert cur.commission == pytest.approx(20)
    assert cur.cogs == 100
    assert cur.shipping == 20
    assert cur.net_profit == pytest.approx(60)
    assert cur.return_rate == pytest.approx(1 / 3)
    assert q.duplicates == 1 and q.missing_required == 1 and q.unknown_status == {"Kayıp": 1}

    prod = metrics.products(con, date(2026, 11, 9), date(2026, 11, 15))
    assert prod.loc[0, "net_profit"] == pytest.approx(60)


def test_missing_column_message(tmp_path):
    o, _ = _write(tmp_path, [{"Yanlış": 1}], [{"Barkod": "A"}])
    with pytest.raises(ValueError, match="beklenen sütun"):
        clean.load_orders(o, CFG, clean.Quality())


def test_week_helpers():
    assert metrics.week_bounds("2026-W46") == (date(2026, 11, 9), date(2026, 11, 15))


def test_sample_patterns_are_caught(tmp_path):
    """Sentetik veriye gömülen dört desenin dördü de uyarı olarak çıkmalı."""
    o, p = sample.generate(tmp_path)
    q = clean.Quality()
    con = storage.build(":memory:", clean.load_orders(o, CFG, q), clean.load_products(p, CFG))
    week = metrics.latest_full_week(con)
    assert week == "2026-W46"
    s, e = metrics.week_bounds(week)
    found = alerts.build(metrics.period(con, s, e), metrics.period(con, s - timedelta(days=7), e - timedelta(days=7)),
                         metrics.products(con, s, e))
    titles = " | ".join(a.title for a in found)
    for expected in ("Kablosuz Kulaklık: stokta yok", "Laptop Standı: zararına", "Termos 500 ml: stok azalıyor",
                     "Telefon Kılıfı Şeffaf: iade oranı yüksek"):
        assert expected in titles
    assert found[0].level == "kritik"
