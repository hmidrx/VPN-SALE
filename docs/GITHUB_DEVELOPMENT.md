# GitHub-Native Development and Verification

Milestone 0 verification is authoritative in GitHub because some local or Codex environments may not have access to package registries or Docker. The repository now supports browser-based development through GitHub Codespaces and CI verification through GitHub Actions.

## GitHub Actions

The main workflow is `.github/workflows/verify.yml`. It runs on pull requests targeting `main` or `master`, pushes to `main` or `master`, and manual `workflow_dispatch`. Permissions are read-only (`contents: read`) and concurrency cancels obsolete branch runs.

Jobs:

- `backend`: Python 3.12 with PostgreSQL 16 and Redis 7 service containers. Defines disposable CI database credentials at the backend job level, derives the application database URL for `127.0.0.1`, runs a sanitized PostgreSQL credential preflight, then runs formatting, linting, Pyright, pytest, Alembic upgrade/current/downgrade/re-upgrade, and API import/startup smoke checks.
- `frontend`: Node.js 22 with npm. Uses `npm ci` when `package-lock.json` exists and temporarily uses `npm install` with a warning when no lockfile exists. If that fallback generates `package-lock.json`, the workflow uploads it as the `generated-package-lock` artifact while keeping read-only repository permissions. Reports Node, npm, TypeScript, and Next.js versions, runs an npm audit gate for high and critical advisories, then runs lint, strict TypeScript checks, tests, clearly labeled real Next.js builds for customer, admin, and reseller apps, and shared package validation.
- `docker`: Runs Docker/Compose versions, `docker compose config`, builds the API image, starts PostgreSQL, Redis, API, and reverse proxy, verifies `/health`, `/ready`, `/version`, and `/metrics` through the reverse proxy, checks readiness content, and cleans up volumes.
- `security`: Runs the repository security baseline without requiring production secrets and without printing secret values. The scanner excludes only its deliberate pattern-source files from self-matching and continues to scan all other tracked source and configuration files.

## Run the workflow manually

1. Open the repository on GitHub.
2. Select **Actions**.
3. Select **Verify Milestone 0**.
4. Select **Run workflow**.
5. Choose the branch and confirm.

## Inspect failed jobs

1. Open the failed workflow run.
2. Select the failed job.
3. Expand the failed step.
4. Review the job summary for runtime versions and validation categories.
5. Download uploaded artifacts such as backend test reports when available.

## Open a Codespace

1. Open the repository on GitHub.
2. Select **Code**.
3. Select **Codespaces**.
4. Select **Create codespace on current branch**.
5. Wait for the dev container to build and for `scripts/bootstrap-dev.sh` to complete.

## Codespaces setup

The dev container is configured in `.devcontainer/devcontainer.json` and `.devcontainer/Dockerfile`. It provides Ubuntu 24.04, Python 3.12, Node.js 22, npm, GitHub CLI, curl, jq, PostgreSQL client, Redis client, Docker CLI, and Docker Compose through Docker-in-Docker. It does not depend on a local Docker daemon.

The post-create command runs:

```bash
bash scripts/bootstrap-dev.sh
```

The script creates `.venv` if missing, installs Python and Node dependencies, creates `.env` from `.env.example` only when absent, validates Docker availability, and prints next commands. It never commits files and never overwrites `.env`.

## Repository tasks

Use the VS Code command palette in the browser and run **Tasks: Run Task**. Available tasks:

- Bootstrap development environment
- Verify backend
- Verify frontend
- Verify Docker stack
- Verify everything
- Start core development stack
- Stop development stack

Equivalent terminal commands:

```bash
scripts/bootstrap-dev.sh
scripts/verify-backend.sh
scripts/verify-frontend.sh
scripts/verify-docker.sh
scripts/verify-all.sh
docker compose up --build api reverse-proxy
docker compose down --volumes --remove-orphans
```

## Generate and commit the npm lockfile

The first successful Codespaces bootstrap may generate `package-lock.json`. Review it and commit it exactly with:

```bash
git add package-lock.json
git commit -m "Add reproducible frontend dependency lockfile"
git push
```

After the lockfile is committed, CI uses `npm ci`, Codespaces bootstrap prefers `npm ci`, and npm caching uses the lockfile. Until then, download the `generated-package-lock` artifact from a frontend workflow run if you need to review the exact lockfile produced by GitHub Actions. The temporary no-lockfile fallback can be removed in a later small Milestone 0 cleanup PR.

## Rebuild the Codespace

If the dev container configuration changes:

1. Open the command palette.
2. Run **Codespaces: Rebuild Container**.
3. Re-run `scripts/bootstrap-dev.sh` if needed.

## Stop or delete unused Codespaces

Use GitHub **Codespaces** settings or the repository **Code > Codespaces** menu to stop or delete unused Codespaces and avoid unnecessary compute usage.

## Limitations

- CI must pass before treating Milestone 0 as fully verified.
- No production credentials are needed or allowed.
- Real Telegram, panel, payment, email, customer, or production domain configuration remains out of scope.
- Do not commit `.env`, private keys, provider credentials, cookies, subscription URLs, or generated build output.
