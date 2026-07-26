# Baseline Verification

This document defines the minimum verification gate that every change must pass before it can be merged into `main`.

## Required automated checks

- Backend: formatting, linting, strict type checking, the complete pytest suite, PostgreSQL migration upgrade/current/downgrade/re-upgrade, and API startup smoke checks.
- Frontend: dependency audit, linting, strict TypeScript checks, workspace tests, and production builds for customer, administrator, and reseller applications.
- Docker: Compose rendering, image builds, service health checks, reverse-proxy checks, and cleanup.
- Security: repository secret and dependency baseline checks.

## Result vocabulary

- `PASS`: the check ran and completed successfully.
- `FAIL`: the check ran and failed. The change must not be merged.
- `NOT_RUN`: the check could not run because a required external environment or credential was unavailable. It must never be represented as a pass.

## Merge rule

A pull request is mergeable only when all four required jobs pass and the final verification gate succeeds. Live payment-provider and VPN-panel certification are separate staging gates and remain `NOT_RUN` until dedicated test credentials and endpoints are configured.

## Delivery workflow

Each product capability is implemented in one focused pull request, validated by automated tests, deployed to the TEST server, exercised through a documented customer/operator scenario, and repaired before merge.
