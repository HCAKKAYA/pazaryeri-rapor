"""Haftalık toplu çalıştırma: config/magazalar.yaml'daki her mağaza için rapor.

Zamanlayıcıdan çağrılır, bu yüzden:
- Bir mağazadaki hata diğerlerini durdurmaz; her şey logs/ altına yazılır.
- Veri güncel değilse (satıcı yeni dosya koymamışsa) rapor GÖNDERİLMEZ; geçen haftanın
  raporunu tekrar göndermek yanıltıcı olur.
- Aynı mağaza + hafta iki kez gönderilmez (data/gonderilenler.json).
"""
from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path

import yaml

from . import mailer, metrics, pipeline

ROOT = pipeline.ROOT
log = logging.getLogger("haftalik")


def _newest(folder: Path, pattern: str) -> Path | None:
    files = [p for p in folder.glob(pattern) if p.is_file() and not p.name.startswith("~$")]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def setup_logging(log_dir: Path, today: date) -> Path:
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"haftalik-{today:%Y-%m-%d}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    return path


def run_all(config_path: Path | None = None, *, today: date | None = None, force: bool = False,
            dry_run: bool = False, use_ai: bool = True, root: Path = ROOT) -> list[dict]:
    """Her mağaza için {'magaza', 'durum', 'ayrinti'} döndürür.

    durum: gonderildi | taslak | atlandi | hata
    """
    today = today or date.today()
    cfg = yaml.safe_load((config_path or root / "config" / "magazalar.yaml").read_text(encoding="utf-8")) or {}
    state_path = root / "data" / "gonderilenler.json"
    state = _load_state(state_path)
    want = pipeline.expected_week(today)
    out: list[dict] = []

    smtp_cfg, smtp_err = None, None
    if any(m.get("gonder") for m in cfg.get("magazalar", [])) and not dry_run:
        try:
            smtp_cfg = mailer.SmtpConfig.from_settings(cfg.get("smtp", {}))
        except mailer.MailError as e:
            smtp_err = str(e)

    for m in cfg.get("magazalar", []):
        name = m.get("ad", "?")
        slug = pipeline.slugify(name)

        def done(status: str, detail: str):
            out.append({"magaza": name, "durum": status, "ayrinti": detail})
            (log.error if status == "hata" else log.info)("%s: %s - %s", name, status, detail)

        try:
            folder = (root / m["klasor"]) if not Path(m["klasor"]).is_absolute() else Path(m["klasor"])
            orders = _newest(folder, m.get("siparis_desen", "*.xlsx"))
            products = _newest(folder, m.get("urun_desen", "*.csv"))
            if not orders or not products:
                done("atlandi", f"{folder} içinde sipariş ya da ürün dosyası yok")
                continue

            to_send = bool(m.get("gonder")) and not dry_run
            if to_send and smtp_err:
                done("hata", smtp_err)
                continue
            if to_send and want in state.get(slug, []) and not force:
                done("atlandi", f"{want} raporu daha önce gönderilmiş")
                continue

            res = pipeline.run(
                name, orders, products, use_ai=use_ai, recipients=m.get("alicilar") or None,
                out_dir=root / "raporlar", db_dir=root / "data",
                sender=smtp_cfg.sender if smtp_cfg else "rapor@localhost",
            )
            for n in res.notes:
                log.info("%s: %s", name, n)

            if res.week != want and not force:
                done("atlandi", f"veri güncel değil: dosyadaki son tam hafta {res.week}, beklenen {want} "
                                f"({orders.name}). Rapor taslağı yazıldı, gönderilmedi.")
                continue

            if to_send and m.get("alicilar"):
                mailer.send(res.msg, smtp_cfg)
                state.setdefault(slug, []).append(res.week)
                state_path.parent.mkdir(parents=True, exist_ok=True)
                state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
                done("gonderildi", f"{res.week} -> {', '.join(m['alicilar'])}")
            else:
                why = "alıcı yok" if not m.get("alicilar") else ("deneme çalıştırması" if dry_run else "gonder: false")
                done("taslak", f"{res.week} raporu hazır, gönderilmedi ({why}): {res.pdf or res.html}")
        except Exception as e:  # zamanlayıcıda tek mağazanın hatası diğerlerini durdurmasın
            log.exception("%s: beklenmeyen hata", name)
            done("hata", f"{type(e).__name__}: {e}")
    return out
