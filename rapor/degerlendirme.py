"""'Verine sor' değerlendirmesi: eval/sorular.yaml'daki her soruyu modele sorar, sonucu
referans SQL'in sonucuyla karşılaştırır ve bir rapor yazar.

Karşılaştırma SQL metnine değil sonuca bakar: model farklı ama doğru bir sorgu yazabilir.
- Her referans satırı için, modelin sonucunda o satırın tüm değerlerini içeren bir satır aranır
  (model fazladan sütun ekleyebilir). Satır sayısı aynı olmalı; `sirali` sorularda sıra da.
- Sayılar %0,5 göreli ya da 0,01 mutlak toleransla eşleşir; oranlar 100 ile çarpılmış hâliyle de kabul edilir.
- Her sorudan sonra verinin bozulmadığı kontrol edilir.
"""
from __future__ import annotations

import math
import tempfile
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import yaml

from . import clean, sample, soru

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = ROOT / "eval" / "sorular.yaml"


def eval_connection():
    tmp = Path(tempfile.mkdtemp(prefix="eval-"))
    o, p = sample.generate(tmp)          # varsayılanlar: 21.09.2026 - 15.11.2026, seed 42
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")
    return soru.sandbox(clean.load_orders(o, cfg, clean.Quality()), clean.load_products(p, cfg))


def _norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.date() if not isinstance(v, date) or isinstance(v, datetime) else v
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if hasattr(v, "item"):           # numpy skaler
        return _norm(v.item())
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s[:10]).date()
    except ValueError:
        return s.casefold()


def _eq(ref, got) -> bool:
    ref, got = _norm(ref), _norm(got)
    if ref is None or got is None:
        return ref is got
    if isinstance(ref, float) and isinstance(got, float):
        for r in (ref, ref * 100):
            if math.isclose(r, got, rel_tol=0.005, abs_tol=0.01):
                return True
        return False
    return ref == got


def _row_match(ref_row, got_row) -> bool:
    remaining = list(got_row)
    for rv in ref_row:
        for i, gv in enumerate(remaining):
            if _eq(rv, gv):
                del remaining[i]
                break
        else:
            return False
    return True


def compare(ref: pd.DataFrame, got: pd.DataFrame | None, ordered: bool) -> tuple[bool, str]:
    if got is None:
        return False, "sonuç yok"
    ref_rows = [tuple(r) for r in ref.itertuples(index=False)]
    got_rows = [tuple(r) for r in got.itertuples(index=False)]
    if len(ref_rows) != len(got_rows):
        return False, f"satır sayısı farklı (beklenen {len(ref_rows)}, gelen {len(got_rows)})"
    if ordered:
        for i, (r, g) in enumerate(zip(ref_rows, got_rows)):
            if not _row_match(r, g):
                return False, f"{i + 1}. satır tutmuyor: beklenen {r}, gelen {g}"
        return True, ""
    unused = list(got_rows)
    for r in ref_rows:
        for i, g in enumerate(unused):
            if _row_match(r, g):
                del unused[i]
                break
        else:
            return False, f"beklenen satır yok: {r}"
    return True, ""


@dataclass
class Sonuc:
    id: str
    soru: str
    gecti: bool
    neden: str
    sql: str
    cevap: str
    sure: float
    deneme: int
    tokens_in: int = 0
    tokens_out: int = 0
    maliyet: float = 0.0


def run(client=None, only: list[str] | None = None, progress=print) -> list[Sonuc]:
    items = yaml.safe_load(QUESTIONS.read_text(encoding="utf-8"))
    if only:
        items = [it for it in items if it["id"] in only]
    con = eval_connection()
    fingerprint = con.execute("SELECT ROUND(SUM(net_kar), 2), COUNT(*) FROM satis").fetchone()
    out: list[Sonuc] = []
    for it in items:
        t0 = time.time()
        c = soru.ask(it["soru"], con, client=client)
        dt = time.time() - t0
        if it.get("beklenen") == "cevaplanamaz":
            ok = c.durum == "cevaplanamaz"
            why = "" if ok else f"cevaplanamaz bekleniyordu, durum={c.durum} {c.hata}".strip()
        elif c.durum == "cevaplanamaz" and it.get("kabul_cevaplanamaz"):
            ok, why = True, "reddetti (kabul)"
        elif c.durum != "ok":
            ok, why = False, f"durum={c.durum}: {c.hata or c.aciklama}"
        else:
            ok, why = compare(soru.run_sql(con, it["sql"]), c.ham, bool(it.get("sirali")))
        if con.execute("SELECT ROUND(SUM(net_kar), 2), COUNT(*) FROM satis").fetchone() != fingerprint:
            raise RuntimeError(f"VERİ DEĞİŞTİ: {it['id']}")   # olmamalı; sandbox ve guard bunu engeller
        s = Sonuc(it["id"], it["soru"], ok, why, c.sql, c.cevap, dt, c.deneme, c.tokens_in, c.tokens_out, c.maliyet)
        out.append(s)
        progress(f"{'✓' if ok else '✗'} {it['id']:<28} {dt:5.1f} sn  ${c.maliyet:.3f}  {why}")
    return out


def report(results: list[Sonuc], path: Path) -> Path:
    n, ok = len(results), sum(r.gecti for r in results)
    lines = [f"# 'Verine sor' değerlendirmesi · {date.today():%d.%m.%Y}", "",
             f"Model: `{soru.MODEL}` · Doğru: **{ok}/{n} (%{ok / n * 100:.0f})** · "
             f"Ortalama süre: {sum(r.sure for r in results) / n:.1f} sn · "
             f"İkinci denemeye kalan: {sum(r.deneme == 2 for r in results)} · "
             f"Token: {sum(r.tokens_in for r in results):,} giriş / {sum(r.tokens_out for r in results):,} çıkış · "
             f"Tahmini maliyet: ${sum(r.maliyet for r in results):.2f} "
             f"(soru başına ${sum(r.maliyet for r in results) / n:.3f})", "",
             "| | Soru | Not |", "|---|---|---|"]
    for r in results:
        lines.append(f"| {'✓' if r.gecti else '✗'} | {r.soru} | {r.neden.replace('|', '/')} |")
    lines += ["", "## Hatalı cevapların SQL'leri", ""]
    for r in results:
        if not r.gecti:
            lines += [f"**{r.id}** · {r.soru}", "", "```sql", r.sql or "(SQL yok)", "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
