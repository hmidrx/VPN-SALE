# Milestone 6-A1 — Production provider core and read-only certified adapters

Extraction date: 2026-07-18. Official GitHub release pages were rechecked on 2026-07-18; stable latest releases remained MHSanaei/3x-ui v3.5.0, alireza0/x-ui v1.11.3 and PasarGuard/panel v4.0.2 after Milestone 6-A2A correction; the prior v5.1.0 target is invalidated. Development builds and prereleases were ignored.

## Scope

Milestone 6-A1 implements safe connectivity, exact version detection, read-only inventory normalization, capability discovery, health, drift, credential encryption, endpoint security, administrator console surfaces, deterministic mocks/tests and operator-only live certification scaffolding. Provider writes, provisioning, allocation, subscription generation, QR/config delivery and service operations remain explicitly disabled.

## Mermaid flows

### Adapter resolution
```mermaid
flowchart LR
  Admin[Admin API / worker] --> Service[Provider application service]
  Service --> Registry[Adapter registry]
  Registry --> Version{Exact version + digest?}
  Version -->|match| Adapter[Certified versioned adapter]
  Version -->|unknown| Diagnostics[Version/health diagnostics only]
```

### Secure connection
```mermaid
flowchart LR
  URL[Admin URL] --> Parse[Strict parser]
  Parse --> DNS[DNS resolve]
  DNS --> Policy[SSRF/IP/port policy]
  Policy --> TLS[TLS CA or fingerprint pin]
  TLS --> Transport[Redirect-limited HTTP transport]
```

### Credential handling
```mermaid
flowchart LR
  Secret[One-way entry] --> AEAD[AES-GCM per-record nonce]
  AEAD --> DB[(Ciphertext only)]
  DB --> Runtime[Bounded plaintext in adapter memory]
  Runtime --> Audit[Sanitized audit metadata]
```

### Read-only synchronization and drift
```mermaid
flowchart TD
  A[Load enabled panel] --> B[Decrypt credential]
  B --> C[Validate endpoint/TLS]
  C --> D[Detect version and contract]
  D --> E[Fetch bounded read-only inventory]
  E --> F[Normalize snapshots]
  F --> G[Compare projection]
  G --> H[Record drift]
  H --> I[Commit sync run atomically]
```

### Live certification
```mermaid
flowchart LR
  CLI[operator --live] --> Panel[Configured panel]
  Panel --> Reads[Safe read operations]
  Reads --> Report[Sanitized certification report]
  Report --> State[LIVE_VERIFIED only on success]
```

## Validation policy

CI uses deterministic mock servers only. Real staging panels are certified through an explicit live command/action requiring an acknowledgement flag and never printing credentials, cookies, raw users or full URLs.
