# BOT-2B activation and delivery

## Architecture

Provisioning and activation are separate durable operations. Provisioning creates a disabled
remote identity and a local `PENDING_ACTIVATION` service. The activation worker owns a stable
per-service attempt identity, claims work with a five-minute database lease, and moves the service
through `ACTIVATING`. A retry always begins with an authoritative provider read.

The service becomes `ACTIVE` in the same database transaction that persists the encrypted delivery
record and the entitlement clock. `starts_at`, `activated_at`, and `expires_at` are derived from one
provider-verified activation instant; purchase and provisioning timestamps are never used.

Delivery configuration is AEAD-encrypted and addressed by an opaque payload reference. Customer
projections use `service_delivery_records.delivery_ready`, rather than inferring readiness from the
service lifecycle or attachment count.

## Verified Sanaei 3x-ui v3.5.0 contract

The implementation was checked against upstream tag `v3.5.0`, commit
`4e928a1ce0945a6e956aa63365034ec24d2b1387`, including its generated OpenAPI contract:

* `GET /panel/api/clients/get/{email}` returns the authoritative full client object.
* `POST /panel/api/clients/update/{email}` replaces the full client object; it is not a patch.
* `GET /panel/api/clients/links/{email}` generates the attached inbound configuration URLs.

Activation therefore reads the full object, verifies its deterministic identity, changes only
`enable` and `expiryTime`, writes the full object, and performs read-after-write before requesting
links. A lost update response is reconciled and never causes an immediate duplicate update.

## Operations and rollback

Migration `0038_bot_2b_activation` follows `0037` and adds indexed activation attempts and delivery
records. Its downgrade drops only those new tables and indexes. Before rollback, stop activation
workers and retain an encrypted backup: provider activations already applied are not reversed by a
database downgrade. Provider write enablement, version/digest certification, TLS, and credential
vault gates remain mandatory operational prerequisites.

Local startup remains `docker compose up --build`; migrations run through the existing API Alembic
lifecycle. Activation workers should be drained before deployment rollback.
