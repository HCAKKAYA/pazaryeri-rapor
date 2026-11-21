"""Türkçe sayı biçimleri."""
from __future__ import annotations


def _tr(x: float, decimals: int) -> str:
    return f"{x:,.{decimals}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def tl(x: float | None, decimals: int = 0) -> str:
    if x is None:
        return "—"
    s = _tr(abs(x), decimals) + " ₺"
    return "−" + s if x < 0 else s


def num(x: float | None, decimals: int = 0) -> str:
    return "—" if x is None else _tr(x, decimals)


def pct(x: float | None, sign: bool = False) -> str:
    if x is None:
        return "—"
    s = "%" + _tr(abs(x) * 100, 1)
    if not sign:
        return s
    return ("+" if x >= 0 else "−") + s
