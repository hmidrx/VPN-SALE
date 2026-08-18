# Alerting

The Telegram production path exposes a bounded, read-only operational health snapshot and Prometheus-compatible metrics under the authenticated admin surface:

- `GET /api/v1/admin/management/operations/health`
- `GET /api/v1/admin/management/operations/metrics`

These endpoints intentionally expose only fixed status classes, aggregate counts and ages. They must never include customer IDs, Telegram IDs, provider endpoints, remote identities, credentials, tokens, hostnames, process IDs or raw failure payloads.

## Health states

- `HEALTHY`: no bounded warning or operator-action signal is active.
- `DEGRADED`: work is retrying, blocked, lagging, usage observations are stale, or the worker reported a short recent cycle failure without losing liveness.
- `ACTION_REQUIRED`: worker liveness is missing/stale, repeated worker cycles are failing, or a terminal/manual-review class requires operator attention.

The main Telegram production worker writes one deterministic role heartbeat (`telegram-production`) at a bounded interval. The role is fixed; deployment-specific instance identifiers are deliberately not exported as metric labels or health payload fields. A healthy empty queue therefore remains distinguishable from a dead worker.

## Recovery signal guide

| Signal | Meaning | First operator action |
| --- | --- | --- |
| `WORKER_HEARTBEAT_MISSING` | No heartbeat has ever been recorded for the main Telegram production worker role. | Verify the worker container/process is deployed and migrations are current; do not mutate queue/provider state to hide the signal. |
| `WORKER_HEARTBEAT_STALE` | The main worker heartbeat is older than the bounded liveness threshold. | Check worker process/container health and database reachability, then restart only the worker if required. Existing durable claims/retries remain authoritative. |
| `WORKER_RECENT_CYCLE_FAILURE` | One or two consecutive main-loop cycles reported a component failure while the worker remains alive. | Inspect worker logs and the matching bounded queue/provider-read signals; allow normal retry/recovery first. |
| `WORKER_CYCLE_FAILURE_STREAK` | Three or more consecutive main-loop cycles reported at least one component failure. | Treat as operator action: identify the failing component from logs/other health signals before restarting or changing configuration. Never replay financial/provider work blindly. |
| `OUTBOX_FAILED` | Durable event exhausted its safe path or contains invalid persisted data. | Inspect the relevant admin outbox/recovery view and failure category; do not replay blindly. |
| `OUTBOX_STALE_CLAIMS` | A worker claim exceeded the generic 15-minute observability threshold. | Verify worker health/restarts, then allow the worker's existing stale-claim recovery path to arbitrate ownership. |
| `OUTBOX_RETRYING` | At least one durable event is waiting after a failed attempt. | Check whether retry volume/age is increasing before intervening. |
| `OUTBOX_LAGGING` | The oldest due event has waited at least 60 seconds. | Check worker availability and database pressure before changing queue state. |
| `FULFILLMENT_FAILED` | Provisioning reached a terminal failure path. | Confirm compensation/reconciliation state before any manual provider action. |
| `FULFILLMENT_OPERATOR_REVIEW` | Provisioning requires an operator decision. | Follow the recorded safe failure category and existing reconciliation workflow. |
| `FULFILLMENT_BLOCKED` | Provisioning is blocked, commonly by configuration or a safety gate. | Verify intended environment/provider-write configuration; never enable writes merely to clear a metric. |
| `FULFILLMENT_RETRYING` | Provisioning is waiting for its bounded retry schedule. | Observe the retry path unless the failure class or age indicates escalation. |
| `SERVICE_OPERATION_REVIEW_REQUIRED` | Renewal/add-traffic has an unresolved provider outcome. | Do not create or charge another same-service mutation; use the existing reconciliation/manual-review flow. |
| `USAGE_SYNC_DEGRADED` | A recent authoritative usage read was partial or failed. | Check provider-read reachability/certification and worker logs without changing provider state. |
| `USAGE_DATA_STALE` | An active usage account has no aggregate newer than 15 minutes. | Verify the read-only usage worker and provider-read health; stale data must remain unknown to customers. |

## Alerting guidance

Alert on `ACTION_REQUIRED` immediately. Alert on `DEGRADED` only after a persistence window appropriate to the signal (for example repeated samples or increasing age) so short retry cycles do not page operators. Keep alert labels low-cardinality and derive them only from the fixed signal/status vocabulary above.

Recovery actions must preserve the repository's idempotency, row-locking, reconciliation and provider-write gates. Never clear a signal by editing provider databases, fabricating usage, deleting durable events, bypassing payment/service-operation admission rules, or creating a generic "retry everything" path.
