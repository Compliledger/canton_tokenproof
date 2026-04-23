"""
canton_adapter.py — Canton Ledger API adapter.
Replaces algorand_adapter.py entirely. No Algorand code remains here.

Uses Canton's JSON Ledger API v2 for:
  bare dpm sandbox:    http://localhost:6864
  CN Quickstart LocalNet: http://localhost:7575
  (override via CANTON_LEDGER_API_URL environment variable)
  - ComplianceProof contract creation  (POST /v2/commands/submit-and-wait)
  - Active Contract Service queries    (POST /v2/state/active-contracts)
  - Party allocation                   (POST /v2/parties/allocate)

JWT party authentication replaces ALGO_SENDER_MNEMONIC.
No private key is stored in this backend.
"""

import os
import hashlib
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Default port matches bare 'dpm sandbox' (SDK 3.4.11 default: 6864).
# CN Quickstart LocalNet uses 7575. Always override via CANTON_LEDGER_API_URL.
LEDGER_API_BASE  = os.getenv("CANTON_LEDGER_API_URL", "http://localhost:6864")
EVALUATOR_JWT    = os.getenv("CANTON_EVALUATOR_JWT", "")
EVALUATOR_PARTY  = os.getenv("CANTON_EVALUATOR_PARTY", "TokenProofEvaluator::placeholder")
USER_ID          = os.getenv("CANTON_USER_ID", "participant_admin")


def _config_health_warnings() -> None:
    """Log loud warnings when the backend is clearly misconfigured.
    Called at module import. Does not raise so that unit tests can still run.
    """
    if "placeholder" in EVALUATOR_PARTY or "::" not in EVALUATOR_PARTY:
        logger.warning(
            "CANTON_EVALUATOR_PARTY is not a fully-qualified party ID (%s). "
            "All ledger calls will fail until this is set correctly.",
            EVALUATOR_PARTY,
        )
    if not os.getenv("TOKENPROOF_PACKAGE_ID"):
        logger.warning(
            "TOKENPROOF_PACKAGE_ID is not set. Template IDs will be sent in short form "
            "which is rejected by production Canton participants. Set it before anchoring proofs."
        )


_config_health_warnings()


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


def _parse_acs_response(body: str) -> list:
    """Parse a Canton v2 active-contracts response body into a list of entries.

    Accepts:
      - JSON array:         [ {...}, {...} ]
      - NDJSON:             {...}\n{...}\n
      - Envelope with result: { "result": [ ... ] }
      - Empty body
    Returns an empty list on malformed input so callers degrade to 'not found'.
    """
    body = (body or "").strip()
    if not body:
        return []
    # Try the simple JSON case first.
    try:
        doc = json.loads(body)
    except json.JSONDecodeError:
        # NDJSON fallback.
        out = []
        for line in body.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping malformed ACS line: %s", line[:120])
        return out
    if isinstance(doc, list):
        return doc
    if isinstance(doc, dict):
        # Some Canton builds wrap the result in { "result": [...] } or similar.
        for key in ("result", "activeContracts", "contractEntries"):
            val = doc.get(key)
            if isinstance(val, list):
                return val
    return []


def _deterministic_command_id(asset_id: str, issuer_party: str, policy_version: str, proof_hash: str) -> str:
    """Deterministic commandId so Canton command deduplication prevents double-anchoring.
    Same (asset, issuer, policy, proof hash) => same command => single on-ledger contract.
    """
    digest = hashlib.sha256(
        "|".join([asset_id, issuer_party, policy_version, proof_hash]).encode()
    ).hexdigest()[:32]
    return f"tokenproof-create-{digest}"


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
    Uses POST /v2/commands/submit-and-wait (JSON Ledger API v2).

    Idempotency: commandId is derived deterministically from the inputs so that a
    retry of the same request is deduplicated by the Canton command dedup window
    rather than creating a second ComplianceProof contract.

    Authorization: v2 uses userId only. The deprecated applicationId field is not
    sent. Ensure the Canton user has actAs rights for both issuer and evaluator.
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
        "actAs":     [issuer_party, EVALUATOR_PARTY],
        "readAs":    [],
        "commandId": _deterministic_command_id(asset_id, issuer_party, policy_version, proof_hash),
        "userId":    USER_ID,
    }

    url = f"{LEDGER_API_BASE}/v2/commands/submit-and-wait"
    response = httpx.post(url, json=payload, headers=_headers(), timeout=30)

    if response.status_code == 200:
        data = response.json()
        update_id = data.get("updateId", "")
        logger.info("ComplianceProof created: assetId=%s updateId=%s", asset_id, update_id)
        # submit-and-wait returns only updateId in v2; retrieve the contractId from ACS.
        # The transaction is committed at this point so the ACS query is consistent.
        newly_created = get_proof_by_asset(asset_id, issuer_party)
        contract_id = newly_created.get("contractId", "") if newly_created else ""
        return {"success": True, "updateId": update_id, "contractId": contract_id, "raw": data}

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

    # Query as the evaluator — co-signatory of all ComplianceProof contracts.
    # The evaluator JWT is used for auth; evaluator can see every proof it co-signed.
    # Filter results by assetId and issuer_party to return the correct contract.
    payload = {
        "filter": {
            "filtersByParty": {
                EVALUATOR_PARTY: {}
            }
        },
        "verbose":         True,
        "activeAtOffset":  str(offset),
        "userId":          os.getenv("CANTON_USER_ID", "participant_admin"),
    }

    url = f"{LEDGER_API_BASE}/v2/state/active-contracts"

    # v2 JSON body: some Canton releases return a JSON array, others return NDJSON.
    # Handle both so the backend works against any 3.4.x participant node.
    try:
        r = httpx.post(url, json=payload, headers=_headers(), timeout=30)
        if r.status_code != 200:
            logger.error("ACS query failed: status=%d body=%s", r.status_code, r.text[:200])
            return None
        entries = _parse_acs_response(r.text)
    except Exception as exc:
        logger.error("ACS request failed: %s", exc)
        return None

    for entry in entries:
        # Canton 3.4.x JSON shapes: entry.contractEntry.JsActiveContract.createdEvent
        # Some releases flatten to entry.createdEvent. Accept both.
        created = (
            entry.get("contractEntry", {})
                 .get("JsActiveContract", {})
                 .get("createdEvent")
            or entry.get("createdEvent")
            or {}
        )
        tid = created.get("templateId", "")
        if "ComplianceProof" not in tid:
            continue
        # Field name differs across 3.4 minor releases: createArgument vs createArguments.
        args = created.get("createArgument") or created.get("createArguments") or {}
        if args.get("assetId") == asset_id and args.get("issuer") == issuer_party:
            # Disclosure blob field also varies: createdEventBlob vs eventBlob.
            blob = (
                created.get("createdEventBlob")
                or created.get("eventBlob")
                or ""
            )
            return {
                "contractId":       created.get("contractId", ""),
                "assetId":          args.get("assetId"),
                "issuer":           args.get("issuer"),
                "classification":   args.get("classification"),
                "policyVersion":    args.get("policyVersion"),
                "decisionStatus":   args.get("decisionStatus", "Unknown"),
                "proofHash":        args.get("proofHash"),
                "timestamp":        args.get("timestamp"),
                # Included for disclosedContracts bundle — needed for multi-node Transfer
                "createdEventBlob": blob,
                "templateId":       created.get("templateId", ""),
            }

    return None


def get_proof_disclosure_bundle(asset_id: str, issuer_party: str) -> Optional[dict]:
    """
    Returns the disclosedContracts entry for a ComplianceProof contract.

    Canton's privacy model means a token owner's participant node may not hold the
    ComplianceProof contract (they are not a signatory or observer). When that owner
    submits a Transfer choice that calls fetch(proofCid), their node cannot resolve
    the contract unless it is provided as a disclosed contract in the API call.

    This function returns the bundle the transfer submitter must include under
    'disclosedContracts' in their POST /v2/commands/submit-and-wait payload:

        {
          "contractId": "<proof contract id>",
          "templateId": "<package>:Main.ComplianceProof:ComplianceProof",
          "createdEventBlob": "<base64 blob from ACS>"
        }

    The evaluator node has full visibility to the proof (co-signatory), so this
    backend can serve the bundle to any authorised caller.
    """
    proof = get_proof_by_asset(asset_id, issuer_party)
    if not proof:
        return None

    blob = proof.get("createdEventBlob", "")
    template_id = proof.get("templateId") or _compliance_proof_template()
    contract_id = proof.get("contractId", "")

    if not contract_id:
        logger.warning(
            "get_proof_disclosure_bundle: contractId empty for assetId=%s", asset_id
        )
        return None

    return {
        "contractId":       contract_id,
        "templateId":       template_id,
        "createdEventBlob": blob,
    }


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
