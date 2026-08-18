# Telegram production recovery drill

This drill validates recovery contracts without contacting a real provider, replaying money, or mutating production state. Run it only in a disposable development/test environment with provider writes disabled.

```bash
VPN_SALE_ENVIRONMENT=test \
VPN_SALE_PROVIDER_WRITES_ENABLED=false \
bash scripts/verify-recovery-drill.sh
```

The script refuses `production` and refuses provider writes.

## What the automated drill proves

### Stale durable claims
A stale Telegram service-operation notification claim may be reclaimed only after its existing bounded claim timeout. A fresh claim remains owned, and a terminal `FAILED` event is not selected by the claim query. Reclaiming increments the attempt count and clears only the retry failure category; it does not recreate financial/provider work.

Operator action: verify worker liveness first. Let the existing lease/claim code recover stale work. Never change `CLAIMED`/`FAILED` rows by hand merely to clear an alert.

### Terminal outbox failures
Terminal `FAILED` events are intentionally excluded from normal delivery claims. They require inspection of their bounded failure category before any targeted operator decision. There is no generic replay-all path.

Operator action: determine whether the underlying action is notification-only, financial, or provider-affecting. For financial/provider work, reconcile authoritative state before considering any targeted retry.

### Unresolved paid service operations
`PARTIALLY_APPLIED`, `UNCERTAIN`, `COMPENSATION_REQUIRED`, and `MANUAL_REVIEW` remain blocking states for new same-service paid mutations. The customer must not be allowed to pay again while one of these states is unresolved.

Operator action: use the existing reconciliation/manual-review path. Do not create a replacement renewal/add-traffic operation and do not edit the service entitlement to guess the provider result.

### Provider-read failure
Missing provider traffic counters remain `UNKNOWN`: used/remaining traffic is not fabricated as zero. An unexplained counter decrease remains manual-review/unusable through the existing usage projection tests.

Operator action: restore read connectivity/certification and allow a later authoritative sync. Do not infer usage from Telegram-local or stale provider data.

### Worker restart / heartbeat
The main worker heartbeat uses one deterministic role and does not identify a host/process. Restarting the worker updates the same liveness row; durable business ownership remains in each existing queue/lease/idempotency mechanism, not in the heartbeat.

Operator action: a stale heartbeat can justify restarting the worker process, but a restart must not be accompanied by deleting queue rows or bypassing idempotency/admission checks.

## Manual staging drill after provider configuration exists

The repository-only drill is not a substitute for real provider-enabled staging. Once a disposable certified Sanaei environment is available, deliberately exercise these boundaries one at a time:

1. stop the worker after a durable event is queued, then restart and confirm exactly one terminal outcome;
2. interrupt a disposable provisioning/renewal/add-traffic request around provider I/O and confirm the existing reconciliation state before any retry;
3. temporarily make provider reads unavailable and confirm customer traffic becomes unknown/stale rather than zero;
4. attempt a second same-service paid mutation while the first is unresolved and confirm it is blocked before wallet mutation;
5. restore the provider and confirm normal authoritative state converges without manual database edits.

Use only disposable staging customers/services. Do not perform fault injection against production customers.
