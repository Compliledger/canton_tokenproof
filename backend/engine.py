"""
TokenProof Classification Engine
Deterministic, blockchain-agnostic asset classification.
6 asset buckets · 3 policy packs · worst-of aggregation.

This engine does not store state. Every call is idempotent.
The Canton adapter (canton_adapter.py) is responsible for anchoring
the result as a ComplianceProof contract on the ledger.
"""

import hashlib
import json
from datetime import datetime, timezone

from policy_packs import REGISTRY

def _canonicalize_timestamp(timestamp: str) -> str:
    normalized = timestamp.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    dt_utc = dt.astimezone(timezone.utc)
    fraction = dt_utc.strftime("%f").rstrip("0")
    if fraction:
        return dt_utc.strftime("%Y-%m-%dT%H:%M:%S") + f".{fraction}Z"
    return dt_utc.strftime("%Y-%m-%dT%H:%M:%SZ")


ASSET_BUCKETS = {
    "payment_stablecoin",
    "digital_security",
    "digital_commodity",
    "digital_tool",
    "digital_collectible",
    "mixed_or_unclassified",
}


def _compute_proof_hash(asset_id: str, classification: str, policy_version: str,
                        control_results: list, timestamp: str) -> str:
    canonical_timestamp = _canonicalize_timestamp(timestamp)
    snapshot = json.dumps(
        {
            "assetId": asset_id,
            "classification": classification,
            "policyVersion": policy_version,
            "controlResults": control_results,
            "timestamp": canonical_timestamp,
        },
        sort_keys=True,
    )
    return "sha256:" + hashlib.sha256(snapshot.encode()).hexdigest()


def classify(asset_id: str, metadata: dict, policy_pack: str,
             override_timestamp: str = None) -> dict:
    """
    Run deterministic classification for the given asset metadata against
    the specified policy pack. Returns a full evaluation result including
    the proof hash ready for anchoring on Canton.

    Worst-of aggregation: one failing control returns mixed_or_unclassified.
    """
    if policy_pack not in REGISTRY:
        raise ValueError(
            f"Unknown policy pack '{policy_pack}'. "
            f"Valid options: {sorted(REGISTRY.keys())}"
        )

    evaluator_fn = REGISTRY[policy_pack]
    result = evaluator_fn(metadata)

    raw_timestamp = override_timestamp if override_timestamp else datetime.now(timezone.utc).isoformat()
    timestamp = _canonicalize_timestamp(raw_timestamp)
    proof_hash = _compute_proof_hash(
        asset_id,
        result["classification"],
        result["policyVersion"],
        result["controlResults"],
        timestamp,
    )

    return {
        "assetId": asset_id,
        "classification": result["classification"],
        "policyVersion": result["policyVersion"],
        "passed": result["passed"],
        "controlResults": result["controlResults"],
        "proofHash": proof_hash,
        "timestamp": timestamp,
    }


def multi_pack_classify(asset_id: str, metadata: dict) -> dict:
    """
    Run all three policy packs and aggregate results.
    Assigns the most specific classification bucket that passes,
    or mixed_or_unclassified if multiple packs produce conflicting results.
    """
    results = {}
    passing_buckets = []

    for pack_name in REGISTRY:
        result = classify(asset_id, metadata, pack_name)
        results[pack_name] = result
        if result["passed"]:
            passing_buckets.append(result["classification"])

    if len(passing_buckets) == 1:
        final_classification = passing_buckets[0]
    else:
        final_classification = "mixed_or_unclassified"

    return {
        "assetId": asset_id,
        "finalClassification": final_classification,
        "packResults": results,
    }
