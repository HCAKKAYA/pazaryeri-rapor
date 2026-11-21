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
  python cli.py sor "Bu hafta en çok kâr eden ürün hangisi?"
  python cli.py degerlendir                 # 45 soruluk doğruluk ölçümü (API anahtarı gerekir)
  python cli.py panel                       # satıcı paneli: http://127.0.0.1:8791 (e-posta + parola)
  python cli.py kullanici-ekle --eposta satici@ornek.com --magaza "Örnek Mağaza"
  python cli.py kullanicilar | kullanici-sil --eposta ... | parola --eposta ... --rastgele
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
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


def cmd_panel(args) -> None:
    import uvicorn

    from rapor import dashboard
    _load_env()
    app = dashboard.create_app(demo_mode=True if args.demo else None)
    n = len(app.state.users.list_users())
    print(f"Panel: http://{args.host}:{args.port}  ({n} kullanıcı)" + ("  [DEMO]" if app.state.demo else ""))
    if n == 0:
        print("Henüz kullanıcı yok. Eklemek için: python cli.py kullanici-ekle --eposta ... --magaza ...")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                proxy_headers=True, forwarded_allow_ips=args.proxy)


def _users():
    from rapor import auth
    return auth, auth.AuthStore(ROOT / "data" / "panel.db")


def _store_slugs() -> dict[str, str]:
    cfg = yaml.safe_load((ROOT / "config" / "magazalar.yaml").read_text(encoding="utf-8")) or {}
    return {pipeline.slugify(m["ad"]): m["ad"] for m in cfg.get("magazalar", [])}


def cmd_kullanici_ekle(args) -> None:
    auth, users = _users()
    stores = _store_slugs()
    slug = pipeline.slugify(args.magaza)
    if slug not in stores:
        sys.exit(f"'{args.magaza}' config/magazalar.yaml içinde yok. Mevcut: {', '.join(stores.values())}")
    pw = getpass.getpass("Parola (boş bırakırsan rastgele üretilir): ") if args.parola_sor else ""
    generated = not pw
    pw = pw or secrets.token_urlsafe(12)
    try:
        users.add_user(args.eposta, pw, slug)
    except auth.AuthError as e:
        sys.exit(str(e))
    print(f"Eklendi: {args.eposta} -> {stores[slug]}")
    if generated:
        print(f"Geçici parola (bir kez gösterilir, güvenli bir kanaldan iletin): {pw}")


def cmd_kullanici_sil(args) -> None:
    _, users = _users()
    print("Silindi." if users.remove_user(args.eposta) else "Böyle bir kullanıcı yok.")


def cmd_kullanicilar(_args) -> None:
    _, users = _users()
    rows = users.list_users()
    print("\n".join(f"{e}  ->  {s}" for e, s in rows) if rows else "Kullanıcı yok.")


def cmd_parola(args) -> None:
    auth, users = _users()
    pw = secrets.token_urlsafe(12) if args.rastgele else getpass.getpass("Yeni parola: ")
    try:
        users.set_password(args.eposta, pw)
    except auth.AuthError as e:
        sys.exit(str(e))
    print("Parola değişti; açık oturumlar kapatıldı.")
    if args.rastgele:
        print(f"Yeni geçici parola: {pw}")


def cmd_statik_demo(args) -> None:
    from rapor import static_demo
    files = static_demo.build(Path(args.cikti), make_pdf=not args.pdf_yok)
    print(f"Statik demo -> {Path(args.cikti).resolve()} ({len(files)} dosya)")


def _load_env() -> None:
    """Proje kökündeki .env dosyasından ANTHROPIC_API_KEY gibi değişkenleri yükler (varsa)."""
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8-sig").splitlines():  # Not Defteri BOM ekleyebilir
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def cmd_sor(args) -> None:
    from rapor import clean, soru
    _load_env()
    cfg = clean.load_mapping(ROOT / "config" / "mapping.yaml")
    orders = clean.load_orders(Path(args.siparis or ROOT / "sample_data" / "siparisler.xlsx"), cfg, clean.Quality())
    products = clean.load_products(Path(args.urun or ROOT / "sample_data" / "urunler.csv"), cfg)
    c = soru.ask(args.soru, soru.sandbox(orders, products))
    if c.durum == "cevaplanamaz":
        print(f"Bu veriyle cevaplanamıyor: {c.aciklama}")
        return
    if c.durum != "ok":
        sys.exit(f"Cevaplanamadı: {c.hata}")
    if c.cevap:
        print(c.cevap + "\n")
    print(" | ".join(c.sutunlar))
    for r in c.satirlar[:20]:
        print(" | ".join(r))
    print(f"\nSQL: {c.sql}")


def cmd_degerlendir(args) -> None:
    from datetime import date as _d

    from rapor import degerlendirme
    _load_env()
    res = degerlendirme.run(only=args.sadece.split(",") if args.sadece else None)
    path = degerlendirme.report(res, ROOT / "eval" / f"sonuc-{_d.today():%Y-%m-%d}.md")
    ok = sum(r.gecti for r in res)
    print(f"\n{ok}/{len(res)} doğru. Rapor: {path}")


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

    pn = sub.add_parser("panel", help="satıcı panelini başlat")
    pn.add_argument("--host", default="127.0.0.1")
    pn.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8791)),
                    help="varsayılan 8791; barındırma servisi PORT ortam değişkeni verirse o kullanılır")
    pn.add_argument("--demo", action="store_true", help="herkese açık demo: sentetik veri, şifresiz demo girişi, yükleme kapalı")
    pn.add_argument("--proxy", default="127.0.0.1", help="X-Forwarded-* başlıklarına güvenilecek vekil sunucu IP'leri")
    pn.set_defaults(fn=cmd_panel)

    ke = sub.add_parser("kullanici-ekle", help="panele kullanıcı ekle (tek mağazaya bağlı)")
    ke.add_argument("--eposta", required=True)
    ke.add_argument("--magaza", required=True, help="config/magazalar.yaml'daki mağaza adı")
    ke.add_argument("--parola-sor", action="store_true", help="rastgele yerine parolayı sor")
    ke.set_defaults(fn=cmd_kullanici_ekle)
    ks = sub.add_parser("kullanici-sil")
    ks.add_argument("--eposta", required=True)
    ks.set_defaults(fn=cmd_kullanici_sil)
    sub.add_parser("kullanicilar").set_defaults(fn=cmd_kullanicilar)
    pd_ = sub.add_parser("parola", help="kullanıcının parolasını değiştir")
    pd_.add_argument("--eposta", required=True)
    pd_.add_argument("--rastgele", action="store_true")
    pd_.set_defaults(fn=cmd_parola)

    sd = sub.add_parser("statik-demo", help="GitHub Pages için statik demo üret")
    sd.add_argument("--cikti", default=str(ROOT / "site"))
    sd.add_argument("--pdf-yok", action="store_true")
    sd.set_defaults(fn=cmd_statik_demo)

    so = sub.add_parser("sor", help="veriye Türkçe soru sor (ANTHROPIC_API_KEY gerekir)")
    so.add_argument("soru")
    so.add_argument("--siparis")
    so.add_argument("--urun")
    so.set_defaults(fn=cmd_sor)

    de = sub.add_parser("degerlendir", help="'Verine sor' doğruluğunu eval/sorular.yaml ile ölç")
    de.add_argument("--sadece", help="virgülle ayrılmış soru id'leri")
    de.set_defaults(fn=cmd_degerlendir)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
