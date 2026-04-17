"""
canton_adapter.py — Canton Ledger API adapter.
Replaces algorand_adapter.py entirely. No Algorand code remains here.

Uses Canton's JSON Ledger API v2 (port 6864) for:
  - ComplianceProof contract creation  (POST /v2/commands/submit-and-wait)
  - Active Contract Service queries    (POST /v2/state/active-contracts)
  - Party allocation                   (POST /v2/parties/allocate)

JWT party authentication replaces ALGO_SENDER_MNEMONIC.
No private key is stored in this backend.
"""

import os
import logging
import uuid
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

LEDGER_API_BASE  = os.getenv("CANTON_LEDGER_API_URL", "http://localhost:6864")
EVALUATOR_JWT    = os.getenv("CANTON_EVALUATOR_JWT", "")
EVALUATOR_PARTY  = os.getenv("CANTON_EVALUATOR_PARTY", "TokenProofEvaluator::placeholder")
APP_ID           = "tokenproof-canton"

# Package hash is set after `dpm damlc inspect-dar --json .daml/dist/*.dar | jq .main_package_id`
# Required by Canton JSON Ledger API v2: format is <packageId>:Module.Name:TemplateName
_PROOF_PACKAGE_ID = os.getenv("TOKENPROOF_PACKAGE_ID", "")


def _template_id(module: str, entity: str) -> str:
    """Build a fully-qualified Canton v2 template ID.
    Reads TOKENPROOF_PACKAGE_ID at call time so a value set after
    module import is always picked up (e.g. in tests or late env init).
    Falls back to short form for local sandbox development only.
    """
    pkg = os.getenv("TOKENPROOF_PACKAGE_ID", "")
    if pkg:
        return f"{pkg}:{module}:{entity}"
    return f"{module}:{entity}"


def _compliance_proof_template() -> str:
    return _template_id("Main.ComplianceProof", "ComplianceProof")


def _headers() -> dict:
    headers = {"Content-Type": "application/json"}
    jwt = os.getenv("CANTON_EVALUATOR_JWT", "")
    if jwt:
        headers["Authorization"] = f"Bearer {jwt}"
    return headers


def create_compliance_proof(
    asset_id: str,
    issuer_party: str,
    classification: str,
    policy_version: str,
    proof_hash: str,
    timestamp: str,
    regulator_party: Optional[str] = None,
) -> dict:
    """
    Submit a ComplianceProof creation command to the Canton node.
    Uses POST /v2/commands/submit-and-wait (JSON Ledger API).
    Returns the contract ID on success.
    """
    # Canton JSON Ledger API v2: Optional uses null for None, bare value for Some.
    regulator_field = regulator_party if regulator_party else None

    payload = {
        "commands": [
            {
                "CreateCommand": {
                    "templateId": _compliance_proof_template(),
                    "createArguments": {
                        "assetId":        asset_id,
                        "issuer":         issuer_party,
                        "evaluator":      EVALUATOR_PARTY,
                        "regulator":      regulator_field,
                        "classification": classification,
                        "policyVersion":  policy_version,
                        "decisionStatus": "Active",
                        "proofHash":      proof_hash,
                        "timestamp":      timestamp,
                    },
                }
            }
        ],
        "actAs":        [issuer_party, EVALUATOR_PARTY],
        "readAs":       [],
        "applicationId": APP_ID,
        "commandId":    f"create-proof-{asset_id}-{uuid.uuid4().hex[:12]}",
        "userId":       os.getenv("CANTON_USER_ID", "participant_admin"),
    }

    url = f"{LEDGER_API_BASE}/v2/commands/submit-and-wait"
    response = httpx.post(url, json=payload, headers=_headers(), timeout=30)

    if response.status_code == 200:
        data = response.json()
        update_id = data.get("updateId", "")
        logger.info("ComplianceProof created: assetId=%s updateId=%s", asset_id, update_id)
        return {"success": True, "updateId": update_id, "contractId": "", "raw": data}

    logger.error(
        "Failed to create ComplianceProof: status=%d body=%s",
        response.status_code, response.text,
    )
    return {"success": False, "error": response.text, "status": response.status_code}


def get_proof_by_asset(asset_id: str, issuer_party: str) -> Optional[dict]:
    """
    Query the Active Contract Service for a ComplianceProof by assetId.
    Uses POST /v2/state/active-contracts (Canton JSON Ledger API v2).
    Returns the proof payload or None if not found.
    """
    # v2 requires activeAtOffset — fetch current ledger end first.
    try:
        end_resp = httpx.get(f"{LEDGER_API_BASE}/v2/state/ledger-end", headers=_headers(), timeout=10)
        offset = end_resp.json().get("offset", "0")
    except Exception as exc:
        logger.error("Failed to fetch ledger-end: %s", exc)
        return None

    payload = {
        "filter": {
            "filtersByParty": {
                issuer_party: {}
            }
        },
        "verbose":         True,
        "activeAtOffset":  str(offset),
        "userId":          os.getenv("CANTON_USER_ID", "participant_admin"),
    }

    url = f"{LEDGER_API_BASE}/v2/state/active-contracts"

    # v2 returns a JSON array (not NDJSON) of objects with contractEntry.JsActiveContract.
    try:
        r = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        if r.status_code != 200:
            logger.error("ACS query failed: status=%d body=%s", r.status_code, r.text[:200])
            return None
        entries = r.json()
    except Exception as exc:
        logger.error("ACS request failed: %s", exc)
        return None

    for entry in entries:
        created = (
            entry.get("contractEntry", {})
                 .get("JsActiveContract", {})
                 .get("createdEvent", {})
        )
        tid = created.get("templateId", "")
        if "ComplianceProof" not in tid:
            continue
        args = created.get("createArgument", {})
        if args.get("assetId") == asset_id:
            return {
                "contractId":     created.get("contractId", ""),
                "assetId":        args.get("assetId"),
                "classification": args.get("classification"),
                "policyVersion":  args.get("policyVersion"),
                "decisionStatus": args.get("decisionStatus", "Unknown"),
                "proofHash":      args.get("proofHash"),
                "timestamp":      args.get("timestamp"),
            }

    return None


def allocate_party(display_name: str, party_id_hint: str) -> dict:
    """
    Allocate a new party on the Canton participant node.
    Uses POST /v2/parties/allocate — NOT the deprecated daml ledger allocate-parties.
    """
    payload = {
        "partyIdHint":        party_id_hint,
        "displayName":        display_name,
        "identityProviderId": "",
    }

    url = f"{LEDGER_API_BASE}/v2/parties/allocate"
    response = httpx.post(url, json=payload, headers=_headers(), timeout=30)

    if response.status_code == 200:
        data = response.json()
        party_id = data.get("partyDetails", {}).get("party", "")
        logger.info("Party allocated: displayName=%s partyId=%s", display_name, party_id)
        return {"success": True, "partyId": party_id}

    logger.error("Party allocation failed: status=%d body=%s", response.status_code, response.text)
    return {"success": False, "error": response.text}
