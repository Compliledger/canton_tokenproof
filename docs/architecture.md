# TokenProof — Architecture Reference

## Four-Layer Design

TokenProof is composed of four layers. Each layer is independently replaceable and open-sourced under Apache 2.0.

| Layer | Technology | Purpose |
|-------|-----------|---------|
| DAML Contract Layer | DAML SDK 3.4 · dpm build | On-ledger proof contracts, party-scoped privacy |
| Classification Engine | Python 3.11 · FastAPI | Deterministic policy evaluation, 3 packs |
| Canton Ledger API Adapter | JSON/gRPC Ledger API | Command submission, ACS queries, party allocation |
| Developer Surface | TypeScript · React | SDK, dashboard, CIP-0103 integration |

---

## DAML Contract Architecture

### Templates

**`Main.ComplianceProof`**
The core on-ledger compliance record. Immutable after creation except through explicit lifecycle choices.

- `signatory`: `issuer` (asset issuer) + `evaluator` (TokenProof evaluator)
- `observer`: `regulator` (Optional Party — scoped read-only)
- `key`: `(assetId, evaluator)` — allows `fetchByKey` from Transfer choices
- `choices`: `SuspendProof` · `RevokeProof` · `ReEvaluate`

**`Main.EvaluationRequest`**
Request lifecycle tracking. Issuer creates; evaluator processes and closes.

- `signatory`: `issuer`
- `observer`: `evaluator`
- `choices`: `MarkEvaluated` · `ArchiveRequest`

### Interface

**`Main.ComplianceGuard`**
A DAML interface any CIP-0056 token can implement to add an atomic compliance precondition on its Transfer choice.

```daml
interface ComplianceGuard where
  viewtype ComplianceGuardView
  getComplianceStatus : Update DecisionStatus
```

The `getComplianceStatus` method runs `fetchByKey @ComplianceProof` inside the same Canton transaction as the asset movement. Atomicity is guaranteed by Canton's two-phase commit.

### DecisionStatus Lifecycle

```
Active ──► Suspended ──► Revoked (terminal)
  ▲              │
  └──────────────┘  (ReEvaluate creates new Active proof)
```

- **Active**: transfers permitted
- **Suspended**: transfers blocked, investigation in progress
- **Revoked**: transfers blocked permanently; issuer must redeploy with new `assetId`

---

## Canton Privacy Model

Canton sub-transaction privacy means each participant sees only the contracts where they are a signatory or observer.

| Party | Sees |
|-------|------|
| Issuer | Their own ComplianceProof, EvaluationRequest, token holdings |
| Evaluator | ComplianceProof they co-signed, proof lifecycle events |
| Regulator | ComplianceProof records where `regulator = Some regulatorParty` |
| Sync Domain | Encrypted routing metadata only — never payload contents |
| Other participants | Nothing — Canton sub-transaction privacy |

This model is structurally impossible on any public chain (Ethereum, Algorand).

---

## JSON Ledger API Endpoints Used

| Operation | Endpoint |
|-----------|---------|
| Create ComplianceProof | `POST /v2/commands/submit-and-wait` |
| Query proof by asset | `POST /v2/state/active-contracts` |
| Allocate party | `POST /v2/parties/allocate` |
| Stream proof events | gRPC Ledger API port 6866 |

**Not used**: deprecated `daml ledger upload-dar`, `daml ledger allocate-parties`, `@daml/ledger`.

---

## Classification Engine

### Policy Packs

| Pack | Controls | Output Classification |
|------|----------|----------------------|
| `GENIUS_v1` | issuer type · reserve ratio · certification · redemption · prohibited activities | `payment_stablecoin` |
| `CLARITY_v1` | network maturity · controller dependency · disclosure · commodity test | `digital_commodity` |
| `SEC_CLASSIFICATION_v1` | investment contract · promoter dependency · profit expectation · decentralisation · disclosure | `digital_security` |

### Worst-of Aggregation

One failing control → `mixed_or_unclassified`. No partial passes. Mirrors prudential regulatory logic.

### Proof Hash

`SHA-256(assetId + classification + policyVersion + controlResults + timestamp)`

Anchored in `ComplianceProof.proofHash`. Regulator can recompute independently via `POST /verify`.

---

## Repository Structure

```
canton_tokenproof/
├── daml/                          # PRIMARY DELIVERABLE — dpm build + dpm test
│   ├── daml.yaml
│   ├── Main/
│   │   ├── ComplianceProof.daml
│   │   ├── ComplianceGuard.daml
│   │   ├── Types.daml
│   │   └── EvaluationRequest.daml
│   └── Test/
│       ├── ComplianceProofTest.daml
│       └── TransferGateTest.daml
├── examples/
│   ├── cip0056-gated-transfer/
│   │   ├── TokenBond.daml
│   │   └── DvPWorkflow.daml
│   └── stablecoin-genius-act/
│       └── StablecoinToken.daml
├── backend/
│   ├── api.py
│   ├── engine.py
│   ├── canton_adapter.py
│   ├── requirements.txt
│   └── policy_packs/
│       ├── GENIUS_v1.py
│       ├── CLARITY_v1.py
│       └── SEC_v1.py
├── sdk/
│   ├── package.json
│   ├── tsconfig.json
│   └── src/index.ts
├── docs/
│   ├── architecture.md
│   └── quickstart.md
└── .github/workflows/ci.yml
```
