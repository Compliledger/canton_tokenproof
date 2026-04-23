# Changelog

All notable changes to TokenProof are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Changed

- `GENIUS_v1` policy pack now accepts `bank` and `bank_trust` as recognized aliases for `insured_depository_institution`.
- `/verify` endpoint now fetches the stored proof from ACS and reuses the original ledger timestamp for deterministic hash recomputation.
- `engine.classify` accepts optional `override_timestamp` parameter for replay-accurate verification.
- Timestamp is canonicalized to UTC `Z`-suffix format before hashing, matching Canton's stored timestamp representation.

---

## [0.1.0] — 2026-04-15

### Added

- **DAML contract layer** (`daml/`)
  - `Main.ComplianceProof` — core on-ledger compliance record with `SuspendProof`, `RevokeProof`, `ReEvaluate` choices.
  - `Main.ComplianceGuard` — DAML interface with `checkCompliance` method; any CIP-0056 token can implement.
  - `Main.EvaluationRequest` — request lifecycle tracking with `MarkEvaluated` and `ArchiveRequest` choices.
  - `Main.Types` — `DecisionStatus`, `PolicyPack`, `AssetBucket` shared types.
  - DAML test suite: `complianceProofLifecycleTest`, `transferGateTest`.

- **Example packages**
  - `examples/cip0056-gated-transfer/` — `TokenBond` gated transfer + `DvPWorkflow` atomic delivery-vs-payment demo.
  - `examples/stablecoin-genius-act/` — `StablecoinToken` with GENIUS Act minting gate.

- **Backend** (`backend/`)
  - `engine.py` — deterministic classification engine, SHA-256 proof hash.
  - `api.py` — FastAPI endpoints: `POST /evaluate`, `GET /proof/{assetId}`, `POST /verify`, `POST /parties/allocate`.
  - `canton_adapter.py` — Canton JSON Ledger API v2 adapter: command submission, ACS query, party allocation.
  - Policy packs: `GENIUS_v1`, `CLARITY_v1`, `SEC_CLASSIFICATION_v1`.
  - Backend unit tests in `backend/tests/`.

- **CI** (`.github/workflows/ci.yml`)
  - DAML build + test for all three packages.
  - Python lint (`ruff`) + backend unit tests.
  - TypeScript SDK build.

- **Docs**
  - `docs/architecture.md` — four-layer design, DAML contract reference, Canton privacy model, API endpoint table, Mermaid diagrams.
  - `docs/quickstart.md` — end-to-end setup from `dpm build` to `POST /verify`.

### Fixed

- `ComplianceGuard` interface uses `checkCompliance` (not `getComplianceStatus`).
- Canton JSON Ledger API v2: `userId` required in command submission and ACS query bodies.
- Canton JSON Ledger API v2: `activeAtOffset` required in ACS queries.
- Submit response parsing uses `updateId` (not legacy event array).
- Authorization patterns: `signatory issuer`, `observer owner, evaluator` in example templates.
- `datetime` usage in DAML tests updated to `DA.Time`-compatible form.

### Technical notes

- Canton SDK version: 3.4.11.
- JSON Ledger API: v2 (port 6864 HTTP / 6865 gRPC with bare `dpm sandbox`; port 7575 HTTP / 6866 gRPC with CN Quickstart LocalNet). Set `CANTON_LEDGER_API_URL` to match your setup.
- Global contract keys removed in Daml-LF 2.x; `ComplianceProof` uses explicit `ContractId` passing.
- Sandbox runs in no-auth mode (`wildcard`) for local development.
