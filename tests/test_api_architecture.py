from __future__ import annotations

import asyncio
import json

from omni_agent import api


def test_architecture_manifest_endpoint_shape() -> None:
    response = asyncio.run(api.architecture_manifest())
    payload = json.loads(response.body)

    assert "architecture" in payload
    assert "runtime" in payload
    assert payload["architecture"]["flow"]
    assert payload["runtime"]["request_harness"]["persistence"] == "SessionStore"
