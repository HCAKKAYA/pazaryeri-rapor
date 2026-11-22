# 'Verine sor' model karşılaştırması · 22.11.2026

Set: `gorulmemis.yaml` (20 soru). Her model aynı setle 3 kez çalıştırıldı; puanlama sonuca göre. Maliyet liste fiyatıyla tahmindir.

| Model | Turlar (doğru/20) | Ortalama | En düşük | Soru başına maliyet | Ortalama süre |
|---|---|---|---|---|---|
| `claude-opus-5-5` | 19 · 19 · 20 | %96.7 | %95.0 | 1.54 sent | 5.0 sn |
| `claude-sonnet-5-5` | 20 · 20 · 20 | %100.0 | %100.0 | 0.73 sent | 3.9 sn |
| `claude-haiku-5-5` | 18 · 19 · 19 | %93.3 | %90.0 | 0.05 sent | 3.9 sn |

## Yanlış cevaplanan sorular

Parantez içi: kaç turda yanlış.

- `claude-opus-5-5`: g20 (2)
- `claude-sonnet-5-5`: yok
- `claude-haiku-5-5`: g20 (3), g15 (1)

## Hatalar ve elle incelenecek (yorumlu) sorular

Her model için her sorunun ilk görüldüğü tur.

**claude-opus-5-5 · g16** · son zamanlarda hangi ürünler iyi gidiyor — yorumlu: SQL elle incelenecek

```sql
SELECT urun, SUM(adet) FILTER (WHERE durum = 'teslim') AS satilan_adet, SUM(brut_satis) AS ciro FROM satis WHERE tarih > DATE '2026-11-15' - INTERVAL 30 DAY AND tarih <= DATE '2026-11-15' GROUP BY urun HAVING SUM(brut_satis) > 0 ORDER BY ciro DESC LIMIT 10
```

**claude-opus-5-5 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
SELECT date_trunc('week', tarih) AS hafta, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM satis WHERE date_trunc('week', tarih) IN (date_trunc('week', DATE '2026-11-15'), date_trunc('week', DATE '2026-11-15') - INTERVAL 7 DAY) GROUP BY 1 ORDER BY hafta
```

**claude-sonnet-5-5 · g16** · son zamanlarda hangi ürünler iyi gidiyor — yorumlu: SQL elle incelenecek

```sql
SELECT urun, SUM(net_kar) AS net_kar FROM satis WHERE tarih BETWEEN DATE '2026-11-15' - INTERVAL 29 DAY AND DATE '2026-11-15' GROUP BY urun HAVING SUM(net_kar) > 0 ORDER BY net_kar DESC LIMIT 10
```

**claude-haiku-5-5 · g15** · geçen haftaya göre bu hafta teslim edilen sipariş sayısı artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
SELECT CAST(date_trunc('week', tarih) AS DATE) AS hafta, COUNT(DISTINCT siparis_no) FILTER (WHERE durum = 'teslim') AS teslim_siparis_sayisi FROM satis WHERE tarih >= DATE '2026-11-02' AND tarih <= DATE '2026-11-15' GROUP BY 1 ORDER BY 1
```

**claude-haiku-5-5 · g16** · son zamanlarda hangi ürünler iyi gidiyor — yorumlu: SQL elle incelenecek

```sql
SELECT urun, barkod, SUM(brut_satis) AS ciro, SUM(adet) FILTER (WHERE durum = 'teslim') AS satilan_adet, SUM(net_kar) AS net_kar FROM satis WHERE tarih > DATE '2026-11-15' - INTERVAL 30 DAY GROUP BY urun, barkod ORDER BY ciro DESC LIMIT 10
```

**claude-haiku-5-5 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
WITH h AS (SELECT CASE WHEN tarih >= DATE '2026-11-02' AND tarih < DATE '2026-11-09' THEN 'geçen hafta' WHEN tarih >= DATE '2026-10-26' AND tarih < DATE '2026-11-02' THEN 'önceki hafta' END AS donem, brut_satis, net_kar, kargo FROM satis WHERE tarih >= DATE '2026-10-26' AND tarih < DATE '2026-11-09') SELECT donem, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM h WHERE donem IS NOT NULL GROUP BY donem ORDER BY CASE donem WHEN 'geçen hafta' THEN 1 ELSE 2 END
```
