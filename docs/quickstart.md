# TokenProof — Quickstart

```mermaid
flowchart LR
    A[1. clone + dpm build] --> B[2. dpm sandbox]
    B --> C[3. start backend]
    C --> D[4. POST /evaluate]
    D --> E[5. GET /proof]
    E --> F[6. POST /verify]
    style F fill:#2a2,color:#fff
```

## Prerequisites

- Canton SDK 3.4.11 with DPM installed
- Python 3.11+
- Node 20+
- A Canton participant node (local sandbox or DevNet)

---

## 1. Build and test the DAML contracts

```bash
cd daml
dpm build
dpm test
```

Both commands must exit 0 before proceeding. The test suite covers the full proof lifecycle and the atomic transfer gate enforcement.

---

## 2. Run a local sandbox

```bash
cd daml
dpm sandbox
```

Bare `dpm sandbox` (SDK 3.4.11) starts the JSON Ledger API on **port 6864** (HTTP) and gRPC on port 6865.
CN Quickstart LocalNet uses port **7575** (HTTP) and port 6866 (gRPC).

Verify the sandbox is ready:

```bash
# bare dpm sandbox:
curl http://localhost:6864/v2/state/ledger-end
# CN Quickstart LocalNet:
curl http://localhost:7575/livez
```

---

## 3. Start the backend

```bash
cd backend
pip install -r requirements.txt

# Copy the example env file and fill in your party fingerprints
cp .env.example .env

# Or export directly:
export CANTON_LEDGER_API_URL=http://localhost:6864    # bare dpm sandbox
# export CANTON_LEDGER_API_URL=http://localhost:7575  # CN Quickstart LocalNet
export CANTON_EVALUATOR_JWT=
export CANTON_EVALUATOR_PARTY=<TokenProofEvaluator::fingerprint>
export TOKENPROOF_PACKAGE_ID=<package-id-from-dpm-build-output>

uvicorn api:app --reload --port 8000
```

API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## 4. Evaluate an asset and anchor a proof

```bash
curl -X POST http://localhost:8000/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "assetId": "STABLECOIN-DEMO-001",
    "issuerParty": "Issuer::fingerprint",
    "policyPack": "GENIUS_v1",
    "assetMetadata": {
      "issuerType": "federal_qualified_nonbank",
      "reserveRatio": 1.02,
      "monthlyReserveCertification": true,
      "redemptionSupport": true,
      "prohibitedActivities": []
    },
    "anchorOnLedger": true
  }'
```

---

## 5. Query proof status

```bash
curl "http://localhost:8000/proof/STABLECOIN-DEMO-001?issuer_party=Issuer::fingerprint"
```

---

## 6. Use the TypeScript SDK

```bash
cd sdk
npm install
npm run build
```

```typescript
import { createTokenProofClient } from "@tokenproof/canton-sdk";

const client = createTokenProofClient("http://localhost:8000");

const result = await client.evaluateAsset({
  assetId: "STABLECOIN-DEMO-001",
  issuerParty: "Issuer::fingerprint",
  policyPack: "GENIUS_v1",
  assetMetadata: {
    issuerType: "federal_qualified_nonbank",
    reserveRatio: 1.02,
    monthlyReserveCertification: true,
    redemptionSupport: true,
    prohibitedActivities: [],
  },
});

console.log(result.evaluation.classification);
// => "payment_stablecoin"

const proof = await client.getProofStatus("STABLECOIN-DEMO-001", "Issuer::fingerprint");
console.log(proof.decisionStatus);
// => "Active"
```

---

## 7. Run the DvP example

```bash
cd examples/cip0056-gated-transfer
dpm test
```

This runs two scripts: `atomicDvPDemo` and `dvpWorkflowDemo`. Both must exit with `ok`. The DvP demo exercises: proof anchored → transfer succeeds → proof revoked → transfer fails (`submitMustFail`).

---

## Deployment Path

| Stage | Command | Notes |
|-------|---------|-------|
| Local | `dpm sandbox` | Port 7575 (JSON API), resets on restart |
| DevNet | Upload DAR via gRPC, allocate parties | Shared Canton DevNet |
| TestNet | Validator node, JWT RS256 auth | Stable, xReserve bridge available |
| MainNet | Kubernetes validator or NaaS | Canton Global Synchronizer |

---

## 8. Multi-Node Token Transfers (Production)

In a real Canton deployment parties live on **separate participant nodes**. The
token owner's node does not hold the `ComplianceProof` contract (they are not a
signatory or observer). The owner must include the proof as a `disclosedContracts`
entry when submitting the `Transfer` choice.

### Step 1 — Get the disclosure bundle

```bash
curl "http://localhost:8000/proof/STABLECOIN-DEMO-001/disclosure?issuer_party=Issuer::fingerprint"
```

Response:
```json
{
  "contractId": "00abc123...",
  "templateId": "<packageId>:Main.ComplianceProof:ComplianceProof",
  "createdEventBlob": "<base64>"
}
```

### Step 2 — Include it in the Transfer command

```bash
curl -X POST http://localhost:7575/v2/commands/submit-and-wait \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $OWNER_JWT" \
  -d '{
    "commands": [{
      "ExerciseCommand": {
        "templateId": "<packageId>:TokenBond:TokenBond",
        "contractId": "<bond-contract-id>",
        "choice": "Transfer",
        "choiceArgument": {
          "newOwner": "<buyer-party>",
          "proofCid": "<contractId-from-step-1>"
        }
      }
    }],
    "actAs": ["<owner-party>"],
    "disclosedContracts": [
      {
        "contractId": "<contractId-from-step-1>",
        "templateId": "<templateId-from-step-1>",
        "createdEventBlob": "<createdEventBlob-from-step-1>"
      }
    ]
  }'
```

The Canton transaction interpreter resolves `proofCid` from the disclosed
contracts payload rather than from the owner's local ACS. The compliance gate
fires atomically inside the same two-phase commit transaction regardless of
which participant node the owner is hosted on.

---

## DISCLAIMER

TokenProof runs deterministic classification controls derived from the GENIUS Act, CLARITY Act, and SEC analysis frameworks. This is not legal advice. ComplianceGuard enforces controls; it does not encode laws. Consult qualified legal counsel before relying on any classification outcome for regulatory compliance decisions.
