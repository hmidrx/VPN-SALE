import { strict as assert } from 'node:assert';
import { readFileSync } from 'node:fs';

const dockerfile = readFileSync(new URL('../../../../infra/docker/web.Dockerfile', import.meta.url), 'utf8');
for (const key of [
  'NEXT_PUBLIC_API_BASE_URL',
  'NEXT_PUBLIC_CUSTOMER_API_BASE_URL',
  'NEXT_PUBLIC_TELEGRAM_BOT_USERNAME',
  'NEXT_PUBLIC_CUSTOMER_APP_NAME',
  'NEXT_PUBLIC_CUSTOMER_FAKE_TELEGRAM',
]) {
  assert.match(dockerfile, new RegExp(`ARG ${key}`));
  assert.match(dockerfile, new RegExp(`${key}=\\$${key}`));
}

const compose = readFileSync(new URL('../../../../docker-compose.test-server.yml', import.meta.url), 'utf8');
assert.match(compose, /NEXT_PUBLIC_API_BASE_URL: \$\{VPN_SALE_API_PUBLIC_ORIGIN/);
assert.match(compose, /NEXT_PUBLIC_TELEGRAM_BOT_USERNAME: \$\{VPN_SALE_TELEGRAM_BOT_USERNAME/);
assert.doesNotMatch(compose, /dr-ping\.com/);
