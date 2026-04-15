"""
TokenProof FastAPI backend.
Exposes three REST endpoints consumed by the TypeScript SDK and React dashboard.

POST /evaluate      — run classification engine, anchor proof on Canton
GET  /proof/{assetId} — query live proof status from Active Contract Service
POST /verify        — recompute proof hash and compare against on-ledger record

DISCLAIMER: This service runs deterministic classification controls.
It does not provide legal advice. ComplianceGuard enforces controls;
it does not encode laws.
"""

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import engine
import canton_adapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TokenProof Canton Backend",
    description="Compliance classification and proof-anchoring service for the Canton Network.",
    version="0.1.0",
)


class EvaluateRequest(BaseModel):
    assetId:        str
    issuerParty:    str
    policyPack:     str
    assetMetadata:  dict
    regulatorParty: Optional[str] = None
    anchorOnLedger: bool = True


class VerifyRequest(BaseModel):
    assetId:      str
    issuerParty:  str
    proofHash:    str
    policyPack:   str
    assetMetadata: dict


@app.post("/evaluate")
def evaluate_asset(req: EvaluateRequest):
    """
    Run the classification engine against the provided metadata and policy pack.
    If anchorOnLedger is True (default), creates a ComplianceProof on the Canton node.
    Returns the classification result and, on success, the proof contract details.
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


@app.get("/proof/{asset_id}")
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


@app.post("/verify")
def verify_proof(req: VerifyRequest):
    """
    Recompute the proof hash from raw metadata and compare against the on-ledger record.
    Fetches the stored proof from ACS to obtain the original timestamp so the hash
    can be reproduced exactly. Returns verified=True when hashes match.
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
        "note": "Hashes match — proof is consistent with on-ledger record."
                if verified else "Hash mismatch may indicate metadata drift or a policy version change.",
    }


@app.post("/parties/allocate")
def allocate_party(display_name: str, party_id_hint: str):
    """
    Allocate a new party on the Canton participant node.
    Used for onboarding issuers and regulator observers.
    """
    result = canton_adapter.allocate_party(display_name, party_id_hint)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Party allocation failed"))
    return result
