"""README ekran görüntülerini sentetik veriyle yeniden üretir.

    .venv\\Scripts\\python -m pip install playwright
    .venv\\Scripts\\python tools\\ekran_goruntuleri.py

Kendi tarayıcı indirmez; bilgisayardaki Chrome/Edge'i kullanır. Gerçek veri ya da hesap
kullanmaz: geçici bir klasörde örnek veri, geçici bir demo kullanıcısı ve panel açar.
"""
from __future__ import annotations

import email
import secrets
import shutil
import sys
import tempfile
import threading
import time
from email import policy
from pathlib import Path

import uvicorn
import yaml
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from rapor import dashboard, pdf, pipeline, sample  # noqa: E402

OUT = ROOT / "docs" / "img"
PORT = 8799


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="ekran-"))
    try:
        (tmp / "config").mkdir()
        shutil.copy(ROOT / "config" / "mapping.yaml", tmp / "config" / "mapping.yaml")
        o, p = sample.generate(tmp / "gelen" / "ornek")
        cfg = {"magazalar": [{"ad": "Örnek Mağaza", "klasor": "gelen/ornek",
                              "siparis_desen": "siparis*.xlsx", "urun_desen": "urun*.csv"}]}
        (tmp / "config" / "magazalar.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

        # Haftalık rapor ve e-posta (kural tabanlı özet; API çağrısı yok)
        res = pipeline.run("Örnek Mağaza", o, p, use_ai=False, make_pdf=False, recipients=["satici@example.com"],
                           out_dir=tmp / "raporlar", db_dir=tmp / "data")
        msg = email.message_from_bytes(res.eml.read_bytes(), policy=policy.default)
        mail_html = tmp / "eposta.html"
        mail_html.write_text(msg.get_body(("html",)).get_content(), encoding="utf-8")

        # Panel
        app = dashboard.create_app(root=tmp, db_path=tmp / "data" / "panel.db", https=False)
        pw = secrets.token_urlsafe(12)
        app.state.users.add_user("demo@example.com", pw, "ornek-magaza")
        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))
        threading.Thread(target=server.run, daemon=True).start()
        while not server.started:
            time.sleep(0.1)

        with sync_playwright() as pw_:
            browser = pw_.chromium.launch(executable_path=pdf.find_browser())

            def ctx(width, height, scheme="light", scale=1.5):
                return browser.new_context(viewport={"width": width, "height": height},
                                           device_scale_factor=scale, color_scheme=scheme, locale="tr-TR")

            def logged_in(c):
                page = c.new_page()
                page.goto(f"http://127.0.0.1:{PORT}/giris")
                page.fill("#e", "demo@example.com")
                page.fill("#p", pw)
                page.click("button[type=submit]")
                page.wait_for_selector(".kpi .val")
                page.wait_for_timeout(600)  # grafik animasyonu
                return page

            page = logged_in(ctx(1280, 820))
            page.screenshot(path=OUT / "panel.png")

            page = logged_in(ctx(1280, 820, "dark"))
            page.screenshot(path=OUT / "panel-koyu.png")

            page = logged_in(ctx(390, 844, scale=2))
            page.screenshot(path=OUT / "panel-mobil.png")

            c = ctx(1280, 820)
            gp = c.new_page()
            gp.goto(f"http://127.0.0.1:{PORT}/giris")
            gp.screenshot(path=OUT / "giris.png")

            rp = ctx(900, 1300).new_page()
            rp.goto(res.html.as_uri())
            rp.wait_for_timeout(300)
            rp.screenshot(path=OUT / "rapor.png")

            mp = ctx(420, 900, scale=2).new_page()
            mp.goto(mail_html.as_uri())
            mp.screenshot(path=OUT / "eposta.png", full_page=True)

            browser.close()
        server.should_exit = True
        for f in sorted(OUT.glob("*.png")):
            print(f"{f.relative_to(ROOT)}  {f.stat().st_size // 1024} KB")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
