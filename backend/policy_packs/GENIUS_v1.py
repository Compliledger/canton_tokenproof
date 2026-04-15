"""
GENIUS_v1 — Guiding and Establishing National Innovation for US Stablecoins Act
Policy pack for payment stablecoin classification.

Controls are deterministic rules derived from the GENIUS Act framework.
This is NOT legal advice. ComplianceGuard enforces controls; it does not encode laws.
"""

POLICY_VERSION = "GENIUS_v1"
CLASSIFICATION = "payment_stablecoin"

CONTROLS = [
    "issuer_permitted_entity",
    "one_to_one_reserve_ratio",
    "monthly_reserve_certification",
    "redemption_support_available",
    "no_prohibited_activities",
]


def _check_issuer_permitted_entity(metadata: dict) -> dict:
    issuer_type = metadata.get("issuerType", "")
    permitted = issuer_type in (
        "insured_depository_institution",
        "federal_qualified_nonbank",
        "state_qualified_nonbank",
        "bank",
        "bank_trust",
    )
    return {
        "control": "issuer_permitted_entity",
        "passed": permitted,
        "reason": None if permitted else f"Issuer type '{issuer_type}' is not a GENIUS Act permitted entity",
    }


def _check_reserve_ratio(metadata: dict) -> dict:
    ratio = metadata.get("reserveRatio", 0.0)
    try:
        ratio = float(ratio)
    except (TypeError, ValueError):
        return {
            "control": "one_to_one_reserve_ratio",
            "passed": False,
            "reason": "reserveRatio is missing or not a number",
        }
    passed = ratio >= 1.0
    return {
        "control": "one_to_one_reserve_ratio",
        "passed": passed,
        "reason": None if passed else f"Reserve ratio {ratio:.4f} is below the required 1.0",
    }


def _check_monthly_certification(metadata: dict) -> dict:
    certified = bool(metadata.get("monthlyReserveCertification", False))
    return {
        "control": "monthly_reserve_certification",
        "passed": certified,
        "reason": None if certified else "monthlyReserveCertification is not confirmed",
    }


def _check_redemption_support(metadata: dict) -> dict:
    supported = bool(metadata.get("redemptionSupport", False))
    return {
        "control": "redemption_support_available",
        "passed": supported,
        "reason": None if supported else "redemptionSupport is not confirmed",
    }


def _check_no_prohibited_activities(metadata: dict) -> dict:
    prohibited = metadata.get("prohibitedActivities", [])
    clean = len(prohibited) == 0
    return {
        "control": "no_prohibited_activities",
        "passed": clean,
        "reason": None if clean else f"Prohibited activities flagged: {prohibited}",
    }


_CHECKERS = [
    _check_issuer_permitted_entity,
    _check_reserve_ratio,
    _check_monthly_certification,
    _check_redemption_support,
    _check_no_prohibited_activities,
]


def evaluate(metadata: dict) -> dict:
    """
    Run all GENIUS_v1 controls against the provided asset metadata.
    Worst-of aggregation: one failing control = non-compliant.
    Returns classification, policyVersion, controlResults, and overall passed flag.
    """
    results = [checker(metadata) for checker in _CHECKERS]
    all_passed = all(r["passed"] for r in results)
    return {
        "policyVersion": POLICY_VERSION,
        "classification": CLASSIFICATION if all_passed else "mixed_or_unclassified",
        "passed": all_passed,
        "controlResults": results,
    }
