"""Dışa aktarım dosyalarını okur, sütunları ortak şemaya bağlar ve temizler."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
import yaml


@dataclass
class Quality:
    """Raporun sonunda gösterilen veri kalitesi özeti; güven için önemli."""
    rows_read: int = 0
    rows_used: int = 0
    duplicates: int = 0
    missing_required: int = 0
    unknown_status: dict[str, int] = field(default_factory=dict)
    missing_cost: list[str] = field(default_factory=list)

    def notes(self) -> list[str]:
        out = []
        if self.duplicates:
            out.append(f"{self.duplicates} çift satır bir kez sayıldı.")
        if self.missing_required:
            out.append(f"Tarihi, barkodu ya da fiyatı olmayan {self.missing_required} satır atlandı.")
        for s, n in self.unknown_status.items():
            out.append(f"Tanınmayan durum '{s}' ({n} satır) hesaplara alınmadı.")
        if self.missing_cost:
            out.append("Maliyeti bilinmeyen ürünler kâr hesabına maliyetsiz girdi: " + ", ".join(self.missing_cost))
        return out


def load_mapping(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


_THOUSANDS_ONLY = re.compile(r"^-?\d{1,3}(\.\d{3})+$")


def parse_tr_number(v) -> float | None:
    """'1.234,56' / '₺1.234,56' / '%18' / 1234.5 -> float.

    Tek nokta ve ardından tam 3 hane varsa ('1.234') binlik ayırıcı sayılır,
    Türkçe dışa aktarımlarda olağan olan budur.
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return None if pd.isna(v) else float(v)
    s = str(v).strip()
    for junk in ("₺", "TL", "%", " ", " "):
        s = s.replace(junk, "")
    if not s:
        return None
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif _THOUSANDS_ONLY.match(s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_rate(v) -> float | None:
    """Komisyon: '%18', '18', 18 ya da 0.18 -> 0.18."""
    x = parse_tr_number(v)
    if x is None:
        return None
    return x / 100 if x > 1 else x


def _read_any(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in (".xlsx", ".xls"):
        return pd.read_excel(path, dtype=object)
    # CSV: Türkçe Excel genelde ';' ile kaydeder; ayırıcıyı pandas bulsun.
    return pd.read_csv(path, sep=None, engine="python", dtype=object, encoding="utf-8-sig")


def _rename(df: pd.DataFrame, mapping: dict[str, str], kind: str) -> pd.DataFrame:
    missing = [src for src in mapping.values() if src not in df.columns]
    if missing:
        raise ValueError(f"{kind} dosyasında beklenen sütun(lar) yok: {missing}. config/mapping.yaml'ı kontrol et.")
    return df.rename(columns={src: dst for dst, src in mapping.items()})[list(mapping)]


def load_orders(path: Path, cfg: dict, q: Quality) -> pd.DataFrame:
    df = _rename(_read_any(path), cfg["orders"], "Sipariş")
    q.rows_read = len(df)

    df["order_id"] = df["order_id"].astype("string").str.strip()
    df["barcode"] = df["barcode"].astype("string").str.strip()
    df["order_date"] = pd.to_datetime(df["order_date"], dayfirst=True, errors="coerce", format="mixed")
    df["quantity"] = df["quantity"].map(parse_tr_number)
    df["unit_price"] = df["unit_price"].map(parse_tr_number)
    df["commission_rate"] = df["commission_rate"].map(parse_rate).fillna(0.0)
    df["shipping_fee"] = df["shipping_fee"].map(parse_tr_number).fillna(0.0)

    required = df["order_date"].notna() & df["barcode"].notna() & df["unit_price"].notna() & df["quantity"].notna()
    q.missing_required = int((~required).sum())
    df = df[required]

    before = len(df)
    df = df.drop_duplicates(subset=["order_id", "barcode"])
    q.duplicates = before - len(df)

    lookup = {raw.strip().casefold(): norm for norm, raws in cfg["status_values"].items() for raw in raws}
    raw_status = df["status"].astype("string").str.strip()
    df["status"] = raw_status.str.casefold().map(lookup)
    unknown = raw_status[df["status"].isna()].fillna("(boş)").value_counts()
    q.unknown_status = {str(k): int(v) for k, v in unknown.items()}
    df = df[df["status"].notna()]

    q.rows_used = len(df)
    return df.reset_index(drop=True)


def load_products(path: Path, cfg: dict) -> pd.DataFrame:
    df = _rename(_read_any(path), cfg["products"], "Ürün")
    df["barcode"] = df["barcode"].astype("string").str.strip()
    df["cost"] = df["cost"].map(parse_tr_number)
    df["stock"] = df["stock"].map(parse_tr_number)
    return df.drop_duplicates(subset=["barcode"]).reset_index(drop=True)
