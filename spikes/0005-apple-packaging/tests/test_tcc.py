"""TCC attribution. Green after W3. Live: the operator runs it by hand."""

from __future__ import annotations

import pytest

from support import (
    APP_DISPLAY_NAME,
    SPIKE_ROOT,
    as_dict,
    assert_tcc_paths,
    helper_output,
    load_json_object,
    parse_preflight,
    require_app,
)


@pytest.mark.live
@pytest.mark.xfail(reason="green after W3: TCC prompt names SevnSpike", strict=False)
def test_helper_prompt_names_app() -> None:
    app = require_app()
    probed = helper_output(app, "--probe-tcc", timeout=60)
    screen_capture, accessibility = parse_preflight(probed.stdout)
    payload = load_json_object(SPIKE_ROOT / "results" / "tcc.json")
    assert payload.get("operator_confirm") == APP_DISPLAY_NAME
    preflight = as_dict(payload.get("preflight"), "preflight")
    assert preflight.get("screen_capture") is screen_capture
    assert preflight.get("accessibility") is accessibility
    assert_tcc_paths(payload, require_pass=True)
