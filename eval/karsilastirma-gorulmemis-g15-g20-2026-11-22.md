# 'Verine sor' model karşılaştırması · 22.11.2026

Set: `gorulmemis.yaml` (2 soru). Her model aynı setle 3 kez çalıştırıldı; puanlama sonuca göre. Maliyet liste fiyatıyla tahmindir.

**Esnek**: katı ölçütte yanlış sayılan ama tüm değerleri doğru olup yalnız biçimi farklı olan cevaplar (ör. iki haftayı iki satırda vermek) doğru sayılır.

| Model | Turlar (doğru/2) | Ortalama | En düşük | Esnek ortalama | Soru başına maliyet | Ortalama süre |
|---|---|---|---|---|---|---|
| `claude-opus-5-5` | 2 · 2 · 1 | %83.3 | %50.0 | %100.0 | 2.69 sent | 10.4 sn |
| `claude-sonnet-5-5` | 1 · 2 · 2 | %83.3 | %50.0 | %100.0 | 1.09 sent | 5.8 sn |
| `claude-haiku-5-5` | 1 · 1 · 1 | %50.0 | %50.0 | %50.0 | 0.09 sent | 6.7 sn |

## Yanlış cevaplanan sorular

Parantez içi: kaç turda yanlış.

- `claude-opus-5-5`: g20 (1)
- `claude-sonnet-5-5`: g20 (1)
- `claude-haiku-5-5`: g20 (3)

## Hatalar ve elle incelenecek (yorumlu) sorular

Her model için her sorunun ilk görüldüğü tur.

**claude-opus-5-5 · tur 3 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — biçim farklı, değerler tam (beklenen 1 satır, gelen 2)

```sql
SELECT CASE WHEN date_trunc('week', tarih) = date_trunc('week', DATE '2026-11-15') THEN 'bu_hafta' ELSE 'gecen_hafta' END AS donem, MIN(date_trunc('week', tarih))::DATE AS hafta_baslangic, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM satis WHERE date_trunc('week', tarih) IN (date_trunc('week', DATE '2026-11-15'), date_trunc('week', DATE '2026-11-15') - INTERVAL 7 DAY) GROUP BY 1 ORDER BY hafta_baslangic
```

**claude-sonnet-5-5 · tur 1 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — biçim farklı, değerler tam (beklenen 1 satır, gelen 2)

```sql
SELECT date_trunc('week', tarih) AS hafta_baslangic, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM satis WHERE date_trunc('week', tarih) IN (date_trunc('week', DATE '2026-11-15'), date_trunc('week', DATE '2026-11-15') - INTERVAL 7 DAY) GROUP BY 1 ORDER BY 1
```

**claude-haiku-5-5 · tur 1 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
WITH h AS (SELECT CAST(date_trunc('week', tarih) AS DATE) AS hafta_baslangic, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM satis WHERE tarih >= DATE '2026-10-26' AND tarih < DATE '2026-11-09' GROUP BY 1) SELECT hafta_baslangic, ciro, net_kar, kargo FROM h ORDER BY hafta_baslangic
```

**claude-haiku-5-5 · tur 2 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
WITH h AS (SELECT CAST(date_trunc('week', tarih) AS DATE) AS hafta, brut_satis, net_kar, kargo FROM satis WHERE tarih >= DATE '2026-10-26' AND tarih < DATE '2026-11-09') SELECT hafta, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo_masrafi FROM h GROUP BY hafta ORDER BY hafta
```

**claude-haiku-5-5 · tur 3 · g20** · gecen hfya gore ciro ve kar ne durumda, kargo masrafı da artmış mı — satır sayısı farklı (beklenen 1, gelen 2)

```sql
SELECT CAST(date_trunc('week', tarih) AS DATE) AS hafta_baslangic, SUM(brut_satis) AS ciro, SUM(net_kar) AS net_kar, SUM(kargo) AS kargo FROM satis WHERE tarih >= DATE '2026-10-26' AND tarih < DATE '2026-11-09' GROUP BY 1 ORDER BY 1
```
