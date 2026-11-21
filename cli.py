"""Komut satırı.

  python cli.py ornek                       # sentetik veri üretir (sample_data/)
  python cli.py calistir                    # örnek veriyle raporu üretir
  python cli.py calistir --siparis X.xlsx --urun Y.csv --magaza "Mağaza" --hafta 2026-W46
  python cli.py calistir --alici satici@ornek.com           # PDF + e-posta taslağı (.eml)
  python cli.py calistir --alici satici@ornek.com --gonder  # SMTP ile gönderir

  python cli.py haftalik                    # config/magazalar.yaml'daki tüm mağazalar
  python cli.py haftalik --deneme           # hiçbir şey göndermeden dener
  python cli.py sifre-kaydet                # SMTP parolasını Windows Kimlik Yöneticisi'ne kaydeder
  python cli.py zamanla --gun Monday --saat 08:00   # Windows Görev Zamanlayıcı'ya ekler
  python cli.py zamanla --kaldir
"""
from __future__ import annotations

import argparse
import getpass
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

from rapor import mailer, pipeline, sample, weekly
from rapor.pipeline import slugify  # noqa: F401  (testler buradan içe aktarır)

ROOT = Path(__file__).resolve().parent
TASK_NAME = "Pazaryeri Rapor Haftalik"


def cmd_ornek(_args) -> None:
    o, p = sample.generate(ROOT / "sample_data")
    print(f"Örnek veri yazıldı:\n  {o}\n  {p}")


def cmd_calistir(args) -> None:
    orders_path = Path(args.siparis or ROOT / "sample_data" / "siparisler.xlsx")
    products_path = Path(args.urun or ROOT / "sample_data" / "urunler.csv")
    if not orders_path.exists():
        sys.exit(f"Sipariş dosyası yok: {orders_path}  (örnek için önce: python cli.py ornek)")

    send_cfg = None
    if args.gonder:
        try:
            send_cfg = mailer.SmtpConfig.from_env()
        except mailer.MailError as e:
            sys.exit(f"Gönderilmedi: {e}")
    sender = os.environ.get("SMTP_GONDEREN") or os.environ.get("SMTP_KULLANICI") or "rapor@localhost"
    try:
        res = pipeline.run(args.magaza, orders_path, products_path, week=args.hafta, use_ai=not args.yz_yok,
                           make_pdf=not args.pdf_yok, recipients=args.alici, send_cfg=send_cfg, sender=sender)
    except mailer.MailError as e:
        sys.exit(f"Gönderilmedi: {e}")
    print("\n".join(res.notes))
    if args.alici and not args.gonder:
        print("Gönderilmedi (taslak). Göndermek için --gonder ekle.")


def cmd_haftalik(args) -> None:
    today = date.fromisoformat(args.tarih) if args.tarih else date.today()
    log_path = weekly.setup_logging(ROOT / "logs", today)
    results = weekly.run_all(today=today, force=args.zorla, dry_run=args.deneme, use_ai=not args.yz_yok)
    for r in results:
        print(f"[{r['durum']}] {r['magaza']}: {r['ayrinti']}")
    print(f"Ayrıntılı kayıt: {log_path}")
    if any(r["durum"] == "hata" for r in results):
        sys.exit(1)


def cmd_sifre_kaydet(_args) -> None:
    cfg = yaml.safe_load((ROOT / "config" / "magazalar.yaml").read_text(encoding="utf-8")) or {}
    user = (cfg.get("smtp") or {}).get("kullanici")
    if not user:
        sys.exit("Önce config/magazalar.yaml içinde smtp.kullanici alanını doldur.")
    pw = getpass.getpass(f"{user} için SMTP parolası (Gmail'de uygulama şifresi; ekranda görünmez): ")
    if not pw.strip():
        sys.exit("Boş parola kaydedilmedi.")
    mailer.set_password(user, pw.replace(" ", ""))
    print("Kaydedildi (Windows Kimlik Yöneticisi). Dosyalara yazılmadı.")


def _ps(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")


def cmd_zamanla(args) -> None:
    if args.kaldir:
        r = _ps(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false")
        print("Kaldırıldı." if r.returncode == 0 else f"Kaldırılamadı: {r.stderr.strip()}")
        return
    pyw = ROOT / ".venv" / "Scripts" / "pythonw.exe"
    if not pyw.exists():
        sys.exit(f"{pyw} yok; önce sanal ortamı kur.")
    q = lambda s: str(s).replace("'", "''")  # noqa: E731  PowerShell tek tırnak kaçışı
    script = f"""
$a = New-ScheduledTaskAction -Execute '{q(pyw)}' -Argument 'cli.py haftalik' -WorkingDirectory '{q(ROOT)}'
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek {args.gun} -At '{args.saat}'
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries
Register-ScheduledTask -TaskName '{TASK_NAME}' -Action $a -Trigger $t -Settings $s -Description 'Pazaryeri haftalik rapor (cli.py haftalik)' -Force | Out-Null
(Get-ScheduledTask -TaskName '{TASK_NAME}' | Get-ScheduledTaskInfo).NextRunTime.ToString('yyyy-MM-dd HH:mm')
"""
    r = _ps(script)
    if r.returncode != 0:
        sys.exit(f"Görev eklenemedi: {r.stderr.strip()}")
    print(f"Görev eklendi: '{TASK_NAME}', her {args.gun} {args.saat}. Sonraki çalışma: {r.stdout.strip()}")
    print("Bilgisayar o saatte kapalıysa açıldığında çalışır. Kayıtlar: logs/")


def main(argv=None) -> None:
    if sys.stdout is None:  # pythonw.exe ile (zamanlayıcıdan) çalışırken konsol yok
        sys.stdout = sys.stderr = open(os.devnull, "w", encoding="utf-8")
    ap = argparse.ArgumentParser(description="Pazaryeri haftalık rapor")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ornek", help="sentetik veri üret").set_defaults(fn=cmd_ornek)

    r = sub.add_parser("calistir", help="tek rapor üret")
    r.add_argument("--siparis")
    r.add_argument("--urun")
    r.add_argument("--magaza", default="Örnek Mağaza")
    r.add_argument("--hafta", help="ISO hafta, ör. 2026-W46; boşsa verideki son tam hafta")
    r.add_argument("--yz-yok", action="store_true", help="yapay zeka yorumu yerine kural tabanlı özet")
    r.add_argument("--pdf-yok", action="store_true", help="PDF üretme")
    r.add_argument("--alici", action="append", help="e-posta alıcısı (birden çok kez verilebilir); taslak .eml yazılır")
    r.add_argument("--gonder", action="store_true", help="taslağı SMTP ile gerçekten gönder (SMTP_* ortam değişkenleri)")
    r.set_defaults(fn=cmd_calistir)

    h = sub.add_parser("haftalik", help="config/magazalar.yaml'daki tüm mağazalar")
    h.add_argument("--deneme", action="store_true", help="hiçbir şey gönderme")
    h.add_argument("--zorla", action="store_true", help="eski veri ve daha önce gönderilmiş olsa da çalış")
    h.add_argument("--yz-yok", action="store_true")
    h.add_argument("--tarih", help="bugün yerine bu tarih (deneme için), ör. 2026-11-16")
    h.set_defaults(fn=cmd_haftalik)

    sub.add_parser("sifre-kaydet", help="SMTP parolasını Windows Kimlik Yöneticisi'ne kaydet").set_defaults(fn=cmd_sifre_kaydet)

    z = sub.add_parser("zamanla", help="Windows Görev Zamanlayıcı'ya haftalık görev ekle")
    z.add_argument("--gun", default="Monday", choices=["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"])
    z.add_argument("--saat", default="08:00")
    z.add_argument("--kaldir", action="store_true")
    z.set_defaults(fn=cmd_zamanla)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
