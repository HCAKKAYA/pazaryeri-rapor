# Pazaryeri haftalık rapor

Pazaryeri satıcısının dışa aktarım dosyalarından (siparişler + ürün/maliyet/stok) her hafta
tek sayfalık bir rapor üretir: net kâr, haftalık değişim, uyarılar (stok, iade, zararına satış),
ürün tablosu ve veri kalitesi notu.

## Kurulum

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install duckdb pandas jinja2 matplotlib openpyxl pyyaml pytest anthropic
```

## Kullanım

```powershell
.venv\Scripts\python cli.py ornek        # sentetik veri: sample_data/
.venv\Scripts\python cli.py calistir     # rapor: raporlar/<mağaza>-<hafta>.html
.venv\Scripts\python cli.py calistir --siparis siparisler.xlsx --urun urunler.csv --magaza "Mağaza Adı" --hafta 2026-W46
.venv\Scripts\python -m pytest -q
```

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
3. PDF ve e-posta ile haftalık gönderim.
