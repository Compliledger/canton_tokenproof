"""
Integration tests for the TokenProof Canton backend.

These tests require a running Canton sandbox:

    cd daml && dpm sandbox &
    cd backend && CANTON_EVALUATOR_PARTY=Alice::... uvicorn api:app &

Run with:
    pytest tests/test_integration.py -v --sandbox

Skipped automatically when the sandbox is not reachable.
"""

import os
import pytest
import httpx

LEDGER_URL  = os.getenv("CANTON_LEDGER_API_URL", "http://localhost:6864")
BACKEND_URL = os.getenv("TOKENPROOF_BACKEND_URL", "http://localhost:8000")


def _sandbox_reachable() -> bool:
    try:
        r = httpx.get(f"{LEDGER_URL}/livez", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _backend_reachable() -> bool:
    try:
        r = httpx.get(f"{BACKEND_URL}/health", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


sandbox_required = pytest.mark.skipif(
    not _sandbox_reachable() or not _backend_reachable(),
    reason="Canton sandbox (port 7575) and/or TokenProof backend (port 8000) not reachable",
)


# ---------------------------------------------------------------------------
# Canton Ledger API connectivity
# ---------------------------------------------------------------------------

@sandbox_required
def test_sandbox_liveness():
    r = httpx.get(f"{LEDGER_URL}/livez", timeout=5)
    assert r.status_code == 200


@sandbox_required
def test_ledger_end_returns_offset():
    r = httpx.get(f"{LEDGER_URL}/v2/state/ledger-end", timeout=5)
    assert r.status_code == 200
    data = r.json()
    assert "offset" in data, f"Expected 'offset' in ledger-end response: {data}"


# ---------------------------------------------------------------------------
# Backend health
# ---------------------------------------------------------------------------

@sandbox_required
def test_backend_health():
    r = httpx.get(f"{BACKEND_URL}/health", timeout=5)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


# ---------------------------------------------------------------------------
# Party allocation → evaluate → proof query lifecycle
# ---------------------------------------------------------------------------

@sandbox_required
def test_party_allocation():
    r = httpx.post(
        f"{BACKEND_URL}/parties/allocate",
        json={"displayName": "IntegTestIssuer", "partyIdHint": "IntegTestIssuer"},
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert "::" in body["partyId"], f"Expected qualified party ID, got: {body['partyId']}"


@sandbox_required
def test_evaluate_without_anchor():
    r = httpx.post(
        f"{BACKEND_URL}/evaluate",
        json={
            "assetId":       "INTEG-TEST-001",
            "issuerParty":   "IntegTestIssuer::placeholder",
            "policyPack":    "GENIUS_v1",
            "assetMetadata": {
                "issuerType":                  "federal_qualified_nonbank",
                "reserveRatio":                1.01,
                "monthlyReserveCertification": True,
                "redemptionSupport":           True,
                "prohibitedActivities":        [],
            },
            "anchorOnLedger": False,
        },
        timeout=15,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["evaluation"]["classification"] == "payment_stablecoin"
    assert body["evaluation"]["proofHash"].startswith("sha256:")
    assert body["ledger"] is None


@sandbox_required
def test_full_evaluate_anchor_and_query_lifecycle():
    issuer_party = os.getenv("INTEGRATION_ISSUER_PARTY")
    if not issuer_party:
        pytest.skip(
            "Set INTEGRATION_ISSUER_PARTY to a real Canton party ID to run ledger lifecycle test"
        )

    asset_id = "INTEG-LIFECYCLE-001"

    # Anchor the proof
    r = httpx.post(
        f"{BACKEND_URL}/evaluate",
        json={
            "assetId":       asset_id,
            "issuerParty":   issuer_party,
            "policyPack":    "GENIUS_v1",
            "assetMetadata": {
                "issuerType":                  "federal_qualified_nonbank",
                "reserveRatio":                1.05,
                "monthlyReserveCertification": True,
                "redemptionSupport":           True,
                "prohibitedActivities":        [],
            },
            "anchorOnLedger": True,
        },
        timeout=30,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ledger"]["success"] is True
    contract_id = body["ledger"]["contractId"]
    assert contract_id != "", "contractId must be populated after successful creation"

    # Query the proof from ACS
    r2 = httpx.get(
        f"{BACKEND_URL}/proof/{asset_id}",
        params={"issuer_party": issuer_party},
        timeout=15,
    )
    assert r2.status_code == 200, r2.text
    proof = r2.json()
    assert proof["decisionStatus"] == "Active"
    assert proof["contractId"] == contract_id

    # Fetch the disclosure bundle
    r3 = httpx.get(
        f"{BACKEND_URL}/proof/{asset_id}/disclosure",
        params={"issuer_party": issuer_party},
        timeout=15,
    )
    assert r3.status_code == 200, r3.text
    bundle = r3.json()
    assert bundle["contractId"] == contract_id
    assert "ComplianceProof" in bundle["templateId"]
    # createdEventBlob may be empty on some sandbox versions but contractId must be present


@sandbox_required
def test_proof_not_found_returns_404():
    r = httpx.get(
        f"{BACKEND_URL}/proof/NONEXISTENT-ASSET-XYZ",
        params={"issuer_party": "NoSuchParty::0000"},
        timeout=10,
    )
    assert r.status_code == 404
