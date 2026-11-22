"""GitHub Pages için statik demo üretir.

Sunucu yoktur: panelin hazır dönemleri (7 gün, 28 gün, 8 hafta, 3 ay) sunucudaki kodun
aynısıyla (`dashboard.summary`, yani SQL) önceden hesaplanır ve JSON olarak yazılır. Panel bu
dosyaları okur. Hesap mantığı tek yerde kalır; tarayıcıda ikinci bir kopyası yoktur.

GitHub Actions haftada bir (pazartesi) ve her push'ta çalıştırır; sentetik veri çalıştığı günün "dün"üne
kadar gelir. Hazır cevaplar aynı çalışmada aynı veriyle üretilir, panelle hep tutarlıdır.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import clean, dashboard, demo, pdf, pipeline

ROOT = pipeline.ROOT
PRESETS = (7, 28, 56, 91)


ORNEK_SORULAR = [
    "Bu hafta en çok kâr eden 3 ürün hangisi?",
    "Kargo cironun yüzde kaçını yiyor?",
    "Zarar eden ürünlerim var mı?",
    "İade oranı en yüksek ürün hangisi?",
    "Son 4 haftanın net kârını hafta hafta göster.",
    "Geçen ay reklama ne kadar harcadım?",          # cevaplanamaz: modelin "bilmiyorum" diyebildiğini gösterir
]


def example_answers(qcon, client=None) -> dict:
    """Örnek soruları gerçek modelle cevaplar. Başarısız olanlar yayınlanmaz (hata sayfaya düşmez)."""
    from . import soru
    items, cost = [], 0.0
    for q in ORNEK_SORULAR:
        c = soru.ask(q, qcon, client=client)
        cost += c.maliyet
        if c.durum in ("ok", "cevaplanamaz"):
            items.append(c.to_dict())
        else:
            print(f"Örnek soru yayınlanmadı ({c.hata}): {q}")
    print(f"Örnek sorular: {len(items)}/{len(ORNEK_SORULAR)}, tahmini maliyet ${cost:.3f}")
    return {"model": soru.MODEL, "uretildi": datetime.now().strftime("%d.%m.%Y %H:%M"), "sorular": items}


def build(out: Path, today: date | None = None, make_pdf: bool = True, client=None) -> list[Path]:
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)
    (out / "veri").mkdir(parents=True)
    tmp = Path(tempfile.mkdtemp(prefix="statik-demo-"))
    written: list[Path] = []
    try:
        folder = tmp / "gelen"
        demo.ensure_data(folder, today)
        end = demo.data_end(today)
        mapping = clean.load_mapping(ROOT / "config" / "mapping.yaml")

        store = dashboard.Store(demo.STORE_NAME, demo.STORE_SLUG, folder, "siparis*.xlsx", "urun*.csv")
        store.refresh(mapping)
        for days in PRESETS:
            data = dashboard.summary(store, end - timedelta(days=days - 1), end)
            data["demo"] = True
            p = out / "veri" / f"ozet-{days}.json"
            p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            written.append(p)

        # Hazır sorular: anahtar varsa (GitHub Actions'ta şifreli Secret) gerçek modelle cevaplanır.
        # Anahtar sayfaya hiç girmez; ziyaretçi yalnız bu önceden üretilmiş cevapları görür.
        if client is not None or os.environ.get("ANTHROPIC_API_KEY"):
            p = out / "veri" / "sorular.json"
            p.write_text(json.dumps(example_answers(store.qcon, client), ensure_ascii=False, separators=(",", ":")),
                         encoding="utf-8")
            written.append(p)
        store.con.close()
        store.qcon.close()

        # Son tam haftanın raporu. Anahtar varsa "Bu haftanın özeti" gerçek modelle yazılır (sayıları
        # denetlenir; tutmazsa kural tabanlı özete düşer). Anahtar yoksa kural tabanlı özet.
        # (Testlerde sahte istemci verilir; rapor yorumu o istemciyi kullanmadığı için o durumda ağa çıkılmaz.)
        use_ai = client is None and bool(os.environ.get("ANTHROPIC_API_KEY"))
        res = pipeline.run(demo.STORE_NAME, folder / "siparisler.xlsx", folder / "urunler.csv",
                           use_ai=use_ai, make_pdf=make_pdf, out_dir=tmp / "rapor", db_dir=tmp / "db")
        shutil.copy(res.html, out / "rapor.html")
        written.append(out / "rapor.html")
        report_link = "rapor.html"
        if res.pdf:
            shutil.copy(res.pdf, out / "rapor.pdf")
            written.append(out / "rapor.pdf")
            report_link = "rapor.pdf"

        html = (dashboard.TEMPLATES / "panel.html").read_text(encoding="utf-8")
        html = html.replace("{{MAGAZA}}", demo.STORE_NAME).replace("<body>", '<body data-statik="1">', 1)
        html = re.sub(r'\s*<form method="post" action="/cikis".*?</form>', "", html, count=1, flags=re.S)
        html = html.replace('src="/static/panel.js"', 'src="panel.js"').replace('src="/static/tema.js"', 'src="tema.js"')
        html = html.replace("veri her gün yeniden üretilir.",
                            f'veri her hafta yeniden üretilir. <a href="{report_link}">Bu haftanın raporu</a> ·', 1)
        assert 'data-statik="1"' in html and "/cikis" not in html and 'src="panel.js"' in html
        (out / "index.html").write_text(html, encoding="utf-8")
        shutil.copy(dashboard.STATIC / "panel.js", out / "panel.js")
        shutil.copy(dashboard.STATIC / "tema.js", out / "tema.js")
        (out / ".nojekyll").write_text("", encoding="utf-8")
        written += [out / "index.html", out / "panel.js", out / "tema.js"]
        return written
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
