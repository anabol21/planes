# ADR-0001: monorepo, ports, and integration branch

- Status: accepted for prototype
- Date: 2026-09-21

## Decision

Use one monorepository with path ownership, short task branches, `dev` as the integration branch, and `main` as accepted checkpoint state. Separate backend orchestration from compute execution through an `OptimizationEngine` port.

## Why

Three people can work independently while sharing versioned contracts and fixtures. The port lets Ruslan test the backend with a fake engine, Grisha develop a pure solver, and Misha build the VPS adapter without forcing synchronized implementation.

## Consequences

- Shared contract changes need coordination.
- A vertical-slice test is required before promotion to `main`.
- Separate repositories or duplicated DTO definitions are rejected for the prototype.
