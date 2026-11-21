"""Sentetik pazaryeri verisi üretir.

Gerçek bir satıcı verisi gelene kadar uçtan uca akışı denemek için. Veriye bilerek
birkaç desen gömülüdür; rapor bunları yakalamalı:
  - "Kablosuz Kulaklık" son hafta stoğu bitiyor (satış düşüyor, stok 0)
  - "Telefon Kılıfı Şeffaf" iade oranı yüksek
  - "Laptop Standı" komisyon ve kargo sonrası zarar ediyor
  - "Termos 500 ml" stoğu birkaç gün yetecek kadar
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# (ad, satış fiyatı, maliyet, komisyon %, günlük ortalama adet, stok, iade olasılığı)
PRODUCTS = [
    ("Kablosuz Kulaklık", 899.90, 420.00, 18, 6.0, 0, 0.04),
    ("Telefon Kılıfı Şeffaf", 149.90, 28.00, 20, 14.0, 640, 0.22),
    ("Laptop Standı", 349.90, 245.00, 18, 3.0, 120, 0.05),
    ("Termos 500 ml", 279.90, 110.00, 15, 5.0, 18, 0.03),
    ("Masa Lambası LED", 459.90, 190.00, 15, 2.5, 85, 0.06),
    ("Kahve Kupası Seramik", 129.90, 35.00, 15, 7.0, 400, 0.05),
    ("Sırt Çantası", 699.90, 290.00, 20, 2.0, 60, 0.08),
    ("Şarj Kablosu USB-C", 99.90, 18.00, 18, 16.0, 900, 0.04),
    ("Bluetooth Hoparlör", 1199.90, 610.00, 18, 1.5, 40, 0.05),
    ("Yoga Matı", 389.90, 140.00, 15, 2.2, 75, 0.04),
    ("Spor Şişesi", 159.90, 45.00, 15, 4.5, 300, 0.03),
    ("Mouse Pad XL", 189.90, 52.00, 18, 3.5, 210, 0.03),
]

# Kargo: sipariş başına kesilen sabit ücret (sentetik varsayım).
SHIPPING_FEE = 64.90


def _tr_number(x: float) -> str:
    """1234.5 -> '1.234,50' (Türkçe dışa aktarımlardaki gibi metin)."""
    return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def generate(out_dir: Path, end: date = date(2026, 11, 15), weeks: int = 8, seed: int = 42) -> tuple[Path, Path]:
    rng = np.random.default_rng(seed)
    start = end - timedelta(days=weeks * 7 - 1)
    days = [start + timedelta(days=i) for i in range(weeks * 7)]
    rows = []
    order_no = 100000

    for d in days:
        progress = (d - start).days / len(days)
        weekend = 1.25 if d.weekday() >= 5 else 1.0
        trend = 0.9 + 0.25 * progress  # hafif büyüme
        for barcode_i, (name, price, _cost, comm, daily, _stock, ret_p) in enumerate(PRODUCTS):
            lam = daily * weekend * trend
            if name == "Kablosuz Kulaklık" and (end - d).days < 5:
                lam *= 0.05  # stok bitti
            n_orders = rng.poisson(lam)
            for _ in range(n_orders):
                order_no += 1
                qty = 1 if rng.random() < 0.85 else 2
                r = rng.random()
                if r < ret_p:
                    status = "İade Edildi"
                elif r < ret_p + 0.03:
                    status = "İptal Edildi"
                elif (end - d).days < 3:
                    status = "Kargoda"
                else:
                    status = "Teslim Edildi"
                ts = datetime(d.year, d.month, d.day, int(rng.integers(8, 24)), int(rng.integers(0, 60)))
                rows.append({
                    "Sipariş No": str(order_no),
                    "Sipariş Tarihi": ts.strftime("%d.%m.%Y %H:%M"),
                    "Barkod": f"86900000{barcode_i:04d}",
                    "Ürün Adı": name,
                    "Adet": qty,
                    "Birim Fiyat": _tr_number(price),
                    "Komisyon Oranı": f"%{comm}",
                    "Kargo Ücreti": _tr_number(SHIPPING_FEE),
                    "Durum": status,
                })

    orders = pd.DataFrame(rows)
    # Gerçek dışa aktarımlardaki pürüzler: birkaç çift satır ve bir boş satır.
    orders = pd.concat([orders, orders.sample(5, random_state=seed)], ignore_index=True)
    orders.loc[len(orders)] = {c: None for c in orders.columns}

    products = pd.DataFrame([
        {"Barkod": f"86900000{i:04d}", "Ürün Adı": p[0], "Birim Maliyet": _tr_number(p[2]), "Stok": p[5]}
        for i, p in enumerate(PRODUCTS)
    ])

    out_dir.mkdir(parents=True, exist_ok=True)
    orders_path = out_dir / "siparisler.xlsx"
    products_path = out_dir / "urunler.csv"
    orders.to_excel(orders_path, index=False)
    products.to_csv(products_path, index=False, sep=";", encoding="utf-8-sig")
    return orders_path, products_path
