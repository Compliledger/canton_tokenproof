# Security Policy

## Supported versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Active  |

---

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Report security issues by emailing the maintainers directly. Include:

- A description of the vulnerability
- The layer affected (DAML contracts / backend / SDK)
- Steps to reproduce
- Potential impact

You will receive an acknowledgement within 48 hours. We aim to release a fix or mitigation within 14 days for critical issues.

---

## Scope

### In scope

- DAML authorization bypass — any path that allows an unauthorized party to create, archive, or exercise a choice on `ComplianceProof`, `ComplianceGuard`, or `EvaluationRequest`.
- Backend authentication bypass — any path that allows unauthenticated access to ledger command submission in a non-sandbox environment.
- Classification engine determinism violations — any input that causes `engine.classify` to return a different result for identical inputs on the same policy version.
- Proof hash collision — any practical collision in the SHA-256 proof hash construction.

### Out of scope

- Canton sandbox running without authentication (this is the intended local development configuration).
- `submitMustFail` test scripts exercising intentional failure paths.
- SDK client-side issues that require a compromised backend.

---

## Security model

TokenProof is a **PoC / Canton Dev Fund milestone project**. It is not yet hardened for MainNet production deployment. Specifically:

- The current Canton adapter accepts an empty JWT for local sandbox use. In a production deployment, a valid JWT from a Canton participant node must be configured via `CANTON_EVALUATOR_JWT`.
- The classification engine does not authenticate callers. In production, the `/evaluate` endpoint must be placed behind an authenticated API gateway.
- The `TOKENPROOF_PACKAGE_ID` must be pinned to the deployed DAR hash. Mismatched package IDs will cause template resolution failures.

---

## Disclosure policy

We follow coordinated disclosure. Once a fix is released, the vulnerability may be disclosed publicly with credit to the reporter.
