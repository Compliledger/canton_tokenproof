"""
canton_adapter.py — Canton Ledger API adapter.
Replaces algorand_adapter.py entirely. No Algorand code remains here.

Uses Canton's JSON Ledger API (port 7575) for:
  - ComplianceProof contract creation  (POST /v2/commands/submit-and-wait)
  - Active Contract Service queries    (POST /v2/state/active-contracts)
  - Party allocation                   (POST /v2/parties/allocate)

JWT party authentication replaces ALGO_SENDER_MNEMONIC.
No private key is stored in this backend.
"""

import os
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

LEDGER_API_BASE  = os.getenv("CANTON_LEDGER_API_URL", "http://localhost:7575")
EVALUATOR_JWT    = os.getenv("CANTON_EVALUATOR_JWT", "")
EVALUATOR_PARTY  = os.getenv("CANTON_EVALUATOR_PARTY", "TokenProofEvaluator::placeholder")
APP_ID           = "tokenproof-canton"

# Package hash is set after `dpm damlc inspect-dar --json .daml/dist/*.dar | jq .main_package_id`
# Required by Canton JSON Ledger API v2: format is <packageId>:Module.Name:TemplateName
_PROOF_PACKAGE_ID = os.getenv("TOKENPROOF_PACKAGE_ID", "")


def _template_id(module: str, entity: str) -> str:
    """Build a fully-qualified Canton v2 template ID.
    Falls back to short form during local sandbox development only.
    Set TOKENPROOF_PACKAGE_ID after dpm build for any live network.
    """
    if _PROOF_PACKAGE_ID:
        return f"{_PROOF_PACKAGE_ID}:{module}:{entity}"
    return f"{module}:{entity}"


COMPLIANCE_PROOF_TEMPLATE = _template_id("Main.ComplianceProof", "ComplianceProof")


def _headers() -> dict:
    jwt = os.getenv("CANTON_EVALUATOR_JWT", EVALUATOR_JWT)
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {jwt}",
    }


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
    regulator_field = (
        {"tag": "Some", "value": regulator_party}
        if regulator_party
        else {"tag": "None", "value": {}}
    )

    payload = {
        "commands": [
            {
                "CreateCommand": {
                    "templateId": COMPLIANCE_PROOF_TEMPLATE,
                    "createArguments": {
                        "assetId":        asset_id,
                        "issuer":         issuer_party,
                        "evaluator":      EVALUATOR_PARTY,
                        "regulator":      regulator_field,
                        "classification": classification,
                        "policyVersion":  policy_version,
                        "decisionStatus": {"tag": "Active"},
                        "proofHash":      proof_hash,
                        "timestamp":      timestamp,
                    },
                }
            }
        ],
        "actAs":        [issuer_party, EVALUATOR_PARTY],
        "readAs":       [],
        "applicationId": APP_ID,
        "commandId":    f"create-proof-{asset_id}-{policy_version}",
    }

    url = f"{LEDGER_API_BASE}/v2/commands/submit-and-wait"
    response = httpx.post(url, json=payload, headers=_headers(), timeout=30)

    if response.status_code == 200:
        data = response.json()
        try:
            events = (
                data.get("result", {})
                    .get("transaction", {})
                    .get("events", [])
            )
            contract_id = next(
                (e["created"]["contractId"]
                 for e in events if "created" in e),
                "",
            )
        except (KeyError, StopIteration, TypeError):
            contract_id = ""
        logger.info("ComplianceProof created: assetId=%s contractId=%s", asset_id, contract_id)
        return {"success": True, "contractId": contract_id, "raw": data}

    logger.error(
        "Failed to create ComplianceProof: status=%d body=%s",
        response.status_code, response.text,
    )
    return {"success": False, "error": response.text, "status": response.status_code}


def get_proof_by_asset(asset_id: str, issuer_party: str) -> Optional[dict]:
    """
    Query the Active Contract Service for a ComplianceProof by assetId.
    Uses POST /v2/state/active-contracts (JSON Ledger API).
    Returns the proof payload or None if not found.
    """
    payload = {
        "filter": {
            "filtersByParty": {
                issuer_party: {
                    "cumulative": [
                        {
                            "templateFilter": {
                                "templateId": COMPLIANCE_PROOF_TEMPLATE,
                                "includeCreatedEventBlob": False,
                            }
                        }
                    ]
                }
            }
        },
        "verbose": True,
    }

    url = f"{LEDGER_API_BASE}/v2/state/active-contracts"
    response = httpx.post(url, json=payload, headers=_headers(), timeout=30)

    if response.status_code != 200:
        logger.error("ACS query failed: status=%d", response.status_code)
        return None

    contracts = response.json().get("activeContracts", [])
    for contract in contracts:
        args = contract.get("createdEvent", {}).get("createArguments", {})
        if args.get("assetId") == asset_id:
            return {
                "contractId":     contract["createdEvent"]["contractId"],
                "assetId":        args.get("assetId"),
                "classification": args.get("classification"),
                "policyVersion":  args.get("policyVersion"),
                "decisionStatus": args.get("decisionStatus", {}).get("tag", "Unknown"),
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
