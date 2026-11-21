# Kullanım kılavuzu

Pazaryeri satıcısının dışa aktarım dosyalarından (siparişler + ürün/maliyet/stok) her hafta
tek sayfalık bir rapor üretir: net kâr, haftalık değişim, uyarılar (stok, iade, zararına satış),
ürün tablosu ve veri kalitesi notu.

## Kurulum

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

## Kullanım

```powershell
.venv\Scripts\python cli.py ornek        # sentetik veri: sample_data/
.venv\Scripts\python cli.py calistir     # rapor: raporlar/<mağaza>-<hafta>.html
.venv\Scripts\python cli.py calistir --siparis siparisler.xlsx --urun urunler.csv --magaza "Mağaza Adı" --hafta 2026-W46
.venv\Scripts\python -m pytest -q
```

## PDF ve e-posta

Her çalıştırmada HTML'in yanına PDF yazılır (bilgisayardaki Chrome ya da Edge ile, ek kurulum yok;
`--pdf-yok` kapatır, başka tarayıcı için `RAPOR_TARAYICI`).

`--alici` verilirse e-posta hazırlanır: kısa HTML gövde (net kâr, özet, uyarılar) + düz metin + PDF eki.
Varsayılan olarak **gönderilmez**, `raporlar/<mağaza>-<hafta>.eml` taslağı yazılır; Outlook ile açılıp
kontrol edilebilir. Gerçek gönderim için `--gonder` ve SMTP ayarları gerekir:

```powershell
$env:SMTP_SUNUCU = "smtp.gmail.com"; $env:SMTP_PORT = "587"
$env:SMTP_KULLANICI = "adres@gmail.com"; $env:SMTP_PAROLA = "<uygulama şifresi>"
.venv\Scripts\python cli.py calistir --alici satici@ornek.com --gonder
```

Gmail normal parolayı kabul etmez; Google hesabında 2 adımlı doğrulama açıp "uygulama şifresi" üretmek gerekir.

## Haftalık otomatik çalışma

`config/magazalar.yaml` mağazaları, dosya klasörlerini, alıcıları ve SMTP ayarlarını tutar (parola hariç).

```powershell
.venv\Scripts\python cli.py sifre-kaydet                 # parola Windows Kimlik Yöneticisi'ne, bir kez
.venv\Scripts\python cli.py haftalik --deneme            # hiçbir şey göndermeden dener
.venv\Scripts\python cli.py zamanla --gun Monday --saat 08:00
.venv\Scripts\python cli.py zamanla --kaldir
```

Görev her pazartesi 08:00'de `cli.py haftalik` çalıştırır; bilgisayar kapalıysa açıldığında çalışır. Kurallar:
- Klasördeki desene uyan **en yeni** sipariş ve ürün dosyası kullanılır.
- Dosyadaki son tam hafta beklenen hafta değilse (satıcı yeni dosya koymamışsa) rapor **gönderilmez**.
- Aynı mağaza ve hafta iki kez gönderilmez (`data/gonderilenler.json`); `--zorla` bunu geçer.
- `gonder: false` olan mağaza için yalnız taslak yazılır.
- Bir mağazadaki hata diğerlerini durdurmaz; her şey `logs/haftalik-<tarih>.log` dosyasına yazılır.

Sınır: veriyi hâlâ birinin klasöre koyması gerekiyor. Pazaryeri API bağlantısı gelene kadar bu elle.

## Satıcı paneli

```powershell
.venv\Scripts\python cli.py kullanici-ekle --eposta satici@ornek.com --magaza "Örnek Mağaza"   # geçici parola yazar
.venv\Scripts\python cli.py panel        # http://127.0.0.1:8791
.venv\Scripts\python cli.py kullanicilar
.venv\Scripts\python cli.py parola --eposta satici@ornek.com --rastgele
```

Giriş e-posta ve parolayla (`rapor/auth.py`): scrypt parola özeti, veritabanında yalnız özeti tutulan
oturum belirteci, HttpOnly/SameSite çerez, 15 dakikada 5 hatalı deneme sınırı, başka siteden gelen
form isteklerinin reddi, CSP ve diğer güvenlik başlıkları. Kayıt yok; kullanıcıyı yönetici açar ve
her kullanıcı yalnız kendi mağazasını görür. İnternete açma adımları: [deploy/KURULUM.md](../deploy/KURULUM.md).

Panelde: dönem seçimi (7 gün / 28 gün / 8 hafta / 3 ay / özel tarih) ve önceki eşit dönemle karşılaştırma,
6 KPI, günlük net kâr grafiği, uyarılar, sıralanabilir ürün tablosu, veri tazeliği ve dosya yükleme.

- Veri "anlık" değil: en son yüklenen dosya kadar güncel; panel son sipariş zamanını gösterir.
- Satıcı dışa aktarım dosyasını panelden yükleyebilir. Dosya önce okunup denetlenir; okunamazsa
  klasöre girmez, eski veri bozulmaz. Yüklenen dosya haftalık rapor da kullanır.
- Yüklenen dosyadan yalnız raporun kullandığı sütunlar saklanır (KVKK: müşteri adı, adres, telefon diske yazılmaz).

## Akış

`clean.py` (sütun eşleme, Türkçe sayı/tarih, çift ve eksik satır) → `storage.py` (DuckDB)
→ `metrics.py` (tüm sayılar SQL ile) → `alerts.py` (kurallar) → `report.py` + `charts.py` (HTML).

Gerçek dışa aktarım gelince yalnız `config/mapping.yaml` içindeki sütun adları değişir.

## Yapay zeka yorumu

`narrative.py` hesaplanmış sayıları Türkçe biçimlenmiş bir olgu paketine koyar ve Claude'a
(`claude-opus-5-5`, effort `medium`, JSON şemalı çıktı) gönderir. Model sayı hesaplamaz:
yanıttaki her sayı paketle karşılaştırılır; uymayan sayı varsa bir kez düzeltme istenir,
yine uymazsa kural tabanlı özet kullanılır. Model güvenlik gerekçesiyle reddederse sunucu
isteği önerilen başka modelde yeniden dener (`fallbacks: "default"`).

Kimlik bilgisi yoksa rapor yine üretilir, özet kural tabanlı olur. Açmak için:

```powershell
$env:ANTHROPIC_API_KEY = "<anahtar>"
.venv\Scripts\python cli.py calistir
```

`--yz-yok` yapay zekayı kapatır. Modele kişisel veri gitmez; yalnız haftalık toplamlar ve ürün adları.

Sınır: denetim sayının pakette *var olduğunu* kontrol eder, doğru ölçüye bağlandığını değil
(ör. net kârı brüt satış diye yazması yakalanmaz). İlk gerçek yanıtlar elle okunmalı.

## Doğrulanacak varsayımlar

- Sentetik dosyanın sütun adları gerçek Trendyol/Hepsiburada dışa aktarımına ait değil.
- Kargo sipariş başına bir kez sayılıyor; iade siparişinde satıcıda kalıyor.
- İadede komisyon geri dönüyor.
- KDV, reklam gideri, ceza/kesinti henüz yok.
- Uyarı eşikleri (`alerts.py` başı) satıcıyla konuşulup ayarlanacak.

## Sonraki adımlar

1. Gerçek bir satıcıdan dışa aktarım dosyası; mapping ve varsayımların doğrulanması.
2. Yapay zeka yorumunu gerçek API anahtarıyla deneyip ilk yanıtları elle okumak.
3. Kendi adresine gerçek bir deneme gönderimi; Gmail/Outlook'ta görünümün kontrolü.
4. Pazaryeri API bağlantısı (dosyayı elle koyma adımını kaldırmak için).
