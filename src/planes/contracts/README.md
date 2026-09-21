# Shared contracts

This directory is jointly owned. It will contain versioned DTOs, engine ports, and serialization fixtures. No workstream may maintain an incompatible private copy of a shared entity.

The first contract-freeze task must add schemas and golden fixtures for `ComputeRequest v0` and `ComputeResponse v0`, followed by the domain entities listed in `docs/architecture/INTERFACES_V0.md`.
