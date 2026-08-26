# راه‌اندازی Production روی سرور

این راهنما برای Ubuntu 24.04، Docker Engine/Compose v2، یک سرور با IP ثابت و شش
زیردامنه نوشته شده است. پرداخت این نسخه فقط کارت‌به‌کارت و کیف پول است؛ هیچ کلید یا
callback مربوط به زرین‌پال و درگاه آنلاین نباید تنظیم شود.

## ۱. پیش‌نیاز و DNS

حداقل پیشنهادی: ۴ هسته، ۸ گیگابایت RAM، ۸۰ گیگابایت SSD و backup خارج از سرور.
رکورد A/AAAA دامنه‌های `app`، `admin`، `reseller`، `api`، `sub` و `bot` را به سرور
وصل کنید. پورت‌های عمومی فقط 22، 80 و 443 باشند؛ PostgreSQL، Redis و پورت‌های برنامه
فقط روی شبکه داخلی Docker یا loopback می‌مانند.

```bash
sudo apt update
sudo apt install -y ca-certificates curl git caddy
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"
newgrp docker
sudo install -d -m 0700 /opt/vpn-sale-runtime /opt/vpn-sale
sudo chown -R "$USER":"$USER" /opt/vpn-sale
git clone https://github.com/hmidrx/VPN-SALE.git /opt/vpn-sale/app
cd /opt/vpn-sale/app
```

## ۲. secrets و environment

نمونه را بیرون repository کپی کنید و همهٔ `REDACTED`/`example.invalid`ها را عوض
کنید. کلیدها باید تصادفی و مستقل باشند و فایل نهایی با permission برابر 0600 بماند.

```bash
sudo cp infra/deployment/env/production.env.example /opt/vpn-sale-runtime/production.env
sudo install -d -m 0700 /opt/vpn-sale-runtime/secrets
openssl rand -base64 48 | tr -d '\n' | sudo tee /opt/vpn-sale-runtime/secrets/telegram-internal-token >/dev/null
sudo chmod 0600 /opt/vpn-sale-runtime/production.env /opt/vpn-sale-runtime/secrets/telegram-internal-token
sudoedit /opt/vpn-sale-runtime/production.env
```

`VPN_SALE_SUBSCRIPTION_PUBLIC_ORIGIN` همان دامنه دلخواه ساب‌لینک، مثلاً
`https://sub.example.com` است. برای شروع
`VPN_SALE_PROVIDER_WRITES_ENABLED=false` بماند. مقدار
`VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST` را در shell روی مسیر secret بالا بگذارید.

## ۳. build، migration و ادمین اول

```bash
export VPN_SALE_PRODUCTION_ENV_FILE=/opt/vpn-sale-runtime/production.env
export VPN_SALE_TELEGRAM_INTERNAL_TOKEN_FILE_HOST=/opt/vpn-sale-runtime/secrets/telegram-internal-token
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml config >/dev/null
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml build --pull
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml up -d postgres redis
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml run --rm api \
  alembic -c /app/apps/api/alembic.ini upgrade head
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml run --rm api \
  python -m platform_api.cli bootstrap-admin --email admin@example.com
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml up -d
```

رمز Super Admin را در password manager نگه دارید و MFA را بلافاصله فعال کنید.

## ۴. Caddy و Telegram

```bash
sudo cp infra/deployment/production/Caddyfile.example /etc/caddy/Caddyfile
sudo systemctl edit caddy
```

محتوای override:

```ini
[Service]
EnvironmentFile=/opt/vpn-sale-runtime/production.env
```

سپس:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

بعد از بالا آمدن HTTPS، webhook را با همان `VPN_SALE_TELEGRAM_WEBHOOK_SECRET_TOKEN` ثبت کنید
و Mini App دامنه `app` را در BotFather مجاز کنید. توکن ربات را در command history
چاپ نکنید.

## ۵. تنظیم داخل پنل ادمین

به‌ترتیب مقصد کارت‌به‌کارت، کاتالوگ/قیمت، پنل‌های Sanaei 3x-ui دقیقاً نسخه 3.7.0،
credential، تست اتصال و sync اینباندها را ثبت کنید. سپس pool و targetهای چنداینباندی،
policy تخصیص و delivery profile هر target را validate و publish کنید. ابتدا با writes
خاموش simulation بگیرید. فقط بعد از موفقیت staging و backup، مقدار
`VPN_SALE_PROVIDER_WRITES_ENABLED=true` را قرار دهید و worker را recreate کنید.

## ۶. کنترل سلامت، backup و ارتقا

```bash
curl -fsS https://api.example.com/health
curl -fsS https://api.example.com/ready
docker compose --env-file "$VPN_SALE_PRODUCTION_ENV_FILE" \
  -f docker-compose.yml -f docker-compose.production.yml ps
```

backup رمزنگاری‌شده PostgreSQL و private media را روزانه به فضای خارج سرور بفرستید و
restore drill دوره‌ای انجام دهید. برای ارتقا: backup، `git pull --ff-only`، build،
migration، `up -d`، health/readiness و یک خرید آزمایشی کارت‌به‌کارت را اجرا کنید. در
صورت خطا writes پنل را فوراً false کنید؛ rollback دیتابیس فقط طبق runbook و پس از
restore test انجام شود.
