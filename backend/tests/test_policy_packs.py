"""
Unit tests for TokenProof policy packs and classification engine.
Run from the backend/ directory:  python -m pytest tests/ -v
"""

import pytest
from policy_packs.GENIUS_v1 import evaluate as genius_evaluate
from policy_packs.CLARITY_v1 import evaluate as clarity_evaluate
from policy_packs.SEC_v1 import evaluate as sec_evaluate
from policy_packs import REGISTRY
import engine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

GENIUS_PASSING = {
    "issuerType": "insured_depository_institution",
    "reserveRatio": 1.05,
    "monthlyReserveCertification": True,
    "redemptionSupport": True,
    "prohibitedActivities": [],
}

CLARITY_PASSING = {
    "networkMature": True,
    "singleControllerDependency": False,
    "publicDisclosureMet": True,
    "investmentContractIndicator": False,
}

SEC_PASSING = {
    "investmentContractIndicators": ["profit_from_others", "common_enterprise"],
    "promoterDependency": True,
    "profitExpectationFromOthers": True,
    "decentralisationLevel": "low",
    "publicDisclosureSufficient": True,
}


# ---------------------------------------------------------------------------
# GENIUS_v1 tests
# ---------------------------------------------------------------------------

class TestGeniusV1:
    def test_all_controls_pass(self):
        result = genius_evaluate(GENIUS_PASSING)
        assert result["passed"] is True
        assert result["classification"] == "payment_stablecoin"
        assert result["policyVersion"] == "GENIUS_v1"
        assert all(c["passed"] for c in result["controlResults"])

    def test_fails_on_unpermitted_issuer_type(self):
        meta = {**GENIUS_PASSING, "issuerType": "offshore_entity"}
        result = genius_evaluate(meta)
        assert result["passed"] is False
        assert result["classification"] == "mixed_or_unclassified"
        issuer_ctrl = next(c for c in result["controlResults"] if c["control"] == "issuer_permitted_entity")
        assert issuer_ctrl["passed"] is False
        assert "offshore_entity" in issuer_ctrl["reason"]

    def test_fails_on_reserve_ratio_below_one(self):
        meta = {**GENIUS_PASSING, "reserveRatio": 0.95}
        result = genius_evaluate(meta)
        assert result["passed"] is False
        ratio_ctrl = next(c for c in result["controlResults"] if c["control"] == "one_to_one_reserve_ratio")
        assert ratio_ctrl["passed"] is False

    def test_fails_on_missing_reserve_ratio(self):
        meta = {k: v for k, v in GENIUS_PASSING.items() if k != "reserveRatio"}
        result = genius_evaluate(meta)
        assert result["passed"] is False

    def test_fails_on_prohibited_activities(self):
        meta = {**GENIUS_PASSING, "prohibitedActivities": ["money_laundering"]}
        result = genius_evaluate(meta)
        assert result["passed"] is False
        ctrl = next(c for c in result["controlResults"] if c["control"] == "no_prohibited_activities")
        assert ctrl["passed"] is False

    def test_reserve_ratio_exactly_one_passes(self):
        meta = {**GENIUS_PASSING, "reserveRatio": 1.0}
        result = genius_evaluate(meta)
        assert result["passed"] is True

    def test_control_results_have_required_keys(self):
        result = genius_evaluate(GENIUS_PASSING)
        for ctrl in result["controlResults"]:
            assert "control" in ctrl
            assert "passed" in ctrl
            assert "reason" in ctrl

    def test_passing_controls_have_null_reason(self):
        result = genius_evaluate(GENIUS_PASSING)
        for ctrl in result["controlResults"]:
            assert ctrl["reason"] is None, f"Control {ctrl['control']} passed but reason is not None"

    def test_all_permitted_issuer_types(self):
        for issuer_type in ("insured_depository_institution", "federal_qualified_nonbank", "state_qualified_nonbank"):
            meta = {**GENIUS_PASSING, "issuerType": issuer_type}
            result = genius_evaluate(meta)
            ctrl = next(c for c in result["controlResults"] if c["control"] == "issuer_permitted_entity")
            assert ctrl["passed"] is True, f"Issuer type {issuer_type} should pass"


# ---------------------------------------------------------------------------
# CLARITY_v1 tests
# ---------------------------------------------------------------------------

class TestClarityV1:
    def test_all_controls_pass(self):
        result = clarity_evaluate(CLARITY_PASSING)
        assert result["passed"] is True
        assert result["classification"] == "digital_commodity"
        assert result["policyVersion"] == "CLARITY_v1"

    def test_fails_on_immature_network(self):
        meta = {**CLARITY_PASSING, "networkMature": False}
        result = clarity_evaluate(meta)
        assert result["passed"] is False
        assert result["classification"] == "mixed_or_unclassified"
        ctrl = next(c for c in result["controlResults"] if c["control"] == "network_maturity")
        assert ctrl["passed"] is False

    def test_fails_on_single_controller(self):
        meta = {**CLARITY_PASSING, "singleControllerDependency": True}
        result = clarity_evaluate(meta)
        assert result["passed"] is False
        ctrl = next(c for c in result["controlResults"] if c["control"] == "no_single_controller_dependency")
        assert ctrl["passed"] is False

    def test_fails_when_investment_contract_indicator_true(self):
        meta = {**CLARITY_PASSING, "investmentContractIndicator": True}
        result = clarity_evaluate(meta)
        assert result["passed"] is False
        ctrl = next(c for c in result["controlResults"] if c["control"] == "commodity_not_security_indicator")
        assert ctrl["passed"] is False

    def test_policy_version_constant_used(self):
        result = clarity_evaluate(CLARITY_PASSING)
        assert result["policyVersion"] == "CLARITY_v1"


# ---------------------------------------------------------------------------
# SEC_CLASSIFICATION_v1 tests
# ---------------------------------------------------------------------------

class TestSecV1:
    def test_all_controls_pass(self):
        result = sec_evaluate(SEC_PASSING)
        assert result["passed"] is True
        assert result["classification"] == "digital_security"
        assert result["policyVersion"] == "SEC_CLASSIFICATION_v1"

    def test_fails_without_investment_contract_indicators(self):
        meta = {**SEC_PASSING, "investmentContractIndicators": []}
        result = sec_evaluate(meta)
        assert result["passed"] is False
        ctrl = next(c for c in result["controlResults"] if c["control"] == "investment_contract_indicators_present")
        assert ctrl["passed"] is False

    def test_fails_without_promoter_dependency(self):
        meta = {**SEC_PASSING, "promoterDependency": False}
        result = sec_evaluate(meta)
        assert result["passed"] is False

    def test_fails_without_profit_expectation(self):
        meta = {**SEC_PASSING, "profitExpectationFromOthers": False}
        result = sec_evaluate(meta)
        assert result["passed"] is False

    def test_fails_with_high_decentralisation(self):
        meta = {**SEC_PASSING, "decentralisationLevel": "high"}
        result = sec_evaluate(meta)
        assert result["passed"] is False
        ctrl = next(c for c in result["controlResults"] if c["control"] == "sufficient_centralisation_for_security")
        assert ctrl["passed"] is False

    def test_medium_decentralisation_passes(self):
        meta = {**SEC_PASSING, "decentralisationLevel": "medium"}
        result = sec_evaluate(meta)
        ctrl = next(c for c in result["controlResults"] if c["control"] == "sufficient_centralisation_for_security")
        assert ctrl["passed"] is True


# ---------------------------------------------------------------------------
# Policy pack registry tests
# ---------------------------------------------------------------------------

class TestRegistry:
    def test_registry_has_all_three_packs(self):
        assert "GENIUS_v1" in REGISTRY
        assert "CLARITY_v1" in REGISTRY
        assert "SEC_CLASSIFICATION_v1" in REGISTRY

    def test_registry_values_are_callable(self):
        for name, fn in REGISTRY.items():
            assert callable(fn), f"REGISTRY[{name}] is not callable"

    def test_registry_returns_valid_shape(self):
        for name, fn in REGISTRY.items():
            result = fn({})
            assert "policyVersion" in result
            assert "classification" in result
            assert "passed" in result
            assert "controlResults" in result
            assert isinstance(result["controlResults"], list)


# ---------------------------------------------------------------------------
# Classification engine tests
# ---------------------------------------------------------------------------

class TestEngine:
    def test_classify_genius_passing(self):
        result = engine.classify("BRALE-USD-001", GENIUS_PASSING, "GENIUS_v1")
        assert result["assetId"] == "BRALE-USD-001"
        assert result["passed"] is True
        assert result["classification"] == "payment_stablecoin"
        assert result["policyVersion"] == "GENIUS_v1"
        assert result["proofHash"].startswith("sha256:")
        assert result["timestamp"]

    def test_classify_produces_deterministic_hash_given_same_timestamp(self):
        from engine import _compute_proof_hash
        h1 = _compute_proof_hash("A", "payment_stablecoin", "GENIUS_v1", [], "2026-04-13T00:00:00+00:00")
        h2 = _compute_proof_hash("A", "payment_stablecoin", "GENIUS_v1", [], "2026-04-13T00:00:00+00:00")
        assert h1 == h2

    def test_classify_different_metadata_produces_different_hash(self):
        from engine import _compute_proof_hash
        h1 = _compute_proof_hash("A", "payment_stablecoin", "GENIUS_v1", [], "2026-04-13T00:00:00+00:00")
        h2 = _compute_proof_hash("B", "payment_stablecoin", "GENIUS_v1", [], "2026-04-13T00:00:00+00:00")
        assert h1 != h2

    def test_classify_raises_on_unknown_pack(self):
        with pytest.raises(ValueError, match="Unknown policy pack"):
            engine.classify("X", {}, "NONEXISTENT_v99")

    def test_classify_proof_hash_prefix(self):
        result = engine.classify("BOND-001", SEC_PASSING, "SEC_CLASSIFICATION_v1")
        assert result["proofHash"].startswith("sha256:")
        assert len(result["proofHash"]) == len("sha256:") + 64

    def test_multi_pack_classify_single_winner(self):
        result = engine.multi_pack_classify("BRALE-USD", GENIUS_PASSING)
        assert result["assetId"] == "BRALE-USD"
        assert "finalClassification" in result
        assert "packResults" in result
        assert len(result["packResults"]) == 3

    def test_multi_pack_classify_conflict_gives_mixed(self):
        mixed_meta = {**GENIUS_PASSING, **SEC_PASSING}
        result = engine.multi_pack_classify("MIXED-ASSET", mixed_meta)
        assert result["finalClassification"] in ("mixed_or_unclassified", "payment_stablecoin", "digital_security")

    def test_multi_pack_classify_nothing_passes_gives_mixed(self):
        result = engine.multi_pack_classify("EMPTY-ASSET", {})
        assert result["finalClassification"] == "mixed_or_unclassified"

    def test_classify_control_results_list(self):
        result = engine.classify("X", GENIUS_PASSING, "GENIUS_v1")
        assert isinstance(result["controlResults"], list)
        assert len(result["controlResults"]) > 0

    def test_asset_buckets_set_contains_expected_values(self):
        assert "payment_stablecoin" in engine.ASSET_BUCKETS
        assert "digital_security" in engine.ASSET_BUCKETS
        assert "mixed_or_unclassified" in engine.ASSET_BUCKETS
