# Provisioning

Provisioning pipeline validates paid orders, acquires idempotency lock, selects route/panel, checks capacity, creates external resource, stores external operation IDs, verifies resource, stores sanitized data, delivers service, emits events, and releases locks. UNCERTAIN is mandatory after ambiguous timeouts; reconciliation precedes retries.
