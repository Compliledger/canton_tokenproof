"""
TokenProof FastAPI backend.
Exposes REST endpoints consumed by the TypeScript SDK and React dashboard.

POST /evaluate                    — classify asset metadata + anchor proof on Canton
POST /evaluate/multi              — classify against all three policy packs at once
GET  /proof/{assetId}             — query live proof status from Active Contract Service
GET  /proof/{assetId}/disclosure  — return disclosedContracts bundle for multi-node Transfer
POST /verify                      — recompute proof hash and compare against on-ledger record
POST /parties/allocate            — allocate a new Canton party (issuer / regulator onboarding)
GET  /health                      — liveness check

DISCLAIMER: Deterministic classification controls only.
Not legal advice. ComplianceGuard enforces controls; it does not encode laws.
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import engine
import canton_adapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TokenProof Canton Backend",
    description=(
        "Compliance classification and on-ledger proof-anchoring service "
        "for the Canton Network. Apache 2.0."
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class EvaluateRequest(BaseModel):
    assetId:        str = Field(..., description="CIP-0056 token identifier")
    issuerParty:    str = Field(..., description="Fully-qualified Canton party ID of the asset issuer")
    policyPack:     str = Field(..., description="Policy pack name: GENIUS_v1 | CLARITY_v1 | SEC_CLASSIFICATION_v1")
    assetMetadata:  Dict[str, Any] = Field(..., description="Asset metadata evaluated against the policy pack controls")
    regulatorParty: Optional[str] = Field(None, description="Optional Canton party ID granted read-only observer access")
    anchorOnLedger: bool = Field(True, description="If true, creates a ComplianceProof contract on the Canton node")


class VerifyRequest(BaseModel):
    assetId:       str = Field(..., description="CIP-0056 token identifier")
    issuerParty:   str = Field(..., description="Fully-qualified Canton party ID of the asset issuer")
    proofHash:     str = Field(..., description="SHA-256 proof hash to verify against on-ledger record")
    policyPack:    str = Field(..., description="Policy pack used when the proof was originally created")
    assetMetadata: Dict[str, Any] = Field(..., description="Original asset metadata used in evaluation")


class AllocatePartyRequest(BaseModel):
    displayName:   str = Field(..., description="Human-readable party display name")
    partyIdHint:   str = Field(..., description="Hint for the party identifier (used in fingerprint generation)")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class ControlResult(BaseModel):
    control: str
    passed:  bool
    reason:  Optional[str]


class EvaluationResult(BaseModel):
    assetId:        str
    classification: str
    policyVersion:  str
    passed:         bool
    controlResults: List[ControlResult]
    proofHash:      str
    timestamp:      str


class LedgerResult(BaseModel):
    success:    bool
    updateId:   Optional[str] = None
    contractId: Optional[str] = None
    error:      Optional[str] = None


class EvaluateResponse(BaseModel):
    evaluation: EvaluationResult
    ledger:     Optional[LedgerResult]


class ProofStatusResponse(BaseModel):
    contractId:     str
    assetId:        str
    classification: str
    policyVersion:  str
    decisionStatus: str
    proofHash:      str
    timestamp:      str


class VerifyResponse(BaseModel):
    assetId:        str
    verified:       bool
    onLedgerHash:   str
    recomputedHash: str
    note:           str


class AllocatePartyResponse(BaseModel):
    success: bool
    partyId: Optional[str] = None
    error:   Optional[str] = None


class HealthResponse(BaseModel):
    status:  str
    version: str


class ProofDisclosureResponse(BaseModel):
    contractId:       str
    templateId:       str
    createdEventBlob: str = Field(
        "",
        description=(
            "Base64-encoded Canton createdEventBlob. Include as disclosedContracts "
            "in POST /v2/commands/submit-and-wait when submitting a Transfer choice "
            "from a node that is not a ComplianceProof stakeholder."
        ),
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse, tags=["ops"])
def health():
    """Liveness check. Returns service version."""
    return {"status": "ok", "version": app.version}


@app.post("/evaluate", response_model=EvaluateResponse, tags=["compliance"])
def evaluate_asset(req: EvaluateRequest):
    """
    Run the classification engine against the provided metadata and policy pack.
    If anchorOnLedger is True (default), creates a ComplianceProof on the Canton node.
    """
    try:
        result = engine.classify(req.assetId, req.assetMetadata, req.policyPack)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not req.anchorOnLedger:
        return {"evaluation": result, "ledger": None}

    ledger_result = canton_adapter.create_compliance_proof(
        asset_id        = req.assetId,
        issuer_party    = req.issuerParty,
        classification  = result["classification"],
        policy_version  = result["policyVersion"],
        proof_hash      = result["proofHash"],
        timestamp       = result["timestamp"],
        regulator_party = req.regulatorParty,
    )

    return {"evaluation": result, "ledger": ledger_result}


@app.post("/evaluate/multi", tags=["compliance"])
def evaluate_multi(req: EvaluateRequest):
    """
    Run all three policy packs (GENIUS_v1, CLARITY_v1, SEC_CLASSIFICATION_v1)
    and return aggregated results. Useful for assets that may span multiple
    regulatory frameworks. Does not anchor — use /evaluate for anchoring.
    """
    try:
        result = engine.multi_pack_classify(req.assetId, req.assetMetadata)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.get("/proof/{asset_id}", response_model=ProofStatusResponse, tags=["compliance"])
def get_proof(asset_id: str, issuer_party: str):
    """
    Query the Active Contract Service for the current ComplianceProof status.
    Proof status is never cached — always read live from the Canton node.
    """
    proof = canton_adapter.get_proof_by_asset(asset_id, issuer_party)
    if proof is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active ComplianceProof found for assetId={asset_id}",
        )
    return proof


@app.post("/verify", response_model=VerifyResponse, tags=["compliance"])
def verify_proof(req: VerifyRequest):
    """
    Recompute the proof hash from raw metadata and compare against the on-ledger record.
    Fetches the stored proof from ACS to obtain the original timestamp — ensuring the
    hash is reproduced exactly as it was when anchored. Returns verified=true on match.
    """
    on_ledger_proof = canton_adapter.get_proof_by_asset(req.assetId, req.issuerParty)
    if on_ledger_proof is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active ComplianceProof found on ledger for assetId={req.assetId}",
        )

    stored_hash = on_ledger_proof.get("proofHash", req.proofHash)
    stored_timestamp = on_ledger_proof.get("timestamp")

    try:
        recomputed = engine.classify(
            req.assetId,
            req.assetMetadata,
            req.policyPack,
            override_timestamp=stored_timestamp,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    recomputed_hash = recomputed["proofHash"]
    verified = recomputed_hash == stored_hash

    return {
        "assetId":        req.assetId,
        "verified":       verified,
        "onLedgerHash":   stored_hash,
        "recomputedHash": recomputed_hash,
        "note": (
            "Hashes match — proof is consistent with on-ledger record."
            if verified else
            "Hash mismatch — metadata or policy version may have drifted from the original evaluation."
        ),
    }


@app.get("/proof/{asset_id}/disclosure", response_model=ProofDisclosureResponse, tags=["compliance"])
def get_proof_disclosure(asset_id: str, issuer_party: str):
    """
    Return the disclosedContracts bundle for a ComplianceProof contract.

    Canton's privacy model means that a token owner on a different participant node
    may not hold the ComplianceProof contract (they are not a signatory or observer).
    When that owner submits a Transfer choice that calls fetch(proofCid) inside the
    same Canton transaction, their node cannot resolve the contract ID unless the
    contract data is included as a disclosedContracts entry in the API call.

    Usage — include the response in your Transfer submission:

        POST /v2/commands/submit-and-wait
        {
          "commands": [{"ExerciseCommand": { ... Transfer choice ... }}],
          "actAs": ["<owner-party>"],
          "disclosedContracts": [
            {
              "contractId": "<from this endpoint>",
              "templateId": "<from this endpoint>",
              "createdEventBlob": "<from this endpoint>"
            }
          ]
        }
    """
    bundle = canton_adapter.get_proof_disclosure_bundle(asset_id, issuer_party)
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail=f"No active ComplianceProof found for assetId={asset_id} issuer={issuer_party}",
        )
    return bundle


@app.post("/parties/allocate", response_model=AllocatePartyResponse, tags=["admin"])
def allocate_party(req: AllocatePartyRequest):
    """
    Allocate a new party on the Canton participant node.
    Used for onboarding issuers and regulator observers.
    Both display name and party ID hint are required in the request body.
    """
    result = canton_adapter.allocate_party(req.displayName, req.partyIdHint)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Party allocation failed"))
    return result
