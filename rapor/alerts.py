"""Kural tabanlı uyarılar. Eşikler satıcıyla konuşulup ayarlanacak."""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .fmt import num, pct, tl
from .metrics import Period, pct_change

PROFIT_DROP = -0.20        # net kâr haftalık %20+ düşerse
STOCK_DAYS_LOW = 7         # stok 7 günden az yetecekse
RETURN_RATE_HIGH = 0.15    # 28 günde iade oranı %15+ ise
RETURN_MIN_UNITS = 10      # ...ve en az 10 adet hareket varsa


@dataclass
class Alert:
    level: str   # "kritik" | "uyarı" | "bilgi"
    title: str
    detail: str

    @property
    def rank(self) -> int:
        return {"kritik": 0, "uyarı": 1, "bilgi": 2}[self.level]


def build(cur: Period, prev: Period, prod: pd.DataFrame) -> list[Alert]:
    out: list[Alert] = []

    ch = pct_change(cur.net_profit, prev.net_profit)
    if ch is not None and ch <= PROFIT_DROP:
        out.append(Alert("uyarı", "Net kâr düştü",
                         f"Bu hafta {tl(cur.net_profit)}, geçen hafta {tl(prev.net_profit)} ({pct(ch, sign=True)})."))

    for r in prod.itertuples():
        if r.stock is not None and r.stock == 0 and r.units_28d > 0:
            daily = r.units_28d / 28
            out.append(Alert("kritik", f"{r.name}: stokta yok",
                             f"Son 28 günde günde ortalama {num(daily, 1)} adet satıyordu. "
                             f"Stok gelene kadar günde yaklaşık {tl(daily * (r.net_profit_28d / r.units_28d) if r.units_28d else 0)} net kâr kaçıyor."))
        elif pd.notna(r.stock_days) and r.stock_days < STOCK_DAYS_LOW:
            out.append(Alert("uyarı", f"{r.name}: stok azalıyor",
                             f"{int(r.stock)} adet kaldı, mevcut hızla yaklaşık {r.stock_days:.0f} gün yeter."))

        moved = r.units_28d + r.returned_28d
        if moved >= RETURN_MIN_UNITS and pd.notna(r.return_rate_28d) and r.return_rate_28d >= RETURN_RATE_HIGH:
            out.append(Alert("uyarı", f"{r.name}: iade oranı yüksek",
                             f"Son 28 günde {int(moved)} adetin {int(r.returned_28d)} tanesi iade ({pct(r.return_rate_28d)}). "
                             "Ürün açıklaması, beden/uyum bilgisi ya da kalite kontrol edilmeli."))

        if r.units_28d >= 5 and r.net_profit_28d < 0:
            per_unit = r.net_profit_28d / r.units_28d
            out.append(Alert("kritik", f"{r.name}: zararına satılıyor",
                             f"Komisyon, kargo ve maliyetten sonra adet başına {tl(per_unit)}; "
                             f"son 28 günde toplam {tl(r.net_profit_28d)}."))

        if r.cost_missing:
            out.append(Alert("bilgi", f"{r.name}: maliyet bilinmiyor",
                             "Ürün dosyasında maliyet yok; kâr bu ürün için olduğundan yüksek görünür."))

    return sorted(out, key=lambda a: a.rank)
