"""
CLARITY_v1 — Digital Asset Market Structure and Investor Protection Act
Policy pack for market structure classification (digital commodity vs digital security).

Controls are deterministic rules derived from the CLARITY Act framework.
This is NOT legal advice. ComplianceGuard enforces controls; it does not encode laws.
"""

POLICY_VERSION = "CLARITY_v1"


def _check_network_maturity(metadata: dict) -> dict:
    mature = bool(metadata.get("networkMature", False))
    return {
        "control": "network_maturity",
        "passed": mature,
        "reason": None if mature else "networkMature is not confirmed — insufficient decentralisation signals",
    }


def _check_control_dependency(metadata: dict) -> dict:
    has_controller = bool(metadata.get("singleControllerDependency", False))
    passed = not has_controller
    return {
        "control": "no_single_controller_dependency",
        "passed": passed,
        "reason": None if passed else "Asset has a single-controller dependency — commodity classification blocked",
    }


def _check_disclosure_requirements(metadata: dict) -> dict:
    disclosed = bool(metadata.get("publicDisclosureMet", False))
    return {
        "control": "disclosure_requirements_met",
        "passed": disclosed,
        "reason": None if disclosed else "publicDisclosureMet is not confirmed",
    }


def _check_commodity_vs_security(metadata: dict) -> dict:
    # Default to None so missing metadata yields 'unknown' rather than a silent
    # default-to-security bias. Only an explicit False passes this control.
    indicator = metadata.get("investmentContractIndicator")
    if indicator is None:
        return {
            "control": "commodity_not_security_indicator",
            "passed": False,
            "reason": "investmentContractIndicator is missing — cannot classify as commodity without explicit determination",
        }
    passed = not bool(indicator)
    return {
        "control": "commodity_not_security_indicator",
        "passed": passed,
        "reason": None if passed else "investmentContractIndicator is True — asset is likely a security, not a commodity",
    }


_CHECKERS = [
    _check_network_maturity,
    _check_control_dependency,
    _check_disclosure_requirements,
    _check_commodity_vs_security,
]

_CLASSIFICATION_MAP = {
    True: "digital_commodity",
    False: "mixed_or_unclassified",
}


def evaluate(metadata: dict) -> dict:
    """
    Run all CLARITY_v1 controls against the provided asset metadata.
    Worst-of aggregation: one failing control = non-compliant result.
    """
    results = [checker(metadata) for checker in _CHECKERS]
    all_passed = all(r["passed"] for r in results)
    return {
        "policyVersion": POLICY_VERSION,
        "classification": _CLASSIFICATION_MAP[all_passed],
        "passed": all_passed,
        "controlResults": results,
    }
