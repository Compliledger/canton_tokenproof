# Proposal Errata — TokenProof Canton Dev Fund Submission

This document records corrections that must be applied to the proposal text
(`proposals/tokenproof.md`) before the Canton Tech & Ops Committee review.
All corrections are reflected in the codebase already.

---

## 1. Remove `key` / `fetchByKey` claim (Section 2.1 — Critical)

**Current proposal text:**
```daml
key (assetId, evaluator) : (Text, Party)
maintainer key._2
```
> "The `(assetId, evaluator)` key design enables `fetchByKey @ComplianceProof`
> from any third-party `Transfer` choice without additional context —
> making TokenProof a drop-in compliance component for any Canton token
> implementation."

**Problem:**
Global contract keys are **not supported** in Canton 3.4 / Daml-LF 2.x.
The `key` and `maintainer` lines shown do not exist in the actual
`ComplianceProof.daml` template and would not compile on the target platform.
`fetchByKey` is not used anywhere in the codebase.

**Corrected text:**
```daml
-- Canton 3.4 / Daml-LF 2.x: global contract keys are not supported.
-- Callers pass ContractId ComplianceProof explicitly to Transfer / Mint choices.
-- fetch() on an archived contract fails atomically — no fetchByKey needed.
```

> "The `ContractId ComplianceProof` is passed explicitly to every Transfer and
> Mint choice. In multi-node deployments the caller obtains the
> `disclosedContracts` bundle from the TokenProof API
> (`GET /proof/{assetId}/disclosure`) and includes it in the
> `POST /v2/commands/submit-and-wait` request. This is the standard Canton
> pattern for cross-node contract visibility used by the Token Standard (CIP-0056)."

---

## 2. Replace "drop-in" claim with accurate integration description (Section 2.1)

**Current proposal text:**
> "making TokenProof a drop-in compliance component for any Canton token
> implementation."

**Problem:**
Without `fetchByKey`, integration is a 3-step process, not drop-in.

**Corrected text:**
> "TokenProof integrates with any CIP-0056 token in three steps:
> (1) add `proofCid : ContractId ComplianceProof` to the Transfer / Mint choice
> arguments, (2) call `fetch proofCid` and `assertMsg` on `decisionStatus`,
> (3) include the `disclosedContracts` bundle from the TokenProof API in the
> Ledger API submission. The compliance gate fires atomically inside the same
> Canton two-phase commit transaction as the asset movement."

---

## 3. Fix Canton JSON Ledger API port reference (Section 2.3)

**Current proposal text (inconsistent):**
Some sections reference port `6864`, others reference port `7575`.

**Correct value:**
`dpm sandbox` starts the JSON Ledger API on port **7575** and gRPC on port **6866**.
Port 6864 does not correspond to any Canton component.

**Required change:**
Replace every occurrence of `port 6864` with `port 7575` in the proposal.

---

## 4. Clarify that Daml Script tests run on single-node sandbox (Section 3 — CI)

**Current proposal text:**
> "CI green — `dpm build` and `dpm test` both pass"

**Required addition:**
> "Note: `dpm test` runs Daml Script tests in the Canton in-memory interpreter,
> not against a live Canton node. The tests verify Daml contract logic, proof
> lifecycle, and atomic enforcement at the interpreter level. Full end-to-end
> integration tests against a live sandbox are provided in
> `backend/tests/test_integration.py` and require a running `dpm sandbox`."

---

## 5. Clarify the TypeScript SDK scope (Section 2.5)

**Current proposal text:**
> "npm package using `@c7/ledger` (not deprecated `@daml/ledger`)"

**Problem:**
`@c7/ledger` is currently not in `sdk/package.json`. The M1–M3 SDK uses `axios`
for JSON Ledger API calls. `@c7/ledger` gRPC wiring is the M4 milestone.

**Corrected text:**
> "npm package using `axios` for JSON Ledger API calls in M1–M3. Migration to
> `@c7/ledger` for gRPC event streaming is the M4 deliverable (not the deprecated
> `@daml/ledger`)."

---

## 6. No changes required

The following technical claims in the proposal are accurate and require no
correction:

- DAML SDK version 3.4.11 ✓
- DPM toolchain (`dpm build --all`, `dpm test`) ✓
- `multi-package.yaml` structure for 3-package repo ✓
- `ComplianceGuard` interface pattern ✓
- `DecisionStatus` sealed sum type (Active / Suspended / Revoked) ✓
- SHA-256 proof hash using canonical JSON snapshot ✓
- `signatory issuer, evaluator` (co-signatory design) ✓
- `regulator : Optional Party` observer pattern ✓
- `submitMustFail` test after RevokeProof ✓
- Apache 2.0 license ✓
- No deprecated `daml-assistant`, `@daml/ledger`, or `daml start` ✓
- Funding breakdown across M1–M5 milestones ✓
