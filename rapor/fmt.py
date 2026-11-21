"""Türkçe sayı biçimleri.

Yuvarlama önce kuruşa, sonra yarımlar yukarı yapılır. Böylece float toplamındaki
küçük farklar (11497.4999 / 11497.5000) aynı veride farklı rakam göstermez.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def _tr(x: float, decimals: int) -> str:
    q = Decimal(1).scaleb(-decimals)
    d = Decimal(str(round(x, 4))).quantize(q, rounding=ROUND_HALF_UP)
    return f"{d:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tl(x: float | None, decimals: int = 0) -> str:
    if x is None:
        return "—"
    s = _tr(abs(x), decimals) + " ₺"  # bölünmez boşluk: ₺ alt satıra düşmesin
    return "−" + s if _tr(abs(x), decimals).strip("0,.") and x < 0 else s


def num(x: float | None, decimals: int = 0) -> str:
    return "—" if x is None else _tr(x, decimals)


def pct(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    s = "%" + _tr(abs(x) * 100, 1)
    negative = x < 0 and s != "%0,0"
    if not sign:
        # Eskiden burada işaret atılıyordu: negatif kâr marjı pozitif görünüyordu.
        return "−" + s if negative else s
    return ("−" if negative else "+") + s
