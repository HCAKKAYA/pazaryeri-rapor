"""HTML raporu PDF'e çevirir.

Ek kurulum gerektirmemek için bilgisayardaki Chrome ya da Edge'in başsız (headless)
yazdırma özelliğini kullanır. Başka bir tarayıcı için RAPOR_TARAYICI ortam
değişkenine exe yolu yazılabilir. Sunucuya taşındığında aynı yol Linux'taki
chromium ile çalışır.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
_NAMES = ["chrome", "google-chrome", "chromium", "chromium-browser", "msedge"]


class PdfError(RuntimeError):
    pass


def find_browser() -> str:
    env = os.environ.get("RAPOR_TARAYICI")
    if env:
        if Path(env).exists():
            return env
        raise PdfError(f"RAPOR_TARAYICI bulunamadı: {env}")
    for c in _CANDIDATES:
        if Path(c).exists():
            return c
    for n in _NAMES:
        p = shutil.which(n)
        if p:
            return p
    raise PdfError("PDF için Chrome ya da Edge bulunamadı. RAPOR_TARAYICI ile yol verilebilir.")


def html_to_pdf(html_path: Path, pdf_path: Path, timeout: int = 90) -> Path:
    html_path, pdf_path = Path(html_path).resolve(), Path(pdf_path).resolve()
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    pdf_path.unlink(missing_ok=True)
    # Ayrı profil: kullanıcının açık tarayıcısıyla çakışmasın.
    with tempfile.TemporaryDirectory(prefix="rapor-pdf-") as profile:
        cmd = [
            find_browser(), "--headless=new", "--disable-gpu", "--no-first-run",
            "--no-pdf-header-footer", f"--user-data-dir={profile}",
            f"--print-to-pdf={pdf_path}", html_path.as_uri(),
        ]
        try:
            subprocess.run(cmd, capture_output=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as e:
            raise PdfError(f"PDF {timeout} saniyede üretilemedi") from e
    if not pdf_path.exists() or pdf_path.read_bytes()[:4] != b"%PDF":
        raise PdfError("Tarayıcı PDF dosyası üretmedi")
    return pdf_path
