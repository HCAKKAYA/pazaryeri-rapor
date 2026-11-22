# Görülmemiş set · kısmi sonuç · 22.11.2026

Set: `gorulmemis.yaml` (20 soru, Hüseyin yazdı; istem 336886e'de donduruldu). Plan: 3 model × 3 tur.
Ölçüm, API kredisi bittiği için yarıda kaldı. Aşağıda yalnız kredi bitmeden alınan geçerli cevaplar var.

| Model | Tur | Doğru | Not |
|---|---|---|---|
| `claude-opus-5-5` | 1 | 19/20 | Tek hata g20 (iki parçalı, yazım hatalı soru): model iki haftayı iki satır olarak döndürdü, referans tek satırda altı değer bekliyordu. Cevap muhtemelen doğru; puanlayıcı biçim yüzünden yanlış saydı. SQL kaydedilmedi, g20 yeniden çalıştırılıp elle incelenecek. |
| `claude-opus-5-5` | 2 | 8/8 | g01-g08 cevaplandı, sonra kredi bitti. |
| `claude-sonnet-5-5`, `claude-haiku-5-5` | - | - | Kredi bittiği için hiç ölçülmedi. |

Geçerli cevaplar: **27/28**. g16 ("son zamanlarda hangi ürünler iyi gidiyor", yorumlu) Opus'ta cevaplandı; SQL'i
kaydedilmediği için elle incelenmedi. g17-g19 (İzmir, kampanya, müşteri) Opus'ta doğru şekilde "cevaplanamaz" dendi.

Yapılacak: kredi yüklendikten sonra seti 3 model × 3 tur baştan çalıştırmak. İstem hâlâ donmuş durumda.
