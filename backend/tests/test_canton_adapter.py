"""
Unit tests for canton_adapter helpers.

These tests do not require a live Canton node. They cover the pure
transformation helpers: ACS response parsing, deterministic commandId,
and template ID construction.
"""

import json

import canton_adapter


def test_deterministic_command_id_is_stable():
    cid_1 = canton_adapter._deterministic_command_id(
        "ASSET-1", "Issuer::abc", "GENIUS_v1", "sha256:hash1"
    )
    cid_2 = canton_adapter._deterministic_command_id(
        "ASSET-1", "Issuer::abc", "GENIUS_v1", "sha256:hash1"
    )
    assert cid_1 == cid_2
    assert cid_1.startswith("tokenproof-create-")


def test_deterministic_command_id_differs_on_input():
    cid_a = canton_adapter._deterministic_command_id("A", "I::1", "P", "h")
    cid_b = canton_adapter._deterministic_command_id("B", "I::1", "P", "h")
    cid_c = canton_adapter._deterministic_command_id("A", "I::2", "P", "h")
    cid_d = canton_adapter._deterministic_command_id("A", "I::1", "P", "h2")
    assert len({cid_a, cid_b, cid_c, cid_d}) == 4


def test_parse_acs_response_empty():
    assert canton_adapter._parse_acs_response("") == []
    assert canton_adapter._parse_acs_response("   ") == []


def test_parse_acs_response_json_array():
    body = json.dumps([{"contractEntry": {}}, {"contractEntry": {}}])
    out = canton_adapter._parse_acs_response(body)
    assert isinstance(out, list)
    assert len(out) == 2


def test_parse_acs_response_ndjson():
    body = "\n".join([
        json.dumps({"contractEntry": {"id": 1}}),
        json.dumps({"contractEntry": {"id": 2}}),
    ])
    out = canton_adapter._parse_acs_response(body)
    assert len(out) == 2
    assert out[0]["contractEntry"]["id"] == 1


def test_parse_acs_response_envelope():
    body = json.dumps({"result": [{"contractEntry": {}}]})
    out = canton_adapter._parse_acs_response(body)
    assert len(out) == 1


def test_parse_acs_response_ndjson_with_malformed_line():
    body = json.dumps({"contractEntry": {}}) + "\nthis-is-not-json\n" + json.dumps({"contractEntry": {}})
    out = canton_adapter._parse_acs_response(body)
    # Malformed line is skipped, not fatal.
    assert len(out) == 2


def test_template_id_uses_package_id_when_set(monkeypatch):
    monkeypatch.setenv("TOKENPROOF_PACKAGE_ID", "0123abc")
    tid = canton_adapter._template_id("Main.ComplianceProof", "ComplianceProof")
    assert tid == "0123abc:Main.ComplianceProof:ComplianceProof"


def test_template_id_falls_back_without_package_id(monkeypatch):
    monkeypatch.delenv("TOKENPROOF_PACKAGE_ID", raising=False)
    tid = canton_adapter._template_id("Main.ComplianceProof", "ComplianceProof")
    assert tid == "Main.ComplianceProof:ComplianceProof"
