# 'Verine sor' model karşılaştırması · 22.11.2026

Set: `sorular.yaml` (45 soru). Her model aynı setle 1 kez çalıştırıldı; puanlama sonuca göre. Maliyet liste fiyatıyla tahmindir.

| Model | Turlar (doğru/45) | Ortalama | En düşük | Soru başına maliyet | Ortalama süre |
|---|---|---|---|---|---|
| `claude-sonnet-5-5` | 44 | %97.8 | %97.8 | 0.66 sent | 3.9 sn |
| `claude-haiku-5-5` | 45 | %100.0 | %100.0 | 0.04 sent | 3.5 sn |

## Yanlış cevaplanan sorular

Parantez içi: kaç turda yanlış.

- `claude-sonnet-5-5`: kilif-kargo-payi (1)
- `claude-haiku-5-5`: yok

## Örnek hatalar

**claude-sonnet-5-5 · kilif-kargo-payi** · Şeffaf telefon kılıfında kargo, cironun yüzde kaçı? — beklenen satır yok: (0.5094354320045698,)

```sql
SELECT SUM(kargo) / SUM(brut_satis) AS kargo_orani FROM satis WHERE urun ILIKE '%şeffaf telefon kılıfı%'
```
