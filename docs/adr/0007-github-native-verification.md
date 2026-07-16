# ADR 0007: GitHub-Native Milestone 0 Verification

## Status
Accepted for Milestone 0 infrastructure.

## Context
Some execution environments cannot access PyPI/npm and do not provide Docker, so local verification cannot be treated as authoritative for Milestone 0.

## Decision
Use GitHub Actions as authoritative CI verification and GitHub Codespaces as the reproducible browser-based development environment. Align CI and Codespaces on Python 3.12, Node.js 22, npm, Ubuntu Linux, PostgreSQL 16, Redis 7, and Docker Compose v2. Repository scripts are shared by CI and Codespaces.

## Consequences
Developers do not need local runtimes or Docker. The workflow uses read-only permissions and does not require production secrets. Until `package-lock.json` is generated and committed, frontend CI temporarily falls back to `npm install` with a warning and does not claim full reproducibility.
