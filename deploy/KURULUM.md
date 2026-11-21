# Paneli internete açma

Hedef: `https://panel.<alan-adı>` adresinde, HTTPS'li, e-posta ve parolayla girilen panel.

## Gerekenler (senin yapacakların)

1. **Bir sunucu (VPS).** Ubuntu 24.04, 1 vCPU / 2 GB RAM yeter. Sağlayıcı seçimi ve hesap açma, ödeme sende.
2. **Alan adı kaydı.** Alan adının DNS paneline bir `A` kaydı: `panel` → sunucunun IP adresi.
3. **Sunucuya SSH erişimi.** Sağlayıcı paneli verir.

## Sunucuda kurulum

```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Proje dosyaları (git deposu yoksa scp ile kopyalanır)
mkdir -p /opt/panel && cd /opt/panel
# ... pazaryeri-rapor klasörünü buraya kopyala ...

cd deploy
cp magazalar.ornek.yaml magazalar.yaml     # mağazaları yaz
mkdir -p data gelen && sudo chown -R 10001:10001 data gelen
echo "PANEL_ALANI=panel.ornek.com" > .env
docker compose up -d --build
```

Birkaç dakika içinde Caddy sertifikayı alır ve `https://panel.ornek.com` açılır.

## Kullanıcı ekleme

```bash
docker compose exec panel python cli.py kullanici-ekle --eposta satici@ornek.com --magaza "Örnek Mağaza"
```

Geçici parola bir kez ekrana yazılır. Satıcıya e-postayla değil, telefonla ya da mesajla ayrı ilet.

## Yedek

`deploy/data` (kullanıcılar) ve `deploy/gelen` (satıcı dosyaları) yedeklenmeli. En basit yol: sağlayıcının
günlük disk anlık görüntüsü (snapshot).

## Güvenlik notları

- Panel konteyneri dışarıya kapalı; yalnız Caddy (80/443) açık. Sunucuda güvenlik duvarı: yalnız 22, 80, 443.
- Çerezler `Secure`, `HttpOnly`, `SameSite=Lax`. Hatalı giriş 15 dakikada 5 denemeyle sınırlı.
- Yüklenen dosyalardan yalnız raporun kullandığı sütunlar saklanır; müşteri adı, adres gibi kişisel veriler diske yazılmaz.

## KVKK

Satıcının satış verisini sen işliyorsun (veri işleyen). İlk satıcıdan önce:
- Satıcıyla kısa bir veri işleme sözleşmesi ya da hizmet şartları (hangi veri, ne amaçla, ne kadar süre, silme).
- Sunucu yurt dışındaysa bu bir yurt dışı aktarımdır; KVKK'nın aktarım kuralları uygulanır.
  Türkiye'de bir sağlayıcı bu konuyu sadeleştirir. Kesin karar için bir hukukçuya danışılmalı.
