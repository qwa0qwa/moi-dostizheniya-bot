
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt \
    REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

WORKDIR /app

# Установка системных сертификатов и OpenSSL
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        openssl \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Файлы проекта
COPY . .

# Конвертация корневого сертификата DER -> PEM
RUN openssl x509 \
    -inform DER \
    -in /app/russian_root_ca.cer \
    -out /usr/local/share/ca-certificates/russian_root_ca.crt

# Промежуточные сертификаты (уже PEM)
COPY Russian_Trusted_Sub_CA.cer /usr/local/share/ca-certificates/russian_sub_ca.crt
COPY Russian_Trusted_Sub_CA_2024.cer /usr/local/share/ca-certificates/russian_sub_ca_2024.crt

# Обновление хранилища сертификатов
RUN update-ca-certificates

# Каталоги приложения
RUN mkdir -p /app/data /app/documents /app/logs

CMD ["python", "main.py"]
