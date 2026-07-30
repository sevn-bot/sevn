"""Import probes for optional uv extras (onboarding live validate + skill setup).

Module: sevn.onboarding.uv_extra_probes
Depends: none

Exports:
    UV_EXTRA_IMPORT_PROBE — extra name to ``python -c`` import probe string.
"""

from __future__ import annotations

UV_EXTRA_IMPORT_PROBE: dict[str, str] = {
    "browser-cdp": "import websockets",
    "web-fetch": "import brotli",
    "web-extract": "import readability",
    "pdf": "import pypdf",
    "yt-dlp": "import yt_dlp",
    "job-ops": "import jobspy",
    "graphify": "import graphify",
    "code-review-graph": "import code_review_graph",
    "code-graph-rag": "import code_graph_rag",
    "bedrock": "import aiobotocore",
    "skillspector": "import skillspector",
}

__all__ = ["UV_EXTRA_IMPORT_PROBE"]
