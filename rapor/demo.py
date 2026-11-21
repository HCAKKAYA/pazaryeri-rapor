"""Herkese açık demo için sentetik veri.

Veri her gün "dün"e kadar yeniden üretilir; böylece demo hangi gün açılırsa açılsın panel
güncel görünür ve gömülü desenler (stok bitti, zararına ürün, yüksek iade) hep son haftaya
denk gelir. Kalıcı disk gerekmez: sunucu yeniden başlarsa veri baştan üretilir.
"""
from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path

from . import sample

STORE_NAME = "Demo Mağaza"
STORE_SLUG = "demo-magaza"
DEMO_EMAIL = "demo@demo.local"
_MARKER = ".demo-bitis"
_lock = threading.Lock()


def data_end(today: date | None = None) -> date:
    return (today or date.today()) - timedelta(days=1)


def ensure_data(folder: Path, today: date | None = None) -> bool:
    """Veri dünden eskiyse yeniden üretir. Üretim yaptıysa True döner."""
    end = data_end(today)
    marker = folder / _MARKER
    with _lock:
        try:
            if marker.read_text(encoding="utf-8").strip() == end.isoformat():
                return False
        except FileNotFoundError:
            pass
        folder.mkdir(parents=True, exist_ok=True)
        # 26 hafta: en uzun hazır dönem (3 ay) ve önceki eşit dönemi birlikte kapsar.
        sample.generate(folder, end=end, weeks=26)
        marker.write_text(end.isoformat(), encoding="utf-8")
        return True
