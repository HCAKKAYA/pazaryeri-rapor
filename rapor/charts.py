"""Rapor grafikleri: e-posta ve PDF'e girecekleri için statik PNG (base64)."""
from __future__ import annotations

import base64
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from .fmt import tl
from .metrics import Period

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"       # bu hafta
BLUE_SOFT = "#86b6ef"  # önceki haftalar (aynı ton, açık adım)


def _style(ax):
    ax.set_facecolor(SURFACE)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, labelsize=9, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _png(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=160, bbox_inches="tight", facecolor=SURFACE)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def weekly_profit(series: list[Period]) -> str:
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    labels = [f"{p.start:%d.%m}" for p in series]
    vals = [p.net_profit for p in series]
    colors = [BLUE_SOFT] * (len(vals) - 1) + [BLUE]
    bars = ax.bar(labels, vals, color=colors, width=0.62, edgecolor=SURFACE, linewidth=2)
    ax.axhline(0, color=INK_2, linewidth=0.8)
    ax.yaxis.set_major_formatter(lambda v, _: tl(v))
    # Yalnız ilk ve son haftaya etiket: her çubuğa sayı koymak okumayı zorlaştırır.
    for i in (0, len(bars) - 1):
        b = bars[i]
        ax.annotate(tl(vals[i]), (b.get_x() + b.get_width() / 2, vals[i]),
                    xytext=(0, 4 if vals[i] >= 0 else -12), textcoords="offset points",
                    ha="center", fontsize=9, color=INK, fontweight="bold" if i else "normal")
    ax.set_xlabel("Hafta başı (pazartesi)", color=INK_2, fontsize=9)
    return _png(fig)


def product_profit(prod: pd.DataFrame, n: int = 8) -> str:
    d = prod.sort_values("net_profit", ascending=True)
    if len(d) > n:  # en kârlı n-1 + en zararlı 1 her zaman görünsün
        d = pd.concat([d.head(1), d.tail(n - 1)]).drop_duplicates("barcode")
    fig, ax = plt.subplots(figsize=(7.2, 0.36 * len(d) + 0.6))
    fig.patch.set_facecolor(SURFACE)
    _style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.barh(d["name"], d["net_profit"], color=BLUE, height=0.6, edgecolor=SURFACE, linewidth=2)
    ax.axvline(0, color=INK_2, linewidth=0.8)
    ax.xaxis.set_major_formatter(lambda v, _: tl(v))
    span = max(abs(d["net_profit"]).max(), 1)
    for y, v in enumerate(d["net_profit"]):
        ax.text(v + (span * 0.02 if v >= 0 else -span * 0.02), y, tl(v), va="center",
                ha="left" if v >= 0 else "right", fontsize=8.5, color=INK)
    lo, hi = d["net_profit"].min(), d["net_profit"].max()
    ax.set_xlim(min(lo, 0) - span * 0.25, hi + span * 0.25)
    ax.tick_params(axis="y", labelsize=9, colors=INK)
    return _png(fig)
