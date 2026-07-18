# Deployment scaffold

Production deployment is deferred until staging readiness.

## Test-server port isolation

The disposable test-server deployment is rendered from `docker-compose.yml` plus `docker-compose.test-server.yml` with the `ops`, `web`, and `telegram` profiles enabled. Operators must inspect the rendered Compose model before startup, for example:

```bash
docker compose \
  --env-file /opt/vpn-sale-runtime/test.env \
  -f docker-compose.yml \
  -f docker-compose.test-server.yml \
  --profile ops \
  --profile web \
  --profile telegram \
  config --format json
```

The test server intentionally does not rely on UFW for service isolation. Only the host-installed Caddy process publishes internet-facing ports 80 and 443. Application containers publish API and web ports to `127.0.0.1` only so Caddy can proxy to them locally. PostgreSQL and Redis remain Docker-network-only and must not publish host ports.

`docker-compose.test-server.yml` uses Docker Compose sequence replacement tags (`!override` and `!reset`) to avoid merged duplicate or public bindings from the development Compose file. This requires Docker Compose 2.24.4 or newer; CI and Codespaces use Docker Compose v2 and the focused port-isolation script enforces the minimum version before rendering.

Run the focused regression check before starting the test server:

```bash
scripts/verify-test-server-compose.sh
```
