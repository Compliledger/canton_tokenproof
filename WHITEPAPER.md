# TokenProof — Technical Whitepaper

**On-Ledger Compliance Enforcement for CIP-0056 Tokens on the Canton Network**

Version 0.1.0 | Apache 2.0 | Canton SDK 3.4.11

---

## Abstract

TokenProof is an open-source compliance primitive for the Canton Network. It
provides a reusable, on-ledger `ComplianceProof` contract that gates CIP-0056
token transfers and minting operations inside the **same Canton two-phase commit
transaction** as the asset movement. A Python classification engine evaluates
asset metadata against deterministic policy packs derived from the GENIUS Act,
CLARITY Act, and SEC classification frameworks. The resulting proof — including
a SHA-256 hash of the full evaluation snapshot — is anchored on the Canton ledger
as an immutable, party-scoped record. Compliance enforcement is atomic: if the
proof is Suspended or Revoked, the transfer transaction fails in its entirety.
No partial execution, no race condition, no after-the-fact remediation.

---

## 1. Problem Statement

### 1.1 The Pre-Transfer Race Condition

Existing blockchain compliance systems perform compliance checks *before*
submitting the transfer transaction. The sequence is:

```
[check compliance] → [wait] → [submit transfer]
                         ↑
                 state can change here
```

Between the check and the submission, the compliance status can change (issuer
suspended by regulator, reserve attestation lapsed). The transfer commits even
though the issuer is no longer compliant at settlement time.

### 1.2 The Canton Solution

Canton's two-phase commit protocol provides atomicity across all actions in a
transaction tree. TokenProof places the compliance check *inside* the transfer
choice, so the check and the asset movement are a single indivisible unit:

```
submit Transfer → [fetch ComplianceProof] → [assert Active] → [move asset]
                         ↑                       ↑
                both inside the same Canton transaction
```

If either the fetch or the assert fails, the entire transaction is rejected.
No partial state change occurs.

---

## 2. Architecture

### 2.1 Four-Layer Design

```
┌─────────────────────────────────────────────────────┐
│  Layer 4: TypeScript SDK                             │
│  axios (M1–M3) → @c7/ledger gRPC (M4)               │
├─────────────────────────────────────────────────────┤
│  Layer 3: FastAPI Backend                            │
│  Classification engine + Canton adapter              │
│  POST /evaluate  GET /proof  GET /proof/disclosure   │
├─────────────────────────────────────────────────────┤
│  Layer 2: Canton JSON Ledger API v2 (port 7575)      │
│  submit-and-wait · active-contracts · parties        │
├─────────────────────────────────────────────────────┤
│  Layer 1: DAML Contracts on Canton Ledger            │
│  ComplianceProof · ComplianceGuard · Types           │
└─────────────────────────────────────────────────────┘
```

### 2.2 DAML Contract Architecture

#### `Types.daml` — Sealed sum types

```daml
data DecisionStatus = Active | Suspended | Revoked  deriving (Eq, Show)
data PolicyPack     = GENIUS_v1 | CLARITY_v1 | SEC_CLASSIFICATION_v1
data AssetBucket    = PaymentStablecoin | DigitalSecurity | ...
```

All three types are sealed, exhaustive, and derive `Eq` and `Show`. They form
the invariant boundary between the Python classification engine and the on-ledger
record.

#### `ComplianceProof.daml` — Core on-ledger record

```daml
template ComplianceProof
  with
    assetId        : Text
    issuer         : Party
    evaluator      : Party
    regulator      : Optional Party
    classification : Text
    policyVersion  : Text
    decisionStatus : DecisionStatus
    proofHash      : Text
    timestamp      : Time
  where
    signatory issuer, evaluator
    observer  regulator
    ensure
      assetId /= "" && proofHash /= "" && policyVersion /= ""
```

**Co-signatory design:** both `issuer` and `evaluator` must authorise every
proof creation and lifecycle transition. Neither party can act unilaterally.

**Canton 3.4 / Daml-LF 2.x:** global contract keys are not supported in this
version. Callers pass `ContractId ComplianceProof` explicitly to Transfer and
Mint choices. The `fetch` call on an archived contract fails atomically — this
provides equivalent safety without `fetchByKey`.

**Lifecycle choices:**

| Choice | Controller | State transition |
|---|---|---|
| `SuspendProof` | evaluator | Active → Suspended |
| `RevokeProof` | evaluator | Active/Suspended → Revoked |
| `ReEvaluate` | issuer, evaluator | Active/Suspended → Active (new proof) |

Revoked is terminal. A new `assetId` is required for re-issuance.

#### `ComplianceGuard.daml` — Interface for third-party tokens

```daml
interface ComplianceGuard where
  checkCompliance : ContractId ComplianceProof -> Update ()

template ComplianceGuardImpl
  with
    evaluator : Party
    issuer    : Party
  where
    signatory evaluator
    observer  issuer
    interface instance ComplianceGuard for ComplianceGuardImpl where
      checkCompliance proofCid = do
        proof <- fetch proofCid
        assertMsg
          ("Compliance gate: proof status is " <> show proof.decisionStatus)
          (proof.decisionStatus == Active)
```

Any CIP-0056 token can implement this interface to obtain atomic compliance
enforcement with a single `exercise guardCid CheckCompliance` call.

### 2.3 Multi-Node Integration Pattern

Canton's privacy model (Principle 1: parties see only what they have a stake in)
means the token `owner`'s participant node does **not** hold the `ComplianceProof`
contract. The `owner` is not a signatory or observer of the proof.

The standard Canton solution is **disclosed contracts**: the submitting party
includes the contract data in the Ledger API call, making it available to the
transaction interpreter without requiring it to be in the local ACS.

#### Integration flow

```
Token Owner                TokenProof Backend          Canton Ledger
     │                           │                          │
     │── GET /proof/{id}/        │                          │
     │   disclosure?issuer=...──►│                          │
     │                           │── ACS query (as eval.) ─►│
     │                           │◄─ {contractId, blob} ────│
     │◄── disclosure bundle ─────│                          │
     │                           │                          │
     │── POST /v2/commands/submit-and-wait ─────────────────►│
     │   commands: [Transfer choice]                         │
     │   disclosedContracts: [bundle from above]             │
     │                                                       │
     │                 Canton 2PC validates, commits ────────│
     │◄─────────────────────── updateId ────────────────────│
```

The `disclosedContracts` entry contains:
- `contractId` — the current active `ComplianceProof` contract ID
- `templateId` — fully qualified template ID with package hash
- `createdEventBlob` — base64-encoded Canton creation event blob

This is identical to the pattern used by the CIP-0056 Token Standard for
`TransferFactory` disclosures, making TokenProof architecturally consistent
with the canonical Canton token infrastructure.

---

## 3. Classification Engine

### 3.1 Deterministic Controls

The Python classification engine in `backend/engine.py` runs a deterministic
sequence of control checks against asset metadata. The outcome of each control
is binary (pass/fail) and deterministic — identical inputs always produce
identical outputs. There is no ML model, no probabilistic inference, no external
API call.

```python
def classify(asset_id, metadata, policy_pack, override_timestamp=None):
    evaluator_fn = REGISTRY[policy_pack]
    control_results = evaluator_fn(metadata)
    classification = _aggregate(control_results)
    proof_hash = _compute_proof_hash(
        asset_id, classification, policy_pack, control_results, timestamp
    )
    return {
        "classification": classification,
        "policyVersion":  policy_pack,
        "passed":         all(r["passed"] for r in control_results),
        "controlResults": control_results,
        "proofHash":      proof_hash,
        "timestamp":      timestamp,
    }
```

### 3.2 Proof Hash

The SHA-256 hash is computed over the canonical JSON of the full evaluation
snapshot:

```python
snapshot = json.dumps({
    "assetId":        asset_id,
    "classification": classification,
    "policyVersion":  policy_version,
    "controlResults": control_results,
    "timestamp":      canonical_timestamp,  # ISO-8601 UTC, microsecond precision
}, sort_keys=True)
return "sha256:" + hashlib.sha256(snapshot.encode()).hexdigest()
```

`sort_keys=True` and canonical timestamp normalisation ensure the hash is
identical across Python versions and environments. Any party holding the original
metadata can recompute the hash independently using `POST /verify`.

### 3.3 Worst-Of Aggregation

When multiple controls are evaluated, the classification is the most restrictive
outcome across all failing controls. If any control fails, the overall result
reflects the most restrictive bucket that applies.

### 3.4 Policy Packs

| Pack | Regulatory Framework | Controls |
|---|---|---|
| `GENIUS_v1` | GENIUS Act (stablecoin) | Issuer type, reserve ratio ≥ 1.0, monthly certification, redemption support, prohibited activities |
| `CLARITY_v1` | CLARITY Act (digital commodities) | Decentralisation threshold, utility function, governance concentration |
| `SEC_CLASSIFICATION_v1` | SEC Howey/Reves analysis | Investment of money, common enterprise, expectation of profit, third-party efforts |

Policy packs are registered in `backend/policy_packs/__init__.py` and can be
extended without modifying the classification engine or the DAML contracts.

---

## 4. Canton Privacy Model

### 4.1 Party Visibility Matrix

| Contract | Signatory | Observer |
|---|---|---|
| `ComplianceProof` | `issuer`, `evaluator` | `regulator` (Optional) |
| `ComplianceGuardImpl` | `evaluator` | `issuer` |
| `TokenBond` (example) | `issuer` | `owner`, `evaluator` |

The token `owner` is **not** a stakeholder of `ComplianceProof`. This is an
intentional design choice: compliance data is between the issuer and the
evaluator (and optionally the regulator). Token holders do not see the
underlying classification details.

The `disclosedContracts` pattern (Section 2.3) resolves the cross-node
visibility requirement without exposing compliance data to all token holders.

### 4.2 Regulator Observer Pattern

The `regulator : Optional Party` field grants a specific regulator party
read-only observer access on a per-proof basis. The regulator sees all
`create`, `archive`, `SuspendProof`, `RevokeProof`, and `ReEvaluate` events
on contracts where they are the named observer. Visibility is scoped — the
regulator cannot see proofs for other issuers.

---

## 5. Formal System Properties

| Property | Mechanism | Status |
|---|---|---|
| Atomic enforcement | `fetch + assertMsg` inside Transfer choice | Verified by `submitMustFail` Daml Script test |
| Immutability | Each lifecycle transition archives old contract, creates new | DAML contract model |
| Non-repudiation | Co-signatory design (issuer + evaluator) | DAML authorization model |
| Determinism | Pure Python controls, `sort_keys=True` JSON, ISO-8601 timestamps | Unit tests in `test_policy_packs.py` |
| Hash verifiability | `POST /verify` recomputes hash from metadata | Endpoint + unit test |
| Regulator visibility | `observer regulator` on ComplianceProof | DAML observer guarantee |
| Privacy | Proof not visible to token owner (not a stakeholder) | Canton privacy model |
| Multi-node transfers | `disclosedContracts` pattern via `/proof/{id}/disclosure` | Integration test |

---

## 6. Reference Examples

### 6.1 DvP Atomic Settlement (`examples/cip0056-gated-transfer/`)

The `DvPWorkflow.daml` example demonstrates an atomic Delivery-versus-Payment
settlement where both the asset transfer and the payment allocation happen in
a single Canton transaction. The `TokenBond.Transfer` choice calls
`fetch proofCid` and `assertMsg Active` before moving the bond, ensuring
the compliance gate fires atomically with the settlement.

### 6.2 GENIUS Act Gated Minting (`examples/stablecoin-genius-act/`)

The `StablecoinToken.daml` example gates the `Mint` choice on an active
`ComplianceProof` with `policyVersion = "GENIUS_v1"`. New tokens cannot be
minted if the issuer's reserve attestation is Suspended (e.g. monthly
certification lapsed) or Revoked.

---

## 7. API Reference

### 7.1 Backend REST Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/evaluate` | Classify asset metadata + anchor proof on Canton |
| `POST` | `/evaluate/multi` | Classify against all three policy packs |
| `GET` | `/proof/{assetId}` | Query live proof status from ACS |
| `GET` | `/proof/{assetId}/disclosure` | Return `disclosedContracts` bundle for Transfer |
| `POST` | `/verify` | Recompute hash and compare against on-ledger record |
| `POST` | `/parties/allocate` | Allocate a new Canton party |
| `GET` | `/health` | Liveness check |

### 7.2 Canton Ledger API Endpoints Used

| Method | Path | Port | Purpose |
|---|---|---|---|
| `POST` | `/v2/commands/submit-and-wait` | 7575 | Create ComplianceProof contract |
| `GET` | `/v2/state/ledger-end` | 7575 | Fetch current offset for ACS query |
| `POST` | `/v2/state/active-contracts` | 7575 | Query active ComplianceProof by evaluator |
| `POST` | `/v2/parties/allocate` | 7575 | Onboard issuer / regulator parties |

---

## 8. Milestone Roadmap

| Milestone | Deliverable | Acceptance Criteria |
|---|---|---|
| M1 | DAML contracts + CI | `dpm build --all` green, `dpm test` passes all scripts |
| M2 | Python backend + policy packs | `/evaluate`, `/proof`, `/verify` tested against sandbox |
| M3 | TypeScript SDK (axios) | SDK builds, `npm test` passes, DevNet deployment documented |
| M4 | `@c7/ledger` gRPC + event stream | Real-time lifecycle events via gRPC, SDK uses `@c7/ledger` |
| M5 | Documentation + co-marketing | Quickstart video, blog post, Canton Dev Fund report |

---

## 9. Security Considerations

- No private key is stored in the backend. JWT tokens are read from environment
  variables at runtime and never logged.
- `.gitignore` excludes `.env`, `.env.local`, and `*.env`.
- The `decisionStatus` field is set to `Active` only by the classification
  engine after all controls pass. It cannot be set to `Active` via the lifecycle
  choices (`SuspendProof`, `RevokeProof`, `ReEvaluate` each enforce state
  transition invariants with `assertMsg`).
- The `ensure` clause in `ComplianceProof` prevents creation of proofs with
  empty `assetId`, `proofHash`, or `policyVersion`.
- Co-signatory design means a compromised evaluator cannot issue or revoke
  proofs without the issuer's participation (and vice versa).

---

## 10. License and Attribution

Apache License 2.0. See `LICENSE`.

Built on:
- [Canton Network](https://canton.network) — Digital Asset
- [Daml](https://daml.com) — Digital Asset, Apache 2.0
- [CIP-0056](https://docs.dev.sync.global/app_dev/splice_daml_apis.html) — Canton Token Standard
- [GENIUS Act](https://www.congress.gov/bill/119th-congress/house-bill/394) — U.S. stablecoin legislation
- [FastAPI](https://fastapi.tiangolo.com) — Sebastián Ramírez, MIT

---

*This whitepaper describes a proof-of-concept implementation. Classification
controls are deterministic approximations of regulatory frameworks, not legal
opinions. Consult qualified legal counsel before relying on any classification
outcome for regulatory compliance decisions.*
