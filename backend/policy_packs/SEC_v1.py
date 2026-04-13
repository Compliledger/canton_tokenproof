"""
SEC_CLASSIFICATION_v1 — SEC Digital Securities Analysis
Policy pack for investment contract / digital security classification.
Applies a Howey-derived framework adapted for tokenized assets.

Controls are deterministic rules. This is NOT legal advice.
ComplianceGuard enforces controls; it does not encode laws.
"""

POLICY_VERSION = "SEC_CLASSIFICATION_v1"


def _check_investment_contract_indicators(metadata: dict) -> dict:
    indicators = metadata.get("investmentContractIndicators", [])
    passed = len(indicators) > 0
    return {
        "control": "investment_contract_indicators_present",
        "passed": passed,
        "reason": None if passed else "No investment contract indicators found — asset may not qualify as a digital security",
    }


def _check_promoter_dependency(metadata: dict) -> dict:
    dependent = bool(metadata.get("promoterDependency", False))
    return {
        "control": "promoter_dependency",
        "passed": dependent,
        "reason": None if dependent else "promoterDependency is False — insufficient reliance on issuer efforts",
    }


def _check_profit_expectation(metadata: dict) -> dict:
    profit_expected = bool(metadata.get("profitExpectationFromOthers", False))
    return {
        "control": "profit_expectation_from_others",
        "passed": profit_expected,
        "reason": None if profit_expected else "profitExpectationFromOthers is False — Howey third prong not satisfied",
    }


def _check_decentralisation_level(metadata: dict) -> dict:
    level = metadata.get("decentralisationLevel", "high")
    passed = level in ("low", "medium")
    return {
        "control": "sufficient_centralisation_for_security",
        "passed": passed,
        "reason": None if passed else f"decentralisationLevel '{level}' suggests insufficient issuer control for security classification",
    }


def _check_public_disclosure(metadata: dict) -> dict:
    disclosed = bool(metadata.get("publicDisclosureSufficient", False))
    return {
        "control": "public_disclosure_sufficient",
        "passed": disclosed,
        "reason": None if disclosed else "publicDisclosureSufficient is not confirmed",
    }


_CHECKERS = [
    _check_investment_contract_indicators,
    _check_promoter_dependency,
    _check_profit_expectation,
    _check_decentralisation_level,
    _check_public_disclosure,
]


def evaluate(metadata: dict) -> dict:
    """
    Run all SEC_CLASSIFICATION_v1 controls against the provided asset metadata.
    All five controls must pass for a digital_security classification.
    Worst-of aggregation applies.
    """
    results = [checker(metadata) for checker in _CHECKERS]
    all_passed = all(r["passed"] for r in results)
    return {
        "policyVersion": POLICY_VERSION,
        "classification": "digital_security" if all_passed else "mixed_or_unclassified",
        "passed": all_passed,
        "controlResults": results,
    }
