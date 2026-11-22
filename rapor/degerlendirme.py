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


BICIM = "biçim farklı, değerler tam"


def _values_present(ref_row: tuple, got: pd.DataFrame) -> bool:
    """Tek satırlık referansın her değeri, sonucun herhangi bir hücresinde (her hücre bir kez) var mı?
    Örn. referans (bu_hafta, gecen_hafta) tek satırda, model iki satır (hafta, değer) döndürmüş."""
    cells = [v for row in got.itertuples(index=False) for v in row]
    return _row_match(ref_row, tuple(cells))


def compare(ref: pd.DataFrame, got: pd.DataFrame | None, ordered: bool) -> tuple[bool, str]:
    """Katı karşılaştırma. Katı ölçütte kalıp yalnız biçimi farklı olan cevaplarda neden BICIM ile başlar
    (esnek ölçütte doğru sayılır)."""
    if got is None:
        return False, "sonuç yok"
    ref_rows = [tuple(r) for r in ref.itertuples(index=False)]
    got_rows = [tuple(r) for r in got.itertuples(index=False)]
    if len(ref_rows) != len(got_rows):
        if len(ref_rows) == 1 and len(ref_rows[0]) > 1 and _values_present(ref_rows[0], got):
            return False, f"{BICIM} (beklenen 1 satır, gelen {len(got_rows)})"
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


def run(client=None, only: list[str] | None = None, progress=print, model: str = soru.MODEL,
        questions: Path = QUESTIONS) -> list[Sonuc]:
    items = yaml.safe_load(Path(questions).read_text(encoding="utf-8"))
    if only:
        items = [it for it in items if it["id"] in only]
    con = eval_connection()
    fingerprint = con.execute("SELECT ROUND(SUM(net_kar), 2), COUNT(*) FROM satis").fetchone()
    out: list[Sonuc] = []
    for it in items:
        t0 = time.time()
        c = soru.ask(it["soru"], con, client=client, model=model)
        if c.durum == "hata" and c.hata.startswith(("API hatası", "API anahtarı", "API'ye bağlanılamadı")):
            # Altyapı hatası modelin cevabı değildir: yanlış sayılırsa doğruluk ölçümü bozulur
            # (2026-11-22'de kredi bitince Haiku'nun bir turu böyle "26/45" görünmüştü). Ölçümü durdur.
            raise RuntimeError(f"Ölçüm durduruldu ({it['id']}): {c.hata}")
        dt = time.time() - t0
        if it.get("beklenen") == "cevaplanamaz":
            ok = c.durum == "cevaplanamaz"
            why = "" if ok else f"cevaplanamaz bekleniyordu, durum={c.durum} {c.hata}".strip()
        elif it.get("beklenen") == "yorumlu":
            # Belirsiz soru: makul bir yorumla cevap vermesi geçer; SQL raporda elle incelenir.
            ok = c.durum == "ok"
            why = "yorumlu: SQL elle incelenecek" if ok else f"durum={c.durum} {c.hata or c.aciklama}".strip()
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


def report(results: list[Sonuc], path: Path, model: str = soru.MODEL, title: str = "değerlendirmesi") -> Path:
    n, ok = len(results), sum(r.gecti for r in results)
    lines = [f"# 'Verine sor' {title} · {date.today():%d.%m.%Y}", "",
             f"Model: `{model}` · Doğru: **{ok}/{n} (%{ok / n * 100:.0f})** · "
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


def compare_models(models: list[str], repeats: int, client=None, questions: Path = QUESTIONS,
                   progress=print, only: list[str] | None = None) -> dict[str, list[list[Sonuc]]]:
    """Her modeli aynı setle `repeats` kez çalıştırır. Sonuç: model -> [tur sonuçları]."""
    out: dict[str, list[list[Sonuc]]] = {}
    for m in models:
        out[m] = []
        for i in range(repeats):
            progress(f"--- {m} · tur {i + 1}/{repeats}")
            out[m].append(run(client=client, progress=progress, model=m, questions=questions, only=only))
    return out


def compare_report(res: dict[str, list[list[Sonuc]]], path: Path, questions: Path = QUESTIONS) -> Path:
    n = len(next(iter(res.values()))[0])
    lines = [f"# 'Verine sor' model karşılaştırması · {date.today():%d.%m.%Y}", "",
             f"Set: `{Path(questions).name}` ({n} soru). Her model aynı setle {len(next(iter(res.values())))} kez çalıştırıldı; "
             "puanlama sonuca göre. Maliyet liste fiyatıyla tahmindir.", "",
             "**Esnek**: katı ölçütte yanlış sayılan ama tüm değerleri doğru olup yalnız biçimi farklı olan "
             "cevaplar (ör. iki haftayı iki satırda vermek) doğru sayılır.", "",
             "| Model | Turlar (doğru/" + str(n) + ") | Ortalama | En düşük | Esnek ortalama | Soru başına maliyet | Ortalama süre |",
             "|---|---|---|---|---|---|---|"]
    flaky: dict[str, dict[str, int]] = {}
    for m, runs in res.items():
        scores = [sum(r.gecti for r in run_) for run_ in runs]
        cost = sum(r.maliyet for run_ in runs for r in run_) / (n * len(runs))
        secs = sum(r.sure for run_ in runs for r in run_) / (n * len(runs))
        flex = [sum(r.gecti or r.neden.startswith(BICIM) for r in run_) for run_ in runs]
        lines.append(f"| `{m}` | {' · '.join(map(str, scores))} | %{sum(scores) / len(scores) / n * 100:.1f} | "
                     f"%{min(scores) / n * 100:.1f} | %{sum(flex) / len(flex) / n * 100:.1f} | "
                     f"{cost * 100:.2f} sent | {secs:.1f} sn |")
        fails: dict[str, int] = {}
        for run_ in runs:
            for r in run_:
                if not r.gecti:
                    fails[r.id] = fails.get(r.id, 0) + 1
        flaky[m] = fails
    lines += ["", "## Yanlış cevaplanan sorular", "", "Parantez içi: kaç turda yanlış.", ""]
    for m, fails in flaky.items():
        txt = ", ".join(f"{k} ({v})" for k, v in sorted(fails.items(), key=lambda x: -x[1])) or "yok"
        lines.append(f"- `{m}`: {txt}")
    lines += ["", "## Hatalar ve elle incelenecek (yorumlu) sorular", "",
              "Her model için her sorunun ilk görüldüğü tur.", ""]
    for m, runs in res.items():
        seen = set()
        for t, run_ in enumerate(runs, 1):
            for r in run_:
                # Hataların hepsi (her tur); yorumlu sorular yalnız ilk turda.
                if not r.gecti or (r.neden.startswith("yorumlu") and r.id not in seen):
                    seen.add(r.id)
                    lines += [f"**{m} · tur {t} · {r.id}** · {r.soru} — {r.neden}", "", "```sql", r.sql or "(SQL yok)", "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path
