# Herkese açık demoyu yayınlama

Demo modu (`PANEL_DEMO=1`) kalıcı disk ya da veritabanı istemez:

- Sentetik veri her gün "dün"e kadar yeniden üretilir; sunucu yeniden başlarsa baştan üretilir.
- Giriş ekranında "Demo'ya gir" düğmesi var, şifre gerekmez. Demo hesabı yalnız demo mağazayı görür.
- Dosya yükleme kapalıdır; panelin üstünde verinin sentetik olduğunu söyleyen bir bant görünür.

Bu yüzden GitHub deposundan Dockerfile ile yayın yapan, ücretsiz katmanı olan herhangi bir servis yeter.
Ücretsiz katmanlarda servis bir süre kullanılmayınca uykuya geçer; ilk açılış yaklaşık bir dakika sürebilir.
Servislerin ücretsiz katman koşulları değişebiliyor, hesap açmadan önce güncel sayfalarına bakın.

## Örnek: Render

1. render.com'da GitHub hesabıyla oturum açın ve `pazaryeri-rapor` deposuna erişim verin.
2. **New → Web Service**, depoyu seçin. Render Dockerfile'ı kendisi bulur.
3. Instance type: **Free**.
4. **Environment** bölümüne ekleyin: `PANEL_DEMO` = `1`
5. **Deploy**. Render `PORT` değişkenini kendisi verir, uygulama onu dinler. HTTPS ve adres (`*.onrender.com`) Render'dan gelir.

Her `git push` sonrası Render yeniden yayınlar.

## Yerelde deneme

```powershell
.venv\Scripts\python cli.py panel --demo
```

`http://127.0.0.1:8791` → "Demo'ya gir".

## Notlar

- Demo modunda `config/magazalar.yaml` okunmaz; demo kendi tek mağazasını kurar.
- Ücretsiz servislerin önündeki vekil sunucu istemci IP'sini `X-Forwarded-For` ile iletir. Uygulama bu başlığa
  güvenir (`--proxy "*"`), yani hatalı giriş sınırındaki IP anahtarı taklit edilebilir; e-posta başına sınır yine geçerlidir.
  Demo'da gerçek hesap olmadığı için bu kabul edilebilir.
