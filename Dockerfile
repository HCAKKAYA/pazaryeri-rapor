# Satıcı paneli. Kalıcı veri /app/data (kullanıcılar, oturumlar) ve /app/gelen (satıcı dosyaları)
# klasörlerinde durur; ikisi de sunucuda birim (volume) olarak bağlanır.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PANEL_HTTPS=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY rapor ./rapor
COPY config/mapping.yaml ./config/mapping.yaml
COPY cli.py .

RUN useradd --create-home --uid 10001 panel \
    && mkdir -p /app/data /app/gelen \
    && chown -R panel:panel /app/data /app/gelen
USER panel

EXPOSE 8791
# Önünde HTTPS sağlayan vekil sunucu (Caddy) olacak; X-Forwarded başlıkları yalnız ondan kabul edilir.
CMD ["python", "cli.py", "panel", "--host", "0.0.0.0", "--port", "8791", "--proxy", "*"]
