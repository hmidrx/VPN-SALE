# Panel Integrations

PanelProvider contract covers auth, health, version, capabilities, capacity, subscription lifecycle actions, usage, expiry, URL retrieval, credential rotation, nodes/inbounds, reconciliation, and error mapping. Planned providers are FakePanelProvider, Sanaei3xUIProvider, and PasarGuardProvider. No real endpoints until specs are supplied.

## Milestone 6-A2B write-safety update

Provider writes remain disabled by default. Exact Sanaei `v3.5.0`, Alireza `v1.11.3` and PasarGuard panel `v4.0.2` contracts may only mutate after read certification, live staging write-canary certification, exact material matching, separate approval, immutable plan verification, idempotency checks and read-before/read-after verification. Unknown versions or contract changes require recertification before transport.
