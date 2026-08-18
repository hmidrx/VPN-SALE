# Provider-enabled Telegram staging E2E

This is the final external validation before calling the Telegram customer path production-ready. Repository CI is intentionally restrictive and never enables provider writes. The real smoke must run only against an operator-controlled, disposable staging customer/service and a certified Sanaei/3x-ui panel.

## Safety boundary

Use a dedicated staging runtime file outside Git, normally `/opt/vpn-sale-runtime/staging.env`, mode `0600` or `0400`. Never paste credentials, Telegram tokens, vault keys, subscription material or panel login details into Git, PR comments, shell arguments or test fixtures.

The staging runtime must explicitly contain:

- `VPN_SALE_ENVIRONMENT=staging`
- `VPN_SALE_PROVIDER_WRITES_ENABLED=true`
- `VPN_SALE_FAKE_CUSTOMER_AUTH_ENABLED=false`
- `VPN_SALE_PAYMENT_FAKE_SUCCESS_PUBLIC_ENABLED=false`
- `VPN_SALE_BOT_ENABLED=true`
- `VPN_SALE_BOT_MODE=polling`
- the normal production-grade API/identity signing/encryption configuration required by `Settings`
- the Telegram bot runtime values
- `PROVIDER_VAULT_MASTER_KEY_B64` and the matching key-version/keyring configuration when required
- database/Redis configuration for the isolated staging stack.

The provider/panel credential itself remains encrypted in the database. The worker is the only service that receives `VPN_SALE_PROVIDER_WRITES_ENABLED=true`; the API does not receive provider-write authority.

## Bring up the isolated Telegram staging stack

Render first:

```bash
bash scripts/vpn-sale-compose-staging --env-file /opt/vpn-sale-runtime/staging.env \
  --profile ops --profile telegram config >/dev/null
```

Apply migrations before normal processing:

```bash
bash scripts/vpn-sale-compose-staging --env-file /opt/vpn-sale-runtime/staging.env \
  --profile ops --profile telegram run --rm --no-deps api \
  alembic -c /app/apps/api/alembic.ini upgrade head
```

Start only the Telegram production path:

```bash
bash scripts/vpn-sale-compose-staging --env-file /opt/vpn-sale-runtime/staging.env \
  --profile ops --profile telegram up -d --build postgres redis api worker telegram-bot
```

Then run the fail-closed preflight/verification:

```bash
VPN_SALE_STAGING_CONFIRM=disposable-provider-write-smoke \
  bash scripts/verify-provider-staging.sh \
  --env-file /opt/vpn-sale-runtime/staging.env
```

The verifier refuses CI, non-staging environments, fake auth/payment, missing explicit provider writes and loose runtime-file permissions. It verifies private service exposure, migrations, API health, Telegram polling, safe logs and certified Sanaei configuration metadata. It does **not** mutate the provider.

## Real disposable end-to-end smoke

Use a dedicated staging customer with a small disposable plan and record only public references/statuses, never connection secrets.

1. **Purchase** — start from Telegram, choose the disposable plan, receive the authoritative quote and complete the intended staging payment/top-up path.
2. **Provision** — confirm exactly one fulfillment request reaches the certified Sanaei target and exactly one remote client is created.
3. **Activation/delivery** — confirm the service becomes active only after verified provisioning and the customer can explicitly request subscription/config material from Telegram.
4. **Usage** — generate a small amount of traffic, wait for authoritative usage sync, refresh the service and confirm remaining traffic changes without provider-local guesses.
5. **Renew** — buy a small renewal, confirm one wallet mutation and one verified provider mutation, then verify expiry changes.
6. **Add traffic** — buy a small traffic increment, confirm one wallet mutation and one verified provider mutation, then verify the authoritative quota/usage projection converges.
7. **Notifications** — exercise terminal operation notification plus one safe lifecycle/traffic threshold if practical on the disposable service.
8. **Restart/idempotency** — queue a harmless durable notification or controlled disposable operation, restart the worker once, and confirm no duplicate payment/provider application occurs.
9. **Admission safety** — while a disposable paid service operation is deliberately unresolved, attempt a second same-service mutation and confirm it is blocked before wallet mutation.
10. **Recovery** — restore normal provider state/readability and verify the service converges through existing reconciliation/usage paths without manual database edits.

## Immediate stop conditions

Stop the smoke and do not retry payment/provider work when any of these occur:

- provider response is ambiguous after a write;
- service operation reaches `PARTIALLY_APPLIED`, `UNCERTAIN`, `COMPENSATION_REQUIRED` or `MANUAL_REVIEW`;
- the wallet/payment result is uncertain;
- worker heartbeat becomes stale during a write;
- the remote client appears to exist but the local operation has not reached a verified terminal state;
- credentials, tokens or connection material appear in logs.

Use the existing reconciliation/manual-review path before any further paid mutation.

## Completion record

The repository can be marked **staging-harness ready** when CI is green and the guarded staging preflight exists. It can be marked **real E2E passed / production-ready** only after the external smoke above is actually executed against the disposable provider environment. Do not infer the external result from CI or mocked tests.
