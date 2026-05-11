from __future__ import annotations

from services.request_lifecycle import RequestLifecycle


def test_phase_payload_uses_expected_event_types() -> None:
    lifecycle = RequestLifecycle()

    prep = lifecycle.phase_payload("prep_context")
    assert prep["type"] == "phase"
    assert prep["phase"] == "prep_context"
    assert prep["transient"] is True

    compression = lifecycle.phase_payload("compression_start")
    assert compression["type"] == "compression_start"
    assert compression["phase"] == "compression_start"
    assert compression["transient"] is False


def test_architecture_signature_contains_reference_layers_and_routes() -> None:
    lifecycle = RequestLifecycle()

    signature = lifecycle.architecture_signature()

    assert signature["reference_style"] == "OBS agent + model + harness"
    assert [role["name"] for role in signature["harness"]["roles"]] == [
        "Planner",
        "Search",
        "Generator",
        "Runner",
        "Evaluator",
    ]
    assert len(signature["harness"]["layers"]) == 6
    assert any(layer["id"] == "session_store" for layer in signature["layers"])
    assert any(layer["id"] == "harness_engine" for layer in signature["layers"])
    assert any(route["mode"] == "agent" for route in signature["mode_routes"])
    assert any(route["mode"] == "create" for route in signature["mode_routes"])
    assert any("Unified Harness" in route["handler"] for route in signature["mode_routes"])
    assert "skill_index" in signature["prompt_sections"]
    assert any(item["key"] == "prep_model" for item in signature["phase_catalog"])
    assert any(item["key"] == "create" for item in signature["phase_catalog"])
